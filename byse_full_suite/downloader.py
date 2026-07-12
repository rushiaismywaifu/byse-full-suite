#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse.sx 快速下載器 (支援自訂域名如 bysedikamoum.com)
涵蓋 3 種方式：直鏈下載 / API 自己帳號 / yt-dlp 解析 HLS

免責：請只下載你擁有版權或已獲授權的影片，遵守 byse.sx ToS

用法:
  pip install requests tqdm yt-dlp
  python downloader.py https://bysedikamoum.com/download/20qj5ubmhhsj
  python downloader.py --code 20qj5ubmhhsj --api-key YOUR_KEY
  python downloader.py https://byse.sx/e/1vtkmhfb44rj --use-ytdlp
"""

import re
import os
import sys
import argparse
import requests
from pathlib import Path
from typing import Optional

# 嘗試載入 tqdm
try:
    from tqdm import tqdm
    HAS_TQDM = True
except:
    HAS_TQDM = False

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer": "https://byse.sx/",
    "Accept": "*/*",
}

CODE_RE = re.compile(r'(?:/e/|/d/|/download/|/video/|/file/)?([a-zA-Z0-9]{8,12})(?:\.html|/|$)')

def extract_code(url_or_code: str) -> str:
    """從各種 byse 連結提取 filecode"""
    s = url_or_code.strip()
    # 如果本身就是 8-12 碼純碼
    if re.fullmatch(r'[A-Za-z0-9]{8,12}', s):
        return s
    m = CODE_RE.search(s)
    if m:
        return m.group(1)
    # 嘗試最後一段
    m2 = re.search(r'([A-Za-z0-9]{8,12})', s)
    if m2:
        return m2.group(1)
    raise ValueError(f"無法從 {url_or_code} 提取 filecode")

def guess_domain(url: str) -> str:
    """從輸入 URL 保留原始域名，例如 bysedikamoum.com"""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        if p.netloc:
            return p.netloc
    except:
        pass
    return "byse.sx"

def build_urls(filecode: str, original_domain: str = "byse.sx"):
    """產生幾種可能的直鏈"""
    return [
        f"https://{original_domain}/download/{filecode}",
        f"https://{original_domain}/d/{filecode}",
        f"https://byse.sx/download/{filecode}",
        f"https://byse.sx/d/{filecode}",
        f"https://filemoon.to/download/{filecode}",
        f"https://filemoon.to/d/{filecode}",
        f"https://{original_domain}/e/{filecode}",
    ]

def download_with_requests(url: str, output: Path, headers: dict = None):
    """串流下載帶進度"""
    headers = headers or DEFAULT_HEADERS
    sess = requests.Session()
    sess.headers.update(headers)
    # 先用 HEAD 試探
    with sess.get(url, stream=True, timeout=30, allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        # 如果回的是 HTML 而不是影片，可能是中間頁
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype and total < 500_000:
            # 嘗試從 HTML 找真正的 mp4 / m3u8 / download 按鈕
            text = r.text
            # 常見 filemoon 在 HTML 裡有 <a href="https://...download..."> 或 file: "https://...m3u8"
            m = re.search(r'(https?://[^"\']+\.(?:mp4|m3u8)[^"\']*)', text)
            if m:
                real_url = m.group(1)
                print(f"[+] 在 HTML 中找到實際連結: {real_url}")
                return download_with_requests(real_url, output, headers)
            m2 = re.search(r'href="([^"]+/download/[^"]+)"', text)
            if m2:
                real_url = m2.group(1)
                if not real_url.startswith("http"):
                    real_url = f"https://{headers.get('Referer','https://byse.sx/').split('/')[2]}{real_url}"
                print(f"[+] 找到 download 按鈕連結: {real_url}")
                return download_with_requests(real_url, output, headers)
            # 否則還是把 HTML 存下來供除錯
            print(f"[!] 回傳是 HTML ({ctype}), 可能需要等待或過廣告, 先存成 {output}.html 供檢查")
            output.with_suffix(".html").write_text(text, encoding="utf-8", errors="ignore")
            raise RuntimeError("拿到的是 HTML 頁面，不是影片本身。建議改用 --use-ytdlp")

        output.parent.mkdir(parents=True, exist_ok=True)
        if HAS_TQDM and total:
            pbar = tqdm(total=total, unit='B', unit_scale=True, desc=output.name)
        else:
            pbar = None
            print(f"[+] 下載 {output.name} {(total/1024/1024):.2f}MB")

        with open(output, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*256):
                if chunk:
                    f.write(chunk)
                    if pbar:
                        pbar.update(len(chunk))
        if pbar:
            pbar.close()
    print(f"[✓] 完成: {output} ({output.stat().st_size/1024/1024:.2f} MB)")

def download_with_api(filecode: str, api_key: str, output: Path):
    """用你自己的 byse API Key 下載自己帳號的檔案 (最穩定)"""
    from sdk import ByseSDK
    sdk = ByseSDK(api_key)
    info = sdk.file_info(filecode)
    print(info)
    # file/info 回的 link 欄位通常是 https://filemoon.to/d/xxx/yyy.mp4
    result = info.get("result", [])
    if isinstance(result, list) and result:
        entry = result[0]
        direct_page = entry.get("link") or f"https://byse.sx/d/{filecode}"
        print(f"[+] API 回傳 download page: {direct_page}")
        # 這個 page 仍然需要再解析，可以直接交給 requests 下載
        return download_with_requests(direct_page, output)
    elif isinstance(result, dict):
        direct_page = result.get("link")
        return download_with_requests(direct_page, output)
    else:
        raise RuntimeError(f"API 未回傳 link: {info}")

def download_with_ytdlp(url_or_code: str, output: str = None):
    """呼叫 yt-dlp，最能處理 HLS / 打包 JS，推薦"""
    try:
        import yt_dlp
    except ImportError:
        print("請先 pip install yt-dlp")
        sys.exit(1)

    # yt-dlp 支援 filemoon / byse extractor，直接給 /e/ 連結最好
    filecode = extract_code(url_or_code)
    domain = guess_domain(url_or_code) if "://" in url_or_code else "byse.sx"
    # 優先用 /e/ 連結，yt-dlp 對 /e/ 解析最好
    test_urls = [
        f"https://{domain}/e/{filecode}",
        f"https://byse.sx/e/{filecode}",
        url_or_code,
    ]

    ydl_opts = {
        "outtmpl": output or f"{filecode}.%(ext)s",
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        last_err = None
        for u in test_urls:
            try:
                print(f"[+] 嘗試 yt-dlp: {u}")
                ydl.download([u])
                print("[✓] yt-dlp 下載完成")
                return
            except Exception as e:
                last_err = e
                print(f"  失敗: {e}")
        raise last_err

def main():
    parser = argparse.ArgumentParser(description="Byse.sx 快速下載器")
    parser.add_argument("url", help="byse 連結，例如 https://bysedikamoum.com/download/20qj5ubmhhsj 或 filecode")
    parser.add_argument("-o", "--output", help="輸出檔名，預設 filecode.mp4")
    parser.add_argument("--code", action="store_true", help="強制把第一參數當 filecode")
    parser.add_argument("--api-key", help="若是下載自己帳號的檔案，提供 API Key 用官方 file/info 取直鏈 (最穩定)")
    parser.add_argument("--use-ytdlp", action="store_true", help="使用 yt-dlp 解析 HLS (推薦處理廣告/打包JS)")
    parser.add_argument("--domain", help="自訂域名，預設自動從 URL 判斷")
    args = parser.parse_args()

    input_str = args.url
    try:
        filecode = extract_code(input_str)
    except Exception as e:
        print(f"無法解析 filecode: {e}")
        sys.exit(1)

    domain = args.domain or guess_domain(input_str)
    output_path = Path(args.output) if args.output else Path(f"{filecode}.mp4")

    print(f"[i] filecode: {filecode} | domain: {domain} | output: {output_path}")

    if args.use_ytdlp:
        download_with_ytdlp(input_str, str(output_path))
        return

    if args.api_key:
        download_with_api(filecode, args.api_key, output_path)
        return

    # 一般直鏈嘗試
    urls = build_urls(filecode, original_domain=domain)
    # 把使用者原始輸入也放最前面
    if input_str.startswith("http"):
        urls = [input_str] + urls

    for u in urls:
        try:
            print(f"\n[+] 嘗試: {u}")
            headers = dict(DEFAULT_HEADERS)
            headers["Referer"] = f"https://{domain}/"
            download_with_requests(u, output_path, headers=headers)
            return
        except Exception as e:
            print(f"  -> 失敗: {e}")
            continue

    print("\n[✗] 所有直鏈都失敗，建議改用 --use-ytdlp，這對 byse/filemoon 的 HLS 打包最有效")
    print("    pip install yt-dlp && python downloader.py --use-ytdlp https://bysedikamoum.com/e/20qj5ubmhhsj")

if __name__ == "__main__":
    main()
