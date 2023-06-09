from unittest.mock import MagicMock, patch

import pytest

from coregio import registry_auth


@pytest.fixture()
def bearer_auth():
    return registry_auth.HTTPBearerAuth("foo")


def test_HTTPBasicAuthWithB64() -> None:
    response = MagicMock()
    response.headers = {}
    auth = registry_auth.HTTPBasicAuthWithB64("foo")

    resp = auth(response)

    assert resp.headers["Authorization"] == "Basic foo"


@patch("coregio.registry_auth.HTTPBearerAuth._set_header")
@patch("coregio.registry_auth.HTTPBearerAuth._get_repo_from_url")
def test_HTTPBearerAuth(
    mock__get_repo_from_url: MagicMock,
    mock__set_header: MagicMock,
    bearer_auth: registry_auth.HTTPBearerAuth,
) -> None:
    response = MagicMock()

    mock__get_repo_from_url.return_value = "repo123"

    resp = bearer_auth(response)

    mock__set_header.assert_not_called()

    bearer_auth.token_cache["repo123"] = "bar"
    bearer_auth(response)
    mock__set_header.assert_called_once_with(response, "repo123")
    response.register_hook.assert_called_once()


def test_HTTPBearerAuth_auth_token(
    bearer_auth: registry_auth.HTTPBearerAuth,
) -> None:
    response = MagicMock()

    bearer_auth.last_auth_header = "foo"
    assert bearer_auth.auth_header == "foo"


@patch("coregio.registry_auth.extract_cookies_to_jar")
@patch("coregio.registry_auth.HTTPBearerAuth._get_token")
def test_HTTPBearerAuth_handle_401(
    mock_get_token: MagicMock,
    mock_extract_cookies_to_jar: MagicMock,
    bearer_auth: registry_auth.HTTPBearerAuth,
) -> None:
    response = MagicMock()
    response.status_code = 400
    response.headers = {"www-authenticate": "foo"}

    resp = bearer_auth.handle_401(response, "foo")

    assert resp == response

    response = MagicMock()
    response.status_code = 401
    response.headers = {"www-authenticate": "foo"}
    resp = bearer_auth.handle_401(response, "foo")

    assert resp == response

    response = MagicMock()
    response.status_code = 401
    response.headers = {"www-authenticate": "bearer realm=foo"}

    mock_get_token.return_value = "bar"
    resp = bearer_auth.handle_401(response, "foo")

    assert bearer_auth.token_cache["foo"] == "bar"


@patch("coregio.registry_auth.requests.get")
@patch("coregio.registry_auth.parse_dict_header")
def test_HTTPBearerAuth_get_token(
    mock_parse_dict_header: MagicMock,
    mock_get: MagicMock,
    bearer_auth: registry_auth.HTTPBearerAuth,
) -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_get.return_value = mock_response
    resp = bearer_auth._get_token("foo", "repo")

    assert resp == None

    mock_response = MagicMock()
    mock_response.json.return_value = {"token": "bar"}
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    resp = bearer_auth._get_token("foo", "repo")

    assert resp == "bar"


def test_HTTPBeaderAuth__set_header(bearer_auth: registry_auth.HTTPBearerAuth) -> None:
    response = MagicMock()
    response.headers = {}
    bearer_auth.token_cache["foo"] = "bar"
    bearer_auth._set_header(response, "foo")

    assert response.headers["Authorization"] == "Bearer bar"


def test_HTTPBeaderAuth__get_repo_from_url(
    bearer_auth: registry_auth.HTTPBearerAuth,
) -> None:
    url = "https://foo.bar/baz"
    repo = bearer_auth._get_repo_from_url(url)

    assert repo is None

    url = "https://foo.bar/v2/baz/manifests/latest"
    repo = bearer_auth._get_repo_from_url(url)

    assert repo == "baz"
