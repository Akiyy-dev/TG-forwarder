# Text Message Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receive captured text with sender/conversation identity and release the verified implementation.

**Architecture:** Add independently authenticated ingestion routes to the existing Web service. Persist idempotency receipts, normalize text, and enqueue through the existing sender pipeline. Reuse source routing and add a management page.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, Redis Streams, React/TypeScript/Mantine.

**Spec:** docs/superpowers/specs/2026-10-21-api-message-ingest-design.md

## Global Constraints

- Text-only v1; no new runtime dependencies unless unavoidable.
- Independent ingress credentials; source and routing come from the token.
- Idempotency key is (API source, conversation_id, message_id).
- API namespace: -2_000_000_000_000_000 < chat_id <= -1_000_000_000_000_000.
- Preserve sender and conversation metadata through retry, recovery, review and API publication.
- User delegated all approvals and release operations; use independent review and check actual CI/publication results.

## Review Focus

- Simultaneous duplicates and enqueue failures must remain retryable without dropping messages.
- An outbound token, admin JWT or another source's token must not write to a source.
- Missing timestamp on retries must not produce conflicts.
- Same text in independent conversations must remain distinguishable and process independently.
- New API sources must never become Telegram subscriptions or be discarded due to stale sender cache.

### Task 1: Backend ingestion and durable idempotency

**Files:** app/database/models.py; new migrations/versions/0010_api_ingest.py; new app/services/ingest_service.py; new app/api/routes/ingest.py; app/api/app.py; app/source_backends.py; app/messaging/models.py; receiver/source routing integrations; new tests/test_ingest_api.py.

**Interfaces:** Expose management and public routes exactly as specified in the spec. Store sender, conversation_id, conversation_name and external_message_id in normalized raw_metadata. Internal receipt ID is source_message_id.

- [ ] Write/run failing tests for creation, token auth, validation, idempotency/conflict, concurrent retry, queue failure and conversation isolation.
- [ ] Implement models/migration/service/routes and pipeline/source backend changes.
- [ ] Verify targeted tests and static checks; report exact evidence.
- [ ] Independent task review and fixes before final integration.

### Task 2: Management UI

**Files:** new web/src/api/ingest.ts; new web/src/pages/IngestSourcesPage.tsx; web/src/api/types.ts; web/src/App.tsx; web/src/layouts/MainLayout.tsx; web/src/utils/sourceBackend.ts; relevant ChannelsPage source badges.

**Interfaces:** Consume Task 1 management routes. Use source_id for existing route configuration; do not let users supply internal routing in message JSON.

- [ ] Implement usable loading/error/empty states, creation, one-time token display, rotation, toggling/revocation, endpoint/example and source link.
- [ ] Add API backend label and ensure Telegram-only actions are hidden for API sources.
- [ ] Run frontend lint/build and independent task review.

### Task 3: Identity presentation and end-to-end integration

**Files:** app/api/routes/history.py; app/api/routes/reviews.py; app/services/api_delivery_service.py; app/review/publish.py as needed; web/src/pages/HistoryPage.tsx; web/src/pages/ReviewDetailPage.tsx; web/src/api/history.ts; relevant identity interfaces; tests; docs/api.md; README.md; docs/user-guide.md; docs/architecture.md.

**Interfaces:** Read identity from normalized raw_metadata, expose nullable sender/conversation_id/conversation_name/external_message_id fields in history/review/public output; exact history filters.

- [ ] Write failing tests for metadata propagation, filters, review approval and API-only publishing.
- [ ] Implement metadata exposure and identity/filter UI; document HTTP contract, retries, route prerequisites and deployment migrations.
- [ ] Run all CI-equivalent checks and migration verification; fix all failures.
- [ ] Broad independent branch review; resolve material findings.

### Task 4: Merge, release and image verification

- [ ] Commit/push feature branch, open and attach PR; verify CI for exact head.
- [ ] Merge PR; review generated release PR/version/changelog and verify its CI.
- [ ] Merge release PR; verify Release/tag and all enabled image jobs.
- [ ] Verify GHCR version/latest manifest digests and report artifact URLs plus any genuine deployment limitations.
