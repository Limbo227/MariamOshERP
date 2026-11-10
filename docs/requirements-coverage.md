# Requirement coverage after owner scope update
2026-11-10. Original brief remains the full future context; owner answers and scope update govern this core. All items below are design coverage, not implemented/tested claims. See acceptance.md for CORE scenarios.

## Original functional requirements
- FR-001: foundation authentication/company/action scope; CORE-15.
- FR-002: catalogue plus matching sack rules; CORE-07/08.
- FR-003: RAW/FINISHED with real sublocations; CORE-02/07.
- FR-004: direct actual receipt; CORE-02/05.
- FR-005: multiline quantities/units; CORE-08/16.
- FR-006: create and confirmation retries; CORE-01/02/08.
- FR-007: stock/history by location/product; CORE-02/07/16.
- FR-008: PurchaseOrder now represents supply agreement, optional contract evidence, shipment/wagon tracking; CORE-01/02.
- FR-009: optional order-line and wagon links, partial arrivals; CORE-02/03.
- FR-010: incoming provenance and honest measurement basis; CORE-02/09.
- FR-011: optional passport/local values and manual release; CORE-05/06.
- FR-012: Russian role screens; CORE-15 plus browser review.
- FR-013: traceable corrections/no deletion; CORE-10–12.
- FR-014: superseded as the main finished workflow by real production reporting using synthetic test data; CORE-07.
- FR-015: PostgreSQL integrity/access/concurrency suites; CORE-01–16.
- FR-016: core customs/purchase cost facts and payment references; allocation/costing later.
- FR-017: minimal order-based debt, amendments and payment allocation moved into core by explicit confirmation; CORE-01/03/04.
- FR-018: sack receipt and one-per-output consumption now core; CORE-07/08/13.
- FR-019: core reasoned corrections/write-offs; full stocktaking workflows later.
- FR-020: actual sales dispatch/returns later; core negative-stock and dependency rules already required.
- FR-021: core stock/debt/history screens; expanded export catalogue later with same access rules.
- FR-022: core drafts, cancellation and grants; complex multi-level approval thresholds later.
- FR-023: direct production reports and manual grain issues moved into core; CORE-07/09.
- FR-024: sales/tickets/gate workflow later; keep separate from supplier settlements.
- FR-025: minimal supplier payments included; full cash/bank books, customer debts and payroll later.
- FR-026: monthly costing/profit later; preserve source quantities, dates, prices and revisions now.
- FR-027: 1C exchange later, no live integration now.
- FR-028: holding and other-plant workflows later; company isolation now.

## Nonfunctional requirements
- NFR-01: Russian desktop/tablet UI, reviewed in executable phases.
- NFR-02: backend role/company/location/field permissions; CORE-15.
- NFR-03: atomicity/unique effects/serialized balances; CORE-01/02/08/11/16.
- NFR-04: actor/time/reason/source audit; CORE-10/15.
- NFR-05: Decimal, explicit price units and nominal versus actual mass; CORE-03/08/09.
- NFR-06: DB plus attachment backup/restore, before deployment.
- NFR-07: future external-source IDs and import deduplication.
- NFR-08: separate environments and synthetic fixtures.
- NFR-09: one Git root, migrations and incremental tested changes in Phase 1 onward.
- NFR-10: protected prices, documents and secrets; CORE-15.
- NFR-11: readable Russian errors and operation-ID logs without sensitive payloads.
- NFR-12: safe network retries; offline sync separately scoped.
- NFR-13: indexed/paginated lists; measured targets during implementation.
- NFR-14: company ownership without speculative holding infrastructure.
- NFR-15: documented module boundaries, ADRs, dictionary and handoff.

## Original acceptance scenarios
- AT-01: CORE-02 direct weighed wheat.
- AT-02: CORE-01/02/08 retries including duplicate creation.
- AT-03: CORE-02/03 partial delivery and plan preservation.
- AT-04: direct empty-sack receipt, CORE-05/07.
- AT-05: CORE-01/03/04 under confirmed-order debt recognition.
- AT-06: revised: real production adds FINISHED and consumes matching RAW sacks; wheat waits for manual issue. The original isolated fake-output expectation is historical.
- AT-07: CORE-10 reasoned correction.
- AT-08: CORE-15 on actual implemented routes; future bank routes need later checks too.
- AT-09: CORE-09 manual estimated grain issues are now core, with later reconciliation via CORE-10.
- AT-10: CORE-10/12 reversal including prior corrections and dependencies.

## Whole-brief disposition
Sections 0–2: authority/stack/isolation retained. Sections 3–6: owner answers refine logistics, locations, quality and actual production. Sections 7–8: future valuation/accounting preserved; only approved supplier settlement is brought forward. Sections 9–13: UI, permissions and acceptance translated above. Sections 14–17: core-scope.md supersedes old sequencing; history preserves original requirements and answers.

