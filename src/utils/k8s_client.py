"""Kubernetes API client wrapper for pod and secret management."""

import logging
from datetime import datetime
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from src.config.settings import settings

logger = logging.getLogger(__name__)


class KubernetesClient:
    """Wraps the Kubernetes Python client for credential-rotation operations."""

    def __init__(self, namespace: Optional[str] = None) -> None:
        self.namespace = namespace or settings.kubernetes.namespace
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config(
                config_file=settings.kubernetes.kubeconfig
            )
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def list_pods(
        self,
        label_selector: Optional[str] = None,
    ) -> list[client.V1Pod]:
        """List pods in the configured namespace."""
        try:
            resp = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector or "",
            )
            return resp.items
        except ApiException as e:
            logger.error("Failed to list pods: %s", e)
            raise

    def get_pod_logs(
        self,
        pod_name: str,
        tail_lines: int = 100,
    ) -> str:
        """Retrieve recent logs for a specific pod."""
        try:
            return self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                tail_lines=tail_lines,
            )
        except ApiException as e:
            logger.error("Failed to get logs for pod %s: %s", pod_name, e)
            raise

    def get_secret(self, secret_name: str) -> Optional[client.V1Secret]:
        """Retrieve a Kubernetes secret by name."""
        try:
            return self.core_v1.read_namespaced_secret(
                name=secret_name,
                namespace=self.namespace,
            )
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error("Failed to get secret %s: %s", secret_name, e)
            raise

    def get_secret_last_modified(
        self, secret_name: str
    ) -> Optional[datetime]:
        """Get the last-modified timestamp of a secret."""
        secret = self.get_secret(secret_name)
        if secret and secret.metadata:
            return secret.metadata.creation_timestamp
        return None

    def rolling_restart_deployment(self, deployment_name: str) -> bool:
        """Trigger a rolling restart of a deployment by patching the template annotation."""
        try:
            now = datetime.utcnow().isoformat()
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": now
                            }
                        }
                    }
                }
            }
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
                body=body,
            )
            logger.info(
                "Rolling restart triggered for deployment %s",
                deployment_name,
            )
            return True
        except ApiException as e:
            logger.error(
                "Failed to restart deployment %s: %s", deployment_name, e
            )
            return False

    def delete_pod(self, pod_name: str) -> bool:
        """Delete a specific pod to force recreation."""
        try:
            self.core_v1.delete_namespaced_pod(
                name=pod_name,
                namespace=self.namespace,
            )
            logger.info("Deleted pod %s", pod_name)
            return True
        except ApiException as e:
            logger.error("Failed to delete pod %s: %s", pod_name, e)
            return False

    def get_deployment(
        self, deployment_name: str
    ) -> Optional[client.V1Deployment]:
        """Retrieve a deployment by name."""
        try:
            return self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
            )
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(
                "Failed to get deployment %s: %s", deployment_name, e
            )
            raise

    def list_deployments_using_secret(
        self, secret_name: str
    ) -> list[str]:
        """Find all deployments that reference a given secret."""
        deployments = []
        try:
            resp = self.apps_v1.list_namespaced_deployment(
                namespace=self.namespace
            )
            for dep in resp.items:
                if self._deployment_uses_secret(dep, secret_name):
                    deployments.append(dep.metadata.name)
        except ApiException as e:
            logger.error("Failed to list deployments: %s", e)
            raise
        return deployments

    @staticmethod
    def _deployment_uses_secret(
        deployment: client.V1Deployment, secret_name: str
    ) -> bool:
        """Check if a deployment references a specific secret."""
        spec = deployment.spec
        if not spec or not spec.template or not spec.template.spec:
            return False

        pod_spec = spec.template.spec

        # Check environment variables from secrets
        for container in pod_spec.containers or []:
            for env in container.env or []:
                if (
                    env.value_from
                    and env.value_from.secret_key_ref
                    and env.value_from.secret_key_ref.name == secret_name
                ):
                    return True
            for env_from in container.env_from or []:
                if (
                    env_from.secret_ref
                    and env_from.secret_ref.name == secret_name
                ):
                    return True

        # Check volume mounts from secrets
        for volume in pod_spec.volumes or []:
            if volume.secret and volume.secret.secret_name == secret_name:
                return True

        return False
