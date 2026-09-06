"""Symmetric encryption for secrets stored at rest (e.g. the FTP password
on FtpImportSettings). Never store a credential in plaintext in the
database - encrypt with encrypt_value() before saving, decrypt_value()
when the raw secret is actually needed (e.g. to open an FTP connection).

The Fernet key is derived from the app's SECRET_KEY rather than a separate
secret, so there's nothing extra to provision - but it also means rotating
SECRET_KEY invalidates every stored encrypted value.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet() -> Fernet:
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""
