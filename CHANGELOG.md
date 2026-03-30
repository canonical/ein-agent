# Changelog

## [0.2.0] - 2026-03-26

### Features

- Add dynamic instructions and refactor agents into dedicated package
- Add skills system for agent domain knowledge
- Add planning workflow with checkpoint summarizer and async shared context tools
- Add ObservabilitySpecialist agent and consolidate observability tools
- Add human-in-the-loop tool approval with sticky decisions
- Add defense-in-depth read-only filtering for all UTCP services
- Add Prometheus UTCP service and refactor server URL resolution
- Add Loki UTCP service with hand-written OpenAPI spec
- Add per-service UTCP_SPEC_SOURCE env var for local/live spec loading
- Add CIDR-aware NO_PROXY support for aiohttp and httpx
- Add snap packaging for ein-agent-cli
- Add snap CI/CD workflows for ein-agent-cli
- Add GHCR release workflow for ein-agent-worker rock
- Add CI workflows for CLI lint and rock build/test
- Add ruff linter and replace Makefile with justfile

### Fixes

- Add swagger.json to OpenAPI URL suffix stripping
- Replace fragile aiohttp proxy patches with explicit CIDR-aware _request wrapper
- Add trust_env=False to httpx clients to enforce CIDR-aware NO_PROXY bypass
- Pass auth headers when fetching OpenAPI specs from live URLs
- Resolve all ruff lint and formatting errors across both packages
- Remove release-snap workflow paths filter
- Remove concurrency on release-snap.yaml to avoid deadlock

### Refactoring

- Replace Kubernetes bearer token auth with kubeconfig
- Extract UTCP loader into strategy pattern with OpenAPI handlers
- Remove incident correlation workflow replaced by human-in-the-loop

### Documentation

- Update documentation to use GHCR images instead of local rock builds
- Add snap installation instructions to READMEs

## [0.1.0] - Initial Release

- Initial release of ein-agent CLI and worker
