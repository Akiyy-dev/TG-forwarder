# Text message ingestion API

## Authorization and outcome

The user approved the HTTP/JSON ingestion design, selected text-only v1, requested sender identity to distinguish conversations, and explicitly delegated remaining design approvals, implementation, builds, push, merge, release and image publication to the agent. No further human design gate is required for this scope. Images and attachments remain future work.

External capture software can submit text to the existing rule/review/publish pipeline. Each administrator-created API source owns an independent ingress token. It uses the existing source/target configuration and publish modes. Token identity determines the source; request bodies cannot override routing. Existing outbound pull tokens grant no ingress permission.

## HTTP contract

`POST /api/ingest/v1/messages`, `Authorization: Bearer <token>`, JSON only.

```json
{
  "message_id": "capture-000001",
  "conversation_id": "group-001",
  "conversation_name": "Project group",
  "sender": "Alice",
  "text": "Captured message",
  "timestamp": "2026-10-21T01:30:00+08:00"
}
```

`message_id`: required nonblank string up to 128 characters. `text`: required nonblank string up to 65,536 characters. `conversation_id`: nonblank string up to 128 characters, default `default`; callers capturing multiple conversations must supply stable distinct IDs. `conversation_name` and `sender`: optional strings up to 256 characters. `timestamp`: optional timezone-aware ISO 8601 time, omitted means server receipt time. Reject unknown fields, attachments, naive timestamps, empty/oversize text. Preserve original text and structured sender/conversation metadata; do not implicitly prepend identity to message text.

The idempotency key is (API source, conversation_id, message_id). Same key and canonical submitted content returns the original receipt with `duplicate=true`; changed text, sender, conversation name or supplied timestamp returns 409. Missing timestamp remains semantically missing for fingerprinting, so retries do not conflict because server time changed. Distinct conversations may reuse the same external message ID.

Return the project's `Envelope` with receipt ID, source ID, message ID, conversation ID, accepted/queued status and duplicate flag. New messages return 202 only after enqueue succeeds (or the local in-process queue accepts them). Redis/unavailable delivery returns 503 and must permit safe retry with the same key. Persist ingress receipt plus normalized payload before enqueue; retry unsent receipts and safely redeliver queued receipts if acknowledgment was ambiguous. Existing message registration provides final downstream idempotency. No assertion of exactly-once external Bot side effects.

Auth failures are 401; disabled/expired ingress credentials or disabled sources are denied. Admin operations require super_admin; list/read may use viewer. Secrets appear only on creation and rotation; store SHA-256 and a display prefix. Never expose raw tokens in list responses or logs. Keep ingress token generation distinct from outbound tokens. Delete/revoke an ingress registration without deleting its source/history.

## Storage and processing

Add ingress-source credentials linked one-to-one to SourceChannel and ingress receipts with a database unique constraint on the idempotency tuple. A receipt's integer primary key supplies a collision-free internal source_message_id. Normalize into NormalizedMessage and use RedisStreamBus.publish_incoming("api", ...) in split-process mode, MessageService.enqueue in local mode. Persist JSON payload and stable fingerprint; handle simultaneous inserts via database constraints. Serialize duplicate delivery attempts sufficiently to avoid content mutation and parallel processing surprises.

Add an API source namespace `-2_000_000_000_000_000 < chat_id <= -1_000_000_000_000_000`, disjoint from Telegram and existing SafeW IDs. Generate cryptographically random 48-bit offsets from the API base. Extend source backend types and labels to `api`, and exclude API sources from Telegram subscription/access checks. Sender should refresh configured sources for API events as necessary so a newly created source is never silently discarded due to stale cache.

API source creation defaults to enabled, publish_mode=review. Configure routes through the existing channel UI. Missing targets retain the existing visible routing failure behavior; document configuring targets before sending and how to retry failures. Sender/conversation metadata must survive normalized serialization, processing recovery, history, review detail and outbound pull delivery, including manual approval. Content deduplication must not merge independent API messages from different conversations/senders merely because their text matches; transport idempotency is enforced by receipts.

## Management contract and UI

`GET /api/v1/ingest-sources` returns `{items: [...]}`. Each item contains id, name, source_id, source_chat_id, token_prefix, enabled, expires_at, last_access_at, created_at. `POST /api/v1/ingest-sources` accepts `{name, enabled?, expires_at?}` and returns item plus token. `PATCH /api/v1/ingest-sources/{id}` accepts name/enabled/expires_at. `POST /api/v1/ingest-sources/{id}/rotate-token` returns item plus token. `DELETE /api/v1/ingest-sources/{id}` revokes credentials while retaining source/history. No user-supplied token is needed in v1.

Add a Chinese `消息接入` navigation/page with token creation/rotation, enable toggle, revocation, source-routing link, endpoint URL and copyable JSON example. One-time token dialog explains that the secret cannot be retrieved later. Display API source labels and sender/conversation in message history and review details. History API supports exact `sender` and `conversation_id` filters. Existing API responses may gain nullable identity fields without breaking old clients.

## Verification and delivery

Tests cover ingress create/auth/RBAC, token separation, expiry/disable/rotation/revocation, validation, retry/ambiguous enqueue failure, same key conflict, concurrent duplicate requests, cross-source/cross-conversation isolation, sender preservation, API-only publish and review approval, metadata through recovery, sender/history filters and receiver exclusion. Migrate a fresh SQLite database through every revision and check migration downgrade/upgrade. Run Ruff lint/format, mypy, full pytest, frontend lint/build. Independent review must resolve correctness/security findings before merge.

Push a dev/ branch, open and attach a PR, verify CI, merge using the tested head SHA. Review/merge the release-please PR, then verify the GitHub Release and application GHCR version/latest tags and digest. SafeW image follows the existing conditional workflow and configured package availability. Do not alter secrets or invent release success when build or publication is unavailable.
