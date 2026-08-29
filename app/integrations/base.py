"""Shared interface for external system integrations.

Every integration (Synergy, Clever, Canvas, a future SFTP/REST/SIS
connector, ...) subclasses IntegrationBase and implements `sync()`. Routes
and services talk only to this interface, never to a specific vendor's API
directly, so a new integration can be dropped in without touching core app
logic. Integrations are opt-in: `is_configured()` gates whether a given
integration does anything at all, and every integration must degrade to a
safe no-op when its config is absent.
"""
from abc import ABC, abstractmethod


class IntegrationResult:
    def __init__(self, success: bool, message: str = "", records_processed: int = 0, errors=None):
        self.success = success
        self.message = message
        self.records_processed = records_processed
        self.errors = errors or []

    def to_dict(self):
        return {
            "success": self.success,
            "message": self.message,
            "records_processed": self.records_processed,
            "errors": self.errors,
        }


class IntegrationBase(ABC):
    name = "base"

    def __init__(self, app_config: dict):
        self.config = app_config

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether required credentials/settings are present."""
        raise NotImplementedError

    @abstractmethod
    def sync(self) -> IntegrationResult:
        """Pull/push data with the external system. Must be a safe no-op
        (return an unsuccessful IntegrationResult) when not configured."""
        raise NotImplementedError

    def guard_disabled(self) -> IntegrationResult | None:
        if not self.is_configured():
            return IntegrationResult(False, f"{self.name} integration is not configured.")
        return None
