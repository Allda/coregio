from typing import Any, Dict, Set
from unittest.mock import MagicMock, patch

import pytest
import requests

from coregio.registry_api import ContainerRegistry


@pytest.mark.parametrize(
    ["url", "expected_url"],
    [
        ("quay.io", "https://quay.io"),
        ("http://quay.io", "http://quay.io"),
        ("quay.io:8080", "https://quay.io:8080"),
        ("quay.io/path", "https://quay.io"),
        ("http://quay.io:8080/path", "http://quay.io:8080"),
        ("registry-1.docker.io", "https://index.docker.io"),
        ("hub.docker.com", "https://index.docker.io"),
        ("registry.hub.docker.com", "https://index.docker.io"),
        ("docker.io", "https://index.docker.io"),
        ("http://docker.io", "http://index.docker.io"),
        ("docker.io:8080", "https://index.docker.io:8080"),
        ("docker.io/path", "https://index.docker.io"),
        ("http://docker.io:8080/path", "http://index.docker.io:8080"),
    ],
)
def test__normalize_registry_url(
    url: str,
    expected_url: str,
) -> None:
    result_url = ContainerRegistry._normalize_registry_url(url)

    assert result_url == expected_url


@pytest.mark.parametrize(
    ["registry", "cfg", "auth", "token"],
    [
        ("quay.io", None, None, None),
        ("quay.io", "qwe", None, None),
        ("quay.io", "{}", None, None),
        ("quay.io", "{}", {"auth": "Zm9vOmJhcg=="}, "Zm9vOmJhcg=="),
        ("quay.io", "{}", {"auth": "Zm9vOmJhcg==", "identitytoken": "abc"}, "abc"),
    ],
)
@patch(
    "coregio.registry_api.ContainerRegistry._select_registry_auth_token_from_docker_config"
)
def test__get__get_auth_token(
    mock_select_token: MagicMock,
    registry: str,
    cfg: Any,
    auth: Any,
    token: Any,
) -> None:
    registry_api = ContainerRegistry(url=registry, docker_cfg=cfg)
    mock_select_token.return_value = auth

    resp_token = registry_api._get_auth_token()

    assert resp_token == token


@pytest.mark.parametrize(
    ["registry", "docker_config", "expected_token"],
    [
        ("quay.io", {}, None),
        ("quay.io", {"": "123"}, None),
        ("quay.io", {"https://": "123"}, None),
        ("quay.io", {"https://docker.io": "123"}, None),
        ("quay.io", {"quay.io": "123"}, "123"),
        ("quay.io", {"quay.io/ns": "123"}, "123"),
        ("quay.io", {"https://quay.io/ns": "123"}, "123"),
        ("quay.io", {"https://quay.io:5000/ns": "123"}, "123"),
        ("quay.io", {"https://quay.io/repo/imag:tag": "123"}, "123"),
        ("quay.io", {"https://registry.quay.io/repo/imag:tag": "123"}, "123"),
        ("quay.io", {"https://api.registry.quay.io": "123"}, "123"),
        ("docker.io", {"https://docker.io": "123"}, "123"),
        ("docker.io", {"https://index.docker.io": "123"}, "123"),
        ("registry-1.docker.io", {"https://index.docker.io": "123"}, "123"),
    ],
)
def test__select_registry_auth_token_from_docker_config(
    registry: str, docker_config: Dict[str, Any], expected_token: Any
) -> None:
    registry_api = ContainerRegistry(registry, "")

    token = registry_api._select_registry_auth_token_from_docker_config(docker_config)

    assert token == expected_token


@patch("coregio.registry_api.ContainerRegistry._get_auth_token")
def test__get_session(mock_auth_token: MagicMock) -> None:
    mock_auth_token.return_value = "Zm9vOmJhcg=="
    registry = ContainerRegistry("test-quay.io", "foo")

    mock_auth = MagicMock()

    def auth_method(token: Any, proxy: Any = None) -> Any:
        return mock_auth

    session = registry._get_session(auth_method)

    assert session.auth == mock_auth


@pytest.mark.parametrize(
    ["status_codes"],
    [
        ((200,),),
        ((401, 200),),
        ((401, 401, 401),),
    ],
)
@patch("coregio.registry_api.ContainerRegistry._get_session")
def test__get(mock_session: MagicMock, status_codes: Set[int]) -> None:
    sessions = []
    for code in status_codes:
        expected_response = requests.Response()
        expected_response.status_code = code

        session = MagicMock()
        session.get.return_value = expected_response
        session.auth.auth_header = "Bearer foo"
        sessions.append(session)
    mock_session.side_effect = sessions

    registry = ContainerRegistry("test-quay.io", "foo")
    resp = registry._get("foo", {}, {}, True)
    assert resp.status_code == sessions[-1].get.return_value.status_code
    assert registry.auth_header == "Bearer foo"


@patch("coregio.utils.handle_response")
@patch("coregio.registry_api.ContainerRegistry._get")
def test_get_request(
    mock_get: MagicMock,
    mock_handle: MagicMock,
    monkeypatch: Any,
) -> None:
    mock_handle.return_value = None
    resp = ContainerRegistry("foo", "bar").get_request("/v1/api")
    assert resp == mock_get.return_value
    mock_get.assert_called_once_with("https://foo/v1/api", params=None, headers=None)


@patch("coregio.registry_api.ContainerRegistry.get_request")
def test_paginated_response(mock_get: MagicMock) -> None:
    get = MagicMock()
    get.json.return_value = {"foo": ["bar1", "bar2"]}
    get.links = {"next": {"url": "test.url"}}
    mock_get.return_value = get

    registry = ContainerRegistry("foo", "bar")
    result = registry.get_paginated_response("v2/foo", "foo", page_size=1, limit=1)
    assert result == ["bar1"]
    mock_get.assert_called_once_with("v2/foo", headers=None, params={"n": 1})

    get.links = {}
    mock_get.return_value = get
    mock_get.reset_mock()
    result = registry.get_paginated_response("v2/foo", "foo")
    assert result == ["bar1", "bar2"]


@patch("coregio.utils.handle_response")
@patch("coregio.registry_api.ContainerRegistry.get_request")
def test_get_manifest_raw(
    mock_get: MagicMock,
    mock_handle: MagicMock,
) -> None:
    mock_response = MagicMock()
    mock_get.return_value = mock_response
    mock_handle.return_value = None
    registry = ContainerRegistry("registry", "docker_cfg")
    result = registry.get_manifest_raw("repo", "ref")

    assert result == mock_response
    mock_get.assert_called_once_with(
        "v2/repo/manifests/ref",
        headers={
            "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json"
        },
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_get.side_effect = requests.HTTPError(response=mock_resp)
    with pytest.raises(requests.HTTPError):
        registry.get_manifest("repo", "ref")


@patch("coregio.registry_api.ContainerRegistry.get_manifest_raw")
def test_get_manifest(
    mock_get_manifest_raw: MagicMock,
) -> None:
    manifest_rsp = MagicMock()
    mock_get_manifest_raw.return_value = manifest_rsp
    registry_api = ContainerRegistry(url="registry")
    result = registry_api.get_manifest("repo", "ref")

    assert result == manifest_rsp.json()
    mock_get_manifest_raw.assert_called_once_with("repo", "ref", None)

    mock_get_manifest_raw.reset_mock()
    result = registry_api.get_manifest("repo", "ref", is_headers=True)

    assert result == manifest_rsp.headers
    mock_get_manifest_raw.assert_called_once_with("repo", "ref", None)


@patch("coregio.registry_api.ContainerRegistry.get_manifest")
def test_get_manifest_headers(
    mock_get_manifest: MagicMock,
) -> None:
    manifest = MagicMock()
    mock_get_manifest.return_value = manifest
    registry_api = ContainerRegistry(url="registry")
    result = registry_api.get_manifest_headers("repo", "ref")

    assert result == manifest
    mock_get_manifest.assert_called_once_with("repo", "ref", is_headers=True)


@patch("coregio.registry_api.ContainerRegistry.get_paginated_response")
def test_get_tags(mock_get: MagicMock) -> None:
    mock_get.return_value = ["foo", "bar"]

    registry = ContainerRegistry("registry", "docker_cfg")
    result = registry.get_tags("repo")

    assert result == ["foo", "bar"]
    mock_get.assert_called_once_with(
        "v2/repo/tags/list", list_name="tags", page_size=100, limit=2000
    )
