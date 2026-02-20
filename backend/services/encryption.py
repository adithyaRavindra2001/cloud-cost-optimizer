import os
import json
from cryptography.fernet import Fernet

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not _ENCRYPTION_KEY:
    _ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(
        f"WARNING: No ENCRYPTION_KEY set. Generated ephemeral key: {_ENCRYPTION_KEY}\n"
        "Set ENCRYPTION_KEY in your .env to persist encrypted credentials across restarts."
    )

_fernet = Fernet(_ENCRYPTION_KEY.encode() if isinstance(_ENCRYPTION_KEY, str) else _ENCRYPTION_KEY)


def encrypt_credentials(data: dict) -> str:
    """Serialize dict to JSON, encrypt with Fernet, return base64 token string."""
    plaintext = json.dumps(data).encode()
    return _fernet.encrypt(plaintext).decode()


def decrypt_credentials(token: str) -> dict:
    """Decrypt a Fernet token string back to a dict."""
    plaintext = _fernet.decrypt(token.encode())
    return json.loads(plaintext)
