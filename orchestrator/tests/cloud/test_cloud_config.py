"""cloud_config: cloud URL precedence (env > file > default), validation."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def opensail_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_URL", raising=False)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_default_when_no_override(opensail_home: Path) -> None:
    from app.config import get_settings
    from app.services import cloud_config

    expected = cloud_config.normalize_cloud_url(get_settings().tesslate_cloud_url)
    assert cloud_config.get_cloud_url() == expected


def test_file_override(opensail_home: Path) -> None:
    from app.services import cloud_config

    cloud_config.set_cloud_url("https://cloud.example.com")
    assert cloud_config.get_cloud_url() == "https://cloud.example.com"


def test_env_beats_file(opensail_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import cloud_config

    cloud_config.set_cloud_url("https://from-file.example.com")
    monkeypatch.setenv("TESSLATE_CLOUD_URL", "https://from-env.example.com")
    assert cloud_config.get_cloud_url() == "https://from-env.example.com"


def test_set_normalizes_trailing_slash_and_path(opensail_home: Path) -> None:
    from app.services import cloud_config

    stored = cloud_config.set_cloud_url("https://cloud.example.com/some/path/")
    assert stored == "https://cloud.example.com"
    assert cloud_config.get_cloud_url() == "https://cloud.example.com"


def test_invalid_scheme_rejected(opensail_home: Path) -> None:
    from app.services.cloud_config import InvalidCloudUrlError, set_cloud_url

    with pytest.raises(InvalidCloudUrlError):
        set_cloud_url("ftp://cloud.example.com")
    with pytest.raises(InvalidCloudUrlError):
        set_cloud_url("not-a-url")


def test_clear_reverts_to_default(opensail_home: Path) -> None:
    from app.config import get_settings
    from app.services import cloud_config

    cloud_config.set_cloud_url("https://cloud.example.com")
    cloud_config.clear_cloud_url()

    expected = cloud_config.normalize_cloud_url(get_settings().tesslate_cloud_url)
    assert cloud_config.get_cloud_url() == expected


def test_corrupt_override_falls_through(opensail_home: Path) -> None:
    from app.config import get_settings
    from app.services import cloud_config

    (opensail_home / "cache" / "cloud_url.json").write_text("{not json", encoding="utf-8")

    expected = cloud_config.normalize_cloud_url(get_settings().tesslate_cloud_url)
    assert cloud_config.get_cloud_url() == expected
