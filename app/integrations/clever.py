"""Placeholder Clever integration (rostering / SSO).

Stubs the interface for syncing schools and student software assignments
from Clever. Stays disabled until CLEVER_ENABLED, CLEVER_CLIENT_ID and
CLEVER_CLIENT_SECRET are configured.
"""
from app.integrations.base import IntegrationBase, IntegrationResult


class CleverIntegration(IntegrationBase):
    name = "Clever"

    def is_configured(self) -> bool:
        return bool(
            self.config.get("CLEVER_ENABLED")
            and self.config.get("CLEVER_CLIENT_ID")
            and self.config.get("CLEVER_CLIENT_SECRET")
        )

    def sync(self) -> IntegrationResult:
        disabled = self.guard_disabled()
        if disabled:
            return disabled
        return IntegrationResult(True, "Clever sync is not yet implemented.", records_processed=0)
