"""Safety level for mutation tools, enforced through Hermes' ``pre_tool_call`` hook.

``plugins.entries.azure-devops.settings.safety_level`` in ``config.yaml`` (or the
settings form in the Desktop app):

* ``open`` -- mutation tools run directly.
* ``confirm`` -- every mutation goes through Hermes' human-approval gate; the
  prompt shows a one-line summary of what would change.
* ``readonly`` -- mutation tools are blocked outright.

Read tools are never affected. The three levels can also be set per org and per
project in the config file (project > org > global), which is how a production
organisation can be pinned to ``readonly`` while a dev org stays ``open``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .tools import MUTATION_TOOLS, is_mutation_tool

VALID_LEVELS = ("open", "confirm", "readonly")


def normalize_level(value: Any) -> str:
    level = str(value or "open").strip().lower()
    # Unknown values fail closed to the level that still lets people work.
    return level if level in VALID_LEVELS else "confirm"


def should_block(safety_level: str, tool_name: str) -> Optional[str]:
    """A block reason when the tool must not run, otherwise None."""
    if not is_mutation_tool(tool_name):
        return None
    if normalize_level(safety_level) == "readonly":
        return (
            f'Tool "{tool_name}" is blocked in readonly safety mode. Change "safetyLevel" '
            "in azure-devops-config.json to \"open\" or \"confirm\"."
        )
    return None


def make_pre_tool_call_hook(get_level: Callable[[], Any]) -> Callable[..., Optional[dict]]:
    """Build the pre_tool_call hook around a settings reader."""

    def pre_tool_call(
        tool_name: str = "", args: Optional[dict] = None, **_kwargs: Any
    ) -> Optional[dict]:
        if tool_name not in MUTATION_TOOLS:
            return None

        level = normalize_level(get_level())
        if level == "open":
            return None
        if level == "readonly":
            return {
                "action": "block",
                "message": f"{tool_name} is blocked: the Azure DevOps plugin is set to readonly "
                '(plugins.entries.azure-devops.settings.safety_level, or "safetyLevel" in '
                "azure-devops-config.json).",
            }
        return {
            "action": "approve",
            "message": format_mutation_summary(tool_name, args or {}),
            "rule_key": f"azure-devops:{tool_name}",
        }

    return pre_tool_call


# ---------------------------------------------------------------------------
# One-line summaries for the approval prompt
# ---------------------------------------------------------------------------


def _truncate(value: Any, limit: int = 80) -> str:
    text = str(value or "")
    return text[:limit] + ("..." if len(text) > limit else "")


def format_mutation_summary(tool_name: str, params: Dict[str, Any]) -> str:
    """A single line a human can judge at a glance."""
    if tool_name == "azure_devops_create_work_item":
        return f"Create {params.get('type') or 'work item'}: \"{params.get('title') or '(untitled)'}\""

    if tool_name == "azure_devops_update_work_item":
        work_item_id = params.get("id") or params.get("workItemId") or "?"
        fields = params.get("fields") or {}
        rendered = ", ".join(f"{key} → {value}" for key, value in fields.items()) or "(no fields)"
        return f"Update #{work_item_id}: {rendered}"

    if tool_name == "azure_devops_add_work_item_comment":
        return f'Comment on #{params.get("workItemId") or "?"}: "{_truncate(params.get("text"))}"'

    if tool_name == "azure_devops_manage_work_item_links":
        operation = params.get("operation") or "add"
        arrow = "→" if operation == "add" else "✕"
        return (
            f'{"Add" if operation == "add" else "Remove"} {params.get("relationType") or "link"} link: '
            f'#{params.get("workItemId") or "?"} {arrow} #{params.get("targetId") or "?"}'
        )

    if tool_name == "azure_devops_set_board_columns":
        columns = params.get("columns") or []
        names = " → ".join(str((column or {}).get("name") or "?") for column in columns) or "(none)"
        return (
            f'Set board columns for "{params.get("boardId") or "?"}" '
            f'({params.get("team") or "default team"}): {names}'
        )

    if tool_name == "azure_devops_set_iteration":
        operation = params.get("operation") or "add"
        return (
            f'{"Add" if operation == "add" else "Remove"} iteration {params.get("iterationId") or "?"} '
            f'{"to" if operation == "add" else "from"} {params.get("team") or "default team"}'
        )

    if tool_name == "azure_devops_set_capacity":
        capacities = params.get("capacities") or []
        return (
            f"Set capacity for {len(capacities)} team member(s) in iteration "
            f"{params.get('iterationId') or '?'}"
        )

    if tool_name == "azure_devops_create_pull_request":
        source = str(params.get("sourceRefName") or "?").replace("refs/heads/", "")
        target = str(params.get("targetRefName") or "?").replace("refs/heads/", "")
        return f'Create PR: "{params.get("title") or "(untitled)"}" ({source} → {target})'

    if tool_name == "azure_devops_update_pull_request":
        changed = []
        if params.get("title"):
            changed.append("title")
        if params.get("description"):
            changed.append("description")
        if params.get("status"):
            changed.append(f"status → {params['status']}")
        return f"Update PR #{params.get('pullRequestId') or '?'}: {', '.join(changed) or 'no changes'}"

    if tool_name == "azure_devops_add_pull_request_comment":
        return f'Comment on PR #{params.get("pullRequestId") or "?"}: "{_truncate(params.get("content"))}"'

    if tool_name == "azure_devops_set_pull_request_vote":
        return f"Vote on PR #{params.get('pullRequestId') or '?'}: {params.get('vote') or '?'}"

    if tool_name == "azure_devops_set_pull_request_autocomplete":
        state = "enable" if params.get("enabled") else "disable"
        return f"Auto-complete PR #{params.get('pullRequestId') or '?'}: {state}"

    if tool_name == "azure_devops_link_pr_work_items":
        ids = ", ".join(f"#{item}" for item in params.get("workItemIds") or [])
        return f"Link work items to PR #{params.get('pullRequestId') or '?'}: {ids} ({params.get('operation') or 'add'})"

    if tool_name == "azure_devops_run_pipeline":
        parameters = params.get("templateParameters") or {}
        extra = (
            " with params: " + ", ".join(f"{key}={value}" for key, value in parameters.items())
            if parameters
            else ""
        )
        return (
            f"Run pipeline #{params.get('pipelineId') or '?'} on branch "
            f"{params.get('branch') or '(default)'}{extra}"
        )

    if tool_name == "azure_devops_cancel_run":
        return f"Cancel run #{params.get('runId') or '?'} (pipeline #{params.get('pipelineId') or '?'})"

    if tool_name == "azure_devops_retry_run":
        return f"Retry run #{params.get('runId') or '?'} (pipeline #{params.get('pipelineId') or '?'})"

    if tool_name == "azure_devops_create_test_run":
        return (
            f"Create test run: '{params.get('name') or '(auto-named)'}' "
            f"(plan #{params.get('planId') or '?'})"
        )

    if tool_name == "azure_devops_update_test_results":
        results = params.get("results") or []
        return f"Update {len(results)} test result(s) in run #{params.get('runId') or '?'}"

    import json

    return f"{tool_name}: {json.dumps(params, default=str)[:100]}"
