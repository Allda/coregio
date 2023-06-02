from unittest.mock import MagicMock

from regapi import registry_auth


def test_HTTPBasicAuthWithB64() -> None:
    response = MagicMock()
    response.headers = {}
    auth = registry_auth.HTTPBasicAuthWithB64("foo")

    resp = auth(response)

    assert resp.headers["Authorization"] == "Basic foo"
