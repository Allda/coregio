"""Registry authentication module."""

import re
import os

import requests
from requests.auth import AuthBase
from requests.cookies import extract_cookies_to_jar
from requests.utils import parse_dict_header
from six.moves.urllib.parse import urlparse


# This module comes from atomic-reactor
# https://github.com/containerbuildsystem/atomic-reactor/blob/1.6.41/atomic_reactor/auth.py


class HTTPBearerAuth(AuthBase):  # pragma: no cover
    """
    Performs Bearer authentication for the given Request object.

    username and password are optional. If provided, they will be used
    when fetching the Bearer token from realm. Otherwise, Bearer token
    is retrieved with anonymous access.

    auth_b64 may be provided for authentication (instead of username and
    password).

    Once Bearer token is retrieved, it will be cached and used in subsequent
    requests. Since tokens are specific to repositories, the token cache may
    store multiple tokens.

    Supports registry v2 API only.
    """

    BEARER_PATTERN = re.compile(r"bearer ", flags=re.IGNORECASE)
    V2_REPO_PATTERN = re.compile(r"^/v2/(.*)/(manifests|tags|blobs)/")

    def __init__(self, auth_b64, verify=True, access=None):
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

        self.token_cache = {}

    def __call__(self, response):
        repo = self._get_repo_from_url(response.url)

        if repo in self.token_cache:
            self._set_header(response, repo)
            return response

        def handle_401_with_repo(resp, **kwargs):
            return self.handle_401(resp, repo, **kwargs)

        response.register_hook("response", handle_401_with_repo)
        return response

    def handle_401(self, response, repo, **kwargs):
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

    def _get_token(self, auth_info, repo):
        bearer_info = parse_dict_header(self.BEARER_PATTERN.sub("", auth_info, count=1))
        # If repo could not be determined, do not set scope - implies
        # global access
        if repo:
            bearer_info["scope"] = f"repository:{repo}:{','.join(self.access)}"
        realm = bearer_info.pop("realm")

        realm_auth = None
        if self.auth_b64:
            realm_auth = HTTPBasicAuthWithB64(self.auth_b64)

        registry_proxy = os.environ.get("EXTERNAL_REGISTRY_PROXY")
        if registry_proxy:
            proxies = {"https": registry_proxy}
        else:
            proxies = None
        realm_response = requests.get(
            realm,
            params=bearer_info,
            verify=self.verify,
            auth=realm_auth,
            proxies=proxies,
            timeout=60,
        )
        realm_response.raise_for_status()

        response = realm_response.json()

        # Based on https://docs.docker.com/registry/spec/auth/token/#requesting-a-token
        # there can be a multiple fields with token - lets iterate over them and
        # return the first one we find
        for token_keys in ("token", "access_token"):
            if token_keys in response:
                return response[token_keys]
        return None

    def _set_header(self, response, repo):
        response.headers["Authorization"] = f"Bearer {self.token_cache[repo]}"

    def _get_repo_from_url(self, url):
        url_parts = urlparse(url)
        repo = None
        v2_match = self.V2_REPO_PATTERN.search(url_parts.path)
        if v2_match:
            repo = v2_match.group(1)
        return repo


# pylint: disable=too-few-public-methods
class HTTPBasicAuthWithB64(AuthBase):
    """Performs Basic authentication for the given Request object.

    As in requests.auth.HTTPBasicAuth, but instead of converting
    'username:password' to a base64 string (as per RFC 7617), this class does
    it by receiving the base64 string.
    """

    def __init__(self, auth):
        """Initialize HTTPBasicAuthWithB64 object.

        :param auth: str, base64 credentials as described in RFC 7617
        """
        self.auth = auth

    def __call__(self, response):
        response.headers["Authorization"] = f"Basic {self.auth}"
        return response
