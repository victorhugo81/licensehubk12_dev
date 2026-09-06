from unittest.mock import MagicMock, patch

from app.integrations.ftp_users import MAX_FETCH_BYTES, FtpUsersIntegration
from app.models import FtpImportSettings


def _configured_settings(db):
    settings = FtpImportSettings.get_or_create()
    settings.is_enabled = True
    settings.host = "ftp.example.org"
    settings.username = "svc-user"
    settings.password = "secret"
    settings.remote_path = "/exports/users.csv"
    settings.use_tls = False  # keep the mock simple - plain ftplib.FTP, no TLS handshake
    db.session.commit()
    return settings


def test_ftp_sync_rejects_oversized_remote_file(app, db):
    with app.app_context():
        settings = _configured_settings(db)

        fake_ftp = MagicMock()

        def fake_retrbinary(cmd, callback):
            callback(b"a" * (MAX_FETCH_BYTES + 1))

        fake_ftp.retrbinary.side_effect = fake_retrbinary

        with patch("ftplib.FTP", return_value=fake_ftp):
            result = FtpUsersIntegration(settings).sync()

        assert result.success is False
        assert "exceeds" in result.message
        assert settings.last_status == "error"


def test_ftp_sync_creates_users_from_valid_remote_csv(app, db):
    with app.app_context():
        settings = _configured_settings(db)
        csv_bytes = b"first_name,last_name,email,role,school\nJane,Doe,jane@example.com,Viewer,\n"

        fake_ftp = MagicMock()

        def fake_retrbinary(cmd, callback):
            callback(csv_bytes)

        fake_ftp.retrbinary.side_effect = fake_retrbinary

        with patch("ftplib.FTP", return_value=fake_ftp):
            result = FtpUsersIntegration(settings).sync()

        assert result.success is True
        assert result.records_processed == 1
        assert settings.last_status == "success"

        from app.models import User
        assert User.query.filter_by(email="jane@example.com").first() is not None


def test_ftp_not_configured_is_a_safe_no_op(app, db):
    with app.app_context():
        settings = FtpImportSettings.get_or_create()  # is_enabled defaults False
        result = FtpUsersIntegration(settings).sync()
        assert result.success is False
