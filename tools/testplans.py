"""Test plan, suite, case, point, run and result tools.

Note the two different REST areas: plans/suites/cases/points live under
``_apis/testplan/...``, while runs and results live under ``_apis/test/...``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .. import client, mocks
from ..formatters import (
    format_test_case_list,
    format_test_plan,
    format_test_plan_list,
    format_test_point_list,
    format_test_result_list,
    format_test_run,
    format_test_run_list,
    format_test_suite,
    format_test_suite_list,
)
from ._base import (
    MOCK_PROPERTY,
    ORG_PROPERTY,
    PROJECT_PROPERTY,
    config_for,
    error,
    is_mock,
    opt_bool,
    opt_dict_list,
    opt_int,
    opt_int_list,
    opt_str,
    req_int,
    result,
    schema,
    tool_handler,
)

OUTCOME_MAP = {
    "passed": 2,
    "failed": 3,
    "inconclusive": 4,
    "timeout": 5,
    "aborted": 6,
    "blocked": 7,
    "notexecuted": 8,
    "warning": 9,
    "error": 10,
    "notapplicable": 11,
    "paused": 12,
    "inprogress": 13,
    "notimpacted": 14,
}

LIST_TEST_PLANS_SCHEMA = schema(
    "azure_devops_list_test_plans",
    "List test plans in the configured Azure DevOps project. "
    "Returns plan name, ID, state, dates, owner, and root suite.",
    {
        "owner": {"type": "string", "description": "Filter by owner display name or email"},
        "filterActivePlans": {"type": "boolean", "description": "Only return active plans"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_test_plans(args: Dict[str, Any]) -> str:
    config = config_for(args)

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_test_plans(opt_bool(args, "filterActivePlans"))

    try:
        plans = client.list_test_plans(
            config,
            owner=opt_str(args, "owner"),
            filter_active=opt_bool(args, "filterActivePlans"),
        )
        if not plans:
            return result("No test plans found in this project.", count=0)
        return result(format_test_plan_list(plans), count=len(plans))
    except Exception as exc:
        return error(f"Failed to list test plans: {client.format_ado_error(exc)}")


GET_TEST_PLAN_SCHEMA = schema(
    "azure_devops_get_test_plan",
    "Get a single test plan by ID. Returns name, state, iteration, dates, owner, root suite, and area path.",
    {
        "planId": {"type": "number", "description": "Test plan ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["planId"],
)


@tool_handler
def get_test_plan(args: Dict[str, Any]) -> str:
    config = config_for(args)
    plan_id = req_int(args, "planId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_test_plan(plan_id)

    try:
        plan = client.get_test_plan(config, plan_id)
        if not plan:
            return error(f"Test plan #{plan_id} not found.")
        return result(format_test_plan(plan), planId=plan.get("id"))
    except Exception as exc:
        return error(f"Failed to get test plan #{plan_id}: {client.format_ado_error(exc)}")


LIST_TEST_SUITES_SCHEMA = schema(
    "azure_devops_list_test_suites",
    "List test suites for a test plan. Returns suite ID, name, type (static, dynamic, requirement-based), "
    "parent, and test case count.",
    {
        "planId": {"type": "number", "description": "Test plan ID"},
        "expand": {"type": "number", "description": "Suite expand level (0=none, 1=children, 2=defaultTesters)"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["planId"],
)


@tool_handler
def list_test_suites(args: Dict[str, Any]) -> str:
    config = config_for(args)
    plan_id = req_int(args, "planId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_test_suites(plan_id)

    try:
        suites = client.list_test_suites(config, plan_id, expand=opt_int(args, "expand"))
        if not suites:
            return result(f"No test suites found for plan #{plan_id}.", planId=plan_id, count=0)
        return result(format_test_suite_list(suites), planId=plan_id, count=len(suites))
    except Exception as exc:
        return error(f"Failed to list test suites for plan #{plan_id}: {client.format_ado_error(exc)}")


GET_TEST_SUITE_SCHEMA = schema(
    "azure_devops_get_test_suite",
    "Get a single test suite by plan ID and suite ID. "
    "Returns suite name, type, parent, children count, and test case count.",
    {
        "planId": {"type": "number", "description": "Test plan ID"},
        "suiteId": {"type": "number", "description": "Test suite ID"},
        "expand": {"type": "number", "description": "Suite expand level (0=none, 1=children, 2=defaultTesters)"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["planId", "suiteId"],
)


@tool_handler
def get_test_suite(args: Dict[str, Any]) -> str:
    config = config_for(args)
    plan_id = req_int(args, "planId")
    suite_id = req_int(args, "suiteId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_test_suite(plan_id, suite_id)

    try:
        suite = client.get_test_suite(config, plan_id, suite_id, expand=opt_int(args, "expand"))
        if not suite:
            return error(f"Test suite #{suite_id} not found in plan #{plan_id}.")
        return result(format_test_suite(suite), planId=plan_id, suiteId=suite.get("id"))
    except Exception as exc:
        return error(f"Failed to get test suite #{suite_id}: {client.format_ado_error(exc)}")


LIST_TEST_CASES_SCHEMA = schema(
    "azure_devops_list_test_cases",
    "List test cases in a test suite. Returns case ID, title, state, assigned to, priority, and configurations.",
    {
        "planId": {"type": "number", "description": "Test plan ID"},
        "suiteId": {"type": "number", "description": "Test suite ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["planId", "suiteId"],
)


@tool_handler
def list_test_cases(args: Dict[str, Any]) -> str:
    config = config_for(args)
    plan_id = req_int(args, "planId")
    suite_id = req_int(args, "suiteId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_test_cases(plan_id, suite_id)

    try:
        cases = client.list_test_cases(config, plan_id, suite_id)
        if not cases:
            return result(f"No test cases found in suite #{suite_id}.", planId=plan_id, suiteId=suite_id, count=0)
        return result(
            format_test_case_list(cases), planId=plan_id, suiteId=suite_id, count=len(cases)
        )
    except Exception as exc:
        return error(f"Failed to list test cases in suite #{suite_id}: {client.format_ado_error(exc)}")


LIST_TEST_POINTS_SCHEMA = schema(
    "azure_devops_list_test_points",
    "List test points in a test suite. Shows current outcome, assigned tester, and configuration for each point — "
    "useful for 'who is testing what' queries.",
    {
        "planId": {"type": "number", "description": "Test plan ID"},
        "suiteId": {"type": "number", "description": "Test suite ID"},
        "testCaseId": {"type": "string", "description": "Filter by test case ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["planId", "suiteId"],
)


@tool_handler
def list_test_points(args: Dict[str, Any]) -> str:
    config = config_for(args)
    plan_id = req_int(args, "planId")
    suite_id = req_int(args, "suiteId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_test_points(plan_id, suite_id)

    try:
        points = client.list_test_points(
            config, plan_id, suite_id, test_case_id=opt_str(args, "testCaseId")
        )
        if not points:
            return result(f"No test points found in suite #{suite_id}.", planId=plan_id, suiteId=suite_id, count=0)
        return result(
            format_test_point_list(points), planId=plan_id, suiteId=suite_id, count=len(points)
        )
    except Exception as exc:
        return error(f"Failed to list test points in suite #{suite_id}: {client.format_ado_error(exc)}")


GET_TEST_RUN_SCHEMA = schema(
    "azure_devops_get_test_run",
    "Get a test run by ID with pass/fail statistics. "
    "Returns run name, state, plan, pass/fail/total counts, dates, and owner.",
    {
        "runId": {"type": "number", "description": "Test run ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["runId"],
)


@tool_handler
def get_test_run(args: Dict[str, Any]) -> str:
    config = config_for(args)
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_test_run(run_id)

    try:
        run = client.get_test_run(config, run_id)
        if not run:
            return error(f"Test run #{run_id} not found.")
        return result(format_test_run(run), runId=run.get("id"))
    except Exception as exc:
        return error(f"Failed to get test run #{run_id}: {client.format_ado_error(exc)}")


LIST_TEST_RUNS_SCHEMA = schema(
    "azure_devops_list_test_runs",
    "List test runs in the project. Optionally filter by plan ID, build URI, or owner. "
    "Returns run ID, name, state, pass/total counts, and date.",
    {
        "planId": {"type": "number", "description": "Filter by test plan ID"},
        "buildUri": {"type": "string", "description": "Filter by build URI"},
        "owner": {"type": "string", "description": "Filter by owner display name"},
        "top": {"type": "number", "description": "Maximum number of runs to return", "default": 25},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_test_runs(args: Dict[str, Any]) -> str:
    config = config_for(args)

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_test_runs(opt_int(args, "planId"))

    try:
        runs = client.list_test_runs(
            config,
            plan_id=opt_int(args, "planId"),
            build_uri=opt_str(args, "buildUri"),
            owner=opt_str(args, "owner"),
            top=opt_int(args, "top") or 25,
        )
        if not runs:
            return result("No test runs found matching the criteria.", count=0)
        return result(format_test_run_list(runs), count=len(runs))
    except Exception as exc:
        return error(f"Failed to list test runs: {client.format_ado_error(exc)}")


CREATE_TEST_RUN_SCHEMA = schema(
    "azure_devops_create_test_run",
    "Create a new test run from a test plan and selected suites. "
    "Collects test points from the specified suites and queues a run.",
    {
        "planId": {"type": "number", "description": "Test plan ID"},
        "suiteIds": {"type": "array", "items": {"type": "number"}, "description": "Suite IDs to include in the run"},
        "name": {"type": "string", "description": "Run name (auto-generated if omitted)"},
        "comment": {"type": "string", "description": "Comment for the run"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["planId", "suiteIds"],
)


@tool_handler
def create_test_run(args: Dict[str, Any]) -> str:
    config = config_for(args)
    plan_id = req_int(args, "planId")
    suite_ids = opt_int_list(args, "suiteIds") or []
    name = opt_str(args, "name")
    comment = opt_str(args, "comment")

    if not suite_ids:
        return error("suiteIds must not be empty.")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.create_test_run(plan_id, suite_ids, name)

    try:
        point_ids: List[int] = []
        for suite_id in suite_ids:
            for point in client.list_test_points(config, plan_id, suite_id) or []:
                if point.get("id"):
                    point_ids.append(point["id"])

        if not point_ids:
            return error(
                f"No test points found in the specified suites for plan #{plan_id}. "
                "Ensure the suites contain test cases with assigned configurations."
            )

        run_name = name or f"Test Run - {datetime.now(timezone.utc).isoformat()}"
        body: Dict[str, Any] = {
            "name": run_name,
            "plan": {"id": plan_id},
            "pointIds": point_ids,
            "isAutomated": False,
            "state": "NotStarted",
        }
        if comment:
            body["comment"] = comment

        run = client.create_test_run(config, body)
        if not run:
            return error("Failed to create test run — no response from the API.")
        return result(f"✅ Created test run:\n\n{format_test_run(run)}", planId=plan_id, runId=run.get("id"), name=run_name)
    except Exception as exc:
        return error(f"Failed to create test run: {client.format_ado_error(exc)}")


UPDATE_TEST_RESULTS_SCHEMA = schema(
    "azure_devops_update_test_results",
    "Update test case results in a test run. Set outcome (passed, failed, blocked, etc.) "
    "and an optional comment for each result.",
    {
        "runId": {"type": "number", "description": "Test run ID"},
        "results": {
            "type": "array",
            "description": "Array of result updates",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "number", "description": "Test case result ID (from test run results)"},
                    "outcome": {
                        "type": "string",
                        "description": "Outcome: passed, failed, blocked, inconclusive, timeout, aborted, "
                        "notExecuted, warning, error, notApplicable, paused, inProgress, notImpacted",
                    },
                    "comment": {"type": "string", "description": "Comment for this result"},
                },
                "required": ["id", "outcome"],
            },
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["runId", "results"],
)


@tool_handler
def update_test_results(args: Dict[str, Any]) -> str:
    config = config_for(args)
    run_id = req_int(args, "runId")
    entries = opt_dict_list(args, "results") or []
    if not entries:
        return error("results must not be empty.")

    if is_mock(config, opt_bool(args, "mock")):
        payload = [
            {
                "testCaseResultId": (entry or {}).get("id"),
                "outcome": (entry or {}).get("outcome"),
                "comment": (entry or {}).get("comment"),
            }
            for entry in entries
        ]
        return mocks.update_test_results(run_id, payload)

    payload: List[Dict[str, Any]] = []
    for entry in entries:
        entry = entry or {}
        result_id = entry.get("id")
        outcome_name = str(entry.get("outcome") or "").strip().lower()
        if result_id is None:
            return error("Every result needs an id.")
        if outcome_name not in OUTCOME_MAP:
            return error(
                f'Unknown outcome "{entry.get("outcome")}". Valid: {", ".join(sorted(OUTCOME_MAP))}'
            )
        item: Dict[str, Any] = {"id": result_id, "outcome": OUTCOME_MAP[outcome_name]}
        if entry.get("comment"):
            item["comment"] = entry["comment"]
        payload.append(item)

    try:
        updated = client.update_test_results(config, run_id, payload)
        if not updated:
            return error("No results were updated — the API returned an empty response.")
        return result(
            f"✅ Updated {len(updated)} result(s) in run #{run_id}:\n\n{format_test_result_list(updated)}",
            runId=run_id,
            updatedCount=len(updated),
        )
    except Exception as exc:
        return error(f"Failed to update test results in run #{run_id}: {client.format_ado_error(exc)}")
