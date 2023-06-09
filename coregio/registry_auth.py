"""
Registry authentication module.
Copyright (c) 2018, 2019 Red Hat, Inc
All rights reserved.

This software may be modified and distributed under the terms
of the BSD license. See the LICENSE file for details.
"""

from __future__ import absolute_import, unicode_literals

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from requests.auth import AuthBase
from requests.cookies import extract_cookies_to_jar
from requests.utils import parse_dict_header

DEFAULT_TIMEOUT = (7.0, 15.0)

# This module comes from atomic-reactor
# https://github.com/containerbuildsystem/atomic-reactor/blob/1.6.41/atomic_reactor/auth.py

LOG = logging.getLogger(__name__)


class BearerAuthBase(AuthBase):
    """
    Base class for Bearer token authentication.
    """

    BEARER_PATTERN = re.compile(r"bearer ", flags=re.IGNORECASE)
    V2_REPO_PATTERN = re.compile(r"^/v2/(.*)/(manifests|tags|blobs)/")

    def __init__(self, proxy: Optional[str] = None) -> None:
        """Initialize HTTPBearerAuth object."""
        self.token_cache = {}
        self.proxy = proxy

        self.last_auth_header = None

    def __call__(self, response: Any) -> Any:
        repo = self._get_repo_from_url(response.url)

        if repo in self.token_cache:
            self._set_header(response, repo)
            return response

        def handle_401_with_repo(resp: Any, **kwargs):  # pragma: no cover
            return self.handle_401(resp, repo, **kwargs)

        response.register_hook("response", handle_401_with_repo)
        return response

    def handle_401(self, response: Any, repo: str, **kwargs) -> Any:
        """Fetch Bearer token and retry."""
        if response.status_code != 401:
            return response

        auth_info = response.headers.get("www-authenticate", "")

        if "bearer" not in auth_info.lower():
            return response

        self.token_cache[repo] = self._get_token(auth_info, repo)

        # Consume content and release the original connection
        # to allow our new request to reuse the same one.
        # This pattern was inspired by the source code of
        # requests.auth.HTTPDigestAuth
        # pylint: disable=W0104
        response.content
        response.close()
        retry_request = response.request.copy()
        # pylint: disable=W0212
        extract_cookies_to_jar(retry_request._cookies, response.request, response.raw)
        retry_request.prepare_cookies(retry_request._cookies)

        self._set_header(retry_request, repo)
        retry_response = response.connection.send(retry_request, **kwargs)
        retry_response.history.append(response)
        retry_response.request = retry_request

        return retry_response

    @property
    def auth_header(self) -> Optional[str]:
        """
        Auth header used in the last request.

        Returns:
            Optional[str]: Auth header used in the last request.
        """
        return self.last_auth_header

    def _set_header(self, response: Any, repo: str) -> None:
        self.last_auth_header = f"Bearer {self.token_cache[repo]}"
        response.headers["Authorization"] = self.last_auth_header

    def _get_repo_from_url(self, url: str) -> Optional[str]:
        url_parts = urlparse(url)
        repo = None
        v2_match = self.V2_REPO_PATTERN.search(url_parts.path)
        if v2_match:
            repo = v2_match.group(1)
        return repo

    def _get_token(
        self, auth_info: str, repo: str
    ) -> Optional[str]:  # pragma: no cover
        raise NotImplementedError()


# pylint: disable=too-few-public-methods
class HTTPBearerAuth(BearerAuthBase):  # pragma: no cover
    """
    Performs Bearer authentication for the given Request object.

    username and password are optional. If provided, they will be used
    when fetching the Bearer token from realm. Otherwise, Bearer token
    is retrivied with anonymous access.

    auth_b64 may be provided for authentication (instead of username and
    password).

    Once Bearer token is retrieved, it will be cached and used in subsequent
    requests. Since tokens are specific to repositories, the token cache may
    store multiple tokens.

    Supports registry v2 API only.
    """

    def __init__(self, auth_b64, *args, verify=True, access=None, **kwargs):
        """Initialize HTTPBearerAuth object.

        :param auth_b64: str, base64 credentials as described in RFC 7617
        :param verify: bool, whether or not to verify server identity when
            fetching Bearer token from realm
        :param access: iter<str>, iterable (list, tuple, etc) of access to be
            requested; possible values to be included are 'pull' and/or 'push';
            defaults to ('pull',)
        """
        self.auth_b64 = auth_b64
        self.verify = verify
        self.access = access or ("pull",)

        super().__init__(*args, **kwargs)

    def _get_token(self, auth_info: str, repo: str) -> Optional[str]:
        bearer_info = parse_dict_header(self.BEARER_PATTERN.sub("", auth_info, count=1))
        # If repo could not be determined, do not set scope - implies
        # global access
        if repo:
            bearer_info["scope"] = f"repository:{repo}:{','.join(self.access)}"
        realm = bearer_info.pop("realm")

        realm_auth = None
        if self.auth_b64:
            realm_auth = HTTPBasicAuthWithB64(self.auth_b64)

        realm_response = requests.get(
            realm,
            params=bearer_info,
            verify=self.verify,
            auth=realm_auth,
            timeout=DEFAULT_TIMEOUT,
            proxies={"https": self.proxy} if self.proxy else None,
        )
        if realm_response.status_code != 200:
            LOG.info(
                "Registry challenge %s responded with %d - %s",
                realm,
                realm_response.status_code,
                realm_response.text,
            )
            return None

        response = realm_response.json()

        # Based on https://docs.docker.com/registry/spec/auth/token/#requesting-a-token
        # there can be a multiple fields with token - lets iterate over them and
        # return the first one we find
        for token_keys in ("token", "access_token"):
            if token_keys in response:
                return response[token_keys]
        return None


# pylint: disable=too-few-public-methods
class HTTPOAuth2(BearerAuthBase):  # pragma: no cover
    """
    Performs OAuth2 authentication for the given Request object.

    Once Bearer token is retrieved, it will be cached and used in subsequent
    requests. Since tokens are specific to repositories, the token cache may
    store multiple tokens.

    Supports registry v2 API only.
    """

    def __init__(self, refresh_token: str, *args, **kwargs) -> None:
        """Initialize HTTPOAuth2 object.

        :param refresh_token: str, identity_token from dockerconfig.json
        """
        self.refresh_token = refresh_token
        super().__init__(*args, **kwargs)

    def _get_token(self, auth_info: str, repo: str) -> Optional[str]:
        """
        Acquires a Bearer token from the registry using OAuth2 flow.
        """
        # convert WWW-Authenticate header into a dict
        # example: Bearer ream="url",service="test.azurecr.io"
        # -> {"realm": "url", "service": "test.azurecr.io"}
        bearer_info = parse_dict_header(self.BEARER_PATTERN.sub("", auth_info, count=1))

        params = {
            "service": bearer_info.get("service"),
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": "mercury",
        }

        # If repo could not be determined, do not set scope -> implies global access
        if repo:
            params["scope"] = f"repository:{repo}:pull"

        # make the request to the registry
        url = bearer_info.get("realm")
        realm_response = requests.post(
            url,
            data=params,
            verify=True,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=DEFAULT_TIMEOUT,
            proxies={"https": self.proxy} if self.proxy else None,
        )
        if realm_response.status_code != 200:
            LOG.info(
                "Registry challenge %s responded with %d - %s\nHeaders: %s",
                url,
                realm_response.status_code,
                realm_response.text,
                realm_response.headers,
            )
            return None

        # Based on https://docs.docker.com/registry/spec/auth/oauth/#response-fields
        # response contains access_token and optionally additional refresh_token
        try:
            response = realm_response.json()
            if response.get("refresh_token"):
                self.refresh_token = response.get("refresh_token")
            return response["access_token"]
        except (json.decoder.JSONDecodeError, KeyError):
            LOG.info("Registry %s did not return oauth bearer token", url)
        return None


# pylint: disable=too-few-public-methods
class HTTPBasicAuthWithB64(AuthBase):
    """Performs Basic authentication for the given Request object.

    As in requests.auth.HTTPBasicAuth, but instead of converting
    'username:password' to a base64 string (as per RFC 7617), this class does
    it by receiving the base64 string.
    """

    def __init__(self, auth, proxy: Optional[str] = None):
        """Initialize HTTPBasicAuthWithB64 object.

        :param auth: str, base64 credentials as described in RFC 7617
        """
        self.auth = auth
        self.proxy = proxy

        self.last_auth_header = f"Basic {self.auth}"

    @property
    def auth_header(self) -> Optional[str]:
        """Return the last auth header."""
        return self.last_auth_header

    def __call__(self, response):
        response.headers["Authorization"] = self.auth_header

        return response
