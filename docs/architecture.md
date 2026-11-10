# Architecture — supply to finished goods
Updated 2026-11-10. Current scope: [core plan](core-scope.md). Status labels and authority: [decisions](domain-decisions.md).

## Business boundary [CONFIRMED]
The core records the actual supply, factory receipt and packaged-output process once per event. It also records agreed supplier debt and manual payment facts. Cashier/manufacturing views exclude raw-material prices. Management costing, full sales and treasury are later extensions.

Two main warehouses remain RAW and FINISHED. Storage A, B and packaging/material storage are RAW locations. FINISHED has a finished-products location. Grain classes can mix; location/product balances are reliable only to the degree their inputs are weighed or explicitly estimated. Incoming batch provenance does not prove the composition of a finished bag.

## Stack [CONFIRMED stack; ASSUMPTION implementation]
Django handles forms, authentication and business services; PostgreSQL stores related records and protects transactional integrity. Django Templates render Russian pages; HTMX progressively updates forms/lists; Tailwind supplies shared styling. Exact supported versions are selected and pinned during environment setup, not guessed in Phase 0.

Use a modular monolith and one database for the pilot. Modules:
- core: company, membership/action grants, audit, protected attachments, retry identity.
- catalog: suppliers, products, units, grades and packaging-to-product mappings.
- procurement: supply orders/revisions, batches/wagons, customs facts and purchase expenses.
- inventory: locations, receipts, provenance lots, manual issues, stock ledger, corrections and balances.
- quality: supplier passport values, local wagon inspections/comparison and manual release decisions.
- production: output reports and automatic sack consumption.
- settlements: confirmed-order supplier charges, amendments, recorded payments and allocations.

Services call inventory/settlements through explicit interfaces in one transaction where consistency requires it. No business posting in hidden model signals. Read models can join authorised data; they cannot create independent stock/debt truth. Company ownership is checked across every relationship.

## Posting and retry safety [ASSUMPTION]
Create/submit requests carry a persistent company-scoped operation key, actor, command and payload fingerprint. Retries return the same permitted result; conflicting reuse fails. A new key is a new intended event, so duplicate-document warnings supplement retry identity.

Lock the parent document and every affected company/location/product stock key in deterministic order. Validate permissions, version, units, source consistency, release availability and nonnegative balances; create all effects and audit atomically. Production output and sack consumption must either both commit or neither commit. Receipt, production, manual issue, opening and correction sources are explicit typed foreign keys, not free-text model names.

Uniqueness is per source/effect. Receipt line has one RECEIPT effect; production line has OUTPUT and PACKAGING effects. Repeated confirmation must not recreate either. Posted quantities and financial entries are immutable under the runtime DB role; correction and audited status transitions are separate. SQL constraints/triggers plus service checks protect against admin/bulk updates as well as forms.

Backdated subtraction must leave every later cumulative balance nonnegative, not just today's total. Serialize checking and posting for the affected stock keys, including empty balances. Corrections also preserve release availability; no production issue can exceed manually released pooled grain.

## Money [CONFIRMED trigger; ASSUMPTION representation]
A confirmed order posts its agreed charge once. Amendments post signed differences; payments allocate to obligations by currency. Receipts never repost debt. A direct receipt with no order has no invented financial basis; authorised manual charges can record an explicitly known obligation.

Payment records describe payments already made externally. No online bank execution and no claimed cash/bank balance without a treasury book. Customs costs can record CASH/BANK payment references and split amounts, but supplier wheat debt and customs-service debt must not be conflated. Overpaid supplier balances appear as credit. No cross-currency arithmetic or implied exchange rate.

## Quality and privacy
Record optional passport parameters and local results with parameter/unit/source per transport unit and receipt. Manual release is a separate decision with actor/time/quantity/reason. Pending/held stock is visible physically but excluded from production availability under A-06. Alert the director through an in-app exception list; do not send external messages without separate instruction. No invented numerical acceptance thresholds.

Apply role, company, warehouse and field-level restrictions to HTML, queries, exports, downloads and retry results. Keep prices/contracts hidden from manufacturing/cashiers; provide a quantity-only arrival view. Evidence downloads inherit the strictest parent-document access.

## Development and delivery
Use this directory as the repository root. Proposed folders: config/, apps/{core,catalog,procurement,inventory,quality,production,settlements}/, templates/, static/, tests/, docs/. Preserve the existing IDE/virtual environment/sample files until intentionally integrated. Verify the configured Python interpreter before toolchain commands.

Development/test/staging/production have separate DBs, secrets and uploads. PostgreSQL is isolated from ERPNext. Synthetic data only. Production readiness later requires HTTPS, backup of DB plus attachments, a restore rehearsal, access review and actual server/network facts; the provider's backup claim is not evidence of recovery.

## [OPEN] and completion
D-01–08 cover real assignments, catalogue/quality definitions, dates and financial precision. These are bounded details with marked demo defaults. Full planned checks are in acceptance.md. Phase 0 validates documents and diagrams, not unbuilt application functionality.

