"""Models for credential rotation tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RotationStatus(Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RemediationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CredentialRotation:
    """Represents a single credential rotation event."""

    rotation_id: str
    service_account: str
    secret_name: str
    namespace: str
    scheduled_at: datetime
    completed_at: Optional[datetime] = None
    status: RotationStatus = RotationStatus.SCHEDULED
    affected_deployments: list[str] = field(default_factory=list)

    @property
    def is_overdue(self) -> bool:
        if self.status == RotationStatus.COMPLETED:
            return False
        return datetime.utcnow() > self.scheduled_at


@dataclass
class PodFailure:
    """Represents a pod failure linked to stale credentials."""

    pod_name: str
    namespace: str
    deployment: str
    failure_reason: str
    detected_at: datetime
    related_rotation_id: Optional[str] = None
    stale_secret_name: Optional[str] = None
    container_restart_count: int = 0


@dataclass
class RemediationAction:
    """Represents a remediation action to be taken."""

    action_id: str
    rotation_id: str
    pod_failures: list[PodFailure]
    deployment: str
    namespace: str
    action_type: str  # "rolling_restart" | "secret_refresh" | "pod_delete"
    status: RemediationStatus = RemediationStatus.PENDING
    approval_ticket_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    result_message: Optional[str] = None
