"""ServiceNow API client for approval workflow integration."""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx

from src.config.settings import settings

logger = logging.getLogger(__name__)


class ApprovalState(Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """Represents a ServiceNow approval request."""

    sys_id: str
    number: str
    state: ApprovalState
    short_description: str
    requested_at: datetime
    resolved_at: Optional[datetime] = None
    approver: Optional[str] = None
    comments: Optional[str] = None


class ServiceNowClient:
    """Client for ServiceNow change request and approval APIs."""

    def __init__(self) -> None:
        self.base_url = settings.servicenow.url.rstrip("/")
        self.auth = (
            settings.servicenow.user,
            settings.servicenow.password,
        )
        self.assignment_group = settings.servicenow.assignment_group

    async def create_change_request(
        self,
        short_description: str,
        description: str,
        affected_services: list[str],
        urgency: int = 2,
    ) -> ApprovalRequest:
        """Create a change request in ServiceNow and return the approval details."""
        payload = {
            "short_description": short_description,
            "description": description,
            "type": "standard",
            "urgency": str(urgency),
            "assignment_group": self.assignment_group,
            "cmdb_ci_list": ",".join(affected_services),
            "state": "new",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/now/table/change_request",
                json=payload,
                auth=self.auth,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            result = response.json()["result"]

        logger.info(
            "Created change request %s for: %s",
            result["number"],
            short_description,
        )
        return ApprovalRequest(
            sys_id=result["sys_id"],
            number=result["number"],
            state=ApprovalState.REQUESTED,
            short_description=short_description,
            requested_at=datetime.utcnow(),
        )

    async def check_approval_status(
        self, sys_id: str
    ) -> ApprovalState:
        """Poll the approval status of a change request."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/now/table/change_request/{sys_id}",
                auth=self.auth,
                headers={"Accept": "application/json"},
                params={"sysparm_fields": "approval,state"},
            )
            response.raise_for_status()
            result = response.json()["result"]

        approval_value = result.get("approval", "requested")
        state_map = {
            "approved": ApprovalState.APPROVED,
            "rejected": ApprovalState.REJECTED,
            "requested": ApprovalState.REQUESTED,
        }
        return state_map.get(approval_value, ApprovalState.REQUESTED)

    async def add_work_note(self, sys_id: str, note: str) -> None:
        """Add a work note to a change request for audit trail."""
        payload = {"work_notes": note}
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}/api/now/table/change_request/{sys_id}",
                json=payload,
                auth=self.auth,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        logger.info("Added work note to %s", sys_id)

    async def close_change_request(
        self, sys_id: str, close_notes: str
    ) -> None:
        """Close a change request after remediation is complete."""
        payload = {
            "state": "closed",
            "close_notes": close_notes,
        }
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}/api/now/table/change_request/{sys_id}",
                json=payload,
                auth=self.auth,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        logger.info("Closed change request %s", sys_id)
