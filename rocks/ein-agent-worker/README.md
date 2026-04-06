# Ein Agent Worker

A Temporal worker that executes AI-powered troubleshooting workflows using UTCP tools generated from OpenAPI specifications.

## Container Image

Pre-built ROCK images are published to GHCR:

```bash
docker pull ghcr.io/canonical/ein-agent-worker:latest
docker pull ghcr.io/canonical/ein-agent-worker:0.1.0
```

Images are published automatically on pushes to `main` and GitHub releases.

## Deployment

See [How to Deploy Ein Agent](../../docs/how-to-deploy-ein-agent.md) for full deployment instructions.

## Local Development

See [Local Development Guide](./LOCAL_DEVELOPMENT.md) for running the worker locally.

### Building Locally (optional)

```bash
just rock-build    # Build ROCK image
just rock-load     # Load into Docker
just rock-tag      # Tag for registry
just rock-all      # Build, load, and tag in one step
```
