"""Authentication for Azure DevOps.

Two methods, in the same precedence pi-azure-devops uses:

1. A personal access token from the config file, sent as HTTP Basic with an
   empty user name (``Basic base64(":" + pat)``).
2. The Azure CLI (``az``), whose Entra ID token is sent as ``Bearer``. That
   suits machines where a developer is already logged in and no PAT is stored.

``authMethod`` in the config file picks one explicitly; ``auto`` prefers a PAT
when one is configured and falls back to the CLI.

Only the standard library is used: the CLI call is a plain subprocess.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .models import AuthError, AzureDevOpsConfig

logger = logging.getLogger(__name__)

#: Azure DevOps resource id, required when asking the CLI for a token.
AZURE_DEVOPS_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"

#: ``az account get-access-token`` is a network call; do not hang the agent.
CLI_TIMEOUT_S = 15.0

#: Tokens usually last 60 minutes; refresh well before that.
TOKEN_TTL_S = 50 * 60


@dataclass(frozen=True)
class AuthResult:
    """The headers and the method that produced them."""

    headers: Dict[str, str]
    method: str


_lock = threading.RLock()
_cached_token: Optional[tuple] = None  # (token, expires_at)


def _basic_headers(pat: str) -> Dict[str, str]:
    credentials = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {credentials}"}


def create_pat_auth(pat: Optional[str]) -> Optional[AuthResult]:
    if not pat:
        return None
    return AuthResult(headers=_basic_headers(pat), method="pat")


def azure_cli_available() -> bool:
    """Whether an ``az`` executable is on PATH."""
    return shutil.which("az") is not None


def clear_token_cache() -> None:
    global _cached_token
    with _lock:
        _cached_token = None


def acquire_cli_token(timeout: float = CLI_TIMEOUT_S) -> str:
    """Get an Entra ID token for Azure DevOps from the Azure CLI, cached."""
    global _cached_token
    with _lock:
        if _cached_token and _cached_token[1] > time.time() + 5 * 60:
            return _cached_token[0]

    command = [
        "az",
        "account",
        "get-access-token",
        "--resource",
        AZURE_DEVOPS_RESOURCE_ID,
        "--output",
        "json",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "AZURE_CORE_ONLY_SHOW_ERRORS": "true"},
        )
    except FileNotFoundError:
        raise AuthError("Azure CLI not found: the 'az' command is not installed.") from None
    except subprocess.TimeoutExpired:
        raise AuthError(f"Azure CLI did not answer within {round(timeout)}s.") from None

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise AuthError(
            "Azure CLI authentication failed: "
            + (detail[0] if detail else "az returned a non-zero exit code. Run `az login`.")
        )

    try:
        parsed = json.loads(completed.stdout)
        token = str(parsed["token"])
    except (ValueError, KeyError, TypeError):
        raise AuthError(
            f"Could not parse the Azure CLI response: {completed.stdout.strip()[:200]}"
        ) from None

    with _lock:
        _cached_token = (token, time.time() + TOKEN_TTL_S)
    return token


def create_cli_auth() -> Optional[AuthResult]:
    try:
        return AuthResult(headers={"Authorization": f"Bearer {acquire_cli_token()}"}, method="azure-cli")
    except AuthError:
        return None


def _methods_to_try(auth_method: str, has_pat: bool) -> List[str]:
    if auth_method == "pat":
        return ["pat"]
    if auth_method == "azure-cli":
        return ["azure-cli"]
    return ["pat", "azure-cli"] if has_pat else ["azure-cli", "pat"]


def resolve_auth(config: AzureDevOpsConfig) -> AuthResult:
    """Resolve authentication for one connection, or raise :class:`AuthError`."""
    errors: List[str] = []
    for method in _methods_to_try(config.auth_method, bool(config.pat)):
        if method == "pat":
            result = create_pat_auth(config.pat)
            if result:
                return result
            errors.append("PAT: no token configured for this project")
        else:
            result = create_cli_auth()
            if result:
                return result
            errors.append("Azure CLI: not authenticated, or az is not installed")

    raise AuthError(
        "No Azure DevOps authentication method available. Add a PAT to the config file, "
        "or sign in with `az login`.",
        errors,
    )


def try_resolve_auth(config: AzureDevOpsConfig) -> Optional[AuthResult]:
    try:
        return resolve_auth(config)
    except AuthError:
        return None
