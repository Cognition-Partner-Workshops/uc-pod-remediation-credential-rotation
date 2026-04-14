"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _csv(val: str) -> List[str]:
    return [v.strip() for v in val.split(",") if v.strip()]


@dataclass(frozen=True)
class ServiceNowSettings:
    base_url: str = ""
    username: str = ""
    password: str = ""
    poll_interval_seconds: int = 30
    assignment_group: str = ""
    sop_table: str = "kb_knowledge"
    incident_table: str = "incident"


@dataclass(frozen=True)
class SplunkSettings:
    base_url: str = ""
    token: str = ""
    verify_ssl: bool = True
    search_timeout_seconds: int = 120


@dataclass(frozen=True)
class IR360Settings:
    base_url: str = ""
    api_key: str = ""
    cli_path: str = ""
    use_cli: bool = False


@dataclass(frozen=True)
class AutosysSettings:
    cli_path: str = "autorep"
    allowed_commands: tuple = ("autorep",)


@dataclass(frozen=True)
class WindowsShareSettings:
    allowed_unc_prefixes: List[str] = field(default_factory=list)
    smb_username: str = ""
    smb_password: str = ""
    smb_domain: str = ""


@dataclass(frozen=True)
class AgentSettings:
    sop_confidence_threshold: float = 0.6
    max_concurrent_incidents: int = 5
    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 1.0
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_seconds: int = 60
    demo_mode: bool = False
    log_level: str = "INFO"
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080


@dataclass(frozen=True)
class Settings:
    servicenow: ServiceNowSettings = field(default_factory=ServiceNowSettings)
    splunk: SplunkSettings = field(default_factory=SplunkSettings)
    ir360: IR360Settings = field(default_factory=IR360Settings)
    autosys: AutosysSettings = field(default_factory=AutosysSettings)
    windows_share: WindowsShareSettings = field(default_factory=WindowsShareSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            servicenow=ServiceNowSettings(
                base_url=os.getenv("SERVICENOW_BASE_URL", ""),
                username=os.getenv("SERVICENOW_USERNAME", ""),
                password=os.getenv("SERVICENOW_PASSWORD", ""),
                poll_interval_seconds=int(os.getenv("SERVICENOW_POLL_INTERVAL", "30")),
                assignment_group=os.getenv("SERVICENOW_ASSIGNMENT_GROUP", ""),
                sop_table=os.getenv("SERVICENOW_SOP_TABLE", "kb_knowledge"),
                incident_table=os.getenv("SERVICENOW_INCIDENT_TABLE", "incident"),
            ),
            splunk=SplunkSettings(
                base_url=os.getenv("SPLUNK_BASE_URL", ""),
                token=os.getenv("SPLUNK_TOKEN", ""),
                verify_ssl=os.getenv("SPLUNK_VERIFY_SSL", "true").lower() == "true",
                search_timeout_seconds=int(os.getenv("SPLUNK_SEARCH_TIMEOUT", "120")),
            ),
            ir360=IR360Settings(
                base_url=os.getenv("IR360_BASE_URL", ""),
                api_key=os.getenv("IR360_API_KEY", ""),
                cli_path=os.getenv("IR360_CLI_PATH", ""),
                use_cli=os.getenv("IR360_USE_CLI", "false").lower() == "true",
            ),
            autosys=AutosysSettings(
                cli_path=os.getenv("AUTOSYS_CLI_PATH", "autorep"),
                allowed_commands=tuple(
                    _csv(os.getenv("AUTOSYS_ALLOWED_COMMANDS", "autorep"))
                ),
            ),
            windows_share=WindowsShareSettings(
                allowed_unc_prefixes=_csv(
                    os.getenv("WINDOWS_SHARE_ALLOWED_PREFIXES", "")
                ),
                smb_username=os.getenv("SMB_USERNAME", ""),
                smb_password=os.getenv("SMB_PASSWORD", ""),
                smb_domain=os.getenv("SMB_DOMAIN", ""),
            ),
            agent=AgentSettings(
                sop_confidence_threshold=float(
                    os.getenv("AGENT_SOP_CONFIDENCE_THRESHOLD", "0.6")
                ),
                max_concurrent_incidents=int(
                    os.getenv("AGENT_MAX_CONCURRENT_INCIDENTS", "5")
                ),
                retry_max_attempts=int(os.getenv("AGENT_RETRY_MAX_ATTEMPTS", "3")),
                retry_base_delay_seconds=float(
                    os.getenv("AGENT_RETRY_BASE_DELAY", "1.0")
                ),
                circuit_breaker_failure_threshold=int(
                    os.getenv("AGENT_CB_FAILURE_THRESHOLD", "5")
                ),
                circuit_breaker_reset_seconds=int(
                    os.getenv("AGENT_CB_RESET_SECONDS", "60")
                ),
                demo_mode=os.getenv("AGENT_DEMO_MODE", "false").lower() == "true",
                log_level=os.getenv("AGENT_LOG_LEVEL", "INFO"),
                webhook_host=os.getenv("AGENT_WEBHOOK_HOST", "0.0.0.0"),
                webhook_port=int(os.getenv("AGENT_WEBHOOK_PORT", "8080")),
            ),
        )
