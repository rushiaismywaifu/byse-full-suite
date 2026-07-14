#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse.sx API 健康檢查腳本

供 GitHub Actions health-check.yml 呼叫, 也可以本機執行:
  python scripts/health_check.py            # 無 key, 只測試 public 端點可達性
  BYSE_API_KEY=xxx python scripts/health_check.py  # 帶 key, 測試授權端點

exit code: 0 = 全部健康, 1 = 有端點不通
"""

import os
import sys
from typing import List, Tuple

import requests

BASES = ["https://api.byse.sx", "https://filemoonapi.com/api"]
PUBLIC_ENDPOINTS = ["account/info", "upload/server"]
AUTHED_ENDPOINTS = ["account/info", "upload/server", "file/list", "folder/list", "encoding/list"]


def check_endpoint(
    base: str, path: str, api_key: str = "invalidkey", timeout: int = 10
) -> Tuple[bool, str]:
    """檢查單一端點, 回傳 (ok, message)"""
    url = f"{base}/{path}"
    params = {"key": api_key}
    if path == "file/list":
        params["fld_id"] = 0
        params["per_page"] = 1
    try:
        r = requests.get(url, params=params, timeout=timeout)
        return True, f"{url} -> {r.status_code} {r.text[:200]}"
    except requests.RequestException as e:
        return False, f"{url} ERR {e}"
    except Exception as e:
        return False, f"{url} ERR {e}"


def main() -> int:
    api_key = os.getenv("BYSE_API_KEY", "").strip()
    print(f"=== Byse API Health Check ===")
    print(f"API Key: {'provided' if api_key else 'not provided (public check only)'}")
    print()

    failures: List[str] = []

    # 公開端點 (用 invalidkey 探測, 只要 server 回應就算健康)
    print("--- Public endpoints (probing reachability) ---")
    for base in BASES:
        for path in PUBLIC_ENDPOINTS:
            ok, msg = check_endpoint(base, path)
            print(msg)
            if not ok:
                failures.append(msg)

    # 授權端點 (只有當 API Key 提供時才測)
    if api_key:
        print()
        print("--- Authed endpoints (real key) ---")
        for path in AUTHED_ENDPOINTS:
            ok, msg = check_endpoint("https://api.byse.sx", path, api_key=api_key, timeout=15)
            print(msg)
            if not ok:
                failures.append(msg)

    print()
    if failures:
        print(f"FAIL: {len(failures)} endpoint(s) unreachable:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK: all checked endpoints reachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
