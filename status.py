"""Connection status surfaces.

Pure functions that turn the resolved config into text a human reads. They are
the Hermes equivalent of pi-azure-devops' footer label and connection card: pi
renders them into the TUI, Hermes reports them through ``/azure-devops-status``
and the doctor.
"""

from __future__ import annotations

from typing import List, Optional

from .models import AzureDevOpsConfig, Card


def build_card(config: Optional[AzureDevOpsConfig]) -> Optional[Card]:
    """Snapshot the active connection, or None when nothing is configured."""
    if config is None:
        return None
    return Card(
        org=config.org_label,
        org_url=config.org_url,
        project=config.project,
        team=config.team,
        auth_method=config.auth_method,
        safety_level=config.safety_level,
        default_work_item_type=config.default_work_item_type,
        max_query_results=config.max_query_results,
        mock=config.mock,
    )


def connection_label(card: Optional[Card]) -> str:
    """Short one-line label, e.g. ``✓ Azure DevOps · neoimpulse/MyProject``."""
    if card is None:
        return "Azure DevOps · not configured"
    parts: List[str] = [f"{card.org}/{card.project}"]
    if card.team:
        parts.append(f"@{card.team}")
    return f"✓ Azure DevOps · {' · '.join(parts)}"


def status_text(card: Optional[Card], config_path: str = "") -> str:
    """Multi-line status, used by ``/azure-devops-status`` and the doctor."""
    if card is None:
        where = f"`{config_path}`" if config_path else "the config file"
        return "\n".join([
            "## Azure DevOps",
            "",
            "⚠️ **No configuration found.**",
            "",
            f"Edit {where} with your orgs, projects, and PATs, then run `/azure-devops-doctor`.",
        ])

    lines = [
        "## Azure DevOps Connection",
        "",
        f"- **Org:** {card.org}",
        f"- **Project:** {card.project}",
    ]
    if card.team:
        lines.append(f"- **Team:** {card.team}")
    lines += [
        f"- **URL:** {card.org_url}",
        f"- **Auth:** {card.auth_method}",
        f"- **Safety:** {card.safety_level}",
        f"- **Default work item type:** {card.default_work_item_type}",
        f"- **Max query results:** {card.max_query_results}",
        f"- **Mode:** {'mock (offline fixtures)' if card.mock else 'live API'}",
    ]
    return "\n".join(lines)
