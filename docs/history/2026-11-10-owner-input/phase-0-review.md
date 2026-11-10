# Phase 0 second review

Date: 2026-11-10. Scope: re-read original brief §§0–17 and check every maintained Phase 0 document. This is a documentation review and correction, not an implementation milestone or owner sign-off.

## Result

The first pass captured the central business model correctly but was too terse to serve as a reliable implementation design. It omitted some required relationships and made broad test-coverage/completion statements. The corrected design retains one event entry, independent quantity/debt/payment effects, two warehouses and visible measurement uncertainty.

## Findings corrected

1. **Receipt-to-contract traceability was incomplete.** The ERD only allowed a contract through shipment; line-level plan matching was missing. Added optional direct contract and line links, consistency rules and immutable planned quantities. Sources: FR-008/009, §6.2, AT-03.
2. **Ledger provenance only showed supplier receipts.** That could force synthetic finished output and corrections into the wrong document type. Added FinishedGoodsReceipt, adjustment lines and a constrained posting-source adapter. Sources: FR-013/014, §§6.3, 14 Phase 3.
3. **Draft/lot cardinalities and inspection timing conflicted.** The graph required lines on drafts, allowed several lots per line despite prose saying one, and posting-time lot creation prevented earlier inspection. Corrected draft cardinality and stable pre-confirmation provenance without stock effects. Sources: §§3.9, 6, FR-010/011.
4. **Retry handling stopped at confirmation.** A create-request retry could produce two documents and bypass confirmation uniqueness. Added persistent creation-operation identity, payload conflicts, current-access checks and retry tests. Sources: FR-006, NFR-03/12, AT-02.
5. **Correction/reversal composition was underspecified.** Added a worked +100, −10, reversal example and per-effect unique inverse references so an earlier correction is not applied twice. Source: AT-07/10 and §5.1.
6. **Purchase costs were deferred too broadly.** Section 14 explicitly requires basic purchase-cost capture in Phase 2. Added PurchaseCharge facts there while keeping allocation/payment policy open. Sources: §14 Phase 2 item 6, FR-016.
7. **Unit and evidence details were ambiguous.** Made kg, counted bags and nominal packaging conversion explicit on the same event; retained separate actual-weight observations, price units, measurement times/actors and unknown-money handling. Sources: §§4.3–4.4, 6.5, NFR-05.
8. **Permission details missed parts of the brief.** Added two warehouse names for the demo receiver without unrestricted FINISHED data, explicit commercial/evidence access, and disputed-correction self-approval denial in the demo. Sources: §§13, 16, NFR-02/10.
9. **Acceptance coverage overstated future scenarios.** AT-09's real production issue and AT-08's bank routes need later modules. Marked partial coverage explicitly, preserved their future checks, and mapped every FR/NFR/AT. Sources: §§10–14.
10. **Readiness and document ownership were too absolute.** Questions are prepared but unanswered; the browser/test phase-gate interpretation is not an approved waiver. Clarified one frozen source snapshot, one maintained design tree and the future repository handoff. Sources: §§14–17.

## Phase 0 deliverables against §14

- ADR explaining stack, module responsibility and accounting risks: prepared in [ADR-0001](adr/0001-django-postgresql.md) and [architecture](architecture.md).
- First-iteration ERD including the nine named entities and contract/lot decisions: prepared in [domain model](domain-model.md), with posting/correction/finished sources distinguished.
- 5–10 genuinely blocking questions: ten prepared in [open questions](open-questions.md), grouped by dependent workflow. Owner answers are still pending; clarification is not complete.
- architecture.md and domain-decisions.md separating CONFIRMED/ASSUMPTION/OPEN: prepared and revised.

Technical Phase 1 scaffolding is not blocked by unanswered operational policies. Real receipt/quality/correction behaviour must not treat demo assumptions as approved policy. No full-ERP interview is required before a synthetic prototype.

## Validation scope

Checked source/archive SHA-256 equality, required document existence, local Markdown link targets, fenced-block balance and explicit coverage of FR-001–028, NFR-01–15 and AT-01–10. These checks establish document consistency, not correctness of future code. Mermaid relationships were reviewed as source; no rendered-diagram/browser check is claimed.

Final check results: PASS — 13 required documents present; 26 local links resolve; fences balanced; no replacement-character encoding errors; all 28 FR, 15 NFR and 10 AT entries present; all nine requested ERD entities represented across 36 relationships; required status labels present. Original and archive SHA-256 remain C16F166D640FEB82316CA37B1DF8CE6395725EB55A55AC2FE94533B917A92D15. An initial entity-presence check only examined the left side of relationships and incorrectly flagged QualityInspection; checking both endpoints resolved that check error without changing the diagram.

No application code, schema, migrations, dependencies, live integrations or financial rules were introduced. No Django/PostgreSQL business tests were run. Original brief and pre-existing IDE/environment/sample files were preserved. See [coverage](requirements-coverage.md) for planned implementation checks.
