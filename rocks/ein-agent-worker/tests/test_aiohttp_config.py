import asyncio
import os
from unittest.mock import patch

import aiohttp

from ein_agent_worker.http.aiohttp_config import AiohttpConfigManager


class TestAiohttpProxyResolution:
    """Tests for explicit proxy resolution in _request."""

    def setup_method(self):
        # Reset patch state so each test can re-apply
        AiohttpConfigManager._proxy_configured = False

    @patch.dict(
        os.environ,
        {
            'NO_PROXY': '10.0.0.0/8,.svc.cluster.local',
            'HTTPS_PROXY': 'http://squid.internal:3128',
        },
    )
    def test_cidr_bypass_no_proxy_kwarg(self):
        """Requests to NO_PROXY CIDR hosts should NOT get proxy= set."""
        from ein_agent_worker.http.proxy import proxy_for_url

        assert proxy_for_url('https://10.142.166.251:6443/api') is None
        assert proxy_for_url('https://kubernetes.default.svc.cluster.local/api') is None

    @patch.dict(
        os.environ,
        {
            'NO_PROXY': '10.0.0.0/8,.svc.cluster.local',
            'HTTPS_PROXY': 'http://squid.internal:3128',
        },
    )
    def test_non_bypass_gets_proxy_kwarg(self):
        """Requests to non-bypassed hosts should get proxy= set."""
        from ein_agent_worker.http.proxy import proxy_for_url

        result = proxy_for_url('https://googleapis.com/v1')
        assert result == 'http://squid.internal:3128'

    @patch.dict(
        os.environ,
        {
            'NO_PROXY': '10.0.0.0/8,.svc.cluster.local',
            'HTTPS_PROXY': 'http://squid.internal:3128',
        },
    )
    def test_request_patch_injects_proxy_for_external(self):
        """The _request patch should inject proxy= for external URLs."""
        captured = {}

        async def fake_original(self, method, url, **kwargs):  # noqa: RUF029
            captured.update(kwargs)
            captured['method'] = method
            captured['url'] = url

        AiohttpConfigManager._proxy_configured = False
        with patch.object(aiohttp.ClientSession, '_request', fake_original):
            AiohttpConfigManager._enable_proxy_env_support()
            patched = aiohttp.ClientSession._request

            async def _run():
                session = aiohttp.ClientSession()
                try:
                    await patched(session, 'GET', 'https://googleapis.com/v1')
                finally:
                    await session.close()

            asyncio.run(_run())

        assert captured.get('proxy') == 'http://squid.internal:3128'

    @patch.dict(
        os.environ,
        {
            'NO_PROXY': '10.0.0.0/8,.svc.cluster.local',
            'HTTPS_PROXY': 'http://squid.internal:3128',
        },
    )
    def test_request_patch_no_proxy_for_bypass(self):
        """The _request patch should NOT inject proxy= for bypassed URLs."""
        captured = {}

        async def fake_original(self, method, url, **kwargs):  # noqa: RUF029
            captured.update(kwargs)
            captured['method'] = method
            captured['url'] = url

        AiohttpConfigManager._proxy_configured = False
        with patch.object(aiohttp.ClientSession, '_request', fake_original):
            AiohttpConfigManager._enable_proxy_env_support()
            patched = aiohttp.ClientSession._request

            async def _run():
                session = aiohttp.ClientSession()
                try:
                    await patched(session, 'GET', 'https://10.142.166.251:6443/api')
                finally:
                    await session.close()

            asyncio.run(_run())

        assert 'proxy' not in captured

    @patch.dict(
        os.environ,
        {
            'NO_PROXY': '10.0.0.0/8,.svc.cluster.local',
            'HTTPS_PROXY': 'http://squid.internal:3128',
        },
    )
    def test_explicit_proxy_kwarg_not_overridden(self):
        """If caller passes proxy= explicitly, the patch should not override it."""
        captured = {}

        async def fake_original(self, method, url, **kwargs):  # noqa: RUF029
            captured.update(kwargs)

        AiohttpConfigManager._proxy_configured = False
        with patch.object(aiohttp.ClientSession, '_request', fake_original):
            AiohttpConfigManager._enable_proxy_env_support()
            patched = aiohttp.ClientSession._request

            async def _run():
                session = aiohttp.ClientSession()
                try:
                    await patched(
                        session,
                        'GET',
                        'https://googleapis.com/v1',
                        proxy='http://custom:8080',
                    )
                finally:
                    await session.close()

            asyncio.run(_run())

        assert captured['proxy'] == 'http://custom:8080'

    def test_trust_env_not_set_to_true(self):
        """After patch, new sessions should NOT have trust_env=True."""
        AiohttpConfigManager()

        async def _check():
            async with aiohttp.ClientSession() as session:
                return session._trust_env

        result = asyncio.run(_check())
        # trust_env should be False (default) — we no longer patch it
        assert result is False

    def test_idempotent(self):
        """Applying the patch multiple times should not error or double-wrap."""
        AiohttpConfigManager()
        AiohttpConfigManager()
        # No error — _proxy_configured prevents double-patching
        assert AiohttpConfigManager._proxy_configured is True


class TestAiohttpSSLBypass:
    """Tests for SSL verification bypass."""

    def test_ssl_patch_composes_with_proxy_patch(self):
        """SSL patch should compose on top of proxy patch."""
        AiohttpConfigManager._proxy_configured = False
        mgr = AiohttpConfigManager()
        mgr.disable_ssl_verification()

        # The _request chain should be: ssl_patch → proxy_patch → original
        # Verify both patches are active
        assert mgr._ssl_configured is True
        assert AiohttpConfigManager._proxy_configured is True

    def test_ssl_idempotent(self):
        """Applying SSL patch multiple times should not error."""
        mgr = AiohttpConfigManager()
        mgr.disable_ssl_verification()
        mgr.disable_ssl_verification()
        assert mgr._ssl_configured is True
