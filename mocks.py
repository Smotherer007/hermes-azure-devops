"""Fixture-backed mock mode.

Every tool accepts ``mock: true`` (and the config file can set ``mock: true``
globally) to answer from the JSON fixtures instead of the network. That is what
makes the test suite run offline and what lets an agent exercise the tool
shapes without touching a real organization.

The fixtures are the ones pi-azure-devops ships, copied verbatim, and the
output goes through the same formatters as the live path, so a mock answer
looks like a real one apart from the ``(mock mode)`` markers.

Fixture loading is lazy and cached; :func:`clear_fixture_cache` drops it, which
the tests use.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import formatters as fmt
from .tools._base import error, result

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_cache: Dict[str, Any] = {}


def _load(name: str) -> Dict[str, Any]:
    cached = _cache.get(name)
    if cached is None:
        try:
            cached = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        _cache[name] = cached
    return cached


def clear_fixture_cache() -> None:
    _cache.clear()


# Convenience accessors
def _work_items() -> List[Dict[str, Any]]:
    return _load("work-items.json").get("workItems") or []


def _types() -> List[Dict[str, Any]]:
    return _load("work-item-types.json").get("workItemTypes") or []


def _comments() -> Dict[str, Any]:
    return _load("comments.json").get("comments") or {}


def _revisions() -> Dict[str, Any]:
    return _load("revisions.json").get("revisions") or {}


def _teams() -> List[Dict[str, Any]]:
    return _load("teams.json").get("teams") or []


def _boards() -> Dict[str, Any]:
    return _load("boards.json").get("boards") or {}


def _board_details() -> Dict[str, Any]:
    return _load("board-detail.json").get("boardDetails") or {}


def _iterations() -> Dict[str, Any]:
    return _load("iterations.json").get("iterations") or {}


def _iteration_work_items() -> Dict[str, Any]:
    return _load("iteration-work-items.json").get("iterationWorkItems") or {}


def _capacities() -> Dict[str, Any]:
    return _load("capacity.json").get("capacities") or {}


def _repos() -> List[Dict[str, Any]]:
    return _load("repos.json").get("repositories") or []


def _branches() -> Dict[str, Any]:
    return _load("branches.json").get("branches") or {}


def _pull_requests() -> List[Dict[str, Any]]:
    return _load("pull-requests.json").get("pullRequests") or []


def _pr_threads() -> Dict[str, Any]:
    return _load("pr-threads.json").get("prThreads") or {}


def _pr_commits() -> Dict[str, Any]:
    return _load("pr-commits.json").get("prCommits") or {}


def _policies() -> List[Dict[str, Any]]:
    return _load("policies.json").get("policies") or []


def _policy_evaluations() -> List[Dict[str, Any]]:
    return _load("policy-evaluations.json").get("evaluations") or {}


def _pipelines() -> List[Dict[str, Any]]:
    return _load("pipelines.json").get("pipelines") or []


def _runs() -> List[Dict[str, Any]]:
    return _load("runs.json").get("runs") or []


def _run_artifacts() -> Dict[str, Any]:
    return _load("run-artifacts.json").get("artifacts") or {}


def _run_logs() -> Dict[str, Any]:
    return _load("run-logs.json").get("logs") or {}


def _run_timelines() -> Dict[str, Any]:
    return _load("run-timeline.json").get("timelines") or {}


def _test_plans() -> List[Dict[str, Any]]:
    return _load("test-plans.json").get("testPlans") or []


def _test_suites() -> Dict[str, Any]:
    return _load("test-suites.json").get("testSuites") or {}


def _test_cases() -> Dict[str, Any]:
    return _load("test-cases.json").get("testCases") or {}


def _test_points() -> Dict[str, Any]:
    return _load("test-points.json").get("testPoints") or {}


def _test_runs() -> List[Dict[str, Any]]:
    return _load("test-runs.json").get("testRuns") or []


def _test_results() -> Dict[str, Any]:
    return _load("test-results.json").get("testResults") or {}


def _(value: Any) -> str:
    return str(value)


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------


def get_work_item(work_item_id: int) -> str:
    for item in _work_items():
        if item.get("id") == work_item_id:
            return result(fmt.format_work_item(item), id=item.get("id"), mock=True)
    return error(f"Work item #{work_item_id} not found (mock mode)")


def query_work_items(query: str, top: int = 100) -> str:
    import re

    items = list(_work_items())
    conditions: List[tuple] = []
    for match in re.finditer(r"\[([^\]]+)\]\s*=\s*'([^']+)'", query):
        conditions.append((match.group(1), match.group(2)))

    lowered = query.lower()
    if "active" in lowered and not any(field == "System.State" for field, _ in conditions):
        conditions.append(("System.State", "Active"))
    if "bug" in lowered and not any(field == "System.WorkItemType" for field, _ in conditions):
        conditions.append(("System.WorkItemType", "Bug"))
    if "closed" in lowered and not any(field == "System.State" for field, _ in conditions):
        conditions.append(("System.State", "Closed"))

    for field, wanted in conditions:
        items = [
            item
            for item in items
            if (item.get("fields") or {}).get(field) is not None
            and str((item.get("fields") or {}).get(field)).lower() == wanted.lower()
        ]

    items = items[:top]
    return result(
        f"Found {len(items)} work item(s) (mock mode):\n\n{fmt.format_work_item_list(items)}",
        count=len(items),
        mock=True,
    )


def list_work_item_types() -> str:
    types = _types()
    return result(
        f"Work item types (mock mode):\n\n{fmt.format_work_item_type_list(types)}",
        count=len(types),
        mock=True,
    )


def get_work_item_comments(work_item_id: int) -> str:
    entry = _comments().get(str(work_item_id))
    if not entry:
        return result(
            f"No comments found for work item #{work_item_id} (mock mode)",
            workItemId=work_item_id,
            count=0,
            mock=True,
        )
    comments = entry.get("comments") or []
    return result(
        f"Comments on #{work_item_id} (mock mode):\n\n{fmt.format_comments(entry)}",
        workItemId=work_item_id,
        count=len(comments),
        mock=True,
    )


def get_work_item_revisions(work_item_id: int) -> str:
    revisions = _revisions().get(str(work_item_id))
    if not revisions:
        return result(
            f"No revisions found for work item #{work_item_id} (mock mode)",
            workItemId=work_item_id,
            count=0,
            mock=True,
        )
    return result(
        f"Revision history for #{work_item_id} (mock mode):\n\n{fmt.format_revisions(revisions)}",
        workItemId=work_item_id,
        count=len(revisions),
        mock=True,
    )


def create_work_item(work_item_type: str, title: str, description: Optional[str] = None,
                     fields: Optional[Dict[str, str]] = None) -> str:
    new_id = random.randint(200, 299)
    return result(
        "\n".join([
            f"✅ Created work item #{new_id} (mock mode)",
            "",
            f"- **Type:** {work_item_type}",
            f"- **Title:** {title}",
            "- **State:** New",
            f"- **URL:** https://dev.azure.com/testorg/_apis/wit/workItems/{new_id}",
            "",
            "⚠️ This is mock data — no work item was actually created.",
        ]),
        id=new_id,
        type=work_item_type,
        title=title,
        mock=True,
    )


def update_work_item(work_item_id: int, fields: Dict[str, str]) -> str:
    if not any(item.get("id") == work_item_id for item in _work_items()):
        return error(f"Work item #{work_item_id} not found (mock mode)")

    lines = [f"✅ Updated work item #{work_item_id} (mock mode)", "", "Changed fields:"]
    lines += [f"- **{key}:** {value}" for key, value in fields.items()]
    lines += ["", "⚠️ This is mock data — no work item was actually updated."]
    return result("\n".join(lines), id=work_item_id, fields=fields, mock=True)


def add_work_item_comment(work_item_id: int, text: str) -> str:
    return result(
        "\n".join([
            f"✅ Added comment to work item #{work_item_id} (mock mode)",
            "",
            f"> {text}",
            "",
            "⚠️ This is mock data — no comment was actually added.",
        ]),
        workItemId=work_item_id,
        mock=True,
    )


def manage_work_item_links(work_item_id: int, operation: str, relation_type: str, target_id: int) -> str:
    verb = "Added" if operation == "add" else "Removed"
    prep = "to" if operation == "add" else "from"
    return result(
        "\n".join([
            f"✅ {verb} {relation_type} link {prep} #{work_item_id} → #{target_id} (mock mode)",
            "",
            "⚠️ This is mock data — no link was actually modified.",
        ]),
        workItemId=work_item_id,
        operation=operation,
        relationType=relation_type,
        targetId=target_id,
        mock=True,
    )


# ---------------------------------------------------------------------------
# Teams, boards, iterations, capacity
# ---------------------------------------------------------------------------


def list_teams() -> str:
    teams = _teams()
    return result(f"Teams (mock mode):\n\n{fmt.format_team_list(teams)}", count=len(teams), mock=True)


def list_boards(team: str) -> str:
    boards = _boards().get(team)
    if not boards:
        return error(f'No boards found for team "{team}" (mock mode)')
    return result(
        f"Boards for {team} (mock mode):\n\n{fmt.format_board_list(boards)}",
        team=team,
        count=len(boards),
        mock=True,
    )


def get_board(team: str, board_id: str) -> str:
    board = _board_details().get(f"{team}:{board_id}")
    if not board:
        return error(f'Board "{board_id}" not found for team "{team}" (mock mode)')
    return result(f"Board detail (mock mode):\n\n{fmt.format_board(board)}", team=team, boardId=board_id, mock=True)


def list_iterations(team: str, timeframe: Optional[str] = None) -> str:
    iterations = _iterations().get(team)
    if not iterations:
        return error(f'No iterations found for team "{team}" (mock mode)')

    filtered = iterations
    if timeframe:
        wanted = timeframe.lower()
        filtered = [it for it in iterations if str((it.get("attributes") or {}).get("timeFrame", "")).lower() == wanted]

    return result(
        f"Iterations for {team} (mock mode):\n\n{fmt.format_iteration_list(filtered)}",
        team=team,
        count=len(filtered),
        mock=True,
    )


def get_iteration_work_items(team: str, iteration_id: str) -> str:
    entry = _iteration_work_items().get(f"{team}:{iteration_id}")
    relations = (entry or {}).get("workItemRelations") or []
    if not relations:
        return result(
            f"No work items in iteration {iteration_id} for {team} (mock mode)",
            team=team,
            iterationId=iteration_id,
            count=0,
            mock=True,
        )

    ids = [r["target"]["id"] for r in relations if (r.get("target") or {}).get("id")]
    matched = [item for item in _work_items() if item.get("id") in ids]

    lines = [f"Work items in iteration {iteration_id} for {team} (mock mode):", ""]
    lines.append(fmt.format_work_item_list(matched) if matched else f"Work item IDs: {', '.join(str(i) for i in ids)}")
    return result("\n".join(lines), team=team, iterationId=iteration_id, count=len(ids), mock=True)


def get_capacity(team: str, iteration_id: str) -> str:
    capacity = _capacities().get(f"{team}:{iteration_id}")
    if not capacity:
        return error(f"No capacity data for {team} / {iteration_id} (mock mode)")
    return result(
        f"Sprint capacity (mock mode):\n\n{fmt.format_capacity(capacity)}",
        team=team,
        iterationId=iteration_id,
        mock=True,
    )


def set_board_columns(team: str, board_id: str, columns: List[Dict[str, Any]]) -> str:
    names = " → ".join(str(column.get("name")) for column in columns)
    return result(
        "\n".join([
            f'✅ Updated columns on board "{board_id}" for {team} (mock mode)',
            "",
            f"Columns: {names}",
            "",
            "⚠️ This is mock data — no board was actually modified.",
        ]),
        team=team,
        boardId=board_id,
        columnCount=len(columns),
        mock=True,
    )


def set_iteration(team: str, iteration_id: str, operation: str) -> str:
    verb = "Added" if operation == "add" else "Removed"
    prep = "to" if operation == "add" else "from"
    return result(
        "\n".join([
            f"✅ {verb} iteration {iteration_id} {prep} {team} (mock mode)",
            "",
            "⚠️ This is mock data — no iteration was actually modified.",
        ]),
        team=team,
        iterationId=iteration_id,
        operation=operation,
        mock=True,
    )


def set_capacity(team: str, iteration_id: str, capacities: List[Dict[str, Any]]) -> str:
    return result(
        "\n".join([
            f"✅ Set capacity for {len(capacities)} member(s) in {team} / {iteration_id} (mock mode)",
            "",
            "⚠️ This is mock data — no capacity was actually modified.",
        ]),
        team=team,
        iterationId=iteration_id,
        memberCount=len(capacities),
        mock=True,
    )


# ---------------------------------------------------------------------------
# Repositories and pull requests
# ---------------------------------------------------------------------------


def list_repos() -> str:
    repos = _repos()
    return result(f"Repositories (mock mode):\n\n{fmt.format_repo_list(repos)}", count=len(repos), mock=True)


def get_repo(repository_id: str) -> str:
    for repo in _repos():
        if repo.get("id") == repository_id or repo.get("name") == repository_id:
            return result(f"Repository detail (mock mode):\n\n{fmt.format_repo(repo)}", repositoryId=repo.get("id"), mock=True)
    return error(f'Repository "{repository_id}" not found (mock mode)')


def list_branches(repository_id: str) -> str:
    branches = _branches().get(repository_id)
    if not branches:
        return error(f'No branches found for repository "{repository_id}" (mock mode)')
    return result(
        f"Branches for {repository_id} (mock mode):\n\n{fmt.format_branch_list(branches)}",
        repositoryId=repository_id,
        count=len(branches),
        mock=True,
    )


def list_pull_requests(
    status: Optional[str] = None, creator: Optional[str] = None, repository_id: Optional[str] = None
) -> str:
    prs = list(_pull_requests())
    if status:
        prs = [pr for pr in prs if pr.get("status") == status]
    if creator:
        wanted = creator.lower()
        prs = [
            pr
            for pr in prs
            if wanted in str((pr.get("createdBy") or {}).get("displayName", "")).lower()
            or wanted in str((pr.get("createdBy") or {}).get("uniqueName", "")).lower()
        ]
    if repository_id:
        prs = [pr for pr in prs if pr.get("repositoryId") == repository_id]

    return result(
        f"Pull requests (mock mode):\n\n{fmt.format_pull_request_list(prs)}",
        count=len(prs),
        mock=True,
    )


def get_pull_request(pull_request_id: int) -> str:
    for pr in _pull_requests():
        if pr.get("pullRequestId") == pull_request_id:
            return result(
                f"Pull request detail (mock mode):\n\n{fmt.format_pull_request(pr)}",
                pullRequestId=pr.get("pullRequestId"),
                mock=True,
            )
    return error(f"Pull request #{pull_request_id} not found (mock mode)")


def get_pull_request_threads(repository_id: str, pull_request_id: int) -> str:
    threads = _pr_threads().get(f"{repository_id}:{pull_request_id}")
    if not threads:
        return result(
            f"No comment threads on PR #{pull_request_id} (mock mode)",
            repositoryId=repository_id,
            pullRequestId=pull_request_id,
            count=0,
            mock=True,
        )
    rendered = "\n".join(fmt.format_pull_request_thread(thread) for thread in threads)
    return result(
        f"Comment threads on PR #{pull_request_id} (mock mode):\n\n{rendered}",
        repositoryId=repository_id,
        pullRequestId=pull_request_id,
        count=len(threads),
        mock=True,
    )


def get_pull_request_commits(repository_id: str, pull_request_id: int) -> str:
    commits = _pr_commits().get(str(pull_request_id))
    if not commits:
        return result(
            f"No commits on PR #{pull_request_id} (mock mode)",
            repositoryId=repository_id,
            pullRequestId=pull_request_id,
            count=0,
            mock=True,
        )
    return result(
        f"Commits on PR #{pull_request_id} (mock mode):\n\n{fmt.format_commit_list(commits)}",
        repositoryId=repository_id,
        pullRequestId=pull_request_id,
        count=len(commits),
        mock=True,
    )


def create_pull_request(
    repository_id: str, title: str, source_ref_name: str, target_ref_name: str, description: Optional[str] = None
) -> str:
    new_id = random.randint(100, 149)
    lines = [
        f"✅ Created pull request #{new_id} (mock mode)",
        "",
        f"- **Title:** {title}",
        f"- **Branch:** {source_ref_name.replace('refs/heads/', '')} → {target_ref_name.replace('refs/heads/', '')}",
        f"- **Repository:** {repository_id}",
        "- **Status:** Active",
    ]
    if description:
        lines.append(f"\n{description}")
    lines += ["", "⚠️ This is mock data — no pull request was actually created."]
    return result("\n".join(lines), pullRequestId=new_id, repositoryId=repository_id, title=title, mock=True)


def update_pull_request(
    repository_id: str, pull_request_id: int, title: Optional[str] = None,
    description: Optional[str] = None, status: Optional[str] = None
) -> str:
    if not any(pr.get("pullRequestId") == pull_request_id for pr in _pull_requests()):
        return error(f"Pull request #{pull_request_id} not found (mock mode)")

    changed: List[str] = []
    if title:
        changed.append(f"title: {title}")
    if description:
        changed.append("description")
    if status:
        changed.append(f"status: {status}")

    return result(
        "\n".join([
            f"✅ Updated pull request #{pull_request_id} (mock mode)",
            "",
            f"Changed: {', '.join(changed)}",
            "",
            "⚠️ This is mock data — no pull request was actually updated.",
        ]),
        pullRequestId=pull_request_id,
        repositoryId=repository_id,
        changes=changed,
        mock=True,
    )


def add_pull_request_comment(repository_id: str, pull_request_id: int, text: str) -> str:
    return result(
        "\n".join([
            f"✅ Added comment to PR #{pull_request_id} (mock mode)",
            "",
            f"> {text}",
            "",
            "⚠️ This is mock data — no comment was actually added.",
        ]),
        pullRequestId=pull_request_id,
        repositoryId=repository_id,
        mock=True,
    )


VOTE_LABELS = {
    10: "Approved",
    5: "Approved with suggestions",
    0: "No vote",
    -5: "Waiting for author",
    -10: "Rejected",
}


def set_pull_request_vote(repository_id: str, pull_request_id: int, vote: int) -> str:
    label = VOTE_LABELS.get(vote, f"Unknown ({vote})")
    return result(
        "\n".join([
            f"✅ Set vote on PR #{pull_request_id}: {label} (mock mode)",
            "",
            "⚠️ This is mock data — no vote was actually recorded.",
        ]),
        pullRequestId=pull_request_id,
        repositoryId=repository_id,
        vote=vote,
        voteLabel=label,
        mock=True,
    )


def set_pull_request_autocomplete(repository_id: str, pull_request_id: int, enabled: bool) -> str:
    state = "enabled" if enabled else "disabled"
    return result(
        f"✅ Auto-complete {state} for PR #{pull_request_id} (mock mode)\n\n"
        "⚠️ This is mock data — no pull request was actually updated.",
        pullRequestId=pull_request_id,
        repositoryId=repository_id,
        autoComplete=enabled,
        mock=True,
    )


def link_pr_work_items(repository_id: str, pull_request_id: int, work_item_ids: List[int], operation: str) -> str:
    verb = "Linked" if operation == "add" else "Unlinked"
    prep = "to" if operation == "add" else "from"
    ids = ", ".join(f"#{wi}" for wi in work_item_ids)
    return result(
        f"✅ {verb} work item(s) {ids} {prep} PR #{pull_request_id} (mock mode)\n\n"
        "⚠️ This is mock data — no changes were actually made.",
        pullRequestId=pull_request_id,
        repositoryId=repository_id,
        workItemIds=work_item_ids,
        operation=operation,
        mock=True,
    )


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def list_policies(scope: Optional[str] = None) -> str:
    policies = [policy for policy in _policies() if not policy.get("isDeleted")]
    if scope:
        policies = [
            policy
            for policy in policies
            if any(scope in str((entry or {}).get("refName", "")) for entry in policy.get("scope") or [])
        ]
    rendered = "\n".join(fmt.format_policy(policy) for policy in policies)
    return result(f"Policy configurations (mock mode):\n\n{rendered}", count=len(policies), mock=True)


def get_policy_evaluations(artifact_id: str) -> str:
    evaluations = _policy_evaluations()
    matched = [entry for entry in evaluations if entry.get("artifactId") == artifact_id]
    # Fall back to every evaluation when the artifact id does not match: handy
    # for exercising the tool shape without constructing the exact vstfs URI.
    chosen = matched or evaluations
    rendered = "\n".join(fmt.format_policy_evaluation(entry) for entry in chosen)
    return result(f"Policy evaluations (mock mode):\n\n{rendered}", count=len(chosen), mock=True)


# ---------------------------------------------------------------------------
# Pipelines and builds
# ---------------------------------------------------------------------------


def list_pipelines() -> str:
    pipelines = _pipelines()
    return result(f"Pipelines (mock mode):\n\n{fmt.format_pipeline_list(pipelines)}", count=len(pipelines), mock=True)


def get_pipeline(pipeline_id: int) -> str:
    for pipeline in _pipelines():
        if pipeline.get("id") == pipeline_id:
            return result(
                f"Pipeline detail (mock mode):\n\n{fmt.format_pipeline(pipeline)}",
                pipelineId=pipeline.get("id"),
                mock=True,
            )
    return error(f"Pipeline #{pipeline_id} not found (mock mode)")


def list_runs(
    pipeline_id: Optional[int] = None,
    status: Optional[str] = None,
    result_filter: Optional[str] = None,
    branch: Optional[str] = None,
) -> str:
    runs = list(_runs())
    if pipeline_id:
        runs = [run for run in runs if (run.get("pipeline") or {}).get("id") == pipeline_id]
    if status:
        runs = [run for run in runs if run.get("state") == status]
    if result_filter:
        runs = [run for run in runs if run.get("result") == result_filter]
    if branch:
        branch_ref = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
        runs = [
            run
            for run in runs
            if (((run.get("resources") or {}).get("repositories") or {}).get("self") or {}).get("refName") == branch_ref
        ]

    return result(f"Runs (mock mode):\n\n{fmt.format_run_list(runs)}", count=len(runs), mock=True)


def get_run(pipeline_id: int, run_id: int) -> str:
    for run in _runs():
        if run.get("id") == run_id and (run.get("pipeline") or {}).get("id") == pipeline_id:
            return result(f"Run detail (mock mode):\n\n{fmt.format_run(run)}", pipelineId=pipeline_id, runId=run.get("id"), mock=True)
    return error(f"Run #{run_id} not found for pipeline #{pipeline_id} (mock mode)")


def get_run_artifacts(pipeline_id: int, run_id: int) -> str:
    artifacts = _run_artifacts().get(str(run_id))
    if not artifacts:
        return result(
            f"No artifacts for run #{run_id} (mock mode)",
            pipelineId=pipeline_id,
            runId=run_id,
            count=0,
            mock=True,
        )
    return result(
        f"Artifacts for run #{run_id} (mock mode):\n\n{fmt.format_artifact_list(artifacts)}",
        pipelineId=pipeline_id,
        runId=run_id,
        count=len(artifacts),
        mock=True,
    )


def get_run_logs(pipeline_id: int, run_id: int) -> str:
    logs = _run_logs().get(str(run_id))
    if not logs:
        return result(
            f"No logs for run #{run_id} (mock mode)",
            pipelineId=pipeline_id,
            runId=run_id,
            count=0,
            mock=True,
        )
    lines = []
    for log in logs:
        created = fmt.format_iso_datetime(log.get("createdOn")) if log.get("createdOn") else "?"
        lines.append(f"Log #{log.get('id') or '?'} ({log.get('lineCount') or 0} lines) — {created}")
    return result(
        f"Logs for run #{run_id} (mock mode):\n\n" + "\n".join(lines),
        pipelineId=pipeline_id,
        runId=run_id,
        count=len(logs),
        mock=True,
    )


def get_run_timeline(pipeline_id: int, run_id: int) -> str:
    timeline = _run_timelines().get(str(run_id))
    records = (timeline or {}).get("records") or []
    if not records:
        return result(
            f"No timeline for run #{run_id} (mock mode)",
            pipelineId=pipeline_id,
            runId=run_id,
            count=0,
            mock=True,
        )
    return result(
        f"Timeline for run #{run_id} (mock mode):\n\n{fmt.format_timeline(timeline)}",
        pipelineId=pipeline_id,
        runId=run_id,
        count=len(records),
        mock=True,
    )


def run_pipeline(pipeline_id: int, branch: Optional[str] = None, template_parameters: Optional[Dict[str, str]] = None) -> str:
    pipeline = next((item for item in _pipelines() if item.get("id") == pipeline_id), None)
    if not pipeline:
        return error(f"Pipeline #{pipeline_id} not found (mock mode)")

    new_run_id = random.randint(100, 999)
    branch_ref = f"refs/heads/{branch}" if branch else "refs/heads/main"
    parameters = template_parameters or {}
    param_line = (
        "\n- **Parameters:** " + ", ".join(f"{key}={value}" for key, value in parameters.items())
        if parameters
        else ""
    )

    lines = [
        f'✅ Queued run #{new_run_id} for "{pipeline.get("name")}" (mock mode)',
        "",
        f"- **Pipeline:** {pipeline.get('name')} (#{pipeline.get('id')})",
        f"- **Branch:** {branch_ref.replace('refs/heads/', '')}",
        "- **State:** inProgress",
    ]
    body = "\n".join(lines)
    if param_line:
        body += param_line
    body += "\n\n⚠️ This is mock data — no pipeline was actually run."

    return result(body, pipelineId=pipeline_id, runId=new_run_id, branch=branch_ref, mock=True)


def cancel_run(pipeline_id: int, run_id: int) -> str:
    run = next(
        (item for item in _runs() if item.get("id") == run_id and (item.get("pipeline") or {}).get("id") == pipeline_id),
        None,
    )
    if not run:
        return error(f"Run #{run_id} not found for pipeline #{pipeline_id} (mock mode)")
    if run.get("state") != "inProgress":
        return error(
            f"Run #{run_id} is not in progress (state: {run.get('state')}) — cannot cancel (mock mode)"
        )
    return result(
        "\n".join([
            f"✅ Cancelled run #{run_id} (mock mode)",
            "",
            f"- **Pipeline:** {(run.get('pipeline') or {}).get('name') or '?'} (#{pipeline_id})",
            "- **State:** Canceling",
            "",
            "⚠️ This is mock data — no run was actually cancelled.",
        ]),
        pipelineId=pipeline_id,
        runId=run_id,
        mock=True,
    )


def retry_run(pipeline_id: int, run_id: int) -> str:
    run = next(
        (item for item in _runs() if item.get("id") == run_id and (item.get("pipeline") or {}).get("id") == pipeline_id),
        None,
    )
    if not run:
        return error(f"Run #{run_id} not found for pipeline #{pipeline_id} (mock mode)")
    new_run_id = run_id + 1000
    return result(
        "\n".join([
            f"✅ Retried run #{run_id} → new run #{new_run_id} (mock mode)",
            "",
            f"- **Pipeline:** {(run.get('pipeline') or {}).get('name') or '?'} (#{pipeline_id})",
            f"- **Original run:** #{run_id}",
            f"- **New run:** #{new_run_id}",
            "- **State:** inProgress",
            "",
            "⚠️ This is mock data — no run was actually retried.",
        ]),
        pipelineId=pipeline_id,
        originalRunId=run_id,
        newRunId=new_run_id,
        mock=True,
    )


# ---------------------------------------------------------------------------
# Test plans and results
# ---------------------------------------------------------------------------


def list_test_plans(filter_active_plans: Optional[bool] = None) -> str:
    plans = list(_test_plans())
    if filter_active_plans:
        plans = [plan for plan in plans if plan.get("state") == "active"]
    return result(f"Test plans (mock mode):\n\n{fmt.format_test_plan_list(plans)}", count=len(plans), mock=True)


def get_test_plan(plan_id: int) -> str:
    for plan in _test_plans():
        if plan.get("id") == plan_id:
            return result(f"Test plan detail (mock mode):\n\n{fmt.format_test_plan(plan)}", planId=plan.get("id"), mock=True)
    return error(f"Test plan #{plan_id} not found (mock mode)")


def list_test_suites(plan_id: int) -> str:
    suites = _test_suites().get(str(plan_id))
    if not suites:
        return result(
            f"No test suites found for plan #{plan_id} (mock mode)", planId=plan_id, count=0, mock=True
        )
    return result(
        f"Test suites for plan #{plan_id} (mock mode):\n\n{fmt.format_test_suite_list(suites)}",
        planId=plan_id,
        count=len(suites),
        mock=True,
    )


def get_test_suite(plan_id: int, suite_id: int) -> str:
    suites = _test_suites().get(str(plan_id))
    if not suites:
        return error(f"No suites found for plan #{plan_id} (mock mode)")
    for suite in suites:
        if suite.get("id") == suite_id:
            return result(
                f"Test suite detail (mock mode):\n\n{fmt.format_test_suite(suite)}",
                planId=plan_id,
                suiteId=suite.get("id"),
                mock=True,
            )
    return error(f"Test suite #{suite_id} not found in plan #{plan_id} (mock mode)")


def list_test_cases(plan_id: int, suite_id: int) -> str:
    cases = _test_cases().get(f"{plan_id}-{suite_id}")
    if not cases:
        return result(
            f"No test cases in suite #{suite_id} of plan #{plan_id} (mock mode)",
            planId=plan_id,
            suiteId=suite_id,
            count=0,
            mock=True,
        )
    return result(
        f"Test cases in suite #{suite_id} (mock mode):\n\n{fmt.format_test_case_list(cases)}",
        planId=plan_id,
        suiteId=suite_id,
        count=len(cases),
        mock=True,
    )


def list_test_points(plan_id: int, suite_id: int) -> str:
    points = _test_points().get(f"{plan_id}-{suite_id}")
    if not points:
        return result(
            f"No test points in suite #{suite_id} of plan #{plan_id} (mock mode)",
            planId=plan_id,
            suiteId=suite_id,
            count=0,
            mock=True,
        )
    return result(
        f"Test points in suite #{suite_id} (mock mode):\n\n{fmt.format_test_point_list(points)}",
        planId=plan_id,
        suiteId=suite_id,
        count=len(points),
        mock=True,
    )


def create_test_run(plan_id: int, suite_ids: List[int], name: Optional[str] = None) -> str:
    plan = next((item for item in _test_plans() if item.get("id") == plan_id), None)
    if not plan:
        return error(f"Test plan #{plan_id} not found (mock mode)")

    new_run_id = random.randint(600, 699)
    run_name = name or f"{plan.get('name')} — Run {new_run_id}"
    suites = ", ".join(f"#{suite}" for suite in suite_ids)

    return result(
        "\n".join([
            f"✅ Created test run #{new_run_id} (mock mode)",
            "",
            f"- **Name:** {run_name}",
            f"- **Plan:** {plan.get('name')} (#{plan_id})",
            f"- **Suites:** {suites}",
            "- **State:** NotStarted",
            "",
            "⚠️ This is mock data — no test run was actually created.",
        ]),
        planId=plan_id,
        runId=new_run_id,
        name=run_name,
        mock=True,
    )


def update_test_results(run_id: int, results: List[Dict[str, Any]]) -> str:
    if not any(run.get("id") == run_id for run in _test_runs()):
        return error(f"Test run #{run_id} not found (mock mode)")

    lines = []
    for entry in results:
        comment = f' — "{entry["comment"]}"' if entry.get("comment") else ""
        lines.append(f"  - Result #{entry.get('testCaseResultId')}: {entry.get('outcome')}{comment}")

    return result(
        "\n".join([
            f"✅ Updated {len(results)} result(s) in run #{run_id} (mock mode)",
            "",
            *lines,
            "",
            "⚠️ This is mock data — no results were actually updated.",
        ]),
        runId=run_id,
        updatedCount=len(results),
        mock=True,
    )


def get_test_run(run_id: int) -> str:
    for run in _test_runs():
        if run.get("id") == run_id:
            return result(f"Test run detail (mock mode):\n\n{fmt.format_test_run(run)}", runId=run.get("id"), mock=True)
    return error(f"Test run #{run_id} not found (mock mode)")


def list_test_runs(plan_id: Optional[int] = None) -> str:
    runs = list(_test_runs())
    if plan_id:
        runs = [run for run in runs if (run.get("plan") or {}).get("id") == plan_id]
    return result(f"Test runs (mock mode):\n\n{fmt.format_test_run_list(runs)}", count=len(runs), mock=True)
