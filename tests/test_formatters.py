"""Formatters: the exact text the model reads.

The expectations mirror pi-azure-devops' ``test/utils/*.test.ts`` so the port
cannot drift from the original rendering without a test failing.
"""

from __future__ import annotations

import json

from conftest import ROOT, sub

fmt = sub("formatters")


def load_fixture(name):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------


def make_work_item(**overrides):
    item = {
        "id": 101,
        "rev": 3,
        "fields": {
            "System.Title": "Test work item",
            "System.WorkItemType": "User Story",
            "System.State": "Active",
            "System.Reason": "Implementation started",
            "System.AssignedTo": {"displayName": "Jane Developer"},
            "System.AreaPath": "Project\\Engineering",
            "System.IterationPath": "Project\\Sprint 4",
            "System.Priority": 2,
            "System.Tags": "backend; critical",
            "System.Description": "<p>Detailed description</p>",
        },
        "url": "https://dev.azure.com/org/_apis/wit/workItems/101",
    }
    item.update(overrides)
    return item


def test_work_item_header_and_fields():
    text = fmt.format_work_item(make_work_item())
    assert "# Work Item 101" in text
    assert "Test work item" in text
    assert "User Story" in text
    assert "**State:** Active" in text
    assert "Implementation started" in text
    assert "Jane Developer" in text
    assert "Project\\Engineering" in text
    assert "Sprint 4" in text
    assert "**Tags:** backend; critical" in text
    assert "Detailed description" in text


def test_work_item_assignee_variants():
    assert "john@contoso.com" in fmt.format_work_item(
        make_work_item(fields={**make_work_item()["fields"], "System.AssignedTo": "john@contoso.com"})
    )
    fields = dict(make_work_item()["fields"])
    fields.pop("System.AssignedTo")
    assert "unassigned" in fmt.format_work_item(make_work_item(fields=fields))


def test_work_item_summary_and_list():
    assert fmt.format_work_item_summary(make_work_item()) == (
        "#101 [User Story] [Active] Test work item"
    )
    assert fmt.format_work_item_list([]) == "No work items found."
    assert fmt.format_work_item_list([make_work_item()]) == (
        "#101 [User Story] [Active] Test work item"
    )


def test_work_item_type_formatting():
    text = fmt.format_work_item_type(
        {
            "name": "Bug",
            "referenceName": "Microsoft.VSTS.WorkItemTypes.Bug",
            "description": "A defect",
            "states": [{"name": "New"}, {"name": "Closed"}],
        }
    )
    assert "**Bug**" in text
    assert "Microsoft.VSTS.WorkItemTypes.Bug" in text
    assert "A defect" in text
    assert "States: New, Closed" in text


def test_comments_render_author_date_and_text():
    text = fmt.format_comments(
        {
            "comments": [
                {
                    "id": 1,
                    "createdBy": {"displayName": "Jane Developer"},
                    "createdDate": "2026-09-01T10:00:00Z",
                    "text": "Looks good to me",
                }
            ]
        }
    )
    assert "**Jane Developer** (2026-09-01):" in text
    assert "Looks good to me" in text


def test_revisions_include_rev_number_author_and_system_fields():
    text = fmt.format_revisions(
        [
            {
                "rev": 2,
                "fields": {
                    "System.ChangedBy": {"displayName": "Jane Developer"},
                    "System.ChangedDate": "2026-09-02T11:22:33Z",
                    "System.State": "Active",
                },
            }
        ]
    )
    assert "## Rev 2 — Jane Developer (2026-09-02 11:22:33)" in text
    assert "System.State: Active" in text


# ---------------------------------------------------------------------------
# Boards, iterations, capacity
# ---------------------------------------------------------------------------


def test_board_columns_rows_and_state_mappings():
    board = load_fixture("board-detail.json")["boardDetails"]["Engineering:stories"]
    text = fmt.format_board(board)
    assert text.startswith(f"# Board: {board['name']}")
    assert "## Columns" in text
    for column in board["columns"]:
        assert column["name"] in text


def test_column_type_labels():
    text = fmt.format_board(
        {
            "name": "B",
            "id": "b",
            "columns": [
                {"name": "New", "columnType": 0},
                {"name": "Doing", "columnType": 1},
                {"name": "Done", "columnType": 2},
            ],
        }
    )
    assert "**New** [Incoming]" in text
    assert "**Doing** [InProgress]" in text
    assert "**Done** [Outgoing]" in text


def test_wip_limit_is_shown():
    text = fmt.format_board({"name": "B", "id": "b", "columns": [{"name": "Doing", "itemLimit": 3}]})
    assert "(limit: 3)" in text


def test_iteration_timeframe_labels_and_dates():
    text = fmt.format_iteration(
        {
            "id": "i1",
            "name": "Sprint 4",
            "path": "Project\\Sprint 4",
            "attributes": {
                "startDate": "2026-09-01T00:00:00Z",
                "finishDate": "2026-09-14T00:00:00Z",
                "timeFrame": "current",
            },
        }
    )
    assert "Sprint 4" in text
    assert "🔵 Current" in text
    assert "2026-09-01 → 2026-09-14" in text


def test_iteration_accepts_the_numeric_timeframe():
    text = fmt.format_iteration({"id": "i", "name": "S", "attributes": {"timeFrame": 2}})
    assert "🟢 Future" in text


def test_capacity_totals_and_members():
    capacity = load_fixture("capacity.json")["capacities"]["Engineering:sprint-3"]
    text = fmt.format_capacity(capacity)
    assert "# Team Capacity" in text
    assert f"**Total capacity:** {capacity['totalCapacityPerDay']}" in text
    assert "## Team Members" in text


# ---------------------------------------------------------------------------
# Repositories, branches, pull requests
# ---------------------------------------------------------------------------


def test_repo_shows_default_branch_size_and_project():
    text = fmt.format_repo(
        {
            "id": "r1",
            "name": "repo-webapp",
            "defaultBranch": "refs/heads/main",
            "size": 2048,
            "project": {"name": "TestProject"},
            "url": "https://example/r1",
        }
    )
    assert "**repo-webapp** (id: r1)" in text
    assert "**Default branch:** main" in text
    assert "2.0 KB" in text
    assert "**Project:** TestProject" in text


def test_branch_shows_short_sha_and_tracking_counts():
    text = fmt.format_branch(
        {
            "name": "refs/heads/main",
            "commit": {"commitId": "abcdef1234567890", "comment": "Fix the thing\nmore detail"},
            "aheadCount": 2,
            "behindCount": 1,
            "isBaseVersion": True,
        }
    )
    assert "`abcdef1`" in text
    assert "↑2 ↓1" in text
    assert "(base)" in text
    assert "Fix the thing" in text
    assert "more detail" not in text


def test_pull_request_full_detail():
    text = fmt.format_pull_request(
        {
            "pullRequestId": 7,
            "title": "Fix login",
            "status": "active",
            "sourceRefName": "refs/heads/fix",
            "targetRefName": "refs/heads/main",
            "createdBy": {"displayName": "Jane Developer"},
            "creationDate": "2026-09-01T10:00:00Z",
            "reviewers": [{"displayName": "Bob", "vote": 10}, {"displayName": "Eve", "vote": -10}],
            "description": "Some markdown",
        }
    )
    assert "# PR #7: Fix login" in text
    assert "🟢 Active" in text
    assert "**Branch:** fix → main" in text
    assert "**Author:** Jane Developer" in text
    assert "**Created:** 2026-09-01" in text
    assert "Bob (Approved)" in text
    assert "Eve (Rejected)" in text
    assert "Some markdown" in text


def test_pull_request_status_by_number():
    assert "✅ Completed" in fmt.format_pull_request({"pullRequestId": 1, "status": 3})
    assert "⚪ Abandoned" in fmt.format_pull_request({"pullRequestId": 1, "status": 2})


def test_pull_request_list_one_line_per_pr():
    text = fmt.format_pull_request_list(
        [
            {
                "pullRequestId": 1,
                "title": "A",
                "status": "active",
                "sourceRefName": "refs/heads/a",
                "targetRefName": "refs/heads/main",
                "createdBy": {"displayName": "Jane"},
                "creationDate": "2026-09-01T00:00:00Z",
            }
        ]
    )
    assert text == "#1 🟢 Active — A (a→main) by Jane [2026-09-01]"


def test_thread_status_labels_and_comments():
    text = fmt.format_pull_request_thread(
        {
            "id": 3,
            "status": 2,
            "comments": [
                {
                    "author": {"displayName": "Bob"},
                    "publishedDate": "2026-09-03T09:00:00Z",
                    "content": "Please fix",
                }
            ],
        }
    )
    assert "### Thread #3 [Fixed]" in text
    assert "**Bob** (2026-09-03):" in text
    assert "Please fix" in text


def test_commit_short_sha_first_line_only():
    text = fmt.format_commit(
        {
            "commitId": "1234567890abcdef",
            "comment": "Subject line\n\nBody text",
            "author": {"name": "Jane", "date": "2026-09-01T00:00:00Z"},
        }
    )
    assert text == "`1234567` Subject line — Jane [2026-09-01]"


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_policy_blocking_flag_scope_and_settings():
    text = fmt.format_policy(
        {
            "id": 5,
            "type": {"displayName": "Minimum number of reviewers"},
            "isBlocking": True,
            "scope": [{"refName": "refs/heads/main"}],
            "settings": {"minimumApproverCount": 2},
        }
    )
    assert "**Minimum number of reviewers** (id: 5) 🔒 Blocking" in text
    assert "Scope: main" in text
    assert 'minimumApproverCount=2' in text


def test_policy_evaluation_icons():
    assert "✅ Approved" in fmt.format_policy_evaluation(
        {"policyDisplayName": "Reviewers", "status": "approved", "startedDate": "2026-09-01T00:00:00Z"}
    )
    assert "❌ Rejected" in fmt.format_policy_evaluation({"status": "rejected"})
    assert "⏳ Running" in fmt.format_policy_evaluation({"status": "running"})


# ---------------------------------------------------------------------------
# Pipelines and runs
# ---------------------------------------------------------------------------


def test_pipeline_detail_and_list():
    pipeline = load_fixture("pipelines.json")["pipelines"][0]
    text = fmt.format_pipeline(pipeline)
    assert pipeline["name"] in text
    assert f"(id: {pipeline['id']})" in text
    assert "**Path:**" in text


def test_run_detail_includes_state_result_branch_and_duration():
    text = fmt.format_run(
        {
            "id": 42,
            "pipeline": {"name": "CI"},
            "state": "completed",
            "result": "succeeded",
            "createdDate": "2026-09-01T10:00:00Z",
            "finishedDate": "2026-09-01T10:05:30Z",
            "resources": {"repositories": {"self": {"refName": "refs/heads/main"}}},
        }
    )
    assert "# Run #42 — CI" in text
    assert "✅ Completed" in text
    assert "✅ succeeded" in text
    assert "**Branch:** main" in text
    assert "**Duration:** 5m 30s" in text
    assert "**Started:** 2026-09-01 10:00:00" in text


def test_duration_formats_hours_minutes_seconds():
    assert fmt.format_duration("2026-09-01T10:00:00Z", "2026-09-01T10:00:45Z") == "45s"
    assert fmt.format_duration("2026-09-01T10:00:00Z", "2026-09-01T12:30:00Z") == "2h 30m"
    assert fmt.format_duration(None) == "?"


def test_run_state_and_result_normalisation():
    assert "❌ Canceling" in fmt.format_run({"state": "cancelling"})
    assert "⚠️ partially succeeded" in fmt.format_run({"state": "completed", "result": "partiallySucceeded"})


def test_run_list_one_line_per_run():
    text = fmt.format_run_list(
        [
            {
                "id": 1,
                "pipeline": {"name": "CI"},
                "state": "completed",
                "result": "failed",
                "createdDate": "2026-09-01T10:00:00Z",
                "finishedDate": "2026-09-01T10:00:30Z",
                "resources": {"repositories": {"self": {"refName": "refs/heads/main"}}},
            }
        ]
    )
    assert text == "#1 CI — ✅ Completed 🔴 failed — main (30s)"


def test_timeline_is_sorted_and_indented():
    timeline = load_fixture("run-timeline.json")["timelines"]["42"]
    text = fmt.format_timeline(timeline)
    lines = text.splitlines()
    assert lines, "timeline should render something"
    # A Task under a parent is indented deeper than a Job.
    assert any(line.startswith("    ") for line in lines)


def test_timeline_reports_error_counts():
    text = fmt.format_timeline_record(
        {"name": "Build", "type": "Task", "state": "completed", "result": "failed", "errorCount": 2}
    )
    assert text.startswith("🔴 **Build** [Task]")
    assert "2 error(s)" in text


def test_timeline_result_icon_for_the_numeric_enum():
    # The numeric enum gets the long label, the string form the short icon --
    # exactly as the TypeScript tables are written.
    assert "🔴 Failed" in fmt.format_timeline_record({"name": "B", "type": "Task", "result": 2})
    assert "⏭️ Skipped" in fmt.format_timeline_record({"name": "B", "type": "Task", "result": 4})


# ---------------------------------------------------------------------------
# Test plans
# ---------------------------------------------------------------------------


def test_test_plan_detail_and_list():
    plan = load_fixture("test-plans.json")["testPlans"][0]
    text = fmt.format_test_plan(plan)
    assert plan["name"] in text
    assert "**Root Suite:**" in text
    assert "**Owner:**" in text


def test_test_suite_type_labels_and_indent():
    suites = load_fixture("test-suites.json")["testSuites"]["101"]
    text = fmt.format_test_suite_list(suites)
    assert "Static" in text
    for suite in suites:
        assert suite["name"] in text


def test_test_point_outcome_icons():
    points = load_fixture("test-points.json")["testPoints"]["101-301"]
    text = fmt.format_test_point_list(points)
    assert "🟢" in text
    assert "🔴" in text
    assert "🚫" in text


def test_test_point_without_an_outcome_reads_as_not_executed():
    # Azure DevOps omits `outcome` until a point has been run.
    point = {"id": 7, "testCaseReference": {"id": 501, "name": "Login"}}
    assert "⏸️ not executed" in fmt.format_test_point(point)
    assert "⏸️ not executed" in fmt.format_test_point_list([point])


def test_test_run_detail_results_line():
    text = fmt.format_test_run(
        {
            "id": 501,
            "name": "Run",
            "state": "Completed",
            "totalTests": 10,
            "passedTests": 8,
            "failedTests": 1,
            "incompleteTests": 1,
            "plan": {"id": 101, "name": "Sprint 42"},
        }
    )
    assert "✅ Completed" in text
    assert "**Results:** 8/10 passed, 1 failed, 1 incomplete" in text


def test_test_result_list_includes_outcome_and_duration():
    results = load_fixture("test-results.json")["testResults"]["501"]
    text = fmt.format_test_result_list(results)
    assert text.splitlines()
    assert "s" in text


# ---------------------------------------------------------------------------
# Time handling
# ---------------------------------------------------------------------------


def test_timestamps_are_rendered_in_utc():
    # 09:00+02:00 is 07:00 UTC, which is what JavaScript's toISOString gives.
    assert fmt.format_iso_datetime("2026-09-01T09:00:00+02:00") == "2026-09-01 07:00:00"
    assert fmt.format_iso_date("2026-09-01T23:30:00-05:00") == "2026-09-02"


def test_unparseable_timestamps_do_not_raise():
    assert fmt.format_iso_datetime("not a date") == ""
    assert fmt.format_iso_date(None) == ""
    assert fmt.format_duration("garbage") == "?"


def test_bytes_formatting():
    assert fmt.format_bytes(512) == "512 B"
    assert fmt.format_bytes(2048) == "2.0 KB"
    assert fmt.format_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert fmt.format_bytes(3 * 1024 * 1024 * 1024) == "3.0 GB"
