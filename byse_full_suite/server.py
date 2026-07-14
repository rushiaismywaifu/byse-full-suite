#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse Full Suite - Flask 代理伺服器 (可選)
解決 CORS + 本地上傳轉發 + 隱藏 API Key

安全設計:
- API Key 從環境變數 BYSE_API_KEY 讀取 (不再走 URL query)
- /api/ 端點白名單, 避免淪為 open relay
- debug 預設關閉, 需明確 BYSE_DEBUG=1 才開
- 可選 BYSE_PROXY_TOKEN 做簡易 bearer 認證

pip install flask flask-cors requests
python server.py
"""

from pathlib import Path
import os
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, abort
from flask_cors import CORS

BASE_API = "https://api.byse.sx"

# 端點白名單: 允許代理的 /api/<path> 路徑
# 任何不在這裡的路徑都會被拒絕, 避免淪為 open relay
ALLOWED_API_PATHS = {
    "account/info",
    "account/stats",
    "account/embed_domains",
    "account/custom_domain",
    "account/domain",
    "upload/server",
    "upload/url",
    "upload/status",
    "upload/remove",
    "remote/add",
    "remote/status",
    "remote/remove",
    "file/info",
    "file/list",
    "file/clone",
    "file/edit",
    "file/embed_domains",
    "folder/list",
    "folder/create",
    "files/deleted",
    "files/dmca",
    "encoding/list",
    "encoding/status",
    "encoding/restart",
    "encoding/delete",
    "images/thumb",
    "images/splash",
    "images/preview",
}

app = Flask(__name__, static_folder=".")
# 不再允許任意 origin 帶 credentials; 預設限制為同源
# 若需跨網域使用, 請明確設 BYSE_CORS_ORIGINS=https://yourdomain.com,https://another.com
cors_origins = (
    os.getenv("BYSE_CORS_ORIGINS", "*").split(",")
    if os.getenv("BYSE_CORS_ORIGINS")
    else "*"
)
CORS(app, origins=cors_origins, supports_credentials=False)


def _get_api_key() -> str:
    """從環境變數或表單取得 API Key.

    優先順序: 環境變數 BYSE_API_KEY > 表單 key 欄位
    若兩者都沒有, 回空字串 (由呼叫端處理錯誤).
    """
    env_key = os.getenv("BYSE_API_KEY", "").strip()
    if env_key:
        return env_key
    return (request.form.get("key") or request.args.get("key") or "").strip()


def _check_proxy_token():
    """若有設定 BYSE_PROXY_TOKEN, 要求請求帶相符的 Bearer token."""
    expected = os.getenv("BYSE_PROXY_TOKEN", "").strip()
    if not expected:
        return  # 未設定 = 不啟用認證 (本機開發使用)
    auth = request.headers.get("Authorization", "")
    bearer = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
    if bearer != expected:
        abort(401, description="Invalid or missing proxy token")


@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


@app.route("/api/<path:path>", methods=["GET", "POST"])
def proxy_api(path):
    """代理 /api/<path> 到 https://api.byse.sx/<path>

    - 白名單檢查: path 必須在 ALLOWED_API_PATHS
    - API Key: 從環境變數注入, 不再從前端帶 query
    - 簡易 bearer token 認證 (可選)
    """
    _check_proxy_token()

    if path not in ALLOWED_API_PATHS:
        return jsonify({"error": f"Endpoint not allowed: {path}"}), 403

    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Server missing BYSE_API_KEY env var"}), 500

    params = {k: v for k, v in request.args.to_dict().items() if k != "key"}
    params["key"] = api_key  # server 端注入, 前端永遠看不到

    url = f"{BASE_API}/{path}"
    try:
        if request.method == "GET":
            r = requests.get(url, params=params, timeout=25)
        else:
            # POST 時 form 也要清掉 key (由 server 注入)
            form = {k: v for k, v in request.form.to_dict().items() if k != "key"}
            form["key"] = api_key
            r = requests.post(
                url, params=params, data=form, files=request.files, timeout=25
            )
        # 嘗試回傳 JSON，失敗回原始
        try:
            return jsonify(r.json()), r.status_code
        except Exception:
            return Response(
                r.text,
                status=r.status_code,
                mimetype=r.headers.get("Content-Type", "text/plain"),
            )
    except requests.RequestException as e:
        return jsonify({"error": f"upstream request failed: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/upload", methods=["POST"])
def proxy_upload():
    """
    前端本地檔案 -> 後端 -> Byse upload server
    前端 FormData: file, (可選 fld_id)
    API Key 由 server 環境變數提供, 前端不需帶
    """
    _check_proxy_token()

    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Server missing BYSE_API_KEY env var"}), 500

    try:
        srv_resp = requests.get(
            f"{BASE_API}/upload/server", params={"key": api_key}, timeout=15
        )
        srv_data = srv_resp.json()
        upload_url = srv_data.get("result")
        if not upload_url:
            return jsonify({"error": f"cannot get upload server: {srv_data}"}), 502
    except requests.RequestException as e:
        return jsonify({"error": f"get upload server fail: {e}"}), 502

    file_obj = request.files.get("file")
    if not file_obj:
        return jsonify({"error": "missing file"}), 400

    fld_id = request.form.get("fld_id")
    data = {"key": api_key}
    if fld_id:
        data["fld_id"] = fld_id

    try:
        files = {"file": (file_obj.filename, file_obj.stream, file_obj.mimetype)}
        r = requests.post(upload_url, data=data, files=files, timeout=300)
        try:
            return jsonify(r.json()), r.status_code
        except Exception:
            return Response(r.text, status=r.status_code)
    except requests.RequestException as e:
        return jsonify({"error": f"upload fail: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/dashboard.html")
def dash():
    return send_from_directory(".", "dashboard.html")


if __name__ == "__main__":
    print("Byse Full Suite Server")
    print("Dashboard: http://localhost:5000/")
    if os.getenv("BYSE_API_KEY"):
        print("API Key: loaded from env (dashboard 不需要輸入 key)")
    else:
        print("WARNING: BYSE_API_KEY 未設定, dashboard 將無法運作")
    if os.getenv("BYSE_PROXY_TOKEN"):
        print("Proxy token auth: ENABLED")
    print("API Proxy: http://localhost:5000/api/account/info")
    # 預設不開 debug, 避免暴露 Werkzeug debugger
    debug = os.getenv("BYSE_DEBUG", "0") == "1"
    host = os.getenv("BYSE_HOST", "127.0.0.1")  # 預設只綁本機
    if debug:
        print("⚠️  DEBUG MODE ON - 請勿在生產環境使用")
    app.run(host=host, port=int(os.getenv("BYSE_PORT", "5000")), debug=debug)
