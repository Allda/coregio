"""Container registry API implementation."""
import json
import logging
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import urljoin, urlparse

import requests

from coregio import utils
from coregio.registry_auth import HTTPBearerAuth, HTTPOAuth2, HTTPBasicAuthWithB64

LOGGER = logging.getLogger(__name__)


ACCEPT_HEADERS = {
    "oci_index": "application/vnd.oci.image.index.v1+json",
    "oci_manifest": "application/vnd.oci.image.manifest.v1+json",
    "oci_config": "application/vnd.oci.image.config.v1+json",
    "oci_gzip": "application/vnd.oci.image.layer.v1.tar+gzip",
    "docker_manifest_list": "application/vnd.docker.distribution.manifest.list.v2+json",
    "docker_manifest_v2": "application/vnd.docker.distribution.manifest.v2+json",
    "docker_manifest_v1": "application/vnd.docker.distribution.manifest.v1+json",
}

# There is something special about docker.io registry
# The content is reference with classic docker.io alias but in fact
# it is stored in index.docker.io
# From the observation this is something specific only to docker.io
# and it needs to be handled specifically using lookup table
SPECIAL_DOCKER_ALIASES = {
    "docker.io": "index.docker.io",
    "registry-1.docker.io": "index.docker.io",
    "hub.docker.com": "index.docker.io",
    "registry.hub.docker.com": "index.docker.io",
}


class ContainerRegistry:
    """
    Class which calls container registry API
    """

    # Timeouts (connect, read) for HTTP requests
    # (see https://requests.readthedocs.io/en/latest/user/advanced/#timeouts)
    # Use a low connect timeout to fail early when trying to connect to an
    # endpoint that is firewalled (dropping packets)
    DEFAULT_TIMEOUT = (7.0, 15.0)

    def __init__(
        self,
        url: str,
        docker_cfg: Optional[str] = None,
        session: Optional[Any] = None,
        proxy: Optional[str] = None,
    ) -> None:
        """
        Args:
        url (str): URL of the registry to auth to
        docker_cfg (Optional, str): DockerConfigJson string
        """

        self.url = self._normalize_registry_url(url)
        self._original_url = url
        self.docker_cfg = docker_cfg

        self.session = session or requests.Session()
        self.proxy = proxy

        self.auth_header = None

    @staticmethod
    def _normalize_registry_url(url: str) -> str:
        """
        Normalize registry URL:
        - If needed, the hostname is replaced according
          to the SPECIAL_DOCKER_ALIASES mapping.
        - Scheme is added if missing.
        - Port number is preserved if present.
        - Path is discarded if present.

        Args:
            url: Registry URL

        Returns:
            str: Normalized registry URL
        """
        url_with_scheme = utils.add_scheme_if_missing(url)
        parsed = urlparse(url_with_scheme)
        hostname = SPECIAL_DOCKER_ALIASES.get(parsed.hostname, parsed.hostname)

        normalized_url = f"{parsed.scheme}://{hostname}"
        if parsed.port:
            normalized_url = f"{normalized_url}:{parsed.port}"
        return normalized_url

    def _get_auth_token(self) -> Any:
        """
        Extract registry auth token from docker_config_json.

        Returns:
            Any: Registry auth token (base64 encoded) if available
        """
        if not self.docker_cfg:
            return None

        try:
            docker_cfg_json = json.loads(self.docker_cfg)
        except ValueError:
            LOGGER.warning("Provided dockerConfigJson is not a valid json")
            return None

        registry_auths = docker_cfg_json.get("auths", {})
        auth = self._select_registry_auth_token_from_docker_config(registry_auths)
        if not auth:
            return None

        # if this is oauth2 auth, token is in identity_token
        if auth.get("identitytoken"):
            return auth["identitytoken"]
        # otherwise use auth
        return auth.get("auth")

    def _select_registry_auth_token_from_docker_config(
        self, registry_auths: Dict[str, Any]
    ) -> Any:
        """
        Select auth from docker config by given registry key.

        Args:
            registry_auths (Dict[str, Any]): Authentication values from
            docker config

        Returns:
            Any: Authentication details
        """
        for registry_key, auth in registry_auths.items():
            if not registry_key:
                continue
            # There are several formats of registry that can be stored
            # in docker config json. Let's compare URLs starting from basic method
            # to more complex

            # First let's try simple URL comparison
            if self._cmp_registry_key(registry_key):
                return auth

            # Add a schema to the URL if missing
            registry_key = utils.add_scheme_if_missing(registry_key)

            # Parse URL and compare matching hostname
            parsed_key = urlparse(registry_key)
            hostname = parsed_key.hostname
            if not hostname:
                continue
            if self._cmp_registry_key(hostname):
                return auth

            # Let's now strip a subdomain and compare the main domain
            # index.quay.io -> quay.io
            hostname_wo_subdomain = ".".join(hostname.split(".")[-2:])

            if self._cmp_registry_key(hostname_wo_subdomain):
                return auth

        # No luck finding auth
        return None

    def _cmp_registry_key(self, registry_key: Optional[str]) -> bool:
        """
        Check if given registry key correspond to the registry hosname

        Args:
            registry_key (Optional[str]): Registry key from docker config

        Returns:
            bool: Matching flag
        """
        return registry_key in (self.url, self._original_url)

    def _get_session(self, auth_class: Callable[[Any], Any]) -> requests.Session:
        """
        Create a registry http session with auth based on class variables,
        using proxy if set in environment variables.

        Auth is set to use Docker config json file.

        Returns:
            requests.Session: Registry session
        """

        auth_token = self._get_auth_token()
        self.session.auth = auth_class(auth_token, proxy=self.proxy)
        utils.add_session_retries(self.session)

        return self.session

    def _get(
        self,
        full_url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        verify: bool = True,
    ) -> requests.Response:
        """
        Make a HTTP GET request to url given by the arguments and use
        multiple auth method as a failover.

        If one auth method returns 401 code a next request is made with another
        method until response is successful or we run out of methods.

        Args:
            full_url (str): Full URL for the request
            params (Optional[Dict[str, Any]], optional): Optional request params.
                Defaults to None.
            headers (Optional[Dict[str, Any]], optional): Optional request headers.
                Defaults to None.
            verify (bool, optional): Optional request verify flag. Defaults to True.

        Returns:
            requests.Response: HTTP response object
        """
        # Registry uses different auth methods and we don't know which one to use until
        # we make a request. This loop iterates over several methods and make requests
        # until it successfully returns valid response
        for auth_method in (HTTPBearerAuth, HTTPOAuth2, HTTPBasicAuthWithB64):
            session = self._get_session(auth_method)

            resp = session.get(
                full_url,
                params=params,
                headers=headers,
                verify=verify,
                timeout=self.DEFAULT_TIMEOUT,
                proxies={"https": self.proxy} if self.proxy else None,
            )

            self.auth_header = session.auth.auth_header
            if resp.status_code != 401:
                return resp
            LOGGER.debug(
                "Auth method %s was un-successful. Trying another one. %s",
                auth_method,
                full_url,
            )

        return resp

    def get_request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """
        GET Registry API request to given uri

        Args:
            path: Registry API endpoint path
            params: Params to pass to Registry API endpoint
            headers: Headers to pass to Registry API endpoint

        Returns:
            Response: The resulting Response object
        """

        full_url = urljoin(self.url, path)

        LOGGER.debug("Querying registry: GET %s %s %s", full_url, headers, params)
        resp = self._get(full_url, params=params, headers=headers)
        utils.handle_response(resp)
        resp.raise_for_status()

        LOGGER.debug(
            "Registry GET query was successful - %s - %s", full_url, resp.status_code
        )
        return resp

    def get_paginated_response(  # pylint: disable=too-many-arguments
        self,
        path: str,
        list_name: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        page_size: int = 100,
        limit: int = 0,
    ) -> List[Any]:
        """
        Get Registry API paginated response. This only applies to responses with lists.

        Args:
            path (str): API endpoint path
            list_name (str): Name that points to the list of data in the response,
                             e.g. tags
            params (Optional[Dict[str, Any]]): Request params
            headers (Optional[Dict[str, Any]]): Request headers
            page_size (int): The number of records per page
            limit (int): Maximum limit of records

        Returns:
            Any: Data returned by iterating over all available pages
        """
        data = []
        next_page = path
        while True:
            if not params:
                params = {}
            params["n"] = page_size
            resp = self.get_request(next_page, headers=headers, params=params)
            page_data = resp.json().get(list_name, [])
            data.extend(page_data)

            next_page = resp.links.get("next", {}).get("url")
            if not next_page:
                break
            if limit != 0 and len(data) >= limit:
                break

        return data[:limit] if limit else data

    def get_manifest_raw(
        self, repository: str, reference: str, manifest_types: Any = None
    ) -> Any:
        """
        Get manifest raw response in a repository by a reference
        (manifest digest or tag).

        Args:
            repository (str): Repository name
            reference (str): Manifest digest or tag
            manifest_types (Optional, List[str]): What type of manifest
                to get, i.e. index, manifest, ...

        Returns:
            Any: Manifest raw http response object
        """
        if not manifest_types:
            manifest_types = ["docker_manifest_v2", "oci_manifest"]

        accept_header = ", ".join([ACCEPT_HEADERS[type] for type in manifest_types])
        headers = {"Accept": accept_header}
        uri = f"v2/{repository}/manifests/{reference}"
        return self.get_request(uri, headers=headers)

    def get_manifest(
        self,
        repository: str,
        reference: str,
        manifest_types: Any = None,
        is_headers: bool = False,
    ) -> Any:
        """
        Get manifest in a repository by a reference (manifest digest or tag).

        Args:
            repository (str): Repository name
            reference (str): Manifest digest or tag
            manifest_types (Optional, List[str]): What type of manifest
                to get, i.e. index, manifest, ...
            is_headers (bool): Indicates if headers need to be returned or response data

        Returns:
            dict: Manifest in the given repository or headers of the response
                (depends on value of is_headers parameter)
        """
        rsp = self.get_manifest_raw(repository, reference, manifest_types)
        if is_headers:
            return rsp.headers
        return rsp.json()

    def get_manifest_headers(self, repository: str, reference: str) -> Any:
        """
        Get manifest headers in a repository by a reference (manifest digest or tag).

        Args:
            repository (str): Repository name
            reference (str): Manifest digest or tag
            manifest_types (Optional, List[str]): What type of manifest
                to get, i.e. index, manifest, ...

        Returns:
            dict: Headers of the response
        """
        return self.get_manifest(repository, reference, is_headers=True)

    def get_tags(self, repository: str, page_size: int = 100, limit: int = 2000) -> Any:
        """
        Get all tags in a repository.

        Args:
            repository (str): Repository name
            page_size (int, optional): The number of tags per page; defaults to 100
            limit (int, optional): Maximum total number of tags
                to be retrieved; defaults to 2000


        Returns:
            list: Tags in the repository

        """
        uri = f"v2/{repository}/tags/list"
        return self.get_paginated_response(
            uri, list_name="tags", page_size=page_size, limit=limit
        )
