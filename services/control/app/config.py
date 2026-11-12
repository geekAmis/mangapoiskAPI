from __future__ import annotations

import re

from manga_common.config import Settings
from pydantic import Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from .ai_supervisor import SUPERVISOR_MODEL, SUPERVISOR_ROOT


class ControlSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "control"
    port: int = 8005
    control_database_url: str | None = None
    deploy_root: str = "/opt/mangapoisk-reborn"
    deploy_user: str = "mangapoisk"
    deploy_timeout_seconds: int = Field(default=3600, ge=60, le=86_400)
    deploy_health_timeout_seconds: int = Field(default=600, ge=30, le=7_200)
    deploy_health_poll_seconds: int = Field(default=2, ge=1, le=30)
    deploy_read_timeout_seconds: int = Field(default=900, ge=30, le=7_200)
    deploy_stale_job_seconds: int = Field(default=1_800, ge=60, le=86_400)
    deploy_pre_start_command: str = ""
    deploy_pre_start_timeout_seconds: int = Field(default=1_800, ge=30, le=86_400)

    # AI deploy supervisor.  It runs only after a full deploy and is optional:
    # a missing OpenCode binary or an unauthenticated free model is reported,
    # not treated as a deploy failure unless AI_SUPERVISOR_REQUIRED=true.
    ai_supervisor_enabled: bool = False
    ai_supervisor_model: str = SUPERVISOR_MODEL
    ai_supervisor_timeout_seconds: int = Field(default=900, ge=60, le=3_600)
    ai_supervisor_round_timeout_seconds: int = Field(default=420, ge=60, le=1_800)
    ai_supervisor_max_iterations: int = Field(default=2, ge=1, le=5)
    ai_supervisor_max_steps: int = Field(default=12, ge=4, le=40)
    ai_supervisor_opencode_bin: str = "opencode"
    ai_supervisor_install_opencode: bool = False
    ai_supervisor_full_deploy_only: bool = True
    ai_supervisor_skip_when_healthy: bool = False
    ai_supervisor_required: bool = False
    ai_supervisor_rollback: bool = True
    ai_supervisor_dry_run: bool = False

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"
    web_push_enabled: bool = False

    @field_validator("ai_supervisor_model")
    @classmethod
    def _free_model_only(cls, value: str) -> str:
        if value.strip() != SUPERVISOR_MODEL:
            raise ValueError(
                f"AI_SUPERVISOR_MODEL must be {SUPERVISOR_MODEL!r}; "
                "paid models are not allowed"
            )
        return SUPERVISOR_MODEL

    @field_validator("ai_supervisor_opencode_bin")
    @classmethod
    def _safe_opencode_bin(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not re.fullmatch(r"[A-Za-z0-9_./-]+", cleaned):
            raise ValueError("AI_SUPERVISOR_OPENCODE_BIN must be a simple executable path")
        return cleaned

    @model_validator(mode="after")
    def _supervisor_limits(self) -> ControlSettings:
        if self.ai_supervisor_round_timeout_seconds > self.ai_supervisor_timeout_seconds:
            raise ValueError(
                "AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS must not exceed "
                "AI_SUPERVISOR_TIMEOUT_SECONDS"
            )
        if (
            self.ai_supervisor_enabled
            and self.ai_supervisor_round_timeout_seconds >= self.deploy_stale_job_seconds
        ):
            raise ValueError(
                "AI_SUPERVISOR_ROUND_TIMEOUT_SECONDS must be less than "
                "DEPLOY_STALE_JOB_SECONDS so the stale-job reaper does not "
                "cancel a running supervisor round"
            )
        if self.environment == "production" and self.deploy_root.rstrip("/") != SUPERVISOR_ROOT:
            raise ValueError(
                f"production deploy root must be {SUPERVISOR_ROOT!r}; "
                "the AI supervisor is restricted to that tree"
            )
        return self

    @property
    def control_dsn(self) -> str:
        return self.control_database_url or self.database_url
