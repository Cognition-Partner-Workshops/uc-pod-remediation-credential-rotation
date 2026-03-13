# Automated Remediation of Pod Failures After Credential Rotations

## Overview

Production incidents frequently occur after password/credential rotations when application pods continue using stale credentials. This project provides an agentic solution that automates detection, approval, and remediation to reduce downtime and operational risk.

## Problem Statement

L3 teams manually track rotations, monitor services, and restart affected pods, creating delays and increasing the risk of prolonged outages. Without automation, mean time to recovery (MTTR) is measured in hours rather than minutes.

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Rotation Monitoring│────▶│  Failure Detection    │────▶│  Approval Workflow  │
│  Agent              │     │  Agent                │     │  Agent (ServiceNow) │
└─────────────────────┘     └──────────────────────┘     └─────────┬───────────┘
                                                                    │
                                                          ┌─────────▼───────────┐
                                                          │  Remediation        │
                                                          │  Orchestrator Agent │
                                                          └─────────────────────┘
```

### Agent Responsibilities

| Agent | Role |
|-------|------|
| **Rotation Monitoring Agent** | Tracks scheduled credential rotations and maps impacted services |
| **Failure Detection Agent** | Identifies pods running with outdated credentials using logs and metrics |
| **Approval Workflow Agent** | Initiates approval requests via ServiceNow integration |
| **Remediation Orchestrator Agent** | Restarts or refreshes affected services upon approval |

## Project Structure

```
├── src/
│   ├── agents/                  # Agent implementations
│   │   ├── rotation_monitor.py  # Tracks credential rotation schedules
│   │   ├── failure_detector.py  # Detects pods with stale credentials
│   │   ├── approval_workflow.py # ServiceNow approval integration
│   │   └── remediation.py       # Pod restart/refresh orchestration
│   ├── config/                  # Configuration management
│   │   └── settings.py          # App settings and env config
│   ├── models/                  # Data models
│   │   ├── credential.py        # Credential and rotation models
│   │   └── service_account.py   # Service account inventory
│   └── utils/                   # Shared utilities
│       ├── k8s_client.py        # Kubernetes API client wrapper
│       └── servicenow_client.py # ServiceNow API client
├── k8s/
│   ├── base/                    # Base Kubernetes manifests
│   │   ├── deployment.yaml      # Agent deployment
│   │   ├── configmap.yaml       # Configuration
│   │   ├── rbac.yaml            # RBAC for pod management
│   │   └── secret.yaml          # Secret template
│   └── overlays/
│       └── production/          # Production kustomize overlay
│           └── kustomization.yaml
├── data/
│   └── sample_inventory.json    # Sample service account inventory
├── tests/                       # Test suite
├── docs/                        # Documentation
├── requirements.txt
├── Dockerfile
└── .gitignore
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Kubernetes cluster and ServiceNow details

# Run the rotation monitoring agent
python -m src.agents.rotation_monitor

# Run the failure detection agent
python -m src.agents.failure_detector
```

## Configuration

Set the following environment variables (see `.env.example`):

| Variable | Description |
|----------|-------------|
| `K8S_NAMESPACE` | Target Kubernetes namespace |
| `K8S_KUBECONFIG` | Path to kubeconfig file |
| `SERVICENOW_URL` | ServiceNow instance URL |
| `SERVICENOW_USER` | ServiceNow API user |
| `SERVICENOW_PASSWORD` | ServiceNow API password |
| `ROTATION_CHECK_INTERVAL` | Seconds between rotation checks (default: 60) |
| `FAILURE_CHECK_INTERVAL` | Seconds between failure scans (default: 30) |

## Business Outcomes

- **Reduced MTTR**: Faster detection and remediation of credential-related failures
- **Operational Reliability**: Fewer production incidents after rotations
- **Risk Reduction**: Controlled, auditable remediation workflows

## Controls

Human approval gates remain mandatory before any production restart. All remediation actions are logged for audit compliance.

## License

MIT
