"""aiohttp configuration management for UTCP clients.

Applies process-wide monkey-patches to aiohttp:
1. Explicit CIDR-aware proxy resolution in _request: calls proxy_for_url()
   directly, bypassing aiohttp's trust_env → get_env_proxy_for_url chain
2. SSL verification bypass (conditional): disabled only when
   insecure=True for self-signed certs
"""

import logging
import ssl

import aiohttp

from ein_agent_worker.http.proxy import proxy_for_url

logger = logging.getLogger(__name__)


class AiohttpConfigManager:
    """Configure aiohttp defaults for UTCP clients.

    Applies process-wide monkey-patches to aiohttp:
    1. Explicit proxy resolution in _request via proxy_for_url()
    2. SSL verification bypass (conditional)

    All patches are idempotent and tracked via class state.
    """

    _proxy_configured = False

    def __init__(self):
        self._ssl_configured = False
        self._enable_proxy_env_support()

    @classmethod
    def _enable_proxy_env_support(cls) -> None:
        """Patch aiohttp _request to resolve proxy explicitly.

        Instead of relying on trust_env=True + proxy_bypass (which breaks
        in the Temporal worker runtime due to module-global instability),
        we inject proxy= directly into every _request call using the same
        proxy_for_url() that works for httpx clients.

        Idempotent.
        """
        if cls._proxy_configured:
            return

        original_request = aiohttp.ClientSession._request

        async def _patched_request_with_proxy(self, method, url, **kwargs):
            # Force trust_env=False to prevent aiohttp's internal proxy resolution
            # (which doesn't support CIDR) from overriding our explicit proxy
            self._trust_env = False
            if 'proxy' not in kwargs:
                resolved = proxy_for_url(str(url))
                if resolved is not None:
                    kwargs['proxy'] = resolved
            return await original_request(self, method, url, **kwargs)

        aiohttp.ClientSession._request = _patched_request_with_proxy

        cls._proxy_configured = True
        logger.info('aiohttp patched: explicit CIDR-aware proxy resolution in _request')

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

        # Also patch ClientSession._request to pass ssl=False by default
        # This composes on top of the proxy patch (captures already-patched _request)
        original_request = aiohttp.ClientSession._request

        async def _patched_request(self, method, url, **kwargs):
            if 'ssl' not in kwargs:
                kwargs['ssl'] = False
            return await original_request(self, method, url, **kwargs)

        aiohttp.ClientSession._request = _patched_request

        self._ssl_configured = True
        logger.warning('SSL verification disabled for aiohttp - use only for development')
