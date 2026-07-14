"""tests/test_uploader.py - ByseClient (thin wrapper) 測試"""

from unittest.mock import patch, MagicMock

import pytest

from byse_uploader import ByseClient


class TestByseClientWrapper:
    """測試 ByseClient 是否正確委派給 ByseSDK"""

    def test_init_creates_sdk(self, fake_api_key):
        client = ByseClient(api_key=fake_api_key)
        assert client._sdk is not None
        assert client._sdk.api_key == fake_api_key
        assert client.api_key == fake_api_key

    def test_init_requires_key(self):
        with pytest.raises(ValueError, match="API Key 不能為空"):
            ByseClient(api_key="")

    def test_account_info_delegates(self, fake_api_key, sample_account_info):
        client = ByseClient(api_key=fake_api_key)
        with patch.object(client._sdk, "account_info", return_value=sample_account_info) as mock:
            result = client.account_info()
            assert result == sample_account_info
            mock.assert_called_once()

    def test_file_list_delegates_with_all_params(self, fake_api_key, sample_file_list):
        client = ByseClient(api_key=fake_api_key)
        with patch.object(client._sdk, "file_list", return_value=sample_file_list) as mock:
            client.file_list(fld_id=5, title="test", per_page=10, page=2, public=1)
            mock.assert_called_once_with(fld_id=5, title="test", per_page=10, page=2, public=1)

    def test_set_folder_uses_file_edit(self, fake_api_key):
        """set_folder 應透過 file_edit(folder_id=...) 走 SDK"""
        client = ByseClient(api_key=fake_api_key)
        with patch.object(client._sdk, "file_edit", return_value={"status": 200}) as mock:
            client.set_folder("abc12345", 42)
            mock.assert_called_once_with("abc12345", folder_id=42)

    def test_remote_upload_status_maps_to_remote_status(self, fake_api_key):
        """remote_upload_status 應對應到 SDK 的 remote_status"""
        client = ByseClient(api_key=fake_api_key)
        with patch.object(client._sdk, "remote_status", return_value={"status": 200}) as mock:
            client.remote_upload_status("abc12345")
            mock.assert_called_once_with("abc12345")
