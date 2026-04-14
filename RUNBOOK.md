# L1 Virtual Engineer Agent - Operational Runbook

## 1. Deployment

### 1.1 Prerequisites

- Python 3.11+ or Docker
- Network access to: ServiceNow instance, Splunk REST API, IR360 API, Autosys CLI host, Windows file shares
- Service account credentials for each integration

### 1.2 Container Deployment

```bash
# Build the image
docker build -t l1-agent:latest .

# Run the service
docker run -d \
  --name l1-agent \
  --env-file .env \
  -p 8080:8080 \
  l1-agent:latest

# Run in demo mode (no credentials needed)
docker build --target demo -t l1-agent-demo:latest .
docker run --rm l1-agent-demo:latest
```

### 1.3 Direct Deployment

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with real credentials

# Start the service
python -m src.l1_agent.main

# Or run demo mode
python -m src.l1_agent.demo
```

### 1.4 Health Check

The service exposes a health endpoint:
```
GET http://localhost:8080/health
```

Response:
```json
{"status": "healthy", "mode": "production", "uptime_seconds": 3600}
```

## 2. Configuration

### 2.1 Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SERVICENOW_BASE_URL` | ServiceNow instance URL | `https://company.service-now.com` |
| `SERVICENOW_USERNAME` | API username | `l1_agent_svc` |
| `SERVICENOW_PASSWORD` | API password | (from vault) |
| `SERVICENOW_ASSIGNMENT_GROUP` | Incident queue to monitor | `L1-Support` |

### 2.2 Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICENOW_POLL_INTERVAL` | `30` | Seconds between polling cycles |
| `SPLUNK_BASE_URL` | (none) | Splunk REST API base URL |
| `SPLUNK_TOKEN` | (none) | Splunk bearer token |
| `IR360_BASE_URL` | (none) | IR360 API base URL |
| `IR360_API_KEY` | (none) | IR360 API key |
| `AUTOSYS_CLI_PATH` | `autorep` | Path to autorep binary |
| `WINDOWS_SHARE_ALLOWED_PREFIXES` | (none) | Comma-separated UNC path prefixes |
| `AGENT_SOP_CONFIDENCE_THRESHOLD` | `0.6` | Minimum SOP match confidence |
| `AGENT_MAX_CONCURRENT_INCIDENTS` | `5` | Max concurrent incident processing |
| `AGENT_DEMO_MODE` | `false` | Use mock adapters (no real connections) |
| `AGENT_LOG_LEVEL` | `INFO` | Logging level |
| `AGENT_WEBHOOK_PORT` | `8080` | Webhook listener port |

## 3. Managing SOPs

### 3.1 SOP Storage

SOPs can be stored in:
1. **ServiceNow Knowledge Base** (production): Retrieved via KB API
2. **Local JSON files** (development): Placed in `data/sample_sops/`

### 3.2 Adding a New SOP

1. Create a JSON file following the schema in `ARCHITECTURE.md` Section 8
2. Required fields:
   - `sop_id`: Unique identifier (e.g., `SOP-MQ-002`)
   - `title`: Human-readable title
   - `keywords`: List of strings/regex patterns to match against incident short_description
   - `steps`: Ordered list of step objects
3. Each step requires:
   - `step_id`: Unique within the SOP
   - `step_type`: One of `SPLUNK_SEARCH`, `MQ_CHECK`, `FILE_CHECK`, `AUTOSYS_STATUS`, `DECISION`, `NOTE`
   - `parameters`: Type-specific parameters (see below)

### 3.3 Step Parameters Reference

**SPLUNK_SEARCH**
```json
{
  "query": "index=app_logs sourcetype=payment ERROR",
  "time_range": "-1h",
  "index": "app_logs"
}
```

**MQ_CHECK**
```json
{
  "queue_manager": "PROD.QM1",
  "queue": "PAYMENT.IN",
  "action": "depth"
}
```
Actions: `depth` (queue depth), `status` (channel status), `browse` (peek at messages)

**FILE_CHECK**
```json
{
  "unc_path": "//fileserver/logs/app/payment.log",
  "pattern": "ERROR|FATAL",
  "last_n_lines": 100,
  "time_window": "1h"
}
```

**AUTOSYS_STATUS**
```json
{
  "job_name": "BATCH_PAYMENT_001",
  "action": "status"
}
```
Actions: `status` (job status via autorep), `dependencies` (job dependencies)

**DECISION**
```json
{
  "rule": "any_failed",
  "on_true": "step-escalate",
  "on_false": "step-resolve"
}
```
Rules: `any_failed` (any previous step failed), `all_success` (all steps succeeded)

**NOTE**
```json
{
  "text": "Beginning MQ queue depth investigation for {cmdb_ci}"
}
```

### 3.4 Testing a New SOP

1. Set `AGENT_DEMO_MODE=true`
2. Place the SOP JSON in `data/sample_sops/`
3. Create a sample incident payload matching the SOP keywords
4. Run the demo: `python -m src.l1_agent.demo`
5. Review the console output for correct step execution and work notes

## 4. Troubleshooting

### 4.1 Common Issues

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| No incidents picked up | Wrong assignment group | Check `SERVICENOW_ASSIGNMENT_GROUP` matches the queue |
| SOP not matched | Keywords don't match | Review SOP keywords; check `sop_matcher` debug logs |
| Low confidence escalations | Too few matching criteria | Add `applicable_services`, `applicable_categories` to SOP |
| Adapter timeout | Network/firewall issue | Check connectivity to tool endpoint; review circuit breaker state |
| "Access denied" escalation | Service account permissions | Verify credentials and permissions for the specific tool |
| Duplicate work notes | Idempotency check bypassed | Check if incident number changed; review `processed_ids` set |

### 4.2 Log Analysis

Logs are structured JSON. Filter by correlation ID (incident number):

```bash
# Find all logs for a specific incident
cat agent.log | python -m json.tool | grep "INC0012345"

# Find all errors
cat agent.log | python -c "
import sys, json
for line in sys.stdin:
    try:
        entry = json.loads(line)
        if entry.get('level') == 'ERROR':
            print(json.dumps(entry, indent=2))
    except: pass
"
```

### 4.3 Circuit Breaker Recovery

If an adapter's circuit breaker is open:
1. Check the tool endpoint is reachable
2. Wait for the reset timeout (default: 60s)
3. The next request will be a probe; if it succeeds, the breaker closes
4. If persistent, check credentials and network configuration

### 4.4 Metrics

The agent tracks these metrics in-process:

| Metric | Type | Description |
|--------|------|-------------|
| `incidents_processed_total` | Counter | Total incidents processed |
| `incidents_escalated_total` | Counter | Total incidents escalated to L2 |
| `sop_match_confidence` | Histogram | SOP match confidence distribution |
| `step_execution_duration_seconds` | Histogram | Per-step execution time |
| `adapter_errors_total` | Counter | Errors per adapter |

## 5. Maintenance

### 5.1 Updating SOPs

1. Modify the SOP JSON in ServiceNow or `data/sample_sops/`
2. No agent restart required (SOPs are fetched on each incident)
3. Test changes in demo mode first

### 5.2 Updating Credentials

1. Update the environment variable or vault entry
2. Restart the agent container: `docker restart l1-agent`
3. Verify with health check endpoint

### 5.3 Scaling

- Increase `AGENT_MAX_CONCURRENT_INCIDENTS` for higher throughput
- Deploy multiple instances behind a load balancer (ensure shared dedup store for production)
- For very high volume, consider event-driven intake (Kafka/RabbitMQ)

## 6. Security Checklist

- [ ] Service account uses least-privilege permissions
- [ ] All secrets stored in vault (not environment variables in production)
- [ ] `WINDOWS_SHARE_ALLOWED_PREFIXES` configured to restrict file access
- [ ] `AUTOSYS_ALLOWED_COMMANDS` limited to read-only commands
- [ ] Network policies restrict egress to required endpoints only
- [ ] Structured logs reviewed for accidental secret exposure
- [ ] Audit logs retained per compliance requirements
