"""aiohttp configuration management for UTCP clients.

Applies process-wide monkey-patches to aiohttp:
1. CIDR-aware NO_PROXY (unconditional): patches aiohttp.helpers.proxy_bypass
   so NO_PROXY entries like 10.0.0.0/8 are matched correctly
2. Proxy env support (unconditional): trust_env=True so
   HTTP_PROXY/HTTPS_PROXY/NO_PROXY are respected
3. SSL verification bypass (conditional): disabled only when
   insecure=True for self-signed certs
"""

import logging
import ssl

import aiohttp
import aiohttp.helpers

from ein_agent_worker.http.proxy import should_bypass_proxy

logger = logging.getLogger(__name__)


def _proxy_bypass_with_cidr(host, proxies=None):
    """Extended proxy_bypass with CIDR notation support.

    Thin wrapper around :func:`should_bypass_proxy` that matches the
    signature expected by ``aiohttp.helpers.proxy_bypass``.
    """
    return should_bypass_proxy(host)


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
