# ADR-0001: Modular Django application
Date: 2026-11-10. Re-reviewed: 2026-11-10. Status: proposed architecture using the owner's confirmed Django/PostgreSQL choice; no new business approval.

## Decision
Use Django + PostgreSQL, Django Templates, progressive HTMX enhancements and a small Tailwind build. Keep ordinary form submission functional without HTMX. Pin supported dependency versions during Phase 1 after environment verification.

## Reason
The system needs reliable transactions, permissions, relational constraints and simple role-specific forms more than a separate frontend platform. One deployment and one authoritative database reduce duplicated business logic. Django admin supports controlled reference-data maintenance, not unrestricted editing of posted documents.

## Alternatives
A separate SPA introduces extra API and client-state maintenance without a demonstrated initial need. ERPNext/Frappe was explicitly rejected by the owner. Microservices introduce distributed posting risks without a current scale requirement.

## Consequences
Posting logic lives in explicit application services backed by PostgreSQL constraints and transactions. Django alone does not guarantee immutable history or correct business accounting. Concurrency, access boundaries, attachment permissions and corrections require deliberate tests. Future modules remain separate within the monolith.

## Responsibility and accounting risks
core owns identity/company membership/audit/protected evidence; catalog owns products/suppliers/units; procurement owns optional plans, RAW receipts and basic purchase costs; inventory owns quantities, lots, correction sources and synthetic finished receipts; quality owns inspection evidence. See [architecture](../architecture.md) and [ERD](../domain-model.md).

Duplicate document creation can bypass confirmation-only idempotency; protect both. Posting accepted quality quantity instead of physical custody can conceal held stock; keep them distinct. Reversing an original entry without its earlier corrections can create a negative residue. Treating payment as stock cost or receipt confirmation as an unapproved debt trigger can double-count finance. These are design/test obligations, not problems solved automatically by the framework choice.
