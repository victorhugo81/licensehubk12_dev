"""Optional scheduled user import over FTP/FTPS. Pulls a single CSV file
from a configured FTP server and runs it through the same
validate_csv()/commit_import() pair used by the manual upload
(app/integrations/user_csv_import.py) - there is exactly one user-import
code path; FTP just supplies the file automatically instead of a human
uploading it.

Disabled unless a FtpImportSettings row exists with is_enabled=True and
every required field (host/username/password/remote_path) set - see
FtpImportSettings.is_configured() in app/models.py. Never call ftplib
directly from a route; go through sync() here.
"""
import ftplib
import io

from app.extensions import db
from app.integrations.base import IntegrationBase, IntegrationResult
from app.integrations.user_csv_import import commit_import, validate_csv
from app.models import FtpImportSettings, ImportHistory, utcnow

# Bounds memory use if remote_path unexpectedly points at something huge
# (misconfiguration, or a compromised/malicious FTP server) - retrbinary
# has no built-in size limit of its own.
MAX_FETCH_BYTES = 10 * 1024 * 1024


class _FetchTooLarge(Exception):
    pass


class FtpUsersIntegration(IntegrationBase):
    name = "FTP User Import"

    def __init__(self, settings: FtpImportSettings):
        super().__init__({})
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings and self.settings.is_configured())

    def _fetch_csv_bytes(self) -> bytes:
        ftp_cls = ftplib.FTP_TLS if self.settings.use_tls else ftplib.FTP
        ftp = ftp_cls(timeout=30)
        try:
            ftp.connect(self.settings.host, self.settings.port or 21)
            ftp.login(self.settings.username, self.settings.password)
            if self.settings.use_tls:
                ftp.prot_p()
            buf = io.BytesIO()
            total = 0

            def _write(chunk):
                nonlocal total
                total += len(chunk)
                if total > MAX_FETCH_BYTES:
                    raise _FetchTooLarge(f"remote file exceeds {MAX_FETCH_BYTES // (1024 * 1024)}MB limit")
                buf.write(chunk)

            ftp.retrbinary(f"RETR {self.settings.remote_path}", _write)
            return buf.getvalue()
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def sync(self) -> IntegrationResult:
        disabled = self.guard_disabled()
        if disabled:
            return disabled

        self.settings.last_run_at = utcnow()
        try:
            raw = self._fetch_csv_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
            preview = validate_csv(io.StringIO(text))

            if preview.column_errors:
                message = "; ".join(preview.column_errors)
                self.settings.last_status = "error"
                self.settings.last_message = message
                db.session.commit()
                return IntegrationResult(False, message)

            created, skipped, results = commit_import(preview)

            history = ImportHistory(
                kind="user", filename=self.settings.remote_path, status="completed",
                total_records=preview.total, valid_records=preview.valid,
                warning_records=preview.warnings, error_records=preview.errors,
            )
            history.details = {"created": created, "skipped": skipped, "results": results}
            db.session.add(history)

            message = f"{created} user(s) created, {skipped} skipped, {preview.errors} row(s) had errors."
            self.settings.last_status = "success"
            self.settings.last_message = message
            db.session.commit()
            return IntegrationResult(True, message, records_processed=created)

        except Exception as exc:
            db.session.rollback()
            self.settings.last_status = "error"
            self.settings.last_message = f"{type(exc).__name__}: {exc}"
            db.session.commit()
            return IntegrationResult(False, self.settings.last_message)
