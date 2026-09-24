"""Test fixtures.

The plugin is imported the way Hermes imports a directory plugin: as a package
whose ``__init__.py`` lives in the repository root, under a namespaced module
name. That also proves the relative imports work outside the source tree.

``ado`` is a real HTTP server on localhost that speaks the Azure DevOps REST
shape, so the live (non-mock) tests go through the actual urllib client and the
actual URL construction.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "hermes_plugins_test.azure_devops"


def _load_plugin():
    if PACKAGE in sys.modules:
        return sys.modules[PACKAGE]
    parent = "hermes_plugins_test"
    if parent not in sys.modules:
        namespace = importlib.util.module_from_spec(
            importlib.machinery.ModuleSpec(parent, None, is_package=True)
        )
        namespace.__path__ = []  # type: ignore[attr-defined]
        sys.modules[parent] = namespace
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin()


def sub(name: str):
    return importlib.import_module(f"{PACKAGE}.{name}")


#: A route reply: a static payload, or a callable receiving ``(body, path, query)``.
Reply = Any
RouteFn = Callable[[Any, str, Dict[str, List[str]]], Tuple[int, Any]]


class FakeAdo:
    """Minimal Azure DevOps: routes by path substring, records every call."""

    def __init__(self) -> None:
        self.routes: List[Tuple[str, str, Any, int]] = []
        self.calls: List[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    # -- routing ---------------------------------------------------------
    def on(self, method: str, path: str, payload: Any, status: int = 200) -> None:
        self.routes.append((method.upper(), path, payload, status))

    def on_fn(self, method: str, path: str, handler: RouteFn, status: int = 200) -> None:
        self.routes.append((method.upper(), path, handler, status))

    def fail(self, method: str, path: str, status: int, payload: Any) -> None:
        self.on(method, path, payload, status=int(status))

    # -- inspection ------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def requests(self, path: Optional[str] = None, method: Optional[str] = None) -> List[dict]:
        found = self.calls
        if path is not None:
            found = [call for call in found if path in call["path"]]
        if method is not None:
            found = [call for call in found if call["method"] == method.upper()]
        return found

    def first(self, path: str, method: Optional[str] = None) -> dict:
        matches = self.requests(path, method)
        assert matches, f"no request matched {method or '*'} {path}; saw {[c['method'] + ' ' + c['path'] for c in self.calls]}"
        return matches[0]

    def bodies(self, path: str) -> List[Any]:
        return [call["body"] for call in self.requests(path)]

    def reset(self) -> None:
        self.calls.clear()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # -- server ----------------------------------------------------------
    def _resolve(self, method: str, path: str):
        for route_method, fragment, payload, status in self.routes:
            if route_method == method and fragment in path:
                return payload, status
        return None, 404

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # keep the test output clean
                pass

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                body: Any = None
                if raw:
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        body = raw

                fake.calls.append(
                    {
                        "method": method,
                        "path": parsed.path,
                        "query": query,
                        "body": body,
                        "headers": dict(self.headers),
                    }
                )

                payload, status = fake._resolve(method, parsed.path)
                if callable(payload):
                    status, payload = payload(body, parsed.path, query)

                if status == 404 and payload is None:
                    payload = {"$id": "1", "message": "The resource could not be found."}

                if payload is None:
                    data = b""
                elif isinstance(payload, str):
                    data = payload.encode("utf-8")
                else:
                    data = json.dumps(payload).encode("utf-8")

                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    "text/html" if isinstance(payload, str) else "application/json",
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PATCH(self):
                self._handle("PATCH")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

        return Handler


@pytest.fixture
def ado():
    server = FakeAdo()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Every test gets its own config file and no pi-extension fallback."""
    config_path = tmp_path / "azure-devops-config.json"
    monkeypatch.setenv("AZURE_DEVOPS_CONFIG", str(config_path))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "pi-agent"))
    monkeypatch.delenv("AZURE_DEVOPS_TEAM", raising=False)

    config = sub("config")
    client = sub("client")
    auth = sub("auth")
    mocks = sub("mocks")
    config._reset_for_testing()
    client.clear_connection_cache()
    auth.clear_token_cache()
    mocks.clear_fixture_cache()
    yield config_path
    config._reset_for_testing()
    client.clear_connection_cache()
    auth.clear_token_cache()
    mocks.clear_fixture_cache()


def write_config(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_template_config(path: Path, data: dict) -> Path:
    """Write the config file in the shape a test then loads."""
    return write_config(path, data)


@pytest.fixture
def configure(isolated_config, ado):
    """Point the plugin at the fake server with one org/project and a team."""

    def apply(
        *,
        org: str = "testorg",
        project: str = "TestProject",
        team: str = "Engineering",
        pat: str = "test-pat-12345",
        extra: Optional[dict] = None,
    ) -> Path:
        data = {
            "orgs": [
                {
                    "name": org,
                    "url": ado.url,
                    "projects": [{"name": project, "pat": pat}],
                }
            ]
        }
        if team:
            data["defaultTeam"] = team
        data.update(extra or {})
        return write_config(isolated_config, data)

    return apply


def call(tool: str, args: Optional[dict] = None) -> dict:
    """Invoke a tool handler the way Hermes does and decode its JSON result."""
    tools = sub("tools")
    handlers = {schema["name"]: handler for schema, handler in tools.TOOLS}
    assert tool in handlers, f"unknown tool {tool}"
    raw = handlers[tool](args or {})
    assert isinstance(raw, str), "handlers must return a JSON string"
    return json.loads(raw)


def tool_names() -> Tuple[str, ...]:
    return sub("tools").TOOL_NAMES


@pytest.fixture
def registered():
    """A fake Hermes ctx that records what register() did."""

    class Ctx:
        def __init__(self):
            self.tools = {}
            self.hooks = {}
            self.commands = {}
            self.skills = {}
            self.sections = {}
            self.settings = {"safety_level": "open"}

        def register_tool(self, name, toolset, schema, handler, description=""):
            self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

        def register_hook(self, name, callback):
            self.hooks[name] = callback

        def register_command(self, name, handler, description="", args_hint=""):
            self.commands[name] = {
                "handler": handler,
                "description": description,
                "args_hint": args_hint,
            }

        def register_skill(self, name, path, description="", frontmatter=None):
            self.skills[name] = {"path": Path(path), "description": description}

        def register_system_prompt_section(self, section_id, content, **_kwargs):
            self.sections[section_id] = content

        def get_config(self, key, default=None):
            return self.settings.get(key, default)

    ctx = Ctx()
    plugin.register(ctx)
    return ctx
