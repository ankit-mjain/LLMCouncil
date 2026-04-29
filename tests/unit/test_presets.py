"""Preset definitions and config pre-filling tests."""

from __future__ import annotations

from llmcouncil.presets import KNOWN_PROVIDERS, PRESETS


def test_all_presets_defined() -> None:
    for name in ["free", "cheap", "balanced", "premium", "custom"]:
        assert name in PRESETS


def test_cheap_preset_seats() -> None:
    p = PRESETS["cheap"]
    roles = [s.role for s in p.seats]
    assert "proposer" in roles
    assert "critic" in roles
    assert "judge" in roles
    providers = {s.provider for s in p.seats}
    assert len(providers) == 3  # 3 distinct lineages


def test_custom_preset_has_no_seats() -> None:
    assert PRESETS["custom"].seats == []
    assert PRESETS["custom"].required_providers == []


def test_all_non_custom_presets_have_3_seats() -> None:
    for name, p in PRESETS.items():
        if name == "custom":
            continue
        assert len(p.seats) == 3, f"Preset '{name}' should have 3 seats"


def test_known_providers_have_required_fields() -> None:
    for name, info in KNOWN_PROVIDERS.items():
        assert "label" in info, f"{name} missing 'label'"
        assert "models" in info, f"{name} missing 'models'"
        assert isinstance(info["models"], list), f"{name} models should be a list"
        assert len(info["models"]) >= 1, f"{name} must have at least one model"
