"""Tests for credential and service account models."""

from datetime import datetime, timedelta

from src.models.credential import (
    CredentialRotation,
    RotationStatus,
)
from src.models.service_account import ServiceAccount, ServiceAccountInventory


class TestCredentialRotation:
    def test_is_overdue_when_scheduled_in_past(self):
        rotation = CredentialRotation(
            rotation_id="rot-001",
            service_account="sa-test",
            secret_name="test-secret",
            namespace="production",
            scheduled_at=datetime.utcnow() - timedelta(hours=1),
            status=RotationStatus.SCHEDULED,
        )
        assert rotation.is_overdue is True

    def test_is_not_overdue_when_completed(self):
        rotation = CredentialRotation(
            rotation_id="rot-002",
            service_account="sa-test",
            secret_name="test-secret",
            namespace="production",
            scheduled_at=datetime.utcnow() - timedelta(hours=1),
            status=RotationStatus.COMPLETED,
            completed_at=datetime.utcnow(),
        )
        assert rotation.is_overdue is False

    def test_is_not_overdue_when_scheduled_in_future(self):
        rotation = CredentialRotation(
            rotation_id="rot-003",
            service_account="sa-test",
            secret_name="test-secret",
            namespace="production",
            scheduled_at=datetime.utcnow() + timedelta(hours=1),
            status=RotationStatus.SCHEDULED,
        )
        assert rotation.is_overdue is False


class TestServiceAccountInventory:
    def _make_inventory(self) -> ServiceAccountInventory:
        inventory = ServiceAccountInventory()
        inventory.accounts = [
            ServiceAccount(
                name="sa-payments",
                namespace="production",
                secret_names=["payment-db-creds", "payment-api-key"],
                linked_deployments=["payment-service"],
                rotation_schedule_cron="0 2 1 */3 *",
            ),
            ServiceAccount(
                name="sa-orders",
                namespace="production",
                secret_names=["order-db-creds"],
                linked_deployments=["order-service", "order-worker"],
                rotation_schedule_cron="0 2 1 */3 *",
            ),
            ServiceAccount(
                name="sa-staging",
                namespace="staging",
                secret_names=["staging-secret"],
                linked_deployments=["staging-app"],
                rotation_schedule_cron="0 0 * * *",
            ),
        ]
        return inventory

    def test_find_by_secret(self):
        inv = self._make_inventory()
        result = inv.find_by_secret("payment-db-creds")
        assert result is not None
        assert result.name == "sa-payments"

    def test_find_by_secret_not_found(self):
        inv = self._make_inventory()
        assert inv.find_by_secret("nonexistent") is None

    def test_find_by_deployment(self):
        inv = self._make_inventory()
        results = inv.find_by_deployment("order-service")
        assert len(results) == 1
        assert results[0].name == "sa-orders"

    def test_find_by_namespace(self):
        inv = self._make_inventory()
        results = inv.find_by_namespace("production")
        assert len(results) == 2
