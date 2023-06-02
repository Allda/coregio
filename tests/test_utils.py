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
