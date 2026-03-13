"""Failure Detection Agent — identifies pods running with outdated credentials."""

import logging
import re
from datetime import datetime
from typing import Optional

import schedule

from src.config.settings import settings
from src.models.credential import PodFailure
from src.utils.k8s_client import KubernetesClient

logger = logging.getLogger(__name__)

# Log patterns that indicate stale-credential failures
CREDENTIAL_FAILURE_PATTERNS = [
    re.compile(r"authentication\s+fail", re.IGNORECASE),
    re.compile(r"access\s+denied", re.IGNORECASE),
    re.compile(r"invalid\s+(credentials?|password|token)", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"401\s+Unauthorized", re.IGNORECASE),
    re.compile(r"login\s+fail", re.IGNORECASE),
    re.compile(r"SQLSTATE.*password\s+authentication\s+failed", re.IGNORECASE),
    re.compile(r"connection\s+refused.*auth", re.IGNORECASE),
]


class FailureDetectionAgent:
    """Scans pods for credential-related failures after rotations."""

    def __init__(
        self,
        k8s_client: Optional[KubernetesClient] = None,
        rotated_secrets: Optional[dict[str, datetime]] = None,
    ) -> None:
        self.k8s = k8s_client or KubernetesClient()
        self.rotated_secrets = rotated_secrets or {}
        self.detected_failures: list[PodFailure] = []

    def scan_pods(self) -> list[PodFailure]:
        """Scan all pods in the namespace for credential-related failures."""
        failures: list[PodFailure] = []
        pods = self.k8s.list_pods()

        for pod in pods:
            pod_name = pod.metadata.name
            pod_status = pod.status

            if not self._is_pod_failing(pod_status):
                continue

            logs = self._safe_get_logs(pod_name)
            failure_reason = self._detect_credential_failure(logs)
            if failure_reason is None:
                continue

            deployment_name = self._extract_deployment_name(pod)
            restart_count = self._get_restart_count(pod_status)

            failure = PodFailure(
                pod_name=pod_name,
                namespace=settings.kubernetes.namespace,
                deployment=deployment_name,
                failure_reason=failure_reason,
                detected_at=datetime.utcnow(),
                container_restart_count=restart_count,
                stale_secret_name=self._find_stale_secret(pod),
            )
            failures.append(failure)
            logger.warning(
                "Credential failure detected in pod %s: %s (restarts: %d)",
                pod_name,
                failure_reason,
                restart_count,
            )

        self.detected_failures.extend(failures)
        return failures

    @staticmethod
    def _is_pod_failing(pod_status) -> bool:
        """Check if a pod is in a failing state (CrashLoopBackOff or Error)."""
        if pod_status is None or pod_status.container_statuses is None:
            return False

        for cs in pod_status.container_statuses:
            if cs.state and cs.state.waiting:
                reason = cs.state.waiting.reason or ""
                if reason in ("CrashLoopBackOff", "Error", "RunContainerError"):
                    return True
            if cs.restart_count and cs.restart_count > 2:
                return True
        return False

    @staticmethod
    def _get_restart_count(pod_status) -> int:
        """Sum the restart counts across all containers."""
        if pod_status is None or pod_status.container_statuses is None:
            return 0
        return sum(
            cs.restart_count or 0 for cs in pod_status.container_statuses
        )

    @staticmethod
    def _detect_credential_failure(logs: str) -> Optional[str]:
        """Search pod logs for credential-failure patterns."""
        for pattern in CREDENTIAL_FAILURE_PATTERNS:
            match = pattern.search(logs)
            if match:
                return match.group(0)
        return None

    def _safe_get_logs(self, pod_name: str) -> str:
        """Retrieve pod logs, returning empty string on error."""
        try:
            return self.k8s.get_pod_logs(pod_name, tail_lines=200)
        except Exception:
            logger.debug("Could not retrieve logs for pod %s", pod_name)
            return ""

    @staticmethod
    def _extract_deployment_name(pod) -> str:
        """Extract the owning deployment name from pod metadata."""
        labels = pod.metadata.labels or {}
        return labels.get("app", labels.get("app.kubernetes.io/name", "unknown"))

    def _find_stale_secret(self, pod) -> Optional[str]:
        """Identify which secret mounted in the pod may be stale."""
        if not pod.spec or not pod.spec.volumes:
            return None

        for volume in pod.spec.volumes:
            if volume.secret and volume.secret.secret_name in self.rotated_secrets:
                return volume.secret.secret_name
        return None

    def run(self) -> None:
        """Start the failure detection loop."""
        interval = settings.agent.failure_check_interval
        logger.info(
            "Starting failure detector (interval=%ds)", interval
        )
        schedule.every(interval).seconds.do(self.scan_pods)

        while True:
            schedule.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=settings.logging.level)
    agent = FailureDetectionAgent()
    agent.run()
