#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse Full Suite - 完整 CLI 管理程式
涵蓋 29+ 端點，互動式 TUI

用法:
  python cli.py --key YOUR_KEY
  或設 BYSE_API_KEY 環境變數
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Optional

# 引入 SDK
try:
    from sdk import ByseSDK, ByseAPIError
except ImportError:
    from byse_full_suite.sdk import ByseSDK, ByseAPIError
    # 兼容直接執行
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from sdk import ByseSDK, ByseAPIError

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None
    print("提示: pip install rich 可獲得更好體驗")

def load_key(cli_key: Optional[str]) -> str:
    if cli_key: return cli_key
    if os.getenv("BYSE_API_KEY"): return os.getenv("BYSE_API_KEY")
    cfg = Path.home() / ".byse" / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text())["api_key"]
        except: pass
    return ""

def print_json(data):
    if HAS_RICH:
        console.print_json(json.dumps(data, ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))

def print_table(title, rows, columns):
    if HAS_RICH:
        table = Table(title=title)
        for c in columns:
            table.add_column(c)
        for r in rows:
            table.add_row(*[str(r.get(c, "")) for c in columns])
        console.print(table)
    else:
        print(f"=== {title} ===")
        for r in rows:
            print(r)

def menu_account(sdk: ByseSDK):
    print("\n[帳號總覽]")
    try:
        info = sdk.account_info()
        print_json(info)
        result = info.get("result", {})
        if result:
            print(f"\nEmail: {result.get('email')} | 檔案數: {result.get('files_total')} | 餘額: ${result.get('balance')}")
    except Exception as e:
        print(f"錯誤: {e}")

    try:
        stats = sdk.account_stats(last=7)
        print("\n[近7天統計]")
        print_json(stats)
    except Exception as e:
        print(f"stats 錯誤: {e}")

    # embed domains 嘗試
    try:
        domains = sdk.account_embed_domains()
        print("\n[Embed Domains]")
        print_json(domains)
    except Exception as e:
        print(f"embed domains 不可用: {e} (請到網頁後台 Settings -> Custom Domains 查看)")

def menu_files(sdk: ByseSDK):
    while True:
        print("\n=== 檔案管理 ===")
        print("1. 列出檔案  2. 搜尋標題  3. 檔案詳情  4. 克隆  5. 編輯標題/公開度  6. 移動到資料夾  7. 縮圖/海報/預覽  8. 產生 Embed Code  9. 返回")
        choice = input("選項: ").strip()
        if choice == "1":
            try:
                fld = int(input("資料夾ID (0=根): ") or "0")
                per = int(input("每頁數量 (20): ") or "20")
                page = int(input("頁碼 (1): ") or "1")
                data = sdk.file_list(fld_id=fld, per_page=per, page=page)
                files = data.get("result", {}).get("files", []) if isinstance(data.get("result"), dict) else data.get("result", [])
                if isinstance(files, list):
                    rows = []
                    for f in files[:20]:
                        rows.append({
                            "file_code": f.get("file_code"),
                            "title": f.get("title")[:30],
                            "length": f.get("length"),
                            "views": f.get("views"),
                            "canplay": f.get("canplay")
                        })
                    print_table("檔案列表", rows, ["file_code","title","length","views","canplay"])
                    print_json(data)
                else:
                    print_json(data)
            except Exception as e:
                print(f"錯誤: {e}")

        elif choice == "2":
            title = input("搜尋標題關鍵字: ").strip()
            try:
                data = sdk.file_list(title=title, per_page=20)
                print_json(data)
            except Exception as e:
                print(e)

        elif choice == "3":
            code = input("filecode (可逗號分隔多個): ").strip()
            try:
                print_json(sdk.file_info(code))
            except Exception as e:
                print(e)

        elif choice == "4":
            code = input("要克隆的 filecode: ").strip()
            fld = input("目標資料夾ID (空白=根): ").strip()
            try:
                fld_id = int(fld) if fld else None
                print_json(sdk.file_clone(code, fld_id))
            except Exception as e:
                print(e)

        elif choice == "5":
            code = input("filecode: ").strip()
            new_title = input("新標題 (空白跳過): ").strip() or None
            public = input("公開? 1=公開 0=私有 空白跳過: ").strip()
            public = int(public) if public in ["0","1"] else None
            try:
                print_json(sdk.file_edit(code, title=new_title, public=public))
            except Exception as e:
                print(e)

        elif choice == "6":
            code = input("filecode: ").strip()
            fld = input("移到哪個資料夾ID: ").strip()
            try:
                print_json(sdk.file_edit(code, folder_id=int(fld)))
                print("移動完成 (透過 file/edit)")
            except Exception as e:
                print(e)

        elif choice == "7":
            code = input("filecode: ").strip()
            print("1. thumb  2. splash  3. preview")
            t = input("選: ").strip()
            try:
                if t=="1":
                    print_json(sdk.thumb(code))
                elif t=="2":
                    print_json(sdk.splash(code))
                elif t=="3":
                    print_json(sdk.preview(code))
            except Exception as e:
                print(e)

        elif choice == "8":
            code = input("filecode: ").strip()
            domain = input("embed domain (預設 byse.sx，建議填你後台專屬域名): ").strip() or "byse.sx"
            # 字幕
            subs=[]
            if input("要加字幕? y/N: ").lower()=="y":
                while True:
                    url = input("字幕 VTT URL (空白結束): ").strip()
                    if not url: break
                    label = input("字幕語言標籤 (如 English): ").strip() or "English"
                    subs.append({"file": url, "label": label})
            poster = input("自訂封面 poster URL (空白跳過): ").strip() or None
            logo = input("自訂 Logo URL (空白跳過): ").strip() or None
            embed_url = sdk.build_embed_with_extras(code, domain, subtitles=subs or None, poster=poster, logo=logo)
            iframe = sdk.iframe_code(code, domain, subtitles=subs or None, poster=poster, logo=logo)
            print(f"\nEmbed URL:\n{embed_url}\n\nIframe:\n{iframe}\n")

        elif choice == "9":
            break

def menu_folders(sdk: ByseSDK):
    while True:
        print("\n=== 資料夾管理 ===")
        print("1. 列出資料夾  2. 建立資料夾  3. 查看資料夾內檔案  4. 返回")
        c = input("選項: ").strip()
        if c=="1":
            try:
                fld = int(input("父資料夾ID (0=根): ") or "0")
                data = sdk.folder_list(fld_id=fld)
                print_json(data)
                folders = data.get("result",{}).get("folders",[])
                print_table("資料夾", folders, ["fld_id","name","code"])
            except Exception as e:
                print(e)
        elif c=="2":
            name = input("新資料夾名稱: ").strip()
            parent = int(input("父資料夾ID (0=根): ") or "0")
            descr = input("描述 (可空白): ").strip() or None
            try:
                print_json(sdk.folder_create(name, parent, descr))
            except Exception as e:
                print(e)
        elif c=="3":
            fld = int(input("資料夾ID: ") or "0")
            try:
                print_json(sdk.folder_list(fld_id=fld, include_files=1))
            except Exception as e:
                print(e)
        else:
            break

def menu_upload(sdk: ByseSDK):
    while True:
        print("\n=== 上傳中心 (完整) ===")
        print("1. 本地檔案上傳  2. 批次本地上傳  3. 遠端 URL 上傳  4. 批次遠端上傳  5. 查詢遠端進度  6. 移除遠端佇列  7. 返回")
        c = input("選項: ").strip()
        if c=="1":
            path = input("檔案路徑: ").strip()
            fld = input("資料夾ID (空白=根): ").strip()
            fld_id = int(fld) if fld else None
            try:
                print("取得上傳伺服器...")
                server = sdk.upload_server()
                print(f"Server: {server}")
                res = sdk.upload_file(path, folder_id=fld_id)
                print_json(res)
            except Exception as e:
                print(f"上傳失敗: {e}")

        elif c=="2":
            paths = input("多檔路徑，用空格或逗號分隔: ").strip().replace(","," ").split()
            fld = input("資料夾ID: ").strip()
            fld_id = int(fld) if fld else None
            for p in paths:
                try:
                    print(f"\n上傳 {p} ...")
                    print_json(sdk.upload_file(p, folder_id=fld_id))
                    time.sleep(1)
                except Exception as e:
                    print(f"{p} 失敗: {e}")

        elif c=="3":
            url = input("直鏈 URL: ").strip()
            fld = input("資料夾ID (空白根): ").strip()
            fld_id = int(fld) if fld else None
            try:
                res = sdk.remote_upload(url, folder_id=fld_id)
                print_json(res)
                # 自動追蹤
                result = res.get("result")
                code = result.get("filecode") if isinstance(result, dict) else result
                if code:
                    print(f"filecode {code}，開始輪詢狀態...")
                    for _ in range(10):
                        time.sleep(3)
                        try:
                            print_json(sdk.remote_status(code))
                        except Exception as e:
                            print(e)
            except Exception as e:
                print(e)

        elif c=="4":
            urls = input("多個 URL 空格分隔: ").strip().split()
            for u in urls:
                try:
                    print(f"遠端上傳 {u}")
                    print_json(sdk.remote_upload(u))
                except Exception as e:
                    print(e)

        elif c=="5":
            code = input("遠端 filecode: ").strip()
            try:
                print_json(sdk.remote_status(code))
            except Exception as e:
                print(e)

        elif c=="6":
            code = input("要移除的 filecode: ").strip()
            try:
                print_json(sdk.remote_remove(code))
            except Exception as e:
                print(e)
        else:
            break

def menu_encoding(sdk: ByseSDK):
    while True:
        print("\n=== 編碼監控 ===")
        print("1. 列出所有編碼任務  2. 單檔編碼狀態  3. 重啟錯誤編碼  4. 刪除錯誤編碼  5. 返回")
        c = input("選項: ").strip()
        if c=="1":
            try: print_json(sdk.encoding_list())
            except Exception as e: print(e)
        elif c=="2":
            code = input("filecode: ").strip()
            try: print_json(sdk.encoding_status(code))
            except Exception as e: print(e)
        elif c=="3":
            code = input("filecode: ").strip()
            try: print_json(sdk.encoding_restart(code))
            except Exception as e: print(e)
        elif c=="4":
            code = input("filecode: ").strip()
            try: print_json(sdk.encoding_delete(code))
            except Exception as e: print(e)
        else:
            break

def menu_tools(sdk: ByseSDK):
    while True:
        print("\n=== 工具箱 ===")
        print("1. 測試所有端點  2. 已刪除檔案  3. DMCA 清單  4. 產生 Premium HLS (實驗)  5. 字幕/封面/Logo URL 產生器  6. 返回")
        c = input("選項: ").strip()
        if c=="1":
            res = sdk.test_all()
            print_json(res)
        elif c=="2":
            try: print_json(sdk.deleted_files())
            except Exception as e: print(e)
        elif c=="3":
            try: print_json(sdk.dmca_files())
            except Exception as e: print(e)
        elif c=="4":
            code = input("filecode: ").strip()
            ip = input("觀看者 IP (如 8.8.8.8): ").strip() or "8.8.8.8"
            ua = input("User-Agent (空白用預設 iPhone): ").strip() or "Mozilla/5.0 (iPhone; CPU iPhone OS 13_5_1 like Mac OS X)"
            try:
                print_json(sdk.premium_hls(code, ip, ua))
            except Exception as e:
                print(e)
        elif c=="5":
            # 已在檔案管理有，但這裡再演示
            code = input("filecode: ").strip()
            sub_url = input("字幕 VTT URL: ").strip()
            sub_label = input("標籤: ").strip() or "English"
            poster = input("Poster URL: ").strip() or None
            logo = input("Logo URL: ").strip() or None
            url = sdk.build_embed_with_extras(code, subtitles=[{"file": sub_url, "label": sub_label}] if sub_url else None, poster=poster, logo=logo)
            print(f"Embed URL: {url}")
            print(f"Iframe: {sdk.iframe_code(code, subtitles=[{'file': sub_url, 'label': sub_label}] if sub_url else None, poster=poster, logo=logo)}")
        else:
            break

def main():
    parser = argparse.ArgumentParser(description="Byse Full Suite CLI")
    parser.add_argument("--key", help="API Key")
    parser.add_argument("--base", default="https://api.byse.sx", help="API base")
    parser.add_argument("--non-interactive", action="store_true", help="僅跑 test_all")
    args = parser.parse_args()

    key = load_key(args.key)
    if not key:
        print("請提供 --key 或設 BYSE_API_KEY")
        sys.exit(1)

    sdk = ByseSDK(api_key=key, base_url=args.base)

    if args.non_interactive:
        print_json(sdk.test_all())
        return

    if HAS_RICH:
        console.print(Panel("Byse Full Suite - 完整 API 管理程式\n12 群組 29+ 端點", style="bold cyan"))

    while True:
        print("\n========== 主選單 ==========")
        print("1. 帳號總覽  2. 檔案管理  3. 資料夾  4. 上傳中心  5. 編碼監控  6. 工具箱  0. 離開")
        choice = input("請選擇: ").strip()
        if choice=="1":
            menu_account(sdk)
        elif choice=="2":
            menu_files(sdk)
        elif choice=="3":
            menu_folders(sdk)
        elif choice=="4":
            menu_upload(sdk)
        elif choice=="5":
            menu_encoding(sdk)
        elif choice=="6":
            menu_tools(sdk)
        elif choice=="0":
            print("再見！")
            break

if __name__ == "__main__":
    main()
