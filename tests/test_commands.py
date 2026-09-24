"""Command registration, prompt-template rendering and the status surfaces."""

from __future__ import annotations

from conftest import sub

commands = sub("commands")
status = sub("status")
models = sub("models")


# ---------------------------------------------------------------------------
# Template rendering (pi's prompt-template syntax)
# ---------------------------------------------------------------------------


def test_frontmatter_is_split_from_the_body():
    meta, body = commands.parse_template(
        "---\ndescription: Do a thing\nargument-hint: \"<id>\"\n---\n\nBody text\n"
    )
    assert meta["description"] == "Do a thing"
    assert meta["argument-hint"] == "<id>"
    assert body.strip() == "Body text"


def test_missing_frontmatter_is_tolerated():
    meta, body = commands.parse_template("Just a prompt with no frontmatter")
    assert meta == {}
    assert body == "Just a prompt with no frontmatter"


def test_positional_arguments_are_substituted():
    rendered = commands.render_template("Review PR $1 in repo $2", ["42", "repo-webapp"])
    assert rendered == "Review PR 42 in repo repo-webapp"


def test_optional_block_kept_only_when_the_argument_is_given():
    template = 'Run azure_devops_get_pull_request with pullRequestId: $1$2{ and repositoryId: "$2"}'
    assert commands.render_template(template, ["42", "repo-webapp"]) == (
        'Run azure_devops_get_pull_request with pullRequestId: 42 and repositoryId: "repo-webapp"'
    )
    assert commands.render_template(template, ["42"]) == (
        "Run azure_devops_get_pull_request with pullRequestId: 42"
    )


def test_mustache_conditional_and_variables():
    template = "{{#if org}}Use **{{org}}**{{else}}Use every org{{/if}} and {{project}}"
    assert commands.render_template(template, [], {"org": "neoimpulse", "project": "SCODA"}) == (
        "Use **neoimpulse** and SCODA"
    )
    assert commands.render_template(template, [], {"project": "SCODA"}) == (
        "Use every org and SCODA"
    )


def test_the_doctor_template_renders_with_and_without_arguments():
    meta, body = commands.parse_template(
        (commands.PROMPTS_DIR / "azure-devops-doctor.md").read_text(encoding="utf-8")
    )
    without = commands.render_template(body, [])
    assert "Validate all configured organizations" in without
    assert "{{" not in without

    with_org = commands.render_template(body, [], {"org": "neoimpulse", "project": "SCODA"})
    assert "neoimpulse" in with_org
    assert "SCODA" in with_org
    assert "{{" not in with_org


def test_every_prompt_file_loads_and_renders_cleanly():
    templates = commands.load_templates()
    assert len(templates) == 14
    for name, description, _hint, body in templates:
        rendered = commands.render_template(body, ["42", "repo-webapp", "extra"])
        assert rendered.strip(), f"{name} rendered empty"
        assert "{{" not in rendered, f"{name} left a mustache tag"
        for index in ("$1", "$2", "$3"):
            assert index not in rendered, f"{name} left {index} unsubstituted"


# ---------------------------------------------------------------------------
# Status surfaces
# ---------------------------------------------------------------------------


def test_label_and_status_when_not_configured():
    assert status.connection_label(None) == "Azure DevOps · not configured"
    text = status.status_text(None, "/tmp/azure-devops-config.json")
    assert "No configuration found" in text
    assert "/tmp/azure-devops-config.json" in text


def test_label_and_status_from_a_resolved_config(configure):
    configure()
    config = sub("config").resolve_config()
    card = status.build_card(config)

    assert card.org == "testorg"
    assert card.project == "TestProject"
    assert status.connection_label(card) == "✓ Azure DevOps · testorg/TestProject · @Engineering"

    text = status.status_text(card)
    assert "**Org:** testorg" in text
    assert "**Team:** Engineering" in text
    assert "**Safety:** confirm" in text
    assert "live API" in text


def test_label_omits_the_team_when_there_is_none(configure):
    configure(team="")
    card = status.build_card(sub("config").resolve_config())
    assert status.connection_label(card) == "✓ Azure DevOps · testorg/TestProject"


def test_card_reports_mock_mode(configure):
    configure(extra={"mock": True})
    card = status.build_card(sub("config").resolve_config())
    assert card.mock is True
    assert "mock (offline fixtures)" in status.status_text(card)


def test_status_command_answers_without_a_model_turn(configure):
    configure()
    handler = commands.make_status_command(ctx=None)
    text = handler("")
    assert "Azure DevOps Connection" in text
    assert "testorg" in text


def test_status_command_when_unconfigured(isolated_config):
    sub("config").load_config()
    handler = commands.make_status_command(ctx=None)
    text = handler("")
    assert "No configuration found" in text


def test_explicit_config_path_resolves_into_the_card(configure):
    configure()
    card = status.build_card(sub("config").resolve_config())
    assert card.org_url.startswith("http://127.0.0.1:")
