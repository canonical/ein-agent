"""HTTP library configuration and monkey-patches.

Centralises process-wide patches for aiohttp and httpx:
- CIDR-aware NO_PROXY matching
- Proxy environment variable support (trust_env)
- Conditional SSL verification bypass
"""

from ein_agent_worker.http.aiohttp_config import AiohttpConfigManager, _proxy_bypass_with_cidr
from ein_agent_worker.http.httpx_config import HttpxConfigManager, _matches_with_cidr
from ein_agent_worker.http.proxy import proxy_for_url, should_bypass_proxy

__all__ = [
    'AiohttpConfigManager',
    'HttpxConfigManager',
    '_matches_with_cidr',
    '_proxy_bypass_with_cidr',
    'proxy_for_url',
    'should_bypass_proxy',
]
