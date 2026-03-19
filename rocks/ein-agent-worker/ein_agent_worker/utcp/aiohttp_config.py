"""aiohttp configuration management for UTCP clients.

Applies process-wide monkey-patches to aiohttp:
1. CIDR-aware NO_PROXY (unconditional): patches aiohttp.helpers.proxy_bypass
   so NO_PROXY entries like 10.0.0.0/8 are matched correctly
2. Proxy env support (unconditional): trust_env=True so
   HTTP_PROXY/HTTPS_PROXY/NO_PROXY are respected
3. SSL verification bypass (conditional): disabled only when
   insecure=True for self-signed certs
"""

import ipaddress
import logging
import os
import ssl

import aiohttp
import aiohttp.helpers

logger = logging.getLogger(__name__)

# Store original before patching
_original_proxy_bypass = aiohttp.helpers.proxy_bypass


def _proxy_bypass_with_cidr(host, proxies=None):
    """Extended proxy_bypass with CIDR notation support.

    aiohttp delegates to urllib's proxy_bypass_environment which only
    supports exact IP matches and domain suffix matching. This adds
    support for CIDR ranges (e.g., 10.0.0.0/8, 192.168.0.0/16) in NO_PROXY.
    """
    no_proxy = os.environ.get('NO_PROXY', os.environ.get('no_proxy', ''))
    if not no_proxy:
        return False

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP — fall back to original for domain suffix matching
        return _original_proxy_bypass(host, proxies) if proxies else _original_proxy_bypass(host)

    for entry in no_proxy.split(','):
        entry = entry.strip()
        if not entry:
            continue

        if entry == '*':
            return True

        # CIDR match
        if '/' in entry:
            try:
                if host_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            except ValueError:
                continue

        # Exact IP match
        try:
            if host_ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue

    return False


class AiohttpConfigManager:
    """Configure aiohttp defaults for UTCP clients.

    Applies process-wide monkey-patches to aiohttp:
    1. CIDR-aware NO_PROXY via aiohttp.helpers.proxy_bypass
    2. trust_env=True by default on ClientSession
    3. SSL verification bypass (conditional)

    All patches are idempotent and tracked via class state.
    """

    _proxy_configured = False

    def __init__(self):
        self._ssl_configured = False
        self._enable_proxy_env_support()

    @classmethod
    def _enable_proxy_env_support(cls) -> None:
        """Patch aiohttp proxy env var handling.

        1. Patches aiohttp.helpers.proxy_bypass to support CIDR in NO_PROXY
        2. Patches aiohttp.ClientSession to default trust_env=True

        Idempotent.
        """
        if cls._proxy_configured:
            return

        # Patch aiohttp's proxy_bypass for CIDR support
        aiohttp.helpers.proxy_bypass = _proxy_bypass_with_cidr

        # Patch aiohttp to read proxy env vars (trust_env=True)
        original_session_init = aiohttp.ClientSession.__init__

        def _patched_session_init(self, *args, **kwargs):
            if 'trust_env' not in kwargs:
                kwargs['trust_env'] = True
            original_session_init(self, *args, **kwargs)

        aiohttp.ClientSession.__init__ = _patched_session_init

        cls._proxy_configured = True
        logger.info('aiohttp patched: CIDR-aware NO_PROXY + trust_env=True')

    def disable_ssl_verification(self) -> None:
        """Disable SSL certificate verification globally for aiohttp.

        WARNING: Only use this for development/testing with self-signed certs.
        This patches aiohttp to disable SSL verification. Idempotent.
        """
        if self._ssl_configured:
            return

        # Create an insecure SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Patch aiohttp's TCPConnector to use insecure SSL by default
        original_init = aiohttp.TCPConnector.__init__

        def _patched_init(self, *args, **kwargs):
            if 'ssl' not in kwargs:
                kwargs['ssl'] = ssl_context
            original_init(self, *args, **kwargs)

        aiohttp.TCPConnector.__init__ = _patched_init

        # Also patch ClientSession to pass ssl=False by default
        original_request = aiohttp.ClientSession._request

        async def _patched_request(self, method, url, **kwargs):
            if 'ssl' not in kwargs:
                kwargs['ssl'] = False
            return await original_request(self, method, url, **kwargs)

        aiohttp.ClientSession._request = _patched_request

        self._ssl_configured = True
        logger.warning('SSL verification disabled for aiohttp - use only for development')
