"""
Utilities for http queries
"""
import logging
import re
from typing import Any

from requests import Session
from requests.adapters import HTTPAdapter, Retry

LOGGER = logging.getLogger(__name__)


def handle_response(resp: Any) -> Any:
    """
    Handle and log API response

    Args:
        resp (Any): API response
    """
    service_name = "Registry API"
    if 400 <= resp.status_code < 500:
        LOGGER.warning(
            "%s: Incomplete or incorrect data given to API: %s - %s",
            service_name,
            resp.status_code,
            resp.text,
            extra={"url": resp.url},
        )
    elif 500 <= resp.status_code < 600:
        LOGGER.error(
            "%s: Unexpected API response: %s - %s",
            service_name,
            resp.status_code,
            resp.text,
            extra={"url": resp.url},
        )
    else:
        LOGGER.debug(
            "%s: Successful API request: %s - %s",
            service_name,
            resp.status_code,
            resp.text,
            extra={"url": resp.url},
        )


def add_session_retries(
    session: Session,
    total: int = 10,
    backoff_factor: int = 1,
    status_forcelist: Any = None,
) -> None:
    """
    Adds retries to a requests HTTP/HTTPS session.
    The default values provide exponential backoff for a max wait of ~8.5 mins

    Reference the urllib3 documentation for more details about the kwargs.

    Args:
        session (Session): A requests session
        total (int): See urllib3 docs
        backoff_factor (int): See urllib3 docs
        status_forcelist (tuple[int]|None): See urllib3 docs
    """
    if status_forcelist is None:
        status_forcelist = (408, 500, 502, 503, 504)
    retries = Retry(
        total=total,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        # Don't raise a MaxRetryError for codes in status_forcelist.
        # This allows for more graceful exception handling using
        # Response.raise_for_status.
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)


def add_scheme_if_missing(url: str) -> str:
    """
    Add https:// to the url if it does not contain a scheme.

    Args:
        url: Url to check

    Returns:
        str: Url containing a scheme
    """
    if not re.search(r"^[A-Za-z0-9+.\-]+://", url):
        return f"https://{url}"
    return url
