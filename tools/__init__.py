"""Tool registry: every tool as a ``(schema, handler)`` pair.

Grouped by area rather than one module per tool, because there are 54 of them.
The order below is pi-azure-devops' registration order, so the model sees the
tools in the same sequence it is used to.
"""

from __future__ import annotations

from . import boards, connection, pipelines, repos, testplans, workitems

TOOLSET = "azure-devops"

TOOLS = (
    # Configuration and health
    (connection.DOCTOR_SCHEMA, connection.doctor),
    # Work items
    (workitems.GET_WORK_ITEM_SCHEMA, workitems.get_work_item),
    (workitems.QUERY_WORK_ITEMS_SCHEMA, workitems.query_work_items),
    (workitems.LIST_WORK_ITEM_TYPES_SCHEMA, workitems.list_work_item_types),
    (workitems.GET_WORK_ITEM_COMMENTS_SCHEMA, workitems.get_work_item_comments),
    (workitems.GET_WORK_ITEM_REVISIONS_SCHEMA, workitems.get_work_item_revisions),
    (workitems.CREATE_WORK_ITEM_SCHEMA, workitems.create_work_item),
    (workitems.UPDATE_WORK_ITEM_SCHEMA, workitems.update_work_item),
    (workitems.ADD_WORK_ITEM_COMMENT_SCHEMA, workitems.add_work_item_comment),
    (workitems.MANAGE_WORK_ITEM_LINKS_SCHEMA, workitems.manage_work_item_links),
    # Teams, boards, sprints, capacity
    (boards.LIST_TEAMS_SCHEMA, boards.list_teams),
    (boards.LIST_BOARDS_SCHEMA, boards.list_boards),
    (boards.GET_BOARD_SCHEMA, boards.get_board),
    (boards.LIST_ITERATIONS_SCHEMA, boards.list_iterations),
    (boards.GET_ITERATION_WORK_ITEMS_SCHEMA, boards.get_iteration_work_items),
    (boards.GET_CAPACITY_SCHEMA, boards.get_capacity),
    (boards.SET_BOARD_COLUMNS_SCHEMA, boards.set_board_columns),
    (boards.SET_ITERATION_SCHEMA, boards.set_iteration),
    (boards.SET_CAPACITY_SCHEMA, boards.set_capacity),
    # Repositories and pull requests
    (repos.LIST_REPOS_SCHEMA, repos.list_repos),
    (repos.GET_REPO_SCHEMA, repos.get_repo),
    (repos.LIST_BRANCHES_SCHEMA, repos.list_branches),
    (repos.LIST_PULL_REQUESTS_SCHEMA, repos.list_pull_requests),
    (repos.GET_PULL_REQUEST_SCHEMA, repos.get_pull_request),
    (repos.GET_PR_THREADS_SCHEMA, repos.get_pull_request_threads),
    (repos.GET_PR_COMMITS_SCHEMA, repos.get_pull_request_commits),
    (repos.LIST_POLICIES_SCHEMA, repos.list_policies),
    (repos.GET_POLICY_EVALUATIONS_SCHEMA, repos.get_policy_evaluations),
    (repos.CREATE_PULL_REQUEST_SCHEMA, repos.create_pull_request),
    (repos.UPDATE_PULL_REQUEST_SCHEMA, repos.update_pull_request),
    (repos.ADD_PR_COMMENT_SCHEMA, repos.add_pull_request_comment),
    (repos.SET_PR_VOTE_SCHEMA, repos.set_pull_request_vote),
    (repos.SET_PR_AUTOCOMPLETE_SCHEMA, repos.set_pull_request_autocomplete),
    (repos.LINK_PR_WORK_ITEMS_SCHEMA, repos.link_pr_work_items),
    # Pipelines and runs
    (pipelines.LIST_PIPELINES_SCHEMA, pipelines.list_pipelines),
    (pipelines.GET_PIPELINE_SCHEMA, pipelines.get_pipeline),
    (pipelines.LIST_RUNS_SCHEMA, pipelines.list_runs),
    (pipelines.GET_RUN_SCHEMA, pipelines.get_run),
    (pipelines.GET_RUN_ARTIFACTS_SCHEMA, pipelines.get_run_artifacts),
    (pipelines.GET_RUN_LOGS_SCHEMA, pipelines.get_run_logs),
    (pipelines.GET_RUN_TIMELINE_SCHEMA, pipelines.get_run_timeline),
    (pipelines.RUN_PIPELINE_SCHEMA, pipelines.run_pipeline),
    (pipelines.CANCEL_RUN_SCHEMA, pipelines.cancel_run),
    (pipelines.RETRY_RUN_SCHEMA, pipelines.retry_run),
    # Test plans
    (testplans.LIST_TEST_PLANS_SCHEMA, testplans.list_test_plans),
    (testplans.GET_TEST_PLAN_SCHEMA, testplans.get_test_plan),
    (testplans.LIST_TEST_SUITES_SCHEMA, testplans.list_test_suites),
    (testplans.GET_TEST_SUITE_SCHEMA, testplans.get_test_suite),
    (testplans.LIST_TEST_CASES_SCHEMA, testplans.list_test_cases),
    (testplans.LIST_TEST_POINTS_SCHEMA, testplans.list_test_points),
    (testplans.GET_TEST_RUN_SCHEMA, testplans.get_test_run),
    (testplans.LIST_TEST_RUNS_SCHEMA, testplans.list_test_runs),
    (testplans.CREATE_TEST_RUN_SCHEMA, testplans.create_test_run),
    (testplans.UPDATE_TEST_RESULTS_SCHEMA, testplans.update_test_results),
)

#: Tools that change something in Azure DevOps. The safety level gates these.
MUTATION_TOOLS = frozenset(
    {
        "azure_devops_create_work_item",
        "azure_devops_update_work_item",
        "azure_devops_add_work_item_comment",
        "azure_devops_manage_work_item_links",
        "azure_devops_set_board_columns",
        "azure_devops_set_iteration",
        "azure_devops_set_capacity",
        "azure_devops_create_pull_request",
        "azure_devops_update_pull_request",
        "azure_devops_add_pull_request_comment",
        "azure_devops_set_pull_request_vote",
        "azure_devops_set_pull_request_autocomplete",
        "azure_devops_link_pr_work_items",
        "azure_devops_run_pipeline",
        "azure_devops_cancel_run",
        "azure_devops_retry_run",
        "azure_devops_create_test_run",
        "azure_devops_update_test_results",
    }
)

TOOL_NAMES = tuple(schema["name"] for schema, _ in TOOLS)


def is_mutation_tool(tool_name: str) -> bool:
    return tool_name in MUTATION_TOOLS
