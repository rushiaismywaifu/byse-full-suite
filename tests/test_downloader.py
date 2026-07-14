"""tests/test_downloader.py - downloader.py 工具函式測試 (不打真實 API)"""

import pytest

from byse_full_suite.downloader import extract_code, guess_domain, build_urls


class TestExtractCode:
    """filecode 提取測試"""

    def test_pure_code(self):
        assert extract_code("abc12345") == "abc12345"

    def test_e_url(self):
        assert extract_code("https://byse.sx/e/abc12345") == "abc12345"

    def test_download_url(self):
        assert extract_code("https://bysedikamoum.com/download/abc12345") == "abc12345"

    def test_d_url(self):
        assert extract_code("https://byse.sx/d/abc12345") == "abc12345"

    def test_with_html_suffix(self):
        assert extract_code("https://byse.sx/e/abc12345.html") == "abc12345"

    def test_with_trailing_slash(self):
        assert extract_code("https://byse.sx/e/abc12345/") == "abc12345"

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError, match="無法從"):
            extract_code("https://example.com/short")


class TestGuessDomain:
    """域名解析測試"""

    def test_extracts_domain(self):
        assert guess_domain("https://bysedikamoum.com/download/abc12345") == "bysedikamoum.com"

    def test_default_when_no_scheme(self):
        assert guess_domain("abc12345") == "byse.sx"

    def test_default_when_parse_fail(self):
        # malformed URL 應 fallback 到 byse.sx
        assert guess_domain("not a url at all") == "byse.sx"


class TestBuildUrls:
    """URL 構建測試"""

    def test_returns_list(self):
        urls = build_urls("abc12345")
        assert isinstance(urls, list)
        assert len(urls) > 0

    def test_includes_original_domain(self):
        urls = build_urls("abc12345", original_domain="bysedikamoum.com")
        assert any("bysedikamoum.com" in u for u in urls)

    def test_includes_byse_sx_fallback(self):
        urls = build_urls("abc12345", original_domain="bysedikamoum.com")
        assert any("byse.sx" in u for u in urls)
