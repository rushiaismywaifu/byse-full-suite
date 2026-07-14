#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse Full Suite - Flask 代理伺服器 (可選)
解決 CORS + 本地上傳轉發

pip install flask flask-cors requests
python server.py
"""

from pathlib import Path
import os
import requests
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

BASE_API = "https://api.byse.sx"
UPLOAD_SERVER_CACHE = {}

app = Flask(__name__, static_folder=".")
CORS(app, supports_credentials=True)


@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


@app.route("/api/<path:path>", methods=["GET", "POST"])
def proxy_api(path):
    """代理所有 /api/xxx 到 https://api.byse.sx/xxx"""
    params = request.args.to_dict()
    # 保留 key
    url = f"{BASE_API}/{path}"
    try:
        if request.method == "GET":
            r = requests.get(url, params=params, timeout=25)
        else:
            r = requests.post(
                url, params=params, data=request.form, files=request.files, timeout=25
            )
        # 嘗試回傳 JSON，失敗回原始
        try:
            return jsonify(r.json()), r.status_code
        except:
            return Response(
                r.text,
                status=r.status_code,
                mimetype=r.headers.get("Content-Type", "text/plain"),
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/upload", methods=["POST"])
def proxy_upload():
    """
    前端本地檔案 -> 後端 -> Byse upload server
    前端 FormData: file, key, fld_id (optional)
    """
    api_key = request.form.get("key") or request.args.get("key")
    if not api_key:
        return jsonify({"error": "缺少 key"}), 400

    # 先取得 upload server
    try:
        srv_resp = requests.get(f"{BASE_API}/upload/server", params={"key": api_key}, timeout=15)
        srv_data = srv_resp.json()
        upload_url = srv_data.get("result")
        if not upload_url:
            return jsonify({"error": f"無法取得 upload server: {srv_data}"}), 500
    except Exception as e:
        return jsonify({"error": f"get upload server fail: {e}"}), 500

    file_obj = request.files.get("file")
    if not file_obj:
        return jsonify({"error": "缺少 file"}), 400

    fld_id = request.form.get("fld_id")
    data = {"key": api_key}
    if fld_id:
        data["fld_id"] = fld_id

    try:
        # 轉發到 byse upload edge
        files = {"file": (file_obj.filename, file_obj.stream, file_obj.mimetype)}
        r = requests.post(upload_url, data=data, files=files, timeout=300)
        try:
            return jsonify(r.json()), r.status_code
        except:
            return Response(r.text, status=r.status_code)
    except Exception as e:
        return jsonify({"error": f"upload fail: {e}"}), 500


@app.route("/dashboard.html")
def dash():
    return send_from_directory(".", "dashboard.html")


if __name__ == "__main__":
    print("Byse Full Suite Server")
    print("Dashboard: http://localhost:5000/")
    print("API Proxy: http://localhost:5000/api/account/info?key=YOUR_KEY")
    app.run(host="0.0.0.0", port=5000, debug=True)
