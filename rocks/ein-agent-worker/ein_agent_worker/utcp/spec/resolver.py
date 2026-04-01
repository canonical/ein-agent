"""URL parsing utilities for OpenAPI spec resolution."""

import logging
from pathlib import Path

from ein_agent_worker.utcp.config import DEFAULT_VERSIONS

logger = logging.getLogger(__name__)

# Suffixes to strip from OpenAPI URLs to get the API base URL
_OPENAPI_SUFFIXES = [
    '/openapi/v2',
    '/openapi/v3',
    '/openapi',
    '/api/swagger.json',
    '/swagger.json',
]


def strip_openapi_suffix(url: str) -> str:
    """Strip OpenAPI endpoint suffixes from a URL to get the API base URL.

    Args:
        url: The OpenAPI spec URL (e.g., 'https://10.0.0.1:6443/openapi/v2')

    Returns:
        The API base URL with suffix stripped (e.g., 'https://10.0.0.1:6443')
    """
    for suffix in _OPENAPI_SUFFIXES:
        if url.endswith(suffix):
            stripped = url[: -len(suffix)]
            logger.debug("Stripped '%s' from URL: %s -> %s", suffix, url, stripped)
            return stripped
    return url


def find_spec_file(
    specs_dir: Path, service_name: str, version: str = '', service_type: str = ''
) -> Path | None:
    """Find a local OpenAPI spec file for a service.

    Looks for version-specific files first, then falls back to any available spec.
    When service_type is provided, uses it for directory lookup (allowing multiple
    instances of the same type to share spec files).

    Args:
        specs_dir: Directory containing spec files organized by service.
        service_name: Service instance name (e.g., 'kubernetes-prod').
        version: Version string (e.g., '1.35', 'tentacle', '12').
        service_type: Service type for directory lookup (e.g., 'kubernetes').
            If empty, falls back to service_name.

    Returns:
        Path to the spec file if found, None otherwise.
    """
    # Use service_type for directory lookup (shared across instances)
    lookup_name = service_type if service_type else service_name
    service_dir = specs_dir / lookup_name
    if not service_dir.exists():
        logger.warning('Spec directory not found: %s', service_dir)
        return None

    # Use default version if not specified (keyed by service type)
    if not version:
        version = DEFAULT_VERSIONS.get(lookup_name.lower(), '')

    # Look for the version-specific file
    if version:
        for ext in ['.json', '.yaml', '.yml']:
            spec_path = service_dir / f'{version}{ext}'
            if spec_path.exists():
                return spec_path

    # Fallback: find any available spec
    for ext in ['.json', '.yaml', '.yml']:
        spec_files = list(service_dir.glob(f'*{ext}'))
        if spec_files:
            return spec_files[0]

    logger.warning('No spec file found for %s', service_name)
    return None
