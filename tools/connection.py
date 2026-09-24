"""azure_devops_doctor -- check config, auth readiness and connection health.

Validates *every* configured org x project pair, not just the default one, so a
half-configured file is caught before a tool fails in the middle of real work.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import client
from ..auth import try_resolve_auth
from ..models import AzureDevOpsConfig
from ._base import (
    ORG_PROPERTY,
    PROJECT_PROPERTY,
    error,
    opt_bool,
    result,
    schema,
    tool_handler,
)

DOCTOR_SCHEMA = schema(
    "azure_devops_doctor",
    "Check Azure DevOps configuration, authentication readiness, and connection health. "
    "Run this first to verify your setup before using other Azure DevOps tools. "
    "The doctor validates ALL configured orgs and projects from azure-devops-config.json.",
    {
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": {
            "type": "boolean",
            "description": "Use mock mode (report healthy without a network call)",
        },
    },
)


def _mock_report(connections: List[AzureDevOpsConfig]) -> str:
    lines = [
        "## Azure DevOps Configuration (Mock Mode)",
        f"- **Orgs configured:** {len(connections)}",
        "",
    ]
    for connection in connections:
        lines += [
            f"### {connection.org_label} / {connection.project}",
            f"- **URL:** {connection.org_url}",
            "- **Auth:** ✅ Mock — simulated as authenticated",
            "- **Connection:** ✅ Mock — simulated as connected (6 work item types)",
            "",
        ]
    lines.append("⚠️ Running in mock mode. No network calls were made.")
    return "\n".join(lines)


@tool_handler
def doctor(args: Dict[str, Any]) -> str:
    from .. import config as cfg

    connections, config_errors = cfg.resolve_all_org_configs()

    if config_errors and not connections:
        detail = "\n".join(f"  ❌ {item}" for item in config_errors)
        return error(
            "Azure DevOps configuration issues:\n"
            f"{detail}\n\n"
            f"Edit {cfg.config_path()} with your orgs, projects, and PATs."
        )

    if not connections:
        return error(
            f"No Azure DevOps orgs are configured. Edit {cfg.config_path()} with your orgs, "
            "projects, and PATs."
        )

    if opt_bool(args, "mock") is True or connections[0].mock:
        return result(_mock_report(connections), orgCount=len(connections), mock=True)

    lines: List[str] = ["## Azure DevOps Configuration", f"- **Orgs configured:** {len(connections)}", ""]

    for index, connection in enumerate(connections):
        if index:
            lines.append("")
        lines.append(f"### {connection.org_label} / {connection.project}")
        lines.append(f"- **URL:** {connection.org_url}")

        auth = try_resolve_auth(connection)
        if not auth:
            lines.append("- **Auth:** ❌ No authentication available")
            continue
        lines.append(f"- **Auth:** ✅ Authenticated via **{auth.method}**")

        try:
            types = client.probe_connection(connection)
            lines.append(f"- **Connection:** ✅ Connected — {len(types)} work item types available")
        except Exception as exc:
            lines.append(f"- **Connection:** ❌ Failed: {client.format_ado_error(exc)}")

    if config_errors:
        lines += ["", "## ⚠️ Config Warnings"]
        lines += [f"- {item}" for item in config_errors]

    return result("\n".join(lines), orgCount=len(connections))
