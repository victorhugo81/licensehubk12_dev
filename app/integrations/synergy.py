"""Placeholder Synergy (SIS) integration.

Not implemented against a live Synergy tenant - this stubs the shape the
real integration would take (school/enrollment sync) so the rest of the app
can be built against a stable interface. Stays disabled until
SYNERGY_ENABLED / SYNERGY_BASE_URL / SYNERGY_API_KEY are set.
"""
from app.integrations.base import IntegrationBase, IntegrationResult


class SynergyIntegration(IntegrationBase):
    name = "Synergy"

    def is_configured(self) -> bool:
        return bool(
            self.config.get("SYNERGY_ENABLED")
            and self.config.get("SYNERGY_BASE_URL")
            and self.config.get("SYNERGY_API_KEY")
        )

    def sync(self) -> IntegrationResult:
        disabled = self.guard_disabled()
        if disabled:
            return disabled
        # Real implementation would call the Synergy API here to pull
        # school/enrollment data and reconcile it against app.models.School.
        return IntegrationResult(True, "Synergy sync is not yet implemented.", records_processed=0)
