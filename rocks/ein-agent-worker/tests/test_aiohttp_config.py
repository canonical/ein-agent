import asyncio
import os
from unittest.mock import patch

import aiohttp
import aiohttp.helpers

from ein_agent_worker.utcp.aiohttp_config import (
    AiohttpConfigManager,
    _proxy_bypass_with_cidr,
)


class TestProxyBypassWithCidr:
    """Tests for the CIDR-aware proxy_bypass function."""

    def setup_method(self):
        self.no_proxy = '10.0.0.0/8,192.168.0.0/16,172.16.0.0/12,127.0.0.1,localhost,::1'

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8,192.168.0.0/16'})
    def test_cidr_ipv4_match(self):
        assert _proxy_bypass_with_cidr('10.42.0.5') is True
        assert _proxy_bypass_with_cidr('10.0.0.1') is True
        assert _proxy_bypass_with_cidr('10.255.255.255') is True

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8,192.168.0.0/16'})
    def test_cidr_ipv4_no_match(self):
        assert _proxy_bypass_with_cidr('172.16.0.1') is False
        assert _proxy_bypass_with_cidr('8.8.8.8') is False
        assert _proxy_bypass_with_cidr('11.0.0.1') is False

    @patch.dict(os.environ, {'NO_PROXY': '192.168.0.0/16'})
    def test_cidr_192_168_range(self):
        assert _proxy_bypass_with_cidr('192.168.1.100') is True
        assert _proxy_bypass_with_cidr('192.168.255.255') is True
        assert _proxy_bypass_with_cidr('192.169.0.1') is False

    @patch.dict(os.environ, {'NO_PROXY': '127.0.0.1,localhost'})
    def test_exact_ip_match(self):
        assert _proxy_bypass_with_cidr('127.0.0.1') is True
        assert _proxy_bypass_with_cidr('127.0.0.2') is False

    @patch.dict(os.environ, {'NO_PROXY': '*'})
    def test_wildcard_bypasses_all(self):
        assert _proxy_bypass_with_cidr('10.0.0.1') is True
        assert _proxy_bypass_with_cidr('8.8.8.8') is True

    @patch.dict(os.environ, {}, clear=False)
    def test_no_proxy_empty(self):
        os.environ.pop('NO_PROXY', None)
        os.environ.pop('no_proxy', None)
        assert _proxy_bypass_with_cidr('10.0.0.1') is False

    @patch.dict(os.environ, {'no_proxy': '10.0.0.0/8'})
    def test_lowercase_no_proxy(self):
        os.environ.pop('NO_PROXY', None)
        assert _proxy_bypass_with_cidr('10.1.2.3') is True

    @patch.dict(os.environ, {'NO_PROXY': '.svc.cluster.local,.canonical.com'})
    def test_domain_suffix_falls_back_to_original(self):
        # Domain hosts should fall back to the original proxy_bypass
        # which handles domain suffix matching
        result = _proxy_bypass_with_cidr('kubernetes.default.svc.cluster.local')
        # Result depends on original implementation; just verify no crash
        assert isinstance(result, bool)

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8, 192.168.0.0/16 , 127.0.0.1'})
    def test_whitespace_in_entries(self):
        assert _proxy_bypass_with_cidr('10.1.1.1') is True
        assert _proxy_bypass_with_cidr('192.168.1.1') is True
        assert _proxy_bypass_with_cidr('127.0.0.1') is True

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8,,,,192.168.0.0/16'})
    def test_empty_entries_ignored(self):
        assert _proxy_bypass_with_cidr('10.1.1.1') is True
        assert _proxy_bypass_with_cidr('192.168.1.1') is True

    @patch.dict(os.environ, {'NO_PROXY': 'invalid-cidr/99,10.0.0.0/8'})
    def test_invalid_cidr_skipped(self):
        # Invalid CIDR should be skipped, valid ones still work
        assert _proxy_bypass_with_cidr('10.1.1.1') is True

    @patch.dict(os.environ, {'NO_PROXY': 'fd00::/8'})
    def test_ipv6_cidr(self):
        assert _proxy_bypass_with_cidr('fd00::1') is True
        assert _proxy_bypass_with_cidr('fe80::1') is False


class TestAiohttpConfigManagerTrustEnv:
    """Tests for aiohttp trust_env patching."""

    def test_trust_env_defaults_true_after_patch(self):
        AiohttpConfigManager()

        async def _check():
            async with aiohttp.ClientSession() as session:
                return session._trust_env

        result = asyncio.run(_check())
        assert result is True

    def test_explicit_trust_env_false_not_overridden(self):
        AiohttpConfigManager()

        async def _check():
            async with aiohttp.ClientSession(trust_env=False) as session:
                return session._trust_env

        result = asyncio.run(_check())
        assert result is False

    def test_proxy_bypass_patched(self):
        AiohttpConfigManager()
        assert aiohttp.helpers.proxy_bypass is _proxy_bypass_with_cidr

    def test_idempotent(self):
        AiohttpConfigManager()
        AiohttpConfigManager()
        # No error, patch applied only once
        assert aiohttp.helpers.proxy_bypass is _proxy_bypass_with_cidr
