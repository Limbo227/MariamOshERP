# Handoff — start here before implementing
Current authority: core-scope.md, business-rules.md, domain-decisions.md and the explicit owner follow-ups dated 2026-11-10. Do not implement from history/ or the original brief's phase numbering alone.

## Read in order
1. core-scope.md and business-rules.md.
2. architecture.md and ADR-0001/0002.
3. diagrams/README.md, domain-model.md and data-dictionary.md.
4. procurement-workflows.md, inventory-workflows.md and roles-and-permissions.md.
5. acceptance.md, requirements-coverage.md and open-questions.md.

## Present state
Phase 1 foundation is in this repository. Local PostgreSQL database `ebb_erp` on 127.0.0.1:55432 holds the migrated tables. Django admin at `/admin/` is limited to the technical superuser. Business users sign in through the Russian screens: company workspace, catalogue, the two warehouses and their locations, synthetic opening stock, and balances summed from the ledger. An opening document posts once. A bad line rolls the whole draft back. Posted ledger rows and posted opening documents stay append-only in the database.

Phase 2 (orders, debt, receipts, quality and release) and Phase 3 (production, sack consumption, manual grain and write-offs) are not started. `main.py` remains the original PyCharm sample. Keep this directory as the single repository root. `docs/history/` remains historical evidence.

## Non-negotiable core invariants
Confirmed order creates debt once; actual receipt adds actual stock once; manual payment reduces debt once. One batch can arrive on several days/wagons. Confirmed output consumes one matching sack and adds finished goods atomically. Grain deduction is manual, measured/estimated, with no invented yield. Release is manual. Pending grain use stays visible. Reject negative stock, including historical deficits. Preserve original financial/quantity facts and dependencies through corrections.

## Development habits
Explain stack/schema/service choices and show the relevant diagram before each feature. Update decisions when the owner clarifies policy. Use isolated dependencies and the IDE-configured interpreter; run applicable IDE inspections and real PostgreSQL tests. Never claim financial/account balance correctness from a payment log alone. Never interpret synthetic data or technical defaults as approved factory policy.

## Maintain the docs
business-rules.md is the current business authority; domain-decisions.md holds proposals. Each rule links to owner evidence or source section. diagrams/*.mmd are editable relationship/flow sources; SVG/PNG previews accompany them. Update all formats when relations change. Dictionary identifies fields/constraints; migrations will become the executable schema and must agree with docs.

History is immutable evidence; do not clean it by deleting the owner's wording. Avoid duplicate current document trees. No live 1C/bank, external notifications or production deployment is authorised.

