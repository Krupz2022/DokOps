import base64
import hashlib
import logging
from cryptography.fernet import Fernet
from app.core.config import settings

_log = logging.getLogger(__name__)


def _fernet() -> Fernet:
    enc_key = settings.ENCRYPTION_KEY
    if enc_key:
        return Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
    _log.warning(
        "ENCRYPTION_KEY is not set — deriving encryption key from AUTH_SECRET_KEY (weaker). "
        "Generate a dedicated key: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )
    key_bytes = hashlib.sha256(settings.AUTH_SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Invalid or tampered ciphertext") from e
