"""Tests for the alertmanager activity, focusing on proxy bypass behaviour."""

import os
from unittest.mock import patch

import httpx
import pytest

from ein_agent_worker.activities.alertmanager import (
    FetchAlertsParams,
    fetch_alerts_activity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALERTMANAGER_URL = 'http://10.142.166.251/cos-alertmanager'
SAMPLE_ALERTS = [
    {
        'labels': {'alertname': 'HighCPU', 'severity': 'critical', 'state': 'firing'},
        'annotations': {'summary': 'CPU is high'},
        'fingerprint': 'abc123',
    },
    {
        'labels': {'alertname': 'Watchdog', 'severity': 'none', 'state': 'firing'},
        'annotations': {'summary': 'Watchdog'},
        'fingerprint': 'def456',
    },
]


def _mock_transport(response_json=None, status_code=200):
    """Return an httpx.MockTransport that serves *response_json*."""
    payload = response_json if response_json is not None else SAMPLE_ALERTS

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


def _proxy_rejecting_transport():
    """Return a transport that returns 403 — simulates a proxy that blocks the request."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text='Forbidden by proxy')

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests: trust_env=False prevents httpx from re-reading proxy env vars
# ---------------------------------------------------------------------------


class TestAlertmanagerProxyBypass:
    """Verify that fetch_alerts_activity honours CIDR-aware NO_PROXY."""

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'NO_PROXY': '10.0.0.0/8',
        },
    )
    async def test_bypassed_host_does_not_use_proxy(self):
        """When the host is in NO_PROXY CIDR, httpx must connect directly (no proxy)."""
        recorded_requests: list[httpx.Request] = []

        def direct_handler(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return httpx.Response(200, json=SAMPLE_ALERTS)

        # Monkey-patch httpx.AsyncClient so we can inject our transport
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            # Verify trust_env=False is being passed
            assert kwargs.get('trust_env') is False, (
                'trust_env must be False to prevent httpx from reading HTTP_PROXY'
            )
            # Verify proxy is None (bypass)
            assert kwargs.get('proxy') is None, (
                'proxy_for_url should return None for a NO_PROXY-bypassed host'
            )
            # Replace transport so no real network call is made
            kwargs['transport'] = httpx.MockTransport(direct_handler)
            original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, '__init__', patched_init):
            params = FetchAlertsParams(
                alertmanager_url=ALERTMANAGER_URL,
                status='all',
            )
            result = await fetch_alerts_activity(params)

        assert len(result) == 2
        assert recorded_requests, 'Expected a direct request to alertmanager'
        assert '10.142.166.251' in str(recorded_requests[0].url)

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'NO_PROXY': '192.168.0.0/16',  # does NOT cover 10.x
        },
    )
    async def test_non_bypassed_host_uses_proxy(self):
        """When the host is NOT in NO_PROXY, the proxy URL should be passed to httpx."""
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            assert kwargs.get('trust_env') is False
            # proxy should be the HTTP_PROXY value since host is not bypassed
            assert kwargs.get('proxy') == 'http://squid:3128'
            # Remove proxy and inject mock transport to avoid real connections
            kwargs.pop('proxy', None)
            kwargs['transport'] = httpx.MockTransport(
                lambda req: httpx.Response(200, json=SAMPLE_ALERTS)
            )
            original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, '__init__', patched_init):
            params = FetchAlertsParams(
                alertmanager_url=ALERTMANAGER_URL,
                status='all',
            )
            result = await fetch_alerts_activity(params)

        assert len(result) == 2


class TestAlertmanagerFiltering:
    """Test alert filtering logic (status and alertname)."""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=False)
    async def test_filter_by_status_firing(self):
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('NO_PROXY', None)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(
                lambda req: httpx.Response(200, json=SAMPLE_ALERTS)
            )
            original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, '__init__', patched_init):
            params = FetchAlertsParams(
                alertmanager_url=ALERTMANAGER_URL,
                status='firing',
            )
            result = await fetch_alerts_activity(params)

        # Both sample alerts have state='firing'
        assert len(result) == 2

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=False)
    async def test_filter_by_alertname(self):
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('NO_PROXY', None)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(
                lambda req: httpx.Response(200, json=SAMPLE_ALERTS)
            )
            original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, '__init__', patched_init):
            params = FetchAlertsParams(
                alertmanager_url=ALERTMANAGER_URL,
                status='all',
                alertname='HighCPU',
            )
            result = await fetch_alerts_activity(params)

        assert len(result) == 1
        assert result[0]['labels']['alertname'] == 'HighCPU'

    @pytest.mark.asyncio
    @patch.dict(os.environ, {}, clear=False)
    async def test_missing_url_raises(self):
        os.environ.pop('ALERTMANAGER_URL', None)
        params = FetchAlertsParams(alertmanager_url=None)
        with pytest.raises(ValueError, match='alertmanager_url is required'):
            await fetch_alerts_activity(params)

    @pytest.mark.asyncio
    @patch.dict(os.environ, {'ALERTMANAGER_URL': ALERTMANAGER_URL}, clear=False)
    async def test_url_from_env(self):
        """alertmanager_url falls back to ALERTMANAGER_URL env var."""
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('NO_PROXY', None)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(
                lambda req: httpx.Response(200, json=SAMPLE_ALERTS)
            )
            original_init(self, *args, **kwargs)

        with patch.object(httpx.AsyncClient, '__init__', patched_init):
            params = FetchAlertsParams(status='all')
            result = await fetch_alerts_activity(params)

        assert len(result) == 2


class TestHttpxTrustEnvIntegration:
    """Integration-style tests proving trust_env=False actually prevents proxy use."""

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'NO_PROXY': '10.0.0.0/8',
        },
    )
    async def test_trust_env_false_ignores_http_proxy(self):
        """With trust_env=False and proxy=None, httpx must NOT read HTTP_PROXY."""
        direct_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={'ok': True}))

        # trust_env=False + proxy=None → httpx should go direct
        async with httpx.AsyncClient(
            proxy=None, trust_env=False, transport=direct_transport
        ) as client:
            resp = await client.get('http://10.142.166.251/test')
            assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'NO_PROXY': '',
        },
    )
    async def test_trust_env_true_would_use_proxy(self):
        """Demonstrate that without trust_env=False, httpx reads HTTP_PROXY."""
        # With trust_env=True (default), httpx creates proxy mounts from env
        async with httpx.AsyncClient(proxy=None, trust_env=True) as client:
            # httpx will have proxy routing configured from env
            # We just check that the proxy pool is set up (not empty)
            transport_map = getattr(client, '_mounts', {})
            # When HTTP_PROXY is set and trust_env=True, httpx adds proxy transports
            assert len(transport_map) > 0, 'Expected httpx to configure proxy transports from env'
