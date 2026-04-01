# How to configure the Ein Agent worker

This guide covers all configuration options for the Ein Agent worker, including UTCP service setup, authentication, multi-instance support, OpenAPI spec loading, and tool call approval policies.

For deployment steps (Temporal, Juju, secrets), see [How to deploy Ein Agent](./how-to-deploy-ein-agent.md).

## UTCP service configuration

UTCP (Universal Tool Calling Protocol) generates tools dynamically from OpenAPI specifications. Each service requires:

| Variable | Description |
|----------|-------------|
| `UTCP_SERVICES` | Comma-separated list of services to enable |
| `UTCP_{SERVICE}_OPENAPI_URL` | URL to the service's OpenAPI spec |
| `UTCP_{SERVICE}_AUTH_TYPE` | Authentication: `kubeconfig`, `bearer`, `api_key`, `jwt`, `none` |
| `UTCP_{SERVICE}_VERSION` | Optional: spec version (e.g., `1.35`, `tentacle`) |
| `UTCP_{SERVICE}_ENABLED` | Optional: enable/disable service (default: true) |
| `UTCP_{SERVICE}_INSECURE` | Optional: skip TLS verification (default: false) |
| `UTCP_{SERVICE}_SPEC_SOURCE` | Optional: `local` or `live` (default: `local`) |
| `UTCP_APPROVAL_POLICY` | Optional: global approval policy for all services (default: `read_only`) |
| `UTCP_{SERVICE}_APPROVAL_POLICY` | Optional: per-service override for approval policy |

### Supported services

- **kubernetes**: Requires `kubeconfig` auth (kubeconfig passed via Juju secret)
- **grafana**: Requires `bearer` auth (service account token via Juju secret)
- **ceph**: Requires `jwt` auth (Ceph dashboard JWT token)
- **prometheus**: Supports `none` auth (no token needed when accessed via COS proxy) or `bearer` auth
- **loki**: Supports `none` auth (no token needed via COS proxy) or `bearer` auth. Uses a hand-written OpenAPI spec (Loki does not ship an official one)

### Supported versions

| Service | Versions | Default |
|---------|----------|---------|
| kubernetes | 1.35, 1.34, 1.33 | 1.35 |
| grafana | 12, 11 | 12 |
| ceph | tentacle, squid, reef | tentacle |
| prometheus | 3.5.0 | 3.5.0 |
| loki | 3 | 3 |

### Example single-instance configuration

```yaml
env:
  - name: UTCP_SERVICES
    value: kubernetes,grafana,ceph,prometheus,loki

  - name: UTCP_KUBERNETES_OPENAPI_URL
    value: https://kubernetes.default.svc.cluster.local/openapi/v2
  - name: UTCP_KUBERNETES_AUTH_TYPE
    value: kubeconfig
  - name: UTCP_KUBERNETES_VERSION
    value: "1.35"
  - name: UTCP_KUBERNETES_INSECURE
    value: "true"

  - name: UTCP_GRAFANA_OPENAPI_URL
    value: https://grafana.cos.svc.cluster.local:3000/api/swagger.json
  - name: UTCP_GRAFANA_AUTH_TYPE
    value: bearer
  - name: UTCP_GRAFANA_VERSION
    value: "12"
  - name: UTCP_GRAFANA_INSECURE
    value: "true"

juju:
  - secret-id: <kubernetes-secret-id>
    name: UTCP_KUBERNETES_KUBECONFIG_CONTENT
    key: kubeconfig-content

  - secret-id: <grafana-secret-id>
    name: UTCP_GRAFANA_TOKEN
    key: token
```

## Configure multiple instances of the same service

To connect the agent to multiple clusters or endpoints of the same service type (e.g., two Kubernetes clusters, two Grafana instances), give each instance a unique name with the service type as a prefix.

### 1. Choose instance names

Instance names must start with a known service type prefix, followed by a hyphen and a descriptive suffix:

| Service type | Single instance name | Multi-instance names |
|---|---|---|
| `kubernetes` | `kubernetes` | `kubernetes-prod`, `kubernetes-staging` |
| `grafana` | `grafana` | `grafana-cos`, `grafana-external` |
| `ceph` | `ceph` | `ceph-primary`, `ceph-backup` |

The worker resolves the service type automatically by stripping the suffix (e.g., `kubernetes-prod` resolves to type `kubernetes`). You can also set the type explicitly with `UTCP_{INSTANCE}_TYPE`.

### 2. List all instances in UTCP_SERVICES

```yaml
env:
  - name: UTCP_SERVICES
    value: kubernetes-prod,kubernetes-staging,grafana
```

### 3. Configure each instance separately

Each instance gets its own set of environment variables, using the uppercased instance name with hyphens replaced by underscores:

```yaml
env:
  # --- kubernetes-prod ---
  - name: UTCP_KUBERNETES_PROD_OPENAPI_URL
    value: https://prod-k8s.example.com:6443/openapi/v2
  - name: UTCP_KUBERNETES_PROD_AUTH_TYPE
    value: kubeconfig
  - name: UTCP_KUBERNETES_PROD_INSECURE
    value: "true"
  - name: UTCP_KUBERNETES_PROD_VERSION
    value: "1.35"

  # --- kubernetes-staging ---
  - name: UTCP_KUBERNETES_STAGING_OPENAPI_URL
    value: https://staging-k8s.example.com:6443/openapi/v2
  - name: UTCP_KUBERNETES_STAGING_AUTH_TYPE
    value: kubeconfig
  - name: UTCP_KUBERNETES_STAGING_INSECURE
    value: "true"
  - name: UTCP_KUBERNETES_STAGING_VERSION
    value: "1.35"
```

### 4. Add secrets for each instance

Each instance requires its own credentials:

```bash
# Kubernetes prod kubeconfig
bash -c 'KUBECONFIG_B64=$(cat ein-agent-kubeconfig-prod.yaml | base64 -w 0) && \
  juju add-secret -m temporal kubernetes-prod-auth kubeconfig-content="$KUBECONFIG_B64"'

# Kubernetes staging kubeconfig
bash -c 'KUBECONFIG_B64=$(cat ein-agent-kubeconfig-staging.yaml | base64 -w 0) && \
  juju add-secret -m temporal kubernetes-staging-auth kubeconfig-content="$KUBECONFIG_B64"'

# Grant secrets
juju grant-secret -m temporal kubernetes-prod-auth ein-agent-worker
juju grant-secret -m temporal kubernetes-staging-auth ein-agent-worker
```

Reference each secret in `environment.yaml`:

```yaml
juju:
  - secret-id: <kubernetes-prod-secret-id>
    name: UTCP_KUBERNETES_PROD_KUBECONFIG_CONTENT
    key: kubeconfig-content

  - secret-id: <kubernetes-staging-secret-id>
    name: UTCP_KUBERNETES_STAGING_KUBECONFIG_CONTENT
    key: kubeconfig-content
```

Instance names must be lowercase alphanumeric with hyphens (e.g., `kubernetes-prod`, `grafana-cos`). The worker auto-detects the service type from the prefix before the first hyphen-suffix.

## OpenAPI spec loading: local files vs live URLs

Each UTCP service can be configured to load its OpenAPI spec from either a **local file** or a **live URL** via the `UTCP_{SERVICE}_SPEC_SOURCE` environment variable.

- `local` (default): Load spec from `specs/{service_name}/{version}.{json|yaml}`. Fails if file not found.
- `live`: Fetch spec from `UTCP_{SERVICE}_OPENAPI_URL` at runtime.

### Local spec directory structure

```
rocks/ein-agent-worker/specs/
├── kubernetes/
│   └── 1.35.json
├── grafana/
│   └── 12.json
└── ceph/
    └── tentacle.json
```

### Use local spec files

1. Download the spec to the appropriate directory:
   ```bash
   # Example: Download Kubernetes OpenAPI spec
   curl -k "https://<K8S_SERVER>/openapi/v2" -o specs/kubernetes/1.35.json
   ```

2. Set the version in your environment configuration:
   ```yaml
   - name: UTCP_KUBERNETES_VERSION
     value: "1.35"
   ```

3. The worker will automatically use the local file when it exists.

### Use live URL loading

To fetch from the live URL at runtime, set:
```yaml
- name: UTCP_{SERVICE}_SPEC_SOURCE
  value: "live"
```

### Log output

Local file loading:
```
[kubernetes] Loading OpenAPI spec from LOCAL file: .../specs/kubernetes/1.35.json
```

Live URL loading:
```
[kubernetes] Loading OpenAPI spec from LIVE URL: https://10.x.x.x:6443/openapi/v2
```

## Tool call approval policy

Tool call approval controls whether operations require human approval before execution.

### Available policies

| Policy | Description |
|--------|-------------|
| `read_only` (default) | Auto-approve read operations (GET, LIST), require approval for writes (POST, PUT, PATCH, DELETE) |
| `never` | Approve all operations automatically |
| `always` | Require human approval for every operation |

### Configuration priority

`UTCP_{SERVICE}_APPROVAL_POLICY` > `UTCP_APPROVAL_POLICY` > default (`read_only`)

### Example

```yaml
env:
  # Global approval policy for all services
  - name: UTCP_APPROVAL_POLICY
    value: "never"

  # Override for specific services
  - name: UTCP_CEPH_APPROVAL_POLICY
    value: "always"
```

When approval is required, the workflow will pause and request human input before executing the tool call.

## Agent model configuration

Set the LLM model used by the agent:

```yaml
env:
  - name: EIN_AGENT_MODEL
    value: "gemini/gemini-3-flash-preview"
```

The model string is passed to LiteLLM, which supports multiple providers. See [LiteLLM supported models](https://docs.litellm.ai/docs/providers) for available options.
