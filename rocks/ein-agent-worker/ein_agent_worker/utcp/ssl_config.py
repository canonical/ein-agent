"""SSL configuration management for UTCP clients.

WARNING: Disabling SSL verification should only be used for
development/testing with self-signed certificates.
"""

import logging
import ssl

import aiohttp

logger = logging.getLogger(__name__)


class SSLConfigManager:
    """Manage SSL verification settings for aiohttp.

    Note: The actual effect of disabling SSL verification is process-wide
    because it monkey-patches aiohttp. The instance state tracks whether
    the patch has been applied to ensure idempotency.
    """

    def __init__(self):
        self._configured = False

    def disable_ssl_verification(self) -> None:
        """Disable SSL certificate verification globally for aiohttp.

        WARNING: Only use this for development/testing with self-signed certs.
        This patches aiohttp to disable SSL verification. Idempotent.
        """
        if self._configured:
            return

        # Create an insecure SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Patch aiohttp's TCPConnector to use insecure SSL by default
        _original_init = aiohttp.TCPConnector.__init__

        def _patched_init(self, *args, **kwargs):
            if "ssl" not in kwargs:
                kwargs["ssl"] = ssl_context
            _original_init(self, *args, **kwargs)

        aiohttp.TCPConnector.__init__ = _patched_init

        # Also patch ClientSession to pass ssl=False by default
        _original_request = aiohttp.ClientSession._request

        async def _patched_request(self, method, url, **kwargs):
            if "ssl" not in kwargs:
                kwargs["ssl"] = False
            return await _original_request(self, method, url, **kwargs)

        aiohttp.ClientSession._request = _patched_request

        self._configured = True
        logger.warning(
            "SSL verification disabled for aiohttp - use only for development"
        )
