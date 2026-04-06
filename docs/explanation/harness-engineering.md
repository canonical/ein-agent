# Engineering an Operations Agent

This document explains the key challenges in building AI agents for infrastructure operations and how ein-agent addresses them.

## Why Operations Agents Are Hard

An operations agent investigates live infrastructure — Kubernetes clusters, Ceph storage, Grafana dashboards — under real incident pressure. This creates challenges that don't exist in code generation or chatbot use cases:

- **Wrong information is worse than no information.** A hallucinated metric or invented error message can send an operator down a wrong path during an incident. The agent must be structurally resistant to producing unfounded claims.
- **The blast radius is production.** Unlike a coding agent where mistakes are caught in review, an operations agent queries (and could potentially mutate) live systems. Safety constraints must be enforced at the tool layer, not just in prompts.
- **Investigations span multiple domains.** A single alert may involve compute, storage, network, and observability. No single agent can reliably reason across all domains without producing shallow or incorrect cross-domain conclusions.
- **Long-running workflows degrade.** As context windows fill, models rush to conclusions, lose track of earlier findings, or loop. Operations investigations are inherently multi-step and can run long.
- **Self-evaluation is unreliable.** Agents confidently praise their own mediocre analysis. An agent that says "I've thoroughly investigated this" has told you nothing about whether it actually has.

## Design Principles

### Make Wrong Information Structurally Hard to Produce

This is the most important principle for operations agents. Rather than trusting the model to self-regulate accuracy, design the system so that producing unfounded claims requires actively working against the structure.

Ein-agent applies this through:

- **Tool-output-only assertions**: Specialist agents are instructed to base findings exclusively on data returned by tool calls. If a tool call fails or returns no data, the agent must report the gap rather than fill it with plausible-sounding information.
- **Domain-scoped tools as evidence boundaries**: A Compute Specialist has no storage tools, so it cannot make unsupported claims about storage state. The tool boundary is also an evidence boundary — agents can only assert what their tools returned.
- **Structured handoff reports with evidence fields**: `SpecialistHandoffReport` requires agents to attach specific tool call results as evidence for each finding. This forces a traceable link between claim and observation.
- **Auto-inject skills for known failure patterns**: When agents encounter specific error conditions (e.g., 403/404 responses), injected skills override the model's tendency to retry or invent workarounds. This converts hallucination-prone situations into deterministic behaviour.

### Separate Concerns Across Agent Roles

A single agent that manages conversation, plans investigation, and queries infrastructure will cut corners. Ein-agent enforces separation:

- **Orchestrator**: Manages conversation, delegation, and synthesis. Has access to all UTCP tools for "surgical" direct queries on simple issues, but delegates to specialists for structured multi-step investigations.
- **Investigation Agent**: Coordinates specialist execution. Has **no** UTCP tools — it must delegate all infrastructure queries to specialists.
- **Domain Specialists** (Compute, Storage, Network, Observability): Have domain-scoped UTCP tools only. Cannot access tools outside their domain.

The key constraint is at the Investigation Agent level: it enforces that multi-step investigations go through domain specialists rather than querying infrastructure directly.

### Enforce Safety at the Tool Layer, Not Just in Prompts

Prompts can be ignored or misinterpreted. Tool-layer constraints cannot:

- **Read-only tool filtering**: UTCP tools are filtered to GET-only HTTP methods by default. Even if the agent's prompt is ignored, the tool layer prevents mutation of live infrastructure. This is a deterministic, computational control applied on every tool call.
- **Domain-scoped tool sets**: Specialists receive only tools relevant to their domain. This prevents accidental cross-domain operations regardless of what the prompt says.

### Gate Plans, Not Every Step

Requiring human approval for every action makes the agent useless during incidents. Requiring no approval makes it dangerous. Ein-agent takes a middle path:

1. The Orchestrator assesses complexity (Quick Check, Standard, or Complex) and builds an investigation plan.
2. For Standard and Complex investigations, the plan is presented to the user for approval before execution begins.
3. Once approved, specialist delegation runs **fully automatically** — specialists execute a mandatory five-step workflow (Scope, Investigate, Correlate, Validate, Report) and return structured findings.

The human approves the *plan*; the *execution* runs autonomously with structural guarantees (scoped tools, structured outputs, auto-persistence).

### Manage Context Across Agent Boundaries

The context window is a finite resource. Operations investigations that run in a single context will degrade as findings accumulate.

Ein-agent mitigates this through its Temporal architecture:

- **Fresh context per specialist**: Each specialist runs as a separate agent invocation with its own context window. The Orchestrator hands off a scoped task description, not the entire conversation history.
- **Shared Context (Blackboard)**: A persistent, structured store that survives across agent invocations without consuming context window space. Every finding includes stable IDs (preventing duplicates), agent attribution, confidence scores (0.0-1.0), and semantic grouping.
- **Max turn limits**: Hard stops at both workflow and per-agent levels prevent runaway context accumulation.

This is closer to Anthropic's "context reset" pattern than to in-place compaction — each agent starts clean and writes structured results to a shared store.

### Treat Prompts as Engineering Artifacts

Agent instructions are extracted into external Markdown files rather than embedded in code. This makes them reviewable, versionable, and tunable independently of agent logic.

Key feedforward controls encoded in prompts:

- **Safety awareness prompts**: Injected into all agent instructions to prevent destructive operations.
- **Structured interaction models**: Workflow interruptions use typed models (`WorkflowInterruption`) to enforce machine-parseable agent-to-user communication.
- **Adaptive complexity tiers**: Investigation planning matches depth to problem severity, preventing over-investigation of simple issues.

Prompt wording steers output in ways that are hard to predict upfront. Extracting prompts into separate files makes tuning an iterative engineering process with version control and review.

## Stress-Testing Assumptions

Every structural constraint encodes an assumption about what the model cannot do on its own. As models improve, some constraints may become unnecessary. The method is: remove one component at a time on realistic scenarios and observe whether quality degrades.

| Component | Assumption it encodes |
|-----------|----------------------|
| Role separation (Orchestrator / Investigation Agent / Specialists) | A single agent cannot reliably manage conversation AND coordinate investigation AND query infrastructure |
| Plan approval before execution | The model will over-scope or mis-scope investigations without human validation |
| Structured handoff reports | The model will produce inconsistent or incomplete findings without enforced output schemas |
| Auto-persistence on handoff | The model may forget to save findings to the shared context |
| Read-only tool filtering | The model may attempt write operations despite instructions |
| Complexity tiers | The model cannot self-calibrate investigation depth |
| Confidence scoring | The model needs explicit numeric scoring to surface uncertainty |
| Max turn limits | The model may loop indefinitely without hard stops |
| Evidence-grounding constraints | The model will hallucinate observations it never made without structural enforcement |

## Further Reading

- [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/) — feedforward/feedback controls, computational vs inferential sensors
- [Harness engineering for coding agent users](https://martinfowler.com/articles/exploring-gen-ai/harness-engineering.html) — Fowler's elaboration with the cybernetic model
- [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) — generator-evaluator separation, context management, sprint contracts, stress-testing assumptions
