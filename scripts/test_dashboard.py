#!/usr/bin/env python3
"""Run isolated browser regressions against a running dashboard.

Usage:
    UV_CACHE_DIR=/tmp/byse-uv-cache PLAYWRIGHT_BROWSERS_PATH=/tmp/byse-playwright \
        uv run --no-project --with playwright python scripts/test_dashboard.py

BASE_URL defaults to http://127.0.0.1:5000. Every API, health, and upload
request is mocked; this script never changes a real Byse account.
"""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Browser, Page, Route, expect, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
INJECTION_TITLE = '<img src=x onerror="window.__byseInjected=true">'
TOKEN = "browser-regression-token"


class MockAPI:
    def __init__(self, configured: bool = True, requires_token: bool = False):
        self.configured = configured
        self.requires_token = requires_token
        self.calls: list[dict] = []
        self.failures: dict[str, tuple[int, dict]] = {}
        self.upload_failure = False
        self.files = [
            {
                "file_code": f"video{index:07d}",
                "title": INJECTION_TITLE if index == 0 else f"Regression video {index}",
                "length": str(120 + index),
                "views": 100 + index,
                "canplay": index % 2,
                "file_size": 15728640,
                "uploaded": "2026-09-01 10:00:00",
            }
            for index in range(21)
        ]

    def handle(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if path not in {"/health", "/upload"} and not path.startswith("/api/"):
            # The test uses only locally served assets. An unexpected third-party
            # call must not leak credentials or contact an actual upload server.
            if parsed.netloc != urlsplit(BASE_URL).netloc:
                route.abort()
            else:
                route.continue_()
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        self.calls.append(
            {
                "path": path,
                "query": query,
                "headers": request.headers,
                "method": request.method,
                "body": request.post_data if path == "/upload" else None,
            }
        )
        if path == "/health":
            self.fulfill(
                route,
                {
                    "service": "byse-proxy",
                    "configured": self.configured,
                    "requires_token": self.requires_token,
                },
            )
            return

        if self.requires_token and request.headers.get("authorization") != f"Bearer {TOKEN}":
            self.fulfill(route, {"error": "Invalid or missing proxy token"}, 401)
            return
        if path in self.failures:
            status, payload = self.failures[path]
            self.fulfill(route, payload, status)
            return
        if path == "/upload":
            if self.upload_failure:
                self.fulfill(route, {"error": "Upload regression failure"}, 500)
            else:
                self.fulfill(
                    route,
                    {
                        "files": [
                            {"filecode": "uploaded0001", "filename": "sample.mp4", "status": "OK"}
                        ]
                    },
                )
            return

        result: object
        if path == "/api/account/info":
            result = {
                "email": "regression@example.com",
                "balance": "10.50",
                "storage": "1024",
                "storage_used": "100",
                "files_total": 42,
            }
        elif path == "/api/account/stats":
            result = [
                {
                    "day": f"2026-09-0{index}",
                    "date": f"2026-09-0{index}",
                    "views": index * 10,
                    "profit": "0.10",
                }
                for index in range(1, 6)
            ]
        elif path == "/api/file/list":
            title = query.get("title", [""])[0].lower()
            files = [file for file in self.files if title in file["title"].lower()]
            page = int(query.get("page", ["1"])[0])
            size = int(query.get("per_page", ["20"])[0])
            result = {"files": files[(page - 1) * size : page * size], "total": len(files)}
        elif path == "/api/folder/list":
            result = {"folders": [{"fld_id": 7, "name": "Browser tests", "code": "testfolder"}]}
        elif path == "/api/encoding/list":
            result = []
        elif path == "/api/file/info":
            result = [self.files[0]]
        elif path == "/api/upload/url":
            result = {"filecode": "remote000001"}
        elif path == "/api/remote/status":
            result = {"filecode": "remote000001", "status": "DONE"}
        elif path in {"/api/files/deleted", "/api/files/dmca"}:
            result = []
        else:
            result = {}
        self.fulfill(route, {"status": 200, "msg": "OK", "result": result})

    @staticmethod
    def fulfill(route: Route, payload: object, status: int = 200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


class Scenario:
    def __init__(self, browser: Browser, api: MockAPI, width: int = 1440):
        self.context = browser.new_context(viewport={"width": width, "height": 1000})
        self.context.route("**/*", api.handle)
        self.page = self.context.new_page()
        self.errors: list[str] = []
        self.console_errors: list[str] = []
        self.dialogs: list[str] = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on(
            "console",
            lambda message: (
                self.console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        self.page.on("dialog", self.dismiss_dialog)

    def dismiss_dialog(self, dialog):
        self.dialogs.append(dialog.type)
        dialog.dismiss()

    def open(self):
        self.page.goto(BASE_URL)
        self.page.wait_for_load_state("networkidle")
        # Inspect the rendered DOM only after the application has initialized.
        assert self.page.locator("main").count() == 1, "Dashboard main landmark missing"

    def close(self):
        assert not self.errors, f"Uncaught browser errors: {self.errors}"
        assert not self.dialogs, f"Unexpected blocking browser dialogs: {self.dialogs}"
        self.context.close()


def invoke(page: Page, function: str, *args):
    """Use a public action when a scenario needs deterministic refresh timing."""
    return page.evaluate("([name, args]) => window[name](...args)", [function, list(args)])


def assert_no_overflow(page: Page):
    width = page.evaluate(
        "({viewport:innerWidth, body:document.body.scrollWidth, document:document.documentElement.scrollWidth})"
    )
    if max(width["body"], width["document"]) > width["viewport"] + 1:
        width["tab"] = page.locator("#pageTitle").inner_text()
        width["overflowing"] = page.evaluate(
            """() => [...document.querySelectorAll('main *, footer *')]
              .filter(element => element.getBoundingClientRect().right > innerWidth + 1)
              .slice(0, 12).map(element => ({tag: element.tagName, id: element.id,
                className: element.className, right: element.getBoundingClientRect().right}))"""
        )
        raise AssertionError(width)


def navigate(page: Page, tab: str):
    button = page.locator(f"button[data-tab='{tab}']")
    if button.is_visible():
        button.click()
    else:
        invoke(page, "switchTab", tab)
    expect(page.locator(f"#tab-{tab}")).to_be_visible()


def disconnected_and_demo(browser: Browser):
    api = MockAPI(configured=False)
    scenario = Scenario(browser, api)
    scenario.open()
    page = scenario.page
    assert not any(
        call["path"].startswith("/api/") for call in api.calls
    ), "Disconnected startup queried upstream"
    assert not scenario.dialogs
    invoke(page, "toggleDemo")
    page.wait_for_load_state("networkidle")
    tabs = page.locator("button[data-tab]").evaluate_all(
        "buttons => [...new Set(buttons.map(b => b.dataset.tab))]"
    )
    assert len(tabs) == 6, tabs
    for tab in tabs:
        navigate(page, tab)
        assert_no_overflow(page)
    navigate(page, tabs[0])
    page.screenshot(path="/tmp/byse-desktop.png", full_page=True, animations="disabled")
    page.set_viewport_size({"width": 390, "height": 844})
    for tab in tabs:
        navigate(page, tab)
        assert_no_overflow(page)
        if tab == "files":
            page.screenshot(
                path="/tmp/byse-mobile-files.png", full_page=True, animations="disabled"
            )
    navigate(page, tabs[0])
    page.screenshot(path="/tmp/byse-mobile.png", full_page=True, animations="disabled")
    assert not any(
        call["path"].startswith("/api/") for call in api.calls
    ), "Demo mode sent an upstream request"
    assert not scenario.console_errors, scenario.console_errors
    scenario.close()


def connected_files_and_errors(browser: Browser):
    api = MockAPI()
    scenario = Scenario(browser, api)
    scenario.open()
    page = scenario.page
    expect(page.locator("#metricFiles")).to_have_text("42")
    expect(page.locator("#metricViews")).to_have_text("150")
    expect(page.locator("#metricBalance")).to_have_text("10.5")
    navigate(page, "files")
    invoke(page, "loadFileList")
    expect(page.locator("#fileTable")).to_contain_text(INJECTION_TITLE)
    assert page.locator("#fileTable img").count() == 0, "Server title became an HTML element"
    assert not page.evaluate("Boolean(window.__byseInjected)")
    assert all("undefined" not in str(call["query"]) for call in api.calls)

    page.locator("#fileTitle").fill("Regression video 20")
    page.locator("#fileTitle").press("Enter")
    expect(page.locator("#fileTable")).to_contain_text("Regression video 20")
    expect(page.locator("#fileTable")).not_to_contain_text("Regression video 19")
    page.locator("#fileTitle").fill("")
    page.locator("#fileTitle").press("Enter")
    expect(page.locator("#fileTable")).to_contain_text(INJECTION_TITLE)
    page.locator("#nextPage").click()
    expect(page.locator("#fileTable")).to_contain_text("Regression video 20")
    assert any(
        call["query"].get("page") == ["2"] for call in api.calls if call["path"] == "/api/file/list"
    )
    assert all("undefined" not in str(call["query"]) for call in api.calls)

    for status, payload, message in [
        (500, {"error": "Upstream regression failure"}, "Upstream regression failure"),
        (200, {"status": 400, "msg": "Invalid operation"}, "不支援這項操作"),
    ]:
        api.failures["/api/file/list"] = (status, payload)
        invoke(page, "loadFileList")
        expect(page.locator("#fileTable")).to_contain_text(message)
    api.failures["/api/file/list"] = (401, {"error": "Authentication regression failure"})
    invoke(page, "loadFileList")
    expect(page.locator("#connectionBanner")).to_contain_text("驗證已失效")
    expect(page.locator("#metricFiles")).to_have_text("—")
    api.failures.clear()
    scenario.close()


def token_upload_and_embed(browser: Browser):
    api = MockAPI(requires_token=True)
    scenario = Scenario(browser, api)
    scenario.open()
    page = scenario.page
    invoke(page, "openSettings")
    page.locator("#connectionMode").select_option("proxy")
    page.locator("#proxyToken").fill(TOKEN)
    page.locator("#connectionForm").evaluate("form => form.requestSubmit()")
    expect(page.locator("#connectionDialog")).not_to_be_visible()
    expect(page.locator("body")).to_contain_text("42")
    account_calls = [call for call in api.calls if call["path"] == "/api/account/info"]
    assert account_calls and account_calls[-1]["headers"].get("authorization") == f"Bearer {TOKEN}"
    assert all("key" not in call["query"] for call in api.calls)

    navigate(page, "upload")
    page.locator("#localFile").set_input_files(
        {"name": "sample.mp4", "mimeType": "video/mp4", "buffer": b"mock upload"}
    )
    expect(page.locator("#uploadQueue")).to_contain_text("sample.mp4")
    page.locator("#uploadStart").click()
    expect(page.locator("#uploadQueue")).to_contain_text("uploaded0001")
    upload_calls = [call for call in api.calls if call["path"] == "/upload"]
    assert upload_calls and upload_calls[-1]["headers"].get("authorization") == f"Bearer {TOKEN}"
    assert 'name="key"' not in (upload_calls[-1]["body"] or "")
    api.upload_failure = True
    page.locator("#localFile").set_input_files(
        {"name": "failure.mp4", "mimeType": "video/mp4", "buffer": b"failed upload"}
    )
    page.locator("#uploadStart").click()
    expect(page.locator("#uploadQueue")).to_contain_text("Upload regression failure")

    api.failures["/api/remote/add"] = (200, {"status": 400, "msg": "Invalid operation"})
    page.locator("#remoteUrl").fill("https://example.com/remote.mp4")
    page.get_by_role("button", name="開始匯入", exact=True).click()
    expect(page.locator("#remoteFileCode")).to_have_value("remote000001")
    assert any(call["path"] == "/api/upload/url" for call in api.calls)
    page.get_by_role("button", name="查看進度", exact=True).click()
    expect(page.locator("#remoteResult")).to_contain_text("DONE")

    navigate(page, "tools")
    page.locator("#toolFileCode").fill("video0000001")
    page.locator("#toolDomain").fill("byse.sx")
    invoke(page, "generateEmbedAdvanced")
    expect(page.locator("#toolResult")).to_contain_text("https://byse.sx/e/video0000001")
    assert page.locator("#toolIframePreview iframe").count() == 0
    page.locator("#toolDomain").fill('byse.sx" onload="window.__byseInjected=true')
    invoke(page, "generateEmbedAdvanced")
    expect(page.locator("#toolResult")).to_contain_text("播放器網域請使用有效的 HTTPS 網域")
    assert page.locator("#toolIframePreview iframe").count() == 0
    assert not page.evaluate("Boolean(window.__byseInjected)")
    page.locator("#toolDomain").fill("byse.sx")
    invoke(page, "generateEmbedAdvanced")
    invoke(page, "previewEmbed")
    expect(page.locator("#toolIframePreview iframe")).to_have_attribute(
        "src", "https://byse.sx/e/video0000001"
    )
    scenario.close()


def main():
    scenarios = {
        "demo": disconnected_and_demo,
        "files": connected_files_and_errors,
        "upload": token_upload_and_embed,
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", choices=scenarios)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name in args.scenario or scenarios:
                test = scenarios[name]
                test(browser)
                print(f"PASS {test.__name__}")
        except BaseException:
            if browser.contexts and browser.contexts[-1].pages:
                browser.contexts[-1].pages[-1].screenshot(
                    path="/tmp/byse-failure.png", full_page=True, animations="disabled"
                )
            raise
        finally:
            browser.close()
    print(
        "Dashboard browser regressions passed. Screenshots: /tmp/byse-desktop.png, /tmp/byse-mobile.png"
    )


if __name__ == "__main__":
    main()
