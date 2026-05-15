"""Vault adapter — age-encrypted file (default) or OS keyring (opt-in).

age backend: all secrets stored as key=value lines inside a single
age-encrypted file at identity_file path. Entire file is re-encrypted on
every write (small number of secrets, acceptable overhead).

keyring backend: each secret stored under service="llmcouncil", username=key.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path


class VaultError(Exception):
    pass


class BaseVault(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def require(self, key: str) -> str:
        v = self.get(key)
        if v is None:
            raise VaultError(f"Secret '{key}' not found in vault.")
        return v


# ---------------------------------------------------------------------------
# age backend
# ---------------------------------------------------------------------------

class AgeVault(BaseVault):
    """Secrets stored in a single age-encrypted JSON file."""

    def __init__(self, encrypted_path: Path, identity_path: Path) -> None:
        self._enc_path = encrypted_path.expanduser()
        self._id_path = identity_path.expanduser()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_identity(self) -> None:
        """Verify the identity file exists and has mode 0600 before any vault operation."""
        if not self._id_path.exists():
            raise VaultError(f"Identity file not found: {self._id_path}")
        mode = self._id_path.stat().st_mode & 0o777
        if mode != 0o600:
            raise VaultError(
                f"Identity file {self._id_path} has insecure permissions {oct(mode)}. "
                "Expected 0o600. Fix with: chmod 600 " + str(self._id_path)
            )

    def _load_identity(self) -> object:
        try:
            import pyrage
        except ImportError as exc:
            raise VaultError("pyrage is not installed. Run: uv pip install pyrage") from exc
        self._check_identity()
        pem = self._id_path.read_text().strip()
        return pyrage.x25519.Identity.from_str(pem)

    def _decrypt(self) -> dict[str, str]:
        self._check_identity()
        if not self._enc_path.exists():
            return {}
        try:
            import pyrage
        except ImportError as exc:
            raise VaultError("pyrage is not installed. Run: uv pip install pyrage") from exc
        ciphertext = self._enc_path.read_bytes()
        identity = self._load_identity()
        plaintext = pyrage.decrypt(ciphertext, [identity])
        return json.loads(plaintext.decode())

    def _encrypt(self, data: dict[str, str]) -> None:
        try:
            import pyrage
        except ImportError as exc:
            raise VaultError("pyrage is not installed. Run: uv pip install pyrage") from exc
        identity = self._load_identity()
        recipient = identity.to_public()
        plaintext = json.dumps(data).encode()
        ciphertext = pyrage.encrypt(plaintext, [recipient])
        self._enc_path.parent.mkdir(parents=True, exist_ok=True)
        self._enc_path.write_bytes(ciphertext)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        return self._decrypt().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._decrypt()
        data[key] = value
        self._encrypt(data)

    def delete(self, key: str) -> None:
        data = self._decrypt()
        data.pop(key, None)
        self._encrypt(data)

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    @classmethod
    def generate_identity(cls, identity_path: Path) -> str:
        """Generate a new age X25519 identity. Returns the public key string."""
        try:
            import pyrage
        except ImportError as exc:
            raise VaultError("pyrage is not installed. Run: uv pip install pyrage") from exc
        identity_path = identity_path.expanduser()
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        identity = pyrage.x25519.Identity.generate()
        # pyrage Identity.__str__ emits the AGE-SECRET-KEY-... PEM line
        identity_path.write_text(str(identity) + "\n")
        identity_path.chmod(0o600)
        return str(identity.to_public())


# ---------------------------------------------------------------------------
# keyring backend
# ---------------------------------------------------------------------------

class KeyringVault(BaseVault):
    _SERVICE = "llmcouncil"

    def get(self, key: str) -> str | None:
        try:
            import keyring
        except ImportError as exc:
            raise VaultError("keyring is not installed. Run: uv pip install keyring") from exc
        return keyring.get_password(self._SERVICE, key)

    def set(self, key: str, value: str) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise VaultError("keyring is not installed.") from exc
        keyring.set_password(self._SERVICE, key, value)

    def delete(self, key: str) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise VaultError("keyring is not installed.") from exc
        keyring.delete_password(self._SERVICE, key)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_vault(backend: str, config_dir: Path, identity_file: Path | None = None) -> BaseVault:
    if backend == "age":
        id_file = identity_file or (config_dir / "age.key")
        enc_file = config_dir / "secrets.age"
        return AgeVault(encrypted_path=enc_file, identity_path=id_file)
    if backend == "keyring":
        return KeyringVault()
    raise VaultError(f"Unknown vault backend: {backend!r}")
