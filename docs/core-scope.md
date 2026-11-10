# Core scope and delivery plan
Authority: owner scope update and answers on 2026-11-10, including the two explicit follow-up confirmations.

## What the first usable core does
1. Create and confirm a supply order with supplier, product lines, agreed quantities/prices/currency. Confirmation creates supplier debt once.
2. Track its delivery batches, customs/port, wagons or other transport units, optional documents and expenses. One batch can arrive in several receipts.
3. Receive actual weighed wheat into RAW / Storage A or B; receive empty sacks/materials into RAW / Packaging & materials. Preserve planned versus received quantities.
4. Record supplier passport values and local laboratory values per wagon; compare them, flag discrepancies and record an authorised manual release.
5. Enter actual production as packaged finished products: date/shift, SKU and bag count. Confirmation adds finished goods immediately and consumes one matching empty sack per finished bag.
6. Enter wheat consumption manually by class/product and storage location, with measurement basis and optional production link. No invented wheat-to-flour conversion.
7. View stocks, operations, supplier debt and recorded partial payments. Record amendments, corrections and cancellations with history and negative-stock protection.

No mandatory production order or separate flour-produced/packaging form. One production confirmation posts all output and sack effects together. A production report can show wheat consumption still pending rather than pretending to know it.

## Explicit boundaries
Production output and manual wheat issues move into the first core, superseding the original Phase 4 deferral. Basic supplier debt/payment records also move into the core because the owner confirmed their trigger. This is a scoped extension of the first iteration, not the whole future ERP.

Later: full sales/tickets/dispatch, bank and cash account books, online banking, payroll, automatic grain recipes/yields, exact mixed-lot depletion, full costing/profit, 1C integration and holding analytics. Customs expense facts and how they were paid can be recorded without implementing treasury.

By-products: preserve today's sales-derived estimate as an explicitly estimated observation. Without dispatch and opening/closing physical counts it is not a verified production or available-stock figure. Do not automatically add it to FINISHED or duplicate stock when sales arrives later.

## Build sequence
- **Phase 1 — foundation:** repository, isolated Django/PostgreSQL, authentication/grants, Russian layout; company, RAW/FINISHED and their locations; products/SKUs and packaging mapping; synthetic opening-stock source; migrations/test runner.
- **Phase 2 — supply to stock:** orders and revisions, minimal payable/payment allocation, batches/wagons/customs, actual receipts, quality comparison/manual release, stock history and corrections.
- **Phase 3 — production to finished goods:** real production-report workflow on synthetic data, automatic sack consumption, manual grain issues, damaged-sack write-offs and finished stock reports. No separate keeper handover.
- **Core acceptance:** demonstrate the scenarios in acceptance.md against PostgreSQL and in the Russian browser UI. Only then expand.

All tests use synthetic data. No real bank/1C connection or production deployment is authorised. Phase 0 completion means the documented design and business decisions needed for this core are available; application acceptance is a later gate.
