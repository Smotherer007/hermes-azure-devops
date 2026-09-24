"""Data types for the Hermes Azure DevOps plugin.

Configuration and domain data are plain frozen dataclasses: no behaviour,
no inheritance. Errors live here too, because every layer raises them.

The configuration shape is deliberately identical to pi-azure-devops'
``pi-azure-devops.json``, so one file serves both agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: How to authenticate against Azure DevOps.
AUTH_METHODS = ("pat", "azure-cli", "auto")

#: How cautious the write tools are.
SAFETY_LEVELS = ("open", "confirm", "readonly")


@dataclass(frozen=True)
class ProjectConfig:
    """One project inside an organization."""

    name: str
    #: Personal access token for this project. Optional: Azure CLI can be used instead.
    pat: Optional[str] = None
    #: Safety level for this project (most specific override wins).
    safety_level: Optional[str] = None


@dataclass(frozen=True)
class OrgConfig:
    """One Azure DevOps organization and the projects configured in it."""

    name: str
    #: Organization URL, e.g. https://dev.azure.com/myorg
    url: str
    projects: tuple = ()
    #: Safety level for this org (overridden by a project, overrides the global one).
    safety_level: Optional[str] = None


@dataclass(frozen=True)
class AzureDevOpsConfig:
    """One resolved org+project connection."""

    org_url: str
    project: str
    #: The org's ``name`` from the config file -- the value the ``org`` parameter takes.
    org_name: Optional[str] = None
    team: Optional[str] = None
    pat: Optional[str] = None
    #: Every configured org, so a tool can be pointed at a different one.
    all_orgs: tuple = ()
    auth_method: str = "auto"
    safety_level: str = "confirm"
    default_work_item_type: str = "User Story"
    max_query_results: int = 100
    autocomplete: bool = True
    mock: bool = False

    @property
    def org_label(self) -> str:
        """Display label for the org: the configured name, else read from the URL."""
        return self.org_name or extract_org_name(self.org_url)


def extract_org_name(org_url: str) -> str:
    """``https://dev.azure.com/myorg`` -> ``myorg``; other hosts keep their path."""
    stripped = org_url.strip()
    for prefix in ("https://", "http://"):
        if stripped.lower().startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    if stripped.lower().startswith("dev.azure.com/"):
        stripped = stripped[len("dev.azure.com/"):]
    stripped = stripped.strip("/")
    return stripped or org_url


@dataclass(frozen=True)
class Card:
    """Snapshot of the active connection, for the status surfaces."""

    org: str
    org_url: str
    project: str
    team: Optional[str] = None
    auth_method: str = "auto"
    safety_level: str = "confirm"
    default_work_item_type: str = "User Story"
    max_query_results: int = 100
    mock: bool = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Required configuration is missing or unusable."""

    def __init__(self, missing: List[str], message: Optional[str] = None) -> None:
        self.missing = list(missing)
        super().__init__(
            message
            or f"Missing required Azure DevOps configuration: {', '.join(self.missing)}"
        )


class AuthError(Exception):
    """No authentication method could be resolved."""

    def __init__(self, message: str, attempted: Optional[List[str]] = None) -> None:
        self.attempted = list(attempted or [])
        super().__init__(message)


class AzureDevOpsApiError(Exception):
    """A non-success response from Azure DevOps, or a transport failure."""

    def __init__(self, status: int, message: str, url: str = "", body: Any = None) -> None:
        self.status = status
        self.url = url
        self.body = body
        super().__init__(message)


class NotFoundError(AzureDevOpsApiError):
    """404 / TF401233 — the caller usually turns this into a friendly message."""

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(404, message, url)


class ToolInputError(ValueError):
    """Invalid arguments from the model. Reported back as a tool error."""
