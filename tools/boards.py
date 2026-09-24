"""Board, team, sprint and capacity tools (the Azure DevOps Work + Core APIs)."""

from __future__ import annotations

from typing import Any, Dict, List

from .. import client, mocks
from ..formatters import (
    format_board,
    format_board_list,
    format_capacity,
    format_iteration_list,
    format_team_list,
    format_work_item_list,
)
from ._base import (
    MOCK_PROPERTY,
    NO_TEAM_MESSAGE,
    ORG_PROPERTY,
    PROJECT_PROPERTY,
    TEAM_PROPERTY,
    config_for,
    error,
    is_mock,
    opt_bool,
    opt_dict_list,
    opt_str,
    req_str,
    resolve_team_context,
    result,
    schema,
    tool_handler,
)

LIST_TEAMS_SCHEMA = schema(
    "azure_devops_list_teams",
    "List all teams in the configured Azure DevOps project. Returns team name, description, and ID.",
    {"org": ORG_PROPERTY, "project": PROJECT_PROPERTY, "mock": MOCK_PROPERTY},
)


@tool_handler
def list_teams(args: Dict[str, Any]) -> str:
    config = config_for(args)

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_teams()

    try:
        teams = client.get_teams(config)
        if not teams:
            return result("No teams found in this project.", count=0)
        return result(format_team_list(teams), count=len(teams))
    except Exception as exc:
        return error(f"Failed to list teams: {client.format_ado_error(exc)}")


LIST_BOARDS_SCHEMA = schema(
    "azure_devops_list_boards",
    "List boards for an Azure DevOps team. Returns board name, ID, and URL. "
    "Requires a team (from config or parameter).",
    {
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "team": TEAM_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_boards(args: Dict[str, Any]) -> str:
    config = config_for(args)
    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_boards(team)

    try:
        boards = client.get_boards(config, team)
        if not boards:
            return result(f'No boards found for team "{team}".', team=team, count=0)
        return result(format_board_list(boards), team=team, count=len(boards))
    except Exception as exc:
        return error(f'Failed to list boards for "{team}": {client.format_ado_error(exc)}')


GET_BOARD_SCHEMA = schema(
    "azure_devops_get_board",
    "Get full detail of an Azure DevOps board — columns with state mappings, item limits, and rows. "
    "Use azure_devops_list_boards first: the board id is the board's own id (on newer projects often "
    "a GUID), not necessarily the backlog category name.",
    {
        "boardId": {
            "type": "string",
            "description": 'Board ID or name from azure_devops_list_boards (e.g. "Stories", "Issues", or a GUID)',
        },
        "team": TEAM_PROPERTY,
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["boardId"],
)


@tool_handler
def get_board(args: Dict[str, Any]) -> str:
    config = config_for(args)
    board_id = req_str(args, "boardId")
    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_board(team, board_id)

    try:
        board = client.get_board(config, team, board_id)
        if not board:
            return error(f'Board "{board_id}" not found for team "{team}".')
        return result(format_board(board), team=team, boardId=board_id)
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f'Board "{board_id}" not found for team "{team}".')
        return error(f'Failed to get board "{board_id}": {client.format_ado_error(exc)}')


LIST_ITERATIONS_SCHEMA = schema(
    "azure_devops_list_iterations",
    "List sprints/iterations for an Azure DevOps team. "
    "Optionally filter by timeframe: 'current', 'past', or 'future'.",
    {
        "team": TEAM_PROPERTY,
        "timeframe": {"type": "string", "description": "Filter by timeframe: 'current', 'past', or 'future'"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_iterations(args: Dict[str, Any]) -> str:
    config = config_for(args)
    timeframe = opt_str(args, "timeframe")
    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_iterations(team, timeframe)

    try:
        iterations = client.get_team_iterations(config, team, timeframe)
        if not iterations:
            suffix = f" ({timeframe})" if timeframe else ""
            return result(f'No iterations found for team "{team}"{suffix}.', team=team, count=0)
        return result(format_iteration_list(iterations), team=team, count=len(iterations))
    except Exception as exc:
        return error(f'Failed to list iterations for "{team}": {client.format_ado_error(exc)}')


GET_ITERATION_WORK_ITEMS_SCHEMA = schema(
    "azure_devops_get_iteration_work_items",
    "Get work items in a specific Azure DevOps sprint/iteration. "
    "Returns work item IDs, titles, states, and types.",
    {
        "iterationId": {"type": "string", "description": "Iteration/sprint GUID or ID"},
        "team": TEAM_PROPERTY,
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["iterationId"],
)


@tool_handler
def get_iteration_work_items(args: Dict[str, Any]) -> str:
    config = config_for(args)
    iteration_id = req_str(args, "iterationId")
    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_iteration_work_items(team, iteration_id)

    try:
        payload = client.get_iteration_work_items(config, team, iteration_id)
        relations = payload.get("workItemRelations") or []
        ids = [entry["target"]["id"] for entry in relations if (entry.get("target") or {}).get("id")]

        if not ids:
            return result(
                f'No work items in iteration {iteration_id} for "{team}".',
                team=team,
                iterationId=iteration_id,
                count=0,
            )

        work_items = client.get_work_items(config, ids)
        return result(
            f'Work items in iteration {iteration_id} for "{team}" ({len(work_items)}):\n\n'
            f"{format_work_item_list(work_items)}",
            team=team,
            iterationId=iteration_id,
            count=len(work_items),
        )
    except Exception as exc:
        return error(f"Failed to get iteration work items: {client.format_ado_error(exc)}")


GET_CAPACITY_SCHEMA = schema(
    "azure_devops_get_capacity",
    "Get sprint capacity for an Azure DevOps team — per-member activities, capacity per day, "
    "days off, and team totals.",
    {
        "iterationId": {"type": "string", "description": "Iteration/sprint GUID or ID"},
        "team": TEAM_PROPERTY,
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["iterationId"],
)


@tool_handler
def get_capacity(args: Dict[str, Any]) -> str:
    config = config_for(args)
    iteration_id = req_str(args, "iterationId")
    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_capacity(team, iteration_id)

    try:
        capacity = client.get_capacities(config, team, iteration_id)
        if not capacity:
            return error(f'No capacity data for iteration {iteration_id} and team "{team}".')
        return result(format_capacity(capacity), team=team, iterationId=iteration_id)
    except Exception as exc:
        return error(f"Failed to get capacity: {client.format_ado_error(exc)}")


COLUMNS_PROPERTY = {
    "type": "array",
    "description": "New column definitions (replaces existing). Each item: "
    '{ "name": str, "itemLimit"?: number, "stateMappings"?: { "<work item type>": "<state>" } }',
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Column name"},
            "itemLimit": {"type": "number", "description": "WIP limit for the column"},
            "stateMappings": {
                "type": "object",
                "description": 'Map work item type to state for this column, e.g. { "User Story": "Active" }',
            },
        },
        "required": ["name"],
    },
}

SET_BOARD_COLUMNS_SCHEMA = schema(
    "azure_devops_set_board_columns",
    "Reconfigure columns on an Azure DevOps board. Replaces all columns with the provided set. "
    "Each column has a name, optional WIP limit, and state mappings per work item type. "
    "Take the board id from azure_devops_list_boards and the current columns from azure_devops_get_board.",
    {
        "boardId": {"type": "string", "description": "Board ID or name from azure_devops_list_boards"},
        "columns": COLUMNS_PROPERTY,
        "team": TEAM_PROPERTY,
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["boardId", "columns"],
)


@tool_handler
def set_board_columns(args: Dict[str, Any]) -> str:
    config = config_for(args)
    board_id = req_str(args, "boardId")
    columns = opt_dict_list(args, "columns") or []
    if not columns:
        return error("columns must not be empty.")

    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.set_board_columns(team, board_id, columns)

    payload: List[Dict[str, Any]] = []
    for index, column in enumerate(columns):
        if not column.get("name"):
            return error("Every column needs a name.")
        payload.append(
            {
                "name": str(column["name"]),
                "itemLimit": column.get("itemLimit"),
                "stateMappings": column.get("stateMappings") or {},
                "columnType": 0 if index == 0 else (2 if index == len(columns) - 1 else 1),
            }
        )

    try:
        updated = client.update_board_columns(config, team, board_id, payload)
        names = " → ".join(str(column["name"]) for column in columns)
        body = f'✅ Updated columns on board "{board_id}" for {team}\n\nColumns: {names}'
        if isinstance(updated, dict) and updated:
            body += f"\n\n{format_board(updated)}"
        return result(body, team=team, boardId=board_id, columnCount=len(columns))
    except Exception as exc:
        return error(f"Failed to set board columns: {client.format_ado_error(exc)}")


SET_ITERATION_SCHEMA = schema(
    "azure_devops_set_iteration",
    "Add or remove an iteration/sprint from a team's sprint set. "
    "Use 'add' to assign a sprint to a team, 'remove' to unassign it.",
    {
        "iterationId": {"type": "string", "description": "Iteration GUID or path"},
        "operation": {"type": "string", "enum": ["add", "remove"], "description": "Add or remove the iteration"},
        "team": TEAM_PROPERTY,
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["iterationId", "operation"],
)


@tool_handler
def set_iteration(args: Dict[str, Any]) -> str:
    config = config_for(args)
    iteration_id = req_str(args, "iterationId")
    operation = req_str(args, "operation").strip().lower()

    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if operation not in ("add", "remove"):
        return error('operation must be "add" or "remove".')

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.set_iteration(team, iteration_id, operation)

    try:
        if operation == "add":
            client.post_team_iteration(config, team, iteration_id)
            return result(
                f"✅ Added iteration {iteration_id} to {team}",
                team=team,
                iterationId=iteration_id,
                operation="add",
            )
        client.delete_team_iteration(config, team, iteration_id)
        return result(
            f"✅ Removed iteration {iteration_id} from {team}",
            team=team,
            iterationId=iteration_id,
            operation="remove",
        )
    except Exception as exc:
        verb = "add" if operation == "add" else "remove"
        return error(f"Failed to {verb} iteration: {client.format_ado_error(exc)}")


CAPACITIES_PROPERTY = {
    "type": "array",
    "description": "Capacity for each team member — replaces the existing capacity.",
    "items": {
        "type": "object",
        "properties": {
            "teamMemberId": {"type": "string", "description": "Team member identity ID or email"},
            "activities": {
                "type": "array",
                "description": "Activities and capacity per day",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Activity name, e.g. 'Development', 'Testing'"},
                        "capacityPerDay": {"type": "number", "description": "Hours per day for this activity"},
                    },
                    "required": ["name", "capacityPerDay"],
                },
            },
            "daysOff": {
                "type": "array",
                "description": "Days off date ranges",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "Start date (ISO 8601)"},
                        "end": {"type": "string", "description": "End date (ISO 8601)"},
                    },
                    "required": ["start", "end"],
                },
            },
        },
        "required": ["teamMemberId", "activities"],
    },
}

SET_CAPACITY_SCHEMA = schema(
    "azure_devops_set_capacity",
    "Set sprint capacity for all team members at once (full replacement, not a patch). "
    "Provide each member's activities with hours/day and optional days off.",
    {
        "iterationId": {"type": "string", "description": "Iteration/sprint GUID"},
        "capacities": CAPACITIES_PROPERTY,
        "team": TEAM_PROPERTY,
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["iterationId", "capacities"],
)


@tool_handler
def set_capacity(args: Dict[str, Any]) -> str:
    config = config_for(args)
    iteration_id = req_str(args, "iterationId")
    capacities = opt_dict_list(args, "capacities") or []
    if not capacities:
        return error("capacities must not be empty.")

    context = resolve_team_context(config, opt_str(args, "team"))
    if not context:
        return error(NO_TEAM_MESSAGE)
    team = context["team"]

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.set_capacity(team, iteration_id, capacities)

    payload: List[Dict[str, Any]] = []
    for member in capacities:
        member_id = member.get("teamMemberId")
        if not member_id:
            return error("Every capacity entry needs a teamMemberId.")
        activities = member.get("activities") or []
        payload.append(
            {
                "teamMember": {"id": str(member_id)},
                "activities": [
                    {
                        "name": (activity or {}).get("name"),
                        "capacityPerDay": (activity or {}).get("capacityPerDay"),
                    }
                    for activity in activities
                ],
                "daysOff": [
                    {"start": (entry or {}).get("start"), "end": (entry or {}).get("end")}
                    for entry in member.get("daysOff") or []
                ],
            }
        )

    try:
        client.replace_capacities(config, team, iteration_id, payload)
        summary = []
        for member in capacities:
            activities = ", ".join(
                f"{(a or {}).get('name')}: {(a or {}).get('capacityPerDay')}h/day"
                for a in member.get("activities") or []
            )
            summary.append(f"- {member.get('teamMemberId')}: {activities}")

        return result(
            f"✅ Set capacity for {len(capacities)} member(s) in {team} / {iteration_id}\n\n"
            + "\n".join(summary),
            team=team,
            iterationId=iteration_id,
            memberCount=len(capacities),
        )
    except Exception as exc:
        return error(f"Failed to set capacity: {client.format_ado_error(exc)}")
