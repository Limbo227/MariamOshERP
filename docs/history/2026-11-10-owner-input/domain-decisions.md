# Domain decisions
Source: brief §§0–17, re-reviewed 2026-11-10. No new owner answers have been received. Design readiness is not business approval.

## [CONFIRMED]
Management ERP, with official accounting in 1C; pilot Mariam-Osh; Russian UI; Django/PostgreSQL; exactly RAW and FINISHED; direct receipts without mandatory orders; stock changes only on confirmed physical events; immutable history; monthly costing and eventual full management profit.

## [ASSUMPTION]
The following are technical proposals, not approved financial or operating policy:

- A-01: modular monolith and explicit transactional posting services; see ADR-0001.
- A-02: company-scoped master data, grants and protected cross-company relationships; no shared holding-wide stock ledger in the pilot.
- A-03: stable internal provenance lots per RAW receipt line, available for inspection before confirmation. Supplier batch numbers can span partial receipts. No assumption of physical lot segregation or valuation method.
- A-04: one authoritative quantity ledger with explicit sources for RAW receipts, synthetic FINISHED receipts and correction lines; protect both receipt creation retries and confirmation retries.
- A-05: preserve kg for mass and package counts/nominal mass together without duplicate movements. Actual weighed packaging mass stays separate pending Q-07.
- A-06: use the state transitions and correction-family reversal design in domain-model.md. Quality results do not automatically release stock or reduce its quantity.
- A-07: record known prices and basic purchase charges during Phase 2; postpone allocation and automated obligations until policy is agreed. Stock-only screens say financial status is not tracked, never imply paid or zero debt.
- A-08: demo receiver can confirm synthetic RAW receipts and see both warehouse names. FINISHED data and changes require separate grants; real assignments remain Q-01.

Optional contracts/shipments and direct receipts are confirmed requirements, not merely assumptions. Their exact schema and states remain proposed.

## [OPEN]
Who confirms receipts and corrections; physical storage and material categories; arrival weighing and authoritative quantity; quality hold/release rules; finished-goods custody handover; mixing and valuation; tolerances; negative-stock policy; obligation recognition; currencies/rounding; backdating and period close.

No numeric tolerances, credit limits, prices, yields, taxes or valuation methods are approved by this design.

## Scope interpretation and unresolved approval
Section 16 requests implementation broadly, while the user's current instruction specifically requests Phase 0. Follow §14 Phase 0 for this delivery; defer scaffolding and executable P0 features to Phases 1–3.
FR-013 makes traceable corrections P0; FR-019 adds the broader inventory-count approval workflow at P1. Provide correction integrity early, full stocktaking later.
FR-014's manual FINISHED receipt is a controlled synthetic test source, never an implied production accounting implementation.
FR-017 classifies payables as P1; no automatic debt recognition until the owner selects the triggering financial fact.
FR-018 combines material receipt and packaging consumption: material receipt is already required in Phase 2 by AT-04; consumption waits for production. FR-022's broader approval workflow is P1, while basic draft/confirmation/correction safety is necessary in the first stock slice.
Section 14 Phase 2 explicitly requires basic purchase-cost recording even though FR-016 is P1; capture the facts in Phase 2 and defer allocation policy, rather than dropping the cost records.
Section 14 lists AT-09 in Phase 2 although its literal conveyor issue belongs to future production. Phase 2 verifies measurement provenance and reconciliation; retain the full production case for Phase 4. Do not claim the literal scenario passed early.
The brief says every phase ends with a browser demonstration and automatic tests. For this documentation-only Phase 0, applying that gate to an executable application is an interpretation, not an owner-approved waiver. The review records document checks only. No application/demo/test completion is claimed. Questions are prepared but not clarified with owner answers; the technical Phase 1 scaffold can proceed without silently resolving them.

## Decision maintenance
Each later written owner answer gets its date, exact wording, affected Q/A/BR identifiers and implementation/test consequences in business-rules.md. Mark assumptions superseded explicitly; do not overwrite the original brief. Business policy is not approved by implementation or a passing synthetic test.
