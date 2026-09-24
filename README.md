# hermes-azure-devops

Azure DevOps for [Hermes Agent](https://github.com/NousResearch/hermes-agent):
work items, boards, sprints and capacity, repositories and pull requests,
pipelines and builds, and test plans — **54 tools**, read and write.

This is a port of the pi extension
[pi-azure-devops](https://github.com/Smotherer007/pi-azure-devops): the same
tools with the same names and parameters, the same config file shape, the same
safety levels, the same skills and the same prompt templates. The npm
dependency is gone — everything is Python standard library.

```
hermes plugins install Smotherer007/hermes-azure-devops
```

## Setup

Configuration lives in `$HERMES_HOME/azure-devops-config.json` (override with
`AZURE_DEVOPS_CONFIG`). The file is the single source of truth, in the same
shape pi-azure-devops writes, so one file can serve both agents:

```json
{
  "orgs": [
    {
      "name": "my-org",
      "url": "https://dev.azure.com/my-org",
      "projects": [
        { "name": "MyProject", "pat": "your-personal-access-token" }
      ]
    }
  ],
  "defaultOrg": "my-org",
  "defaultProject": "MyProject",
  "defaultTeam": "MyTeam",
  "authMethod": "auto",
  "safetyLevel": "confirm"
}
```

Per-org and per-project `safetyLevel` are honoured, and an org can set
`"insecureTls": true` for an on-premise server with a self-signed certificate.

A template is written on first start. Then:

```
/azure-devops-doctor
```

validates **every** configured org × project: authentication, reachability and
the work item types it can see.

If the file is missing, the plugin reads `~/.pi/agent/pi-azure-devops.json`
read-only, so a machine already set up for the pi extension works without
copying PATs around. `/azure-devops-status` says when that is happening.

### Authentication

| `authMethod` | Behaviour |
| --- | --- |
| `auto` (default) | A PAT if one is configured for the project, otherwise the Azure CLI |
| `pat` | Only the PAT |
| `azure-cli` | Only `az account get-access-token` (run `az login` once) |

A PAT is sent as HTTP Basic (`":" + pat`, which is what Azure DevOps expects for
a PAT). The CLI token is sent as `Bearer` and cached for 50 minutes.

The file holds plaintext PATs, so it is created `0600` inside a `0700`
directory. Keep it that way.

### Safety

Mutation tools are gated by a safety level. There are two sources, and the
**more restrictive one wins** — the Hermes setting can only tighten, never
loosen, so a plugin-level `readonly` locks everything down while a project-level
`readonly` cannot be undone by the plugin default:

1. `plugins.entries.azure-devops.settings.safety_level` (default `open`, i.e. no
   extra restriction)
2. `safetyLevel` in the config file, cascading **project > org > global**
   (global default `confirm`)

| Level | Effect |
| --- | --- |
| `open` | Mutations run directly |
| `confirm` | Every mutation goes through Hermes' approval prompt, which shows a one-line summary of what would change |
| `readonly` | Mutations are blocked |

Pinning a production org to `readonly` while a dev org stays `open` is the usual
setup. The gate is evaluated per call against the `org`/`project` the tool
actually targets, so `{ "org": "prod" }` is blocked even when the default
connection is unrestricted. The 18 gated tools are work item create/update/comment/link, board
columns, iteration and capacity writes, pull request create/update/comment/vote/
auto-complete/link, pipeline run/cancel/retry, and test run create / result
update. Reads are never affected.

## Tools

| Area | Tools |
| --- | --- |
| Health | `azure_devops_doctor` |
| Work items | `get_work_item`, `query_work_items`, `list_work_item_types`, `get_work_item_comments`, `get_work_item_revisions`, `create_work_item`, `update_work_item`, `add_work_item_comment`, `manage_work_item_links` |
| Boards & sprints | `list_teams`, `list_boards`, `get_board`, `list_iterations`, `get_iteration_work_items`, `get_capacity`, `set_board_columns`, `set_iteration`, `set_capacity` |
| Repos & PRs | `list_repos`, `get_repo`, `list_branches`, `list_pull_requests`, `get_pull_request`, `get_pull_request_threads`, `get_pull_request_commits`, `list_policies`, `get_policy_evaluations`, `create_pull_request`, `update_pull_request`, `add_pull_request_comment`, `set_pull_request_vote`, `set_pull_request_autocomplete`, `link_pr_work_items` |
| Pipelines | `list_pipelines`, `get_pipeline`, `list_runs`, `get_run`, `get_run_artifacts`, `get_run_logs`, `get_run_timeline`, `run_pipeline`, `cancel_run`, `retry_run` |
| Test plans | `list_test_plans`, `get_test_plan`, `list_test_suites`, `get_test_suite`, `list_test_cases`, `list_test_points`, `get_test_run`, `list_test_runs`, `create_test_run`, `update_test_results` |

Every tool carries `org` and `project` to retarget the call, and `mock` to
answer from the bundled fixtures without touching the network. Setting
`"mock": true` in the config file switches everything to fixtures at once.

### Mock mode

All 54 tools answer offline from the JSON fixtures in `fixtures/`, through the
same formatters as the live path, so the output shape is identical apart from
the `(mock mode)` marker and a `⚠️ This is mock data` note. That is how the test
suite runs without credentials.

## Commands

| Command | What it does |
| --- | --- |
| `/azure-devops-status` | The active connection, auth method, safety level and mode. No model turn |
| `/azure-devops-doctor` | Asks the agent to validate every configured org and project |
| 13 prompt templates | `pr-review`, `pr-creator`, `triage`, `sprint-health`, `plan-sprint`, `plan-status`, `board-review`, `pipeline-status`, `test-status`, `test-runner`, `status-report`, `review-history`, `deploy`, `create-batch` — the same files pi ships, rendered with the same `$1` / `$2{...}` syntax |

## Skills

`azure-devops:azure-devops-workitems` is registered with the plugin and is the
place for the tool's own conventions (WIQL, relation types, PR vote values,
policy evaluation states, test point semantics). The system prompt gets a short
pointer to it plus the list of configured orgs.

## What differs from pi-azure-devops

The tools, parameters, output and config format are the same. Four deliberate
differences:

1. **No npm SDK.** `azure-devops-node-api` is replaced by a standard-library
   REST client (`client.py`). Nothing is added to Hermes' virtualenv.
2. **A PR vote works.** pi sends an empty reviewer id and Azure DevOps answers
   `401`. This port resolves the real identity from `connectionData` and votes
   as that user.
3. **Auto-complete works.** pi sends `autoCompleteSetBy: {"id": ""}`, which fails
   with "Invalid argument value". This port sends the real identity id.
4. **Unlinking a PR work item works.** pi reads the work item without
   `$expand=relations`, so it never finds the link to remove. This port expands.
5. **A not-yet-run test point reads `⏸️ not executed`** instead of `❓ ?`.
   Azure DevOps omits the `outcome` field entirely until a point is executed,
   and `?` read like an unknown or failed result.

The first two are documented as failures in the `azure-devops-pr-approve-
autocomplete` skill for the pi extension.

Also, `org` now selects an org by its configured `name` (pi derived it from the
URL, which only works for `dev.azure.com` hosts). On-premise collections work.

## Layout

```
__init__.py      registers 54 tools, the safety hook, commands, skill, prompt section
models.py        frozen dataclasses: config, card, errors
config.py        org/project resolution, safety cascade, 0600 profile store
auth.py          PAT (basic) and Azure CLI (bearer), token cache
client.py        all HTTP: the ~54 SDK calls as REST, stdlib only
formatters.py    pure functions: API payloads -> display strings
mocks.py         fixture-backed mock mode
safety.py        safety level for mutation tools (pre_tool_call)
status.py        connection card, label, status text
commands.py      /azure-devops-status, /azure-devops-doctor, prompt templates
tools/           the 54 tools: connection, workitems, boards, repos, pipelines, testplans
fixtures/        offline data for mock mode
prompts/         the 14 prompt templates (shared with the pi extension)
skills/          the bundled skill
```

## Development

```bash
python -m venv .venv
.venv/bin/pip install "pytest>=8,<10" "pyyaml>=6,<7"
.venv/bin/python -m pytest tests
```

The suite runs offline: a fake Azure DevOps HTTP server on localhost exercises
the real client, and the mock-mode block covers all 54 tools. Registration is
checked against `plugin.yaml` with the real Hermes validator:

```bash
hermes plugins validate .
hermes plugins doctor . --ci
```

## Licence

MIT.
