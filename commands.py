"""Slash commands.

Two kinds live here:

``/azure-devops-status``
    Answers immediately from the config file -- no model turn, no network.

the prompt templates
    pi-azure-devops ships 14 prompt templates in ``prompts/``; Hermes has no
    prompt-template loader, so each one is registered as a slash command whose
    handler renders the template and hands the result to the agent.

Rendering keeps pi's template syntax, so the files stay usable by both agents:
``$1``/``$2`` are positional arguments, ``$2{ ... }`` keeps its body only when
that argument was given, and ``{{#if key}}A{{else}}B{{/if}}``/``{{key}}`` handle
the two named markers the doctor template uses.

In the CLI, ``ctx.inject_message`` always works. In the gateway (Teams,
Telegram, ...) Hermes only allows it when the operator sets
``plugins.entries.azure-devops.allow_gateway_injection: true``; without that the
command answers with the rendered prompt so the user can send it as a message.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config as cfg
from .status import build_card, status_text

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

#: Prompt-template files whose command name a purpose-built handler occupies.
#: ``azure-devops-doctor.md`` renders nearly the same prompt but without the
#: "is anything configured" pre-check, so the handler wins.
DEDICATED_COMMANDS = frozenset({"status", "doctor"})

NOT_CONFIGURED = (
    "Azure DevOps is not configured. Edit "
    "{path} with your orgs, projects, and PATs "
    "(a template is created on first start)."
)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_MUSTACHE_IF = re.compile(r"\{\{#if\s+([\w.]+)\s*\}\}(.*?)(?:\{\{else\}\}(.*?))?\{\{/if\}\}", re.S)
_MUSTACHE_VAR = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")
_POSITIONAL_BLOCK = re.compile(r"\$(\d)\{([^{}]*)\}")


def parse_template(text: str) -> Tuple[Dict[str, str], str]:
    """Split an optional frontmatter block from the body."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def render_template(text: str, args: List[str], named: Optional[Dict[str, str]] = None) -> str:
    """Render pi's prompt-template syntax with the given arguments."""
    named = named or {}
    values = dict(named)
    for index, arg in enumerate(args, start=1):
        values[str(index)] = arg

    # $2{ ... } -- keep the body only when that positional argument was given.
    def positional_block(match: re.Match) -> str:
        index, body = match.group(1), match.group(2)
        return body if (values.get(index) or "").strip() else ""

    text = _POSITIONAL_BLOCK.sub(positional_block, text)

    def conditional(match: re.Match) -> str:
        key, if_body, else_body = match.group(1), match.group(2), match.group(3)
        return if_body if (values.get(key) or "").strip() else (else_body or "")

    text = _MUSTACHE_IF.sub(conditional, text)
    text = _MUSTACHE_VAR.sub(lambda match: str(values.get(match.group(1), "")), text)

    # Plain $1 / $2 substitution last, so $1{...} was already resolved.
    for index, value in sorted(values.items(), key=lambda item: -len(item[0])):
        text = text.replace(f"${index}", value)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_templates() -> List[Tuple[str, str, str, str]]:
    """``(command_name, description, args_hint, body)`` for every file in ``prompts/``."""
    templates: List[Tuple[str, str, str, str]] = []
    if not PROMPTS_DIR.is_dir():
        return templates
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        try:
            meta, body = parse_template(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        name = path.stem
        if name.startswith("azure-devops-"):
            name = name[len("azure-devops-"):]
        templates.append((name, meta.get("description") or "", meta.get("argument-hint") or "", body))
    return templates


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _session_key() -> str:
    try:  # bound by the gateway around plugin command dispatch
        from gateway.session_context import get_session_env  # type: ignore

        return get_session_env("HERMES_SESSION_KEY", "")
    except Exception:
        return os.environ.get("HERMES_SESSION_KEY", "")


def _deliver(ctx: Any, prompt: str, started: str) -> str:
    try:
        key = _session_key() or None
        if ctx.inject_message(prompt, session_key=key):
            return started
    except Exception:
        logger.debug("azure-devops: message injection failed", exc_info=True)
    return (
        "I could not start this automatically here (the gateway needs "
        "plugins.entries.azure-devops.allow_gateway_injection: true). "
        "Send this as a message instead:\n\n" + prompt
    )


def _not_configured() -> str:
    return NOT_CONFIGURED.format(path=cfg.config_path())


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def make_status_command(ctx: Any) -> Callable[[str], str]:
    def azure_devops_status(raw_args: str = "") -> str:
        config = cfg.try_resolve_config()
        label = "### Azure DevOps status\n\n"
        try:
            from .auth import try_resolve_auth

            if config is not None and try_resolve_auth(config) is None:
                label += "⚠️ No authentication available. Add a PAT or run `az login`.\n\n"
        except Exception:
            pass
        text = status_text(build_card(config), str(cfg.config_path()))
        if cfg.using_pi_file():
            text += (
                "\n\n_This configuration was read from pi-azure-devops' file "
                f"(`{cfg.config_path()}`). Set `AZURE_DEVOPS_CONFIG` or create the Hermes file "
                "to keep the two agents separate._"
            )
        return label + text

    return azure_devops_status


def make_doctor_command(ctx: Any) -> Callable[[str], str]:
    def azure_devops_doctor(raw_args: str = "") -> str:
        if cfg.try_resolve_config() is None:
            return _not_configured()
        prompt = (
            "Check the Azure DevOps configuration and connection health. "
            "Run the azure_devops_doctor tool first, then report what it found: "
            "which orgs and projects are configured, whether authentication works, "
            "and what to fix if anything failed."
        )
        extra = (raw_args or "").strip()
        if extra:
            prompt += f" Focus on: {extra}."
        return _deliver(ctx, prompt, "Checking the Azure DevOps connection...")

    return azure_devops_doctor


def make_template_command(ctx: Any, name: str, description: str, body: str) -> Callable[[str], str]:
    def command(raw_args: str = "") -> str:
        if cfg.try_resolve_config() is None:
            return _not_configured()

        # Split on whitespace, keeping the trailing argument whole so a pasted
        # list or WIQL clause survives.
        text = (raw_args or "").strip()
        parts = text.split(None, 2) if text else []
        prompt = render_template(body, parts)
        started = description or f"Running /azure-devops-{name}..."
        return _deliver(ctx, prompt, started)

    return command


def template_commands(ctx: Any) -> List[Tuple[str, Callable[[str], str], str, str]]:
    """``(name, handler, description, args_hint)`` for every prompt template.

    Template names that a dedicated command already owns are skipped, so
    ``/azure-devops-doctor`` is the version that checks the config first rather
    than a second, near-identical registration of the same name.
    """
    commands: List[Tuple[str, Callable[[str], str], str, str]] = []
    for name, description, hint, body in load_templates():
        if name in DEDICATED_COMMANDS:
            continue
        commands.append(
            (name, make_template_command(ctx, name, description, body), description, hint)
        )
    return commands
