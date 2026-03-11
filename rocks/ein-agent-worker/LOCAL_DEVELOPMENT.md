# Local Development Guide

This guide explains how to run the ein-agent-worker locally for development and testing.

## Prerequisites

- Python 3.12+
- uv package manager
- Access to a Temporal server (local or remote)
- (Optional) Kubernetes cluster access for UTCP integration
- (Optional) Gemini API key or other LLM provider credentials

## Quick Start

1. **Set up environment variables**

   Copy the example script and configure your credentials:
   ```bash
   cp run-worker-local.sh run-worker-local.sh.local
   chmod +x run-worker-local.sh.local
   ```

   Edit `run-worker-local.sh.local` and replace placeholder values:
   - `GEMINI_API_KEY`: Your Gemini API key
   - `UTCP_KUBERNETES_OPENAPI_URL`: Your Kubernetes API server URL
   - `UTCP_KUBERNETES_KUBECONFIG_CONTENT`: Base64-encoded kubeconfig with ServiceAccount token
   - `ALERTMANAGER_URL`: Your Alertmanager URL

2. **Install dependencies**

   ```bash
   uv sync
   ```

3. **Run the worker**

   ```bash
   ./run-worker-local.sh.local
   ```

## Configuration

### Environment Variables

Configure all required environment variables:

```bash
# LLM Provider
export GEMINI_API_KEY="your-api-key"
export EIN_AGENT_MODEL="gemini/gemini-3-flash-preview"

# UTCP Service Configuration
export UTCP_SERVICES="kubernetes,grafana"

# Kubernetes UTCP Configuration (kubeconfig-based auth)
export UTCP_KUBERNETES_OPENAPI_URL="https://<K8S_SERVER>:6443/openapi/v2"
export UTCP_KUBERNETES_AUTH_TYPE="kubeconfig"  # REQUIRED for Kubernetes
export UTCP_KUBERNETES_KUBECONFIG_CONTENT="$(cat ein-agent-kubeconfig.yaml | base64 -w 0)"
export UTCP_KUBERNETES_INSECURE="true"  # For self-signed certificates
export UTCP_KUBERNETES_ENABLED="true"
export UTCP_KUBERNETES_VERSION="1.35"

# Grafana UTCP Configuration (bearer token auth)
export UTCP_GRAFANA_OPENAPI_URL="https://<GRAFANA_SERVER>/api/swagger.json"
export UTCP_GRAFANA_AUTH_TYPE="bearer"
export UTCP_GRAFANA_TOKEN="<grafana service account token>"
export UTCP_GRAFANA_INSECURE="true"  # For self-signed certificates
export UTCP_GRAFANA_ENABLED="true"
export UTCP_GRAFANA_VERSION="12"

# Temporal Configuration
export TEMPORAL_HOST="localhost:7233"
export TEMPORAL_NAMESPACE="default"
export TEMPORAL_QUEUE="ein-agent-queue"

# Alertmanager (Optional)
export ALERTMANAGER_URL="http://your-alertmanager-url/cos-alertmanager"
```

Supported LLM models via LiteLLM:
- Gemini: `gemini/gemini-3-flash-preview`, `gemini/gemini-1.5-pro`
- OpenAI: `gpt-4o`, `gpt-4-turbo`
- Other LiteLLM-supported providers

### Kubernetes ServiceAccount Setup

To enable Kubernetes UTCP tools, create a ServiceAccount with appropriate permissions:

```bash
# Create ServiceAccount
kubectl create serviceaccount ein-agent -n default

# Create ClusterRoleBinding (read-only access for troubleshooting)
kubectl create clusterrolebinding ein-agent-viewer \
    --clusterrole=view \
    --serviceaccount=default:ein-agent

# Generate kubeconfig with long-lived token (1 year)
CONTEXT=$(kubectl config current-context)
CLUSTER=$(kubectl config view -o jsonpath="{.contexts[?(@.name=='$CONTEXT')].context.cluster}")
SERVER=$(kubectl config view -o jsonpath="{.clusters[?(@.name=='$CLUSTER')].cluster.server}")
CA_DATA=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name=='$CLUSTER')].cluster.certificate-authority-data}")
TOKEN=$(kubectl create token ein-agent -n default --duration=8760h)  # 1 year

# Create kubeconfig file
cat > ein-agent-kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: $CA_DATA
    server: $SERVER
  name: $CLUSTER
contexts:
- context:
    cluster: $CLUSTER
    user: ein-agent
  name: ein-agent-context
current-context: ein-agent-context
users:
- name: ein-agent
  user:
    token: $TOKEN
EOF
```

## Development Workflow

1. **Make code changes** in `ein_agent_worker/` directory

2. **Test locally** by running the worker:
   ```bash
   ./run-worker-local.sh.local
   ```

3. **Monitor logs** - the worker will output logs showing:
   - UTCP service initialization
   - Workflow execution
   - Activity execution
   - Agent responses

## Troubleshooting

### Worker won't start

- Check that Temporal server is accessible: `telnet localhost 7233`
- Verify Python version: `python --version` (must be 3.12+)
- Ensure dependencies are installed: `uv sync`

### UTCP tools not loading

- Verify kubeconfig is valid: `kubectl --kubeconfig=ein-agent-kubeconfig.yaml get nodes`
- Check OpenAPI URL is accessible: `curl -k $UTCP_KUBERNETES_OPENAPI_URL`
- Verify kubeconfig is base64-encoded correctly: `echo $UTCP_KUBERNETES_KUBECONFIG_CONTENT | base64 -d | head`
- Review worker logs for UTCP initialization errors

### LLM errors

- Verify API key is set: `echo $GEMINI_API_KEY`
- Check model name is correct for your provider
- Ensure you have API quota/credits available
