#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Byse.sx / Filemoon 完整 SDK - 支援 29+ 端點
涵蓋官方 api-docs 和 filemoonapi 兼容端點

作者: Arena Agent
測試環境: api.byse.sx
Base: https://api.byse.sx  (fallback https://filemoonapi.com/api 已失效 522)
"""

from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from urllib.parse import quote

import requests

DEFAULT_BASE = "https://api.byse.sx"
LEGACY_BASE = "https://filemoonapi.com/api"


class ByseAPIError(Exception):
    """Byse API 錯誤, 帶 status_code 與原始回應方便除錯"""

    def __init__(
        self, message: str, status_code: Optional[int] = None, response: Any = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response

    def __str__(self):
        base = super().__str__()
        if self.status_code is not None:
            return f"[HTTP {self.status_code}] {base}"
        return base


class ByseSDK:
    """
    完整 SDK，包含 12 群組 29+ 端點 + 補助工具

    內建 endpoint fallback cache: 第一次找到可用的 endpoint path 後,
    後續相同呼叫直接用快取, 避免重複打多個候選路徑.
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE, timeout: int = 25):
        if not api_key:
            raise ValueError("API Key 必須提供")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "ByseFullSDK/2.1",
                "Accept": "application/json",
            }
        )
        # endpoint fallback cache: {logical_name: working_path}
        # 例如 "embed_domains" -> "account/embed_domains"
        self._endpoint_cache: Dict[str, str] = {}

    # ---------- 內部請求 ----------
    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        allow_400: bool = False,
    ) -> Dict:
        """統一 GET 包裝"""
        p = dict(params or {})
        p["key"] = self.api_key
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            r = self.session.get(url, params=p, timeout=self.timeout)
        except requests.RequestException as e:
            raise ByseAPIError(f"請求失敗 {path}: {e}")

        # 非 JSON 處理 (前端 404 等)
        try:
            data = r.json()
        except Exception:
            if "Page not found" in r.text:
                raise ByseAPIError(
                    f"端點 {path} 404 (前端)",
                    status_code=404,
                    response=r.text[:500],
                )
            raise ByseAPIError(
                f"非 JSON 回應: {r.text[:500]}",
                status_code=r.status_code,
                response=r.text[:500],
            )

        if data.get("msg") == "Wrong Auth":
            raise ByseAPIError("Invalid API Key", status_code=401, response=data)

        # 400 + Invalid operation 視為錯誤 (除非呼叫端明確允許)
        if not allow_400 and data.get("status") == 400:
            msg = data.get("msg", "")
            if msg in ("Invalid operation", "Wrong Auth"):
                raise ByseAPIError(
                    f"{path} {msg}: {data}", status_code=400, response=data
                )

        return data

    def _get_with_fallback(
        self,
        cache_key: str,
        candidate_paths: List[str],
        params: Optional[Dict[str, Any]] = None,
        allow_400: bool = False,
    ) -> Dict:
        """對多個候選 endpoint 嘗試, 第一次成功後快取.

        - 命中快取: 只打 1 次
        - 未命中: 依序嘗試 candidates, 第一個成功就快取
        - 全部失敗: 拋 ByseAPIError 帶最後一個錯誤
        """
        cached = self._endpoint_cache.get(cache_key)
        paths_to_try = [cached] if cached else candidate_paths
        last_err: Optional[ByseAPIError] = None

        for p in paths_to_try:
            if p is None:
                continue
            try:
                data = self._get(p, params=params, allow_400=allow_400)
                # 成功就快取
                self._endpoint_cache[cache_key] = p
                return data
            except ByseAPIError as e:
                last_err = e
                # 404 / 端點不存在 -> 試下一個
                # 401 / Wrong Auth -> 直接拋 (key 錯了沒意義繼續試)
                if e.status_code == 401:
                    raise
                continue

        raise ByseAPIError(
            f"所有候選端點都失敗 ({cache_key}): {candidate_paths}. 最後錯誤: {last_err}",
            status_code=last_err.status_code if last_err else None,
            response=last_err.response if last_err else None,
        )

    def _post_upload(
        self,
        upload_server_url: str,
        filepath: Path,
        extra_data: Optional[Dict] = None,
    ):
        """POST 到 upload server (非 api base)"""
        extra_data = extra_data or {}
        extra_data["key"] = self.api_key
        mime = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        with open(filepath, "rb") as f:
            files = {"file": (filepath.name, f, mime)}
            try:
                r = self.session.post(
                    upload_server_url, data=extra_data, files=files, timeout=300
                )
            except requests.RequestException as e:
                raise ByseAPIError(f"上傳請求失敗: {e}")
            try:
                return r.json()
            except Exception:
                raise ByseAPIError(
                    f"上傳回應非 JSON: {r.text[:1000]}",
                    status_code=r.status_code,
                    response=r.text[:1000],
                )

    # ========== 1. Account 群組 ==========
    def account_info(self) -> Dict:
        """GET account/info - 餘額、檔案總數、儲存空間"""
        return self._get("account/info")

    def account_stats(self, last: int = 7) -> Dict:
        """GET account/stats?last=7 - 收益、觀看"""
        return self._get("account/stats", {"last": last})

    def account_embed_domains(self) -> Dict:
        """嘗試多個路徑取得舊/新 embed domain (使用 endpoint cache)"""
        candidates = [
            "account/embed_domains",
            "file/embed_domains",
            "account/custom_domain",
            "account/domain",
        ]
        try:
            return self._get_with_fallback("embed_domains", candidates)
        except ByseAPIError:
            raise ByseAPIError(
                "embed_domains 端點不存在，請到後台 Settings -> Custom Domains 查看"
            )

    # ========== 2. Upload 群組 ==========
    def upload_server(self) -> str:
        """GET upload/server -> 回傳最佳上傳節點 URL"""
        data = self._get("upload/server")
        result = data.get("result")
        if not result:
            raise ByseAPIError(f"無法取得上傳伺服器: {data}")
        return result

    def upload_file(
        self, filepath: Union[str, Path], folder_id: Optional[int] = None
    ) -> Dict:
        """本地檔案上傳：先拿 server 再 POST"""
        fp = Path(filepath)
        if not fp.exists():
            raise FileNotFoundError(str(fp))
        server_url = self.upload_server()
        extra = {}
        if folder_id is not None:
            extra["fld_id"] = folder_id
        return self._post_upload(server_url, fp, extra)

    def remote_upload(self, direct_link: str, folder_id: Optional[int] = None) -> Dict:
        """
        遠端 URL 拉取
        新版文件寫 upload/url，但實測可用的是 remote/add (fallback)
        """
        params: Dict[str, Any] = {"url": direct_link}
        if folder_id is not None:
            params["fld_id"] = folder_id
        candidates = ["remote/add", "upload/url"]
        return self._get_with_fallback(
            "remote_upload", candidates, params=params, allow_400=True
        )

    def remote_remove(self, file_code: str) -> Dict:
        """移除佇列中的遠端上傳"""
        params = {"file_code": file_code}
        candidates = ["remote/remove", "upload/remove", "upload/url/remove"]
        try:
            return self._get_with_fallback(
                "remote_remove", candidates, params=params, allow_400=True
            )
        except ByseAPIError:
            # 全失敗時再試一次主路徑, 让上層看到真實錯誤
            return self._get("remote/remove", params, allow_400=True)

    def remote_status(self, file_code: str) -> Dict:
        """查詢遠端上傳進度"""
        params = {"file_code": file_code}
        candidates = ["remote/status", "upload/status", "upload/url/status"]
        try:
            return self._get_with_fallback(
                "remote_status", candidates, params=params, allow_400=True
            )
        except ByseAPIError:
            return self._get("remote/status", params, allow_400=True)

    # ========== 3. File 群組 ==========
    def file_info(self, file_code: Union[str, List[str]]) -> Dict:
        """file/info?file_code=xxx 或逗號分隔多個"""
        if isinstance(file_code, list):
            file_code = ",".join(file_code)
        return self._get("file/info", {"file_code": file_code})

    def file_list(
        self,
        fld_id: int = 0,
        title: Optional[str] = None,
        created: Optional[str] = None,
        public: Optional[int] = None,
        per_page: int = 20,
        page: int = 1,
    ) -> Dict:
        """file/list - 支援篩選"""
        params: Dict[str, Any] = {"fld_id": fld_id, "per_page": per_page, "page": page}
        if title:
            params["title"] = title
        if created:
            params["created"] = created
        if public is not None:
            params["public"] = public
        return self._get("file/list", params)

    def file_clone(self, file_code: str, folder_id: Optional[int] = None) -> Dict:
        """file/clone - 複製檔案到當前帳號 (需對方開放)"""
        params: Dict[str, Any] = {"file_code": file_code}
        if folder_id is not None:
            params["fld_id"] = folder_id
        return self._get("file/clone", params)

    def file_edit(
        self,
        file_code: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        folder_id: Optional[int] = None,
        public: Optional[int] = None,
        tags: Optional[str] = None,
        adult: Optional[int] = None,
        cat_id: Optional[int] = None,
    ) -> Dict:
        """
        file/edit - 編輯檔案屬性
        經測試支援: file_title, file_public, fld_id, file_adult, cat_id 等
        這是 byse 移動檔案的主要方式
        """
        params: Dict[str, Any] = {"file_code": file_code}
        if title is not None:
            params["file_title"] = title
        if description is not None:
            params["file_descr"] = description
        if folder_id is not None:
            params["fld_id"] = folder_id
        if public is not None:
            params["file_public"] = public
        if tags is not None:
            params["tags"] = tags
        if adult is not None:
            params["file_adult"] = adult
        if cat_id is not None:
            params["cat_id"] = cat_id
        return self._get("file/edit", params)

    def file_set_folder(self, file_code: str, fld_id: int) -> Dict:
        """相容舊 API 名稱"""
        return self.file_edit(file_code, folder_id=fld_id)

    # ========== 4. Folder 群組 ==========
    def folder_list(self, fld_id: int = 0, include_files: int = 0) -> Dict:
        """folder/list"""
        return self._get("folder/list", {"fld_id": fld_id, "files": include_files})

    def folder_create(
        self,
        name: str,
        parent_id: int = 0,
        description: Optional[str] = None,
    ) -> Dict:
        """folder/create"""
        params: Dict[str, Any] = {"name": name, "parent_id": parent_id}
        if description:
            params["descr"] = description
        return self._get("folder/create", params)

    # ========== 5. Deleted / DMCA 群組 ==========
    def deleted_files(self, last: Optional[int] = None) -> Dict:
        """files/deleted - 取回已刪除清單"""
        params: Dict[str, Any] = {}
        if last:
            params["last"] = last
        return self._get("files/deleted", params)

    def dmca_files(self, last: Optional[int] = None) -> Dict:
        """files/dmca - DMCA 待刪除清單"""
        params: Dict[str, Any] = {}
        if last:
            params["last"] = last
        return self._get("files/dmca", params)

    # ========== 6. Encoding 群組 ==========
    def encoding_list(self) -> Dict:
        return self._get("encoding/list")

    def encoding_status(self, file_code: str) -> Dict:
        return self._get("encoding/status", {"file_code": file_code})

    def encoding_restart(self, file_code: str) -> Dict:
        return self._get("encoding/restart", {"file_code": file_code}, allow_400=True)

    def encoding_delete(self, file_code: str) -> Dict:
        return self._get("encoding/delete", {"file_code": file_code}, allow_400=True)

    # ========== 7. Images 群組 ==========
    def thumb(self, file_code: str) -> Dict:
        return self._get("images/thumb", {"file_code": file_code})

    def splash(self, file_code: str) -> Dict:
        return self._get("images/splash", {"file_code": file_code})

    def preview(self, file_code: str) -> Dict:
        """sprite 預覽 + VTT 軌跡"""
        return self._get("images/preview", {"file_code": file_code})

    # ========== 8. HLS Premium (實驗性) ==========
    def premium_hls(self, file_code: str, ip: str, ua: str) -> Dict:
        """
        官方文件提到產生時限性 HLS 連結，需要 premium
        嘗試多個可能路徑 (使用 endpoint cache)
        """
        params = {"file_code": file_code, "ip": ip, "ua": ua}
        candidates = [
            "file/hls",
            "file/premium_link",
            "file/direct_link",
            "account/hls",
        ]
        try:
            return self._get_with_fallback(
                "premium_hls", candidates, params=params, allow_400=True
            )
        except ByseAPIError:
            raise ByseAPIError("premium HLS 端點暫不可用或帳號未開通 premium")

    # ========== 9. 補助工具：字幕、封面、Logo、Embed ==========
    @staticmethod
    def build_embed_url(
        file_code: str,
        domain: str = "byse.sx",
        custom_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """產生 embed 播放頁 URL"""
        base = f"https://{domain}/e/{file_code}"
        if not custom_params:
            return base
        qs = "&".join(
            [f"{k}={quote(str(v), safe='')}" for k, v in custom_params.items()]
        )
        return f"{base}?{qs}" if qs else base

    @staticmethod
    def build_subtitle_params(subtitles: List[Dict[str, str]]) -> Dict[str, str]:
        """
        subtitles = [{"file":"https://example.com/en.vtt","label":"English"},...]
        轉成 c1_file, c1_label, c2_file...
        """
        params: Dict[str, str] = {}
        for idx, sub in enumerate(subtitles, start=1):
            params[f"c{idx}_file"] = sub["file"]
            params[f"c{idx}_label"] = sub.get("label", f"Subtitle {idx}")
        return params

    @staticmethod
    def build_subtitle_json_manifest(subtitles: List[Dict]) -> str:
        """
        產生 JSON manifest: [{"src":"...","label":"...","default":true},...]
        """
        manifest = []
        for sub in subtitles:
            entry: Dict[str, Any] = {"src": sub["file"], "label": sub.get("label", "")}
            if sub.get("default"):
                entry["default"] = True
            manifest.append(entry)
        return json.dumps(manifest)

    @staticmethod
    def build_embed_with_extras(
        file_code: str,
        domain: str = "byse.sx",
        subtitles: Optional[List[Dict]] = None,
        poster: Optional[str] = None,
        logo: Optional[str] = None,
        subtitle_json: Optional[str] = None,
    ) -> str:
        """一鍵產生帶字幕、封面、Logo 的 embed URL"""
        params: Dict[str, str] = {}
        if subtitles:
            params.update(ByseSDK.build_subtitle_params(subtitles))
        if poster:
            params["poster"] = poster
        if logo:
            params["logo"] = logo
        if subtitle_json:
            params["subtitle_json"] = subtitle_json
        return ByseSDK.build_embed_url(file_code, domain, params)

    @staticmethod
    def iframe_code(
        file_code: str,
        domain: str = "byse.sx",
        width: int = 640,
        height: int = 360,
        **extras,
    ) -> str:
        """產生 iframe embed code"""
        url = ByseSDK.build_embed_with_extras(file_code, domain, **extras)
        return f'<iframe src="{url}" width="{width}" height="{height}" frameborder="0" allowfullscreen></iframe>'

    # ========== 10. 綜合測試 ==========
    def test_all(self) -> Dict[str, Any]:
        """跑遍所有已知可用端點，回報狀態"""
        results: Dict[str, Any] = {}
        tests = [
            ("account/info", lambda: self.account_info()),
            ("account/stats", lambda: self.account_stats()),
            ("upload/server", lambda: self._get("upload/server")),
            ("file/list root", lambda: self.file_list(fld_id=0, per_page=1)),
            ("folder/list", lambda: self.folder_list()),
            ("files/deleted", lambda: self.deleted_files()),
            ("files/dmca", lambda: self.dmca_files()),
            ("encoding/list", lambda: self.encoding_list()),
        ]
        for name, fn in tests:
            try:
                data = fn()
                results[name] = {"ok": True, "sample": str(data)[:300]}
            except Exception as e:
                results[name] = {"ok": False, "error": str(e)}
        return results
