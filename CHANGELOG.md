# Changelog

## [0.3.0](https://github.com/canonical/ein-agent/compare/v0.2.3...v0.3.0) (2026-04-06)


### Features

* add safety awareness prompts to all agent instructions ([#13](https://github.com/canonical/ein-agent/issues/13)) ([cfa6995](https://github.com/canonical/ein-agent/commit/cfa6995228a4ecce2b8a11271479c7a18e6ceb71))
* add safety prompts and unit test CI jobs ([cfa6995](https://github.com/canonical/ein-agent/commit/cfa6995228a4ecce2b8a11271479c7a18e6ceb71))


### Bug Fixes

* bootstrap release-please with packages config and last-release-sha ([#14](https://github.com/canonical/ein-agent/issues/14)) ([85a3953](https://github.com/canonical/ein-agent/commit/85a3953e86f72ca0a02b45b5a18d088384953a80))
* use plain string extra-files to avoid YAML reformatting ([#17](https://github.com/canonical/ein-agent/issues/17)) ([5bb657a](https://github.com/canonical/ein-agent/commit/5bb657a4238bb2dbc162d5a314b1edc7e333864b))


### CI/CD

* adopt release-please and enforce conventional commits ([a787678](https://github.com/canonical/ein-agent/commit/a78767826adacd6383794438010edd0cd6932229))
* adopt release-please and enforce conventional commits ([3d4e129](https://github.com/canonical/ein-agent/commit/3d4e1292ec8ca228e123dcb85087541b7cb9aac6)), closes [#8](https://github.com/canonical/ein-agent/issues/8)
* fix snap release ([46acb38](https://github.com/canonical/ein-agent/commit/46acb3872b49df92c842517198c0ea98b4f1a5f3))
* fix snap release ([119b5d4](https://github.com/canonical/ein-agent/commit/119b5d41a49a38c6b6db3a2683bc313cee32d343))
* replace pull_request_target with pull_request in PR title check ([4ece043](https://github.com/canonical/ein-agent/commit/4ece04320631e6d52c65f7240c45d1db8c732428))
* replace pull_request_target with pull_request in PR title check ([f3377ff](https://github.com/canonical/ein-agent/commit/f3377ff1c6cc05acf9467f2ecd9b3799fbd287d2))
* use PAT for release-please to trigger downstream CI ([#16](https://github.com/canonical/ein-agent/issues/16)) ([97ff5a4](https://github.com/canonical/ein-agent/commit/97ff5a438a386ac489a469a2a30eb058348cfa07))

## [0.2.3] - 2026-04-03

### Features

- Add auto-inject skill system for embedding critical knowledge directly in agent prompts
- Add UTCP best practices skill to prevent agents retrying 403/404 errors indefinitely
- Enhance specialist workflow with Scope, Correlate, and Validate phases

### Fixes

- Improve worker log format and suppress noisy third-party loggers

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
