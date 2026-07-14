"""tests/test_sdk.py - ByseSDK 核心邏輯測試 (不打真實 API)"""

from unittest.mock import patch, MagicMock

import pytest
import requests

from byse_full_suite.sdk import ByseSDK, ByseAPIError


class TestByseSDKInit:
    """SDK 初始化測試"""

    def test_init_requires_api_key(self):
        with pytest.raises(ValueError, match="API Key 必須提供"):
            ByseSDK(api_key="")

    def test_init_strips_whitespace(self, fake_api_key):
        sdk = ByseSDK(api_key="  " + fake_api_key + "  ")
        assert sdk.api_key == fake_api_key

    def test_init_strips_trailing_slash(self, fake_api_key):
        sdk = ByseSDK(api_key=fake_api_key, base_url="https://api.byse.sx/")
        assert sdk.base_url == "https://api.byse.sx"

    def test_init_default_timeout(self, fake_api_key):
        sdk = ByseSDK(api_key=fake_api_key)
        assert sdk.timeout == 25

    def test_init_has_endpoint_cache(self, fake_api_key):
        sdk = ByseSDK(api_key=fake_api_key)
        assert hasattr(sdk, "_endpoint_cache")
        assert sdk._endpoint_cache == {}


class TestByseAPIError:
    """ByseAPIError 結構測試"""

    def test_basic_error(self):
        err = ByseAPIError("something failed")
        assert str(err) == "something failed"
        assert err.status_code is None
        assert err.response is None

    def test_error_with_status_code(self):
        err = ByseAPIError("not found", status_code=404, response="not found body")
        assert "[HTTP 404]" in str(err)
        assert err.status_code == 404
        assert err.response == "not found body"


class TestSDKGet:
    """_get 方法測試"""

    def test_get_success(self, sdk, sample_account_info):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_account_info
        mock_resp.text = '{"status": 200}'
        with patch.object(sdk.session, "get", return_value=mock_resp) as mock_get:
            data = sdk._get("account/info")
            assert data["status"] == 200
            mock_get.assert_called_once()
            # 確認 key 有被加入 params
            _, kwargs = mock_get.call_args
            assert kwargs["params"]["key"] == sdk.api_key

    def test_get_wrong_auth_raises(self, sdk):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": 403, "msg": "Wrong Auth"}
        mock_resp.text = '{"msg": "Wrong Auth"}'
        with patch.object(sdk.session, "get", return_value=mock_resp):
            with pytest.raises(ByseAPIError, match="Invalid API Key") as exc_info:
                sdk._get("account/info")
            assert exc_info.value.status_code == 401

    def test_get_invalid_operation_400_raises(self, sdk):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": 400, "msg": "Invalid operation"}
        mock_resp.text = '{"status": 400, "msg": "Invalid operation"}'
        with patch.object(sdk.session, "get", return_value=mock_resp):
            with pytest.raises(ByseAPIError, match="Invalid operation"):
                sdk._get("remote/add")

    def test_get_invalid_operation_400_allowed(self, sdk):
        """allow_400=True 時不應拋錯"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": 400, "msg": "Invalid operation"}
        mock_resp.text = '{"status": 400, "msg": "Invalid operation"}'
        with patch.object(sdk.session, "get", return_value=mock_resp):
            data = sdk._get("remote/add", allow_400=True)
            assert data["status"] == 400

    def test_get_non_json_response(self, sdk):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "Page not found – The requested page doesn't exist in the renewed frontend"
        mock_resp.status_code = 404
        with patch.object(sdk.session, "get", return_value=mock_resp):
            with pytest.raises(ByseAPIError, match="404"):
                sdk._get("nonexistent/endpoint")

    def test_get_request_exception(self, sdk):
        with patch.object(sdk.session, "get", side_effect=requests.ConnectionError("net down")):
            with pytest.raises(ByseAPIError, match="請求失敗"):
                sdk._get("account/info")


class TestEndpointCache:
    """endpoint fallback cache 測試"""

    def test_cache_hit_skips_other_candidates(self, sdk, sample_account_info):
        """第一次成功後, 第二次呼叫不應再嘗試其他候選路徑"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_account_info
        mock_resp.text = '{"status": 200}'
        with patch.object(sdk.session, "get", return_value=mock_resp) as mock_get:
            # 第一次: 應該嘗試第一個候選
            sdk.account_embed_domains()
            assert mock_get.call_count == 1
            first_call_url = mock_get.call_args[0][0]
            assert "account/embed_domains" in first_call_url

            # 第二次: 應該用快取, 仍然只打 1 次 (且是同一個 path)
            mock_get.reset_mock()
            sdk.account_embed_domains()
            assert mock_get.call_count == 1
            assert "account/embed_domains" in mock_get.call_args[0][0]

    def test_cache_falls_through_on_404(self, sdk, sample_account_info):
        """第一個候選 404 時, 應繼續嘗試第二個"""
        mock_404 = MagicMock()
        mock_404.json.side_effect = ValueError("not json")
        mock_404.text = "Page not found – renewed frontend"
        mock_404.status_code = 404

        mock_ok = MagicMock()
        mock_ok.json.return_value = sample_account_info
        mock_ok.text = '{"status": 200}'

        with patch.object(sdk.session, "get", side_effect=[mock_404, mock_ok]) as mock_get:
            data = sdk.account_embed_domains()
            assert mock_get.call_count == 2
            assert "file/embed_domains" in mock_get.call_args_list[1][0][0]
            # 快取應記住第二個 path
            assert sdk._endpoint_cache["embed_domains"] == "file/embed_domains"

    def test_wrong_auth_does_not_fall_through(self, sdk):
        """遇到 401 Wrong Auth 應立刻拋錯, 不繼續嘗試其他候選"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"msg": "Wrong Auth"}
        mock_resp.text = '{"msg": "Wrong Auth"}'
        mock_resp.status_code = 403

        with patch.object(sdk.session, "get", return_value=mock_resp) as mock_get:
            with pytest.raises(ByseAPIError, match="Invalid API Key"):
                sdk.account_embed_domains()
            # 只打了 1 次, 沒有繼續試其他候選
            assert mock_get.call_count == 1


class TestStaticHelpers:
    """靜態輔助方法測試"""

    def test_build_embed_url_no_params(self):
        url = ByseSDK.build_embed_url("abc12345")
        assert url == "https://byse.sx/e/abc12345"

    def test_build_embed_url_with_params(self):
        url = ByseSDK.build_embed_url("abc12345", "mydomain.com", {"poster": "https://x.com/p.jpg"})
        assert url == "https://mydomain.com/e/abc12345?poster=https%3A%2F%2Fx.com%2Fp.jpg"

    def test_build_subtitle_params_single(self):
        params = ByseSDK.build_subtitle_params(
            [{"file": "https://x.com/en.vtt", "label": "English"}]
        )
        assert params == {"c1_file": "https://x.com/en.vtt", "c1_label": "English"}

    def test_build_subtitle_params_multi(self):
        subs = [
            {"file": "https://x.com/en.vtt", "label": "English"},
            {"file": "https://x.com/zh.vtt"},  # 沒給 label
        ]
        params = ByseSDK.build_subtitle_params(subs)
        assert params["c1_file"] == "https://x.com/en.vtt"
        assert params["c1_label"] == "English"
        assert params["c2_file"] == "https://x.com/zh.vtt"
        assert params["c2_label"] == "Subtitle 2"  # 自動補預設

    def test_build_subtitle_json_manifest(self):
        import json

        subs = [
            {"file": "https://x.com/en.vtt", "label": "English", "default": True},
            {"file": "https://x.com/zh.vtt", "label": "中文"},
        ]
        manifest = json.loads(ByseSDK.build_subtitle_json_manifest(subs))
        assert len(manifest) == 2
        assert manifest[0]["default"] is True
        assert "default" not in manifest[1]

    def test_iframe_code(self):
        html = ByseSDK.iframe_code("abc12345", "mydomain.com", 800, 450)
        assert '<iframe src="https://mydomain.com/e/abc12345"' in html
        assert 'width="800"' in html
        assert 'height="450"' in html
        assert "allowfullscreen" in html


class TestFileListParsing:
    """file/info 介面測試 (含 list 轉字串)"""

    def test_file_info_accepts_list(self, sdk, sample_file_list):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_file_list
        mock_resp.text = '{"status": 200}'
        with patch.object(sdk.session, "get", return_value=mock_resp) as mock_get:
            sdk.file_info(["abc12345", "def67890"])
            _, kwargs = mock_get.call_args
            # list 應被轉成逗號分隔字串
            assert kwargs["params"]["file_code"] == "abc12345,def67890"

    def test_file_info_accepts_string(self, sdk):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": 200, "result": []}
        mock_resp.text = '{"status": 200}'
        with patch.object(sdk.session, "get", return_value=mock_resp) as mock_get:
            sdk.file_info("abc12345")
            _, kwargs = mock_get.call_args
            assert kwargs["params"]["file_code"] == "abc12345"
