# Changelog

## [0.2.2] - 2026-04-03

### Features

- Add configurable workflow execution timeout via Temporal
- Enforce structured handoff reports for specialist agents
- Add adaptive complexity tiers to investigation planning
- Improve shared context robustness with semantic dedup, stable IDs, and compaction
- Add lightweight poll query and auto-approve quick check investigations
- Replace hardcoded checkpoint messages with LLM-powered progress reporter (Gemini-style "grace turn")

### Fixes

- Truncate large UTCP tool results to prevent Temporal payload overflow (100KB default limit)
  - Smart truncation for Kubernetes-style list responses with item count metadata
  - Hard truncation with warning for other large results

### Refactoring

- Extract agent prompts to external markdown files and add output style constraints
- Merge PlanningAgent + ContextAgent into single OrchestratorAgent with direct UTCP tool access

## [0.2.1] - 2026-04-01

### Features

- Add multi-instance UTCP support across all agents (e.g., `kubernetes-first`, `kubernetes-second`)
- Add auth provider registry with kubeconfig, bearer, and no-auth providers
- Add `create_grouped_utcp_workflow_tools` for type-grouped tool loading
- Add service type registry for multi-instance lookups
- Surface instance names in PlanningAgent, ContextAgent, and InvestigationAgent instructions

### Refactoring

- Extract authentication logic from loader into dedicated `utcp/auth.py` module
- Extract serialization helpers into `utcp/serializers.py` module
- Simplify `utcp/loader.py` by delegating to auth providers and spec strategies
- Move HTTP method constants (`READ_HTTP_METHODS`, `WRITE_HTTP_METHODS`) to `utcp/config.py`

### Tests

- Add tests for auth providers, config, registry, serializers, and specialists

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
