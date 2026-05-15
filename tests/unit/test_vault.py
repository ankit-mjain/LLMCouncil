"""Vault adapter unit tests — age backend round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmcouncil.adapters.vault import AgeVault, KeyringVault, VaultError, build_vault


@pytest.fixture()
def age_vault(tmp_path: Path) -> AgeVault:
    id_path = tmp_path / "age.key"
    AgeVault.generate_identity(id_path)
    enc_path = tmp_path / "secrets.age"
    return AgeVault(encrypted_path=enc_path, identity_path=id_path)


def test_age_set_and_get(age_vault: AgeVault) -> None:
    age_vault.set("ANTHROPIC_API_KEY", "sk-ant-test-123")
    assert age_vault.get("ANTHROPIC_API_KEY") == "sk-ant-test-123"


def test_age_get_missing_returns_none(age_vault: AgeVault) -> None:
    assert age_vault.get("NONEXISTENT_KEY") is None


def test_age_require_raises_on_missing(age_vault: AgeVault) -> None:
    with pytest.raises(VaultError, match="not found"):
        age_vault.require("NONEXISTENT_KEY")


def test_age_delete(age_vault: AgeVault) -> None:
    age_vault.set("MY_KEY", "my-value")
    age_vault.delete("MY_KEY")
    assert age_vault.get("MY_KEY") is None


def test_age_multiple_secrets(age_vault: AgeVault) -> None:
    age_vault.set("KEY_A", "value-a")
    age_vault.set("KEY_B", "value-b")
    assert age_vault.get("KEY_A") == "value-a"
    assert age_vault.get("KEY_B") == "value-b"


def test_age_overwrite(age_vault: AgeVault) -> None:
    age_vault.set("KEY", "old")
    age_vault.set("KEY", "new")
    assert age_vault.get("KEY") == "new"


def test_build_vault_age(tmp_path: Path) -> None:
    id_path = tmp_path / "age.key"
    AgeVault.generate_identity(id_path)
    vault = build_vault("age", tmp_path, id_path)
    assert isinstance(vault, AgeVault)


def test_build_vault_unknown_raises() -> None:
    with pytest.raises(VaultError, match="Unknown vault backend"):
        build_vault("hashicorp", Path("/tmp"))


# ---------------------------------------------------------------------------
# Identity file permission checks (HIGH-002)
# ---------------------------------------------------------------------------

def test_load_identity_rejects_insecure_permissions(tmp_path: Path) -> None:
    id_path = tmp_path / "age.key"
    AgeVault.generate_identity(id_path)
    id_path.chmod(0o644)  # deliberately weaken permissions
    enc_path = tmp_path / "secrets.age"
    vault = AgeVault(encrypted_path=enc_path, identity_path=id_path)
    with pytest.raises(VaultError, match="insecure permissions"):
        vault.get("ANY_KEY")


def test_load_identity_accepts_correct_permissions(age_vault: AgeVault) -> None:
    age_vault.set("KEY", "value")
    assert age_vault.get("KEY") == "value"


def test_load_identity_raises_when_file_missing(tmp_path: Path) -> None:
    enc_path = tmp_path / "secrets.age"
    vault = AgeVault(encrypted_path=enc_path, identity_path=tmp_path / "missing.key")
    with pytest.raises(VaultError, match="not found"):
        vault.get("ANY_KEY")
