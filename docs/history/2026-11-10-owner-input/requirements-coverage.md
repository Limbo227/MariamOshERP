# Requirement coverage — Phase 0 design review

Source: original brief §§0–17. Date: 2026-11-10.
Status throughout: **design coverage only**. No requirement below is marked implemented or tested. P0/P1/P2 are priorities; Phase 0/1/2/3/4 are delivery stages.

## All brief sections reviewed

- §0: authority, confirmed choices and unknown policies → business-rules.md / domain-decisions.md.
- §1: duplicate entry problem, management goals and multi-company boundary → architecture.md.
- §2: existing Windows host, unverified backups, 1C and ERPNext isolation → architecture.md.
- §3: wheat/material procurement, bank operator, uncertain production quantities, packing, bran, cashier ticket, dispatch, gate and laboratory → architecture.md and workflow documents. Full production/sales/finance remain deferred.
- §4: two warehouses, units and measurement provenance → domain-model.md / inventory-workflows.md.
- §5: module responsibilities and independent stock/finance effects → architecture.md / domain-model.md.
- §6: entities, lots, attachments, auditing, transactions and currencies → domain-model.md.
- §7: monthly costing and joint-product/WIP constraints → architecture.md / domain-model.md; no costing policy approved.
- §8: separate internal registers with official 1C retained → business-rules.md / procurement-workflows.md.
- §9: Russian role-specific UX, few fields, explicit summaries and errors → architecture.md.
- §10: FR coverage below; no P0 requirement silently removed.
- §11: NFR coverage below; deployment readiness not assumed.
- §12: acceptance scenarios below; partial versus deferred scenarios explicit.
- §13: scoped role/action permissions → roles-and-permissions.md.
- §14: staged scope and Phase 0 evidence → phase-0-review.md.
- §15: 10 stable owner questions with safe interim behaviour → open-questions.md.
- §16: synthetic first vertical slice and explicit exclusions → architecture.md / domain-decisions.md; implementation belongs to Phases 1–3 for the current Phase 0 request.
- §17: required document set exists, source snapshot retained, later written decisions take precedence → README.md / business-rules.md.

## Functional requirements

- FR-001 (P0): login and company/action access → core, roles-and-permissions.md; Phase 1.
- FR-002 (P0): suppliers, products, grades, units, packaging → catalog, domain-model.md; Phase 1 seed, Phase 2 maintenance.
- FR-003 (P0): separate RAW/FINISHED → warehouse uniqueness plus seed/setup checks; Phase 1, balances Phases 2–3.
- FR-004 (P0): direct RAW receipt → procurement-workflows.md; Phase 2.
- FR-005 (P0): multiple lines and conversions → domain-model.md; Phase 2, atomic all-line validation.
- FR-006 (P0): exactly one original movement per line → unique posting source and operation key, architecture.md; Phase 2.
- FR-007 (P0): product/warehouse balance and movements → inventory-workflows.md; RAW Phase 2, FINISHED Phase 3.
- FR-008 (P0): optional contracts and shipment tracking → procurement-workflows.md / domain-model.md; Phase 2.
- FR-009 (P0): direct contract or shipment linkage, partial receipts → explicit header/line links in ERD; Phase 2.
- FR-010 (P0): incoming lot and measurement basis → domain-model.md; Phase 2.
- FR-011 (P0): passport/evidence and minimal inspection → quality/protected attachments, domain-model.md; Phase 2.
- FR-012 (P0): Russian procurement/warehouse UI → architecture.md; Phase 1 shell, Phase 2 forms.
- FR-013 (P0): immutable confirmations and authorised reasoned corrections → domain-model.md; Phase 2, extended to FINISHED in Phase 3.
- FR-014 (P0): controlled synthetic finished receipt with origin → separate FinishedGoodsReceipt source; Phase 3.
- FR-015 (P0): automated integrity/unit/access/retry tests → architecture.md and acceptance list below; setup Phase 1, executable suites with features.
- FR-016 (P1): purchase costs/allocation → basic charge facts in Phase 2 per §14; allocation deferred until method is approved.
- FR-017 (P1): obligations and partial payments → future finance links in domain-model.md; Q-09, §14 Phase 4.
- FR-018 (P1): materials receipt and packaging consumption → receipt already Phase 2 (AT-04); consumption with production Phase 4.
- FR-019 (P1): full stocktaking/approval → future StockCount workflow; distinguish from P0 reasoned corrections.
- FR-020 (P1): actual dispatch/returns/negative-stock policy → future dispatch source, inventory-workflows.md; Q-08 and Phase 4.
- FR-021 (P1): exports → later reporting iteration; same company/warehouse/field permissions as screens.
- FR-022 (P1): drafts/cancellation/exception approval → basic draft/correction safety Phase 2; extended thresholds/approval policy later.
- FR-023 (P2): direct production facts without orders → production Phase 4; preserve lot, unit and measurement provenance now.
- FR-024 (P2): cashier sale/ticket, payment/debt, keeper and gate events → architecture.md; Phase 4.
- FR-025 (P2): cash/bank/debts/expenses/payroll costs → finance Phase 4; no live integrations now.
- FR-026 (P2): costing/full profit/month close → future valuation sources and PRELIMINARY/CLOSED distinction; Phase 4 after policy/data readiness.
- FR-027 (P2): 1C exchange → future external IDs, supported export/API and reconciliation; no .1CD writes.
- FR-028 (P2): holding analytics and other plants → scoped companies and future separate installations/analytics; no copied Mariam-Osh equipment assumptions.

## Nonfunctional requirements

- NFR-01: Russian desktop/tablet UX → role-specific forms in architecture.md; browser acceptance during implementation.
- NFR-02: backend access, including reports → roles-and-permissions.md; test forged IDs and direct URLs.
- NFR-03: atomicity/uniqueness/retries → architecture.md / domain-model.md; PostgreSQL concurrency and rollback tests.
- NFR-04: actor/time/reason/source audit → domain-model.md; verify correction trail.
- NFR-05: Decimal, units/currency → domain-model.md; test incompatible units, conversions and unknown amounts.
- NFR-06: database/file recovery → architecture.md; independent backup/restore rehearsal before production, not provider assurances.
- NFR-07: future import IDs and no duplicate imports → architecture.md; implement/test with approved integration.
- NFR-08: separate environments and synthetic data → architecture.md; configuration checks in Phase 1.
- NFR-09: Git/migrations/incremental checks → Phase 1 repository and repeatable test runner; no Git repo created in Phase 0.
- NFR-10: confidential fields/evidence/secrets → roles-and-permissions.md / architecture.md; restricted downloads and commercial fields.
- NFR-11: readable errors and logs → architecture.md; no confidential payloads in logs, operation IDs for failures.
- NFR-12: retry-safe network recovery → creation and confirmation operation identity; offline editing/sync is not assumed.
- NFR-13: performance → indexed queries/pagination and measured targets; no invented latency guarantee.
- NFR-14: future companies → company-scoped data without a speculative microservice/multi-tenant platform.
- NFR-15: maintainability → module/service ownership, readable tests, decision records and this coverage register.

## Acceptance scenarios and honest completion boundaries

- AT-01: Phase 2 — synthetic 20,000 kg wheat increases RAW exactly once, with source/actor/time/basis.
- AT-02: Phase 2 — sequential/concurrent confirmation and lost-response retries; also test create retries cannot generate a second document.
- AT-03: Phase 2 — contract 100 t, shipments 60/40 t, receipt 59.5 t; original plans preserved, stock 59,500 kg.
- AT-04: Phase 2 — 10,000 empty sacks in pieces, no purchase order.
- AT-05: future finance after Q-09 — debt 2,000,000 minus payment 500,000 = 1,500,000; payment does not duplicate cost/stock. Not simulated as complete in a stock-only build.
- AT-06: Phase 3 — 200 finished 50 kg bags add 10,000 nominal kg only to FINISHED, leaving RAW wheat and sacks unchanged.
- AT-07: Phase 2 — +100 sacks then −10 correction leaves 90, with reason/authority and immutable original.
- AT-08: Phase 2 — real implemented warehouse/correction/evidence/company boundaries. Repeat for actual bank routes when finance exists; absence of those routes is not sufficient proof.
- AT-09: Phase 2 — provenance and signed reconciliation of synthetic estimated stock facts. Literal estimated conveyor-to-production issue remains Phase 4; do not claim the whole scenario complete beforehand.
- AT-10: Phase 3 (RAW reversal safety earlier) — compensating history returns correct balance; add correction-before-reversal and repeated-reversal cases.

Additional planned checks: invalid second line rolls back the whole receipt; concurrent edit versus confirm; pre-confirmation quality evidence with zero stock; conflicting operation-key payload; cross-company supplier/contract/shipment/product; mixed units; changing packaging metadata after posting; document reversal leaves correct effective-date history; no service inventory; unauthorised retries and attachment downloads.

None of these application scenarios has been run. Document validation is recorded separately in phase-0-review.md.
