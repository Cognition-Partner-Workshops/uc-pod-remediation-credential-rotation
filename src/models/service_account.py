"""Models for service account inventory management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ServiceAccount:
    """Represents a Kubernetes service account and its credential metadata."""

    name: str
    namespace: str
    secret_names: list[str]
    linked_deployments: list[str]
    rotation_schedule_cron: str
    last_rotated_at: Optional[datetime] = None
    owner_team: str = "platform-ops"
    description: str = ""

    @property
    def rotation_schedule_display(self) -> str:
        return f"cron({self.rotation_schedule_cron})"


@dataclass
class ServiceAccountInventory:
    """Centralized inventory of all managed service accounts."""

    accounts: list[ServiceAccount] = field(default_factory=list)

    def find_by_secret(self, secret_name: str) -> Optional[ServiceAccount]:
        for account in self.accounts:
            if secret_name in account.secret_names:
                return account
        return None

    def find_by_deployment(
        self, deployment_name: str
    ) -> list[ServiceAccount]:
        return [
            account
            for account in self.accounts
            if deployment_name in account.linked_deployments
        ]

    def find_by_namespace(self, namespace: str) -> list[ServiceAccount]:
        return [
            account
            for account in self.accounts
            if account.namespace == namespace
        ]
