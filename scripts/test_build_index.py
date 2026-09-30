"""Tests for the catalog index builder. Run with `python -m pytest scripts`."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
import yaml

import build_index as builder

CATEGORIES = {"email", "inventory", "other"}
URL = "https://raw.githubusercontent.com/acme/catalog/0123abcd/workflows/email/x.yaml"


def _bundle(**workflow_overrides) -> dict:
    workflow = {
        "workflow_id": "mailbox_search",
        "version": "1.0.0",
        "display_name": "Search a mailbox for new messages",
        "description": "Search the INBOX for new messages. Use it as the first step of a flow.",
        "trigger": {},
        "settings": {},
        "tags": [],
        "phases": [
            {
                "phase_id": "start",
                "steps": [
                    {
                        "step_id": "read_mailbox",
                        "step_kind": "connector",
                        "connector_id": "extension.acme.mailbox",
                        "connector_install_id": "9204647a-0000-4000-8000-000000000001",
                        "override": {"connector": {"extension_id": "acme.mailbox"}},
                    }
                ],
            }
        ],
    }
    workflow.update(workflow_overrides)
    return {
        "schema_version": "platform.workflow_bundle.v1",
        "kind": "workflow_bundle",
        "metadata": {},
        "workflows": [workflow],
        "dependencies": {
            "agents": [],
            "tools": [],
            "child_workflows": [],
            "extensions": [
                {
                    "install_id": "9204647a-0000-4000-8000-000000000001",
                    "extension_id": "acme.mailbox",
                    "display_name": "Acme Mailbox",
                    "required": True,
                }
            ],
            "project_connections": [
                {
                    "connection_ref": "conn_1",
                    "display_name": "conn_1",
                    "required": True,
                    "sources": ["start.read_mailbox.connection_binding"],
                }
            ],
        },
        "import_hints": {},
    }


def _derive(bundle: dict, path: str = "workflows/email/mailbox_search.yaml"):
    raw = yaml.safe_dump(bundle, sort_keys=False).encode("utf-8")
    return builder.derive_entry(path, raw, categories=CATEGORIES, url=URL)


def test_every_field_is_derived_from_the_export_and_its_folder():
    entry = _derive(_bundle())
    item = entry.item

    assert item["item_id"] == "mailbox_search"
    assert item["categories"] == ["email"]
    assert item["summary"] == "Search the INBOX for new messages."
    assert item["integrations"] == ["acme.mailbox"]
    assert entry.labels == {"acme.mailbox": "Acme Mailbox"}
    assert item["trigger_types"] == ["manual"]
    assert {"kind": "connection", "label": "Acme Mailbox connection", "required": True} in item[
        "setup_requirements"
    ]
    assert item["workflow_yaml_url"] == URL
    assert len(item["workflow_yaml_sha256"]) == 64


def test_a_sub_workflow_is_its_own_trigger_type():
    bundle = _bundle(settings={"callable": {"trigger_channels": ["parent_workflow"]}})
    assert _derive(bundle).item["trigger_types"] == ["sub_workflow"]


def test_schedules_webhooks_and_provider_triggers_become_trigger_types():
    bundle = _bundle()
    bundle["metadata"] = {
        "triggers": [
            {"kind": "schedule"},
            {"kind": "webhook"},
            {"kind": "provider", "provider_key": "acme", "trigger_type_id": "acme.new_mail"},
        ]
    }
    assert _derive(bundle).item["trigger_types"] == ["event", "schedule", "webhook"]


def test_the_exporting_version_is_the_minimum_compatible_version():
    bundle = _bundle()
    bundle["metadata"] = {"flow_steward_version": "1.2.0"}
    assert _derive(bundle).item["compatible_flow_steward"] == {"min": "1.2.0", "max": ""}


def test_an_export_without_a_version_sets_no_compatibility():
    assert "compatible_flow_steward" not in _derive(_bundle()).item


def test_the_install_id_is_never_a_label():
    bundle = _bundle()
    bundle["dependencies"]["extensions"][0]["display_name"] = "acme.mailbox"
    assert _derive(bundle).labels == {}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: b["workflows"].append(copy.deepcopy(b["workflows"][0])), "exactly one workflow"),
        (lambda b: b["workflows"][0].update(display_name="mailbox_search"), "readable title"),
        (lambda b: b["workflows"][0].update(description="Too short."), "at least 40"),
        (lambda b: b["workflows"][0].update(version="1.0"), "semantic"),
        (lambda b: b["workflows"][0].update(workflow_id="Mailbox-Search"), "lowercase"),
        (
            lambda b: b["workflows"][0]["settings"].update(api_key="sk-live-123"),
            "must not carry secrets",
        ),
    ],
)
def test_a_file_that_cannot_be_published_says_why(mutate, message):
    bundle = _bundle()
    mutate(bundle)
    with pytest.raises(builder.CatalogError, match=message):
        _derive(bundle)


def test_an_unknown_category_folder_is_refused_with_the_allowed_list():
    with pytest.raises(builder.CatalogError, match="use one of: email, inventory, other"):
        _derive(_bundle(), path="workflows/shops/mailbox_search.yaml")


# --- the whole index, over a real git repository -------------------------------


def _repo(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "workflows" / "email").mkdir(parents=True)
    (tmp_path / "categories.json").write_text(json.dumps(sorted(CATEGORIES)))
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.test"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    return tmp_path


def _commit(repo: Path, rel: str, bundle: dict) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(bundle, sort_keys=False))
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", rel], cwd=repo, check=True)


def test_the_newest_version_is_listed_and_older_urls_stay_pinned(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())
    _commit(repo, "workflows/email/mailbox_search_1_1_0.yaml", _bundle(version="1.1.0"))

    index = builder.build_index(repository="acme/catalog")

    [item] = index["items"]
    assert item["version"] == "1.1.0"
    sha = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "workflows/email/mailbox_search_1_1_0.yaml"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert item["workflow_yaml_url"] == (
        f"https://raw.githubusercontent.com/acme/catalog/{sha}/workflows/email/mailbox_search_1_1_0.yaml"
    )
    assert index["integration_labels"] == {"acme.mailbox": "Acme Mailbox"}


def test_the_same_files_always_give_the_same_index(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())

    assert builder.render(builder.build_index(repository="a/b")) == builder.render(
        builder.build_index(repository="a/b")
    )


def test_two_files_publishing_the_same_version_are_refused(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/a.yaml", _bundle())
    _commit(repo, "workflows/email/b.yaml", _bundle())

    with pytest.raises(builder.CatalogError, match="bump the version"):
        builder.build_index(repository="a/b")


def test_a_pull_request_may_not_edit_a_published_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())
    subprocess.run(["git", "branch", "-q", "base"], cwd=repo, check=True)
    edited = _bundle(description="Search the INBOX again, differently this time, for the next step.")
    _commit(repo, "workflows/email/mailbox_search.yaml", edited)

    assert builder.published_file_changes("base") == ["workflows/email/mailbox_search.yaml"]
    assert builder.main(["--check", "--base", "base", "--repository", "a/b"]) == 1


def test_adding_a_new_file_passes_the_pull_request_check(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())
    subprocess.run(["git", "branch", "-q", "base"], cwd=repo, check=True)
    _commit(repo, "workflows/inventory/stock.yaml", _bundle(workflow_id="stock_sync"))

    assert builder.published_file_changes("base") == []
    assert builder.main(["--check", "--base", "base", "--repository", "a/b"]) == 0
