#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse.sx / Filemoon  Python 上傳小工具 (輕量版 CLI wrapper)
支援 byse.sx 新域名 api.byse.sx 和舊域名 filemoonapi.com
官方文件: https://byse.sx/api-docs

功能:
- 本地檔案上傳 (自動取得上傳伺服器, 含進度條)
- 遠端 URL 拉取上傳
- 查詢帳號資訊、檔案資訊、編碼狀態
- 支援資料夾

注意: v2.1 起 ByseClient 改為 ByseSDK 的 thin wrapper, 不再重複實作 API 邏輯

用法範例見下方 README 或 --help
"""

import os
import sys
import json
import time
import argparse
import mimetypes
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("缺少 requests，請先安裝: pip install requests")
    sys.exit(1)

# 嘗試載入 tqdm 進度條，不存在則用簡易版
try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None

DEFAULT_BASE_NEW = "https://api.byse.sx"
DEFAULT_BASE_LEGACY = "https://filemoonapi.com/api"
DEFAULT_PLAYER_BASE = (
    "https://byse.sx/e/"  # 用於拼接播放頁，實際 embed domain 每個帳號不同
)

# 引入完整 SDK (避免重複實作)
try:
    # 嘗試從 package 載入
    from byse_full_suite.sdk import ByseSDK, ByseAPIError
except ImportError:
    # 嘗試作為腳本直接執行 (從專案根目錄)
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from byse_full_suite.sdk import ByseSDK, ByseAPIError
    except ImportError:
        # 最後嘗試同層目錄 (byse_full_suite 在旁邊)
        sys.path.insert(0, str(Path(__file__).parent / "byse_full_suite"))
        from sdk import ByseSDK, ByseAPIError


class ByseClient:
    """
    輕量上傳用戶端, 內部委派 ByseSDK
    保留舊 API 名稱以維持向後相容
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_NEW,
        legacy_fallback: bool = True,
        timeout: int = 30,
    ):
        if not api_key:
            raise ValueError("API Key 不能為空，請到 byse.sx 後台 Settings -> API 取得")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.legacy_fallback = legacy_fallback  # 保留選項, 但 SDK 已內建 fallback cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ByseUploader/2.1 Python"})
        # 委派給 SDK
        self._sdk = ByseSDK(api_key=api_key, base_url=base_url, timeout=timeout)

    # ---------- 帳號 ----------
    def account_info(self) -> dict:
        return self._sdk.account_info()

    def account_stats(self, last: int = 7) -> dict:
        return self._sdk.account_stats(last=last)

    def get_embed_domains(self) -> dict:
        try:
            return self._sdk.account_embed_domains()
        except ByseAPIError:
            return self._sdk.account_info()

    # ---------- 上傳伺服器 ----------
    def get_upload_server(self) -> str:
        return self._sdk.upload_server()

    # ---------- 本地檔案上傳 (保留進度條實作) ----------
    def upload_file(self, filepath: str, folder_id: Optional[int] = None) -> dict:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"檔案不存在: {filepath}")

        upload_url = self.get_upload_server()
        print(f"[+] 上傳伺服器: {upload_url}")
        print(f"[+] 準備上傳: {path.name} ({path.stat().st_size / 1024 / 1024:.2f} MB)")

        data = {"key": self.api_key}
        if folder_id is not None:
            data["fld_id"] = str(folder_id)

        # 進度條: 使用 with 確保 file handle 關閉, 避免 fd 洩漏
        class ProgressFile:
            def __init__(self, f, pbar):
                self.f = f
                self.pbar = pbar

            def read(self, size=-1):
                chunk = self.f.read(size)
                if chunk:
                    self.pbar.update(len(chunk))
                return chunk

            def __getattr__(self, attr):
                return getattr(self.f, attr)

        try:
            mime = mimetypes.guess_type(str(path))[0] or "video/mp4"
            if HAS_TQDM:
                file_size = path.stat().st_size
                with tqdm(
                    total=file_size, unit="B", unit_scale=True, desc=path.name
                ) as pbar, open(path, "rb") as f:
                    files = {"file": (path.name, ProgressFile(f, pbar), mime)}
                    resp = self.session.post(
                        upload_url, data=data, files=files, timeout=300
                    )
            else:
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, mime)}
                    resp = self.session.post(
                        upload_url, data=data, files=files, timeout=300
                    )

            try:
                j = resp.json()
            except Exception:
                raise Exception(f"上傳回應非 JSON: {resp.text[:500]}")

            print(f"[+] 上傳回應: {json.dumps(j, indent=2, ensure_ascii=False)}")
            return j

        except Exception as e:
            raise Exception(f"本地上傳失敗: {e}")

    # ---------- 遠端上傳 ----------
    def remote_upload(self, direct_link: str, folder_id: Optional[int] = None) -> dict:
        return self._sdk.remote_upload(direct_link, folder_id=folder_id)

    def remote_upload_status(self, file_code: str) -> dict:
        return self._sdk.remote_status(file_code)

    def remove_remote_upload(self, file_code: str) -> dict:
        return self._sdk.remote_remove(file_code)

    # ---------- 檔案 ----------
    def file_info(self, file_code: str) -> dict:
        return self._sdk.file_info(file_code)

    def file_list(
        self,
        fld_id: int = 0,
        title: str = None,
        per_page: int = 20,
        page: int = 1,
        public: int = None,
    ) -> dict:
        return self._sdk.file_list(
            fld_id=fld_id,
            title=title,
            per_page=per_page,
            page=page,
            public=public,
        )

    def clone_file(self, file_code: str, fld_id: int = None) -> dict:
        return self._sdk.file_clone(file_code, folder_id=fld_id)

    def set_folder(self, file_code: str, fld_id: int) -> dict:
        # byse 主流程是 file/edit 帶 fld_id, 直接走 SDK 的 file_edit
        return self._sdk.file_edit(file_code, folder_id=fld_id)

    # ---------- 資料夾 ----------
    def folder_list(self, fld_id: int = 0, files: int = 0) -> dict:
        return self._sdk.folder_list(fld_id=fld_id, include_files=files)

    def create_folder(self, name: str, parent_id: int = 0) -> dict:
        return self._sdk.folder_create(name=name, parent_id=parent_id)

    # ---------- 編碼 / 縮圖 ----------
    def encoding_list(self) -> dict:
        return self._sdk.encoding_list()

    def encoding_status(self, file_code: str) -> dict:
        return self._sdk.encoding_status(file_code)

    def thumbnail(self, file_code: str) -> dict:
        return self._sdk.thumb(file_code)


def load_api_key(args_key: Optional[str]) -> str:
    # 優先順序: 命令行 > 環境變數 > 配置檔 > .env
    if args_key:
        return args_key
    if os.getenv("BYSE_API_KEY"):
        return os.getenv("BYSE_API_KEY")
    cfg_path = Path.home() / ".byse" / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if data.get("api_key"):
                return data["api_key"]
        except Exception:
            pass
    for p in [Path(".env"), Path("byse_key.txt")]:
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            for line in txt.splitlines():
                if "BYSE_API_KEY" in line or "API_KEY" in line:
                    if "=" in line:
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
                if len(line.strip()) >= 10 and " " not in line.strip():
                    if p.name == "byse_key.txt":
                        return line.strip()
    return ""


def format_file_result(result: dict, client: ByseClient):
    """把上傳回應美化，幫你拼出播放連結"""
    files = result.get("files") or []
    if not files and result.get("result"):
        res = result.get("result")
        if isinstance(res, dict) and "filecode" in res:
            files = [res]
        elif isinstance(res, str):
            files = [{"filecode": res}]

    for f in files:
        code = f.get("filecode") or f.get("file_code") or f.get("code") or "UNKNOWN"
        name = f.get("filename") or f.get("name") or ""
        print(f"  -> filecode: {code}")
        if name:
            print(f"     檔名: {name}")
        print(f"     官方播放頁 (通用): https://byse.sx/e/{code}")
        print(f"     直鏈 (需 premium): https://byse.sx/d/{code}")
        try:
            domains = client.get_embed_domains()
            if isinstance(domains, dict):
                new_d = None
                if isinstance(domains.get("result"), dict):
                    new_d = domains.get("result", {}).get("new_domain")
                elif domains.get("new_domain"):
                    new_d = domains.get("new_domain")
                if new_d:
                    print(f"     自訂 embed: https://{new_d}/e/{code}")
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Byse.sx 上傳小工具 (相容 Filemoon) - Python",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
範例:
  # 查帳號
  python byse_uploader.py --key YOUR_API_KEY info

  # 上傳單檔
  python byse_uploader.py --key YOUR_KEY -f video.mp4

  # 上傳多檔到指定資料夾
  python byse_uploader.py --key YOUR_KEY -f a.mp4 b.mkv --folder-id 15

  # 遠端拉取
  python byse_uploader.py --key YOUR_KEY --url https://example.com/video.mp4

  # 查已上傳列表
  python byse_uploader.py --key YOUR_KEY list --per-page 10

  # 查檔案資訊
  python byse_uploader.py --key YOUR_KEY fileinfo abc123,def456

環境變數:
  BYSE_API_KEY  可避免每次輸入 --key
        """,
    )
    parser.add_argument("--key", help="API Key (或設環境變數 BYSE_API_KEY)")
    parser.add_argument("-f", "--file", nargs="+", help="本地影片檔案路徑 (可多檔)")
    parser.add_argument(
        "--url", nargs="+", help="遠端直鏈 URL (可多個，進行 remote upload)"
    )
    parser.add_argument(
        "--folder-id", type=int, default=None, help="上傳到指定資料夾 ID，預設 0 根目錄"
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE_NEW,
        help=f"API base，預設 {DEFAULT_BASE_NEW}，可改 {DEFAULT_BASE_LEGACY}",
    )
    parser.add_argument("--timeout", type=int, default=60, help="API timeout 秒數")

    subparsers = parser.add_subparsers(dest="command", help="額外指令")
    subparsers.add_parser("info", help="查詢帳號資訊")
    subparsers.add_parser("stats", help="查詢收益統計")
    subparsers.add_parser("domains", help="查詢 embed domain")
    p_list = subparsers.add_parser("list", help="列出檔案")
    p_list.add_argument("--per-page", type=int, default=20)
    p_list.add_argument("--page", type=int, default=1)
    p_list.add_argument("--title", type=str, default=None)

    p_finfo = subparsers.add_parser("fileinfo", help="查詢檔案資訊")
    p_finfo.add_argument("filecode", help="單個或逗號分隔多個 filecode")

    subparsers.add_parser("encoding", help="查看編碼佇列")
    p_enc_status = subparsers.add_parser("enc-status", help="查看單檔編碼狀態")
    p_enc_status.add_argument("filecode")

    p_status = subparsers.add_parser("remote-status", help="查遠端上傳進度")
    p_status.add_argument("filecode")

    args = parser.parse_args()

    api_key = load_api_key(args.key)
    if not api_key:
        print("❌ 未提供 API Key，請用 --key 或設 BYSE_API_KEY 環境變數")
        print("   取得方式: 登入 byse.sx -> 右上角 Settings -> API Key")
        sys.exit(1)

    client = ByseClient(api_key=api_key, base_url=args.base, timeout=args.timeout)

    # 子命令優先處理
    if args.command == "info":
        print(json.dumps(client.account_info(), indent=2, ensure_ascii=False))
        return
    if args.command == "stats":
        print(json.dumps(client.account_stats(), indent=2, ensure_ascii=False))
        return
    if args.command == "domains":
        print(json.dumps(client.get_embed_domains(), indent=2, ensure_ascii=False))
        return
    if args.command == "list":
        res = client.file_list(per_page=args.per_page, page=args.page, title=args.title)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return
    if args.command == "fileinfo":
        res = client.file_info(args.filecode)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return
    if args.command == "encoding":
        print(json.dumps(client.encoding_list(), indent=2, ensure_ascii=False))
        return
    if args.command == "enc-status":
        print(
            json.dumps(
                client.encoding_status(args.filecode), indent=2, ensure_ascii=False
            )
        )
        return
    if args.command == "remote-status":
        print(
            json.dumps(
                client.remote_upload_status(args.filecode), indent=2, ensure_ascii=False
            )
        )
        return

    # 預設行為: 上傳
    has_action = False

    if args.file:
        has_action = True
        for fp in args.file:
            try:
                res = client.upload_file(fp, folder_id=args.folder_id)
                format_file_result(res, client)
            except Exception as e:
                print(f"❌ {fp} 上傳失敗: {e}")
            print("-" * 60)
            time.sleep(1)

    if args.url:
        has_action = True
        for u in args.url:
            try:
                print(f"[+] 遠端上傳: {u}")
                res = client.remote_upload(u, folder_id=args.folder_id)
                print(json.dumps(res, indent=2, ensure_ascii=False))
                format_file_result(res, client)
                filecode = None
                if isinstance(res.get("result"), dict):
                    filecode = res["result"].get("filecode")
                elif isinstance(res.get("result"), str):
                    filecode = res["result"]
                if filecode:
                    print(f"    正在追蹤進度 filecode={filecode} ...")
                    for _ in range(12):
                        time.sleep(5)
                        st = client.remote_upload_status(filecode)
                        print(
                            f"    狀態: {json.dumps(st.get('result', st), ensure_ascii=False)}"
                        )
                        r = st.get("result", {})
                        if isinstance(r, dict) and r.get("status") in (
                            "DONE",
                            "finished",
                            "OK",
                        ):
                            break
            except Exception as e:
                print(f"❌ 遠端上傳 {u} 失敗: {e}")
            print("-" * 60)

    if not has_action:
        print("[*] 未指定 --file 或 --url，顯示帳號資訊：")
        try:
            print(json.dumps(client.account_info(), indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"查詢失敗: {e}")
        print("\n請用 --help 查看用法。")


if __name__ == "__main__":
    main()
