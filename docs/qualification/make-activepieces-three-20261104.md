# Three Make and Activepieces pattern adaptations

**86/86 main offline cases passed against the final exported bytes**, plus one actual PostgreSQL restart/fresh-graph case and four queue recovery graph records. These are disabled, unbound callable templates; no live provider API call, OAuth, source subscription or production import was performed. [Exact hashes and scenario assertions](make-activepieces-three-20261104.json).

| Template | Main cases | Required guide |
| --- | --- | --- |
| Typeform response to private Zendesk ticket | 46 | [Internal token profile, input positions and retry policy](../templates/ap_typeform_zendesk/README.md) |
| Trusted charge notification and fulfillment | 20 | [Telegram, Drive MCP, SMTP and trusted event setup](../templates/make_payment_fulfillment_m3/README.md) |
| Order export protocol with a durable queue | 20 | [Mandatory SQL DDL, ownership, ordering and demo service protocol](../templates/m5_order_failsafe/README.md) |

Canonical production exports from core0.9.9 commit21601831d5f816e94f7ba2135585715f96f80316 were executed by the real target graph. Native Telegram1.3.2, SMTP0.3.1 and PostgreSQL1.4.0 handlers were exercised. Provider transports and declared host fixture boundaries were substituted. Safe input rejection, expected failure, paused recovery and successful completion are all asserted scenarios; not every passing test is a completed business run.

The PostgreSQL restart proves durable journal recovery into a fresh graph; it does not prove production worker/broker/checkpointer crash behavior. HTTP and SQL do not share a transaction. The order template is an explicit protocol example requiring source-compatible services; it is not a prebuilt real 3PL integration. The current catalog's PostgreSQL1.4.1 was not qualified.

The payment template replaces the source-branded HTML, links, contacts and subject with an original neutral confirmation. Accepted SMTP message headers, escaping and body are asserted. The Typeform template requires a dedicated project with retry_max_attempts=0 and existing internal Zendesk API-token credentials, not a managed OAuth service. Bindings and real permissions still require setup and a controlled provider test.

Make sources were inspected as real public Blueprint files and the Activepieces pattern as a full configured hosted flow. No original Blueprint/hosted export/source program is redistributed in this submission. Source notices and the distinction between original adaptation and source licensing are in the guides. Popularity metrics were unavailable; these are B2B examples, not a popularity ranking. Seven other campaign workflows remain blocked on exact MCP contracts and are not included.
