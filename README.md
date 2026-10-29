# Flow Steward workflow catalog

Ready-made workflows for [Flow Steward](https://github.com/Flow-Steward/flow-steward-app).
Flow Steward reads [`index.json`](index.json) and lists these workflows under
**Create workflow → From catalog**, where anyone can search, filter and import them.

`index.json` is generated. Never edit it by hand: a GitHub Action rebuilds it from
the files in `workflows/` after every merge.

## Share a workflow

1. In Flow Steward, open the workflow and give it a readable **name** and a
   **description**. The first sentence of the description becomes the card
   summary, so say what the workflow does, for example
   *"Import supplier stock from email attachments into Shopify."*
2. Export it: **Workflows → ⋯ → Export YAML**. If it calls other workflows, tick
   **Include child workflows**, so they travel in the same file and the template
   installs complete. Do not edit the file.

   From Flow Steward 0.9.4 the export also carries, under `definitions`, the
   agents, skills, data contracts and guardrails the workflow uses, so an import
   on a new installation creates them instead of asking for each one. The agents
   travel without a model: they use the model the importing project configures.
3. Choose one folder from [`categories.json`](categories.json) and add the file as
   `workflows/<category>/<workflow_id>.yaml`. The list is shared with the
   [extension catalog](https://github.com/Flow-Steward/extensions), whose copy is the
   original; a pull request that changes it here alone fails.
4. Open a pull request. The **Validate submission** check tells you what to fix.

The category is your choice; reviewers only check that it is one of the list.

### What the check refuses

- an export that is not `platform.workflow_bundle.v2` (a phase-based v1 export, or a
  workflow that still carries phases: export it again from a current Flow Steward);
- a workflow that calls another workflow which is not in the file (export it with
  child workflows);
- a file carrying a workflow its main workflow does not call (one file is one
  template: a workflow and the child workflows it calls);
- a folder that is not a category;
- a name that is an identifier (`stock_import`) instead of a title, or a
  description shorter than 40 characters;
- a version that is not semantic (`1.0.0`);
- a value under a key such as `password`, `api_key` or `secret`;
- an agent, skill or data contract the workflow uses that the file does not
  define, including a contract a skill's input or output names, or a guardrail
  attached to an agent outside the file (export it again from Flow Steward 0.9.4
  or later). An extension's own agent or skill is fine when the file depends on
  that extension: installing it provides them;
- a change to a file that is already published (removing a phase-based v1 file is
  the one exception, see below).

### Updating a published workflow

Published files never change, because every catalog entry pins its file's exact
bytes. Raise `version` in Flow Steward, export again and add the new file next to
the old one, for example `workflows/email/mailbox_search_1_1_0.yaml`. The catalog
lists the highest version; older files keep working for anyone who pinned them.

A phase-based `platform.workflow_bundle.v1` file is the one file that may go: no
current Flow Steward imports it and the check refuses it, so the pull request that
adds its v2 export under a new name removes it. Its pinned URL keeps serving it.

## What the catalog shows, and where it comes from

| Field | Source |
| --- | --- |
| Name, summary, description | `display_name` and `description` in the export |
| Category | the folder; its name comes from `categories.json` |
| Integrations | the extensions the workflow's steps use |
| Integration names | the extension name recorded in the export |
| Trigger | how the workflow can be started (`manual`, `schedule`, `webhook`, `sub_workflow`) |
| Includes | the child workflows the file carries; they are created with it |
| Requires | project connections, tools and AI models it needs; the agents and skills the file defines are created with it |
| Bundle schema (`bundle_schema`) | `schema_version` of the export; always `platform.workflow_bundle.v2` |
| Compatible Flow Steward | the version the file was exported from, never older than 0.7.16, the first Flow Steward that imports v2 bundles, or 0.9.4 for a file with `definitions`, the first that creates them |
| Added, updated | the commit that added the first version, and the one that added this version |
| Download URL, size, SHA-256 | the file and the commit that last changed it |

## Maintainers

```bash
pip install -r requirements.txt
python -m pytest -q scripts          # builder tests
python scripts/build_index.py --check --base origin/main
python scripts/build_index.py        # writes index.json
```

The **Publish index** workflow commits `index.json` to `main` with the built-in
`GITHUB_TOKEN`. If `main` is protected, allow GitHub Actions to push to it.

Point Flow Steward at the catalog with

```
FS_WORKFLOW_TEMPLATE_CATALOG_URL=https://raw.githubusercontent.com/<owner>/<repo>/main/index.json
```

The format is `workflow_template_catalog/v1`, documented in Flow Steward's
`docs/catalogs/static-catalog-contracts.md`.
