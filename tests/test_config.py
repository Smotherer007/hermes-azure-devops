"""Config resolution: defaults, overrides, the safety cascade and file handling."""

from __future__ import annotations

import json

import pytest

from conftest import sub, write_config


def _cfg():
    return sub("config")


def test_template_is_created_when_nothing_exists(isolated_config):
    assert not isolated_config.exists()
    cfg = _cfg()
    cfg.load_config()

    assert isolated_config.exists()
    data = json.loads(isolated_config.read_text())
    assert data["orgs"][0]["name"] == "my-org"
    assert data["safetyLevel"] == "confirm"
    # 0600: the file holds plaintext PATs.
    assert oct(isolated_config.stat().st_mode & 0o777) == "0o600"


def test_resolves_default_org_and_project(configure):
    configure()
    config = _cfg().resolve_config()

    assert config.project == "TestProject"
    assert config.org_name == "testorg"
    assert config.team == "Engineering"
    assert config.pat == "test-pat-12345"
    assert config.auth_method == "auto"
    assert config.default_work_item_type == "User Story"
    assert config.max_query_results == 100


def test_default_project_and_team_are_honoured(isolated_config, ado):
    write_config(
        isolated_config,
        {
            "orgs": [
                {
                    "name": "org1",
                    "url": ado.url,
                    "projects": [{"name": "First", "pat": "p1"}, {"name": "Second", "pat": "p2"}],
                }
            ],
            "defaultProject": "Second",
            "defaultTeam": "Platform",
            "authMethod": "pat",
            "defaultWorkItemType": "Bug",
            "maxQueryResults": 7,
            "mock": True,
        },
    )
    config = _cfg().resolve_config()

    assert config.project == "Second"
    assert config.pat == "p2"
    assert config.team == "Platform"
    assert config.auth_method == "pat"
    assert config.default_work_item_type == "Bug"
    assert config.max_query_results == 7
    assert config.mock is True


def test_missing_configuration_raises_with_details(isolated_config):
    write_config(isolated_config, {"orgs": []})
    with pytest.raises(sub("models").ConfigError) as error:
        _cfg().resolve_config()
    assert any("No orgs configured" in item for item in error.value.missing)


def test_missing_project_is_reported(isolated_config, ado):
    write_config(isolated_config, {"orgs": [{"name": "o", "url": ado.url, "projects": []}]})
    with pytest.raises(sub("models").ConfigError) as error:
        _cfg().resolve_config()
    assert any("No project configured" in item for item in error.value.missing)


def test_safety_level_cascades_project_over_org_over_global(isolated_config, ado):
    write_config(
        isolated_config,
        {
            "orgs": [
                {
                    "name": "o1",
                    "url": ado.url,
                    "safetyLevel": "confirm",
                    "projects": [
                        {"name": "P1", "pat": "p"},
                        {"name": "P2", "pat": "p", "safetyLevel": "readonly"},
                    ],
                }
            ],
            "defaultProject": "P1",
            "safetyLevel": "open",
        },
    )

    assert _cfg().resolve_config().safety_level == "confirm"  # org beats global

    config = _cfg()
    base = config.resolve_config()
    overridden = config.resolve_org_project_config(base, None, "P2")
    assert overridden.safety_level == "readonly"  # project beats org


def test_invalid_enum_values_fall_back_to_defaults(isolated_config, ado):
    write_config(
        isolated_config,
        {
            "orgs": [{"name": "o", "url": ado.url, "projects": [{"name": "P", "pat": "p"}]}],
            "authMethod": "nonsense",
            "safetyLevel": "nonsense",
        },
    )
    config = _cfg().resolve_config()
    assert config.auth_method == "auto"
    assert config.safety_level == "confirm"


def test_org_override_and_project_fallback(isolated_config, ado):
    write_config(
        isolated_config,
        {
            "orgs": [
                {"name": "a", "url": ado.url, "projects": [{"name": "PA", "pat": "pa"}]},
                {"name": "b", "url": f"{ado.url}/b", "projects": [{"name": "PB", "pat": "pb"}]},
            ]
        },
    )
    config = _cfg()
    base = config.resolve_config()

    switched = config.resolve_org_project_config(base, "b")
    assert switched.project == "PB"
    assert switched.pat == "pb"
    assert switched.org_url == f"{ado.url}/b"

    both = config.resolve_org_project_config(base, "b", "PB")
    assert both.project == "PB"


def test_unknown_org_and_project_raise(isolated_config, ado):
    write_config(
        isolated_config,
        {"orgs": [{"name": "a", "url": ado.url, "projects": [{"name": "PA", "pat": "p"}]}]},
    )
    config = _cfg()
    base = config.resolve_config()

    with pytest.raises(sub("models").ConfigError):
        config.resolve_org_project_config(base, "nope")

    with pytest.raises(sub("models").ConfigError):
        config.resolve_org_project_config(base, "a", "nope")


def test_resolve_all_org_configs_returns_every_pair(isolated_config, ado):
    write_config(
        isolated_config,
        {
            "orgs": [
                {
                    "name": "a",
                    "url": ado.url,
                    "projects": [{"name": "P1", "pat": "p"}, {"name": "P2", "pat": "p"}],
                },
                {"name": "broken", "url": "", "projects": [{"name": "PX", "pat": "p"}]},
                {"name": "empty", "url": ado.url, "projects": []},
            ]
        },
    )
    connections, errors = _cfg().resolve_all_org_configs()

    assert sorted(item.project for item in connections) == ["P1", "P2"]
    assert any("missing url" in item for item in errors)
    assert any("no projects configured" in item for item in errors)


def test_falls_back_to_the_pi_extension_config(isolated_config, tmp_path):
    """The pi file is read when the Hermes file is absent, and never written to."""
    pi_dir = tmp_path / "pi-agent"
    pi_dir.mkdir()
    pi_file = pi_dir / "pi-azure-devops.json"
    write_config(
        pi_file,
        {"orgs": [{"name": "piorg", "url": "https://dev.azure.com/piorg", "projects": [{"name": "PiProject", "pat": "pipat"}]}]},
    )

    cfg = _cfg()
    cfg.load_config()
    config = cfg.resolve_config()

    assert config.project == "PiProject"
    assert config.org_name == "piorg"
    assert cfg.using_pi_file() is True
    # The Hermes file was not created, so no secrets are duplicated on disk.
    assert not isolated_config.exists()


def test_environment_override_wins_for_the_path(monkeypatch, tmp_path, ado):
    explicit = tmp_path / "explicit.json"
    write_config(
        explicit,
        {"orgs": [{"name": "e", "url": ado.url, "projects": [{"name": "EP", "pat": "p"}]}]},
    )
    monkeypatch.setenv("AZURE_DEVOPS_CONFIG", str(explicit))

    cfg = _cfg()
    cfg.load_config()
    assert cfg.resolve_config().project == "EP"
    assert cfg.config_path() == explicit


def test_corrupt_config_file_does_not_crash(isolated_config):
    isolated_config.write_text("{not json", encoding="utf-8")
    cfg = _cfg()
    cfg.load_config()
    with pytest.raises(sub("models").ConfigError):
        cfg.resolve_config()


def test_try_resolve_returns_none_instead_of_raising(isolated_config):
    write_config(isolated_config, {"orgs": []})
    cfg = _cfg()
    cfg.load_config()
    assert cfg.try_resolve_config() is None
