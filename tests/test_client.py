"""The REST client: URLs, auth headers, api-versions and error translation.

These are the tests that matter most for the port, because pi-azure-devops used
the npm SDK and this plugin builds the URLs itself.
"""

from __future__ import annotations

import base64

import pytest

from conftest import sub

client = sub("client")
auth = sub("auth")
models = sub("models")


def _config(ado, **overrides):
    base = {
        "org_url": ado.url,
        "project": "TestProject",
        "org_name": "testorg",
        "team": "Engineering",
        "pat": "test-pat-12345",
        "all_orgs": (),
        "auth_method": "pat",
        "safety_level": "confirm",
        "default_work_item_type": "User Story",
        "max_query_results": 100,
        "autocomplete": True,
        "mock": False,
    }
    base.update(overrides)
    return models.AzureDevOpsConfig(**base)


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call, path_fragment",
    [
        (lambda c: client.get_work_item(c, 101), "/TestProject/_apis/wit/workitems/101"),
        (lambda c: client.get_work_item_types(c), "/TestProject/_apis/wit/workitemtypes"),
        (lambda c: client.get_comments(c, 101), "/TestProject/_apis/wit/workItems/101/comments"),
        (lambda c: client.get_revisions(c, 101), "/TestProject/_apis/wit/workItems/101/revisions"),
        (lambda c: client.get_boards(c, "Engineering"), "/TestProject/Engineering/_apis/work/boards"),
        (
            lambda c: client.get_board(c, "Engineering", "stories"),
            "/TestProject/Engineering/_apis/work/boards/stories",
        ),
        (
            lambda c: client.get_team_iterations(c, "Engineering"),
            "/TestProject/Engineering/_apis/work/teamsettings/iterations",
        ),
        (
            lambda c: client.get_capacities(c, "Engineering", "sprint-3"),
            "/TestProject/Engineering/_apis/work/teamsettings/iterations/sprint-3/capacities",
        ),
        (lambda c: client.get_projects(c), "/_apis/projects"),
        (lambda c: client.get_teams(c), "/_apis/projects/TestProject/teams"),
        (lambda c: client.list_repositories(c), "/TestProject/_apis/git/repositories"),
        (lambda c: client.get_repository(c, "repo-webapp"), "/TestProject/_apis/git/repositories/repo-webapp"),
        (
            lambda c: client.list_branches(c, "repo-webapp"),
            "/TestProject/_apis/git/repositories/repo-webapp/stats/branches",
        ),
        (
            lambda c: client.list_pull_requests(c),
            "/TestProject/_apis/git/pullrequests",
        ),
        (
            lambda c: client.get_pull_request(c, 7),
            "/TestProject/_apis/git/pullrequests/7",
        ),
        (
            lambda c: client.get_pull_request_threads(c, "repo-webapp", 7),
            "/TestProject/_apis/git/repositories/repo-webapp/pullRequests/7/threads",
        ),
        (
            lambda c: client.get_pull_request_commits(c, "repo-webapp", 7),
            "/TestProject/_apis/git/repositories/repo-webapp/pullRequests/7/commits",
        ),
        (lambda c: client.list_policies(c), "/TestProject/_apis/policy/configurations"),
        (lambda c: client.list_pipelines(c), "/TestProject/_apis/pipelines"),
        (lambda c: client.get_run(c, 1, 42), "/TestProject/_apis/pipelines/1/runs/42"),
        (lambda c: client.list_builds(c), "/TestProject/_apis/build/builds"),
        (lambda c: client.get_build_artifacts(c, 42), "/TestProject/_apis/build/builds/42/artifacts"),
        (lambda c: client.get_build_logs(c, 42), "/TestProject/_apis/build/builds/42/logs"),
        (lambda c: client.get_build_timeline(c, 42), "/TestProject/_apis/build/builds/42/timeline"),
        (lambda c: client.list_test_plans(c), "/TestProject/_apis/testplan/plans"),
        (lambda c: client.get_test_plan(c, 101), "/TestProject/_apis/testplan/plans/101"),
        (lambda c: client.list_test_suites(c, 101), "/TestProject/_apis/testplan/Plans/101/Suites"),
        (lambda c: client.get_test_suite(c, 101, 301), "/TestProject/_apis/testplan/Plans/101/Suites/301"),
        (lambda c: client.list_test_cases(c, 101, 301), "/TestProject/_apis/testplan/Plans/101/Suites/301/TestCase"),
        (lambda c: client.list_test_points(c, 101, 301), "/TestProject/_apis/testplan/Plans/101/Suites/301/TestPoint"),
        (lambda c: client.list_test_runs(c), "/TestProject/_apis/test/runs"),
        (lambda c: client.get_test_run(c, 501), "/TestProject/_apis/test/runs/501"),
    ],
)
def test_endpoint_paths(ado, call, path_fragment):
    config = _config(ado)
    ado.on("GET", path_fragment, {"value": []})
    call(config)

    paths = [entry["path"] for entry in ado.calls]
    assert path_fragment in paths, f"expected {path_fragment}, saw {paths}"


def test_query_parameters_are_rendered(ado):
    config = _config(ado)
    ado.on("POST", "/_apis/wit/wiql", {"workItems": []})
    client.query_by_wiql(config, "SELECT [System.Id] FROM WorkItems", top=25)

    assert ado.calls[0]["method"] == "POST"
    assert ado.calls[0]["body"] == {"query": "SELECT [System.Id] FROM WorkItems"}
    assert ado.calls[0]["query"]["$top"] == ["25"]
    assert ado.calls[0]["query"]["api-version"] == ["7.1"]


def test_boolean_and_list_parameters(ado):
    config = _config(ado)
    ado.on("GET", "/_apis/build/builds", {"value": []})
    client.list_builds(config, definitions=[1, 2], status="inProgress", top=5)

    query = ado.calls[0]["query"]
    assert query["definitions"] == ["1,2"]
    assert query["statusFilter"] == ["inProgress"]
    assert query["$top"] == ["5"]


def test_include_hidden_is_only_sent_when_requested(ado):
    config = _config(ado)
    ado.on("GET", "/_apis/git/repositories", {"value": []})

    client.list_repositories(config)
    assert "includeHidden" not in ado.calls[0]["query"]

    ado.reset()
    client.list_repositories(config, include_hidden=True)
    assert ado.calls[0]["query"]["includeHidden"] == ["true"]


def test_project_and_team_names_are_url_encoded(ado):
    config = _config(ado, project="PI Agent Reviewer", team="My Team")
    ado.on("GET", "/_apis/work/boards", {"value": []})
    client.get_boards(config, "My Team")

    path = ado.calls[0]["path"]
    assert "PI%20Agent%20Reviewer" in path
    assert "My%20Team" in path


# ---------------------------------------------------------------------------
# API versions
# ---------------------------------------------------------------------------


def test_comments_use_the_preview_api_version(ado):
    config = _config(ado)
    ado.on("GET", "/comments", {"comments": []})
    client.get_comments(config, 101)
    assert ado.calls[0]["query"]["api-version"] == [client.COMMENTS_API_VERSION]


def test_work_item_patch_uses_json_patch_content_type(ado):
    config = _config(ado)
    ado.on("POST", "/workitems/", {"id": 1})
    client.create_work_item(config, "Bug", [{"op": "add", "path": "/fields/System.Title", "value": "t"}])

    assert ado.calls[0]["headers"]["Content-Type"] == "application/json-patch+json"


def test_artifact_link_patch_uses_api_version_7_0(ado):
    """ArtifactLinks are dropped on 7.1-preview.x, which is why 7.0 is pinned."""
    config = _config(ado)
    ado.on("PATCH", "/workitems/101", {"id": 101})
    client.update_work_item(config, 101, [{"op": "add", "path": "/relations/-", "value": {}}],
                            api_version=client.ARTIFACT_LINK_API_VERSION)

    assert ado.calls[0]["query"]["api-version"] == ["7.0"]
    assert ado.calls[0]["method"] == "PATCH"


def test_default_work_item_patch_uses_the_stable_version(ado):
    config = _config(ado)
    ado.on("PATCH", "/workitems/101", {"id": 101})
    client.update_work_item(config, 101, [{"op": "replace", "path": "/fields/System.State", "value": "Active"}])
    assert ado.calls[0]["query"]["api-version"] == ["7.1"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_pat_is_sent_as_basic_auth_with_an_empty_username(ado):
    config = _config(ado, pat="my-token")
    ado.on("GET", "/workitemtypes", {"value": []})
    client.get_work_item_types(config)

    header = ado.calls[0]["headers"]["Authorization"]
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
    assert decoded == ":my-token"


def test_azure_cli_token_is_sent_as_bearer(ado, monkeypatch):
    config = _config(ado, pat=None, auth_method="azure-cli")
    monkeypatch.setattr(auth, "acquire_cli_token", lambda timeout=0: "cli-token")

    ado.on("GET", "/workitemtypes", {"value": []})
    client.get_work_item_types(config)

    assert ado.calls[0]["headers"]["Authorization"] == "Bearer cli-token"


def test_auth_headers_are_cached_per_pat(ado):
    config = _config(ado, pat="one")
    ado.on("GET", "/workitemtypes", {"value": []})
    client.get_work_item_types(config)
    client.get_work_item_types(config)

    assert len(ado.calls) == 2

    az = _config(ado, pat="two")
    client.get_work_item_types(az)
    header = ado.calls[2]["headers"]["Authorization"]
    assert base64.b64decode(header.split(" ", 1)[1]).decode() == ":two"


def test_missing_credentials_raise_auth_error(ado):
    config = _config(ado, pat=None, auth_method="azure-cli")
    with pytest.raises(models.AuthError):
        client.get_work_item_types(config)


def test_authenticated_user_id_is_read_and_cached(ado):
    config = _config(ado)
    ado.on("GET", "/_apis/connectionData", {"authenticatedUser": {"id": "user-123"}})

    assert client.authenticated_user_id(config) == "user-123"
    assert client.authenticated_user_id(config) == "user-123"
    assert len(ado.requests("/_apis/connectionData")) == 1


def test_clear_connection_cache_forces_a_fresh_header_lookup(ado):
    config = _config(ado, pat="one")
    ado.on("GET", "/workitemtypes", {"value": []})
    client.get_work_item_types(config)

    client.clear_connection_cache()
    changed = _config(ado, pat="two")
    client.get_work_item_types(changed)
    header = ado.calls[1]["headers"]["Authorization"]
    assert base64.b64decode(header.split(" ", 1)[1]).decode() == ":two"


# ---------------------------------------------------------------------------
# Payload handling and errors
# ---------------------------------------------------------------------------


def test_collections_are_unwrapped_from_the_value_envelope(ado):
    config = _config(ado)
    ado.on("GET", "/workitemtypes", {"count": 1, "value": [{"name": "Bug"}]})
    assert client.get_work_item_types(config) == [{"name": "Bug"}]


def test_empty_body_is_handled(ado):
    config = _config(ado)
    ado.on("DELETE", "/teamsettings/iterations/i1", None, status=204)
    assert client.delete_team_iteration(config, "Engineering", "i1") is None


def test_401_is_reported_as_a_credential_problem(ado):
    config = _config(ado)
    ado.fail("GET", "/workitemtypes", 401, {"message": "Unauthorized"})
    with pytest.raises(models.AzureDevOpsApiError) as error:
        client.get_work_item_types(config)
    assert "credentials" in str(error.value).lower()
    assert client.is_auth_error(error.value)


def test_403_mentions_the_required_scopes(ado):
    config = _config(ado)
    ado.fail("GET", "/workitemtypes", 403, {"message": "Forbidden"})
    with pytest.raises(models.AzureDevOpsApiError) as error:
        client.get_work_item_types(config)
    assert "403" in str(error.value)


def test_404_becomes_a_not_found_error(ado):
    config = _config(ado)
    ado.fail("GET", "/workitems/999", 404, {"message": "not found"})
    with pytest.raises(models.NotFoundError):
        client.get_work_item(config, 999)


def test_429_is_reported_as_rate_limiting(ado):
    config = _config(ado)
    ado.fail("GET", "/workitemtypes", 429, {"message": "slow down"})
    with pytest.raises(models.AzureDevOpsApiError) as error:
        client.get_work_item_types(config)
    assert "rate limit" in str(error.value).lower()


def test_html_response_is_diagnosed_as_a_wrong_url(ado):
    config = _config(ado)
    ado.on("GET", "/workitemtypes", "<html><body>Sign in</body></html>", status=200)
    with pytest.raises(models.AzureDevOpsApiError) as error:
        client.get_work_item_types(config)
    assert "HTML" in str(error.value)


@pytest.mark.parametrize(
    "message, expected",
    [
        ("TF401232: The project does not exist", "Project not found"),
        ("TF401233: The work item does not exist", "Work item not found"),
        ("VS402335: Invalid work item type", "Invalid work item type"),
        ("401 Unauthorized", "Authentication failed"),
        ("403 Forbidden", "Permission denied"),
        ("404 Not Found", "Resource not found"),
        ("429 too many requests", "Rate limited"),
        ("ETIMEDOUT", "Network error"),
        ("ENOTFOUND", "DNS error"),
    ],
)
def test_error_messages_are_translated(message, expected):
    assert expected in client.format_ado_error(models.AzureDevOpsApiError(0, message))


def test_unknown_error_keeps_only_the_first_line():
    assert client.format_ado_error(RuntimeError("first line\nstack trace here")) == "first line"


def test_unreachable_host_is_reported_not_raised_raw():
    config = models.AzureDevOpsConfig(
        org_url="http://127.0.0.1:1", project="P", pat="x", auth_method="pat"
    )
    with pytest.raises(models.AzureDevOpsApiError) as error:
        client.get_work_item_types(config)
    assert error.value.status == 0
    assert "Could not reach Azure DevOps" in str(error.value) or "did not respond" in str(error.value)
