"""Tests for the catalog index builder. Run with `python -m pytest scripts`."""

from __future__ import annotations

import copy
import json
import os
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
        "steps": [
            {
                "step_id": "read_mailbox",
                "step_kind": "connector",
                "connector_id": "extension.acme.mailbox",
                "connector_install_id": "9204647a-0000-4000-8000-000000000001",
                "override": {"connector": {"extension_id": "acme.mailbox"}},
            },
            {"step_id": "done", "step_kind": "stop_success"},
        ],
        "groups": [],
        "for_each": [],
        "execution_graph": {
            "schema_version": 1,
            "entry": {"kind": "step", "id": "read_mailbox"},
            "edges": [
                {
                    "source": {"kind": "step", "id": "read_mailbox"},
                    "outcome": {"name": "success"},
                    "target": {"kind": "step", "id": "done"},
                    "rework": False,
                }
            ],
        },
    }
    workflow.update(workflow_overrides)
    return {
        "schema_version": "platform.workflow_bundle.v2",
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
                    "sources": ["read_mailbox.connection_binding"],
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


@pytest.mark.parametrize("exported", ["0.7.15", "0.3.0", "", "not-a-version"])
def test_no_template_claims_a_flow_steward_that_cannot_import_v2(exported):
    bundle = _bundle()
    bundle["metadata"] = {"flow_steward_version": exported}
    assert _derive(bundle).item["compatible_flow_steward"] == {
        "min": builder.MIN_FLOW_STEWARD_FOR_BUNDLE,
        "max": "",
    }


def test_the_compatibility_floor_is_the_first_release_after_the_v1_only_ones():
    assert builder.MIN_FLOW_STEWARD_FOR_BUNDLE == "0.7.16"


def test_every_item_names_its_bundle_schema():
    assert _derive(_bundle()).item["bundle_schema"] == "platform.workflow_bundle.v2"


def test_the_install_id_is_never_a_label():
    bundle = _bundle()
    bundle["dependencies"]["extensions"][0]["display_name"] = "acme.mailbox"
    assert _derive(bundle).labels == {}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: b["workflows"].append(copy.deepcopy(b["workflows"][0])), "more than once"),
        (
            lambda b: b["workflows"].append({**copy.deepcopy(b["workflows"][0]), "workflow_id": "stray"}),
            "does not call: stray",
        ),
        (
            lambda b: b["workflows"][0]["steps"].append(
                {"step_id": "call", "step_kind": "invoke_workflow",
                 "override": {"invoke_workflow": {"workflow_id": "missing_child"}}}
            ),
            "export it with child workflows",
        ),
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
    (tmp_path / "categories.json").write_text(json.dumps({key: key.title() for key in sorted(CATEGORIES)}))
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.test"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    return tmp_path


def _commit(repo: Path, rel: str, bundle: dict, *, date: str = "") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(bundle, sort_keys=False))
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    subprocess.run(["git", "commit", "-qm", rel], cwd=repo, check=True, env=env)


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


def _committed_at(repo: Path, path: str) -> str:
    when = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", path], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return builder._iso_utc(when)


def test_an_item_records_when_it_first_appeared_and_when_this_version_did(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle(), date="2026-09-01T10:00:00+02:00")
    _commit(repo, "workflows/email/mailbox_search_1_1_0.yaml", _bundle(version="1.1.0"), date="2026-09-20T09:30:00Z")

    [item] = builder.build_index(repository="acme/catalog")["items"]

    assert item["added_at"] == "2026-09-01T08:00:00Z"
    assert item["updated_at"] == "2026-09-20T09:30:00Z"
    assert item["added_at"] == _committed_at(repo, "workflows/email/mailbox_search.yaml")


def test_the_index_names_every_category_from_categories_json(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())

    index = builder.build_index(repository="a/b")

    assert index["category_labels"] == {"email": "Email", "inventory": "Inventory", "other": "Other"}


def test_a_category_list_without_names_is_refused(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    (repo / "categories.json").write_text(json.dumps(["email"]))

    with pytest.raises(builder.CatalogError, match="map each category id"):
        builder.load_categories()


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


def _child(workflow_id: str = "fetch_messages") -> dict:
    return {
        "workflow_id": workflow_id,
        "version": "1.0.0",
        "display_name": "Fetch the messages a search found",
        "description": "Fetch every message a search returned, with its attachments.",
        "steps": [
            {
                "step_id": "fetch",
                "step_kind": "connector",
                "connector_id": "extension.acme.storage",
                "override": {"connector": {"extension_id": "acme.storage"}},
            }
        ],
    }


def test_a_template_carries_the_child_workflows_its_root_calls():
    bundle = _bundle()
    bundle["metadata"] = {"source_workflow_id": "mailbox_search"}
    bundle["workflows"][0]["steps"].append(
        {"step_id": "call", "step_kind": "invoke_workflow",
         "override": {"invoke_workflow": {"workflow_id": "fetch_messages"}}}
    )
    bundle["workflows"].append(_child())
    bundle["dependencies"]["child_workflows"] = [{"workflow_id": "fetch_messages"}]

    item = _derive(bundle).item

    assert item["item_id"] == "mailbox_search"
    assert item["includes"] == [
        {"item_id": "fetch_messages", "name": "Fetch the messages a search found"}
    ]
    # The child is part of the template: nothing to provide for it.
    assert not [r for r in item["setup_requirements"] if r["kind"] == "workflow"]
    # Its integrations are the template's too.
    assert "acme.storage" in item["integrations"]


def test_a_single_workflow_includes_nothing():
    assert _derive(_bundle()).item["includes"] == []


@pytest.mark.parametrize("schema", ["platform.workflow_bundle.v1", "", None, 2])
def test_an_export_that_is_not_v2_is_refused(schema):
    bundle = _bundle()
    bundle["schema_version"] = schema
    with pytest.raises(builder.CatalogError) as raised:
        _derive(bundle)
    message = str(raised.value)
    assert "accepts platform.workflow_bundle.v2 only" in message
    assert "phase-based v1 export is not accepted" in message


def test_the_v1_refusal_names_the_schema_it_found():
    bundle = _bundle()
    bundle["schema_version"] = "platform.workflow_bundle.v1"
    with pytest.raises(builder.CatalogError, match="schema_version is platform.workflow_bundle.v1"):
        _derive(bundle)


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (lambda w: w.update(phases=[{"phase_id": "start", "steps": []}]), "(phases)"),
        (lambda w: w.update(phase_id="start"), "(phase_id)"),
        (lambda w: w["steps"][0].update(phase_id="start"), "steps.read_mailbox.phase_id"),
        (lambda w: w["groups"].append({"group_id": "g", "phase_id": "start"}), "groups.g.phase_id"),
        (
            lambda w: w["for_each"].append({"for_each_id": "each", "phase_id": "start"}),
            "for_each.each.phase_id",
        ),
    ],
)
def test_a_phase_based_workflow_in_a_v2_file_is_refused(mutate, where):
    bundle = _bundle()
    mutate(bundle["workflows"][0])
    with pytest.raises(builder.CatalogError, match="is phase-based") as raised:
        _derive(bundle)
    assert where in str(raised.value)
    assert "export it again from a current Flow Steward" in str(raised.value)


def _v1_bundle() -> dict:
    bundle = _bundle()
    workflow = bundle["workflows"][0]
    steps = workflow.pop("steps")
    for key in ("groups", "for_each", "execution_graph"):
        workflow.pop(key)
    workflow["phases"] = [{"phase_id": "start", "steps": steps}]
    bundle["schema_version"] = "platform.workflow_bundle.v1"
    return bundle


def test_a_v1_file_is_retired_by_the_pull_request_that_adds_its_v2_export(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _v1_bundle())
    subprocess.run(["git", "branch", "-q", "base"], cwd=repo, check=True)
    (repo / "workflows/email/mailbox_search.yaml").unlink()
    _commit(repo, "workflows/email/mailbox_search_1_1_0.yaml", _bundle(version="1.1.0"))

    assert builder.published_file_changes("base") == []
    assert builder.main(["--check", "--base", "base", "--repository", "a/b"]) == 0


def test_a_v1_file_may_not_be_rewritten_in_place(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _v1_bundle())
    subprocess.run(["git", "branch", "-q", "base"], cwd=repo, check=True)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle(version="1.1.0"))

    assert builder.published_file_changes("base") == ["workflows/email/mailbox_search.yaml"]


def test_a_published_v2_file_may_not_be_removed(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())
    _commit(repo, "workflows/inventory/stock.yaml", _bundle(workflow_id="stock_sync"))
    subprocess.run(["git", "branch", "-q", "base"], cwd=repo, check=True)
    (repo / "workflows/inventory/stock.yaml").unlink()
    subprocess.run(["git", "commit", "-qam", "remove"], cwd=repo, check=True)

    assert builder.published_file_changes("base") == ["workflows/inventory/stock.yaml"]


def test_a_published_v2_file_may_not_be_renamed(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    _commit(repo, "workflows/email/mailbox_search.yaml", _bundle())
    subprocess.run(["git", "branch", "-q", "base"], cwd=repo, check=True)
    subprocess.run(
        ["git", "mv", "workflows/email/mailbox_search.yaml", "workflows/email/renamed.yaml"],
        cwd=repo, check=True,
    )
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=repo, check=True)

    assert builder.published_file_changes("base") == ["workflows/email/mailbox_search.yaml"]


def test_every_published_file_is_a_final_workflow_export():
    categories = builder.load_categories()
    files = builder.workflow_files()
    assert files
    for rel_path in files:
        raw = (builder.ROOT / rel_path).read_bytes()
        entry = builder.derive_entry(rel_path, raw, categories=categories, url=URL)
        assert entry.item["item_id"]
        assert entry.item["bundle_schema"] == builder.BUNDLE_SCHEMA_VERSION
