# Handoff — start here before implementing
Current authority: core-scope.md, business-rules.md, domain-decisions.md and the explicit owner follow-ups dated 2026-11-10. Do not implement from history/ or the original brief's phase numbering alone.

## Read in order
1. core-scope.md and business-rules.md.
2. architecture.md and ADR-0001/0002.
3. diagrams/README.md, domain-model.md and data-dictionary.md.
4. procurement-workflows.md, inventory-workflows.md and roles-and-permissions.md.
5. acceptance.md, requirements-coverage.md and open-questions.md.

## Present state
Phase 2 supply-to-stock is in this repository. Local PostgreSQL database `ebb_erp` on 127.0.0.1:55432 holds the migrated tables. Django admin at `/admin/` is limited to the technical superuser and does not post business documents. Business users sign in through the Russian screens.

A confirmed order posts the supplier debt once. A receipt posts physical stock once and does not create that debt again. Payments reduce the debt by allocation. Amendments keep the original order lines and post only the debt delta. Customs and other service charges are separate and do not reduce the wheat debt. Receipts and corrections append ledger effects. A correction that would make any historical balance negative is rejected. Passport and local quality values can be compared, and neither one releases grain. Release is a separate manual quantity capped by the received amount. Storage and customs screens do not receive supplier prices. In this local demo, supply records payments as a stand-in for the missing bank operator; that is not factory policy.

Phase 3 (production, one sack per finished bag, manual wheat issue and damaged-sack write-off) is not started. `main.py` remains the original PyCharm sample. Keep this directory as the single repository root. `docs/history/` remains historical evidence.

## Non-negotiable core invariants
Confirmed order creates debt once; actual receipt adds actual stock once; manual payment reduces debt once. One batch can arrive on several days/wagons. Confirmed output consumes one matching sack and adds finished goods atomically. Grain deduction is manual, measured/estimated, with no invented yield. Release is manual. Pending grain use stays visible. Reject negative stock, including historical deficits. Preserve original financial/quantity facts and dependencies through corrections.

## Development habits
Explain stack/schema/service choices and show the relevant diagram before each feature. Update decisions when the owner clarifies policy. Use isolated dependencies and the IDE-configured interpreter; run applicable IDE inspections and real PostgreSQL tests. Never claim financial/account balance correctness from a payment log alone. Never interpret synthetic data or technical defaults as approved factory policy.

## Maintain the docs
business-rules.md is the current business authority; domain-decisions.md holds proposals. Each rule links to owner evidence or source section. diagrams/*.mmd are editable relationship/flow sources; SVG/PNG previews accompany them. Update all formats when relations change. Dictionary identifies fields/constraints; migrations will become the executable schema and must agree with docs.

History is immutable evidence; do not clean it by deleting the owner's wording. Avoid duplicate current document trees. No live 1C/bank, external notifications or production deployment is authorised.

