"""Application settings loaded from environment variables."""

from dataclasses import dataclass, field
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class KubernetesConfig:
    namespace: str = os.getenv("K8S_NAMESPACE", "production")
    kubeconfig: str = os.getenv("K8S_KUBECONFIG", "~/.kube/config")


@dataclass(frozen=True)
class ServiceNowConfig:
    url: str = os.getenv("SERVICENOW_URL", "https://instance.service-now.com")
    user: str = os.getenv("SERVICENOW_USER", "api_user")
    password: str = os.getenv("SERVICENOW_PASSWORD", "")
    assignment_group: str = os.getenv(
        "SERVICENOW_ASSIGNMENT_GROUP", "L3-Platform-Ops"
    )


@dataclass(frozen=True)
class AgentConfig:
    rotation_check_interval: int = int(
        os.getenv("ROTATION_CHECK_INTERVAL", "60")
    )
    failure_check_interval: int = int(
        os.getenv("FAILURE_CHECK_INTERVAL", "30")
    )
    max_restart_attempts: int = int(os.getenv("MAX_RESTART_ATTEMPTS", "3"))
    approval_timeout_minutes: int = int(
        os.getenv("APPROVAL_TIMEOUT_MINUTES", "30")
    )


@dataclass(frozen=True)
class LoggingConfig:
    level: str = os.getenv("LOG_LEVEL", "INFO")
    audit_log_path: str = os.getenv("AUDIT_LOG_PATH", "./logs/audit.log")


@dataclass(frozen=True)
class Settings:
    kubernetes: KubernetesConfig = field(default_factory=KubernetesConfig)
    servicenow: ServiceNowConfig = field(default_factory=ServiceNowConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


settings = Settings()
