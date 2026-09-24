"""The registration contract with Hermes, and internal consistency."""

from __future__ import annotations

import re

from conftest import ROOT, plugin, sub, tool_names

tools = sub("tools")


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_registers_every_tool_in_one_toolset(registered):
    assert len(registered.tools) == 54
    assert set(registered.tools) == set(tool_names())
    assert {entry["toolset"] for entry in registered.tools.values()} == {"azure-devops"}


def test_registers_the_safety_hook(registered):
    assert "pre_tool_call" in registered.hooks
    assert callable(registered.hooks["pre_tool_call"])


def test_registers_the_status_and_doctor_commands(registered):
    assert "azure-devops-status" in registered.commands
    assert "azure-devops-doctor" in registered.commands


def test_registers_a_command_per_prompt_template(registered):
    template_commands = {name for name in registered.commands if name.startswith("azure-devops-")}
    # 14 prompt templates minus the doctor one, which the dedicated handler owns,
    # plus the dedicated status and doctor commands.
    assert len(template_commands) == 15
    assert "azure-devops-pr-review" in registered.commands
    assert "azure-devops-triage" in registered.commands
    assert "azure-devops-sprint-health" in registered.commands
    # The doctor command is the dedicated one, not the template fallback.
    assert registered.commands["azure-devops-doctor"]["description"] == (
        "Check Azure DevOps configuration, authentication and connection health"
    )


def test_registers_the_bundled_skill(registered):
    assert "azure-devops-workitems" in registered.skills
    entry = registered.skills["azure-devops-workitems"]
    assert entry["path"].name == "SKILL.md"
    assert entry["path"].exists()
    assert entry["description"], "the frontmatter description is used for skills_list"


def test_registers_the_system_prompt_section(registered):
    assert "azure-devops.overview" in registered.sections


def test_prompt_section_lists_connections_without_secrets(configure):
    configure()
    section = plugin._prompt_section({})

    assert "azure_devops_*" in section
    assert "testorg/TestProject" in section
    assert "safety: confirm" in section
    # Never the credential itself.
    assert "test-pat-12345" not in section


def test_prompt_section_says_what_to_do_when_unconfigured(isolated_config):
    sub("config").load_config()
    section = plugin._prompt_section({})
    assert "No Azure DevOps connection is configured" in section
    assert str(isolated_config) in section


def test_prompt_section_survives_a_broken_config(isolated_config):
    isolated_config.write_text("{ not json", encoding="utf-8")
    section = plugin._prompt_section({})
    assert "azure_devops_*" in section


def test_registration_works_when_the_optional_api_is_missing(isolated_config):
    """Older Hermes builds have no register_system_prompt_section."""

    class MinimalCtx:
        def __init__(self):
            self.tools = []
            self.hooks = []
            self.commands = []
            self.skills = []

        def register_tool(self, name, toolset, schema, handler, description=""):
            self.tools.append(name)

        def register_hook(self, name, callback):
            self.hooks.append(name)

        def register_command(self, name, handler, description="", args_hint=""):
            self.commands.append(name)

        def register_skill(self, name, path, description="", frontmatter=None):
            self.skills.append(name)

        def get_config(self, key, default=None):
            return default

    ctx = MinimalCtx()
    plugin.register(ctx)
    assert len(ctx.tools) == 54
    assert ctx.hooks == ["pre_tool_call"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_every_schema_is_a_json_schema_object():
    for schema, handler in tools.TOOLS:
        assert schema["name"].startswith("azure_devops_")
        assert schema["description"].strip()
        assert callable(handler)
        parameters = schema["parameters"]
        assert parameters["type"] == "object"
        assert isinstance(parameters["properties"], dict)
        assert isinstance(parameters["required"], list)
        for name in parameters["required"]:
            assert name in parameters["properties"], f"{schema['name']}: required {name} is undeclared"


def test_every_tool_accepts_org_project_and_mock_except_the_doctor():
    for schema, _handler in tools.TOOLS:
        properties = schema["parameters"]["properties"]
        if schema["name"] == "azure_devops_doctor":
            continue
        for expected in ("org", "project", "mock"):
            assert expected in properties, f"{schema['name']} is missing {expected}"


def test_tools_that_need_a_team_declare_it():
    team_tools = {
        "azure_devops_list_boards",
        "azure_devops_get_board",
        "azure_devops_list_iterations",
        "azure_devops_get_iteration_work_items",
        "azure_devops_get_capacity",
        "azure_devops_set_board_columns",
        "azure_devops_set_iteration",
        "azure_devops_set_capacity",
    }
    for schema, _handler in tools.TOOLS:
        assert ("team" in schema["parameters"]["properties"]) == (schema["name"] in team_tools)


def test_tool_names_are_unique():
    names = [schema["name"] for schema, _ in tools.TOOLS]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# plugin.yaml
# ---------------------------------------------------------------------------


def _manifest():
    import yaml

    return yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))


def test_manifest_declares_exactly_the_registered_tools():
    manifest = _manifest()
    assert manifest["name"] == "azure-devops"
    assert manifest["kind"] == "standalone"
    assert manifest["manifest_version"] == 2
    assert manifest["api_version"] == 1
    assert set(manifest["provides_tools"]) == set(tool_names())
    assert len(manifest["provides_tools"]) == 54


def test_manifest_declares_the_hook_it_registers():
    assert _manifest()["provides_hooks"] == ["pre_tool_call"]


def test_manifest_only_uses_keys_hermes_knows():
    known = {
        "name", "version", "description", "author", "requires_env", "provides_tools", "provides_hooks",
        "kind", "hooks", "label", "optional_env", "platforms", "external_dependencies",
        "pip_dependencies", "provides_browser_providers", "provides_web_providers",
        "manifest_version", "api_version", "requires_plugins", "python_dependencies",
        "config_schema", "license", "homepage", "tags", "capabilities", "emits", "listens",
        "hermes", "depends", "requires_hermes", "python_runtime",
    }
    assert set(_manifest()) <= known


def test_manifest_config_schema_matches_the_safety_module():
    schema = _manifest()["config_schema"]["safety_level"]
    assert schema["choices"] == list(sub("safety").VALID_LEVELS)
    assert schema["default"] == "open"


def test_optional_env_entries_are_well_formed():
    for entry in _manifest().get("optional_env", []):
        assert re.fullmatch(r"[A-Z0-9_]+", entry["name"]), entry["name"]
        assert entry.get("description")


# ---------------------------------------------------------------------------
# Repository layout
# ---------------------------------------------------------------------------


def test_expected_files_are_present():
    for relative in (
        "__init__.py",
        "models.py",
        "config.py",
        "auth.py",
        "client.py",
        "formatters.py",
        "mocks.py",
        "safety.py",
        "status.py",
        "commands.py",
        "plugin.yaml",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        ".github/workflows/ci.yml",
        "skills/azure-devops-workitems/SKILL.md",
        "catalog/azure-devops.yaml",
    ):
        assert (ROOT / relative).exists(), f"missing {relative}"


def test_pyproject_declares_no_runtime_dependencies():
    """A Hermes plugin installs into Hermes' venv; stdlib only is the point."""
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == []
    assert data["project"]["requires-python"] == ">=3.11"


def test_all_fixtures_used_by_the_mock_layer_exist():
    mocks = sub("mocks")
    names = {
        "work-items.json", "work-item-types.json", "comments.json", "revisions.json", "teams.json",
        "boards.json", "board-detail.json", "iterations.json", "iteration-work-items.json",
        "capacity.json", "repos.json", "branches.json", "pull-requests.json", "pr-threads.json",
        "pr-commits.json", "policies.json", "policy-evaluations.json", "pipelines.json", "runs.json",
        "run-artifacts.json", "run-logs.json", "run-timeline.json", "test-plans.json",
        "test-suites.json", "test-cases.json", "test-points.json", "test-runs.json",
        "test-results.json",
    }
    on_disk = {path.name for path in mocks.FIXTURES_DIR.glob("*.json")}
    assert names <= on_disk, f"missing fixtures: {sorted(names - on_disk)}"


def test_catalog_entry_matches_the_manifest():
    import yaml

    catalog = yaml.safe_load((ROOT / "catalog" / "azure-devops.yaml").read_text(encoding="utf-8"))
    manifest = _manifest()

    assert catalog["name"] == manifest["name"]
    assert catalog["version"] == manifest["version"]
    assert catalog["repo"] == "https://github.com/Smotherer007/hermes-azure-devops"
    # The catalog pins an exact 40-character commit.
    assert re.fullmatch(r"[0-9a-f]{40}", catalog["sha"]), catalog["sha"]
    assert set(catalog["capabilities"]["provides_tools"]) == set(manifest["provides_tools"])
    assert catalog["capabilities"]["provides_hooks"] == manifest["provides_hooks"]


def test_skills_carry_frontmatter_descriptions():
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"{path} has no frontmatter"
        assert "description:" in content.split("\n---", 1)[0]
        assert plugin._frontmatter_description(path)
