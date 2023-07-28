from unittest.mock import MagicMock

import pytest

from coregio import utils


@pytest.mark.parametrize("status_code", [200, 400, 500])
def test_handle_response(status_code: int) -> None:
    resp = MagicMock()
    resp.status_code = status_code
    utils.handle_response(resp)


def test_add_session_retries() -> None:
    session = MagicMock()
    reps = utils.add_session_retries(session)

    assert reps is None
    assert session.mount.call_count == 2


@pytest.mark.parametrize(
    ["url", "expected_url"],
    [
        ("quay.io", "https://quay.io"),
        ("http://quay.io", "http://quay.io"),
    ],
)
def test_add_scheme_if_missing(
    url: str,
    expected_url: str,
) -> None:
    result_url = utils.add_scheme_if_missing(url)

    assert result_url == expected_url
