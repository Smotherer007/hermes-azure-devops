"""Configuration loading, resolution and persistence.

The config file is the single source of truth, in the same shape
pi-azure-devops writes, so the same file serves both agents::

    {
      "orgs": [
        {"name": "my-org", "url": "https://dev.azure.com/my-org",
         "projects": [{"name": "MyProject", "pat": "..."}]}
      ],
      "defaultOrg": "my-org",
      "defaultProject": "MyProject",
      "defaultTeam": "MyTeam",
      "authMethod": "auto",
      "safetyLevel": "confirm",
      "defaultWorkItemType": "User Story",
      "maxQueryResults": 100,
      "mock": false
    }

Where it is read from, in order:

1. ``AZURE_DEVOPS_CONFIG`` -- an explicit path.
2. ``$HERMES_HOME/azure-devops-config.json`` -- this plugin's own file. Because
   ``HERMES_HOME`` is per Hermes profile, every profile gets its own set of orgs.
3. ``$PI_CODING_AGENT_DIR/pi-azure-devops.json`` -- the file pi-azure-devops
   already wrote, read-only. This makes the port work on a machine where the pi
   extension is already configured, without copying the PATs around.

If none of them exists, a template is written to the Hermes path so the doctor
has something concrete to point at. The file holds plaintext PATs, so it is
written 0600 into a 0700 directory.

Hermes runs tools on several threads and the CLI and gateway can be separate
processes, so every access re-reads the file when its modification time changes.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    AUTH_METHODS,
    SAFETY_LEVELS,
    AzureDevOpsConfig,
    ConfigError,
    OrgConfig,
    ProjectConfig,
)

_lock = threading.RLock()

DEFAULTS = {
    "auth_method": "auto",
    "safety_level": "confirm",
    "default_work_item_type": "User Story",
    "max_query_results": 100,
    "autocomplete": True,
    "mock": False,
}

TEMPLATE_JSON = """{
  "orgs": [
    {
      "name": "my-org",
      "url": "https://dev.azure.com/my-org",
      "projects": [
        {
          "name": "MyProject",
          "pat": "your-personal-access-token-here"
        }
      ]
    }
  ],
  "safetyLevel": "confirm"
}
"""

#: Markers of the untouched template, so an unconfigured plugin says so
#: instead of trying to reach a fictional organisation.
TEMPLATE_ORG_NAME = "my-org"
TEMPLATE_ORG_URL = "https://dev.azure.com/my-org"
TEMPLATE_PAT = "your-personal-access-token-here"

#: Raw config cache, keyed by source.
_raw: Optional[Dict[str, Any]] = None
_loaded_mtime: Optional[int] = None
_loaded_path: Optional[Path] = None
_using_pi_file = False


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _hermes_home() -> Path:
    try:  # the documented resolver honours profile overrides; fall back outside Hermes
        from hermes_constants import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        home = os.environ.get("HERMES_HOME", "").strip()
        return Path(home).expanduser() if home else Path.home() / ".hermes"


def _pi_config_path() -> Path:
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
    base = Path(agent_dir).expanduser() if agent_dir else Path.home() / ".pi" / "agent"
    return base / "pi-azure-devops.json"


def config_path() -> Path:
    """The path this plugin writes to."""
    override = os.environ.get("AZURE_DEVOPS_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return _hermes_home() / "azure-devops-config.json"


def _read_path() -> Path:
    """The path this plugin reads from: its own file, else the pi extension's."""
    path = config_path()
    if path.exists():
        return path
    pi_path = _pi_config_path()
    if pi_path.exists():
        return pi_path
    return path


def using_pi_file() -> bool:
    """True when the config in force was read from pi-azure-devops' file."""
    return _using_pi_file


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _parse(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"orgs": []}
    return raw if isinstance(raw, dict) else {"orgs": []}


def ensure_config_template() -> bool:
    """Create the template in the Hermes path if nothing is configured anywhere.

    Returns True when a template was written. Mirrors pi-azure-devops, which
    creates the file on session start, but only when there is no pi file to
    fall back to either.
    """
    path = config_path()
    if path.exists() or _pi_config_path().exists():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(TEMPLATE_JSON)
        return True
    except OSError:
        return False


def load_config() -> None:
    """(Re)read the config file and create a template when nothing exists."""
    global _raw, _loaded_mtime, _loaded_path, _using_pi_file
    with _lock:
        path = _read_path()
        if path == config_path() and not path.exists():
            ensure_config_template()
        path = _read_path()

        mtime: Optional[int] = None
        try:
            mtime = path.stat().st_mtime_ns if path.exists() else None
        except OSError:
            mtime = None

        _raw = _parse(path) if path.exists() else {"orgs": []}
        _loaded_path = path
        _loaded_mtime = mtime
        _using_pi_file = path != config_path()


def _refresh_if_changed() -> None:
    """Pick up edits made by another process or by hand."""
    path = _read_path()
    try:
        mtime = path.stat().st_mtime_ns if path.exists() else None
    except OSError:
        mtime = None
    if path != _loaded_path or mtime != _loaded_mtime:
        load_config()


def _raw_config() -> Dict[str, Any]:
    with _lock:
        if _raw is None:
            load_config()
        _refresh_if_changed()
        return _raw or {"orgs": []}


def raw_config() -> Dict[str, Any]:
    """The parsed config file, for the doctor's own reporting."""
    return dict(_raw_config())


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _valid_auth(value: Any) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in AUTH_METHODS else None


def _valid_safety(value: Any) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in SAFETY_LEVELS else None


def _orgs(raw: Dict[str, Any]) -> List[OrgConfig]:
    orgs: List[OrgConfig] = []
    for entry in raw.get("orgs") or []:
        if not isinstance(entry, dict):
            continue
        projects = []
        for proj in entry.get("projects") or []:
            if not isinstance(proj, dict):
                continue
            projects.append(
                ProjectConfig(
                    name=str(proj.get("name") or ""),
                    pat=(str(proj["pat"]) if proj.get("pat") else None),
                    safety_level=_valid_safety(proj.get("safetyLevel")),
                )
            )
        orgs.append(
            OrgConfig(
                name=str(entry.get("name") or ""),
                url=str(entry.get("url") or ""),
                projects=tuple(projects),
                safety_level=_valid_safety(entry.get("safetyLevel")),
                insecure_tls=bool(entry.get("insecureTls", False)),
            )
        )
    return orgs


def _find_org(orgs: List[OrgConfig], name: Optional[str]) -> Optional[OrgConfig]:
    if not name or not orgs:
        return None
    for org in orgs:
        if org.name == name:
            return org
    return None


def _find_project(org: OrgConfig, name: Optional[str]) -> Optional[ProjectConfig]:
    if not name:
        return org.projects[0] if org.projects else None
    for project in org.projects:
        if project.name == name:
            return project
    return None


def _is_placeholder(org: OrgConfig, project: Optional[ProjectConfig]) -> bool:
    """True for the template as written, i.e. nobody has filled it in yet."""
    project_pat = (project.pat or "").strip() if project else ""
    return (
        org.name == TEMPLATE_ORG_NAME
        and org.url.rstrip("/") == TEMPLATE_ORG_URL
        and project_pat == TEMPLATE_PAT
    )


def _effective_safety_level(
    global_level: Any,
    org: Optional[OrgConfig],
    project: Optional[ProjectConfig],
) -> str:
    """Priority (most specific wins): project > org > global > default."""
    for candidate in (
        project.safety_level if project else None,
        org.safety_level if org else None,
        _valid_safety(global_level),
    ):
        if candidate:
            return candidate
    return DEFAULTS["safety_level"]


def _settings(raw: Dict[str, Any]) -> Dict[str, Any]:
    max_results = raw.get("maxQueryResults")
    try:
        max_results = int(max_results) if max_results is not None else DEFAULTS["max_query_results"]
    except (TypeError, ValueError):
        max_results = DEFAULTS["max_query_results"]
    return {
        "auth_method": _valid_auth(raw.get("authMethod")) or DEFAULTS["auth_method"],
        "default_work_item_type": str(
            raw.get("defaultWorkItemType") or DEFAULTS["default_work_item_type"]
        ),
        "max_query_results": max_results,
        "autocomplete": DEFAULTS["autocomplete"] if raw.get("autocomplete") is None
        else bool(raw.get("autocomplete")),
        "mock": bool(raw.get("mock", DEFAULTS["mock"])),
        "team": (str(raw["defaultTeam"]).strip() or None) if raw.get("defaultTeam") else None,
    }


def _build(
    raw: Dict[str, Any],
    org: OrgConfig,
    project: ProjectConfig,
    settings: Dict[str, Any],
) -> AzureDevOpsConfig:
    return AzureDevOpsConfig(
        org_url=org.url.rstrip("/"),
        project=project.name,
        org_name=org.name or None,
        team=settings["team"],
        pat=project.pat or None,
        all_orgs=tuple(_orgs(raw)),
        auth_method=settings["auth_method"],
        safety_level=_effective_safety_level(raw.get("safetyLevel"), org, project),
        default_work_item_type=settings["default_work_item_type"],
        max_query_results=settings["max_query_results"],
        autocomplete=settings["autocomplete"],
        mock=settings["mock"],
        insecure_tls=org.insecure_tls,
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_config() -> AzureDevOpsConfig:
    """Resolve the default org+project. Raises :class:`ConfigError` if unusable."""
    raw = _raw_config()
    orgs = _orgs(raw)
    settings = _settings(raw)

    missing: List[str] = []
    default_org_name = raw.get("defaultOrg") or (orgs[0].name if orgs else None)
    org = _find_org(orgs, default_org_name)

    if org is None:
        missing.append("No orgs configured (set defaultOrg or add orgs)")
    elif not org.url:
        missing.append("org.url is required")

    default_project_name = raw.get("defaultProject") or (
        org.projects[0].name if org and org.projects else None
    )
    project = _find_project(org, default_project_name) if org else None
    if not project or not project.name:
        missing.append("No project configured (set defaultProject or add projects)")

    if missing:
        raise ConfigError(missing)

    assert org is not None and project is not None  # implied by `missing`
    if _is_placeholder(org, project):
        raise ConfigError(
            ["configuration still has the template values"],
            "Azure DevOps is not configured yet: the config file still contains the template "
            f"org/project/PAT. Edit {config_path()} with your org, project and PAT "
            "(or sign in with `az login` and delete the placeholder PAT).",
        )
    return _build(raw, org, project, settings)


def try_resolve_config() -> Optional[AzureDevOpsConfig]:
    try:
        return resolve_config()
    except Exception:
        return None


def resolve_org_project_config(
    base: AzureDevOpsConfig,
    org_name: Optional[str] = None,
    project_name: Optional[str] = None,
) -> AzureDevOpsConfig:
    """Point an existing config at another org/project from the same file.

    Used by the ``org`` and ``project`` parameters every tool accepts.
    """
    if not org_name and not project_name:
        return base

    raw = _raw_config()
    orgs = _orgs(raw)

    if org_name:
        # An explicitly named org must exist: silently using a different one
        # would make a typo look like it worked.
        target_org = _find_org(orgs, org_name)
        if target_org is None:
            available = ", ".join(org.name for org in orgs) or "none"
            raise ConfigError(
                [f'org "{org_name}"'],
                f'Organization "{org_name}" not found. Available: {available}',
            )
    else:
        # Keep the org the connection already points at. Matching the URL as
        # well as the derived name is what makes non-dev.azure.com hosts -- an
        # on-premise collection, a test server -- work with the project-only
        # override.
        target_org = None
        for candidate in orgs:
            if candidate.url.rstrip("/") == base.org_url.rstrip("/"):
                target_org = candidate
                break
        if target_org is None:
            target_org = _find_org(orgs, base.org_name) or (orgs[0] if orgs else None)

    target_project = None
    if project_name:
        target_project = _find_project(target_org, project_name)
    else:
        # No project given: keep the current project name if this org has it,
        # otherwise fall back to the org's first project.
        target_project = _find_project(target_org, base.project) or (
            target_org.projects[0] if target_org.projects else None
        )

    if target_project is None or not target_project.name:
        searched = project_name or base.project
        available = ", ".join(p.name for p in target_org.projects) or "none"
        raise ConfigError(
            [f'project "{searched}" in org "{target_org.name}"'],
            f'Project "{searched}" not found in org "{target_org.name}". Available: {available}',
        )

    settings = _settings(raw)
    settings["team"] = base.team or settings["team"]

    return AzureDevOpsConfig(
        org_url=target_org.url.rstrip("/"),
        project=target_project.name,
        org_name=target_org.name or None,
        team=settings["team"],
        pat=target_project.pat or base.pat,
        all_orgs=tuple(_orgs(raw)),
        auth_method=settings["auth_method"],
        safety_level=_effective_safety_level(raw.get("safetyLevel"), target_org, target_project),
        default_work_item_type=settings["default_work_item_type"],
        max_query_results=settings["max_query_results"],
        autocomplete=settings["autocomplete"],
        mock=settings["mock"],
        insecure_tls=target_org.insecure_tls,
    )


def resolve_all_org_configs() -> Tuple[List[AzureDevOpsConfig], List[str]]:
    """Every configured org x project pair, so the doctor can validate them all."""
    raw = _raw_config()
    settings = _settings(raw)
    orgs = _orgs(raw)
    errors: List[str] = []

    if not orgs:
        return [], ["No orgs configured in the config file"]

    connections: List[AzureDevOpsConfig] = []
    for org in orgs:
        if not org.url:
            errors.append(f'Org "{org.name or "(unnamed)"}": missing url')
            continue
        if not org.projects:
            errors.append(f'Org "{org.name}": no projects configured')
            continue
        for project in org.projects:
            if not project.name:
                errors.append(f'Org "{org.name}": project missing name')
                continue
            if _is_placeholder(org, project):
                # The template counts as unconfigured, not as a broken org.
                continue
            connections.append(_build(raw, org, project, settings))

    if not connections and not errors:
        errors.append(
            "No Azure DevOps organisation is configured yet (the config file still contains the template)"
        )
    return connections, errors


def _reset_for_testing() -> None:
    global _raw, _loaded_mtime, _loaded_path, _using_pi_file
    with _lock:
        _raw = None
        _loaded_mtime = None
        _loaded_path = None
        _using_pi_file = False
