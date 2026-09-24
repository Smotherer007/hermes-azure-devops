"""Shared plumbing for the tool modules.

Hermes hands a handler the raw arguments the model produced and expects a JSON
string back -- also on failure, so a handler must never raise. Models also send
numbers as strings and booleans as ``"true"`` now and then, so every tool reads
its arguments through the coercing helpers below instead of trusting the schema.

There is one behaviour change from pi-azure-devops worth naming: pi is handed a
resolved session config by the extension host, while Hermes plugins resolve
their own. :func:`config_for` therefore resolves the base config from the file
on every call (cheap: the file is only re-read when its mtime changes) and then
applies the tool's ``org``/``project`` override on top.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Callable, Dict, List, Optional

from .. import config as cfg
from ..models import AzureDevOpsConfig, ToolInputError

#: Every tool carries these three.
MOCK_PROPERTY = {
    "type": "boolean",
    "description": "Use mock/fixture data instead of the live Azure DevOps API",
}
ORG_PROPERTY = {
    "type": "string",
    "description": "Organization name (e.g. 'neoimpulse', 'eagleburgmann'). Uses the default if omitted.",
}
PROJECT_PROPERTY = {
    "type": "string",
    "description": "Project name (e.g. 'PI Agent Reviewer', 'SCODA'). Uses the default if omitted.",
}
TEAM_PROPERTY = {
    "type": "string",
    "description": 'Team name. Uses "defaultTeam" from the config file if omitted.',
}

NO_TEAM_MESSAGE = (
    'No team specified. Set "defaultTeam" in azure-devops-config.json, '
    "or pass the team parameter."
)


def schema(name: str, description: str, properties: Dict[str, Any], required: List[str] = ()) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


def result(text: str, **details: Any) -> str:
    """Success: the formatted text the model reads, plus structured details."""
    return json.dumps({"result": text, **details}, ensure_ascii=False, default=str)


def error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def tool_handler(fn: Callable[[dict], str]) -> Callable[..., str]:
    """Wrap a handler so every exception becomes an ``{"error": ...}`` result."""

    @functools.wraps(fn)
    def wrapper(args: Optional[dict] = None, **_kwargs: Any) -> str:
        try:
            return fn(args if isinstance(args, dict) else {})
        except Exception as exc:  # the contract: never raise into the agent loop
            return error(str(exc) or type(exc).__name__)

    return wrapper


# ---------------------------------------------------------------------------
# Argument coercion
# ---------------------------------------------------------------------------


def opt_str(args: dict, key: str) -> Optional[str]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        raise ToolInputError(f"{key} must be a string.")
    return str(value)


def req_str(args: dict, key: str) -> str:
    value = opt_str(args, key)
    if value is None or not value.strip():
        raise ToolInputError(f"{key} must not be empty.")
    return value


def opt_int(args: dict, key: str) -> Optional[int]:
    value = args.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ToolInputError(f"{key} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ToolInputError(f"{key} must be a number.") from None
    if number != int(number):
        raise ToolInputError(f"{key} must be a whole number.")
    return int(number)


def req_int(args: dict, key: str) -> int:
    value = opt_int(args, key)
    if value is None:
        raise ToolInputError(f"{key} must not be empty.")
    return value


def opt_bool(args: dict, key: str) -> Optional[bool]:
    value = args.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "1"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "no", "0"):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ToolInputError(f"{key} must be true or false.")


def opt_str_list(args: dict, key: str) -> Optional[List[str]]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        # "draft,archived" or a JSON array that arrived as a string
        try:
            parsed = json.loads(value)
            value = parsed if isinstance(parsed, list) else [value]
        except ValueError:
            value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be a list of strings.")
    return [str(item) for item in value]


def opt_int_list(args: dict, key: str) -> Optional[List[int]]:
    value = args.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = [part.strip() for part in value.split(",") if part.strip()]
        value = parsed if isinstance(parsed, list) else [parsed]
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be a list of numbers.")
    numbers: List[int] = []
    for item in value:
        if isinstance(item, bool):
            raise ToolInputError(f"{key} must be a list of numbers.")
        try:
            numbers.append(int(float(item)))
        except (TypeError, ValueError):
            raise ToolInputError(f"{key} must be a list of numbers.") from None
    return numbers


def opt_str_map(args: dict, key: str) -> Optional[Dict[str, str]]:
    value = args.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ToolInputError(f"{key} must be an object of key/value pairs.") from None
    if not isinstance(value, dict):
        raise ToolInputError(f"{key} must be an object of key/value pairs.")
    return {str(k): str(v) for k, v in value.items()}


def opt_dict(args: dict, key: str) -> Optional[Dict[str, Any]]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ToolInputError(f"{key} must be an object.") from None
    if not isinstance(value, dict):
        raise ToolInputError(f"{key} must be an object.")
    return value


def opt_dict_list(args: dict, key: str) -> Optional[List[Dict[str, Any]]]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ToolInputError(f"{key} must be a list of objects.") from None
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be a list of objects.")
    items: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ToolInputError(f"{key} must be a list of objects.")
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Config and team context
# ---------------------------------------------------------------------------


def config_for(args: dict) -> AzureDevOpsConfig:
    """The base config with the tool's ``org``/``project`` override applied."""
    base = cfg.resolve_config()
    return cfg.resolve_org_project_config(base, opt_str(args, "org"), opt_str(args, "project"))


def is_mock(config: AzureDevOpsConfig, tool_mock: Optional[bool]) -> bool:
    return bool(config.mock or tool_mock is True)


def resolve_team_context(config: AzureDevOpsConfig, team_param: Optional[str]) -> Optional[Dict[str, str]]:
    """TeamContext ``{project, team}`` for the Work API, or None when no team is set."""
    team = (team_param or "").strip() or config.team
    if not team:
        return None
    return {"project": config.project, "team": team}


def team_name(config: AzureDevOpsConfig, team_param: Optional[str]) -> str:
    context = resolve_team_context(config, team_param)
    return context["team"] if context else ""
