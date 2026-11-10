# Phase 0 — final core design review
Date: 2026-11-10. Status: **core design package complete; implementation not started**.

## Authority and scope
Processed all ten annotated owner answers and all business-rule comments. Preserved their exact text before updating the working documents. Two follow-ups were answered explicitly: confirmed supply order starts debt; an authorised person decides quality release manually.
The current core is supply order → partial transport/receipt → quality comparison/manual release → packaged production → finished goods, with automatic matching-sack consumption, separate manual grain issues and minimal supplier settlements. Full sales, treasury and costing remain later.

## What changed after owner input
- Recognised RAW sublocations A/B and packaging storage while keeping two main warehouses.
- Added supplier batch/wagon/partial-arrival relationships and variable customs port/cost evidence.
- Replaced vague future financial policy with confirmed-order debt, dated amendments and payment allocation.
- Added optional supplier/local quality values and manual release.
- Replaced the isolated synthetic finished-receipt placeholder with the real production-report workflow, tested using synthetic data.
- Added one matching sack per output bag, manual wheat issues, damaged-sack write-offs and dependency-aware corrections.
- Explained BR-04, BR-06, BR-08 and BR-12 in plain examples; retained proposals separately from owner-confirmed facts.
- Documented shipment-derived by-product figures as estimates excluded from reliable stock.
- Chose one repository root here and added a reading order, table dictionary, reusable diagram sources and a developer/AI handoff.

## Visuals and design coverage
Three PNG previews and three SVG versions show business flow, procurement tables and production/stock tables. Five Mermaid sources cover workflow plus supply, quality, manufacturing and settlements; four relationship sources also appear in domain-model.md. layout.json records overview geometry/text for reuse. PNGs were opened and visually inspected for readable labels, connections and clipping.
The diagrams are designed views, not a reverse-engineered live database.

All 28 original FR, 15 NFR and 10 AT identifiers have current disposition in requirements-coverage.md. Sixteen CORE acceptance scenarios cover the narrowed end-to-end implementation, including concurrency, partial receipts, financial amendments, release, packaging and historical negative balances.

## Verification performed
- Original brief and archived brief retain SHA-256 C16F166D640FEB82316CA37B1DF8CE6395725EB55A55AC2FE94533B917A92D15.
- Owner annotated questions snapshot retains SHA-256 44AE09C7B493E1A9296B4B04E605F77C4DCB71E5513918F8D4514CC4A8CA2E49.
- Owner annotated rules snapshot retains SHA-256 6329274D64F0260EBB9210E7990678D7B810922B1E7128990425C2B2561F188E.
- Active-document local links, encoding and fenced blocks checked; four embedded/source Mermaid diagrams match; three SVGs parse and all 27 overview cards fit their canvases.
- Synthetic arithmetic checked: 3,000 + 3,000 + 4,000 = 10,000 kg; 100 × 50 = 5,000 nominal kg; 200,000 − 4,000 − 50,000 = 146,000 KGS due.

These are document/diagram checks, not application tests. No Python/Django implementation, migrations, business test execution, live data, bank calls or browser application demonstration occurred. No inspectable application source was changed.

## Next step
Build Phase 1 as described in [core scope](core-scope.md), then Phase 2 supply/stock and Phase 3 manufacturing. [Remaining details](open-questions.md) are bounded catalogue, staff and operating settings with explicit synthetic defaults. Consult them when implementing the dependent feature; do not reopen already confirmed decisions.

The original brief's executable browser/test gate remains required for application phases; Phase 0 is a design deliverable. Its completion does not claim a working ERP or production readiness.

