# Architecture — Phase 0
Source: brief §§0–17. Reviewed again on 2026-11-10. Status: design prepared, with unanswered owner questions; no implementation or business approval claimed. See [review](phase-0-review.md) and [requirements coverage](requirements-coverage.md).

## Business understanding [CONFIRMED]
The operational problem is repeated transcription between workers, paper journals, cashiers and 1C. A simple Russian interface must capture the event where it occurs. Official accounting remains in 1C. The pilot is Mariam-Osh; other plants have different measuring equipment and cannot inherit assumed operating rules.

RAW holds wheat, empty packaging and agreed materials. FINISHED holds packaged flour SKUs and measurable finished by-products. Intermediate flour and grain in the mill are possible WIP, not an invented third warehouse. Warehouse identity, measurement certainty and quality availability are separate concepts.

Wheat contracts and shipments describe expectations over a 2–3 week journey. Receipts describe arrivals; neither contracts nor dispatch-to-factory statuses increase inventory. Payments and obligations are independent financial events. Ordinary purchases can be received directly.

Production, sales tickets, actual dispatch, gate weights and payments will later become separate linked events. Bran production is not reliably measured today. Monthly costing must account for joint products, WIP, losses, accrued costs and closing inventories before reporting full management profit.

## Modules [ASSUMPTION]
A modular Django monolith with PostgreSQL and server-rendered templates:
- core: company membership, authentication, audit events and protected attachments.
- catalog: suppliers, products, units, grades and packaging specifications.
- procurement: optional contracts and lines, inbound shipments and lines, RAW receipts and lines, and basic purchase-charge records in Phase 2. Allocation policy is separate and unresolved.
- inventory: two warehouse types, provenance lots, immutable quantity ledger, balance queries, correction documents and Phase 3 synthetic finished-goods receipts.
- quality: lot inspections, evidence and explicitly separate quality state.
Future production, sales, gate, finance and costing modules consume linked business events. They must not reproduce stock movements already posted by inventory.

Use Django Groups plus company/warehouse grants. Application services own posting; views, admin and future imports all call the same services. No financial posting through model signals. See ADR-0001 and domain-model.md.

Dependency direction: core → catalog → inventory primitives (warehouses, lots, ledger); procurement uses those primitives through its posting service. Quality records evidence against lots. The inventory-owned posting-source adapter has explicit protected links to supported source-line models, added in ordered migrations; it is not a second receipt workflow. It avoids an unconstrained text source ID. Finished receipts and corrections use the same ledger service. Views never construct ledger rows directly.

## Posting boundary [ASSUMPTION]
Protect both document creation and confirmation. A form receives a persistent operation key; the server uniquely scopes it by company and operation, associates it with the creator and a payload fingerprint, and binds it to the resulting document. A retry with the same key/payload returns the same authorised result; a different payload is a conflict, not a second receipt. Independent business events use new keys. These keys cannot detect every manually re-entered duplicate, so supplier/document references also support duplicate warnings without inventing a globally unique supplier-document rule.

Within one database transaction: recheck backend permissions and company consistency; lock the receipt and validate its version and all draft lines; resolve existing provenance lots; create one source and ledger entry per line; record confirmation and audit. A unique source-line link and a unique ledger source prevent duplicates. Repeated confirmation returns the original result only after checking current access. Concurrent edits and confirmation serialize on the same parent lock. Any failure rolls back the entire document, movements and confirmation audit. Retrying after a lost response must preserve the operation key.

Lots can exist while a receipt is a draft so the laboratory can inspect before stock confirmation. Creating a lot or recording an inspection does not create stock. Lot identity remains stable; changing an inspected draft line's product/provenance requires explicit replacement and retention of the superseded evidence.

Confirmed document quantities and ledger rows cannot be edited or deleted through UI, admin or imports. Audited status transitions remain possible. Enforce ledger immutability with database guards and a restricted runtime role; migration/maintenance credentials are separate. Confirmed lines also need database guards, because view-level restrictions do not protect bulk updates. Corrections have their own document, reason, actor and source entries. Reversal must not erase the original or reverse an already corrected quantity twice; the correction rules are in [domain model](domain-model.md).

Balances are sums of signed posted movements by company, warehouse, product and unit, optionally lot. Cached balances must be rebuildable. Reports include effective date and recorded timestamp; quality and measurement uncertainty remain visible. Never sum unlike units.

## UI proposal [ASSUMPTION]
Russian role-specific landing pages. Receipt: supplier, effective date, multiple product rows, quantity/unit, measurement basis and evidence; shipment optional. Preview the result before confirmation, then show receipt number and history. Show physical stock separately from any approved usable-stock calculation. Provide tablet-friendly controls and plain Russian errors. No mandatory orders or accounting terminology.

Use «Принять сырьё», «Посмотреть остатки», «Новая поставка пшеницы» and «Поставки в пути». Phase 3 adds «Принять готовую продукцию» for authorised demo users with an explicit synthetic-source label. Full «Инвентаризация», «Отгрузить» and «Долги поставщикам» actions appear only when their real workflows exist. The demo RAW receiver sees both warehouse names as §16 requires, but FINISHED quantities/documents require a separate grant. Company and warehouse defaults must come from permissions, not hard-coded IDs. Unknown costs or quality release must display as unknown, not zero cost or available stock.

## Risks and operational controls [ASSUMPTION]
Concurrency and retries can duplicate stock; test against PostgreSQL with competing transactions. Cross-company references can leak or mix stock; validate every related object and scope every query/export/download. Decimal and explicit conversion snapshots prevent unit drift. Lot identity does not imply FIFO valuation or physical segregation.

Backups must include database and attachments, with a proven restore; provider claims are not verification. Deployment, HTTPS, network availability, recovery targets and server rights remain open. No real integrations or data during development.

Separate development, test, staging and production databases, uploads and secrets. Keep credentials out of Git. Protect attachment downloads using parent-document permissions, including commercial-price access; retain metadata/hash and restrict upload type/size. Use session authentication and CSRF protection. Log operation IDs and failures without credentials or confidential document contents. Future imports use unique company/source/external identifiers and reconciliation reports. Establish performance targets from measured forms/list queries; use pagination and appropriate indexes without inventing a throughput promise.

The reported Windows Server 2022 host (~16 GB RAM), missing administrator rights and claimed 12-hour backups are brief context, not verified deployment readiness. Phase 1 checks the IDE's interpreter and isolated environment before installation. Use a separate PostgreSQL instance/container, never existing ERPNext volumes. Pin versions and supply Windows setup instructions then. Existing .venv, .idea and sample main.py are preserved. The proposed ebb-erp application root will own its README, configuration and docs; move the reviewed docs there when that repository is created, leaving a workspace pointer rather than maintaining two live document trees.

## Unresolved business choices [OPEN]
See [Q-01–Q-10](open-questions.md). Receipt authority, weight evidence, quality release, correction permissions and finished-goods handover are not approved. No FIFO/weighted-average policy, quantity tolerance, credit limit, tax or cost-allocation method is selected. A stock-only prototype must say that financial status is not yet tracked; it must not infer paid/unpaid from receipt data. No real consumption/dispatch of uncertain or held stock until its policy and workflow exist.

## Scope and validation
Phase 0 delivers design only. Phase 1 provides the technical skeleton. Phase 2 delivers RAW procurement; Phase 3 adds controlled FINISHED receipts. P0 requirements span these phases; Phase 0 is not the P0 application.

Phase 1 checks: clean isolated install, PostgreSQL migrations, authentication, scoped demo data, Russian layout and repeatable test command.
Phase 2: AT-01–04 and AT-07; AT-08 access boundaries; the provenance/reconciliation part of AT-09. Its literal conveyor-to-production scenario remains for Phase 4. Include basic purchase-charge capture without assumed allocation, concurrent creation/confirmation retries, all-line rollback, protected uploads, unit errors and cross-company access.
Phase 3: AT-06 and AT-10, including reversal after an earlier correction. AT-08 bank-route checks recur when finance exists. AT-05 waits for approved financial recognition rules. The [coverage register](requirements-coverage.md) distinguishes these partial checks from complete acceptance.
All numerical examples are synthetic. Documentation integrity checks are reported in the review; no application tests or browser demonstration have occurred.
