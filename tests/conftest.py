"""tests/conftest.py - pytest 共用 fixtures"""

import sys
from pathlib import Path

import pytest

# 把專案根目錄加入 sys.path, 讓 import byse_full_suite 可以運作
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def fake_api_key():
    return "test_key_12345"


@pytest.fixture
def sdk(fake_api_key):
    """建立一個不會真正打 API 的 SDK 實例"""
    from byse_full_suite.sdk import ByseSDK

    return ByseSDK(api_key=fake_api_key, base_url="https://api.byse.sx")


@pytest.fixture
def sample_account_info():
    """模擬 account/info 回應"""
    return {
        "status": 200,
        "msg": "OK",
        "result": {
            "email": "test@example.com",
            "balance": "10.50",
            "storage": "1024",
            "storage_used": "100",
            "files_total": 42,
        },
    }


@pytest.fixture
def sample_file_list():
    """模擬 file/list 回應"""
    return {
        "status": 200,
        "msg": "OK",
        "result": {
            "files": [
                {
                    "file_code": "abc12345",
                    "title": "Test Video",
                    "length": "120",
                    "views": 100,
                    "canplay": 1,
                },
                {
                    "file_code": "def67890",
                    "title": None,  # 測試 None 不 crash
                    "length": "60",
                    "views": 50,
                    "canplay": 0,
                },
            ],
            "total": 2,
        },
    }
