"""Remediation Orchestrator Agent — restarts or refreshes affected services upon approval."""

import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from src.config.settings import settings
from src.models.credential import (
    PodFailure,
    RemediationAction,
    RemediationStatus,
)
from src.utils.k8s_client import KubernetesClient

logger = logging.getLogger(__name__)


class RemediationOrchestrator:
    """Executes approved remediation actions against the Kubernetes cluster."""

    def __init__(
        self,
        k8s_client: Optional[KubernetesClient] = None,
    ) -> None:
        self.k8s = k8s_client or KubernetesClient()
        self.history: list[RemediationAction] = []

    def create_action(
        self,
        rotation_id: str,
        deployment: str,
        pod_failures: list[PodFailure],
        action_type: str = "rolling_restart",
    ) -> RemediationAction:
        """Build a remediation action for approval."""
        return RemediationAction(
            action_id=f"rem-{uuid4().hex[:8]}",
            rotation_id=rotation_id,
            pod_failures=pod_failures,
            deployment=deployment,
            namespace=settings.kubernetes.namespace,
            action_type=action_type,
        )

    def execute(self, action: RemediationAction) -> RemediationAction:
        """Execute an approved remediation action."""
        if action.status != RemediationStatus.APPROVED:
            logger.error(
                "Cannot execute action %s — status is %s, not APPROVED",
                action.action_id,
                action.status.value,
            )
            return action

        logger.info(
            "Executing %s on deployment %s (action=%s)",
            action.action_type,
            action.deployment,
            action.action_id,
        )

        success = False
        if action.action_type == "rolling_restart":
            success = self._rolling_restart(action)
        elif action.action_type == "pod_delete":
            success = self._delete_affected_pods(action)
        elif action.action_type == "secret_refresh":
            success = self._refresh_and_restart(action)
        else:
            logger.error("Unknown action type: %s", action.action_type)

        action.executed_at = datetime.utcnow()
        if success:
            action.status = RemediationStatus.COMPLETED
            action.result_message = (
                f"Successfully executed {action.action_type} "
                f"on {action.deployment}"
            )
            logger.info("Remediation completed: %s", action.result_message)
        else:
            action.status = RemediationStatus.FAILED
            action.result_message = (
                f"Failed to execute {action.action_type} "
                f"on {action.deployment}"
            )
            logger.error("Remediation failed: %s", action.result_message)

        self.history.append(action)
        return action

    def _rolling_restart(self, action: RemediationAction) -> bool:
        """Perform a rolling restart of the affected deployment."""
        return self.k8s.rolling_restart_deployment(action.deployment)

    def _delete_affected_pods(self, action: RemediationAction) -> bool:
        """Delete individual failing pods so the deployment recreates them."""
        all_ok = True
        for failure in action.pod_failures:
            if not self.k8s.delete_pod(failure.pod_name):
                all_ok = False
        return all_ok

    def _refresh_and_restart(self, action: RemediationAction) -> bool:
        """Trigger a rolling restart to pick up the refreshed secret."""
        return self.k8s.rolling_restart_deployment(action.deployment)

    def get_history(self) -> list[RemediationAction]:
        """Return the full remediation history for audit."""
        return list(self.history)
