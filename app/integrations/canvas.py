"""Placeholder Canvas LMS integration.

Stubs the interface for syncing Canvas course/license usage data. Stays
disabled until CANVAS_ENABLED, CANVAS_BASE_URL and CANVAS_API_TOKEN are
configured.
"""
from app.integrations.base import IntegrationBase, IntegrationResult


class CanvasIntegration(IntegrationBase):
    name = "Canvas"

    def is_configured(self) -> bool:
        return bool(
            self.config.get("CANVAS_ENABLED")
            and self.config.get("CANVAS_BASE_URL")
            and self.config.get("CANVAS_API_TOKEN")
        )

    def sync(self) -> IntegrationResult:
        disabled = self.guard_disabled()
        if disabled:
            return disabled
        return IntegrationResult(True, "Canvas sync is not yet implemented.", records_processed=0)
