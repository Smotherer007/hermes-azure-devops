"""Pure formatting: Azure DevOps payloads -> the text the model reads.

A direct port of pi-azure-devops' ``src/utils/formatting.ts``. Every function
takes the parsed JSON (exactly what the REST client returns) and returns a
string; none of them touch the network, the config or the file system.

Wording, emoji and spacing are kept identical to the pi extension on purpose:
the bundled skills, the prompts and the agent's own memory refer to this
output, so a different rendering would be a silent regression.

Timestamps are rendered in UTC, matching JavaScript's ``toISOString()``.
Numbers used as object keys (``status``, ``result``, ``timeFrame``) arrive as
JSON numbers and are looked up through the same numeric-then-lowercase-string
fallback the TypeScript code uses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, *path: str, default: Any = None) -> Any:
    """Walk a nested dict, tolerating anything that is not a dict on the way."""
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _parse_time(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # JavaScript Date accepts epoch milliseconds.
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date(value: Any) -> str:
    """``YYYY-MM-DD`` in UTC, or "" when unparseable."""
    parsed = _parse_time(value)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def _datetime(value: Any) -> str:
    """``YYYY-MM-DD HH:MM:SS`` in UTC, or "" when unparseable."""
    parsed = _parse_time(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


def format_iso_datetime(value: Any) -> str:
    """Public wrapper around :func:`_datetime` for callers outside this module."""
    return _datetime(value)


def format_iso_date(value: Any) -> str:
    """Public wrapper around :func:`_date` for callers outside this module."""
    return _date(value)


def _field(value: Any) -> str:
    """Field values are often ``{displayName, ...}``; render the readable part."""
    if value is None:
        return "(empty)"
    if isinstance(value, dict) and "displayName" in value:
        return str(value["displayName"])
    return str(value)


def _entries(mapping: Optional[Dict[str, Any]]) -> List[tuple]:
    return list(mapping.items()) if isinstance(mapping, dict) else []


def _ordered(mapping: Dict[str, Any], value: Any, default: str = "") -> str:
    """Numeric-key lookup, then lowercase-string lookup, mirroring TS."""
    text = "None" if value is None else str(value)
    if text in mapping:
        return mapping[text]
    lowered = text.lower()
    if lowered in mapping:
        return mapping[lowered]
    return default


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------


def format_work_item(work_item: Dict[str, Any]) -> str:
    fields = work_item.get("fields") or {}
    lines: List[str] = []

    lines.append(f"# Work Item {work_item.get('id')}: {fields.get('System.Title') or '(untitled)'}")
    lines.append(f"- **Type:** {fields.get('System.WorkItemType') or 'Unknown'}")
    lines.append(f"- **State:** {fields.get('System.State') or 'Unknown'}")
    lines.append(f"- **Reason:** {fields.get('System.Reason') or ''}")

    assigned = fields.get("System.AssignedTo")
    if isinstance(assigned, dict) and "displayName" in assigned:
        lines.append(f"- **Assigned To:** {assigned['displayName']}")
    elif assigned:
        lines.append(f"- **Assigned To:** {assigned}")
    else:
        lines.append("- **Assigned To:** (unassigned)")

    if fields.get("System.AreaPath"):
        lines.append(f"- **Area Path:** {fields['System.AreaPath']}")
    if fields.get("System.IterationPath"):
        lines.append(f"- **Iteration Path:** {fields['System.IterationPath']}")
    if fields.get("System.Priority"):
        lines.append(f"- **Priority:** {fields['System.Priority']}")
    if fields.get("Microsoft.VSTS.Common.Severity"):
        lines.append(f"- **Severity:** {fields['Microsoft.VSTS.Common.Severity']}")

    if fields.get("System.Description"):
        lines.append("")
        lines.append("## Description")
        lines.append(str(fields["System.Description"]))

    if fields.get("System.Tags"):
        lines.append("")
        lines.append(f"**Tags:** {fields['System.Tags']}")

    if work_item.get("url"):
        lines.append("")
        lines.append(f"**URL:** {work_item['url']}")

    return "\n".join(lines)


def format_work_item_summary(work_item: Dict[str, Any]) -> str:
    fields = work_item.get("fields") or {}
    work_item_type = fields.get("System.WorkItemType") or "?"
    state = fields.get("System.State") or "?"
    title = fields.get("System.Title") or "(untitled)"
    return f"#{work_item.get('id')} [{work_item_type}] [{state}] {title}"


def format_work_item_list(work_items: Sequence) -> str:
    if not work_items:
        return "No work items found."
    return "\n".join(format_work_item_summary(item) for item in work_items)


def format_work_item_type(work_item_type: Dict[str, Any]) -> str:
    lines = [f"**{work_item_type.get('name')}** ({work_item_type.get('referenceName')})"]
    if work_item_type.get("description"):
        lines.append(f"  {work_item_type['description']}")
    states = work_item_type.get("states") or []
    if states:
        lines.append("  States: " + ", ".join(str((s or {}).get("name") or "") for s in states))
    return "\n".join(lines)


def format_work_item_type_list(types: Sequence) -> str:
    if not types:
        return "No work item types found."
    return "\n".join(format_work_item_type(item) for item in types)


def format_comments(comment_list: Dict[str, Any]) -> str:
    comments = (comment_list or {}).get("comments") or []
    if not comments:
        return "No comments."

    lines: List[str] = []
    for comment in comments:
        author = _get(comment, "createdBy", "displayName") or "Unknown"
        date = _date(comment.get("createdDate"))
        lines.append(f"**{author}** ({date}):")
        lines.append(comment.get("text") or "(empty)")
        lines.append("")
    return "\n".join(lines)


def format_revisions(revisions: Sequence) -> str:
    if not revisions:
        return "No revisions found."

    lines: List[str] = []
    for revision in revisions:
        fields = revision.get("fields") or {}
        rev = revision.get("rev")
        rev_label = rev if rev is not None else "?"
        changed_by = fields.get("System.ChangedBy")
        if isinstance(changed_by, dict) and "displayName" in changed_by:
            author = str(changed_by["displayName"])
        else:
            author = str(changed_by) if changed_by is not None else "Unknown"
        changed_date = _datetime(fields.get("System.ChangedDate")) if fields.get("System.ChangedDate") else ""

        lines.append(f"## Rev {rev_label} — {author} ({changed_date})")
        for key, value in _entries(fields):
            if key.startswith("System.") or key.startswith("Microsoft.VSTS."):
                lines.append(f"  {key}: {_field(value)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


def format_team(team: Dict[str, Any]) -> str:
    lines = [f"**{team.get('name') or 'Unknown'}** (id: {team.get('id') or '?'})"]
    if team.get("description"):
        lines.append(f"  {team['description']}")
    if team.get("url"):
        lines.append(f"  URL: {team['url']}")
    return "\n".join(lines)


def format_team_list(teams: Sequence) -> str:
    if not teams:
        return "No teams found."
    return "\n".join(format_team(team) for team in teams)


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

COLUMN_TYPE_NAMES = {0: "Incoming", 1: "InProgress", 2: "Outgoing"}


def format_board_ref(board: Dict[str, Any]) -> str:
    suffix = f" — {board['url']}" if board.get("url") else ""
    return f"**{board.get('name') or 'Unknown'}** (id: {board.get('id') or '?'}){suffix}"


def format_board_list(boards: Sequence) -> str:
    if not boards:
        return "No boards found."
    return "\n".join(format_board_ref(board) for board in boards)


def format_board(board: Dict[str, Any]) -> str:
    lines = [f"# Board: {board.get('name') or 'Unknown'} (id: {board.get('id') or '?'})"]
    if board.get("canEdit") is not None:
        lines.append(f"- **Editable:** {'Yes' if board['canEdit'] else 'No'}")

    columns = board.get("columns") or []
    if columns:
        lines.append("")
        lines.append("## Columns")
        for column in columns:
            column_type = column.get("columnType")
            type_label = COLUMN_TYPE_NAMES.get(column_type, "Unknown") if column_type is not None else "Unknown"
            limit = column.get("itemLimit")
            limit_str = f" (limit: {limit})" if limit is not None else ""
            lines.append(f"- **{column.get('name') or '?'}** [{type_label}]{limit_str}")
            mappings = column.get("stateMappings")
            if mappings:
                rendered = ", ".join(f"{key} → {value}" for key, value in _entries(mappings))
                lines.append(f"  Mappings: {rendered}")

    rows = board.get("rows") or []
    if rows:
        lines.append("")
        lines.append(f"## Rows ({len(rows)})")
        for row in rows:
            lines.append(f"- {row.get('name') or '(default)'}")

    if board.get("url"):
        lines.append("")
        lines.append(f"**URL:** {board['url']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Iterations
# ---------------------------------------------------------------------------

TIMEFRAME_LABELS = {
    "0": "⚪ Past",
    "1": "🔵 Current",
    "2": "🟢 Future",
    "past": "⚪ Past",
    "current": "🔵 Current",
    "future": "🟢 Future",
}


def format_iteration(iteration: Dict[str, Any]) -> str:
    attributes = iteration.get("attributes") or {}
    raw_timeframe = attributes.get("timeFrame")
    timeframe = "" if raw_timeframe is None or raw_timeframe == "" else str(raw_timeframe)
    timeframe_label = _ordered(TIMEFRAME_LABELS, timeframe) if timeframe else ""
    start = _date(attributes.get("startDate")) if attributes.get("startDate") else "?"
    end = _date(attributes.get("finishDate")) if attributes.get("finishDate") else "?"

    lines = [
        f"**{iteration.get('name') or 'Unknown'}** (id: {iteration.get('id') or '?'}) {timeframe_label}",
        f"  {start} → {end}",
    ]
    if iteration.get("path"):
        lines.append(f"  Path: {iteration['path']}")
    return "\n".join(lines)


def format_iteration_list(iterations: Sequence) -> str:
    if not iterations:
        return "No iterations found."
    return "\n".join(format_iteration(iteration) for iteration in iterations)


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------


def format_capacity(capacity: Dict[str, Any]) -> str:
    members = (capacity or {}).get("teamMembers") or []
    lines = [
        "# Team Capacity",
        f"- **Total capacity:** {capacity.get('totalCapacityPerDay') or 0} hours/day",
        f"- **Total days off:** {capacity.get('totalDaysOff') or 0}",
    ]

    if members:
        lines.append("")
        lines.append("## Team Members")
        for member in members:
            name = _get(member, "teamMember", "displayName") or "Unknown"
            activities = member.get("activities") or []
            activity_str = ", ".join(
                f"{(a or {}).get('name') or '?'}: {(a or {}).get('capacityPerDay') or 0}h/day"
                for a in activities
            )
            days_off = member.get("daysOff") or []
            if days_off:
                rendered = []
                for entry in days_off:
                    start = _date((entry or {}).get("start")) if (entry or {}).get("start") else "?"
                    end = _date((entry or {}).get("end")) if (entry or {}).get("end") else "?"
                    rendered.append(start if start == end else f"{start}–{end}")
                off_str = ", ".join(rendered)
            else:
                off_str = "none"

            lines.append(f"- **{name}**: {activity_str or 'no activities'}")
            lines.append(f"  Days off: {off_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Repositories and branches
# ---------------------------------------------------------------------------


def format_bytes(size: float) -> str:
    if size < 1024:
        return f"{int(size)} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def format_repo(repo: Dict[str, Any]) -> str:
    lines = [f"**{repo.get('name') or 'Unknown'}** (id: {repo.get('id') or '?'})"]
    if repo.get("defaultBranch"):
        lines.append(f"- **Default branch:** {str(repo['defaultBranch']).replace('refs/heads/', '')}")
    if repo.get("size") is not None:
        lines.append(f"- **Size:** {format_bytes(repo['size'])}")
    if _get(repo, "project", "name"):
        lines.append(f"- **Project:** {_get(repo, 'project', 'name')}")
    if repo.get("url"):
        lines.append(f"- **URL:** {repo['url']}")
    return "\n".join(lines)


def format_repo_list(repos: Sequence) -> str:
    if not repos:
        return "No repositories found."
    return "\n".join(format_repo(repo) for repo in repos)


def format_branch(branch: Dict[str, Any]) -> str:
    commit_id = _get(branch, "commit", "commitId") or ""
    sha = str(commit_id)[:7] if commit_id else "?"
    comment = _get(branch, "commit", "comment") or ""
    message = str(comment).split("\n")[0]
    ahead = branch.get("aheadCount") or 0
    behind = branch.get("behindCount") or 0
    badge = " (base)" if branch.get("isBaseVersion") else ""
    tracking = f" ↑{ahead} ↓{behind}" if ahead > 0 or behind > 0 else ""

    lines = [f"**{branch.get('name') or '?'}**{badge} `{sha}`{tracking}"]
    if message:
        lines.append(f"  {message}")
    return "\n".join(lines)


def format_branch_list(branches: Sequence) -> str:
    if not branches:
        return "No branches found."
    return "\n".join(format_branch(branch) for branch in branches)


# ---------------------------------------------------------------------------
# Pull requests
# ---------------------------------------------------------------------------

PR_STATUS_LABELS = {
    "0": "Not Set",
    "1": "🟢 Active",
    "2": "⚪ Abandoned",
    "3": "✅ Completed",
    "active": "🟢 Active",
    "completed": "✅ Completed",
    "abandoned": "⚪ Abandoned",
}

PR_VOTE_LABELS = {
    10: "Approved",
    5: "Approved with suggestions",
    0: "No vote",
    -5: "Waiting for author",
    -10: "Rejected",
}


def _normalize_pr_status(status: Any) -> str:
    return _ordered(PR_STATUS_LABELS, status) or str(status if status is not None else "Unknown")


def _short_ref(ref_name: Optional[str]) -> str:
    if not ref_name:
        return "?"
    return str(ref_name).replace("refs/heads/", "")


def format_pull_request(pull_request: Dict[str, Any]) -> str:
    lines = [
        f"# PR #{pull_request.get('pullRequestId') or '?'}: {pull_request.get('title') or '(untitled)'}",
        f"- **Status:** {_normalize_pr_status(pull_request.get('status'))}",
        f"- **Branch:** {_short_ref(pull_request.get('sourceRefName'))} → {_short_ref(pull_request.get('targetRefName'))}",
        f"- **Author:** {_get(pull_request, 'createdBy', 'displayName') or 'Unknown'}",
    ]

    if pull_request.get("creationDate"):
        lines.append(f"- **Created:** {_date(pull_request['creationDate'])}")

    reviewers = pull_request.get("reviewers") or []
    if reviewers:
        rendered = ", ".join(
            f"{(r or {}).get('displayName') or '?'} ({PR_VOTE_LABELS.get((r or {}).get('vote') or 0, '?')})"
            for r in reviewers
        )
        lines.append(f"- **Reviewers:** {rendered}")

    if pull_request.get("description"):
        lines.append("")
        lines.append("## Description")
        lines.append(str(pull_request["description"]))

    if pull_request.get("url"):
        lines.append("")
        lines.append(f"**URL:** {pull_request['url']}")

    return "\n".join(lines)


def format_pull_request_list(pull_requests: Sequence) -> str:
    if not pull_requests:
        return "No pull requests found."

    lines: List[str] = []
    for pull_request in pull_requests:
        status = _normalize_pr_status(pull_request.get("status"))
        source = _short_ref(pull_request.get("sourceRefName"))
        target = _short_ref(pull_request.get("targetRefName"))
        author = _get(pull_request, "createdBy", "displayName") or "?"
        date = _date(pull_request.get("creationDate")) if pull_request.get("creationDate") else "?"
        lines.append(
            f"#{pull_request.get('pullRequestId') or '?'} {status} — "
            f"{pull_request.get('title') or '?'} ({source}→{target}) by {author} [{date}]"
        )
    return "\n".join(lines)


THREAD_STATUS_LABELS = {
    0: "Unknown",
    1: "Active",
    2: "Fixed",
    3: "Won't Fix",
    4: "Closed",
    5: "By Design",
    6: "Pending",
}


def format_pull_request_thread(thread: Dict[str, Any]) -> str:
    status = THREAD_STATUS_LABELS.get(thread.get("status") or 0, "Unknown")
    lines = [f"### Thread #{thread.get('id') or '?'} [{status}]"]

    for comment in thread.get("comments") or []:
        author = _get(comment, "author", "displayName") or "Unknown"
        date = _date((comment or {}).get("publishedDate")) if (comment or {}).get("publishedDate") else ""
        lines.append(f"**{author}** ({date}):")
        lines.append((comment or {}).get("content") or "(empty)")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commits
# ---------------------------------------------------------------------------


def format_commit(commit: Dict[str, Any]) -> str:
    commit_id = commit.get("commitId") or ""
    sha = str(commit_id)[:7] if commit_id else "?"
    author = _get(commit, "author", "name") or "Unknown"
    date = _date(_get(commit, "author", "date")) if _get(commit, "author", "date") else ""
    comment = commit.get("comment") or ""
    message = str(comment).split("\n")[0]
    return f"`{sha}` {message} — {author} [{date}]"


def format_commit_list(commits: Sequence) -> str:
    if not commits:
        return "No commits found."
    return "\n".join(format_commit(commit) for commit in commits)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def format_policy(policy: Dict[str, Any]) -> str:
    type_name = _get(policy, "type", "displayName") or "Unknown"
    blocking = "🔒 Blocking" if policy.get("isBlocking") else "⚠️ Non-blocking"
    lines = [f"**{type_name}** (id: {policy.get('id') or '?'}) {blocking}"]

    scope = policy.get("scope") or []
    if scope:
        rendered = ", ".join(
            (entry or {}).get("refName", "?").replace("refs/heads/", "")
            if (entry or {}).get("refName")
            else "?"
            for entry in scope
        )
        lines.append(f"  Scope: {rendered}")

    if policy.get("settings"):
        settings = ", ".join(
            f"{key}={json.dumps(value, separators=(',', ':'))}"
            for key, value in _entries(policy["settings"])
        )
        lines.append(f"  Settings: {settings}")

    return "\n".join(lines)


EVAL_STATUS_ICONS = {
    "approved": "✅ Approved",
    "running": "⏳ Running",
    "rejected": "❌ Rejected",
    "queued": "📋 Queued",
    "notApplicable": "➖ Not applicable",
}


def format_policy_evaluation(evaluation: Dict[str, Any]) -> str:
    status = EVAL_STATUS_ICONS.get(
        evaluation.get("status") or "", evaluation.get("status") or "?"
    )
    started = _date(evaluation.get("startedDate")) if evaluation.get("startedDate") else "?"
    completed = _date(evaluation.get("completedDate")) if evaluation.get("completedDate") else "—"
    suffix = f" → {completed}" if completed != "—" else ""
    return f"**{evaluation.get('policyDisplayName') or '?'}**: {status} ({started}{suffix})"


# ---------------------------------------------------------------------------
# Pipelines and runs
# ---------------------------------------------------------------------------

RUN_STATE_ICONS = {
    "0": "❓ Unknown",
    "1": "⏳ In Progress",
    "2": "❌ Canceling",
    "4": "✅ Completed",
    "completed": "✅ Completed",
    "inProgress": "⏳ In Progress",
    "cancelling": "❌ Canceling",
}

RUN_RESULT_LABELS = {
    "0": "unknown",
    "1": "✅ succeeded",
    "2": "🔴 failed",
    "4": "⚪ canceled",
    "succeeded": "✅ succeeded",
    "failed": "🔴 failed",
    "canceled": "⚪ canceled",
    "partiallySucceeded": "⚠️ partially succeeded",
}


def _normalize_run_state(state: Any) -> str:
    found = _ordered(RUN_STATE_ICONS, state)
    if found:
        return found
    return f"⏸️ {state}"


def _normalize_run_result(result: Any) -> str:
    return _ordered(RUN_RESULT_LABELS, result)


def format_pipeline(pipeline: Dict[str, Any]) -> str:
    lines = [f"**{pipeline.get('name') or 'Unknown'}** (id: {pipeline.get('id') or '?'})"]
    if pipeline.get("folder"):
        lines.append(f"- **Folder:** {pipeline['folder']}")
    configuration = pipeline.get("configuration")
    if configuration:
        lines.append(f"- **Type:** {configuration.get('type') or '?'}")
        if configuration.get("path"):
            lines.append(f"- **Path:** {configuration['path']}")
        if _get(configuration, "repository", "name"):
            lines.append(f"- **Repository:** {_get(configuration, 'repository', 'name')}")
    if pipeline.get("url"):
        lines.append(f"- **URL:** {pipeline['url']}")
    return "\n".join(lines)


def format_pipeline_list(pipelines: Sequence) -> str:
    if not pipelines:
        return "No pipelines found."
    return "\n".join(format_pipeline(pipeline) for pipeline in pipelines)


def format_duration(created_date: Any, finished_date: Any = None) -> str:
    """Human duration. A run that has not finished is measured against now."""
    start = _parse_time(created_date)
    if start is None:
        return "?"
    end = _parse_time(finished_date) if finished_date else datetime.now(timezone.utc)
    if end is None:
        end = datetime.now(timezone.utc)
    diff_ms = (end - start).total_seconds() * 1000
    if diff_ms < 0:
        return "?"
    seconds = int(diff_ms // 1000)
    minutes = seconds // 60
    hours = minutes // 60
    if hours > 0:
        return f"{hours}h {minutes % 60}m"
    if minutes > 0:
        return f"{minutes}m {seconds % 60}s"
    return f"{seconds}s"


def format_run(run: Dict[str, Any]) -> str:
    state = _normalize_run_state(run.get("state"))
    result = _normalize_run_result(run.get("result")) if run.get("result") else ""
    pipeline_name = _get(run, "pipeline", "name") or "?"
    ref_name = _get(run, "resources", "repositories", "self", "refName") or "?"
    branch = str(ref_name).replace("refs/heads/", "")
    duration = format_duration(run.get("createdDate"), run.get("finishedDate"))

    lines = [
        f"# Run #{run.get('id') or '?'} — {pipeline_name}",
        f"- **State:** {state}",
    ]
    if result:
        lines.append(f"- **Result:** {result}")
    lines.append(f"- **Branch:** {branch}")
    lines.append(f"- **Duration:** {duration}")

    if run.get("createdDate"):
        lines.append(f"- **Started:** {_datetime(run['createdDate'])}")
    if run.get("finishedDate"):
        lines.append(f"- **Finished:** {_datetime(run['finishedDate'])}")

    parameters = run.get("templateParameters") or {}
    if parameters:
        rendered = ", ".join(f"{key}={value}" for key, value in _entries(parameters))
        lines.append(f"- **Parameters:** {rendered}")

    if run.get("url"):
        lines.append(f"- **URL:** {run['url']}")
    return "\n".join(lines)


def format_run_list(runs: Sequence) -> str:
    if not runs:
        return "No runs found."

    lines: List[str] = []
    for run in runs:
        state = _normalize_run_state(run.get("state"))
        result = _normalize_run_result(run.get("result")) if run.get("result") else ""
        pipeline_name = _get(run, "pipeline", "name") or "?"
        ref_name = _get(run, "resources", "repositories", "self", "refName") or "?"
        branch = str(ref_name).replace("refs/heads/", "")
        duration = format_duration(run.get("createdDate"), run.get("finishedDate"))
        status = f"{state} {result}" if result else state
        lines.append(f"#{run.get('id') or '?'} {pipeline_name} — {status} — {branch} ({duration})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Artifacts and timeline
# ---------------------------------------------------------------------------


def format_artifact(artifact: Dict[str, Any]) -> str:
    lines = [f"**{artifact.get('name') or 'Unknown'}** (id: {artifact.get('id') or '?'})"]
    resource = artifact.get("resource") or {}
    if resource.get("type"):
        lines.append(f"- **Type:** {resource['type']}")
    if resource.get("data"):
        lines.append(f"- **Data:** {resource['data']}")
    if resource.get("url"):
        lines.append(f"- **URL:** {resource['url']}")
    return "\n".join(lines)


def format_artifact_list(artifacts: Sequence) -> str:
    if not artifacts:
        return "No artifacts found."
    return "\n".join(format_artifact(artifact) for artifact in artifacts)


TIMELINE_STATE_ICONS = {
    "0": "⏸️ Pending",
    "1": "⏳ In Progress",
    "2": "✅ Completed",
    "completed": "✅",
    "inProgress": "⏳",
    "pending": "⏸️",
}

TIMELINE_RESULT_ICONS = {
    "0": "🟢 Succeeded",
    "1": "⚠️ Succeeded with issues",
    "2": "🔴 Failed",
    "3": "⚪ Canceled",
    "4": "⏭️ Skipped",
    "5": "⚪ Abandoned",
    "succeeded": "🟢",
    "failed": "🔴",
    "canceled": "⚪",
    "skipped": "⏭️",
    "abandoned": "⚪",
}


def _normalize_timeline_state(state: Any) -> str:
    return _ordered(TIMELINE_STATE_ICONS, state, "⏸️")


def _normalize_timeline_result(result: Any) -> str:
    return _ordered(TIMELINE_RESULT_ICONS, result)


def format_timeline_record(record: Dict[str, Any]) -> str:
    state_icon = _normalize_timeline_state(record.get("state"))
    result_icon = _normalize_timeline_result(record.get("result")) if record.get("result") else ""
    icon = result_icon or state_icon
    duration = format_duration(record.get("startTime"), record.get("finishTime"))

    issues: List[str] = []
    if (record.get("errorCount") or 0) > 0:
        issues.append(f"{record['errorCount']} error(s)")
    if (record.get("warningCount") or 0) > 0:
        issues.append(f"{record['warningCount']} warning(s)")
    issue_str = f" — {', '.join(issues)}" if issues else ""

    return f"{icon} **{record.get('name') or '?'}** [{record.get('type') or '?'}] ({duration}){issue_str}"


def format_timeline(timeline: Dict[str, Any]) -> str:
    records = (timeline or {}).get("records") or []
    if not records:
        return "No timeline records."

    ordered = sorted(records, key=lambda record: record.get("order") or 0)
    lines: List[str] = []
    for record in ordered:
        if record.get("parentId"):
            indent = "    " if record.get("type") == "Task" else "  "
        else:
            indent = ""
        lines.append(f"{indent}{format_timeline_record(record)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test plans, suites, cases, points
# ---------------------------------------------------------------------------

TEST_OUTCOME_ICONS = {
    "passed": "🟢",
    "failed": "🔴",
    "blocked": "🚫",
    "notExecuted": "⏸️",
    "inconclusive": "❓",
    "timeout": "⏱️",
    "aborted": "⚪",
    "notApplicable": "➖",
    "warning": "⚠️",
    "error": "💥",
    "paused": "⏸️",
    "inProgress": "⏳",
    "notImpacted": "➖",
}

TEST_RUN_STATE_ICONS = {
    "InProgress": "⏳",
    "Completed": "✅",
    "Aborted": "⚪",
    "Waiting": "⏸️",
    "NeedsInvestigation": "🔍",
    "NotStarted": "⏸️",
}

SUITE_TYPE_LABELS = {
    "staticTestSuite": "Static",
    "dynamicTestSuite": "Dynamic (query-based)",
    "requirementTestSuite": "Requirement-based",
}


def format_test_plan(plan: Dict[str, Any]) -> str:
    lines = [
        f"**{plan.get('name') or 'Unknown'}** (id: {plan.get('id') or '?'})",
        f"- **State:** {plan.get('state') or 'unknown'}",
    ]
    if plan.get("iteration"):
        lines.append(f"- **Iteration:** {plan['iteration']}")
    if plan.get("startDate"):
        lines.append(f"- **Start:** {_date(plan['startDate'])}")
    if plan.get("endDate"):
        lines.append(f"- **End:** {_date(plan['endDate'])}")
    if _get(plan, "owner", "displayName"):
        lines.append(f"- **Owner:** {_get(plan, 'owner', 'displayName')}")
    if plan.get("rootSuite"):
        root = plan["rootSuite"]
        lines.append(f"- **Root Suite:** #{root.get('id')} {root.get('name') or ''}")
    if plan.get("areaPath"):
        lines.append(f"- **Area:** {plan['areaPath']}")
    if plan.get("url"):
        lines.append(f"- **URL:** {plan['url']}")
    return "\n".join(lines)


def format_test_plan_list(plans: Sequence) -> str:
    if not plans:
        return "No test plans found."
    return "\n".join(format_test_plan(plan) for plan in plans)


def format_test_suite(suite: Dict[str, Any]) -> str:
    type_label = SUITE_TYPE_LABELS.get(suite.get("suiteType") or "", suite.get("suiteType") or "unknown")
    lines = [
        f"**{suite.get('name') or 'Unknown'}** (id: {suite.get('id') or '?'})",
        f"- **Type:** {type_label}",
    ]
    if suite.get("parentSuite"):
        parent = suite["parentSuite"]
        lines.append(f"- **Parent:** #{parent.get('id')} {parent.get('name') or ''}")
    children = suite.get("children")
    if isinstance(children, list) and children:
        lines.append(f"- **Children:** {len(children)}")
    if suite.get("testCaseCount") is not None:
        lines.append(f"- **Test Cases:** {suite['testCaseCount']}")
    if suite.get("requirementId"):
        lines.append(f"- **Requirement:** #{suite['requirementId']}")
    if suite.get("url"):
        lines.append(f"- **URL:** {suite['url']}")
    return "\n".join(lines)


def format_test_suite_list(suites: Sequence) -> str:
    if not suites:
        return "No test suites found."

    lines: List[str] = []
    for suite in suites:
        type_label = SUITE_TYPE_LABELS.get(suite.get("suiteType") or "", suite.get("suiteType") or "?")
        indent = "  " if suite.get("parentSuite") else ""
        case_count = f" ({suite['testCaseCount']} cases)" if suite.get("testCaseCount") is not None else ""
        lines.append(f"{indent}#{suite.get('id') or '?'} {suite.get('name') or '?'}{case_count} [{type_label}]")
    return "\n".join(lines)


def _case_fields(test_case: Dict[str, Any]) -> Dict[str, Any]:
    work_item = (test_case or {}).get("workItem") or {}
    fields = work_item.get("workItemFields")
    if isinstance(fields, list) and fields:
        first = fields[0]
        return first if isinstance(first, dict) else {}
    return {}


def format_test_case(test_case: Dict[str, Any]) -> str:
    work_item = test_case.get("workItem") or {}
    lines = [f"**{work_item.get('name') or 'Unknown'}** (id: {work_item.get('id') or '?'})"]
    fields = _case_fields(test_case)
    if fields.get("System.State"):
        lines.append(f"- **State:** {fields['System.State']}")
    if fields.get("System.AssignedTo"):
        lines.append(f"- **Assigned To:** {fields['System.AssignedTo']}")
    if fields.get("Microsoft.VSTS.Common.Priority"):
        lines.append(f"- **Priority:** {fields['Microsoft.VSTS.Common.Priority']}")
    if test_case.get("order") is not None:
        lines.append(f"- **Order:** {test_case['order']}")
    configurations = test_case.get("pointAssignments") or []
    if configurations:
        rendered = ", ".join(
            (c or {}).get("configurationName") or f"#{(c or {}).get('configurationId')}"
            for c in configurations
        )
        lines.append(f"- **Configurations:** {rendered}")
    return "\n".join(lines)


def format_test_case_list(test_cases: Sequence) -> str:
    if not test_cases:
        return "No test cases found."

    lines: List[str] = []
    for test_case in test_cases:
        work_item = test_case.get("workItem") or {}
        fields = _case_fields(test_case)
        state = f" [{fields['System.State']}]" if fields.get("System.State") else ""
        assignee = f" → {fields['System.AssignedTo']}" if fields.get("System.AssignedTo") else ""
        lines.append(f"#{work_item.get('id') or '?'} {work_item.get('name') or '?'}{state}{assignee}")
    return "\n".join(lines)


def format_test_point(point: Dict[str, Any]) -> str:
    # Azure DevOps omits ``outcome`` entirely until a point has been executed,
    # so an absent value is "not executed" rather than "unknown".
    outcome = point.get("outcome")
    outcome_icon = TEST_OUTCOME_ICONS.get(outcome or "notExecuted", "❓")
    reference = point.get("testCaseReference") or {}
    lines = [
        f"**Point #{point.get('id') or '?'}** — {reference.get('name') or '?'} (case #{reference.get('id') or '?'})",
        f"- **Outcome:** {outcome_icon} {outcome or 'not executed'}",
    ]
    if _get(point, "configuration", "name"):
        lines.append(f"- **Configuration:** {_get(point, 'configuration', 'name')}")
    if _get(point, "tester", "displayName"):
        lines.append(f"- **Tester:** {_get(point, 'tester', 'displayName')}")
    if point.get("state"):
        lines.append(f"- **State:** {point['state']}")
    if point.get("lastRunBuildNumber"):
        lines.append(f"- **Last Build:** {point['lastRunBuildNumber']}")
    return "\n".join(lines)


def format_test_point_list(points: Sequence) -> str:
    if not points:
        return "No test points found."

    lines: List[str] = []
    for point in points:
        outcome = point.get("outcome")
        outcome_icon = TEST_OUTCOME_ICONS.get(outcome or "notExecuted", "❓")
        configuration = _get(point, "configuration", "name") or "?"
        tester = _get(point, "tester", "displayName") or "?"
        reference = point.get("testCaseReference") or {}
        lines.append(
            f"#{point.get('id') or '?'} {reference.get('name') or '?'} — "
            f"{outcome_icon} {outcome or 'not executed'} — {configuration} — {tester}"
        )
    return "\n".join(lines)


def format_test_run(run: Dict[str, Any]) -> str:
    state_icon = TEST_RUN_STATE_ICONS.get(run.get("state") or "", "⏸️")
    lines = [
        f"# Run #{run.get('id') or '?'} — {run.get('name') or 'Unknown'}",
        f"- **State:** {state_icon} {run.get('state') or 'unknown'}",
    ]
    if run.get("plan"):
        plan = run["plan"]
        lines.append(f"- **Plan:** {plan.get('name') or '?'} (#{plan.get('id') or '?'})")

    total = run.get("totalTests") or 0
    passed = run.get("passedTests") or 0
    failed = run.get("failedTests") or 0
    incomplete = run.get("incompleteTests") or 0
    lines.append(f"- **Results:** {passed}/{total} passed, {failed} failed, {incomplete} incomplete")

    if run.get("startedDate"):
        lines.append(f"- **Started:** {_datetime(run['startedDate'])}")
    if run.get("completedDate"):
        lines.append(f"- **Completed:** {_datetime(run['completedDate'])}")
        lines.append(f"- **Duration:** {format_duration(run.get('startedDate'), run.get('completedDate'))}")
    if _get(run, "owner", "displayName"):
        lines.append(f"- **Owner:** {_get(run, 'owner', 'displayName')}")
    if run.get("url"):
        lines.append(f"- **URL:** {run['url']}")
    return "\n".join(lines)


def format_test_run_list(runs: Sequence) -> str:
    if not runs:
        return "No test runs found."

    lines: List[str] = []
    for run in runs:
        state_icon = TEST_RUN_STATE_ICONS.get(run.get("state") or "", "⏸️")
        passed = run.get("passedTests") or 0
        total = run.get("totalTests") or 0
        date = _date(run.get("startedDate")) if run.get("startedDate") else "?"
        lines.append(
            f"#{run.get('id') or '?'} {run.get('name') or '?'} — {state_icon} "
            f"{run.get('state') or '?'} — {passed}/{total} passed ({date})"
        )
    return "\n".join(lines)


def format_test_result(result: Dict[str, Any]) -> str:
    outcome = result.get("outcome") or ""
    outcome_icon = TEST_OUTCOME_ICONS.get(outcome, "❓")
    if outcome not in TEST_OUTCOME_ICONS:
        outcome_icon = TEST_OUTCOME_ICONS.get(outcome.lower(), "❓")
    title = result.get("testCaseTitle") or _get(result, "testCase", "name") or "Unknown"
    lines = [
        f"**{title}** (result #{result.get('id') or '?'})",
        f"- **Outcome:** {outcome_icon} {result.get('outcome') or 'unknown'}",
    ]
    if result.get("durationInMs") is not None:
        lines.append(f"- **Duration:** {result['durationInMs'] / 1000:.1f}s")
    if _get(result, "runBy", "displayName"):
        lines.append(f"- **Run By:** {_get(result, 'runBy', 'displayName')}")
    if result.get("errorMessage"):
        lines.append(f"- **Error:** {result['errorMessage']}")
    if result.get("comment"):
        lines.append(f"- **Comment:** {result['comment']}")
    return "\n".join(lines)


def format_test_result_list(results: Sequence) -> str:
    if not results:
        return "No test results found."

    lines: List[str] = []
    for result in results:
        outcome = result.get("outcome") or ""
        outcome_icon = TEST_OUTCOME_ICONS.get(outcome) or TEST_OUTCOME_ICONS.get(outcome.lower(), "❓")
        duration = f"{result['durationInMs'] / 1000:.1f}s" if result.get("durationInMs") is not None else "?"
        lines.append(
            f"#{result.get('id') or '?'} {result.get('testCaseTitle') or '?'} — "
            f"{outcome_icon} {result.get('outcome') or '?'} ({duration})"
        )
    return "\n".join(lines)
