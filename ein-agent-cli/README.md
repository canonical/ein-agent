# Ein Agent CLI

The `ein-agent-cli` is a command-line interface for the Ein Agent system, enabling users to start interactive human-in-the-loop investigation workflows within Temporal.

## Features

-   Start interactive investigation sessions with an AI agent.
-   Connect to existing investigation workflows.

## Installation

### Snap (recommended)

Install `ein-agent` from the Snap Store:

```bash
sudo snap install ein-agent --channel=latest/edge
```

Once installed, the `ein-agent` command is available system-wide.

### From source

For development, install from source using `uv`:

```bash
cd ein-agent-cli
uv sync
```

## Usage

If installed via snap:

```bash
ein-agent [OPTIONS]
```

If running from source:

```bash
uv run python -m ein_agent_cli [OPTIONS]
```

### Start an Interactive Investigation

```bash
# Start interactive investigation with default settings
ein-agent investigate

# Connect to specific Temporal instance
ein-agent investigate --temporal-host localhost:7233
```

### Connect to an Existing Session

```bash
# Reconnect to a running investigation workflow
ein-agent connect --workflow-id hitl-investigation-20231025-120000
```

### Configuration

Configure Temporal connection:

```bash
# Set Temporal host, namespace, and queue
ein-agent investigate \
    --temporal-host localhost:7233 \
    --temporal-namespace default \
    --temporal-queue ein-agent-queue
```

### Getting Help

```bash
ein-agent --help
```
