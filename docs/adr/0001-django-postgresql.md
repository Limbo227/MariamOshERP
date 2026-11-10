# ADR-0001 — Django/PostgreSQL modular monolith
Date: 2026-11-10. Stack confirmed in original brief; module structure is proposed.

Use Django, PostgreSQL, server-rendered Django Templates, progressive HTMX and shared Tailwind styles. Django owns forms/authentication/services; PostgreSQL owns relational storage and transactional constraints. Pin actual supported versions during Phase 1 setup.

One application/database suits the core connected events and avoids distributed stock/debt transactions. A separate SPA is unnecessary for the first role-specific forms. ERPNext/Frappe remains excluded by the owner.

Module responsibilities are in [architecture](../architecture.md): core, catalog, procurement, inventory, quality, production and settlements. Posting services must atomically validate all effects; framework selection alone cannot guarantee inventory or financial correctness.

Key risks: duplicate creation/confirmation, wrong stock units, double debt, automatic estimated grain use, partial production posting, ignored release holds and negative historical balances. Acceptance scenarios test each. See [core-scope ADR](0002-core-production-scope.md).

