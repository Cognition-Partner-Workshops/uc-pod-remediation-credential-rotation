"""IR360 MQ adapter for queue manager checks.

IR360 provides visibility into IBM MQ queue managers.  This adapter
supports two modes:
  1. API mode  - calls the IR360 REST API (when base_url is configured)
  2. CLI mode  - wraps a local CLI binary (when use_cli=True)

Both modes implement the same BaseAdapter interface.  If the real
IR360 API details are unavailable, the adapter falls back to a
mock implementation with clear TODOs for production wiring.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from src.l1_agent.adapters.base import AdapterResult, BaseAdapter
from src.l1_agent.config.settings import IR360Settings
from src.l1_agent.utils.logging import get_logger
from src.l1_agent.utils.metrics import metrics

logger = get_logger("ir360_adapter")


class IR360Adapter(BaseAdapter):
    """MQ checks via IR360 API or CLI wrapper."""

    def __init__(self, settings: IR360Settings) -> None:
        self._settings = settings

    @property
    def adapter_name(self) -> str:
        return "IR360_MQ"

    async def health_check(self) -> bool:
        if self._settings.use_cli:
            return await self._cli_health()
        return await self._api_health()

    async def execute(self, parameters: Dict[str, Any]) -> AdapterResult:
        """Execute an MQ check.

        Parameters:
            queue_manager (str): Queue manager name
            queue (str): Queue name
            action (str): One of 'depth', 'browse', 'status'
        """
        action = parameters.get("action", "status")
        qm = parameters.get("queue_manager", "")
        queue = parameters.get("queue", "")

        if not qm:
            return AdapterResult(success=False, error="queue_manager is required")

        if self._settings.use_cli:
            return await self._execute_cli(action, qm, queue)
        return await self._execute_api(action, qm, queue)

    # ── API mode ──────────────────────────────────────────────────────

    async def _api_health(self) -> bool:
        """TODO: Implement real IR360 API health check."""
        import aiohttp

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self._settings.base_url}/api/v1/health"
                headers = {"X-API-Key": self._settings.api_key}
                async with session.get(url, headers=headers) as resp:
                    return resp.status == 200
        except Exception as exc:
            logger.warning("IR360 API health check failed: %s", exc)
            return False

    async def _execute_api(
        self, action: str, qm: str, queue: str
    ) -> AdapterResult:
        """TODO: Wire to real IR360 REST endpoints.

        Expected endpoints (placeholder):
          GET /api/v1/queuemanagers/{qm}/queues/{queue}/depth
          GET /api/v1/queuemanagers/{qm}/queues/{queue}/status
          GET /api/v1/queuemanagers/{qm}/queues/{queue}/browse?limit=5
        """
        import aiohttp

        base = self._settings.base_url.rstrip("/")
        headers = {
            "X-API-Key": self._settings.api_key,
            "Accept": "application/json",
        }
        endpoint = f"/api/v1/queuemanagers/{qm}"
        if queue:
            endpoint += f"/queues/{queue}"
        endpoint += f"/{action}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}{endpoint}", headers=headers
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    evidence = self._format_evidence(action, qm, queue, data)
                    metrics.increment("ir360.api_calls")
                    return AdapterResult(
                        success=True,
                        data=data,
                        raw_output=json.dumps(data),
                        evidence_snippet=evidence,
                    )
        except Exception as exc:
            metrics.increment("ir360.api_errors")
            return AdapterResult(success=False, error=str(exc))

    # ── CLI mode ──────────────────────────────────────────────────────

    async def _cli_health(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._settings.cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    async def _execute_cli(
        self, action: str, qm: str, queue: str
    ) -> AdapterResult:
        """Execute IR360 CLI command for MQ checks (read-only)."""
        cmd_args = [self._settings.cli_path, "--qm", qm]
        if queue:
            cmd_args.extend(["--queue", queue])
        cmd_args.append(f"--action={action}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")
                return AdapterResult(
                    success=False,
                    error=f"CLI exit {proc.returncode}: {err}",
                    raw_output=output,
                )
            metrics.increment("ir360.cli_calls")
            return AdapterResult(
                success=True,
                data={"stdout": output},
                raw_output=output,
                evidence_snippet=f"MQ {action} on {qm}/{queue}:\n{output[:300]}",
            )
        except Exception as exc:
            return AdapterResult(success=False, error=str(exc))

    @staticmethod
    def _format_evidence(
        action: str, qm: str, queue: str, data: dict
    ) -> str:
        return f"MQ {action} | QM={qm} Queue={queue} | Result: {json.dumps(data)[:300]}"
