# Trusted charge notification and fulfillment

This disabled callable template notifies Telegram about every accepted charge, then independently creates a Drive folder and sends an SMTP email only for case-sensitive `status == "succeeded"`. Route order is Telegram, Drive, SMTP. A failure stops later effects; earlier effects are not rolled back. The charge amount remains in raw source minor units.

## Setup

1. Install/bind the qualified native Telegram `1.3.2` and Outgoing Email/SMTP `0.3.1` operations, or inspect and requalify the selected release. Select a permitted Telegram connection/internal channel and an SMTP connection with an approved sender.
2. Map the template-local Drive tool dependency to an authorized Google Drive MCP `create_file` action. It is a portable dependency, not an installed connector ID. The selected documented folder arguments are `title`, `parentId`, `contentMimeType: application/vnd.google-apps.folder` and `disableConversionToGoogleType: true`; see the [official reference](https://developers.google.com/workspace/drive/api/reference/mcp/tools_list/create_file). Configure OAuth/refresh/scopes and the parent folder separately. The workflow does not share the folder.
3. Supply a verified Make-shaped `event.object` charge, connection references and parent-folder ID through the callable inputs. Raw Stripe webhook `data.object` must first be normalized by your trusted adapter. Set the confirmation flags only after that adapter verifies the event's origin and permissions. The flags do not verify a signature.
4. Configure replay/ownership policy outside this template before using payment events. This YAML installs no Stripe subscription, replay ledger or managed Stripe login.
5. Review the neutral email body and subject, validate your configured draft and run a controlled provider test before enabling. The publication profile replaces the source's company-branded welcome letter, links and contacts with an original generic confirmation; customer-name HTML escaping is preserved.

No automatic write retries, compensation, exactly-once guarantee, IMAP Sent-folder copy or live OAuth/provider qualification is included. If an external effect may have succeeded before an error, reconcile it before retrying the whole workflow.

## Source attribution and adaptation

The route pattern was inspected in [this pinned public Make Blueprint](https://github.com/tommyevening/makemcp/blob/87594f96a769322ea79f0404b3e8f01c41957a52/data/corpus/elyf-stripe-telegram-gdrive.json). The repository carries the [MIT notice retained here](NOTICE.txt). Its inherited corpus chain was not independently established. No original Blueprint, company HTML, images, source account IDs or source links are redistributed in the catalog YAML. This is an independently authored Flow Steward adaptation, not an endorsement by the source author or an exact Make engine implementation.

## Offline evidence

Real native Telegram/SMTP handlers and the target MCP client/normalization execute with substituted provider transports. Standard synthetic MCP result envelopes are explicit fixtures; the selected live Drive server's result envelope was not observed and is not consumed downstream. Final exported-byte hashes and scenario assertions are linked from [publication qualification](../../qualification/make-activepieces-three-20261104.md). No provider API is called.
