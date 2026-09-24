"""Repository, branch, pull request and policy tools (the Git + Policy APIs)."""

from __future__ import annotations

from typing import Any, Dict, List

from .. import client, mocks
from ..formatters import (
    format_branch_list,
    format_commit_list,
    format_policy,
    format_policy_evaluation,
    format_pull_request,
    format_pull_request_list,
    format_pull_request_thread,
    format_repo,
    format_repo_list,
)
from ._base import (
    MOCK_PROPERTY,
    ORG_PROPERTY,
    PROJECT_PROPERTY,
    config_for,
    error,
    is_mock,
    opt_bool,
    opt_int,
    opt_int_list,
    opt_str,
    req_int,
    req_str,
    result,
    schema,
    tool_handler,
)

PR_STATUS_VALUES = ("active", "abandoned", "completed", "all")
PR_STATUS_BODY = {"active": 1, "abandoned": 2, "completed": 3}
THREAD_STATUS_BODY = {"active": 1, "closed": 4, "pending": 6}
VOTE_BODY = {
    "approve": 10,
    "approve-with-suggestions": 5,
    "waiting-for-author": -5,
    "reject": -10,
    "reset": 0,
}
VOTE_LABELS = {
    "approve": "Approved",
    "approve-with-suggestions": "Approved with suggestions",
    "waiting-for-author": "Waiting for author",
    "reject": "Rejected",
    "reset": "Vote reset (no vote)",
}

LIST_REPOS_SCHEMA = schema(
    "azure_devops_list_repos",
    "List all Git repositories in the configured Azure DevOps project. "
    "Returns repo name, ID, default branch, and size.",
    {
        "includeHidden": {"type": "boolean", "description": "Include hidden repositories", "default": False},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_repos(args: Dict[str, Any]) -> str:
    config = config_for(args)

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_repos()

    try:
        repos = client.list_repositories(config, include_hidden=bool(opt_bool(args, "includeHidden")))
        if not repos:
            return result("No repositories found in this project.", count=0)
        return result(format_repo_list(repos), count=len(repos))
    except Exception as exc:
        return error(f"Failed to list repositories: {client.format_ado_error(exc)}")


GET_REPO_SCHEMA = schema(
    "azure_devops_get_repo",
    "Get details of a single Azure DevOps Git repository by ID or name. "
    "Returns name, default branch, size, and URL.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId"],
)


@tool_handler
def get_repo(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_repo(repository_id)

    try:
        repo = client.get_repository(config, repository_id)
        if not repo or not repo.get("id"):
            return error(f'Repository "{repository_id}" not found.')
        return result(format_repo(repo), repositoryId=repo["id"])
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'Repository "{repository_id}" not found.')
        return error(f'Failed to get repository "{repository_id}": {client.format_ado_error(exc)}')


LIST_BRANCHES_SCHEMA = schema(
    "azure_devops_list_branches",
    "List branches in an Azure DevOps Git repository. "
    "Shows branch name, latest commit, and ahead/behind counts.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId"],
)


@tool_handler
def list_branches(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_branches(repository_id)

    try:
        branches = client.list_branches(config, repository_id)
        if not branches:
            return result(f'No branches found in repository "{repository_id}".', count=0)
        return result(format_branch_list(branches), repositoryId=repository_id, count=len(branches))
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'Repository "{repository_id}" not found.')
        return error(f"Failed to list branches: {client.format_ado_error(exc)}")


LIST_PULL_REQUESTS_SCHEMA = schema(
    "azure_devops_list_pull_requests",
    "List or search Azure DevOps pull requests. Supports filtering by status, repository, creator, "
    "and branch names. Returns PR ID, title, status, author, and branch info.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name to scope results"},
        "status": {
            "type": "string",
            "enum": list(PR_STATUS_VALUES),
            "description": "Filter by PR status. Defaults to active.",
        },
        "creator": {"type": "string", "description": "Filter by creator display name or email"},
        "reviewer": {"type": "string", "description": "Filter by reviewer display name or email"},
        "sourceRefName": {"type": "string", "description": "Filter by source branch (e.g. refs/heads/feature/login)"},
        "targetRefName": {"type": "string", "description": "Filter by target branch (e.g. refs/heads/main)"},
        "top": {"type": "number", "description": "Maximum number of results", "default": 100},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_pull_requests(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = opt_str(args, "repositoryId")
    status = opt_str(args, "status")
    creator = opt_str(args, "creator")
    reviewer = opt_str(args, "reviewer")

    if status and status not in PR_STATUS_VALUES:
        return error(f"status must be one of: {', '.join(PR_STATUS_VALUES)}.")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_pull_requests(status, creator, repository_id)

    try:
        pull_requests = client.list_pull_requests(
            config,
            repository_id=repository_id,
            status=status,
            source_ref_name=opt_str(args, "sourceRefName"),
            target_ref_name=opt_str(args, "targetRefName"),
            top=opt_int(args, "top") or 100,
        )

        # creator/reviewer are display-name or e-mail filters. Azure DevOps has
        # no query parameter for them, so filter locally like the pi extension
        # does through its mock path.
        if creator:
            wanted = creator.lower()
            pull_requests = [
                pr
                for pr in pull_requests
                if wanted in str((pr.get("createdBy") or {}).get("displayName", "")).lower()
                or wanted in str((pr.get("createdBy") or {}).get("uniqueName", "")).lower()
                or wanted in str((pr.get("createdBy") or {}).get("id", "")).lower()
            ]
        if reviewer:
            wanted = reviewer.lower()

            def matches_reviewer(pr: Dict[str, Any]) -> bool:
                for entry in pr.get("reviewers") or []:
                    entry = entry or {}
                    haystack = " ".join(
                        str(entry.get(key, "")) for key in ("displayName", "uniqueName", "id")
                    ).lower()
                    if wanted in haystack:
                        return True
                return False

            pull_requests = [pr for pr in pull_requests if matches_reviewer(pr)]

        if not pull_requests:
            return result("No pull requests found matching the criteria.", count=0)

        details: Dict[str, Any] = {"count": len(pull_requests)}
        if repository_id:
            details["repositoryId"] = repository_id
        return result(format_pull_request_list(pull_requests), **details)
    except Exception as exc:
        return error(f"Failed to list pull requests: {client.format_ado_error(exc)}")


GET_PULL_REQUEST_SCHEMA = schema(
    "azure_devops_get_pull_request",
    "Get full details of an Azure DevOps pull request. Returns title, description, reviewers with votes, "
    "merge status, and branch info.",
    {
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "repositoryId": {
            "type": "string",
            "description": "Repository ID or name (optional — uses a project-wide lookup if omitted)",
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pullRequestId"],
)


@tool_handler
def get_pull_request(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pull_request_id = req_int(args, "pullRequestId")
    repository_id = opt_str(args, "repositoryId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_pull_request(pull_request_id)

    try:
        pull_request = client.get_pull_request(config, pull_request_id, repository_id=repository_id)
        if not pull_request or not pull_request.get("pullRequestId"):
            return error(f"Pull request #{pull_request_id} not found.")
        return result(format_pull_request(pull_request), pullRequestId=pull_request["pullRequestId"])
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Pull request #{pull_request_id} not found.")
        return error(f"Failed to get pull request #{pull_request_id}: {client.format_ado_error(exc)}")


GET_PR_THREADS_SCHEMA = schema(
    "azure_devops_get_pull_request_threads",
    "Get comment threads on an Azure DevOps pull request. Shows thread status and all comments with authors.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId"],
)


@tool_handler
def get_pull_request_threads(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_pull_request_threads(repository_id, pull_request_id)

    try:
        threads = client.get_pull_request_threads(config, repository_id, pull_request_id)
        if not threads:
            return result(f"No comment threads on PR #{pull_request_id}.", pullRequestId=pull_request_id, threadCount=0)
        rendered = "\n".join(format_pull_request_thread(thread) for thread in threads)
        return result(
            f"Comment threads on PR #{pull_request_id}:\n\n{rendered}",
            pullRequestId=pull_request_id,
            threadCount=len(threads),
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'PR #{pull_request_id} or repository "{repository_id}" not found.')
        return error(f"Failed to get PR threads: {client.format_ado_error(exc)}")


GET_PR_COMMITS_SCHEMA = schema(
    "azure_devops_get_pull_request_commits",
    "Get commits in an Azure DevOps pull request. Shows short SHA, author, message, and date for each commit.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId"],
)


@tool_handler
def get_pull_request_commits(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_pull_request_commits(repository_id, pull_request_id)

    try:
        commits = client.get_pull_request_commits(config, repository_id, pull_request_id)
        if not commits:
            return result(f"No commits in PR #{pull_request_id}.", pullRequestId=pull_request_id, commitCount=0)
        return result(
            f"Commits in PR #{pull_request_id}:\n\n{format_commit_list(commits)}",
            pullRequestId=pull_request_id,
            commitCount=len(commits),
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'PR #{pull_request_id} or repository "{repository_id}" not found.')
        return error(f"Failed to get PR commits: {client.format_ado_error(exc)}")


LIST_POLICIES_SCHEMA = schema(
    "azure_devops_list_policies",
    "List branch and PR policies configured for the Azure DevOps project. "
    "Shows policy type, blocking status, scope, and settings.",
    {
        "scope": {"type": "string", "description": "Filter by scope (e.g. refs/heads/main)"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_policies(args: Dict[str, Any]) -> str:
    config = config_for(args)
    scope = opt_str(args, "scope")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_policies(scope)

    try:
        policies = client.list_policies(config, scope)
        if not policies:
            return result("No policies configured for this project.", count=0)
        rendered = "\n".join(format_policy(policy) for policy in policies)
        return result(f"Policy configurations:\n\n{rendered}", count=len(policies))
    except Exception as exc:
        return error(f"Failed to list policies: {client.format_ado_error(exc)}")


GET_POLICY_EVALUATIONS_SCHEMA = schema(
    "azure_devops_get_policy_evaluations",
    "Get policy evaluation status for an Azure DevOps pull request. "
    "Shows whether each policy (reviewers, build, etc.) is approved, pending, or rejected.",
    {
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "repositoryId": {
            "type": "string",
            "description": "Repository ID or name (used for artifact ID construction)",
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pullRequestId"],
)


@tool_handler
def get_policy_evaluations(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pull_request_id = req_int(args, "pullRequestId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_policy_evaluations(f"vstfs://CodeReview/CodeReviewId/{pull_request_id}")

    try:
        project_id = config.project
        for project in client.get_projects(config):
            if (project or {}).get("name") == config.project and (project or {}).get("id"):
                project_id = str(project["id"])
                break

        artifact_id = f"vstfs:///CodeReview/CodeReviewId/{project_id}/{pull_request_id}"
        evaluations = client.get_policy_evaluations(config, artifact_id)
        if not evaluations:
            return result(
                f"No policy evaluations found for PR #{pull_request_id}.",
                pullRequestId=pull_request_id,
                evaluationCount=0,
            )
        rendered = "\n".join(format_policy_evaluation(entry) for entry in evaluations)
        return result(
            f"Policy evaluations for PR #{pull_request_id}:\n\n{rendered}",
            pullRequestId=pull_request_id,
            evaluationCount=len(evaluations),
        )
    except Exception as exc:
        return error(
            f"Failed to get policy evaluations for PR #{pull_request_id}: {client.format_ado_error(exc)}"
        )


CREATE_PULL_REQUEST_SCHEMA = schema(
    "azure_devops_create_pull_request",
    "Create a new Azure DevOps pull request. Requires repository, source branch, target branch, and title.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "sourceRefName": {"type": "string", "description": "Source branch (e.g. refs/heads/feature/login)"},
        "targetRefName": {"type": "string", "description": "Target branch (e.g. refs/heads/main)"},
        "title": {"type": "string", "description": "Pull request title"},
        "description": {"type": "string", "description": "Pull request description (supports markdown)"},
        "isDraft": {"type": "boolean", "description": "Create as draft PR", "default": False},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "sourceRefName", "targetRefName", "title"],
)


@tool_handler
def create_pull_request(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    source_ref_name = req_str(args, "sourceRefName")
    target_ref_name = req_str(args, "targetRefName")
    title = req_str(args, "title")
    description = opt_str(args, "description")
    is_draft = opt_bool(args, "isDraft") or False

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.create_pull_request(repository_id, title, source_ref_name, target_ref_name, description)

    body: Dict[str, Any] = {
        "sourceRefName": source_ref_name,
        "targetRefName": target_ref_name,
        "title": title,
    }
    if description:
        body["description"] = description
    if is_draft:
        body["isDraft"] = True

    try:
        pull_request = client.create_pull_request(config, repository_id, body)
        if not pull_request or not pull_request.get("pullRequestId"):
            return error("Failed to create pull request — no ID returned from the API.")
        return result(
            f"✅ Created pull request #{pull_request['pullRequestId']}\n\n{format_pull_request(pull_request)}",
            pullRequestId=pull_request["pullRequestId"],
            repositoryId=repository_id,
        )
    except Exception as exc:
        return error(f"Failed to create pull request: {client.format_ado_error(exc)}")


UPDATE_PULL_REQUEST_SCHEMA = schema(
    "azure_devops_update_pull_request",
    "Update an Azure DevOps pull request — change title, description, or status (abandon/complete/reactivate).",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "title": {"type": "string", "description": "New title"},
        "description": {"type": "string", "description": "New description"},
        "status": {
            "type": "string",
            "enum": ["active", "abandoned", "completed"],
            "description": "New status — active, abandoned, or completed",
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId"],
)


@tool_handler
def update_pull_request(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")
    title = opt_str(args, "title")
    description = opt_str(args, "description")
    status = opt_str(args, "status")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.update_pull_request(repository_id, pull_request_id, title, description, status)

    patch: Dict[str, Any] = {}
    if title:
        patch["title"] = title
    if description:
        patch["description"] = description
    if status:
        if status not in PR_STATUS_BODY:
            return error("status must be active, abandoned, or completed.")
        patch["status"] = PR_STATUS_BODY[status]

    if not patch:
        return error("Nothing to update: provide title, description, or status.")

    try:
        pull_request = client.update_pull_request(config, repository_id, pull_request_id, patch)
        if not pull_request or not pull_request.get("pullRequestId"):
            return error(f"Failed to update pull request #{pull_request_id}.")

        updated: List[str] = []
        if title:
            updated.append("title")
        if description:
            updated.append("description")
        if status:
            updated.append(f"status → {status}")

        return result(
            f"✅ Updated pull request #{pull_request_id}\n\nChanged: {', '.join(updated)}\n\n"
            f"{format_pull_request(pull_request)}",
            pullRequestId=pull_request["pullRequestId"],
            repositoryId=repository_id,
            fieldsUpdated=updated,
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Pull request #{pull_request_id} not found.")
        return error(f"Failed to update pull request #{pull_request_id}: {client.format_ado_error(exc)}")


ADD_PR_COMMENT_SCHEMA = schema(
    "azure_devops_add_pull_request_comment",
    "Add a comment to an Azure DevOps pull request. Creates a new comment thread on the PR.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "content": {"type": "string", "description": "Comment text"},
        "threadStatus": {
            "type": "string",
            "enum": ["active", "closed", "pending"],
            "description": "Thread status. Defaults to active.",
            "default": "active",
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId", "content"],
)


@tool_handler
def add_pull_request_comment(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")
    content = req_str(args, "content")
    thread_status = (opt_str(args, "threadStatus") or "active").strip().lower()

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.add_pull_request_comment(repository_id, pull_request_id, content)

    if thread_status not in THREAD_STATUS_BODY:
        return error("threadStatus must be active, closed, or pending.")

    try:
        thread = client.create_thread(
            config,
            repository_id,
            pull_request_id,
            {
                "status": THREAD_STATUS_BODY[thread_status],
                "comments": [{"content": content, "commentType": 1}],
            },
        )
        if not thread or not thread.get("id"):
            return error(f"Failed to add comment to PR #{pull_request_id}.")
        return result(
            f"✅ Added comment to PR #{pull_request_id} (thread #{thread['id']})\n\n> {content}",
            pullRequestId=pull_request_id,
            repositoryId=repository_id,
            threadId=thread["id"],
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'PR #{pull_request_id} or repository "{repository_id}" not found.')
        return error(f"Failed to add comment to PR #{pull_request_id}: {client.format_ado_error(exc)}")


SET_PR_VOTE_SCHEMA = schema(
    "azure_devops_set_pull_request_vote",
    "Vote on an Azure DevOps pull request. Use approve, approve-with-suggestions, waiting-for-author, "
    "reject, or reset.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "vote": {
            "type": "string",
            "enum": list(VOTE_BODY),
            "description": "Vote value: approve, approve-with-suggestions, waiting-for-author, reject, or reset",
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId", "vote"],
)


@tool_handler
def set_pull_request_vote(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")
    vote_name = req_str(args, "vote").strip().lower()

    if vote_name not in VOTE_BODY:
        return error(f'vote must be one of: {", ".join(VOTE_BODY)}.')
    vote = VOTE_BODY[vote_name]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.set_pull_request_vote(repository_id, pull_request_id, vote)

    try:
        # The reviewer id must be the real identity of the signed-in user. An
        # empty id makes Azure DevOps answer 401 (see the plugin README).
        reviewer_id = client.authenticated_user_id(config)
        if not reviewer_id:
            return error(
                "Could not determine the authenticated identity (connectionData returned no user id). "
                "A vote needs a real reviewer identity."
            )

        client.set_pull_request_reviewer_vote(
            config, repository_id, pull_request_id, reviewer_id, vote
        )
        label = VOTE_LABELS.get(vote_name, vote_name)
        return result(
            f"✅ Set vote on PR #{pull_request_id}: {label}",
            pullRequestId=pull_request_id,
            repositoryId=repository_id,
            vote=vote,
            voteLabel=label,
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'PR #{pull_request_id} or repository "{repository_id}" not found.')
        return error(f"Failed to set vote on PR #{pull_request_id}: {client.format_ado_error(exc)}")


SET_PR_AUTOCOMPLETE_SCHEMA = schema(
    "azure_devops_set_pull_request_autocomplete",
    "Enable or disable auto-complete on an Azure DevOps pull request. "
    "When enabled, the PR merges automatically once all branch policies are satisfied.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "enabled": {"type": "boolean", "description": "true to enable auto-complete, false to disable"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId", "enabled"],
)


@tool_handler
def set_pull_request_autocomplete(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")
    enabled = opt_bool(args, "enabled")

    if enabled is None:
        return error("enabled must be true or false.")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.set_pull_request_autocomplete(repository_id, pull_request_id, enabled)

    try:
        if enabled:
            # autoCompleteSetBy needs the real identity id; {"id": ""} fails
            # with "Invalid argument value" (see the plugin README).
            identity = client.authenticated_user_id(config)
            if not identity:
                return error(
                    "Could not determine the authenticated identity (connectionData returned no user id). "
                    "Auto-complete needs a real identity."
                )
            patch: Dict[str, Any] = {"autoCompleteSetBy": {"id": identity}}
        else:
            patch = {"autoCompleteSetBy": None}

        pull_request = client.update_pull_request(config, repository_id, pull_request_id, patch)
        if not pull_request or not pull_request.get("pullRequestId"):
            return error(f"Failed to update auto-complete for PR #{pull_request_id}.")

        state = "enabled" if enabled else "disabled"
        body = f"✅ Auto-complete {state} for PR #{pull_request_id}"
        if enabled:
            body += "\n\nThe PR will merge automatically once all branch policies pass."
        return result(
            body,
            pullRequestId=pull_request["pullRequestId"],
            repositoryId=repository_id,
            autoComplete=enabled,
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Pull request #{pull_request_id} not found.")
        return error(
            f"Failed to set auto-complete for PR #{pull_request_id}: {client.format_ado_error(exc)}"
        )


LINK_PR_WORK_ITEMS_SCHEMA = schema(
    "azure_devops_link_pr_work_items",
    "Link or unlink work items to/from an Azure DevOps pull request. "
    "Linked work items appear in the PR overview and can be transitioned on PR completion.",
    {
        "repositoryId": {"type": "string", "description": "Repository ID or name"},
        "pullRequestId": {"type": "number", "description": "Pull request ID"},
        "workItemIds": {"type": "array", "items": {"type": "number"}, "description": "Work item IDs to link or unlink"},
        "operation": {"type": "string", "enum": ["add", "remove"], "description": "'add' to link work items, 'remove' to unlink them"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["repositoryId", "pullRequestId", "workItemIds", "operation"],
)


@tool_handler
def link_pr_work_items(args: Dict[str, Any]) -> str:
    config = config_for(args)
    repository_id = req_str(args, "repositoryId")
    pull_request_id = req_int(args, "pullRequestId")
    work_item_ids = opt_int_list(args, "workItemIds") or []
    operation = req_str(args, "operation").strip().lower()

    if not work_item_ids:
        return error("workItemIds must not be empty.")
    if operation not in ("add", "remove"):
        return error('operation must be "add" or "remove".')

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.link_pr_work_items(repository_id, pull_request_id, work_item_ids, operation)

    try:
        pull_request = client.get_pull_request(config, pull_request_id, repository_id=repository_id)
        if not pull_request or not pull_request.get("pullRequestId"):
            return error(f"Pull request #{pull_request_id} not found.")

        repository = pull_request.get("repository") or {}
        project_id = (repository.get("project") or {}).get("id") or ""
        repo_guid = repository.get("id") or repository_id
        if not project_id or not repo_guid:
            return error(f"Could not resolve project/repo GUIDs from PR #{pull_request_id}.")

        # Must use GUIDs and %2F separators.
        artifact_uri = f"vstfs:///Git/PullRequestId/{project_id}%2F{repo_guid}%2F{pull_request_id}"

        linked: List[str] = []
        failures: List[str] = []

        for work_item_id in work_item_ids:
            try:
                if operation == "add":
                    client.update_work_item(
                        config,
                        work_item_id,
                        [
                            {
                                "op": "add",
                                "path": "/relations/-",
                                "value": {
                                    "rel": "ArtifactLink",
                                    "url": artifact_uri,
                                    "attributes": {"name": "Pull Request"},
                                },
                            }
                        ],
                        # ArtifactLinks are silently dropped on 7.1-preview.x.
                        api_version=client.ARTIFACT_LINK_API_VERSION,
                    )
                    linked.append(f"#{work_item_id}")
                else:
                    work_item = client.get_work_item(config, work_item_id, expand="relations")
                    relations = work_item.get("relations") or []
                    index = next(
                        (
                            position
                            for position, relation in enumerate(relations)
                            if relation.get("rel") == "ArtifactLink"
                            and relation.get("url") == artifact_uri
                        ),
                        -1,
                    )
                    if index >= 0:
                        client.update_work_item(
                            config,
                            work_item_id,
                            [{"op": "remove", "path": f"/relations/{index}"}],
                            api_version=client.ARTIFACT_LINK_API_VERSION,
                        )
                        linked.append(f"#{work_item_id}")
                    else:
                        failures.append(f"#{work_item_id}: not linked to this PR")
            except Exception as exc:
                failures.append(f"#{work_item_id}: {client.format_ado_error(exc)}")

        verb = "Linked" if operation == "add" else "Unlinked"
        prep = "to" if operation == "add" else "from"
        if linked:
            body = f"✅ {verb} work item(s) {', '.join(linked)} {prep} PR #{pull_request_id}"
        else:
            body = f"⚠️ No work items were {'linked' if operation == 'add' else 'unlinked'}."
        if failures:
            body += "\n\n❌ Errors:\n" + "\n".join(f"- {item}" for item in failures)

        return result(
            body,
            pullRequestId=pull_request_id,
            repositoryId=repository_id,
            artifactUri=artifact_uri,
            workItemIds=work_item_ids,
            operation=operation,
            linked=linked,
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'Pull request #{pull_request_id} or repository "{repository_id}" not found.')
        return error(
            f"Failed to link work items to PR #{pull_request_id}: {client.format_ado_error(exc)}"
        )
