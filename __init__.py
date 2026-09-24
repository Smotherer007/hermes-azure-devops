"""Hermes Azure DevOps plugin.

Gives Hermes read and write access to Azure DevOps -- work items, boards,
sprints and capacity, repositories and pull requests, pipelines and builds, and
test plans -- through the Azure DevOps REST API.

Port of the pi extension pi-azure-devops: the same 54 tools with the same
names, parameters and output, the same config file shape, the same safety
levels and the same skills. The npm dependency is gone; everything is standard
library.

Tools (54), in registration order:

  azure_devops_doctor                     config, auth and connection health
  ..._get_work_item / ..._query_work_items / ..._list_work_item_types
  ..._get_work_item_comments / ..._get_work_item_revisions
  ..._create_work_item / ..._update_work_item / ..._add_work_item_comment
  ..._manage_work_item_links
  ..._list_teams / ..._list_boards / ..._get_board
  ..._list_iterations / ..._get_iteration_work_items / ..._get_capacity
  ..._set_board_columns / ..._set_iteration / ..._set_capacity
  ..._list_repos / ..._get_repo / ..._list_branches
  ..._list_pull_requests / ..._get_pull_request / ..._get_pull_request_threads
  ..._get_pull_request_commits / ..._list_policies / ..._get_policy_evaluations
  ..._create_pull_request / ..._update_pull_request / ..._add_pull_request_comment
  ..._set_pull_request_vote / ..._set_pull_request_autocomplete
  ..._link_pr_work_items
  ..._list_pipelines / ..._get_pipeline / ..._list_runs / ..._get_run
  ..._get_run_artifacts / ..._get_run_logs / ..._get_run_timeline
  ..._run_pipeline / ..._cancel_run / ..._retry_run
  ..._list_test_plans / ..._get_test_plan / ..._list_test_suites
  ..._get_test_suite / ..._list_test_cases / ..._list_test_points
  ..._get_test_run / ..._list_test_runs / ..._create_test_run
  ..._update_test_results

Layout:
  models.py      frozen dataclasses: config, card, errors
  config.py      org/project resolution, safety cascade, 0600 profile store
  auth.py        PAT (basic) and Azure CLI (bearer) resolution, token cache
  client.py      all HTTP: the 54 SDK calls as plain REST, stdlib only
  formatters.py  pure functions: API payloads -> display strings
  mocks.py       fixture-backed mock mode
  safety.py      safety level for mutation tools (pre_tool_call hook)
  status.py      connection card, label and status text
  commands.py    /azure-devops-status plus the 14 ported prompt templates
  tools/         the 54 tools, grouped by area
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from . import config as cfg
from .commands import make_doctor_command, make_status_command, template_commands
from .safety import make_pre_tool_call_hook
from .tools import TOOLSET, TOOLS

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent

SKILLS = {
    "azure-devops-workitems": "Azure DevOps work items, boards, repos, pull requests, pipelines and "
    "test plans: use the azure_devops_* tools for any of it.",
}


def _frontmatter_description(path: Path) -> str:
    """The single-line ``description:`` of a SKILL.md, without a YAML parser."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not content.startswith("---\n"):
        return ""
    end = content.find("\n---", 4)
    for line in content[4:end].splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip().strip("\"'")
    return ""


def _prompt_section(_session: Mapping[str, Any]) -> str:
    """Short, frozen-per-session pointer to the skills and the configured orgs.

    Plugin skills are not listed in Hermes' skill index, so without this the
    model would never learn that they exist. No PATs, no secrets -- only names.
    """
    lines = [
        "Azure DevOps tools (azure_devops_*) are available for work items, boards and sprints, "
        "repositories and pull requests, pipelines and builds, and test plans. Use the matching "
        "skill for anything beyond a single lookup:",
    ]
    lines += [f"- azure-devops:{name} -- {text}" for name, text in SKILLS.items()]

    try:
        connections, errors = cfg.resolve_all_org_configs()
    except Exception:
        connections, errors = [], []

    if connections:
        lines.append("Configured Azure DevOps connections (the org/project parameters pick one):")
        for connection in connections:
            lines.append(
                f"- {connection.org_label}/{connection.project}"
                f" (safety: {connection.safety_level}, auth: {connection.auth_method})"
            )
    else:
        lines.append(
            f"No Azure DevOps connection is configured yet; edit {cfg.config_path()}, "
            "then run azure_devops_doctor."
        )
    if errors:
        lines.append("Configuration warnings: " + "; ".join(errors))
    return "\n".join(lines)


def register(ctx) -> None:
    """Called once by the Hermes plugin loader."""
    cfg.load_config()

    for tool_schema, handler in TOOLS:
        ctx.register_tool(
            name=tool_schema["name"],
            toolset=TOOLSET,
            schema=tool_schema,
            handler=handler,
            description=tool_schema["description"],
        )

    for name, short in SKILLS.items():
        skill_md = _PLUGIN_DIR / "skills" / name / "SKILL.md"
        if skill_md.exists():
            ctx.register_skill(
                name, skill_md, description=_frontmatter_description(skill_md) or short
            )

    def safety_level() -> Any:
        try:
            return ctx.get_config("safety_level", default="open")
        except Exception:
            return "open"

    ctx.register_hook("pre_tool_call", make_pre_tool_call_hook(safety_level))

    ctx.register_command(
        "azure-devops-status",
        handler=make_status_command(ctx),
        description="Show the current Azure DevOps connection status",
    )
    ctx.register_command(
        "azure-devops-doctor",
        handler=make_doctor_command(ctx),
        description="Check Azure DevOps configuration, authentication and connection health",
        args_hint="[focus]",
    )
    for name, handler, description, hint in template_commands(ctx):
        ctx.register_command(
            f"azure-devops-{name}",
            handler=handler,
            description=description or f"Run the azure-devops-{name} prompt",
            args_hint=hint,
        )

    register_section = getattr(ctx, "register_system_prompt_section", None)
    if callable(register_section):
        try:
            register_section("azure-devops.overview", _prompt_section)
        except Exception:  # older Hermes: the skills are still reachable via skills_list
            logger.debug("azure-devops: could not register the system prompt section", exc_info=True)
