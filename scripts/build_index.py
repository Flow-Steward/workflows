#!/usr/bin/env python3
"""Build the Flow Steward workflow catalog index from exported workflow YAML.

Authors add a plain Flow Steward export under ``workflows/<category>/``. Nothing
else is written by hand: every index field is derived from the file itself, its
folder, and git history.

    python scripts/build_index.py                  # write index.json
    python scripts/build_index.py --check          # validate only (pull requests)
    python scripts/build_index.py --check --base origin/main
                                                   # also refuse edits to published files

The output follows ``workflow_template_catalog/v1`` as Flow Steward validates it
(``core/application/workflows/workflow_template_catalog.py``). Unknown fields are
ignored by Flow Steward, so fields added here must stay optional there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = "workflows"
CATEGORIES_FILE = "categories.json"
INDEX_FILE = "index.json"

SCHEMA_VERSION = "workflow_template_catalog/v1"
# The final workflow format: root steps, groups, For each containers and one
# execution_graph per workflow. A phase-based v1 export is refused, as Flow
# Steward refuses to import it.
BUNDLE_SCHEMA_VERSION = "platform.workflow_bundle.v2"
# The first Flow Steward release that imports v2 bundles. Releases up to 0.7.15
# import only phase-based v1 bundles, so no v2 template may claim them, whatever
# version its export names.
MIN_FLOW_STEWARD_FOR_BUNDLE = "0.7.16"
# The first Flow Steward release whose import creates the agents, skills, data
# contracts and guardrails a bundle carries under `definitions`. An older one
# refuses such a file outright, so no template with definitions may claim it.
MIN_FLOW_STEWARD_FOR_DEFINITIONS = "0.9.4"
# Workflow fields of the phase-based format. Flow Steward refuses a v2 bundle that
# still carries any of them, so the catalog refuses it first.
_PHASE_KEYS = ("phases", "phase_id")

# Flow Steward's own ceilings (core/infrastructure/static_catalog/settings.py).
MAX_WORKFLOW_YAML_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 5000
MAX_SUMMARY_CHARS = 160
MAX_LABEL_CHARS = 120

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_ITEM_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_SNAKE_CASE_ONLY = re.compile(r"^[a-z0-9_]+$")

# Channel a workflow can be started from -> the trigger facet value shown in the UI.
_TRIGGER_BY_CHANNEL = {
    "parent_workflow": "sub_workflow",
    "ui": "manual",
    "api": "manual",
    "manual": "manual",
    "schedule": "schedule",
    "cron": "schedule",
    "webhook": "webhook",
}

# Keys whose non-empty value in an export would be a leaked secret. Exports redact
# these already; this is a second line for a public repository.
_SECRET_KEYS = re.compile(r"(password|secret|api[_-]?key|access[_-]?token|private[_-]?key)$", re.I)


class CatalogError(Exception):
    """One or more files cannot be published; the message lists every problem."""


@dataclass(frozen=True)
class Entry:
    path: str
    item: dict[str, Any]
    labels: dict[str, str]


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _last_commit(path: str) -> tuple[str, str]:
    """(sha, ISO time) of the last commit that touched *path*; HEAD when uncommitted."""
    out = _git("log", "-1", "--format=%H %cI", "--", path)
    if not out:
        return _git("rev-parse", "HEAD"), datetime.now(UTC).replace(microsecond=0).isoformat()
    sha, when = out.split(" ", 1)
    return sha, when


def _repository() -> str:
    """owner/name for raw URLs: GITHUB_REPOSITORY in Actions, else the origin remote."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    url = _git("remote", "get-url", "origin")
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise CatalogError(f"cannot derive owner/name from remote '{url}'; set GITHUB_REPOSITORY")
    return match.group(1)


# ---------------------------------------------------------------------------
# derivation from one exported bundle
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return str(value or "").strip()


def _summary(description: str) -> str:
    first = re.split(r"(?<=[.!?])\s+|\n\s*\n", description.strip(), maxsplit=1)[0].strip()
    if len(first) <= MAX_SUMMARY_CHARS:
        return first
    return first[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


def _steps(workflow: dict[str, Any]):
    for step in workflow.get("steps") or []:
        if isinstance(step, dict):
            yield step


def _phase_fields(workflow: dict[str, Any]) -> list[str]:
    """Where a workflow still carries the phase-based format, as `steps.<id>.phase_id`."""
    found = [key for key in _PHASE_KEYS if key in workflow]
    for collection, id_key in (("steps", "step_id"), ("groups", "group_id"), ("for_each", "for_each_id")):
        for index, item in enumerate(workflow.get(collection) or []):
            if not isinstance(item, dict):
                continue
            name = _text(item.get(id_key)) or f"[{index}]"
            found.extend(f"{collection}.{name}.{key}" for key in _PHASE_KEYS if key in item)
    return found


def _step_extension_id(step: dict[str, Any]) -> str:
    connector = ((step.get("override") or {}).get("connector")) or {}
    extension_id = _text(connector.get("extension_id"))
    if extension_id:
        return extension_id
    connector_id = _text(step.get("connector_id"))
    return connector_id.removeprefix("extension.") if connector_id.startswith("extension.") else ""


def _step_child_ref(step: dict[str, Any]) -> str:
    """The workflow an invoke step calls, or ""."""
    invoke = ((step.get("override") or {}).get("invoke_workflow")) or {}
    ref = _text(invoke.get("workflow_id"))
    if ref:
        return ref
    if _text(step.get("step_kind")) == "invoke_workflow":
        return _text(step.get("workflow_id") or step.get("child_workflow_id"))
    return ""


def _child_refs(workflow: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for step in _steps(workflow):
        ref = _step_child_ref(step)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _template_parts(
    bundle: dict[str, Any], workflows: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """(root, children in call order, problems) for a file that is one template.

    The root is the workflow the file was exported for. Every other workflow must be
    one the root calls, directly or through another child; every workflow called must
    be in the file, so the template installs complete.
    """
    by_id = {_text(w.get("workflow_id")): w for w in workflows if _text(w.get("workflow_id"))}
    ids = [_text(w.get("workflow_id")) for w in workflows]
    repeated = sorted({wid for wid in ids if wid and ids.count(wid) > 1})
    declared = _text((bundle.get("metadata") or {}).get("source_workflow_id"))
    called = {ref for w in workflows for ref in _child_refs(w)}
    root_id = declared if declared in by_id else next(
        (wid for wid in by_id if wid not in called), next(iter(by_id), "")
    )
    root = by_id.get(root_id, workflows[0])
    problems: list[str] = [
        f"carries workflow '{wid}' more than once" for wid in repeated
    ]
    order: list[str] = []
    queue = list(_child_refs(root))
    while queue:
        ref = queue.pop(0)
        if ref == root_id or ref in order:
            continue
        if ref not in by_id:
            problems.append(
                f"calls workflow '{ref}', which is not in this file; "
                "export it with child workflows"
            )
            continue
        order.append(ref)
        queue.extend(_child_refs(by_id[ref]))
    strays = sorted(set(by_id) - {root_id} - set(order))
    if strays:
        problems.append(
            f"carries workflows the root does not call: {', '.join(strays)}; "
            "a file is one workflow and the child workflows it calls"
        )
    return root, [by_id[ref] for ref in order], problems


def _definition_ids(definitions: dict[str, Any], section: str, key: str) -> set[str]:
    return {
        _text(row.get(key))
        for row in definitions.get(section) or []
        if isinstance(row, dict) and _text(row.get(key))
    }


def _schema_contract_ids(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [
            ref
            for key, value in node.items()
            for ref in (
                [_text(value)] if key == "contract_id" and _text(value) else _schema_contract_ids(value)
            )
        ]
    if isinstance(node, list):
        return [ref for value in node for ref in _schema_contract_ids(value)]
    return []


def _closure_problems(bundle: dict[str, Any], workflows: list[dict[str, Any]]) -> list[str]:
    """Every agent, skill and data contract the template uses must travel with it.

    A new Flow Steward has none of the author's agents, so a reference without a
    definition stops the import until someone recreates it by hand. An extension's
    own agent or skill is the exception: the file must then depend on an extension,
    and installing it provides them. A skill's I/O counts, not just the dependency
    list: a contract its fields name without the contract's schema is not delivered.
    """
    definitions = bundle.get("definitions") or {}
    if not isinstance(definitions, dict):
        return ["definitions must be an object"]
    dependencies = bundle.get("dependencies") or {}
    agents = _definition_ids(definitions, "agents", "agent_id")
    skills = _definition_ids(definitions, "skills", "skill_id")
    contracts = _definition_ids(definitions, "data_contracts", "contract_id")
    has_extension = any(
        _text((row or {}).get("extension_id")) for row in dependencies.get("extensions") or []
    )
    problems: list[str] = []
    hint = (
        f"export it again from Flow Steward {MIN_FLOW_STEWARD_FOR_DEFINITIONS} or later, "
        "which carries the definitions"
    )

    def require(kind: str, ref: str, defined: set[str], where: str) -> None:
        if not ref or ref in defined:
            return
        if ref.startswith("extension.") and has_extension:
            return
        message = f"{kind} '{ref}' ({where}) has no definition in the file; {hint}"
        if message not in problems:
            problems.append(message)

    for row in dependencies.get("agents") or []:
        require("agent", _text((row or {}).get("agent_id")), agents, "dependencies")
    for workflow in workflows:
        workflow_id = _text(workflow.get("workflow_id"))
        participants = [
            *(workflow.get("participants") or []),
            *((workflow.get("settings") or {}).get("participants") or []),
        ]
        for row in participants:
            require("agent", _text((row or {}).get("agent_id")), agents, f"{workflow_id} participants")
        for step in _steps(workflow):
            require("agent", _text(step.get("agent_id")), agents, f"{workflow_id}.{_text(step.get('step_id'))}")
    for row in dependencies.get("skills") or []:
        require("skill", _text((row or {}).get("skill_id")), skills, "dependencies")
    for agent in definitions.get("agents") or []:
        for binding in (agent or {}).get("skills") or []:
            require("skill", _text((binding or {}).get("skill_id")), skills, f"agent {_text(agent.get('agent_id'))}")
    for skill in definitions.get("skills") or []:
        skill_id = _text((skill or {}).get("skill_id"))
        for key in ("expected_inputs", "expected_outputs"):
            for field in skill.get(key) or []:
                require(
                    "data contract",
                    _text((field or {}).get("contract_id")),
                    contracts,
                    f"skill {skill_id} {key} {_text((field or {}).get('name'))}",
                )
    for contract in definitions.get("data_contracts") or []:
        for ref in _schema_contract_ids((contract or {}).get("schema")):
            require("data contract", ref, contracts, f"contract {_text(contract.get('contract_id'))}")
    for rule in definitions.get("guardrails") or []:
        for agent_id in (rule or {}).get("agents") or []:
            if _text(agent_id) not in agents:
                problems.append(
                    f"guardrail '{_text(rule.get('id'))}' names agent '{_text(agent_id)}', "
                    "which is not in the file"
                )
    return problems


def _triggers(workflow: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    found: list[str] = []
    # Flow Steward records the enabled schedule / webhook / provider triggers here;
    # a provider trigger (a new e-mail, a new order) is an event to the catalog.
    for row in metadata.get("triggers") or []:
        kind = _text((row or {}).get("kind")).lower()
        value = "event" if kind == "provider" else _TRIGGER_BY_CHANNEL.get(kind)
        if value:
            found.append(value)
    trigger = workflow.get("trigger") or {}
    for key in ("type", "kind", "trigger_type"):
        value = _TRIGGER_BY_CHANNEL.get(_text(trigger.get(key)).lower())
        if value:
            found.append(value)
    callable_settings = ((workflow.get("settings") or {}).get("callable")) or {}
    for channel in callable_settings.get("trigger_channels") or []:
        value = _TRIGGER_BY_CHANNEL.get(_text(channel).lower())
        if value:
            found.append(value)
    # Every workflow can be started by hand; a bundle that says nothing is manual.
    return sorted(set(found)) or ["manual"]


def _compatibility(metadata: dict[str, Any], *, has_definitions: bool = False) -> dict[str, Any]:
    """The oldest Flow Steward the file works on.

    That is the release it was exported from, but never one older than the first
    release that imports its bundle schema, or its definitions when it has any.
    """
    version = _text(metadata.get("flow_steward_version"))
    floor = MIN_FLOW_STEWARD_FOR_DEFINITIONS if has_definitions else MIN_FLOW_STEWARD_FOR_BUNDLE
    minimum = version if _SEMVER.match(version) and _semver_key(version) > _semver_key(floor) else floor
    return {"compatible_flow_steward": {"min": minimum, "max": ""}}


def _secret_values(node: Any, path: str = "") -> list[str]:
    leaks: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if _SECRET_KEYS.search(str(key)) and isinstance(value, str) and value.strip():
                if not value.strip().startswith(("${", "secret:", "{{")):
                    leaks.append(here)
            leaks.extend(_secret_values(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            leaks.extend(_secret_values(value, f"{path}[{index}]"))
    return leaks


def derive_entry(
    rel_path: str,
    raw: bytes,
    *,
    categories: set[str],
    url: str,
) -> Entry:
    """Turn one exported YAML file into an index item, or raise listing every problem."""
    problems: list[str] = []
    parts = Path(rel_path).parts
    category = parts[1] if len(parts) == 3 else ""
    if len(parts) != 3 or parts[0] != WORKFLOWS_DIR:
        problems.append("must live at workflows/<category>/<file>.yaml")
    elif category not in categories:
        problems.append(
            f"folder '{category}' is not a category; use one of: {', '.join(sorted(categories))}"
        )
    if len(raw) > MAX_WORKFLOW_YAML_BYTES:
        problems.append(f"is larger than {MAX_WORKFLOW_YAML_BYTES} bytes")

    try:
        bundle = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CatalogError(f"{rel_path}: not valid YAML ({exc})") from exc
    if not isinstance(bundle, dict) or bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        found = _text(bundle.get("schema_version")) if isinstance(bundle, dict) else ""
        raise CatalogError(
            f"{rel_path}: schema_version is {found or 'missing'}, the catalog accepts "
            f"{BUNDLE_SCHEMA_VERSION} only; a phase-based v1 export is not accepted, "
            "export the workflow again from a current Flow Steward"
        )
    workflows = [w for w in bundle.get("workflows") or [] if isinstance(w, dict)]
    if not workflows:
        raise CatalogError(f"{rel_path}: carries no workflow")
    workflow, children, structure_problems = _template_parts(bundle, workflows)
    problems.extend(structure_problems)
    for each in workflows:
        phase_fields = _phase_fields(each)
        if phase_fields:
            problems.append(
                f"workflow '{_text(each.get('workflow_id'))}' is phase-based "
                f"({', '.join(phase_fields)}); export it again from a current Flow Steward"
            )

    item_id = _text(workflow.get("workflow_id"))
    version = _text(workflow.get("version"))
    name = _text(workflow.get("display_name"))
    description = _text(workflow.get("description"))
    if not _ITEM_ID.match(item_id):
        problems.append(f"workflow_id '{item_id}' must be lowercase letters, digits and underscores")
    if not _SEMVER.match(version):
        problems.append(f"version '{version}' must be semantic (for example 1.0.0)")
    if not name or _SNAKE_CASE_ONLY.match(name):
        problems.append("display_name must be a readable title, not an identifier")
    elif len(name) > MAX_LABEL_CHARS:
        problems.append(f"display_name is longer than {MAX_LABEL_CHARS} characters")
    if len(description) < 40:
        problems.append("description must say what the workflow does (at least 40 characters)")
    for leak in _secret_values(bundle):
        problems.append(f"'{leak}' holds a value; exports must not carry secrets")
    problems.extend(_closure_problems(bundle, workflows))
    if problems:
        raise CatalogError("\n".join(f"{rel_path}: {problem}" for problem in problems))

    metadata = bundle.get("metadata") or {}
    dependencies = bundle.get("dependencies") or {}
    integrations: list[str] = []
    labels: dict[str, str] = {}
    requirements: list[dict[str, Any]] = []

    for step in (step for w in [workflow, *children] for step in _steps(w)):
        extension_id = _step_extension_id(step)
        if extension_id and extension_id not in integrations:
            integrations.append(extension_id)
    for row in dependencies.get("extensions") or []:
        extension_id = _text((row or {}).get("extension_id"))
        if not extension_id:
            continue
        if extension_id not in integrations:
            integrations.append(extension_id)
        label = _text(row.get("display_name"))
        if label and label != extension_id and label != _text(row.get("install_id")):
            labels[extension_id] = label[:MAX_LABEL_CHARS]
        requirements.append(
            {
                "kind": "extension",
                "label": labels.get(extension_id, extension_id),
                "ref": extension_id,
                "required": bool(row.get("required", True)),
            }
        )
    # A connection is exported by an id only its author's project knows. Its sources
    # name the steps using it (`<step_id>.<field>`), and a step names its extension,
    # so the requirement can say which account the importer must connect.
    step_extension = {
        _text(step.get("step_id")): _step_extension_id(step) for step in _steps(workflow)
    }
    connection_labels: list[str] = []
    for row in dependencies.get("project_connections") or []:
        extension_ids = {
            step_extension.get(parts[0], "")
            for source in (row or {}).get("sources") or []
            if len(parts := _text(source).split(".")) >= 2
        } - {""}
        names = sorted(labels.get(extension_id, extension_id) for extension_id in extension_ids)
        label = f"{' / '.join(names)} connection" if names else "Project connection"
        if label not in connection_labels:
            connection_labels.append(label)
            requirements.append(
                {"kind": "connection", "label": label, "required": bool(row.get("required", True))}
            )
    included = {_text(child.get("workflow_id")) for child in children}
    for row in dependencies.get("child_workflows") or []:
        child = _text((row or {}).get("workflow_id"))
        # A child the file carries is part of the template, not something to provide.
        if child and child not in included:
            requirements.append(
                {"kind": "workflow", "label": f"Child workflow {child}", "ref": child, "required": True}
            )
    for row in dependencies.get("tools") or []:
        tool = _text((row or {}).get("tool_id"))
        if tool:
            requirements.append(
                {"kind": "tool", "label": _text(row.get("display_name")) or tool, "ref": tool, "required": True}
            )
    if dependencies.get("agents"):
        requirements.append({"kind": "llm", "label": "An AI model provider", "required": True})

    item = {
        "item_id": item_id,
        "version": version,
        "name": name,
        "summary": _summary(description),
        "description": description,
        "categories": [category],
        "tags": sorted({_text(t) for t in workflow.get("tags") or [] if _text(t)}),
        "integrations": integrations,
        "trigger_types": _triggers(workflow, metadata),
        "setup_requirements": requirements,
        # The child workflows this template creates along with itself.
        "includes": [
            {
                "item_id": _text(child.get("workflow_id")),
                "name": _text(child.get("display_name")) or _text(child.get("workflow_id")),
            }
            for child in children
        ],
        # Which bundle format the file is, so Flow Steward can tell a template it
        # imports from one it cannot. Every published file is this one.
        "bundle_schema": BUNDLE_SCHEMA_VERSION,
        **_compatibility(metadata, has_definitions=bool(bundle.get("definitions"))),
        "workflow_yaml_url": url,
        "workflow_yaml_bytes": len(raw),
        "workflow_yaml_sha256": hashlib.sha256(raw).hexdigest(),
        "publication_status": "published",
        "verification_status": "verified",
    }
    return Entry(path=rel_path, item=item, labels=labels)


# ---------------------------------------------------------------------------
# the whole index
# ---------------------------------------------------------------------------


def _semver_key(version: str) -> tuple[int, int, int, int, str]:
    core, _, pre = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    # A release sorts after its pre-releases.
    return (major, minor, patch, 0 if pre else 1, pre)


def load_category_labels() -> dict[str, str]:
    """categories.json: category id -> the name to show. The same file as the extension catalog's."""
    raw = json.loads((ROOT / CATEGORIES_FILE).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in raw.items()
    ):
        raise CatalogError("categories.json must map each category id to the name to show")
    return {key: value.strip() for key, value in raw.items()}


def load_categories() -> set[str]:
    return set(load_category_labels())


def _iso_utc(when: str) -> str:
    return (
        datetime.fromisoformat(when).astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def workflow_files() -> list[str]:
    base = ROOT / WORKFLOWS_DIR
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in base.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )


def build_index(*, repository: str | None = None) -> dict[str, Any]:
    category_labels = load_category_labels()
    categories = set(category_labels)
    repo = repository or _repository()
    problems: list[str] = []
    entries: list[Entry] = []
    newest = ""
    # Published files never change, so a file's last commit is the one that added it.
    added: dict[str, str] = {}
    for rel_path in workflow_files():
        sha, when = _last_commit(rel_path)
        newest = max(newest, when)
        added[rel_path] = _iso_utc(when) if when else ""
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{rel_path}"
        try:
            entries.append(
                derive_entry(rel_path, (ROOT / rel_path).read_bytes(), categories=categories, url=url)
            )
        except CatalogError as exc:
            problems.append(str(exc))

    by_version: dict[tuple[str, str], str] = {}
    latest: dict[str, Entry] = {}
    for entry in entries:
        key = (entry.item["item_id"], entry.item["version"])
        if key in by_version:
            problems.append(
                f"{entry.path}: {key[0]} {key[1]} is already published by {by_version[key]}; "
                "bump the version"
            )
            continue
        by_version[key] = entry.path
        current = latest.get(key[0])
        if current is None or _semver_key(key[1]) > _semver_key(current.item["version"]):
            latest[key[0]] = entry
    if problems:
        raise CatalogError("\n".join(problems))

    chosen = sorted(latest.values(), key=lambda e: (e.item["name"].lower(), e.item["item_id"]))
    if len(chosen) > MAX_ITEMS:
        raise CatalogError(f"the catalog would carry {len(chosen)} items; the ceiling is {MAX_ITEMS}")
    labels: dict[str, str] = {}
    for entry in chosen:
        labels.update(entry.labels)
    first_added: dict[str, str] = {}
    for entry in entries:
        when = added.get(entry.path, "")
        item_id = entry.item["item_id"]
        if when and (item_id not in first_added or when < first_added[item_id]):
            first_added[item_id] = when
    items = [
        {
            **entry.item,
            # When the template first appeared, and when this version did.
            "added_at": first_added.get(entry.item["item_id"], ""),
            "updated_at": added.get(entry.path, ""),
        }
        for entry in chosen
    ]

    # Deterministic: the same files give the same bytes, so publishing commits only on change.
    digest = hashlib.sha256(
        json.dumps([items, labels], sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:8]
    published = newest or datetime.now(UTC).replace(microsecond=0).isoformat()
    published_utc = datetime.fromisoformat(published).astimezone(UTC).replace(microsecond=0)
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_revision": f"{published_utc.date().isoformat()}.{digest}",
        "published_at": published_utc.isoformat().replace("+00:00", "Z"),
        "items": items,
        "integration_labels": dict(sorted(labels.items())),
        "category_labels": category_labels,
    }


def render(index: dict[str, Any]) -> str:
    text = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    if len(text.encode("utf-8")) > MAX_INDEX_BYTES:
        raise CatalogError(f"index.json would exceed {MAX_INDEX_BYTES} bytes")
    return text


def _retired_bundle(revision: str, path: str) -> bool:
    """Whether *path* at *revision* is an export of an older bundle format.

    No current Flow Steward imports such a file and the builder refuses it, so the
    pull request that adds its re-export removes it. Its pinned URL keeps serving it.
    """
    try:
        bundle = yaml.safe_load(_git("show", f"{revision}:{path}"))
    except (subprocess.CalledProcessError, yaml.YAMLError):
        return False
    return isinstance(bundle, dict) and bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION


def published_file_changes(base: str) -> list[str]:
    """Published files a pull request modifies, renames or deletes (all refused).

    The one exception is removing a file of an older bundle format.
    """
    fork = _git("merge-base", base, "HEAD")
    out = _git(
        "diff", "--name-status", "--no-renames", "--diff-filter=MD", f"{fork}..HEAD", "--", WORKFLOWS_DIR
    )
    changed: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        if status == "D" and _retired_bundle(fork, path):
            continue
        changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--base", help="git ref a pull request targets; refuses edits to its files")
    parser.add_argument("--repository", help="owner/name used in raw URLs")
    args = parser.parse_args(argv)
    try:
        if args.base:
            changed = published_file_changes(args.base)
            if changed:
                raise CatalogError(
                    "\n".join(
                        f"{path}: published files are immutable; add a new file with a higher version"
                        for path in changed
                    )
                )
        text = render(build_index(repository=args.repository))
    except CatalogError as exc:
        print(f"Catalog check failed:\n{exc}", file=sys.stderr)
        return 1
    if args.check:
        print(f"Catalog OK: {len(json.loads(text)['items'])} workflows.")
        return 0
    (ROOT / INDEX_FILE).write_text(text, encoding="utf-8")
    print(f"Wrote {INDEX_FILE} with {len(json.loads(text)['items'])} workflows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
