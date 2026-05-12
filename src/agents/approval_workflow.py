"""Approval Workflow Agent — initiates ServiceNow approval requests before remediation."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.config.settings import settings
from src.models.credential import RemediationAction, RemediationStatus
from src.utils.servicenow_client import ApprovalState, ServiceNowClient

logger = logging.getLogger(__name__)


class ApprovalWorkflowAgent:
    """Manages the approval lifecycle for remediation actions."""

    def __init__(
        self,
        snow_client: Optional[ServiceNowClient] = None,
    ) -> None:
        self.snow = snow_client or ServiceNowClient()
        self.pending_approvals: dict[str, RemediationAction] = {}

    async def request_approval(
        self,
        action: RemediationAction,
    ) -> RemediationAction:
        """Submit a remediation action for approval via ServiceNow."""
        affected_pods = ", ".join(f.pod_name for f in action.pod_failures)
        short_desc = (
            f"Credential rotation remediation: {action.action_type} "
            f"for {action.deployment}"
        )
        description = (
            f"Automated remediation request\n"
            f"Rotation ID: {action.rotation_id}\n"
            f"Deployment: {action.deployment}\n"
            f"Namespace: {action.namespace}\n"
            f"Action: {action.action_type}\n"
            f"Affected pods: {affected_pods}\n"
            f"Failure reasons: "
            + "; ".join(f.failure_reason for f in action.pod_failures)
        )

        approval = await self.snow.create_change_request(
            short_description=short_desc,
            description=description,
            affected_services=[action.deployment],
            urgency=2,
        )

        action.approval_ticket_id = approval.number
        action.status = RemediationStatus.PENDING
        self.pending_approvals[approval.sys_id] = action

        logger.info(
            "Approval requested: ticket=%s, deployment=%s, action=%s",
            approval.number,
            action.deployment,
            action.action_type,
        )
        return action

    async def poll_approval(
        self, sys_id: str
    ) -> RemediationStatus:
        """Poll a single approval and update the action status."""
        action = self.pending_approvals.get(sys_id)
        if action is None:
            return RemediationStatus.FAILED

        state = await self.snow.check_approval_status(sys_id)

        if state == ApprovalState.APPROVED:
            action.status = RemediationStatus.APPROVED
            logger.info(
                "Approval granted for %s (ticket=%s)",
                action.deployment,
                action.approval_ticket_id,
            )
        elif state == ApprovalState.REJECTED:
            action.status = RemediationStatus.REJECTED
            logger.warning(
                "Approval rejected for %s (ticket=%s)",
                action.deployment,
                action.approval_ticket_id,
            )

        return action.status

    async def wait_for_approval(
        self,
        sys_id: str,
        poll_interval: int = 30,
    ) -> RemediationStatus:
        """Block until an approval is granted, rejected, or times out."""
        timeout = timedelta(minutes=settings.agent.approval_timeout_minutes)
        deadline = datetime.utcnow() + timeout

        while datetime.utcnow() < deadline:
            status = await self.poll_approval(sys_id)
            if status in (
                RemediationStatus.APPROVED,
                RemediationStatus.REJECTED,
            ):
                return status
            await asyncio.sleep(poll_interval)

        action = self.pending_approvals.get(sys_id)
        if action:
            action.status = RemediationStatus.FAILED
            logger.error(
                "Approval timed out for %s (ticket=%s)",
                action.deployment,
                action.approval_ticket_id,
            )
        return RemediationStatus.FAILED
