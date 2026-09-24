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
