from __future__ import annotations

import os

import pytest
from rag_api.migrations import MigrationConfigurationError, MigrationSettings

CLOUD_VARIABLES = ("INSTANCE_CONNECTION_NAME", "DB_NAME", "DB_USER")


def test_local_database_url_selects_local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://user:secret@localhost/db")
    for name in CLOUD_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    settings = MigrationSettings.from_environment()

    assert not settings.uses_cloud_sql
    assert "secret" not in repr(settings)


def test_complete_cloud_configuration_selects_cloud_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "project:region:instance")
    monkeypatch.setenv("DB_NAME", "support_rag")
    monkeypatch.setenv("DB_USER", "migration@project.iam")

    settings = MigrationSettings.from_environment()

    assert settings.uses_cloud_sql


@pytest.mark.parametrize("missing_name", CLOUD_VARIABLES)
def test_incomplete_cloud_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in CLOUD_VARIABLES:
        monkeypatch.setenv(name, f"value-for-{name.lower()}")
    monkeypatch.delenv(missing_name)

    with pytest.raises(MigrationConfigurationError, match="INSTANCE_CONNECTION_NAME"):
        MigrationSettings.from_environment()


def test_mixed_connection_modes_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://localhost/db")
    for name in CLOUD_VARIABLES:
        monkeypatch.setenv(name, f"value-for-{name.lower()}")

    with pytest.raises(MigrationConfigurationError, match="not both"):
        MigrationSettings.from_environment()


def test_environment_is_not_modified_by_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://localhost/db")
    for name in CLOUD_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    before = dict(os.environ)
    MigrationSettings.from_environment()

    assert dict(os.environ) == before
