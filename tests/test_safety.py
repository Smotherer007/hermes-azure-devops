"""The safety level: which tools are gated, and how each level behaves."""

from __future__ import annotations

from conftest import sub

safety = sub("safety")
tools = sub("tools")


def test_mutation_tool_set_matches_the_write_tools():
    assert "azure_devops_create_work_item" in tools.MUTATION_TOOLS
    assert "azure_devops_run_pipeline" in tools.MUTATION_TOOLS
    assert "azure_devops_update_test_results" in tools.MUTATION_TOOLS
    # Reads are never gated.
    assert "azure_devops_get_work_item" not in tools.MUTATION_TOOLS
    assert "azure_devops_list_pipelines" not in tools.MUTATION_TOOLS
    assert "azure_devops_doctor" not in tools.MUTATION_TOOLS


def test_every_mutation_tool_is_a_registered_tool():
    assert tools.MUTATION_TOOLS <= set(tools.TOOL_NAMES)


def test_normalize_level_fails_closed_on_unknown_values():
    assert safety.normalize_level("open") == "open"
    assert safety.normalize_level("READONLY") == "readonly"
    assert safety.normalize_level("") == "open"
    assert safety.normalize_level(None) == "open"
    assert safety.normalize_level("nonsense") == "confirm"


def test_should_block_only_in_readonly():
    name = "azure_devops_create_work_item"
    assert safety.should_block("readonly", name) is not None
    assert safety.should_block("confirm", name) is None
    assert safety.should_block("open", name) is None
    # Never blocks a read tool, whatever the level.
    assert safety.should_block("readonly", "azure_devops_get_work_item") is None


def test_hook_passes_through_when_open():
    hook = safety.make_pre_tool_call_hook(lambda: "open")
    assert hook("azure_devops_create_work_item", {"title": "x"}) is None
    assert hook("azure_devops_doctor", {}) is None


def test_hook_blocks_when_readonly():
    hook = safety.make_pre_tool_call_hook(lambda: "readonly")
    verdict = hook("azure_devops_run_pipeline", {"pipelineId": 3})
    assert verdict["action"] == "block"
    assert "readonly" in verdict["message"]


def test_hook_asks_for_approval_in_confirm_mode():
    hook = safety.make_pre_tool_call_hook(lambda: "confirm")
    verdict = hook("azure_devops_create_pull_request", {
        "title": "Fix login",
        "sourceRefName": "refs/heads/fix",
        "targetRefName": "refs/heads/main",
    })
    assert verdict["action"] == "approve"
    assert verdict["rule_key"] == "azure-devops:azure_devops_create_pull_request"
    assert "Fix login" in verdict["message"]
    # The approval prompt names both branches without the refs/heads/ noise.
    assert "(fix → main)" in verdict["message"]


def test_stricter_never_loosens():
    assert safety.stricter("open", "readonly") == "readonly"
    assert safety.stricter("readonly", "open") == "readonly"
    assert safety.stricter("open", "confirm") == "confirm"
    assert safety.stricter("confirm", "confirm") == "confirm"
    assert safety.stricter("open", "open") == "open"


def _file_level(args):
    """Adapter: the hook hands over the whole args mapping (see __init__.py)."""
    return sub("config").effective_safety_level(args.get("org"), args.get("project"))


def test_a_readonly_project_in_the_config_file_is_enforced(configure, isolated_config):
    """The hook must gate on the org/project the call targets, not just the setting."""
    from conftest import write_config

    write_config(isolated_config, {
        "orgs": [
            {
                "name": "prod",
                "url": "https://dev.azure.com/prod",
                "safetyLevel": "readonly",
                "projects": [{"name": "P", "pat": "x"}],
            },
            {
                "name": "dev",
                "url": "https://dev.azure.com/dev",
                "safetyLevel": "open",
                "projects": [{"name": "D", "pat": "y"}],
            },
        ],
        "defaultOrg": "dev",
    })
    sub("config").load_config()

    hook = safety.make_pre_tool_call_hook(lambda: "open", _file_level)

    # The dev org is unrestricted...
    assert hook("azure_devops_run_pipeline", {"pipelineId": 1}) is None
    # ...while the same tool against the production org is blocked.
    verdict = hook("azure_devops_run_pipeline", {"pipelineId": 1, "org": "prod"})
    assert verdict["action"] == "block"


def test_an_unset_level_falls_back_to_confirm_not_open(configure, isolated_config):
    """A connection with no safetyLevel anywhere asks before writing."""
    from conftest import write_config

    write_config(isolated_config, {
        "orgs": [{"name": "o", "url": "https://dev.azure.com/o", "projects": [{"name": "P", "pat": "x"}]}]
    })
    sub("config").load_config()

    hook = safety.make_pre_tool_call_hook(lambda: "open", _file_level)
    assert hook("azure_devops_cancel_run", {"runId": 1})["action"] == "approve"


def test_the_plugin_setting_can_only_tighten(configure):
    configure()  # config file says confirm
    hook = safety.make_pre_tool_call_hook(lambda: "readonly", _file_level)
    assert hook("azure_devops_create_work_item", {"title": "x"})["action"] == "block"


def test_a_broken_config_does_not_unblock_a_mutation(isolated_config):
    isolated_config.write_text("{ not json", encoding="utf-8")
    config_module = sub("config")
    config_module.load_config()

    hook = safety.make_pre_tool_call_hook(lambda: "confirm", _file_level)
    assert hook("azure_devops_create_work_item", {"title": "x"})["action"] == "approve"


def test_hook_reads_the_level_lazily():
    """The setting is read per call, so a config change applies immediately."""
    levels = ["open"]
    hook = safety.make_pre_tool_call_hook(lambda: levels[0])
    assert hook("azure_devops_cancel_run", {"runId": 1}) is None
    levels[0] = "readonly"
    assert hook("azure_devops_cancel_run", {"runId": 1})["action"] == "block"


def test_summaries_name_the_thing_being_changed():
    assert "Update #42" in safety.format_mutation_summary(
        "azure_devops_update_work_item", {"id": 42, "fields": {"System.State": "Closed"}}
    )
    assert "#7" in safety.format_mutation_summary(
        "azure_devops_set_pull_request_vote", {"pullRequestId": 7, "vote": "approve"}
    )
    assert "enable" in safety.format_mutation_summary(
        "azure_devops_set_pull_request_autocomplete", {"pullRequestId": 7, "enabled": True}
    )
    assert "2 team member(s)" in safety.format_mutation_summary(
        "azure_devops_set_capacity", {"iterationId": "sprint-1", "capacities": [{}, {}]}
    )
    # An unknown tool still produces a usable line.
    assert safety.format_mutation_summary("azure_devops_mystery", {"a": 1}).startswith(
        "azure_devops_mystery:"
    )


def test_long_comment_text_is_truncated_in_the_prompt():
    summary = safety.format_mutation_summary(
        "azure_devops_add_pull_request_comment", {"pullRequestId": 1, "content": "x" * 200}
    )
    assert "..." in summary
    assert len(summary) < 140
