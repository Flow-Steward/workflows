# Order export protocol with a durable queue

This disabled template adapts the order-export Blueprint from [vinimabreu/make-failsafe](https://github.com/vinimabreu/make-failsafe/tree/1f798ee059a4e4d739c52588b9650b7e12baedb6). It demonstrates source-compatible validation, shipping-method routing, order creation and ops notifications over HTTP. The source author explicitly calls `/orders` and `/ops` **demo sinks**. This template is a protocol example; it does not provide a real 3PL integration or implement the source service's validation and fuzzy-mapping algorithms.

The graph was qualified with Flow Steward core **0.9.9**, commit `21601831d5f816e94f7ba2135585715f96f80316`, and the actual PostgreSQL extension **1.4.0** handler. The observed catalog also contains PostgreSQL 1.4.1; that release was not qualified. Map the dependency to the qualified release or inspect and requalify the installed release before activation.

## Set up before activation

1. Use a dedicated project with `concurrency_cap=1`. Its trusted ingress adapter must preserve the order of received events. Native timer pauses release execution capacity; the SQL journal separately prevents later orders from producing HTTP effects while an earlier order remains unfinished.
2. Provision the companion [queue-schema.sql](https://github.com/Flow-Steward/workflows/blob/main/docs/templates/m5_order_failsafe/queue-schema.sql) in an application-owned PostgreSQL database. It creates `migration_order_failsafe.scope_admission` and `migration_order_failsafe.order_journal`, plus constraints and indexes. Run it once with an authorized schema owner; do not run it against Flow Steward's internal platform tables. The workflow's `execute_write` action does not execute DDL.
3. Select a project-permitted PostgreSQL SQL-writer connection and map the native PostgreSQL extension dependency during import. Restrict database permissions to this application's schema. Connection credentials remain in the connection, outside workflow inputs.
4. Configure an authenticated trusted webhook/API adapter. Import does not create a webhook or subscription. Each received event needs an immutable `delivery_id`; preserve it during recovery. Distinct received replays have distinct IDs. Do not use `order_ref` as a deduplication key. Allow **one active invocation per delivery**. Before starting a fresh recovery invocation, stop and reconcile the previous job.
5. Supply configured `tenant_id` and `project_id` values matching the actual host scope. The graph rejects a mismatch before SQL and obtains SQL scope from immutable host-authored `state.tenant_id` and `state.project_id`. A caller-provided ID alone grants no scope.
6. Replace the literal HTTPS hosts `configure-order-service.invalid`, `configure-order-alert.invalid` and `configure-order-3pl.invalid`. The template currently declares no provider authentication. Review the actual service's request, response, authentication and authorization contracts; configure any required authentication through supported platform facilities and requalify changed bindings. Do not paste credentials into this template.
7. Choose positive delay inputs in milliseconds. The explicit adaptation uses an initial attempt plus **3 validation/mapping retries**, or an initial attempt plus **5 create retries**. Review Make's attempt-count and interval conventions before selecting `900000` milliseconds for the source's validation/mapping interval or `1800000` for its create interval. The fixtures use 100 milliseconds to test timer mechanics, not source timing parity. Choose a practical `poll_wait_ms` for queued orders.
8. Review uncertain writes before approving recovery. A create may have succeeded externally even when the response or subsequent checkpoint was lost. **No exactly-once guarantee** is made across HTTP and PostgreSQL. Approval resets the held stage's retry budget; rejection leaves the order retained and blocks later order effects. Native rework-budget review may add a human gate after repeated polls.
9. Set `setup_confirmed=true` only after completing these steps and keep the workflow disabled until the intended connection, adapter, endpoints and operations have been checked.

The source-compatible order input contains `order_ref`, `customer`, `shipping_address`, `shipping_method` and the complete ordered `lines` array. Safe JSON serialization preserves typed collections and quoted/Unicode strings. Reusing a delivery ID with a different order fails before HTTP and leaves the original payload intact.

## Behavior and recovery

The journal admits each received event under tenant/project scope, claims only the earliest unfinished order, and retains typed payload, stage, service responses and retry count. An invalid order posts the source's scalar `order-invalid` alert; an unmapped shipping method posts its scalar `shipping-method-unmapped` alert. Failures of those alerts are ignored as in the source. A failed create posts `3pl-create-failed` before retry handling; failure of that alert stops before the retry handler and leaves the order retained.

The source mapped predicate is `decision != UNMAPPED`; an unexpected decision with a method follows that route. Source labels mention gap lists and candidates, but the actual alert bodies omit those lists. This template preserves the actual predicates and payloads.

Durable SQL retention, native Wait and native Approval are an explicit business adaptation of Make's Break/DLQ behavior. Scenario-level Make transaction flags and `maxErrors` handling are not claimed identical. The source title says DRAFT although its author reports live Make runs; those runs were not independently reproduced.

## Qualification and limits

Offline qualification uses the actual target graph, HTTP handler, PostgreSQL 1.4.0 handler and SQL parser/compiler, real disposable PostgreSQL, official unmodified MemorySaver, and native timer/approval resume. Only provider HTTP transport and documented host/connection/test boundaries are substituted. Scenarios cover scope rejection before SQL, payload collision, route outcomes, alert failures, retries, exhaustion, approve/reject recovery, retained order blocking and subsequent release. A real fixture database restart followed by a fresh graph checks journal recovery without HTTP effects.

This evidence does not qualify a real 3PL, alert channel, service algorithm, live credentials or project permissions, production worker/broker/checkpointer crash recovery, or exact source-platform semantics. Endpoint or binding changes require their own checks. See the artifact's `qualification.json`, executor receipts and setup report for exact hashes and boundaries.

## Attribution and license

Adapted from `blueprints/order_export_failsafe.json` at source revision `1f798ee059a4e4d739c52588b9650b7e12baedb6`. The original Blueprint and service are by Vinicius Pereira, copyright 2026. The full source MIT notice accompanies this template in `LICENSE.source-MIT.txt`; retain it when distributing this adaptation. The SQL schema and Flow Steward graph assembly are migration companion work, not a copy of the source service implementation.
