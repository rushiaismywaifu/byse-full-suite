"""Dashboard proxy regression tests; no requests reach the real Byse API."""

from io import BytesIO
from unittest.mock import Mock

import pytest
import requests

from byse_full_suite import server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("BYSE_API_KEY", raising=False)
    monkeypatch.delenv("BYSE_PROXY_TOKEN", raising=False)
    monkeypatch.setitem(server.app.config, "TESTING", True)
    return server.app.test_client()


@pytest.fixture
def upstream(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"status": 200, "result": {"email": "test@example.com"}}
    get = Mock(return_value=response)
    post = Mock(return_value=response)
    monkeypatch.setattr(server.requests, "get", get)
    monkeypatch.setattr(server.requests, "post", post)
    return get, post


@pytest.mark.parametrize("api_key,token", [("", ""), ("  ", "  "), ("test-key", "test-token")])
def test_health_exposes_only_setup_state(client, monkeypatch, upstream, api_key, token):
    monkeypatch.setenv("BYSE_API_KEY", api_key)
    monkeypatch.setenv("BYSE_PROXY_TOKEN", token)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {
        "service": "byse-proxy",
        "configured": bool(api_key.strip()),
        "requires_token": bool(token.strip()),
    }
    assert response.headers["Cache-Control"] == "no-store"
    upstream[0].assert_not_called()
    upstream[1].assert_not_called()


@pytest.mark.parametrize(
    "route,filename,mimetype",
    [
        ("/", "dashboard.html", "text/html"),
        ("/dashboard.html", "dashboard.html", "text/html"),
        ("/dashboard.css", "dashboard.css", "text/css"),
        ("/dashboard.js", "dashboard.js", None),
    ],
)
def test_assets_are_served_from_package_in_any_cwd(
    client, monkeypatch, tmp_path, route, filename, mimetype
):
    monkeypatch.chdir(tmp_path)

    response = client.get(route)

    assert response.status_code == 200
    assert response.data == (server.DASHBOARD_DIRECTORY / filename).read_bytes()
    if mimetype:
        assert response.mimetype == mimetype
    else:
        assert response.mimetype in {"text/javascript", "application/javascript"}


@pytest.mark.parametrize(
    "route", ["/server.py", "/sdk.py", "/static/server.py", "/dashboard.css/../server.py"]
)
def test_package_source_is_not_public(client, route):
    assert client.get(route).status_code == 404


@pytest.mark.parametrize("route,method", [("/api/account/info", "get"), ("/upload", "post")])
@pytest.mark.parametrize("authorization", ["", "Bearer wrong-token", "Basic test-token"])
def test_proxy_token_blocks_unauthorized_requests(
    client, monkeypatch, upstream, route, method, authorization
):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")
    monkeypatch.setenv("BYSE_PROXY_TOKEN", "test-token")

    response = getattr(client, method)(route, headers={"Authorization": authorization})

    assert response.status_code == 401
    upstream[0].assert_not_called()
    upstream[1].assert_not_called()


def test_valid_token_allows_request(client, monkeypatch, upstream):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")
    monkeypatch.setenv("BYSE_PROXY_TOKEN", "test-token")

    response = client.get("/api/account/info", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    upstream[0].assert_called_once()


def test_unknown_endpoint_never_reaches_upstream(client, monkeypatch, upstream):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")

    response = client.get("/api/not/allowed")

    assert response.status_code == 403
    upstream[0].assert_not_called()


@pytest.mark.parametrize(
    "endpoint", ["file/hls", "file/premium_link", "file/direct_link", "account/hls"]
)
def test_existing_hls_tool_candidates_are_allowed(client, monkeypatch, upstream, endpoint):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")

    response = client.get(f"/api/{endpoint}?file_code=example")

    assert response.status_code == 200
    assert upstream[0].call_args[0][0] == f"{server.BASE_API}/{endpoint}"


@pytest.mark.parametrize("method", ["get", "post"])
def test_environment_key_takes_precedence(client, monkeypatch, upstream, method):
    monkeypatch.setenv("BYSE_API_KEY", " server-key ")
    kwargs = {"data": {"key": "form-key", "name": "Example"}} if method == "post" else {}

    response = getattr(client, method)("/api/account/info?key=query-key&page=2", **kwargs)

    assert response.status_code == 200
    called = upstream[0] if method == "get" else upstream[1]
    assert called.call_args[1]["params"] == {"key": "server-key", "page": "2"}
    if method == "post":
        assert called.call_args[1]["data"] == {"key": "server-key", "name": "Example"}


def test_query_key_fallback_is_preserved(client, upstream):
    assert client.get("/api/account/info?key=temporary-key").status_code == 200
    assert upstream[0].call_args[1]["params"]["key"] == "temporary-key"


def test_form_key_fallback_is_preserved(client, upstream):
    response = client.post("/api/account/info?key=query-key", data={"key": "form-key"})
    assert response.status_code == 200
    assert upstream[1].call_args[1]["data"]["key"] == "form-key"


@pytest.mark.parametrize(
    "failure,status",
    [
        (requests.ConnectionError("failed URL https://api.byse.sx/?key=server-key"), 502),
        (RuntimeError("unexpected server-key"), 500),
    ],
)
def test_api_errors_do_not_expose_credentials(client, monkeypatch, upstream, failure, status):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")
    upstream[0].side_effect = failure

    response = client.get("/api/account/info")

    assert response.status_code == status
    assert "server-key" not in response.get_data(as_text=True)
    assert response.json["error"]


@pytest.mark.parametrize("phase", ["discovery", "upload"])
def test_upload_network_errors_do_not_expose_credentials(client, monkeypatch, upstream, phase):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")
    failure = requests.ConnectionError("failed URL https://upload.byse.sx/?key=server-key")
    if phase == "discovery":
        upstream[0].side_effect = failure
    else:
        upstream[0].return_value.json.return_value = {"result": "https://upload.byse.sx/"}
        upstream[1].side_effect = failure

    response = client.post("/upload", data={"file": (BytesIO(b"video"), "sample.mp4")})

    assert response.status_code == 502
    assert "server-key" not in response.get_data(as_text=True)
    assert response.json["error"]


@pytest.mark.parametrize("payload", [{"error": "server-key"}, None, []])
def test_bad_upload_discovery_response_is_safe(client, monkeypatch, upstream, payload):
    monkeypatch.setenv("BYSE_API_KEY", "server-key")
    upstream[0].return_value.json.return_value = payload

    response = client.post("/upload", data={"file": (BytesIO(b"video"), "sample.mp4")})

    assert response.status_code == 502
    assert "server-key" not in response.get_data(as_text=True)
    upstream[1].assert_not_called()
