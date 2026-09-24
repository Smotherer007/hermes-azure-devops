"""Work item tools: read, query, create, update, comment, link."""

from __future__ import annotations

from typing import Any, Dict

from .. import client, mocks
from ..formatters import (
    format_comments,
    format_revisions,
    format_work_item,
    format_work_item_list,
    format_work_item_type_list,
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
    opt_str,
    opt_str_map,
    req_int,
    req_str,
    result,
    schema,
    tool_handler,
)

GET_WORK_ITEM_SCHEMA = schema(
    "azure_devops_get_work_item",
    "Fetch a single Azure DevOps work item by ID. Returns all fields, formatted for readability.",
    {
        "id": {"type": "number", "description": "Work item ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["id"],
)


@tool_handler
def get_work_item(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_id = req_int(args, "id")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_work_item(work_item_id)

    try:
        work_item = client.get_work_item(config, work_item_id)
        if not work_item or not work_item.get("id"):
            return error(f"Work item #{work_item_id} not found.")
        return result(format_work_item(work_item), id=work_item["id"])
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Work item #{work_item_id} not found.")
        return error(f"Failed to fetch work item #{work_item_id}: {client.format_ado_error(exc)}")


QUERY_WORK_ITEMS_SCHEMA = schema(
    "azure_devops_query_work_items",
    "Run a WIQL query to find Azure DevOps work items. "
    "Supports full WIQL syntax. Use to search by type, state, assigned to, area path, iteration path, etc.",
    {
        "query": {
            "type": "string",
            "description": "WIQL query string. Example: SELECT [System.Id] FROM WorkItems WHERE [System.State] = 'Active'",
        },
        "top": {"type": "number", "description": "Maximum results to return (default: from config)"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["query"],
)


@tool_handler
def query_work_items(args: Dict[str, Any]) -> str:
    config = config_for(args)
    query = req_str(args, "query")
    top = opt_int(args, "top") or config.max_query_results

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.query_work_items(query, top)

    try:
        query_result = client.query_by_wiql(config, query, top=top)
        references = query_result.get("workItems") or []
        if not references:
            return result("No work items found matching the query.", count=0)

        ids = [item.get("id") for item in references if item.get("id")]
        work_items = client.get_work_items(config, ids)
        if not work_items:
            return result("No work items found matching the query.", count=0)

        return result(
            f"Found {len(work_items)} work item(s):\n\n{format_work_item_list(work_items)}",
            count=len(work_items),
        )
    except Exception as exc:
        return error(f"Query failed: {client.format_ado_error(exc)}")


LIST_WORK_ITEM_TYPES_SCHEMA = schema(
    "azure_devops_list_work_item_types",
    "List all available work item types for the Azure DevOps project. "
    "Use before creating work items to determine valid types.",
    {
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_work_item_types(args: Dict[str, Any]) -> str:
    config = config_for(args)

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_work_item_types()

    try:
        types = client.get_work_item_types(config)
        if not types:
            return result("No work item types found for this project.", count=0)
        return result(
            f"Work item types for {config.project}:\n\n{format_work_item_type_list(types)}",
            count=len(types),
        )
    except Exception as exc:
        return error(f"Failed to list work item types: {client.format_ado_error(exc)}")


GET_WORK_ITEM_COMMENTS_SCHEMA = schema(
    "azure_devops_get_work_item_comments",
    "Retrieve all comments on an Azure DevOps work item. Returns comment text, author, and date.",
    {
        "workItemId": {"type": "number", "description": "Work item ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["workItemId"],
)


@tool_handler
def get_work_item_comments(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_id = req_int(args, "workItemId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_work_item_comments(work_item_id)

    try:
        comment_list = client.get_comments(config, work_item_id)
        comments = (comment_list or {}).get("comments") or []
        if not comments:
            return result(f"No comments on work item #{work_item_id}.", workItemId=work_item_id, count=0)
        return result(
            f"Comments on #{work_item_id}:\n\n{format_comments(comment_list)}",
            workItemId=work_item_id,
            count=len(comments),
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Work item #{work_item_id} not found.")
        return error(f"Failed to get comments: {client.format_ado_error(exc)}")


GET_WORK_ITEM_REVISIONS_SCHEMA = schema(
    "azure_devops_get_work_item_revisions",
    "Get revision history for an Azure DevOps work item. Shows all changes with who changed what and when.",
    {
        "workItemId": {"type": "number", "description": "Work item ID"},
        "top": {"type": "number", "description": "Maximum revisions to return (default: 50)"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["workItemId"],
)


@tool_handler
def get_work_item_revisions(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_id = req_int(args, "workItemId")
    top = opt_int(args, "top") or 50

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_work_item_revisions(work_item_id)

    try:
        revisions = client.get_revisions(config, work_item_id, top=top)
        if not revisions:
            return result(f"No revisions found for work item #{work_item_id}.", workItemId=work_item_id, count=0)
        return result(
            f"Revision history for #{work_item_id}:\n\n{format_revisions(revisions)}",
            workItemId=work_item_id,
            count=len(revisions),
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Work item #{work_item_id} not found.")
        return error(f"Failed to get revisions: {client.format_ado_error(exc)}")


CREATE_WORK_ITEM_SCHEMA = schema(
    "azure_devops_create_work_item",
    "Create a new Azure DevOps work item. Requires type, title, and optionally description and custom fields.",
    {
        "type": {
            "type": "string",
            "description": "Work item type (e.g., User Story, Bug, Task). Use azure_devops_list_work_item_types to see valid types.",
        },
        "title": {"type": "string", "description": "Work item title"},
        "description": {"type": "string", "description": "Work item description (supports HTML)"},
        "fields": {
            "type": "object",
            "description": 'Additional fields to set, e.g. {"System.Priority": "1", "System.Tags": "backend; critical"}',
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["type", "title"],
)


@tool_handler
def create_work_item(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_type = req_str(args, "type")
    title = req_str(args, "title")
    description = opt_str(args, "description")
    fields = opt_str_map(args, "fields")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.create_work_item(work_item_type, title, description, fields)

    patch: list = [{"op": "add", "path": "/fields/System.Title", "value": title}]
    if description:
        patch.append({"op": "add", "path": "/fields/System.Description", "value": description})
    for key, value in (fields or {}).items():
        patch.append({"op": "add", "path": f"/fields/{key}", "value": value})

    try:
        work_item = client.create_work_item(config, work_item_type, patch)
        if not work_item or not work_item.get("id"):
            return error("Failed to create work item — no ID returned from the API.")
        return result(
            f"✅ Created work item #{work_item['id']}\n\n{format_work_item(work_item)}",
            id=work_item["id"],
            type=work_item_type,
        )
    except Exception as exc:
        return error(f"Failed to create work item: {client.format_ado_error(exc)}")


UPDATE_WORK_ITEM_SCHEMA = schema(
    "azure_devops_update_work_item",
    "Update fields on an existing Azure DevOps work item using JSON Patch. "
    "Provide the work item ID and a map of field names to new values.",
    {
        "id": {"type": "number", "description": "Work item ID to update"},
        "fields": {
            "type": "object",
            "description": 'Fields to update, e.g. {"System.State": "Closed", "System.Reason": "Completed"}',
        },
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["id", "fields"],
)


@tool_handler
def update_work_item(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_id = req_int(args, "id")
    fields = opt_str_map(args, "fields")
    if not fields:
        return error("fields must not be empty.")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.update_work_item(work_item_id, fields)

    patch = [{"op": "replace", "path": f"/fields/{key}", "value": value} for key, value in fields.items()]

    try:
        work_item = client.update_work_item(config, work_item_id, patch)
        if not work_item or not work_item.get("id"):
            return error(f"Failed to update work item #{work_item_id} — no data returned.")
        changed = "\n".join(f"- **{key}:** {value}" for key, value in fields.items())
        return result(
            f"✅ Updated work item #{work_item['id']}\n\nUpdated fields:\n{changed}\n\n"
            f"{format_work_item(work_item)}",
            id=work_item["id"],
            fields=fields,
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Work item #{work_item_id} not found.")
        return error(f"Failed to update work item #{work_item_id}: {client.format_ado_error(exc)}")


ADD_WORK_ITEM_COMMENT_SCHEMA = schema(
    "azure_devops_add_work_item_comment",
    "Add a comment to an Azure DevOps work item.",
    {
        "workItemId": {"type": "number", "description": "Work item ID to comment on"},
        "text": {"type": "string", "description": "Comment text"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["workItemId", "text"],
)


@tool_handler
def add_work_item_comment(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_id = req_int(args, "workItemId")
    text = req_str(args, "text")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.add_work_item_comment(work_item_id, text)

    try:
        comment = client.add_comment(config, work_item_id, text)
        if not comment or not comment.get("id"):
            return error(f"Failed to add comment to work item #{work_item_id}.")
        return result(
            f"✅ Added comment to work item #{work_item_id}\n\n> {text}\n\nComment ID: {comment['id']}",
            workItemId=work_item_id,
            commentId=comment["id"],
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error(f"Work item #{work_item_id} not found.")
        return error(f"Failed to add comment: {client.format_ado_error(exc)}")


MANAGE_WORK_ITEM_LINKS_SCHEMA = schema(
    "azure_devops_manage_work_item_links",
    "Add or remove relation links between Azure DevOps work items. "
    "Common relation types: System.LinkTypes.Hierarchy-Forward (parent/child), "
    "System.LinkTypes.Related, System.LinkTypes.Duplicate, System.LinkTypes.Dependency.",
    {
        "workItemId": {"type": "number", "description": "Source work item ID"},
        "operation": {"type": "string", "enum": ["add", "remove"], "description": "Add or remove the link"},
        "relationType": {
            "type": "string",
            "description": "Relation type, e.g. System.LinkTypes.Hierarchy-Forward, System.LinkTypes.Related",
        },
        "targetId": {"type": "number", "description": "Target work item ID"},
        "comment": {"type": "string", "description": "Optional comment for the link"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["workItemId", "operation", "relationType", "targetId"],
)


@tool_handler
def manage_work_item_links(args: Dict[str, Any]) -> str:
    config = config_for(args)
    work_item_id = req_int(args, "workItemId")
    operation = req_str(args, "operation").strip().lower()
    relation_type = req_str(args, "relationType")
    target_id = req_int(args, "targetId")
    comment = opt_str(args, "comment")

    if operation not in ("add", "remove"):
        return error('operation must be "add" or "remove".')

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.manage_work_item_links(work_item_id, operation, relation_type, target_id)

    try:
        if operation == "add":
            relation: Dict[str, Any] = {
                "rel": relation_type,
                "url": f"{config.org_url}/_apis/wit/workItems/{target_id}",
            }
            if comment:
                relation["attributes"] = {"comment": comment}
            patch = [{"op": "add", "path": "/relations/-", "value": relation}]
        else:
            # Relations are only returned when explicitly expanded; without
            # $expand=relations the index of the link cannot be found.
            work_item = client.get_work_item(config, work_item_id, expand="relations")
            relations = work_item.get("relations") or []
            if not relations:
                return error(f"No relations found on work item #{work_item_id}.")

            index = next(
                (
                    position
                    for position, relation in enumerate(relations)
                    if relation.get("rel") == relation_type
                    and str(relation.get("url", "")).endswith(f"/workItems/{target_id}")
                ),
                -1,
            )
            if index == -1:
                return error(
                    f"No {relation_type} link to #{target_id} found on work item #{work_item_id}."
                )
            patch = [{"op": "remove", "path": f"/relations/{index}"}]

        updated = client.update_work_item(config, work_item_id, patch)
        verb = "Added" if operation == "add" else "Removed"
        arrow = "→" if operation == "add" else "✕"
        body = f"✅ {verb} {relation_type} link: #{work_item_id} {arrow} #{target_id}\n\n"
        body += format_work_item(updated) if updated else ""
        return result(
            body,
            workItemId=work_item_id,
            operation=operation,
            targetId=target_id,
        )
    except Exception as exc:
        if client.is_not_found_error(exc):
            return error("Work item not found.")
        return error(f"Failed to manage link: {client.format_ado_error(exc)}")
