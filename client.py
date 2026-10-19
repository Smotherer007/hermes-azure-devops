"""Azure DevOps REST client (standard library only).

pi-azure-devops is built on the npm package ``azure-devops-node-api``. Hermes
plugins install into Hermes' own virtualenv, so this port keeps the plugin
dependency-free and reimplements the ~54 SDK calls the tools make as plain
REST over :mod:`urllib.request`.

Everything a tool sees is the parsed JSON, in the same shape the SDK's
serializer would have produced -- the formatters and the tools work on the
Azure DevOps payloads directly, exactly as the pi extension does.

Auth is resolved once per (org, method, PAT) and cached; Azure CLI tokens are
cached in :mod:`auth`. A rotated PAT therefore invalidates the stale headers
immediately instead of serving an expired connection until restart.

Two deliberate deviations from pi-azure-devops, both of them bug fixes its own
skill documents (`azure-devops-pr-approve-autocomplete`):

* a PR vote uses the authenticated user's identity id from ``connectionData``
  instead of an empty string, which Azure DevOps rejects as unauthenticated;
* auto-complete sets ``autoCompleteSetBy`` to that same real identity id
  instead of ``{"id": ""}``, which fails with "Invalid argument value".
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .auth import resolve_auth
from .models import (
    AzureDevOpsApiError,
    AzureDevOpsConfig,
    NotFoundError,
)

#: Stable API version for almost everything.
API_VERSION = "7.1"

#: Work item comments are still preview-only in 7.1.
COMMENTS_API_VERSION = "7.1-preview.4"

#: ArtifactLink relations (PR <-> work item) silently vanish on 7.1-preview.x.
ARTIFACT_LINK_API_VERSION = "7.0"

DEFAULT_TIMEOUT_S = 30.0
PROBE_TIMEOUT_S = 15.0
PLUGIN_VERSION = "1.0.0"

_lock = threading.RLock()
_header_cache: Dict[str, Dict[str, str]] = {}
_identity_cache: Dict[str, str] = {}
_ssl_contexts: Dict[Any, ssl.SSLContext] = {}

#: Where a CA bundle usually lives, best first. macOS with a python.org build has
#: no default verify path at all (Node ships its own CA store, which is why the
#: pi extension never hits this), so the system bundle has to be named explicitly.
#: The OS store comes before certifi on purpose: a corporate root CA installed in
#: the system keychain is there, not in certifi's Mozilla-derived list.
CA_BUNDLE_CANDIDATES = (
    "/etc/ssl/cert.pem",  # macOS, BSD
    "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL, Fedora, CentOS
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu
    "/etc/ssl/ca-bundle.pem",  # SUSE
)


def _ca_bundle() -> Optional[str]:
    """A CA bundle to verify with, or None to let Python decide."""
    # Python honours these itself, so do not override an explicit choice.
    for variable in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if os.environ.get(variable, "").strip():
            return None

    for candidate in CA_BUNDLE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate

    try:
        import certifi  # type: ignore

        path = certifi.where()
        return path if Path(path).is_file() else None
    except Exception:
        return None


def _ssl_context(config: AzureDevOpsConfig) -> Optional[ssl.SSLContext]:
    """A context per verification mode, so it is built once.

    ``insecureTls`` on the org is the escape hatch for an on-premise server with
    a self-signed certificate; it is part of the cache key so that switching
    orgs cannot leak verification settings into one another.
    """
    if config.insecure_tls:
        key: Any = "insecure"
    else:
        key = _ca_bundle() or "system"

    with _lock:
        cached = _ssl_contexts.get(key)
    if cached is not None:
        return cached

    if key == "insecure":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif key == "system":
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=key)

    with _lock:
        _ssl_contexts[key] = context
    return context


# ---------------------------------------------------------------------------
# URLs and parameters
# ---------------------------------------------------------------------------


def _quote(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="")


def _org_url(config: AzureDevOpsConfig) -> str:
    return config.org_url.rstrip("/")


def _project(config: AzureDevOpsConfig, project: Optional[str] = None) -> str:
    return _quote(project or config.project)


def _build_url(base: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Append query parameters, dropping None and rendering bools as true/false."""
    if not params:
        return base
    pairs: List[tuple] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            if not value:
                continue
            pairs.append((key, ",".join(str(item) for item in value)))
        else:
            pairs.append((key, str(value)))
    if not pairs:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urllib.parse.urlencode(pairs)}"


def _unwrap(payload: Any) -> List[Any]:
    """Collection endpoints answer ``{count, value: [...]}``; return the list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            return value
    return []


def _as_dict(payload: Any) -> Dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------


#: Azure DevOps error codes that are meaningful on their own. Matched as
#: substrings only because the codes are distinctive: no status number is, and
#: ``"401" in "TF401320"`` is exactly the false positive this guards against.
_CODE_HINTS = (
    ("TF401232", "Project not found. Verify the project name in your configuration."),
    ("TF401233", "Work item not found. Check the work item ID."),
    ("VS402335", "Invalid work item type. Use azure_devops_list_work_item_types to see valid types."),
    ("TF401181", "The pull request cannot be edited in its current state (it may already be merging or completed)."),
)

#: Translated by HTTP status, taken from the exception rather than the text.
_STATUS_HINTS = {
    401: "Authentication failed. Check your PAT or Azure CLI login.",
    403: "Permission denied. Your credentials lack access to this resource.",
    404: "Resource not found. Check the organization URL and project name.",
    429: "Rate limited by Azure DevOps. Wait a moment and try again.",
}

#: Transport failures only ever appear as text.
_NETWORK_HINTS = (
    ("ETIMEDOUT", "Network error: could not reach Azure DevOps. Check your connection."),
    ("ECONNREFUSED", "Network error: could not reach Azure DevOps. Check your connection."),
    ("ENOTFOUND", "DNS error: could not resolve the Azure DevOps hostname. Check the org URL."),
)

#: A status number counts only at a word boundary. Without this, ``TF401320``
#: would read as "401" and every rule violation would look like a login problem.
_STATUS_IN_TEXT = re.compile(r"(?<![\w.])(401|403|404|429)(?!\d)")


def rule_validation_fields(payload: Any) -> List[str]:
    """The fields Azure DevOps flagged on a rule violation, e.g. a missing mandatory field.

    The API answers such a rejection with 400 and a ``RuleValidationErrors``
    list inside ``customProperties``; naming those fields is the difference
    between "request failed" and an actionable message.
    """
    body = _as_dict(payload)
    rules = body.get("RuleValidationErrors")
    if not isinstance(rules, list):
        rules = _as_dict(body.get("customProperties")).get("RuleValidationErrors")

    labels: List[str] = []
    for rule in rules if isinstance(rules, list) else []:
        entry = _as_dict(rule)
        reference = entry.get("fieldReferenceName")
        if not isinstance(reference, str) or not reference:
            continue
        # "TF401320: Rule Error for field Acceptance Criteria." -> the label a
        # user sees in the form.
        match = re.search(r"for field ([^.]+)\.", str(entry.get("errorMessage") or ""))
        label = match.group(1).strip() if match else ""
        text = f"{label} ({reference})" if label else reference
        if text not in labels:
            labels.append(text)
    return labels


def format_ado_error(error: Any) -> str:
    """Turn an Azure DevOps failure into one readable line."""
    message = str(error)

    fields = rule_validation_fields(getattr(error, "body", None))
    if fields:
        return (
            "Azure DevOps rejected the request: required field(s) missing or invalid: "
            + ", ".join(fields)
            + " (TF401320)."
        )

    for code, friendly in _CODE_HINTS:
        if code in message:
            return friendly

    status = getattr(error, "status", None)
    if isinstance(status, int) and status in _STATUS_HINTS:
        return _STATUS_HINTS[status]

    # Only trust the text when no HTTP status survived: a 400 whose body quotes
    # "401" must not be read as an authentication failure.
    if not isinstance(status, int) or status == 0:
        found = _STATUS_IN_TEXT.search(message)
        if found:
            return _STATUS_HINTS[int(found.group(1))]

    for needle, friendly in _NETWORK_HINTS:
        if needle in message:
            return friendly

    first_line = message.split("\n")[0].strip()
    return first_line or "Unknown error"


def is_auth_error(error: Any) -> bool:
    status = getattr(error, "status", None)
    if isinstance(status, int) and status in (401, 403):
        return True
    message = str(error)
    return "Unauthorized" in message or "Forbidden" in message


def is_not_found_error(error: Any) -> bool:
    if isinstance(error, NotFoundError):
        return True
    status = getattr(error, "status", None)
    if isinstance(status, int) and status == 404:
        return True
    message = str(error)
    return "TF401233" in message or "Not Found" in message


def _describe_failure(status: int, payload: Any, url: str) -> AzureDevOpsApiError:
    body = _as_dict(payload)
    detail = ""
    for key in ("message", "error", "value"):
        candidate = body.get(key)
        if isinstance(candidate, str) and candidate.strip():
            detail = candidate.strip()
            break

    if status == 401:
        return AzureDevOpsApiError(
            status,
            "Azure DevOps rejected the credentials (401). Check the PAT in the config file, "
            "or run `az login` for Azure CLI auth.",
            url,
            payload,
        )
    if status == 403:
        suffix = f": {detail}" if detail else ""
        return AzureDevOpsApiError(
            status,
            f"Azure DevOps denied access (403){suffix}. The PAT may lack the required scope "
            "(Work items, Code, Build, Test Management).",
            url,
            payload,
        )
    if status == 404:
        suffix = f": {detail}" if detail else ""
        return NotFoundError(f"Azure DevOps returned 404{suffix}", url)
    if status == 429:
        return AzureDevOpsApiError(
            status, "Azure DevOps rate limit reached (429). Wait a moment and retry.", url, payload
        )

    fields = rule_validation_fields(payload)
    if fields:
        return AzureDevOpsApiError(
            status,
            f"Azure DevOps rejected the request ({status}): required field(s) missing or "
            f"invalid: {', '.join(fields)} (TF401320).",
            url,
            payload,
        )

    suffix = f": {detail}" if detail else ""
    return AzureDevOpsApiError(status, f"Azure DevOps request failed ({status}){suffix}", url, payload)


# ---------------------------------------------------------------------------
# Core request
# ---------------------------------------------------------------------------


def _headers_for(config: AzureDevOpsConfig) -> Dict[str, str]:
    key = f"{config.org_url}::{config.auth_method}::{config.pat or ''}"
    with _lock:
        cached = _header_cache.get(key)
    if cached:
        return cached

    result = resolve_auth(config)
    headers = dict(result.headers)
    with _lock:
        _header_cache[key] = headers
    return headers


def clear_connection_cache() -> None:
    """Drop cached auth headers and identities (after an auth failure, say)."""
    with _lock:
        _header_cache.clear()
        _identity_cache.clear()


def request(
    config: AzureDevOpsConfig,
    method: str,
    url: str,
    body: Any = None,
    *,
    content_type: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Any:
    """One HTTP call. Raises :class:`AzureDevOpsApiError` for anything but 2xx."""
    headers = {
        "Accept": "application/json",
        "User-Agent": f"hermes-azure-devops/{PLUGIN_VERSION}",
        **_headers_for(config),
    }
    data: Optional[bytes] = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = content_type or "application/json"

    request_object = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

    status = 0
    raw = ""
    try:
        with urllib.request.urlopen(
            request_object, timeout=timeout, context=_ssl_context(config)
        ) as response:
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            raw = error.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        parsed = _parse(raw)
        if parsed is None and raw.strip().startswith("<"):
            raise AzureDevOpsApiError(
                status,
                f"Azure DevOps returned HTML instead of JSON ({status}) for {url}. "
                "Check the organisation URL in the config file.",
                url,
            ) from None
        raise _describe_failure(status, parsed, url) from None
    except (socket.timeout, TimeoutError):
        raise AzureDevOpsApiError(
            0, f"Azure DevOps did not respond within {round(timeout)}s ({url}).", url
        ) from None
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise AzureDevOpsApiError(
                0, f"Azure DevOps did not respond within {round(timeout)}s ({url}).", url
            ) from None
        raise AzureDevOpsApiError(
            0, f"Could not reach Azure DevOps ({url}): {reason}", url
        ) from None
    except OSError as error:
        if isinstance(error, ssl.SSLCertVerificationError):
            raise AzureDevOpsApiError(
                0,
                f"TLS certificate verification failed for {config.org_url}: {error.verify_message or error}. "
                "For an on-premise server with a self-signed certificate, add "
                '"insecureTls": true to that org in the config file.',
                url,
            ) from None
        raise AzureDevOpsApiError(0, f"Could not reach Azure DevOps ({url}): {error}", url) from None

    if not raw:
        return None
    parsed = _parse(raw)
    if parsed is None:
        if raw.strip().startswith("<"):
            raise AzureDevOpsApiError(
                status,
                f"Azure DevOps returned HTML instead of JSON ({status}) for {url}. "
                "Check the organisation URL in the config file.",
                url,
            )
        return raw
    return parsed


def _parse(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# WIT -- work items, types, comments, revisions
# ---------------------------------------------------------------------------


def get_work_item(
    config: AzureDevOpsConfig, work_item_id: Any, *, expand: Optional[str] = None
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workitems/{_quote(work_item_id)}",
        {"$expand": expand, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def get_work_items(
    config: AzureDevOpsConfig, ids: Sequence[Any], *, fields: Optional[Sequence[str]] = None
) -> List[Dict[str, Any]]:
    if not ids:
        return []
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workitems",
        {"ids": list(ids), "fields": list(fields) if fields else None, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def query_by_wiql(
    config: AzureDevOpsConfig, query: str, *, top: Optional[int] = None
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/wiql",
        {"$top": top, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "POST", url, {"query": query}))


def get_work_item_types(config: AzureDevOpsConfig) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workitemtypes",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_comments(config: AzureDevOpsConfig, work_item_id: Any) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workItems/{_quote(work_item_id)}/comments",
        {"api-version": COMMENTS_API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def get_revisions(
    config: AzureDevOpsConfig, work_item_id: Any, *, top: Optional[int] = None
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workItems/{_quote(work_item_id)}/revisions",
        {"$top": top, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def create_work_item(
    config: AzureDevOpsConfig, work_item_type: str, patch: List[Dict[str, Any]]
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workitems/${_quote(work_item_type)}",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "POST", url, patch, content_type="application/json-patch+json"))


def update_work_item(
    config: AzureDevOpsConfig,
    work_item_id: Any,
    patch: List[Dict[str, Any]],
    *,
    api_version: str = API_VERSION,
) -> Dict[str, Any]:
    """PATCH a work item.

    ``json-patch+json`` is required; the default JSON content type makes Azure
    DevOps ignore the patch operations.
    """
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workitems/{_quote(work_item_id)}",
        {"api-version": api_version},
    )
    return _as_dict(request(config, "PATCH", url, patch, content_type="application/json-patch+json"))


def add_comment(config: AzureDevOpsConfig, work_item_id: Any, text: str) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/wit/workItems/{_quote(work_item_id)}/comments",
        {"api-version": COMMENTS_API_VERSION},
    )
    return _as_dict(request(config, "POST", url, {"text": text}))


# ---------------------------------------------------------------------------
# Core -- projects, teams, identity
# ---------------------------------------------------------------------------


def get_projects(config: AzureDevOpsConfig) -> List[Dict[str, Any]]:
    url = _build_url(f"{_org_url(config)}/_apis/projects", {"api-version": API_VERSION})
    return _unwrap(request(config, "GET", url))


def get_teams(config: AzureDevOpsConfig) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/_apis/projects/{_project(config)}/teams", {"api-version": API_VERSION}
    )
    return _unwrap(request(config, "GET", url))


def authenticated_user_id(config: AzureDevOpsConfig) -> str:
    """The identity id of whoever the credentials belong to.

    Needed for voting on a pull request and for arming auto-complete: both
    require a real identity id, not an empty placeholder.
    """
    key = f"{config.org_url}::{config.pat or ''}::{config.auth_method}"
    with _lock:
        cached = _identity_cache.get(key)
    if cached:
        return cached

    url = _build_url(
        f"{_org_url(config)}/_apis/connectionData", {"api-version": "7.1-preview.1"}
    )
    payload = _as_dict(request(config, "GET", url, timeout=PROBE_TIMEOUT_S))
    user = _as_dict(payload.get("authenticatedUser"))
    identity = str(user.get("id") or "")
    if identity:
        with _lock:
            _identity_cache[key] = identity
    return identity


# ---------------------------------------------------------------------------
# Work -- boards, iterations, capacity
# ---------------------------------------------------------------------------


def _team_base(config: AzureDevOpsConfig, team: str) -> str:
    return f"{_org_url(config)}/{_project(config)}/{_quote(team)}"


def get_boards(config: AzureDevOpsConfig, team: str) -> List[Dict[str, Any]]:
    url = _build_url(f"{_team_base(config, team)}/_apis/work/boards", {"api-version": API_VERSION})
    return _unwrap(request(config, "GET", url))


def get_board(config: AzureDevOpsConfig, team: str, board_id: str) -> Dict[str, Any]:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/boards/{_quote(board_id)}", {"api-version": API_VERSION}
    )
    return _as_dict(request(config, "GET", url))


def update_board_columns(
    config: AzureDevOpsConfig, team: str, board_id: str, columns: List[Dict[str, Any]]
) -> Any:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/boards/{_quote(board_id)}/columns",
        {"api-version": API_VERSION},
    )
    return request(config, "PUT", url, columns)


def get_team_iterations(
    config: AzureDevOpsConfig, team: str, timeframe: Optional[str] = None
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/teamsettings/iterations",
        {"$timeframe": timeframe, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def post_team_iteration(
    config: AzureDevOpsConfig, team: str, iteration_id: str
) -> Dict[str, Any]:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/teamsettings/iterations",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "POST", url, {"id": iteration_id}))


def delete_team_iteration(config: AzureDevOpsConfig, team: str, iteration_id: str) -> Any:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/teamsettings/iterations/{_quote(iteration_id)}",
        {"api-version": API_VERSION},
    )
    return request(config, "DELETE", url)


def get_iteration_work_items(
    config: AzureDevOpsConfig, team: str, iteration_id: str
) -> Dict[str, Any]:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/teamsettings/iterations/{_quote(iteration_id)}/workitems",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def get_capacities(config: AzureDevOpsConfig, team: str, iteration_id: str) -> Dict[str, Any]:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/teamsettings/iterations/{_quote(iteration_id)}/capacities",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def replace_capacities(
    config: AzureDevOpsConfig, team: str, iteration_id: str, capacities: List[Dict[str, Any]]
) -> Any:
    url = _build_url(
        f"{_team_base(config, team)}/_apis/work/teamsettings/iterations/{_quote(iteration_id)}/capacities",
        {"api-version": API_VERSION},
    )
    return request(config, "PUT", url, capacities)


# ---------------------------------------------------------------------------
# Git -- repositories, branches, pull requests, policies
# ---------------------------------------------------------------------------


def list_repositories(
    config: AzureDevOpsConfig, *, include_hidden: bool = False
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories",
        {"includeHidden": include_hidden or None, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_repository(config: AzureDevOpsConfig, repository_id: str) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def list_branches(config: AzureDevOpsConfig, repository_id: str) -> List[Dict[str, Any]]:
    """Branch stats: name, tip commit, ahead/behind counts."""
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}/stats/branches",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def _pr_collection_url(
    config: AzureDevOpsConfig, repository_id: Optional[str], *, by_project: bool = False
) -> str:
    if by_project or not repository_id:
        return f"{_org_url(config)}/{_project(config)}/_apis/git/pullrequests"
    return (
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/"
        f"{_quote(repository_id)}/pullrequests"
    )


def list_pull_requests(
    config: AzureDevOpsConfig,
    *,
    repository_id: Optional[str] = None,
    status: Optional[str] = None,
    source_ref_name: Optional[str] = None,
    target_ref_name: Optional[str] = None,
    top: Optional[int] = None,
) -> List[Dict[str, Any]]:
    url = _build_url(
        _pr_collection_url(config, repository_id, by_project=not repository_id),
        {
            "searchCriteria.status": status,
            "searchCriteria.sourceRefName": source_ref_name,
            "searchCriteria.targetRefName": target_ref_name,
            "$top": top,
            "api-version": API_VERSION,
        },
    )
    return _unwrap(request(config, "GET", url))


def get_pull_request(
    config: AzureDevOpsConfig, pull_request_id: Any, *, repository_id: Optional[str] = None
) -> Dict[str, Any]:
    if repository_id:
        base = (
            f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/"
            f"{_quote(repository_id)}/pullrequests/{_quote(pull_request_id)}"
        )
    else:
        base = (
            f"{_org_url(config)}/{_project(config)}/_apis/git/pullrequests/{_quote(pull_request_id)}"
        )
    return _as_dict(request(config, "GET", _build_url(base, {"api-version": API_VERSION})))


def get_pull_request_threads(
    config: AzureDevOpsConfig, repository_id: str, pull_request_id: Any
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}"
        f"/pullRequests/{_quote(pull_request_id)}/threads",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_pull_request_commits(
    config: AzureDevOpsConfig, repository_id: str, pull_request_id: Any
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}"
        f"/pullRequests/{_quote(pull_request_id)}/commits",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def create_pull_request(
    config: AzureDevOpsConfig, repository_id: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}/pullrequests",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "POST", url, body))


def update_pull_request(
    config: AzureDevOpsConfig, repository_id: str, pull_request_id: Any, patch: Dict[str, Any]
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}"
        f"/pullrequests/{_quote(pull_request_id)}",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "PATCH", url, patch))


def create_thread(
    config: AzureDevOpsConfig, repository_id: str, pull_request_id: Any, body: Dict[str, Any]
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}"
        f"/pullRequests/{_quote(pull_request_id)}/threads",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "POST", url, body))


def set_pull_request_reviewer_vote(
    config: AzureDevOpsConfig,
    repository_id: str,
    pull_request_id: Any,
    reviewer_id: str,
    vote: int,
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/git/repositories/{_quote(repository_id)}"
        f"/pullRequests/{_quote(pull_request_id)}/reviewers/{_quote(reviewer_id)}",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "PUT", url, {"vote": vote}))


def list_policies(config: AzureDevOpsConfig, scope: Optional[str] = None) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/policy/configurations",
        {"scope": scope, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_policy_evaluations(config: AzureDevOpsConfig, artifact_id: str) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/policy/evaluations",
        {"artifactId": artifact_id, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


# ---------------------------------------------------------------------------
# Pipelines and builds
# ---------------------------------------------------------------------------


def list_pipelines(config: AzureDevOpsConfig, *, top: Optional[int] = None) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/pipelines",
        {"$top": top, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_pipeline(
    config: AzureDevOpsConfig, pipeline_id: Any, version: Optional[int] = None
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/pipelines/{_quote(pipeline_id)}",
        {"pipelineVersion": version, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def get_run(config: AzureDevOpsConfig, pipeline_id: Any, run_id: Any) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/pipelines/{_quote(pipeline_id)}/runs/{_quote(run_id)}",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def run_pipeline(
    config: AzureDevOpsConfig, pipeline_id: Any, body: Dict[str, Any], version: Optional[int] = None
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/pipelines/{_quote(pipeline_id)}/runs",
        {"pipelineVersion": version, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "POST", url, body))


def list_builds(
    config: AzureDevOpsConfig,
    *,
    definitions: Optional[Sequence[Any]] = None,
    status: Optional[str] = None,
    result: Optional[str] = None,
    branch_name: Optional[str] = None,
    top: Optional[int] = None,
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/build/builds",
        {
            "definitions": list(definitions) if definitions else None,
            "statusFilter": status,
            "resultFilter": result,
            "branchName": branch_name,
            "$top": top,
            "api-version": API_VERSION,
        },
    )
    return _unwrap(request(config, "GET", url))


def get_build_artifacts(config: AzureDevOpsConfig, build_id: Any) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/build/builds/{_quote(build_id)}/artifacts",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_build_logs(config: AzureDevOpsConfig, build_id: Any) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/build/builds/{_quote(build_id)}/logs",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_build_timeline(config: AzureDevOpsConfig, build_id: Any) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/build/builds/{_quote(build_id)}/timeline",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def update_build(
    config: AzureDevOpsConfig, build_id: Any, patch: Dict[str, Any], *, retry: bool = False
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/build/builds/{_quote(build_id)}",
        {"retry": retry or None, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "PATCH", url, patch))


# ---------------------------------------------------------------------------
# Test plans (testplan area) and test results (test area)
# ---------------------------------------------------------------------------


def list_test_plans(
    config: AzureDevOpsConfig,
    *,
    owner: Optional[str] = None,
    filter_active: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/testplan/plans",
        {"owner": owner, "filterActivePlans": filter_active, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_test_plan(config: AzureDevOpsConfig, plan_id: Any) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/testplan/plans/{_quote(plan_id)}",
        {"api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def list_test_suites(
    config: AzureDevOpsConfig, plan_id: Any, *, expand: Optional[int] = None
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/testplan/Plans/{_quote(plan_id)}/Suites",
        {"expand": expand, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def get_test_suite(
    config: AzureDevOpsConfig, plan_id: Any, suite_id: Any, *, expand: Optional[int] = None
) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/testplan/Plans/{_quote(plan_id)}"
        f"/Suites/{_quote(suite_id)}",
        {"expand": expand, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def list_test_cases(
    config: AzureDevOpsConfig, plan_id: Any, suite_id: Any
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/testplan/Plans/{_quote(plan_id)}"
        f"/Suites/{_quote(suite_id)}/TestCase",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def list_test_points(
    config: AzureDevOpsConfig,
    plan_id: Any,
    suite_id: Any,
    *,
    test_case_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    # The route really is singular ("TestPoint"); "Points" answers 404.
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/testplan/Plans/{_quote(plan_id)}"
        f"/Suites/{_quote(suite_id)}/TestPoint",
        {"testCaseId": test_case_id, "api-version": API_VERSION},
    )
    return _unwrap(request(config, "GET", url))


def list_test_runs(
    config: AzureDevOpsConfig,
    *,
    plan_id: Optional[Any] = None,
    build_uri: Optional[str] = None,
    owner: Optional[str] = None,
    top: Optional[int] = None,
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/test/runs",
        {
            "planId": plan_id,
            "buildUri": build_uri,
            "owner": owner,
            "includeRunDetails": True,
            "$top": top,
            "api-version": API_VERSION,
        },
    )
    return _unwrap(request(config, "GET", url))


def get_test_run(config: AzureDevOpsConfig, run_id: Any) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/test/runs/{_quote(run_id)}",
        {"includeDetails": True, "api-version": API_VERSION},
    )
    return _as_dict(request(config, "GET", url))


def create_test_run(config: AzureDevOpsConfig, body: Dict[str, Any]) -> Dict[str, Any]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/test/runs", {"api-version": API_VERSION}
    )
    return _as_dict(request(config, "POST", url, body))


def update_test_results(
    config: AzureDevOpsConfig, run_id: Any, results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    url = _build_url(
        f"{_org_url(config)}/{_project(config)}/_apis/test/Runs/{_quote(run_id)}/results",
        {"api-version": API_VERSION},
    )
    return _unwrap(request(config, "PATCH", url, results))


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------


def probe_connection(config: AzureDevOpsConfig) -> List[Dict[str, Any]]:
    """Cheap authenticated call that proves URL, credentials and project work."""
    return get_work_item_types(config)
