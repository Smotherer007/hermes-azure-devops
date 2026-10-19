"""Every tool, plus the live request each one makes.

The mock-mode block proves all 54 tools answer without touching the network.
The live block drives the real client against the fake Azure DevOps server and
asserts the request that goes out -- which is where a hand-written REST port
can go wrong.
"""

from __future__ import annotations

import json

import pytest

from conftest import call, sub, tool_names

# ---------------------------------------------------------------------------
# Mock mode: every tool answers
# ---------------------------------------------------------------------------

MOCK_CASES = {
    "azure_devops_doctor": {},
    "azure_devops_get_work_item": {"id": 101},
    "azure_devops_query_work_items": {"query": "SELECT [System.Id] FROM WorkItems WHERE [System.State] = 'Active'"},
    "azure_devops_list_work_item_types": {},
    "azure_devops_get_work_item_comments": {"workItemId": 101},
    "azure_devops_get_work_item_revisions": {"workItemId": 101},
    "azure_devops_create_work_item": {"type": "Bug", "title": "Something broke"},
    "azure_devops_update_work_item": {"id": 101, "fields": {"System.State": "Active"}},
    "azure_devops_add_work_item_comment": {"workItemId": 101, "text": "note"},
    "azure_devops_manage_work_item_links": {
        "workItemId": 101,
        "operation": "add",
        "relationType": "System.LinkTypes.Related",
        "targetId": 102,
    },
    "azure_devops_list_teams": {},
    "azure_devops_list_boards": {},
    "azure_devops_get_board": {"boardId": "stories"},
    "azure_devops_list_iterations": {},
    "azure_devops_get_iteration_work_items": {"iterationId": "sprint-3"},
    "azure_devops_get_capacity": {"iterationId": "sprint-3"},
    "azure_devops_set_board_columns": {
        "boardId": "stories",
        "columns": [{"name": "New"}, {"name": "Done"}],
    },
    "azure_devops_set_iteration": {"iterationId": "sprint-3", "operation": "add"},
    "azure_devops_set_capacity": {
        "iterationId": "sprint-3",
        "capacities": [{"teamMemberId": "jane@example.com", "activities": [{"name": "Dev", "capacityPerDay": 6}]}],
    },
    "azure_devops_list_repos": {},
    "azure_devops_get_repo": {"repositoryId": "repo-webapp"},
    "azure_devops_list_branches": {"repositoryId": "repo-webapp"},
    "azure_devops_list_pull_requests": {},
    "azure_devops_get_pull_request": {"pullRequestId": 1},
    "azure_devops_get_pull_request_threads": {"repositoryId": "repo-webapp", "pullRequestId": 1},
    "azure_devops_get_pull_request_commits": {"repositoryId": "repo-webapp", "pullRequestId": 1},
    "azure_devops_list_policies": {},
    "azure_devops_get_policy_evaluations": {"pullRequestId": 1},
    "azure_devops_create_pull_request": {
        "repositoryId": "repo-webapp",
        "sourceRefName": "refs/heads/feature",
        "targetRefName": "refs/heads/main",
        "title": "Add feature",
    },
    "azure_devops_update_pull_request": {"repositoryId": "repo-webapp", "pullRequestId": 1, "title": "New title"},
    "azure_devops_add_pull_request_comment": {
        "repositoryId": "repo-webapp",
        "pullRequestId": 1,
        "content": "Looks good",
    },
    "azure_devops_set_pull_request_vote": {"repositoryId": "repo-webapp", "pullRequestId": 1, "vote": "approve"},
    "azure_devops_set_pull_request_autocomplete": {
        "repositoryId": "repo-webapp",
        "pullRequestId": 1,
        "enabled": True,
    },
    "azure_devops_link_pr_work_items": {
        "repositoryId": "repo-webapp",
        "pullRequestId": 1,
        "workItemIds": [101],
        "operation": "add",
    },
    "azure_devops_list_pipelines": {},
    "azure_devops_get_pipeline": {"pipelineId": 1},
    "azure_devops_list_runs": {},
    "azure_devops_get_run": {"pipelineId": 1, "runId": 42},
    "azure_devops_get_run_artifacts": {"pipelineId": 1, "runId": 42},
    "azure_devops_get_run_logs": {"pipelineId": 1, "runId": 42},
    "azure_devops_get_run_timeline": {"pipelineId": 1, "runId": 42},
    "azure_devops_run_pipeline": {"pipelineId": 1},
    "azure_devops_cancel_run": {"pipelineId": 1, "runId": 44},
    "azure_devops_retry_run": {"pipelineId": 1, "runId": 42},
    "azure_devops_list_test_plans": {},
    "azure_devops_get_test_plan": {"planId": 101},
    "azure_devops_list_test_suites": {"planId": 101},
    "azure_devops_get_test_suite": {"planId": 101, "suiteId": 301},
    "azure_devops_list_test_cases": {"planId": 101, "suiteId": 301},
    "azure_devops_list_test_points": {"planId": 101, "suiteId": 301},
    "azure_devops_get_test_run": {"runId": 501},
    "azure_devops_list_test_runs": {},
    "azure_devops_create_test_run": {"planId": 101, "suiteIds": [301]},
    "azure_devops_update_test_results": {"runId": 501, "results": [{"id": 1, "outcome": "passed"}]},
}


def test_mock_cases_cover_every_registered_tool():
    assert set(MOCK_CASES) == set(tool_names())


@pytest.mark.parametrize("tool", sorted(MOCK_CASES))
def test_every_tool_answers_in_mock_mode(configure, tool):
    configure()
    payload = call(tool, {**MOCK_CASES[tool], "mock": True})

    assert "error" not in payload, payload.get("error")
    assert payload.get("result"), "a successful tool returns rendered text"
    assert payload.get("mock") is True


def test_mock_mode_marks_output_as_simulated(configure):
    configure()
    payload = call("azure_devops_create_work_item", {"type": "Bug", "title": "x", "mock": True})
    assert "no work item was actually created" in payload["result"]


def test_global_mock_flag_in_the_config_switches_every_tool(configure):
    configure(extra={"mock": True})
    payload = call("azure_devops_list_repos", {})
    assert payload["mock"] is True
    assert "mock mode" in payload["result"]


def test_mock_mode_does_not_need_a_reachable_org(configure):
    configure(pat="")
    payload = call("azure_devops_get_work_item", {"id": 101, "mock": True})
    assert "error" not in payload


# ---------------------------------------------------------------------------
# Live: work items
# ---------------------------------------------------------------------------


def _wi(id=101, title="Test work item"):
    return {
        "id": id,
        "rev": 1,
        "fields": {
            "System.Title": title,
            "System.WorkItemType": "User Story",
            "System.State": "Active",
            "System.AssignedTo": {"displayName": "Jane"},
        },
    }


def test_get_work_item_live(configure, ado):
    configure()
    ado.on("GET", "/_apis/wit/workitems/101", _wi())

    payload = call("azure_devops_get_work_item", {"id": 101})
    assert payload["id"] == 101
    assert "# Work Item 101" in payload["result"]


def test_get_work_item_not_found_is_friendly(configure, ado):
    configure()
    ado.fail("GET", "/_apis/wit/workitems/999", 404, {"message": "does not exist"})

    payload = call("azure_devops_get_work_item", {"id": 999})
    assert payload["error"] == "Work item #999 not found."


def test_list_work_item_types_live(configure, ado):
    configure()
    ado.on("GET", "/_apis/wit/workitemtypes", {"count": 1, "value": [{"name": "Bug", "referenceName": "Bug"}]})

    payload = call("azure_devops_list_work_item_types", {})
    assert payload["count"] == 1
    assert "**Bug**" in payload["result"]


def test_query_work_items_runs_wiql_then_fetches_the_items(configure, ado):
    configure()
    ado.on("POST", "/_apis/wit/wiql", {"workItems": [{"id": 101}, {"id": 102}]})
    ado.on("GET", "/_apis/wit/workitems", {"value": [_wi(101, "One"), _wi(102, "Two")]})

    payload = call("azure_devops_query_work_items", {"query": "SELECT [System.Id] FROM WorkItems"})
    assert payload["count"] == 2
    assert "#101" in payload["result"] and "#102" in payload["result"]
    assert ado.first("/_apis/wit/wiql")["method"] == "POST"
    assert ado.first("/_apis/wit/workitems")["query"]["ids"] == ["101,102"]


def test_query_work_items_with_no_hits(configure, ado):
    configure()
    ado.on("POST", "/_apis/wit/wiql", {"workItems": []})
    payload = call("azure_devops_query_work_items", {"query": "SELECT [System.Id] FROM WorkItems"})
    assert payload["count"] == 0
    assert "No work items found" in payload["result"]


def test_create_work_item_builds_a_patch_document(configure, ado):
    configure()
    ado.on("POST", "/_apis/wit/workitems/$", _wi(200, "New one"))

    payload = call("azure_devops_create_work_item", {
        "type": "Bug",
        "title": "New one",
        "description": "<p>desc</p>",
        "fields": {"System.Priority": "1"},
    })
    assert payload["id"] == 200
    patch = ado.first("/_apis/wit/workitems/$")["body"]
    assert {"op": "add", "path": "/fields/System.Title", "value": "New one"} in patch
    assert {"op": "add", "path": "/fields/System.Description", "value": "<p>desc</p>"} in patch
    assert {"op": "add", "path": "/fields/System.Priority", "value": "1"} in patch


def test_create_work_item_reports_missing_mandatory_fields(configure, ado):
    configure()
    ado.fail(
        "POST",
        "/_apis/wit/workitems/$",
        400,
        {
            "message": "TF401320: Rule Error for field Description.",
            "typeKey": "RuleValidationException",
            "customProperties": {
                "RuleValidationErrors": [
                    {
                        "fieldReferenceName": "System.Description",
                        "errorMessage": "TF401320: Rule Error for field Description.",
                    }
                ]
            },
        },
    )

    payload = call("azure_devops_create_work_item", {"type": "User Story", "title": "No description"})
    assert "System.Description" in payload["error"]
    assert "Authentication" not in payload["error"]


def test_update_work_item_uses_replace_operations(configure, ado):
    configure()
    ado.on("PATCH", "/_apis/wit/workitems/101", _wi())
    call("azure_devops_update_work_item", {"id": 101, "fields": {"System.State": "Closed"}})

    patch = ado.first("/_apis/wit/workitems/101")["body"]
    assert patch == [{"op": "replace", "path": "/fields/System.State", "value": "Closed"}]


def test_add_work_item_comment_live(configure, ado):
    configure()
    ado.on("POST", "/comments", {"id": 5, "text": "hello"})
    payload = call("azure_devops_add_work_item_comment", {"workItemId": 101, "text": "hello"})
    assert payload["commentId"] == 5
    assert ado.first("/comments")["body"] == {"text": "hello"}


def test_manage_work_item_links_add_uses_the_configured_org_url(configure, ado):
    configure()
    ado.on("PATCH", "/_apis/wit/workitems/101", _wi())

    call("azure_devops_manage_work_item_links", {
        "workItemId": 101,
        "operation": "add",
        "relationType": "System.LinkTypes.Hierarchy-Forward",
        "targetId": 102,
    })
    patch = ado.first("/_apis/wit/workitems/101")["body"]
    assert patch[0]["op"] == "add"
    assert patch[0]["value"]["rel"] == "System.LinkTypes.Hierarchy-Forward"
    assert patch[0]["value"]["url"].endswith("/_apis/wit/workItems/102")


def test_manage_work_item_links_remove_expands_relations_first(configure, ado):
    configure()
    ado.on_fn(
        "GET",
        "/_apis/wit/workitems/101",
        lambda body, path, query: (200, {
            "id": 101,
            "relations": [
                {"rel": "System.LinkTypes.Related", "url": "https://x/_apis/wit/workItems/999"},
                {"rel": "System.LinkTypes.Related", "url": "https://x/_apis/wit/workItems/102"},
            ],
        }),
    )
    ado.on("PATCH", "/_apis/wit/workitems/101", _wi())

    payload = call("azure_devops_manage_work_item_links", {
        "workItemId": 101,
        "operation": "remove",
        "relationType": "System.LinkTypes.Related",
        "targetId": 102,
    })
    assert "Removed" in payload["result"]
    # The GET must ask for relations, otherwise the index cannot be found.
    assert ado.requests("/_apis/wit/workitems/101", "GET")[0]["query"]["$expand"] == ["relations"]
    assert ado.first("/_apis/wit/workitems/101", "PATCH")["body"] == [
        {"op": "remove", "path": "/relations/1"}
    ]


def test_manage_work_item_links_reports_a_missing_link(configure, ado):
    configure()
    ado.on("GET", "/_apis/wit/workitems/101", {"id": 101, "relations": []})
    payload = call("azure_devops_manage_work_item_links", {
        "workItemId": 101,
        "operation": "remove",
        "relationType": "System.LinkTypes.Related",
        "targetId": 102,
    })
    assert "No relations found" in payload["error"]


# ---------------------------------------------------------------------------
# Live: boards, sprints, capacity
# ---------------------------------------------------------------------------


def test_team_is_required_for_board_tools(configure):
    configure(team="")
    payload = call("azure_devops_list_boards", {})
    assert "No team specified" in payload["error"]
    assert "defaultTeam" in payload["error"]


def test_team_parameter_overrides_the_config(configure, ado):
    configure(team="Engineering")
    ado.on("GET", "/_apis/work/boards", {"value": [{"id": "stories", "name": "Stories"}]})

    call("azure_devops_list_boards", {"team": "Platform"})
    assert "/Platform/_apis/work/boards" in ado.calls[0]["path"]


def test_list_iterations_forwards_the_timeframe(configure, ado):
    configure()
    ado.on("GET", "/teamsettings/iterations", {"value": []})
    call("azure_devops_list_iterations", {"timeframe": "current"})
    assert ado.calls[0]["query"]["$timeframe"] == ["current"]


def test_get_iteration_work_items_resolves_target_ids(configure, ado):
    configure()
    ado.on("GET", "/iterations/sprint-3/workitems", {
        "workItemRelations": [{"target": {"id": 101}}, {"target": {"id": 102}}],
    })
    ado.on("GET", "/_apis/wit/workitems", {"value": [_wi(101, "One"), _wi(102, "Two")]})

    payload = call("azure_devops_get_iteration_work_items", {"iterationId": "sprint-3"})
    assert payload["count"] == 2
    assert ado.first("/_apis/wit/workitems")["query"]["ids"] == ["101,102"]


def test_get_capacity_live(configure, ado):
    configure()
    ado.on("GET", "/capacities", {
        "teamMembers": [
            {
                "teamMember": {"displayName": "Jane"},
                "activities": [{"name": "Development", "capacityPerDay": 6}],
                "daysOff": [],
            }
        ],
        "totalCapacityPerDay": 6,
        "totalDaysOff": 0,
    })
    payload = call("azure_devops_get_capacity", {"iterationId": "sprint-3"})
    assert "Jane" in payload["result"]
    assert "**Total capacity:** 6" in payload["result"]


def test_set_board_columns_assigns_column_types(configure, ado):
    configure()
    ado.on("PUT", "/columns", [{"name": "New"}, {"name": "Doing"}, {"name": "Done"}])

    call("azure_devops_set_board_columns", {
        "boardId": "stories",
        "columns": [{"name": "New"}, {"name": "Doing"}, {"name": "Done"}],
    })
    body = ado.first("/columns")["body"]
    assert [column["columnType"] for column in body] == [0, 1, 2]
    assert ado.first("/columns")["method"] == "PUT"


def test_set_iteration_add_posts_the_iteration_id(configure, ado):
    configure()
    ado.on("POST", "/teamsettings/iterations", {"id": "sprint-3"})
    call("azure_devops_set_iteration", {"iterationId": "sprint-3", "operation": "add"})
    assert ado.first("/teamsettings/iterations")["body"] == {"id": "sprint-3"}


def test_set_iteration_remove_deletes(configure, ado):
    configure()
    ado.on("DELETE", "/teamsettings/iterations/sprint-3", None, status=204)
    payload = call("azure_devops_set_iteration", {"iterationId": "sprint-3", "operation": "remove"})
    assert ado.first("/teamsettings/iterations/sprint-3")["method"] == "DELETE"
    assert "Removed" in payload["result"]


def test_set_capacity_sends_activities_and_days_off(configure, ado):
    configure()
    ado.on("PUT", "/capacities", [])
    call("azure_devops_set_capacity", {
        "iterationId": "sprint-3",
        "capacities": [
            {
                "teamMemberId": "jane@example.com",
                "activities": [{"name": "Development", "capacityPerDay": 6}],
                "daysOff": [{"start": "2026-09-03", "end": "2026-09-03"}],
            }
        ],
    })
    body = ado.first("/capacities")["body"]
    assert body[0]["teamMember"] == {"id": "jane@example.com"}
    assert body[0]["activities"] == [{"name": "Development", "capacityPerDay": 6}]
    assert body[0]["daysOff"] == [{"start": "2026-09-03", "end": "2026-09-03"}]


# ---------------------------------------------------------------------------
# Live: repositories and pull requests
# ---------------------------------------------------------------------------


def test_list_pull_requests_passes_the_status_name(configure, ado):
    configure()
    ado.on("GET", "/_apis/git/pullrequests", {"value": []})
    call("azure_devops_list_pull_requests", {"status": "completed", "top": 5})
    query = ado.calls[0]["query"]
    assert query["searchCriteria.status"] == ["completed"]
    assert query["$top"] == ["5"]


def test_list_pull_requests_rejects_an_unknown_status(configure, ado):
    configure()
    payload = call("azure_devops_list_pull_requests", {"status": "nonsense"})
    assert "status must be one of" in payload["error"]


def test_list_pull_requests_scoped_to_a_repository(configure, ado):
    configure()
    ado.on("GET", "/repositories/repo-webapp/pullrequests", {"value": []})
    call("azure_devops_list_pull_requests", {"repositoryId": "repo-webapp"})
    assert "/TestProject/_apis/git/repositories/repo-webapp/pullrequests" in ado.calls[0]["path"]


def test_creator_filter_is_applied_locally(configure, ado):
    configure()
    ado.on("GET", "/_apis/git/pullrequests", {
        "value": [
            {"pullRequestId": 1, "title": "A", "createdBy": {"displayName": "Jane Developer"}},
            {"pullRequestId": 2, "title": "B", "createdBy": {"displayName": "Bob"}},
        ]
    })
    payload = call("azure_devops_list_pull_requests", {"creator": "jane"})
    assert payload["count"] == 1
    assert "#1" in payload["result"]
    assert "#2" not in payload["result"]


def test_create_pull_request_body(configure, ado):
    configure()
    ado.on("POST", "/pullrequests", {"pullRequestId": 7, "title": "T"})

    payload = call("azure_devops_create_pull_request", {
        "repositoryId": "repo-webapp",
        "sourceRefName": "refs/heads/feature",
        "targetRefName": "refs/heads/main",
        "title": "T",
        "description": "Why",
        "isDraft": True,
    })
    assert payload["pullRequestId"] == 7
    body = ado.first("/pullrequests")["body"]
    assert body["sourceRefName"] == "refs/heads/feature"
    assert body["isDraft"] is True
    assert body["description"] == "Why"


def test_update_pull_request_maps_status_to_the_enum(configure, ado):
    configure()
    ado.on("PATCH", "/pullrequests/7", {"pullRequestId": 7})
    call("azure_devops_update_pull_request", {
        "repositoryId": "repo-webapp",
        "pullRequestId": 7,
        "status": "abandoned",
    })
    assert ado.first("/pullrequests/7")["body"] == {"status": 2}


def test_update_pull_request_without_changes_is_an_error(configure, ado):
    configure()
    payload = call("azure_devops_update_pull_request", {"repositoryId": "r", "pullRequestId": 7})
    assert "Nothing to update" in payload["error"]


def test_add_pull_request_comment_maps_thread_status(configure, ado):
    configure()
    ado.on("POST", "/threads", {"id": 9})
    payload = call("azure_devops_add_pull_request_comment", {
        "repositoryId": "repo-webapp",
        "pullRequestId": 7,
        "content": "hi",
        "threadStatus": "pending",
    })
    assert payload["threadId"] == 9
    body = ado.first("/threads")["body"]
    assert body["status"] == 6
    assert body["comments"] == [{"content": "hi", "commentType": 1}]


def test_set_vote_uses_the_real_identity_not_an_empty_id(configure, ado):
    """pi's tool sends an empty reviewer id and gets a 401; this one does not."""
    configure()
    ado.on("GET", "/_apis/connectionData", {"authenticatedUser": {"id": "identity-42"}})
    ado.on("PUT", "/reviewers/identity-42", {"vote": 10, "id": "identity-42"})

    payload = call("azure_devops_set_pull_request_vote", {
        "repositoryId": "repo-webapp",
        "pullRequestId": 7,
        "vote": "approve",
    })
    assert payload["vote"] == 10
    assert ado.first("/reviewers/identity-42")["method"] == "PUT"
    assert ado.first("/reviewers/identity-42")["body"] == {"vote": 10}


def test_set_vote_reports_an_unknown_choice(configure, ado):
    configure()
    payload = call("azure_devops_set_pull_request_vote", {
        "repositoryId": "r",
        "pullRequestId": 7,
        "vote": "maybe",
    })
    assert "vote must be one of" in payload["error"]


def test_autocomplete_uses_the_real_identity(configure, ado):
    configure()
    ado.on("GET", "/_apis/connectionData", {"authenticatedUser": {"id": "identity-42"}})
    ado.on("PATCH", "/pullrequests/7", {"pullRequestId": 7})

    call("azure_devops_set_pull_request_autocomplete", {
        "repositoryId": "repo-webapp",
        "pullRequestId": 7,
        "enabled": True,
    })
    assert ado.first("/pullrequests/7")["body"] == {"autoCompleteSetBy": {"id": "identity-42"}}


def test_autocomplete_can_be_disabled(configure, ado):
    configure()
    ado.on("PATCH", "/pullrequests/7", {"pullRequestId": 7})
    call("azure_devops_set_pull_request_autocomplete", {
        "repositoryId": "repo-webapp",
        "pullRequestId": 7,
        "enabled": False,
    })
    assert ado.first("/pullrequests/7")["body"] == {"autoCompleteSetBy": None}


def test_link_pr_work_items_builds_the_artifact_uri_and_uses_7_0(configure, ado):
    configure()
    ado.on("GET", "/pullrequests/7", {
        "pullRequestId": 7,
        "repository": {"id": "repo-guid", "project": {"id": "project-guid"}},
    })
    ado.on("PATCH", "/workitems/101", {"id": 101})

    payload = call("azure_devops_link_pr_work_items", {
        "repositoryId": "repo-webapp",
        "pullRequestId": 7,
        "workItemIds": [101],
        "operation": "add",
    })
    assert payload["artifactUri"] == "vstfs:///Git/PullRequestId/project-guid%2Frepo-guid%2F7"
    patch_call = ado.first("/workitems/101", "PATCH")
    assert patch_call["query"]["api-version"] == ["7.0"]
    assert patch_call["body"][0]["value"]["rel"] == "ArtifactLink"


def test_get_policy_evaluations_resolves_the_project_guid(configure, ado):
    configure()
    ado.on("GET", "/_apis/projects", {"value": [{"id": "project-guid", "name": "TestProject"}]})
    ado.on("GET", "/_apis/policy/evaluations", {"value": [
        {"policyDisplayName": "Reviewers", "status": "approved"}
    ]})

    call("azure_devops_get_policy_evaluations", {"pullRequestId": 7})
    artifact = ado.first("/_apis/policy/evaluations")["query"]["artifactId"][0]
    assert artifact == "vstfs:///CodeReview/CodeReviewId/project-guid/7"


# ---------------------------------------------------------------------------
# Live: pipelines
# ---------------------------------------------------------------------------


def test_list_runs_reshapes_builds_and_filters_the_branch(configure, ado):
    configure()
    ado.on("GET", "/_apis/build/builds", {"value": [
        {
            "id": 42,
            "buildNumber": "20260901.1",
            "status": 2,
            "result": 2,
            "definition": {"id": 1, "name": "CI"},
            "startTime": "2026-09-01T10:00:00Z",
            "finishTime": "2026-09-01T10:05:00Z",
            "sourceBranch": "refs/heads/main",
        }
    ]})

    payload = call("azure_devops_list_runs", {"pipelineId": 1, "branch": "main", "result": "succeeded"})
    assert payload["count"] == 1
    assert "#42 CI" in payload["result"]
    query = ado.calls[0]["query"]
    assert query["definitions"] == ["1"]
    assert query["branchName"] == ["refs/heads/main"]
    assert query["resultFilter"] == ["succeeded"]


def test_list_runs_accepts_the_numeric_filters_pi_used(configure, ado):
    configure()
    ado.on("GET", "/_apis/build/builds", {"value": []})
    call("azure_devops_list_runs", {"status": "2", "result": "2"})
    query = ado.calls[0]["query"]
    assert query["statusFilter"] == ["completed"]
    assert query["resultFilter"] == ["succeeded"]


def test_run_pipeline_body_includes_resources_and_parameters(configure, ado):
    configure()
    ado.on("POST", "/runs", {"id": 99, "state": "inProgress"})

    payload = call("azure_devops_run_pipeline", {
        "pipelineId": 1,
        "branch": "feature/x",
        "templateParameters": {"env": "dev"},
        "variables": {"greeting": "hi"},
        "stagesToSkip": ["Deploy"],
    })
    assert payload["runId"] == 99
    body = ado.first("/runs")["body"]
    assert body["resources"]["repositories"]["self"]["refName"] == "refs/heads/feature/x"
    assert body["templateParameters"] == {"env": "dev"}
    assert body["variables"] == {"greeting": {"value": "hi"}}
    assert body["stagesToSkip"] == ["Deploy"]


def test_cancel_run_sets_the_cancelling_status(configure, ado):
    configure()
    ado.on("PATCH", "/builds/42", {"id": 42})
    call("azure_devops_cancel_run", {"pipelineId": 1, "runId": 42})
    assert ado.first("/builds/42")["body"] == {"status": 4}


def test_retry_run_sets_the_retry_query_flag(configure, ado):
    configure()
    ado.on("PATCH", "/builds/42", {"id": 43})
    payload = call("azure_devops_retry_run", {"pipelineId": 1, "runId": 42})
    assert ado.first("/builds/42")["query"]["retry"] == ["true"]
    assert payload["newRunId"] == 43


def test_get_run_logs_formats_each_entry(configure, ado):
    configure()
    ado.on("GET", "/builds/42/logs", {"value": [
        {"id": 1, "lineCount": 12, "createdOn": "2026-09-01T10:00:00Z"}
    ]})
    payload = call("azure_devops_get_run_logs", {"pipelineId": 1, "runId": 42})
    assert "Log #1 (12 lines) — 2026-09-01 10:00:00" in payload["result"]


# ---------------------------------------------------------------------------
# Live: test plans
# ---------------------------------------------------------------------------


def test_list_test_points_live(configure, ado):
    configure()
    ado.on("GET", "/TestPoint", {"value": [
        {
            "id": 1,
            "testCaseReference": {"id": 501, "name": "Login"},
            "configuration": {"id": "1", "name": "Chrome"},
            "outcome": "passed",
            "tester": {"displayName": "Jane"},
        }
    ]})
    payload = call("azure_devops_list_test_points", {"planId": 101, "suiteId": 301})
    assert payload["count"] == 1
    assert "🟢 passed" in payload["result"]


def test_create_test_run_collects_point_ids_from_the_suites(configure, ado):
    configure()
    ado.on("GET", "/TestPoint", {"value": [{"id": 11}, {"id": 12}]})
    ado.on("POST", "/_apis/test/runs", {"id": 601, "name": "Run"})

    payload = call("azure_devops_create_test_run", {"planId": 101, "suiteIds": [301], "name": "Smoke"})
    assert payload["runId"] == 601
    body = ado.first("/_apis/test/runs")["body"]
    assert body["pointIds"] == [11, 12]
    assert body["plan"] == {"id": 101}
    assert body["name"] == "Smoke"


def test_create_test_run_without_points_is_an_error(configure, ado):
    configure()
    ado.on("GET", "/TestPoint", {"value": []})
    payload = call("azure_devops_create_test_run", {"planId": 101, "suiteIds": [301]})
    assert "No test points found" in payload["error"]


def test_update_test_results_maps_outcomes_to_the_enum(configure, ado):
    configure()
    ado.on("PATCH", "/results", {"value": [{"id": 1, "outcome": "Passed", "testCaseTitle": "Login"}]})

    payload = call("azure_devops_update_test_results", {
        "runId": 501,
        "results": [{"id": 1, "outcome": "passed", "comment": "ok"}],
    })
    assert payload["updatedCount"] == 1
    body = ado.first("/results")["body"]
    assert body == [{"id": 1, "outcome": 2, "comment": "ok"}]
    assert ado.first("/results")["method"] == "PATCH"


def test_update_test_results_rejects_an_unknown_outcome(configure, ado):
    configure()
    payload = call("azure_devops_update_test_results", {
        "runId": 501,
        "results": [{"id": 1, "outcome": "sort-of-worked"}],
    })
    assert "Unknown outcome" in payload["error"]


# ---------------------------------------------------------------------------
# Live: doctor and overrides
# ---------------------------------------------------------------------------


def test_doctor_reports_each_connection(configure, ado):
    configure()
    ado.on("GET", "/workitemtypes", {"count": 3, "value": [{"name": "Bug"}, {"name": "Task"}, {"name": "Story"}]})

    payload = call("azure_devops_doctor", {})
    assert "Authenticated via **pat**" in payload["result"]
    assert "3 work item types available" in payload["result"]


def test_doctor_reports_a_failed_connection(configure, ado):
    configure()
    ado.fail("GET", "/workitemtypes", 401, {"message": "Unauthorized"})

    payload = call("azure_devops_doctor", {})
    assert "❌ Failed" in payload["result"]


def test_doctor_in_mock_mode_makes_no_call(configure, ado):
    configure()
    payload = call("azure_devops_doctor", {"mock": True})
    assert payload["mock"] is True
    assert ado.calls == []


def test_doctor_when_nothing_is_configured(isolated_config):
    sub("config").load_config()
    payload = call("azure_devops_doctor", {})
    assert "Edit" in payload["error"]


def test_org_and_project_parameters_retarget_a_tool(isolated_config, ado):
    from conftest import write_config

    write_config(isolated_config, {
        "orgs": [
            {"name": "one", "url": ado.url, "projects": [{"name": "P1", "pat": "p1"}]},
            {"name": "two", "url": f"{ado.url}/two", "projects": [{"name": "P2", "pat": "p2"}]},
        ]
    })
    ado.on("GET", "/two/P2/_apis/wit/workitemtypes", {"value": [{"name": "Bug"}]})

    payload = call("azure_devops_list_work_item_types", {"org": "two", "project": "P2"})
    assert payload["count"] == 1
    assert ado.calls[0]["path"] == "/two/P2/_apis/wit/workitemtypes"


def test_an_unknown_org_parameter_is_a_clear_error(isolated_config, ado):
    from conftest import write_config

    write_config(isolated_config, {
        "orgs": [{"name": "one", "url": ado.url, "projects": [{"name": "P1", "pat": "p1"}]}]
    })
    payload = call("azure_devops_list_work_item_types", {"org": "nope"})
    assert "not found" in payload["error"]


# ---------------------------------------------------------------------------
# Handler contract
# ---------------------------------------------------------------------------


def test_invalid_arguments_come_back_as_an_error_not_an_exception(configure):
    configure()
    payload = call("azure_devops_get_work_item", {"id": {"nested": "object"}})
    assert "error" in payload


def test_successful_results_are_json_strings(configure, ado):
    configure()
    ado.on("GET", "/workitems/101", _wi())
    tools = sub("tools")
    handler = dict((schema["name"], fn) for schema, fn in tools.TOOLS)["azure_devops_get_work_item"]
    raw = handler({"id": 101})
    assert isinstance(raw, str)
    json.loads(raw)
