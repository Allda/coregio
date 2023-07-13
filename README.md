# CoregIO
![PyPI version](https://badge.fury.io/py/coregio.svg)

The CoregIO Python Library empowers you to seamlessly fetch objects from the Container Registry API. This capability enables you to retrieve container images, manifests and other objects stored in a Container registry with ease. With a simple and intuitive interface, you can specify the object you want to fetch, such as an image by its name and tag, and the library takes care of the underlying API calls and data retrieval. Whether you need to pull a specific image or access various objects within the registry, this library streamlines the process, allowing you to interact with the Docker Registry API effortlessly.

## Supported auth methods
In order to connect to a remote registry using standard docker registry API the library supports several authentication methods.
 - Bearer
 - OAuth2
 - Basic

## How to install
The library is available on PyPi and can be downloaded using `pip`.
```bash
$ pip install coregio
```

## Usage
The Coregio Python Library empowers you to seamlessly fetch objects from the Container Registry API. This capability enables you to retrieve container images, manifests and other objects stored in a Container registry with ease. With a simple and intuitive interface, you can specify the object you want to fetch, such as an image by its name and tag, and the library takes care of the underlying API calls and data retrieval. Whether you need to pull a specific image or access various objects within the registry, this library streamlines the process, allowing you to interact with the Docker Registry API effortlessly.

### Repository tags
```python
from coregio.registry_api import ContainerRegistry

# Create a registry interface and fetch repository tags
registry = ContainerRegistry("quay.io")
tags = registry.get_tags("prometheus/node-exporter")
print(tags)
['v0.17.0', 'v0.15.1', 'v0.15.2', 'latest', 'master']
```
### Image manifest
```python
manifest = registry.get_manifest(
    "prometheus/node-exporter",
    "latest",
)
print(manifest)
{'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.v2+json', 'config': {'mediaType': 'application/vnd.docker.container.image.v1+json', 'size': 3361, 'digest': 'sha256:173d3570a5af2b2ef8816b40af3ca985280549520e8d328a7f20333d9f354d1b'}, 'layers': [{'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip', 'size': 777654, 'digest': 'sha256:e6b9e25f5d0157c1c76c9d3680c4645368c9ac87cb008b5eddf9d856b8551373'}, {'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip', 'size': 486261, 'digest': 'sha256:0c6a06713be86bfb61b5f1ce1217f7b509c7ea7b894af65149cafac5004ee28f'}, {'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip', 'size': 10458504, 'digest': 'sha256:15ef7072c2ab4f35955068b02a09e669a5613d5bfca4f5c442c45b958036f17a'}]}


# User can select a manifest type based on accept headers
manifest = registry.get_manifest(
    "prometheus/node-exporter",
    "latest",
    manifest_types=["oci_index"]
)
print(manifest)
{'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.list.v2+json', 'manifests': [{'mediaType': 'application/vnd.docker.distribution.manifest.v2+json', 'size': 595, 'digest': 'sha256:1b2da31e89c8efe8d67f726f9872ca2fce95ddb1d5d97fd71468d5c48de85ddf', 'platform': {'architecture': 'amd64', 'os': 'linux'}}, {'mediaType': 'application/vnd.docker.distribution.manifest.v2+json', 'size': 595, 'digest': 'sha256:18ef5a4eb0a00e0513c8d4fb87bc31728e4c7ed6caea83c608c5048418b00185', 'platform': {'architecture': 'ppc64le', 'os': 'linux'}}, {'mediaType': 'application/vnd.docker.distribution.manifest.v2+json', 'size': 595, 'digest': 'sha256:c3e79af3edaf3b05282565c0b3e08e5b189e4200153114475256d00367da09da', 'platform': {'architecture': 's390x', 'os': 'linux'}}, {'mediaType': 'application/vnd.docker.distribution.manifest.v2+json', 'size': 595, 'digest': 'sha256:7da24517de68a4af11f098841d10c2e02f12619c662e5b812bff7959e2a477a6', 'platform': {'architecture': 'arm64', 'os': 'linux'}}]}

```


```python
# Using a proxy
registry = ContainerRegistry(
    "quay.io",
    proxy="http://proxy.example.com"
)

manifest = registry.get_manifest(
    "redhat-isv-containers/5e61e93ffe2231a0c286037e",
    "latest",
)

```

## Contributing
Contributions are welcome! If you find any issues or have suggestions for improvement, please open an issue or submit a pull request. Please follow our [CONTRIBUTING.md](./CONTRIBUTING.md)