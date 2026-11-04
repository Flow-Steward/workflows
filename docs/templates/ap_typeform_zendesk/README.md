# Typeform response to private Zendesk ticket

This disabled callable template processes a trusted normalized Typeform submission. It searches for an existing requester, uses the first returned user when present, otherwise supplies the requester's name/email, then creates a private-comment ticket. It is an independently authored Flow Steward implementation of the form-to-ticket pattern illustrated by [this Activepieces template](https://cloud.activepieces.com/api/v1/templates/GXatxWVoQyW8GQMTRHl22); no hosted source export or source program is redistributed here, and no license for that hosted template is asserted.

## Setup

1. Replace `https://configure-zendesk-subdomain.invalid` in both HTTP steps with your reviewed Zendesk HTTPS subdomain.
2. In a dedicated project, create project secrets named `zendesk_username` and `zendesk_api_token`. The username value is the existing Zendesk agent email followed by `/token`; the other secret is an existing internal-use API token. `auth_ref: zendesk_username:zendesk_api_token` refers to the two secret names. Never replace it with literal credentials.
3. Set the dedicated project's `retry_max_attempts` to **0**. The setup confirmation flag does not set this policy. This preserves the source's immediate fallback on requester-lookup errors; the core's default safe-GET retry occurs before the error route.
4. Supply a positive destination `organization_id` and your `expected_form_id`. The event requires `form_id` and ordered answers: index 0 is body text, index 1 requester-name text, index 2 email. Reorder/normalize upstream or adapt and revalidate if your form differs.
5. Use a trusted adapter to verify Typeform signatures/admission and unwrap the raw webhook's `form_response`. This YAML creates no webhook or subscription; callable flags attest setup but are not authentication. API/parent invocation channels only.
6. Review permissions, admission replay policy and uncertain-write handling before enabling. Validate the configured draft and make a controlled live test on your own account.

The token profile is for an existing internal deployment. It is not a managed OAuth integration or a multi-customer authentication service. Zendesk recommends OAuth for broader distribution. No provider login, refresh, live scopes, source subscription or production worker crash recovery was qualified.

## Offline evidence

The production exporter, validators and real target graph are exercised against scripted HTTP transport responses, including lookup fallback, malformed/empty responses, invalid inputs, HTTP failures and private ticket creation. The final artifact's SHA and results are linked from [publication qualification](../../qualification/make-activepieces-three-20261104.md). HTTP authentication construction is checked with synthetic project secrets. No provider request is sent; this is not live-provider verification.
