"""Rotation Monitoring Agent — tracks scheduled credential rotations and impacted services."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import schedule

from src.config.settings import settings
from src.models.credential import CredentialRotation, RotationStatus
from src.models.service_account import ServiceAccount, ServiceAccountInventory
from src.utils.k8s_client import KubernetesClient

logger = logging.getLogger(__name__)


class RotationMonitorAgent:
    """Monitors credential rotation schedules and identifies affected services."""

    def __init__(
        self,
        inventory_path: str = "data/sample_inventory.json",
        k8s_client: Optional[KubernetesClient] = None,
    ) -> None:
        self.k8s = k8s_client or KubernetesClient()
        self.inventory = self._load_inventory(inventory_path)
        self.active_rotations: dict[str, CredentialRotation] = {}

    @staticmethod
    def _load_inventory(path: str) -> ServiceAccountInventory:
        """Load the service account inventory from a JSON file."""
        inventory = ServiceAccountInventory()
        file_path = Path(path)
        if not file_path.exists():
            logger.warning("Inventory file not found: %s", path)
            return inventory

        with open(file_path) as f:
            data = json.load(f)

        for entry in data.get("service_accounts", []):
            account = ServiceAccount(
                name=entry["name"],
                namespace=entry["namespace"],
                secret_names=entry["secret_names"],
                linked_deployments=entry["linked_deployments"],
                rotation_schedule_cron=entry["rotation_schedule_cron"],
                last_rotated_at=(
                    datetime.fromisoformat(entry["last_rotated_at"])
                    if entry.get("last_rotated_at")
                    else None
                ),
                owner_team=entry.get("owner_team", "platform-ops"),
                description=entry.get("description", ""),
            )
            inventory.accounts.append(account)

        logger.info(
            "Loaded %d service accounts from inventory",
            len(inventory.accounts),
        )
        return inventory

    def check_for_rotations(self) -> list[CredentialRotation]:
        """Detect secrets that have been recently rotated in the cluster."""
        detected: list[CredentialRotation] = []

        for account in self.inventory.accounts:
            for secret_name in account.secret_names:
                last_modified = self.k8s.get_secret_last_modified(secret_name)
                if last_modified is None:
                    continue

                if (
                    account.last_rotated_at is None
                    or last_modified > account.last_rotated_at
                ):
                    rotation = CredentialRotation(
                        rotation_id=f"rot-{secret_name}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                        service_account=account.name,
                        secret_name=secret_name,
                        namespace=account.namespace,
                        scheduled_at=last_modified,
                        completed_at=last_modified,
                        status=RotationStatus.COMPLETED,
                        affected_deployments=list(account.linked_deployments),
                    )
                    self.active_rotations[rotation.rotation_id] = rotation
                    detected.append(rotation)
                    account.last_rotated_at = last_modified

                    logger.info(
                        "Detected rotation for secret %s (account: %s, "
                        "affected deployments: %s)",
                        secret_name,
                        account.name,
                        rotation.affected_deployments,
                    )

        return detected

    def get_affected_deployments(
        self, rotation_id: str
    ) -> list[str]:
        """Return the list of deployments affected by a rotation."""
        rotation = self.active_rotations.get(rotation_id)
        if rotation is None:
            return []
        return rotation.affected_deployments

    def run(self) -> None:
        """Start the monitoring loop."""
        interval = settings.agent.rotation_check_interval
        logger.info(
            "Starting rotation monitor (interval=%ds, namespace=%s)",
            interval,
            settings.kubernetes.namespace,
        )
        schedule.every(interval).seconds.do(self.check_for_rotations)

        while True:
            schedule.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=settings.logging.level)
    agent = RotationMonitorAgent()
    agent.run()
