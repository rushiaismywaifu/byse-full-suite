#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse.sx / Filemoon  Python 上傳小工具
支援 byse.sx 新域名 api.byse.sx 和舊域名 filemoonapi.com
官方文件: https://byse.sx/api-docs

功能:
- 本地檔案上傳 (自動取得上傳伺服器)
- 遠端 URL 拉取上傳
- 查詢帳號資訊、檔案資訊、編碼狀態
- 支援資料夾

用法範例見下方 README 或 --help
"""

import os
import sys
import json
import time
import argparse
import mimetypes
from pathlib import Path
from typing import List, Optional, Dict, Any

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
DEFAULT_PLAYER_BASE = "https://byse.sx/e/"  # 用於拼接播放頁，實際 embed domain 每個帳號不同

class ByseClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_NEW, legacy_fallback: bool = True, timeout: int = 30):
        if not api_key:
            raise ValueError("API Key 不能為空，請到 byse.sx 後台 Settings -> API 取得")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.legacy_base = DEFAULT_BASE_LEGACY.rstrip("/")
        self.legacy_fallback = legacy_fallback
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ByseUploader/1.0 Python"})

    def _build_url(self, path: str, params: dict, use_legacy: bool = False) -> str:
        base = self.legacy_base if use_legacy else self.base_url
        # 確保 path 不以 / 開頭重複
        path = path.lstrip("/")
        qs = "&".join([f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items() if v is not None])
        return f"{base}/{path}?{qs}" if qs else f"{base}/{path}"

    def _get(self, primary_path: str, fallback_paths: List[str] = None, extra_params: Dict[str, Any] = None) -> dict:
        """嘗試主路徑，失敗自動試 fallback 路徑（相容 byse 新舊 API）"""
        params = {"key": self.api_key}
        if extra_params:
            params.update(extra_params)

        paths_to_try = [primary_path] + (fallback_paths or [])
        
        last_err = None
        for i, p in enumerate(paths_to_try):
            use_legacy = False
            # 如果 path 屬於 legacy 域名格式，但我們現在用 new base，也要試
            # 策略：前兩次用 new base，之後用 legacy base
            if i >= 1 and self.legacy_fallback:
                # 第二輪開始同時試 legacy base
                url_new = self._build_url(p, params, use_legacy=False)
                url_legacy = self._build_url(p, params, use_legacy=True)
                for url in [url_new, url_legacy]:
                    try:
                        resp = self.session.get(url, timeout=self.timeout)
                        # byse 新前端在 404 時會回 HTML "Page not found – The requested page doesn't exist in the renewed frontend"
                        if "Page not found" in resp.text and "renewed frontend" in resp.text:
                            last_err = f"{url} => 前端 404，可能是舊端點"
                            continue
                        data = resp.json()
                        if data.get("status") in [200, 201] or data.get("msg") == "OK" or "result" in data:
                            return data
                        # Wrong Auth 要直接拋
                        if "Wrong Auth" in str(data):
                            raise Exception(f"API Key 錯誤: {data}")
                        # 如果是明確的 error，試下一個
                        last_err = data
                    except Exception as e:
                        last_err = e
                        continue
            else:
                url = self._build_url(p, params, use_legacy=False)
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    if "Page not found" in resp.text and "renewed frontend" in resp.text:
                        last_err = f"{url} => 前端 404"
                        continue
                    data = resp.json()
                    if data.get("msg") == "Wrong Auth":
                        raise Exception("Invalid API key，請檢查 byse.sx 後台的 API Key")
                    return data
                except Exception as e:
                    last_err = e
                    continue

        raise Exception(f"所有 API 端點嘗試失敗，最後錯誤: {last_err}")

    # ---------- 帳號 ----------
    def account_info(self) -> dict:
        return self._get("account/info", ["file/info"])

    def account_stats(self, last: int = 7) -> dict:
        return self._get("account/stats", [], {"last": last})

    def get_embed_domains(self) -> dict:
        # 這個端點在 api-docs 有提到：回傳 old_domain / new_domain
        try:
            return self._get("account/embed_domains", ["account/embed_domains", "file/embed_domains"])
        except Exception:
            # 舊版可能沒有，嘗試 filemoon 的類似接口
            return self._get("account/info")

    # ---------- 上傳伺服器 ----------
    def get_upload_server(self) -> str:
        data = self._get("upload/server", ["upload/server"])
        # 回傳格式: {"result": "https://s1.xxx/upload/01"}
        result = data.get("result")
        if not result:
            raise Exception(f"無法取得上傳伺服器: {data}")
        return result

    # ---------- 本地檔案上傳 ----------
    def upload_file(self, filepath: str, folder_id: Optional[int] = None) -> dict:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"檔案不存在: {filepath}")

        upload_url = self.get_upload_server()
        print(f"[+] 上傳伺服器: {upload_url}")
        print(f"[+] 準備上傳: {path.name} ({path.stat().st_size / 1024 / 1024:.2f} MB)")

        # 官方要求 POST 到 upload server，參數 key + file
        # 有些舊文件說要帶 fld_id，這裡一併支援
        data = {'key': self.api_key}
        if folder_id is not None:
            data['fld_id'] = str(folder_id)

        # 進度條處理：requests 不內建，簡單用檔案大小估
        # 若有 tqdm，我們手動包裝 ProgressFile
        # 重要: 使用 with 確保 file handle 一定被關閉, 避免 fd 洩漏
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
            mime = mimetypes.guess_type(str(path))[0] or 'video/mp4'
            if HAS_TQDM:
                file_size = path.stat().st_size
                with tqdm(total=file_size, unit='B', unit_scale=True, desc=path.name) as pbar, \
                     open(path, 'rb') as f:
                    files = {'file': (path.name, ProgressFile(f, pbar), mime)}
                    resp = self.session.post(upload_url, data=data, files=files, timeout=300)
            else:
                with open(path, 'rb') as f:
                    files = {'file': (path.name, f, mime)}
                    resp = self.session.post(upload_url, data=data, files=files, timeout=300)

            try:
                j = resp.json()
            except Exception:
                # 有時候上傳伺服器回 HTML，需要看文字
                raise Exception(f"上傳回應非 JSON: {resp.text[:500]}")

            print(f"[+] 上傳回應: {json.dumps(j, indent=2, ensure_ascii=False)}")
            return j

        except Exception as e:
            raise Exception(f"本地上傳失敗: {e}")

    # ---------- 遠端上傳 ----------
    def remote_upload(self, direct_link: str, folder_id: Optional[int] = None) -> dict:
        # 新版: upload/url  舊版: remote/add
        result = self._get("upload/url", ["remote/add"], {"url": direct_link, "fld_id": folder_id} if folder_id else {"url": direct_link})
        return result

    def remote_upload_status(self, file_code: str) -> dict:
        return self._get("upload/status", ["remote/status", "upload/url/status"], {"file_code": file_code, "file_code": file_code} if False else {"file_code": file_code})

    def remove_remote_upload(self, file_code: str) -> dict:
        return self._get("upload/remove", ["remote/remove"], {"file_code": file_code})

    # ---------- 檔案 ----------
    def file_info(self, file_code: str) -> dict:
        # file_code 可逗號分隔多個
        return self._get("file/info", ["file/info"], {"file_code": file_code})

    def file_list(self, fld_id: int = 0, title: str = None, per_page: int = 20, page: int = 1, public: int = None) -> dict:
        params = {"fld_id": fld_id, "per_page": per_page, "page": page}
        if title:
            params["title"] = title
        if public is not None:
            params["public"] = public
        return self._get("file/list", [], params)

    def clone_file(self, file_code: str, fld_id: int = None) -> dict:
        params = {"file_code": file_code}
        if fld_id is not None:
            params["fld_id"] = fld_id
        return self._get("file/clone", [], params)

    def set_folder(self, file_code: str, fld_id: int) -> dict:
        # 新版文件: file/set_folder 或 move
        return self._get("file/set_folder", ["file/move", "file/set_folder"], {"file_code": file_code, "fld_id": fld_id})

    # ---------- 資料夾 ----------
    def folder_list(self, fld_id: int = 0, files: int = 0) -> dict:
        return self._get("folder/list", ["folder/list"], {"fld_id": fld_id, "files": files})

    def create_folder(self, name: str, parent_id: int = 0) -> dict:
        params = {"name": name, "parent_id": parent_id}
        # 有些版本用 parent_id，有些用 fld_id，嘗試兼容
        try:
            return self._get("folder/create", [], params)
        except Exception:
            params = {"name": name, "parent_id": parent_id, "fld_id": parent_id}
            return self._get("folder/create", [], params)

    # ---------- 編碼 / 縮圖 ----------
    def encoding_list(self) -> dict:
        return self._get("encoding/list", ["encoding/list"])

    def encoding_status(self, file_code: str) -> dict:
        return self._get("encoding/status", [], {"file_code": file_code})

    def thumbnail(self, file_code: str) -> dict:
        return self._get("images/thumb", ["file/thumb", "thumbnail"], {"file_code": file_code})


def load_api_key(args_key: Optional[str]) -> str:
    # 優先順序: 命令行 > 環境變數 > 配置檔 > .env
    if args_key:
        return args_key
    if os.getenv("BYSE_API_KEY"):
        return os.getenv("BYSE_API_KEY")
    # 嘗試 ~/.byse/config.json
    cfg_path = Path.home() / ".byse" / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if data.get("api_key"):
                return data["api_key"]
        except Exception:
            pass
    # 嘗試當前目錄 .env 或 byse_key.txt
    for p in [Path(".env"), Path("byse_key.txt")]:
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            for line in txt.splitlines():
                if "BYSE_API_KEY" in line or "API_KEY" in line:
                    if "=" in line:
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
                if len(line.strip()) >= 10 and " " not in line.strip():
                    # 可能是純 key
                    if p.name == "byse_key.txt":
                        return line.strip()
    return ""

def format_file_result(result: dict, client: ByseClient):
    """把上傳回應美化，幫你拼出播放連結"""
    files = result.get("files") or []
    if not files and result.get("result"):
        # 遠端上傳只回 filecode
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
        # 嘗試取得 embed domain，使用者可在後台 Settings -> Custom Domains 查看
        print(f"     官方播放頁 (通用): https://byse.sx/e/{code}")
        print(f"     直鏈 (需 premium): https://byse.sx/d/{code}")
        # 如果有拿到自定義 domain，會更準
        try:
            domains = client.get_embed_domains()
            # 舊格式: result 裡有？
            if isinstance(domains, dict):
                # 有些帳號會回 old_domain / new_domain
                new_d = domains.get("new_domain") or domains.get("result", {}).get("new_domain") if isinstance(domains.get("result"), dict) else None
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
        """
    )
    parser.add_argument("--key", help="API Key (或設環境變數 BYSE_API_KEY)")
    parser.add_argument("-f", "--file", nargs="+", help="本地影片檔案路徑 (可多檔)")
    parser.add_argument("--url", nargs="+", help="遠端直鏈 URL (可多個，進行 remote upload)")
    parser.add_argument("--folder-id", type=int, default=None, help="上傳到指定資料夾 ID，預設 0 根目錄")
    parser.add_argument("--base", default=DEFAULT_BASE_NEW, help=f"API base，預設 {DEFAULT_BASE_NEW}，可改 {DEFAULT_BASE_LEGACY}")
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

    p_enc = subparsers.add_parser("encoding", help="查看編碼佇列")
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

    # 如果有子命令，優先處理
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
        print(json.dumps(client.encoding_status(args.filecode), indent=2, ensure_ascii=False))
        return
    if args.command == "remote-status":
        print(json.dumps(client.remote_upload_status(args.filecode), indent=2, ensure_ascii=False))
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
                # 自動輪詢狀態
                filecode = None
                if isinstance(res.get("result"), dict):
                    filecode = res["result"].get("filecode")
                elif isinstance(res.get("result"), str):
                    filecode = res["result"]
                if filecode:
                    print(f"    正在追蹤進度 filecode={filecode} ...")
                    for _ in range(12):  # 最多追 1 分鐘
                        time.sleep(5)
                        st = client.remote_upload_status(filecode)
                        print(f"    狀態: {json.dumps(st.get('result', st), ensure_ascii=False)}")
                        # 如果已完成，跳出
                        r = st.get("result", {})
                        if isinstance(r, dict) and r.get("status") in ["DONE", "finished", "OK"]:
                            break
            except Exception as e:
                print(f"❌ 遠端上傳 {u} 失敗: {e}")
            print("-" * 60)

    if not has_action:
        # 若沒指定檔案也沒子命令，預設顯示帳號資訊 + 使用提示
        print("[*] 未指定 --file 或 --url，顯示帳號資訊：")
        try:
            print(json.dumps(client.account_info(), indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"查詢失敗: {e}")
        print("\n請用 --help 查看用法。")

if __name__ == "__main__":
    main()
