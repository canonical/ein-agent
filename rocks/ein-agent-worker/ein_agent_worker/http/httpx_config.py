"""httpx configuration management for UTCP clients.

Patches httpx.URLPattern.matches to support CIDR notation in NO_PROXY.

httpx parses NO_PROXY entries like '10.0.0.0/8' as URL patterns with
host='10.0.0.0' and path='/8', so only the exact IP 10.0.0.0 matches.
This patch adds proper CIDR range matching using Python's ipaddress module.
"""

import ipaddress
import logging

from httpx._urls import URL
from httpx._utils import URLPattern

logger = logging.getLogger(__name__)

_original_matches = URLPattern.matches


def _matches_with_cidr(self: URLPattern, other: URL) -> bool:
    """Extended URLPattern.matches with CIDR support.

    If the pattern was created from a CIDR entry (e.g., '10.0.0.0/8'),
    httpx stores host='10.0.0.0' and the '/8' is lost in the path.
    We detect this by checking if the original pattern contains a CIDR
    and comparing the request host IP against the network range.
    """
    # Check if this pattern looks like a CIDR entry
    # Pattern format is 'all://10.0.0.0/8' from NO_PROXY parsing
    pattern_str = self.pattern
    if '/' in pattern_str:
        # Extract the part after '://' to check for CIDR
        parts = pattern_str.split('://', 1)
        if len(parts) == 2:
            host_path = parts[1]
            # Check if it's a CIDR like '10.0.0.0/8'
            if '/' in host_path:
                try:
                    network = ipaddress.ip_network(host_path, strict=False)
                    # It's a valid CIDR — check if the request host is in range
                    try:
                        host_ip = ipaddress.ip_address(other.host)
                        return host_ip in network
                    except ValueError:
                        return False
                except ValueError:
                    pass

    return _original_matches(self, other)


class HttpxConfigManager:
    """Configure httpx defaults for UTCP clients.

    Patches httpx.URLPattern.matches to support CIDR notation in NO_PROXY.
    Idempotent.
    """

    _configured = False

    @classmethod
    def enable_cidr_no_proxy(cls) -> None:
        """Patch httpx URLPattern.matches for CIDR support.

        Idempotent.
        """
        if cls._configured:
            return

        URLPattern.matches = _matches_with_cidr

        cls._configured = True
        logger.info('httpx patched: CIDR-aware NO_PROXY')
