"""Incident processor: end-to-end orchestration from intake to resolution/escalation."""

from __future__ import annotations

from typing import List, Optional, Set

from src.l1_agent.clients.servicenow_client import ServiceNowClient
from src.l1_agent.engine.executor import SOPExecutor
from src.l1_agent.engine.sop_matcher import MatchResult, SOPMatcher
from src.l1_agent.engine.sop_parser import SOPParser
from src.l1_agent.models.evidence import ExecutionOutcome, ExecutionSummary
from src.l1_agent.models.incident import Incident
from src.l1_agent.models.sop import SOP
from src.l1_agent.utils.logging import get_logger, set_correlation_id
from src.l1_agent.utils.metrics import metrics

logger = get_logger("incident_processor")


class IncidentProcessor:
    """Orchestrates the full lifecycle of processing a single incident.

    1. Fetch/receive incident
    2. Match to SOP
    3. Execute SOP steps
    4. Update incident with results
    5. Escalate if needed
    """

    def __init__(
        self,
        snow_client: ServiceNowClient,
        sop_matcher: SOPMatcher,
        sop_parser: SOPParser,
        executor: SOPExecutor,
        sop_cache: Optional[List[SOP]] = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        self._snow = snow_client
        self._matcher = sop_matcher
        self._parser = sop_parser
        self._executor = executor
        self._sop_cache = sop_cache or []
        self._threshold = confidence_threshold
        self._processed_ids: Set[str] = set()

    async def process_incident(self, incident: Incident) -> ExecutionSummary:
        """Process a single incident end-to-end."""
        set_correlation_id(incident.number)

        # Idempotency check
        if incident.sys_id in self._processed_ids:
            logger.info("Incident %s already processed; skipping", incident.number)
            return ExecutionSummary(
                incident_number=incident.number,
                sop_id="",
                sop_title="",
                outcome=ExecutionOutcome.RESOLVED,
            )
        self._processed_ids.add(incident.sys_id)

        metrics.increment("incidents.received")
        logger.info("Processing incident %s: %s", incident.number, incident.short_description)

        # 1. Post initial work note
        await self._post_note(
            incident,
            f"[L1 Agent] Incident received. Searching for applicable SOP...\n"
            f"Category: {incident.category} | CI: {incident.cmdb_ci}",
        )

        # 2. Match SOP
        match_result = await self._match_sop(incident)

        if not match_result.sop:
            return await self._escalate_no_sop(incident, match_result)

        if match_result.confidence < self._threshold:
            return await self._escalate_low_confidence(incident, match_result)

        sop = match_result.sop
        await self._post_note(
            incident,
            f"[L1 Agent] SOP matched: {sop.title} (confidence: {match_result.confidence:.2f})\n"
            f"Rationale: {match_result.rationale}",
        )

        # 3. Set incident to In Progress
        await self._update_state(incident, state=2)

        # 4. Execute SOP
        summary = await self._executor.execute_sop(
            incident,
            sop,
            work_note_callback=self._snow.add_work_note,
        )

        # 5. Post conclusion
        await self._post_conclusion(incident, summary)

        return summary

    async def _match_sop(self, incident: Incident) -> MatchResult:
        """Match the incident to an SOP from the cache or ServiceNow."""
        if not self._sop_cache:
            await self._refresh_sop_cache()
        return self._matcher.match(incident, self._sop_cache)

    async def _refresh_sop_cache(self) -> None:
        """Reload SOPs from ServiceNow."""
        try:
            records = await self._snow.get_sops()
            self._sop_cache = []
            for record in records:
                sop = self._parser.parse_from_servicenow(record)
                if sop:
                    self._sop_cache.append(sop)
            logger.info("Loaded %d SOPs from ServiceNow", len(self._sop_cache))
        except Exception as exc:
            logger.error("Failed to refresh SOP cache: %s", exc)

    async def _escalate_no_sop(
        self, incident: Incident, match: MatchResult
    ) -> ExecutionSummary:
        """Escalate when no SOP is available."""
        note = (
            "[L1 Agent] ESCALATION: No applicable SOP found.\n"
            f"Reason: {match.rationale}\n"
            "Routing to L2 for manual investigation."
        )
        await self._post_note(incident, note)
        metrics.increment("incidents.escalated", labels={"reason": "no_sop"})
        return ExecutionSummary(
            incident_number=incident.number,
            sop_id="",
            sop_title="",
            outcome=ExecutionOutcome.ESCALATED,
            escalation_reason="No applicable SOP found",
        )

    async def _escalate_low_confidence(
        self, incident: Incident, match: MatchResult
    ) -> ExecutionSummary:
        """Escalate when SOP confidence is below threshold."""
        sop = match.sop
        sop_title = sop.title if sop else "N/A"
        sop_id = sop.sop_id if sop else ""
        note = (
            f"[L1 Agent] ESCALATION: Low confidence SOP match ({match.confidence:.2f}).\n"
            f"Best match: {sop_title}\n"
            f"Rationale: {match.rationale}\n"
            "Routing to L2 for confirmation."
        )
        await self._post_note(incident, note)
        metrics.increment("incidents.escalated", labels={"reason": "low_confidence"})
        return ExecutionSummary(
            incident_number=incident.number,
            sop_id=sop_id,
            sop_title=sop_title,
            outcome=ExecutionOutcome.ESCALATED,
            escalation_reason=f"Low confidence SOP match: {match.confidence:.2f}",
        )

    async def _post_conclusion(
        self, incident: Incident, summary: ExecutionSummary
    ) -> None:
        """Post the final work note and update incident state."""
        note = summary.to_work_note()
        await self._post_note(incident, note)

        if summary.outcome == ExecutionOutcome.RESOLVED:
            await self._update_state(incident, state=6)  # Resolved
            metrics.increment("incidents.resolved")
        elif summary.outcome == ExecutionOutcome.ESCALATED:
            escalation_packet = summary.to_escalation_packet()
            await self._post_note(
                incident,
                f"[L1 Agent] Escalation packet:\n{_format_escalation(escalation_packet)}",
            )
            metrics.increment("incidents.escalated", labels={"reason": "sop_execution"})
        else:
            metrics.increment("incidents.failed")

    async def _post_note(self, incident: Incident, note: str) -> None:
        """Post a work note to the incident; swallow errors."""
        try:
            await self._snow.add_work_note(incident.sys_id, note)
        except Exception as exc:
            logger.error("Failed to post work note for %s: %s", incident.number, exc)

    async def _update_state(self, incident: Incident, state: int) -> None:
        """Update incident state field."""
        try:
            await self._snow.update_incident(incident.sys_id, {"state": str(state)})
        except Exception as exc:
            logger.error("Failed to update state for %s: %s", incident.number, exc)


def _format_escalation(packet: dict) -> str:
    lines = [
        f"Incident: {packet.get('incident_number', '')}",
        f"SOP: {packet.get('sop_title', 'N/A')} ({packet.get('sop_id', '')})",
        f"Reason: {packet.get('escalation_reason', '')}",
        "",
        "Checks performed:",
    ]
    for check in packet.get("checks_performed", []):
        lines.append(
            f"  - {check.get('step_id', '?')} [{check.get('status', '?')}]: "
            f"{check.get('output_summary', '')}"
        )
    lines.append(f"\nRecommended: {packet.get('recommended_actions', '')}")
    return "\n".join(lines)
