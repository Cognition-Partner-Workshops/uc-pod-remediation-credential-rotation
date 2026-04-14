"""Mock adapters for demo mode and testing.

These adapters return realistic-looking responses without connecting
to any real external systems.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from src.l1_agent.adapters.base import AdapterResult, BaseAdapter


class MockSplunkAdapter(BaseAdapter):
    """Returns sample Splunk search results."""

    @property
    def adapter_name(self) -> str:
        return "MockSplunk"

    async def health_check(self) -> bool:
        return True

    async def execute(self, parameters: Dict[str, Any]) -> AdapterResult:
        _query = parameters.get("query", "")  # noqa: F841 - kept for interface clarity
        results = [
            {
                "_raw": "2026-04-14 09:55:00 ERROR [PaymentService] Connection timeout to MQ broker mqprod01:1414",
                "_time": "2026-04-14T09:55:00.000+00:00",
                "host": "app-server-01",
                "source": "/var/log/payment-service/app.log",
                "sourcetype": "log4j",
            },
            {
                "_raw": "2026-04-14 09:55:05 WARN [PaymentService] Retry 1/3 for queue PAYMENT.REQUEST",
                "_time": "2026-04-14T09:55:05.000+00:00",
                "host": "app-server-01",
                "source": "/var/log/payment-service/app.log",
                "sourcetype": "log4j",
            },
            {
                "_raw": "2026-04-14 09:56:00 ERROR [PaymentService] All retries exhausted for PAYMENT.REQUEST",
                "_time": "2026-04-14T09:56:00.000+00:00",
                "host": "app-server-01",
                "source": "/var/log/payment-service/app.log",
                "sourcetype": "log4j",
            },
        ]
        evidence = f"Splunk search returned {len(results)} result(s):\n"
        for i, r in enumerate(results):
            evidence += f"  [{i+1}] {r['_raw']}\n"
        return AdapterResult(
            success=True,
            data={"result_count": len(results), "results": results},
            raw_output=json.dumps(results),
            evidence_snippet=evidence,
        )


class MockIR360Adapter(BaseAdapter):
    """Returns sample MQ queue status."""

    @property
    def adapter_name(self) -> str:
        return "MockIR360"

    async def health_check(self) -> bool:
        return True

    async def execute(self, parameters: Dict[str, Any]) -> AdapterResult:
        qm = parameters.get("queue_manager", "QMPROD01")
        queue = parameters.get("queue", "PAYMENT.REQUEST")
        action = parameters.get("action", "depth")

        data: Dict[str, Any] = {}
        if action == "depth":
            data = {
                "queue_manager": qm,
                "queue": queue,
                "current_depth": 1523,
                "max_depth": 5000,
                "oldest_message_age_seconds": 3642,
                "input_count": 45,
                "output_count": 0,
            }
            evidence = (
                f"MQ depth check | QM={qm} Queue={queue}\n"
                f"  Current depth: 1523 / 5000 (30.5%)\n"
                f"  Oldest message age: 3642s (~1h)\n"
                f"  Input: 45, Output: 0 (CONSUMERS STALLED)"
            )
        elif action == "status":
            data = {
                "queue_manager": qm,
                "queue": queue,
                "status": "RUNNING",
                "open_input_count": 2,
                "open_output_count": 0,
                "last_put_time": "2026-04-14T09:55:00Z",
                "last_get_time": "2026-04-14T08:30:00Z",
            }
            evidence = (
                f"MQ status | QM={qm} Queue={queue}\n"
                f"  Status: RUNNING\n"
                f"  Open inputs: 2, Open outputs: 0\n"
                f"  Last put: 09:55:00, Last get: 08:30:00 (STALE)"
            )
        else:
            data = {"queue_manager": qm, "queue": queue, "action": action}
            evidence = f"MQ {action} | QM={qm} Queue={queue} | OK"

        return AdapterResult(
            success=True,
            data=data,
            raw_output=json.dumps(data),
            evidence_snippet=evidence,
        )


class MockWindowsShareAdapter(BaseAdapter):
    """Returns sample log file content."""

    @property
    def adapter_name(self) -> str:
        return "MockWindowsShare"

    async def health_check(self) -> bool:
        return True

    async def execute(self, parameters: Dict[str, Any]) -> AdapterResult:
        unc_path = parameters.get("unc_path", "//fileserver/logs/app.log")
        pattern = parameters.get("pattern", "")
        lines = [
            "2026-04-14 09:50:00 INFO  Application started successfully",
            "2026-04-14 09:52:30 WARN  High memory usage detected: 85%",
            "2026-04-14 09:54:00 ERROR Connection refused to database server db-prod-01:5432",
            "2026-04-14 09:54:05 ERROR Retry 1/3 failed for db-prod-01:5432",
            "2026-04-14 09:54:15 ERROR Retry 2/3 failed for db-prod-01:5432",
            "2026-04-14 09:54:30 ERROR Retry 3/3 failed for db-prod-01:5432",
            "2026-04-14 09:54:31 FATAL Service degraded - database unavailable",
            "2026-04-14 09:55:00 INFO  Health check: DEGRADED",
        ]
        if pattern:
            import re as _re
            try:
                regex = _re.compile(pattern, _re.IGNORECASE)
                lines = [ln for ln in lines if regex.search(ln)]
            except _re.error:
                pass

        evidence = f"File: {unc_path}\nLines: {len(lines)}\n---\n" + "\n".join(lines[-10:])
        return AdapterResult(
            success=True,
            data={"line_count": len(lines), "path": unc_path},
            raw_output="\n".join(lines),
            evidence_snippet=evidence,
        )


class MockAutosysAdapter(BaseAdapter):
    """Returns sample Autosys job status."""

    @property
    def adapter_name(self) -> str:
        return "MockAutosys"

    async def health_check(self) -> bool:
        return True

    async def execute(self, parameters: Dict[str, Any]) -> AdapterResult:
        job_name = parameters.get("job_name", "BATCH_PAYMENT_PROCESS")
        query_type = parameters.get("query_type", "status")

        if query_type == "dependencies":
            data = {
                "jobs": [
                    {"job_name": job_name, "status": "SU", "condition": "ROOT"},
                    {"job_name": f"{job_name}_STEP1", "status": "SU", "condition": f"s({job_name})"},
                    {"job_name": f"{job_name}_STEP2", "status": "FA", "condition": f"s({job_name}_STEP1)"},
                ],
            }
            evidence = (
                f"Autosys dependencies for {job_name}:\n"
                f"  {job_name} -> SU (ROOT)\n"
                f"  {job_name}_STEP1 -> SU\n"
                f"  {job_name}_STEP2 -> FA (FAILED)"
            )
        else:
            data = {
                "jobs": [
                    {
                        "job_name": job_name,
                        "status": "FA",
                        "last_start": "2026-04-14 09:00:00",
                        "last_end": "2026-04-14 09:05:23",
                        "exit_code": "1",
                    },
                ],
            }
            evidence = (
                f"Autosys status for {job_name}:\n"
                f"  Status: FA (FAILURE)\n"
                f"  Last run: 09:00:00 - 09:05:23\n"
                f"  Exit code: 1"
            )

        return AdapterResult(
            success=True,
            data=data,
            raw_output=json.dumps(data),
            evidence_snippet=evidence,
        )
