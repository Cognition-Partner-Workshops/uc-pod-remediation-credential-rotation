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
│  │  - SOP matching                  │                               │
│  │  - SOP execution                 │                               │
│  │  - Incident update               │                               │
│  │  - Escalation handling           │                               │
│  └──────────────┬───────────────────┘                               │
│                 │                                                    │
│    ┌────────────┼────────────────────────┐                          │
│    ▼            ▼                        ▼                          │
│  ┌──────┐  ┌──────────┐  ┌────────────────────────┐                │
│  │ SOP  │  │ SOP      │  │ SOP Execution Engine   │                │
│  │Matcher│  │ Parser   │  │                        │                │
│  └──────┘  └──────────┘  │  ┌──────────────────┐  │                │
│                           │  │  Step Executor   │  │                │
│                           │  │  - SPLUNK_SEARCH │  │                │
│                           │  │  - MQ_CHECK      │  │                │
│                           │  │  - FILE_CHECK    │  │                │
│                           │  │  - AUTOSYS_STATUS│  │                │
│                           │  │  - DECISION      │  │                │
│                           │  │  - NOTE          │  │                │
│                           │  └──────────────────┘  │                │
│                           └────────────────────────┘                │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Tool Adapters                             │    │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────────┐  │    │
│  │  │ Splunk  │ │  IR360  │ │ Autosys  │ │ Windows Share   │  │    │
│  │  │ REST API│ │ MQ API  │ │ CLI      │ │ SMB Reader      │  │    │
│  │  └─────────┘ └─────────┘ └──────────┘ └─────────────────┘  │    │
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

### 3.2 SOP Matching Algorithm

The matcher scores each SOP against the incident using weighted criteria:

| Criterion | Weight | Method |
|-----------|--------|--------|
| Keyword match in short_description | 0.40 | Exact substring + regex patterns |
| CI (CMDB CI) match | 0.20 | Exact match against applicable_services |
| Category match | 0.20 | Exact match against applicable_categories |
| Assignment group match | 0.20 | Exact match against applicable_assignment_groups |

- Score >= threshold (default 0.6): proceed with SOP
- Score < threshold: escalate to L2 with explanation

### 3.3 Step Execution

Each SOP step is dispatched to the appropriate tool adapter:

| Step Type | Adapter | Parameters |
|-----------|---------|------------|
| `SPLUNK_SEARCH` | SplunkAdapter | query, time_range, index |
| `MQ_CHECK` | IR360Adapter | queue_manager, queue, action (depth/browse/status) |
| `FILE_CHECK` | WindowsShareAdapter | unc_path, pattern, last_n_lines, time_window |
| `AUTOSYS_STATUS` | AutosysAdapter | job_name, action (status/dependencies) |
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

## 10. Future Enhancements

- **Vault integration**: HashiCorp Vault / AWS Secrets Manager for production secrets
- **Kubernetes deployment**: Helm chart with HPA for auto-scaling
- **ML-based SOP matching**: Train on historical incident-SOP pairs for improved accuracy
- **Approval workflow UI**: Web dashboard for L2 engineers to approve write actions
- **Prometheus/Grafana**: Export metrics for monitoring dashboards
- **Event-driven intake**: Kafka/RabbitMQ consumer for high-throughput environments
