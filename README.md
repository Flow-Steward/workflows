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
2. Export it: **Workflows → ⋯ → Export YAML**. Do not edit the file.
3. Choose one folder from [`categories.json`](categories.json) and add the file as
   `workflows/<category>/<workflow_id>.yaml`. The list is shared with the
   [extension catalog](https://github.com/Flow-Steward/extensions), whose copy is the
   original; a pull request that changes it here alone fails.
4. Open a pull request. The **Validate submission** check tells you what to fix.

The category is your choice; reviewers only check that it is one of the list.

### What the check refuses

- a file with more than one workflow (export child workflows as their own files);
- a folder that is not a category;
- a name that is an identifier (`stock_import`) instead of a title, or a
  description shorter than 40 characters;
- a version that is not semantic (`1.0.0`);
- a value under a key such as `password`, `api_key` or `secret`;
- a change to a file that is already published.

### Updating a published workflow

Published files never change, because every catalog entry pins its file's exact
bytes. Raise `version` in Flow Steward, export again and add the new file next to
the old one, for example `workflows/email/mailbox_search_1_1_0.yaml`. The catalog
lists the highest version; older files keep working for anyone who pinned them.

## What the catalog shows, and where it comes from

| Field | Source |
| --- | --- |
| Name, summary, description | `display_name` and `description` in the export |
| Category | the folder; its name comes from `categories.json` |
| Integrations | the extensions the workflow's steps use |
| Integration names | the extension name recorded in the export |
| Trigger | how the workflow can be started (`manual`, `schedule`, `webhook`, `sub_workflow`) |
| Requires | project connections, child workflows, tools and AI models it needs |
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
