"""Pipeline and build-run tools (the Pipelines + Build APIs)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .. import client, mocks
from ..formatters import (
    format_artifact_list,
    format_iso_datetime,
    format_pipeline,
    format_pipeline_list,
    format_run,
    format_run_list,
    format_timeline,
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
    opt_str_list,
    opt_str_map,
    req_int,
    result,
    schema,
    tool_handler,
)

#: BuildStatus / BuildResult enums, both accepted by name and by number.
BUILD_STATUS = {
    "completed": 2,
    "inprogress": 1,
    "inProgress": 1,
    "cancelling": 4,
    "postponed": 8,
    "notstarted": 32,
    "notStarted": 32,
}
BUILD_RESULT = {
    "succeeded": 2,
    "partiallysucceeded": 4,
    "partiallySucceeded": 4,
    "failed": 8,
    "canceled": 32,
}

STATUS_NAMES = ("completed", "inProgress", "cancelling", "postponed", "notStarted", "all")
RESULT_NAMES = ("succeeded", "failed", "canceled", "partiallySucceeded")

LIST_PIPELINES_SCHEMA = schema(
    "azure_devops_list_pipelines",
    "List YAML pipelines (definitions) in the configured Azure DevOps project. "
    "Returns pipeline name, ID, folder, and YAML path.",
    {
        "top": {"type": "number", "description": "Maximum number of pipelines to return", "default": 50},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


@tool_handler
def list_pipelines(args: Dict[str, Any]) -> str:
    config = config_for(args)

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_pipelines()

    try:
        pipelines = client.list_pipelines(config, top=opt_int(args, "top") or 50)
        if not pipelines:
            return result("No pipelines found in this project.", count=0)
        return result(format_pipeline_list(pipelines), count=len(pipelines))
    except Exception as exc:
        return error(f"Failed to list pipelines: {client.format_ado_error(exc)}")


GET_PIPELINE_SCHEMA = schema(
    "azure_devops_get_pipeline",
    "Get a single YAML pipeline definition by ID. Returns name, folder, YAML path, and repository info.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "pipelineVersion": {"type": "number", "description": "Specific pipeline version"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId"],
)


@tool_handler
def get_pipeline(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_pipeline(pipeline_id)

    try:
        pipeline = client.get_pipeline(config, pipeline_id, opt_int(args, "pipelineVersion"))
        if not pipeline:
            return error(f"Pipeline #{pipeline_id} not found.")
        return result(format_pipeline(pipeline), pipelineId=pipeline.get("id"))
    except Exception as exc:
        return error(f"Failed to get pipeline #{pipeline_id}: {client.format_ado_error(exc)}")


LIST_RUNS_SCHEMA = schema(
    "azure_devops_list_runs",
    "List pipeline runs (builds). Optionally filter by pipeline ID, status, result, or branch. "
    "Returns run ID, pipeline name, state, result, duration, and branch.",
    {
        "pipelineId": {"type": "number", "description": "Filter by pipeline ID (omit for all pipelines)"},
        "top": {"type": "number", "description": "Maximum number of runs to return", "default": 25},
        "status": {
            "type": "string",
            "description": "Filter by state: completed, inProgress, cancelling, postponed, notStarted, all",
        },
        "result": {
            "type": "string",
            "description": "Filter by result: succeeded, failed, canceled, partiallySucceeded",
        },
        "branch": {"type": "string", "description": "Filter by branch name (e.g. main, feature/login)"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
)


def _canonical_status(value: Optional[str]) -> Optional[str]:
    """Accept both the enum name and the numeric value pi used to send."""
    if not value:
        return None
    text = str(value).strip()
    for name in STATUS_NAMES:
        if text.lower() == name.lower():
            return name
    numeric = {"2": "completed", "1": "inProgress", "4": "cancelling", "8": "postponed", "32": "notStarted", "47": "all"}
    return numeric.get(text, text)


def _canonical_result(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    for name in RESULT_NAMES:
        if text.lower() == name.lower():
            return name
    numeric = {"2": "succeeded", "4": "partiallySucceeded", "8": "failed", "32": "canceled"}
    return numeric.get(text, text)


def _build_to_run(build: Dict[str, Any]) -> Dict[str, Any]:
    """Reshape a build into the Run shape the formatter renders."""
    status = build.get("status")
    result_value = build.get("result")
    state = "completed" if status == 2 else ("inProgress" if status == 1 else "pending")
    if result_value == 2:
        result_name = "succeeded"
    elif result_value == 8:
        result_name = "failed"
    elif result_value == 32:
        result_name = "canceled"
    elif result_value == 4:
        result_name = "partiallySucceeded"
    else:
        result_name = None

    definition = build.get("definition") or {}
    return {
        "id": build.get("id"),
        "name": build.get("buildNumber"),
        "pipeline": {"id": definition.get("id"), "name": definition.get("name")},
        "state": state,
        "result": result_name,
        "createdDate": build.get("startTime") or build.get("queueTime"),
        "finishedDate": build.get("finishTime"),
        "resources": {"repositories": {"self": {"refName": build.get("sourceBranch"), "version": build.get("sourceVersion")}}},
        "templateParameters": build.get("templateParameters"),
        "url": build.get("url"),
    }


@tool_handler
def list_runs(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = opt_int(args, "pipelineId")
    status = _canonical_status(opt_str(args, "status"))
    result_filter = _canonical_result(opt_str(args, "result"))
    branch = opt_str(args, "branch")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.list_runs(pipeline_id, status, result_filter, branch)

    branch_name = branch
    if branch_name and not branch_name.startswith("refs/"):
        branch_name = f"refs/heads/{branch_name}"

    try:
        builds = client.list_builds(
            config,
            definitions=[pipeline_id] if pipeline_id else None,
            status=status,
            result=result_filter,
            branch_name=branch_name,
            top=opt_int(args, "top") or 25,
        )
        if not builds:
            return result("No runs found matching the criteria.", count=0)
        runs = [_build_to_run(build) for build in builds]
        return result(format_run_list(runs), count=len(builds))
    except Exception as exc:
        return error(f"Failed to list runs: {client.format_ado_error(exc)}")


GET_RUN_SCHEMA = schema(
    "azure_devops_get_run",
    "Get a single pipeline run by pipeline ID and run ID. Returns state, result, duration, branch, and parameters.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "runId": {"type": "number", "description": "Run ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId", "runId"],
)


@tool_handler
def get_run(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_run(pipeline_id, run_id)

    try:
        run = client.get_run(config, pipeline_id, run_id)
        if not run:
            return error(f"Run #{run_id} not found for pipeline #{pipeline_id}.")
        return result(format_run(run), pipelineId=pipeline_id, runId=run.get("id"))
    except Exception as exc:
        return error(f"Failed to get run #{run_id}: {client.format_ado_error(exc)}")


GET_RUN_ARTIFACTS_SCHEMA = schema(
    "azure_devops_get_run_artifacts",
    "Get artifacts produced by a pipeline run (build). Returns artifact name, type, and resource URL.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "runId": {"type": "number", "description": "Run (build) ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId", "runId"],
)


@tool_handler
def get_run_artifacts(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_run_artifacts(pipeline_id, run_id)

    try:
        artifacts = client.get_build_artifacts(config, run_id)
        if not artifacts:
            return result(f"No artifacts for run #{run_id}.", count=0)
        return result(format_artifact_list(artifacts), count=len(artifacts))
    except Exception as exc:
        return error(f"Failed to get artifacts for run #{run_id}: {client.format_ado_error(exc)}")


GET_RUN_LOGS_SCHEMA = schema(
    "azure_devops_get_run_logs",
    "Get log entries for a pipeline run (build). Returns log IDs with line counts and timestamps.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "runId": {"type": "number", "description": "Run (build) ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId", "runId"],
)


@tool_handler
def get_run_logs(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_run_logs(pipeline_id, run_id)

    try:
        logs = client.get_build_logs(config, run_id)
        if not logs:
            return result(f"No logs for run #{run_id}.", count=0)

        lines = []
        for log in logs:
            created = format_iso_datetime(log.get("createdOn")) if log.get("createdOn") else "?"
            lines.append(f"Log #{log.get('id') or '?'} ({log.get('lineCount') or 0} lines) — {created}")
        return result(f"Logs for run #{run_id}:\n\n" + "\n".join(lines), count=len(logs))
    except Exception as exc:
        return error(f"Failed to get logs for run #{run_id}: {client.format_ado_error(exc)}")


GET_RUN_TIMELINE_SCHEMA = schema(
    "azure_devops_get_run_timeline",
    "Get the stages/jobs/tasks timeline for a pipeline run. "
    "Shows hierarchy, state, result, duration, and error counts.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "runId": {"type": "number", "description": "Run (build) ID"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId", "runId"],
)


@tool_handler
def get_run_timeline(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.get_run_timeline(pipeline_id, run_id)

    try:
        timeline = client.get_build_timeline(config, run_id)
        records = (timeline or {}).get("records") or []
        if not records:
            return result(f"No timeline for run #{run_id}.", count=0)
        return result(f"Timeline for run #{run_id}:\n\n{format_timeline(timeline)}", count=len(records))
    except Exception as exc:
        return error(f"Failed to get timeline for run #{run_id}: {client.format_ado_error(exc)}")


RUN_PIPELINE_SCHEMA = schema(
    "azure_devops_run_pipeline",
    "Queue a new pipeline run. Optionally specify branch, template parameters, stages to skip, and variables.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID to run"},
        "pipelineVersion": {"type": "number", "description": "Specific pipeline version to run"},
        "branch": {"type": "string", "description": "Branch to build (e.g. main, feature/login). Defaults to the repo default."},
        "templateParameters": {"type": "object", "description": "Template parameters as key-value pairs"},
        "stagesToSkip": {"type": "array", "items": {"type": "string"}, "description": "Stage names to skip"},
        "variables": {"type": "object", "description": "Build variables as key-value pairs"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId"],
)


@tool_handler
def run_pipeline(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    branch = opt_str(args, "branch")
    template_parameters = opt_str_map(args, "templateParameters")
    stages_to_skip = opt_str_list(args, "stagesToSkip")
    variables = opt_str_map(args, "variables")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.run_pipeline(pipeline_id, branch, template_parameters)

    body: Dict[str, Any] = {}
    if branch:
        ref_name = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
        body["resources"] = {"repositories": {"self": {"refName": ref_name}}}
    if template_parameters:
        body["templateParameters"] = template_parameters
    if stages_to_skip:
        body["stagesToSkip"] = stages_to_skip
    if variables:
        body["variables"] = {key: {"value": value} for key, value in variables.items()}

    try:
        run = client.run_pipeline(config, pipeline_id, body, opt_int(args, "pipelineVersion"))
        if not run:
            return error("Failed to queue the pipeline run — no response.")
        return result(f"✅ Queued pipeline run:\n\n{format_run(run)}", pipelineId=pipeline_id, runId=run.get("id"))
    except Exception as exc:
        return error(f"Failed to run pipeline #{pipeline_id}: {client.format_ado_error(exc)}")


CANCEL_RUN_SCHEMA = schema(
    "azure_devops_cancel_run",
    "Cancel an in-progress pipeline run (build). Sets the build status to cancelling.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "runId": {"type": "number", "description": "Run (build) ID to cancel"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId", "runId"],
)


@tool_handler
def cancel_run(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.cancel_run(pipeline_id, run_id)

    try:
        client.update_build(config, run_id, {"status": 4})
        return result(
            f"✅ Cancelled run #{run_id}\n\n- **Pipeline:** #{pipeline_id}\n- **Status:** cancelling",
            pipelineId=pipeline_id,
            runId=run_id,
        )
    except Exception as exc:
        return error(f"Failed to cancel run #{run_id}: {client.format_ado_error(exc)}")


RETRY_RUN_SCHEMA = schema(
    "azure_devops_retry_run",
    "Retry a failed or partially succeeded pipeline run. Creates a new run based on the original.",
    {
        "pipelineId": {"type": "number", "description": "Pipeline ID"},
        "runId": {"type": "number", "description": "Run (build) ID to retry"},
        "org": ORG_PROPERTY,
        "project": PROJECT_PROPERTY,
        "mock": MOCK_PROPERTY,
    },
    ["pipelineId", "runId"],
)


@tool_handler
def retry_run(args: Dict[str, Any]) -> str:
    config = config_for(args)
    pipeline_id = req_int(args, "pipelineId")
    run_id = req_int(args, "runId")

    if is_mock(config, opt_bool(args, "mock")):
        return mocks.retry_run(pipeline_id, run_id)

    try:
        updated = client.update_build(config, run_id, {}, retry=True)
        return result(
            f"✅ Retried run #{run_id}\n\n"
            f"- **Pipeline:** #{pipeline_id}\n"
            f"- **New run:** #{updated.get('id') if updated else '?'}\n"
            f"- **Status:** {updated.get('status') if updated else 'queued'}",
            pipelineId=pipeline_id,
            originalRunId=run_id,
            newRunId=(updated or {}).get("id"),
        )
    except Exception as exc:
        return error(f"Failed to retry run #{run_id}: {client.format_ado_error(exc)}")
