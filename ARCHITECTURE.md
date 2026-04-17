# L1 Virtual Engineer Agent - Architecture & Design Document

## 1. Overview

The L1 Virtual Engineer Agent automates L1 incident triage and resolution by:
1. Ingesting incidents from ServiceNow (webhook or polling)
2. Matching incidents to Standard Operating Procedures (SOPs)
3. Executing SOP steps using approved tool integrations
4. Updating the ServiceNow incident with evidence and outcomes
5. Escalating to L2 when appropriate

## 2. Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        L1 Agent Service                             │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐ │
│  │ Webhook      │  │ Polling      │  │ Health Check              │ │
│  │ Listener     │  │ Worker       │  │ Endpoint                  │ │
│  │ POST /webhook│  │ (async loop) │  │ GET /health               │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────────────────────┘ │
│         │                 │                                         │
│         └────────┬────────┘                                         │
│                  ▼                                                   │
│  ┌──────────────────────────────────┐                               │
│  │      Incident Processor          │                               │
│  │  - Idempotency check             │                               │
│  │  - AI or rule-based routing      │                               │
│  │  - SOP matching / execution      │                               │
│  │  - Incident update               │                               │
│  │  - Escalation handling           │                               │
│  └──────────┬───────────────────────┘                               │
│             │                                                       │
│      ┌──────┴──────┐                                                │
│      ▼             ▼                                                │
│  ┌─────────────────────────┐   ┌────────────────────────────┐      │
│  │   AI / LLM Engine       │   │  Rule-Based Engine          │      │
│  │  ┌───────────────────┐  │   │  ┌──────┐  ┌──────────┐   │      │
│  │  │ LLM Client        │  │   │  │ SOP  │  │ SOP      │   │      │
│  │  │ (OpenAI-compat.)  │  │   │  │Matcher│  │ Parser   │   │      │
│  │  └───────────────────┘  │   │  └──────┘  └──────────┘   │      │
│  │  ┌───────────────────┐  │   │  ┌────────────────────┐   │      │
│  │  │ AI Analyzer       │  │   │  │ SOP Executor       │   │      │
│  │  │ (SOP selection)   │  │   │  │ (deterministic)    │   │      │
│  │  └───────────────────┘  │   │  └────────────────────┘   │      │
│  │  ┌───────────────────┐  │   └────────────────────────────┘      │
│  │  │ AI Executor       │  │                                       │
│  │  │ (tool-calling     │  │                                       │
│  │  │  loop + reasoning)│  │                                       │
│  │  └───────────────────┘  │                                       │
│  │  ┌───────────────────┐  │                                       │
│  │  │ Tool Definitions  │  │                                       │
│  │  │ (LLM functions)   │  │                                       │
│  │  └───────────────────┘  │                                       │
│  └─────────────────────────┘                                       │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Tool Adapters                             │    │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────────┐  │    │
│  │  │ Splunk  │ │  IR360  │ │ Autosys  │ │ Windows Share   │  │    │
│  │  │ REST API│ │ MQ API  │ │ CLI      │ │ SMB Reader      │  │    │
│  │  └─────────┘ └─────────┘ └──────────┘ └─────────────────┘  │    │
│  │  ┌───────────┐ ┌──────────────┐ ┌──────────────────────┐   │    │
│  │  │ Dynatrace │ │ Web UI       │ │ Mainframe TN3270     │   │    │
│  │  │ REST API  │ │ Scraper      │ │ BEIM ASYNC           │   │    │
│  │  └───────────┘ └──────────────┘ └──────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Observability                             │    │
│  │  ┌──────────────┐ ┌──────────┐ ┌───────────────────────┐   │    │
│  │  │ Structured   │ │ Metrics  │ │ Audit Trail           │   │    │
│  │  │ JSON Logging │ │ Collector│ │ (per-step evidence)   │   │    │
│  │  └──────────────┘ └──────────┘ └───────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. Data Flow

### 3.1 Incident Lifecycle

```
1. INTAKE        ServiceNow incident arrives (webhook POST or polling query)
                 ↓
2. DEDUP         Check idempotency (have we processed this incident number?)
                 ↓
3. SOP MATCH     Match short_description + CI/category/assignment_group to SOP
                 → If no SOP or confidence < threshold → ESCALATE
                 ↓
4. EXECUTE       Parse SOP steps; execute sequentially via tool adapters
                 → Post work notes at each step
                 → Collect evidence (tool output summaries)
                 → Handle DECISION branching
                 → If step requires approval → ESCALATE
                 ↓
5. UPDATE        Post final work note with execution summary
                 Set incident state (Resolved or escalated)
                 ↓
6. COMPLETE      Log audit trail; update metrics
```

### 3.2 AI-Driven Mode (Primary)

When `LLM_ENABLED=true`, the LLM is the primary decision-maker:

```
1. INTAKE        Incident arrives
                 ↓
2. AI ANALYSIS   LLM reads ticket (short_description, description, CI, category)
                 → Returns preliminary analysis and key observations
                 ↓
3. AI SOP MATCH  LLM selects the best SOP via function calling (select_sop tool)
                 → Returns SOP ID, confidence, and rationale
                 → If no match or low confidence → ESCALATE
                 ↓
4. AI EXECUTION  LLM drives a tool-calling loop:
                 → LLM decides which tool to call next (splunk_search, mq_check, etc.)
                 → Tool adapter executes the call, returns results
                 → LLM interprets results and decides next action
                 → Repeats until LLM calls resolve_incident or escalate_to_l2
                 ↓
5. UPDATE        Post conclusion work note with evidence summary
```

The LLM uses OpenAI-compatible function calling. Tool definitions expose every
adapter as a callable function with typed parameters. The AI Executor runs an
async loop: send messages → receive tool_calls → execute → feed results back.

### 3.3 Rule-Based Mode (Fallback)

When `LLM_ENABLED=false` or the LLM is unreachable, the system falls back to
deterministic keyword/regex matching and sequential step execution.

### 3.4 Rule-Based SOP Matching Algorithm

The rule-based matcher scores each SOP against the incident using weighted criteria:

| Criterion | Weight | Method |
|-----------|--------|--------|
| Keyword match in short_description | 0.40 | Exact substring + regex patterns |
| CI (CMDB CI) match | 0.20 | Exact match against applicable_services |
| Category match | 0.20 | Exact match against applicable_categories |
| Assignment group match | 0.20 | Exact match against applicable_assignment_groups |

- Score >= threshold (default 0.6): proceed with SOP
- Score < threshold: escalate to L2 with explanation

### 3.5 Step Execution

Each SOP step is dispatched to the appropriate tool adapter:

| Step Type | Adapter | Parameters |
|-----------|---------|------------|
| `SPLUNK_SEARCH` | SplunkAdapter | query, time_range, index |
| `MQ_CHECK` | IR360Adapter | queue_manager, queue, action (depth/browse/status) |
| `FILE_CHECK` | WindowsShareAdapter | unc_path, pattern, last_n_lines, time_window |
| `AUTOSYS_STATUS` | AutosysAdapter | job_name, action (status/dependencies) |
| `DYNATRACE_VM_CHECK` | DynatraceAdapter | host_name, host_group (VM health via Dynatrace Entities/Problems API) |
| `DYNATRACE_METRICS` | DynatraceAdapter | metric_selector, entity_selector, time_range (CPU/memory via Metrics API) |
| `WEB_UI_CHECK` | WebUIScraperAdapter | url, check_type, click_steps, expected_text (headless Selenium click-path) |
| `MAINFRAME_CHECK` | MainframeAdapter | job_name, expected_status, action (TN3270 BEIM ASYNC screen scrape) |
| `DECISION` | Internal | rule (any_failed, all_success, custom) |
| `NOTE` | Internal | text (posted as work note) |

## 4. Security Model

### 4.1 Principles

- **Read-only by default**: All tool adapters perform read-only operations
- **Approval gates**: Steps with `requires_approval: true` trigger escalation
- **Least privilege**: Each adapter uses minimum required permissions
- **No secrets in code**: All credentials via environment variables / vault

### 4.2 Input Validation

| Component | Validation |
|-----------|------------|
| Autosys CLI | Job name regex: `^[a-zA-Z0-9_.\-/]+$` (no shell metacharacters) |
| Windows share | UNC paths validated against allow-list prefixes |
| Splunk queries | Parameterized via REST API (no shell execution) |
| IR360 | API calls with typed parameters |

### 4.3 Log Redaction

Sensitive fields are automatically redacted in structured logs:
- `password`, `token`, `secret`, `api_key`, `authorization`
- Custom patterns configurable via settings

### 4.4 RBAC

| Role | Permissions |
|------|-------------|
| Agent (service account) | Read incidents, read SOPs, post work notes, read-only tool access |
| L2 Engineer | Approve write actions, override escalations |
| Admin | Configure SOPs, manage allow-lists, view audit logs |

## 5. Reliability

### 5.1 Retry Strategy

- Exponential backoff: `base_delay * 2^attempt` with jitter
- Default: 3 attempts, 1s base delay
- Configurable per adapter

### 5.2 Circuit Breaker

Each tool adapter has an independent circuit breaker:
- **Closed** (normal): requests pass through
- **Open** (tripped): requests fail immediately (after N consecutive failures)
- **Half-open**: after reset timeout, allow one probe request

Default: 5 failures to trip, 60s reset timeout.

### 5.3 Concurrency

- `asyncio.Semaphore` limits concurrent incident processing (default: 5)
- Each incident processed in its own async task
- Polling and webhook intake run concurrently

### 5.4 Idempotency

- Incident numbers tracked in a processed set
- Re-processing the same incident is a no-op
- Work notes include timestamps to detect duplicates

## 6. Observability

### 6.1 Structured Logging

All logs are JSON-lines format with:
- `timestamp` (ISO 8601)
- `level` (INFO, WARNING, ERROR)
- `correlation_id` (incident number)
- `component` (module name)
- `message`
- `extra` (context-specific fields)

### 6.2 Metrics

In-process metrics collector tracks:
- `incidents_processed_total` (counter)
- `incidents_escalated_total` (counter)
- `sop_match_confidence` (gauge/histogram)
- `step_execution_duration_seconds` (histogram)
- `adapter_errors_total` (counter, per adapter)

### 6.3 Audit Trail

Every step execution produces an audit record:
```json
{
  "step_id": "step-2",
  "step_type": "MQ_CHECK",
  "status": "success",
  "tool_called": "IR360",
  "input_summary": "queue_manager=QM1, queue=PAYMENT.IN",
  "output_summary": "depth=1523, status=RUNNING",
  "evidence_snippet": "Queue depth: 1523 (threshold: 1000)",
  "started_at": "2026-01-15T10:30:00Z",
  "completed_at": "2026-01-15T10:30:02Z",
  "duration_seconds": 2.1
}
```

## 7. Escalation Design

### 7.1 Escalation Triggers

| Trigger | Action |
|---------|--------|
| No matching SOP | Post "No SOP found" note, assign to L2 |
| SOP confidence < threshold | Post alternatives, assign to L2 |
| Tool access denied | Post error details, assign to L2 |
| Ambiguous/inconsistent data | Post findings, request L2 review |
| Write action required | Post approval request, pause execution |
| Step execution failure (after retries) | Post error + evidence, assign to L2 |

### 7.2 Escalation Packet

When escalating, the agent posts a structured summary:
```
[L1 Agent Escalation]
Incident: INC0012345
SOP: SOP-MQ-001 (MQ Queue Depth High)
Reason: Step failed after 3 retries

Checks performed:
  [OK] step-1: MQ queue depth check - depth=1523
  [OK] step-2: Splunk log search - 3 errors found
  [FAIL] step-3: Autosys job status - Connection timeout

Action needed: Verify Autosys connectivity; review job BATCH_PAYMENT_001
```

## 8. SOP Schema

### 8.1 SOP Definition

```json
{
  "sop_id": "SOP-MQ-001",
  "title": "MQ Queue Depth High - Investigation",
  "applicable_services": ["PaymentService", "OrderService"],
  "applicable_categories": ["Middleware"],
  "applicable_assignment_groups": ["L1-Middleware-Support"],
  "keywords": ["queue depth", "mq.*high", "message.*backlog"],
  "steps": [...],
  "pre_checks": ["Verify MQ monitoring access"],
  "tools_required": ["IR360", "Splunk"],
  "escalation_criteria": {
    "max_retry_count": 3,
    "escalate_on_access_denied": true,
    "escalate_on_ambiguous_result": true,
    "escalate_on_write_action": true
  },
  "version": "1.2"
}
```

### 8.2 Step Definition

```json
{
  "step_id": "step-2",
  "step_type": "MQ_CHECK",
  "description": "Check current queue depth",
  "parameters": {
    "queue_manager": "PROD.QM1",
    "queue": "PAYMENT.IN",
    "action": "depth"
  },
  "expected_output": "depth < 1000",
  "on_success": "step-3",
  "on_failure": "step-escalate",
  "requires_approval": false,
  "timeout_seconds": 30
}
```

## 9. Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Async framework | asyncio + aiohttp |
| Data validation | Pydantic v2 |
| HTTP client | aiohttp.ClientSession |
| Testing | pytest + pytest-asyncio |
| Linting | ruff |
| Container | Docker (python:3.11-slim) |
| Configuration | Environment variables (.env) |

## 10. AI / LLM Integration

### 10.1 LLM Client

The `LLMClient` (`src/l1_agent/ai/llm_client.py`) connects to any OpenAI-compatible
API endpoint. It supports:

- Chat completions with tool/function calling
- Configurable model, temperature, max tokens, timeout
- Automatic retry with exponential backoff
- API key loaded from `LLM_API_KEY` environment variable (never logged)

### 10.2 Tool Definitions

`src/l1_agent/ai/tool_definitions.py` exposes adapters as LLM-callable functions:

| Function | Adapter | Purpose |
|----------|---------|--------|
| `splunk_search` | SplunkAdapter | Search logs by query and time range |
| `mq_check` | IR360Adapter | Check MQ queue depth / status |
| `file_check` | WindowsShareAdapter | Read log file lines, filter by pattern |
| `autosys_status` | AutosysAdapter | Query job status or dependencies |
| `dynatrace_vm_check` | DynatraceAdapter | Check VM/host health (entities + problems) |
| `dynatrace_metrics_check` | DynatraceAdapter | Query CPU/memory metrics from Dynatrace |
| `web_ui_check` | WebUIScraperAdapter | Navigate URL click-path via headless Selenium |
| `mainframe_async_check` | MainframeAdapter | Check MF BEIM ASYNC job status via TN3270 |
| `post_work_note` | (internal) | Post a work note to the incident |
| `escalate_to_l2` | (internal) | Escalate with reason and findings |
| `resolve_incident` | (internal) | Resolve with summary and evidence |

### 10.3 AI Analyzer

`AIAnalyzer` sends the incident context to the LLM and asks it to:
1. Produce a preliminary analysis (key observations, likely root cause)
2. Select the best SOP via `select_sop` tool call (returns SOP ID + confidence + rationale)
3. Interpret individual tool results when needed

### 10.4 AI Executor

`AIExecutor` runs an async tool-calling loop:
1. Build a system prompt with SOP context, available tools, and investigation guidelines
2. Send to LLM; receive response.
3. If response contains `tool_calls`, execute each via the appropriate adapter.
4. Feed tool results back as `tool` messages.
5. Repeat until the LLM calls `resolve_incident` or `escalate_to_l2` (or max iterations reached).

### 10.5 Mock LLM

`MockLLMClient` provides realistic responses without a real API. It supports:
- **Scripted mode**: Pre-defined responses returned in order (for deterministic tests)
- **Auto mode**: Generates contextual responses based on message content (for demos)

## 11. New Tool Adapters (v2)

### 11.1 Dynatrace Adapter (`DynatraceAdapter`)

Connects to the Dynatrace REST API for two use cases:

- **VM Health Check** (`dynatrace_vm_check`): Queries the Entities API (`/api/v2/entities`) to find hosts matching a name filter, then queries the Problems API (`/api/v2/problems`) for active problems affecting those hosts. Returns host details, problem count, and overall healthy/unhealthy status.
- **Metrics Check** (`dynatrace_metrics_check`): Queries the Metrics API (`/api/v2/metrics/query`) for time-series data such as `builtin:host.cpu.usage` and `builtin:host.mem.usage`. Returns latest values with threshold evaluation.

Configuration: `DYNATRACE_BASE_URL`, `DYNATRACE_API_TOKEN`, `DYNATRACE_VERIFY_SSL`, `DYNATRACE_TIMEOUT`.

### 11.2 Web UI Scraper Adapter (`WebUIScraperAdapter`)

Uses headless Selenium/ChromeDriver to perform automated click-path navigation on web applications. Supports two check types:

- **Page Load** (`check_type: page_load`): Navigates to a URL, captures title, load time, page size, and optionally verifies expected text is present.
- **Click Path** (`check_type: click_path`): Navigates to a URL then executes a sequence of steps (click, type, wait, assert_text, screenshot) defined as a list of actions with CSS/XPath selectors.

Used for both **Application URL UI Actions** and **GCAS Launcher** checks. Runs in headless mode (no visible browser).

Configuration: `WEBUI_PAGE_TIMEOUT`, `WEBUI_ALLOWED_DOMAINS`, `WEBUI_CHROME_BINARY`.

### 11.3 Mainframe Adapter (`MainframeAdapter`)

Connects to mainframe systems via TN3270 terminal emulator (using py3270 library) for screen scraping. All operations are read-only.

- **ASYNC Status** (`mainframe_async_check`): Navigates to the BEIM status screen and parses job statuses. Looks for "inact ok" to confirm jobs completed successfully. Recognizes statuses: inact ok, active, inact error, inact abend, waiting, stopped.
- **Screen Check** (`screen_check`): Navigates to any screen and checks for expected text presence.

Configuration: `MAINFRAME_HOST`, `MAINFRAME_PORT`, `MAINFRAME_ALLOWED_TRANSACTIONS`, `MAINFRAME_TIMEOUT`.

## 12. Future Enhancements

- **Vault integration**: HashiCorp Vault / AWS Secrets Manager for production secrets
- **Kubernetes deployment**: Helm chart with HPA for auto-scaling
- **Fine-tuned SOP matching model**: Train on historical incident-SOP pairs
- **Approval workflow UI**: Web dashboard for L2 engineers to approve write actions
- **Prometheus/Grafana**: Export metrics for monitoring dashboards
- **Event-driven intake**: Kafka/RabbitMQ consumer for high-throughput environments
- **Multi-turn conversation**: Allow L2 engineers to chat with the agent about an incident
- **RAG over SOP corpus**: Retrieve relevant SOP sections via vector search for very large SOP libraries
