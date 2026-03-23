"""CIDR-aware proxy resolution.

Provides explicit proxy resolution that handles CIDR notation in NO_PROXY,
which neither httpx nor urllib.request support natively. Follows the same
approach as the ``requests`` library's ``should_bypass_proxies()``.
"""

import ipaddress
import logging
import os
import urllib.parse

logger = logging.getLogger(__name__)


def should_bypass_proxy(host: str) -> bool:
    """Check if *host* should bypass the proxy based on NO_PROXY.

    Supports:
    - CIDR ranges (``10.0.0.0/8``, ``fd00::/8``)
    - Exact IP match (``127.0.0.1``)
    - Domain suffix match (``.example.com``, ``example.com``)
    - Wildcard (``*``)
    """
    no_proxy = os.environ.get('NO_PROXY', os.environ.get('no_proxy', ''))
    if not no_proxy:
        return False

    if no_proxy.strip() == '*':
        return True

    # Try to parse host as an IP address
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None

    for entry in no_proxy.split(','):
        entry = entry.strip()
        if not entry:
            continue

        # CIDR match (only meaningful for IP hosts)
        if '/' in entry and host_ip is not None:
            try:
                if host_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            except ValueError:
                continue

        # Exact IP match
        if host_ip is not None:
            try:
                if host_ip == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                pass
            continue

        # Domain suffix match (host is a hostname, not an IP)
        entry_lower = entry.lower().lstrip('.')
        host_lower = host.lower()
        if host_lower == entry_lower or host_lower.endswith('.' + entry_lower):
            return True

    return False


def proxy_for_url(url: str) -> str | None:
    """Return the proxy URL for *url*, or ``None`` for direct connection.

    Reads ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY`` from the
    environment with CIDR-aware bypass logic.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname

    if host and should_bypass_proxy(host):
        logger.debug('proxy_for_url: %s -> DIRECT (NO_PROXY bypass)', url)
        return None

    if parsed.scheme == 'https':
        proxy = os.environ.get('HTTPS_PROXY', os.environ.get('https_proxy'))
    else:
        proxy = os.environ.get('HTTP_PROXY', os.environ.get('http_proxy'))

    logger.debug('proxy_for_url: %s -> %s', url, proxy or 'DIRECT (no proxy configured)')
    return proxy
