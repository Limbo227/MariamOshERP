# Table dictionary — planned core schema
Design reference, not generated migrations. PK = primary identifier; FK = reference to another row. Every business record is company-scoped; all money carries currency. Required at confirmation may be optional in a draft.

## Shared and catalogue
- **Company:** PK, name, timezone; owns organisational data. One pilot company, future companies separated.
- **Warehouse:** PK, company FK, type RAW/FINISHED, name; unique company/type.
- **StorageLocation:** PK, warehouse FK, name, active; one warehouse to many locations. Seed A, B, Packaging & materials and Finished products.
- **Supplier:** PK, company FK, name, contact/reference fields; restricted commercial details.
- **Product:** PK, company FK, SKU, name, category, wheat/flour grade where applicable, base unit, nominal package kg; unique company/SKU. Distinguish wheat classes, empty sacks and packed flour SKUs.
- **PackagingRule:** PK, finished-product FK, empty-sack-product FK, valid version, quantity-per-bag=1. Require exactly one applicable mapping at production confirmation; snapshot it on output.
- **User/company/action grants:** Django identity plus company/warehouse and action permissions. Price visibility is a distinct grant.

## Supply and transport
- **PurchaseOrder:** PK, supplier FK, company, agreed currency, status, dates, creator/confirmer, optional contract reference. One to many lines; no stock effect.
- **OrderLine:** PK, order FK, product FK, ordered quantity/unit, price and price unit. Original confirmed terms preserved.
- **OrderAmendment:** PK, order FK, revision, reason, actor/approval/date, prior/new terms. Child amendment lines reference affected order lines and record quantity/price changes; unique order/revision. Posting creates a financial delta, not a rewritten initial debt.
- **Shipment:** PK, optional order FK, supplier, supplier-batch reference, customs port, expected dates, status and responsible user. Plan details reference order lines or explicit product/quantity for direct batches.
- **TransportUnit:** PK, shipment FK, type WAGON/TRUCK/OTHER, external identifier, declared quantity/unit and source evidence. Duplicate identifiers are checked within context, not assumed globally unique.
- **PurchaseCharge / ChargePayment:** service expense facts and optional cash/bank payment portions; separate customs counterparty and wheat supplier accounting.

## Actual receipt and quality
- **GoodsReceipt:** PK, supplier, optional order FK, business date, status, actor/version. Document header may cover several wagon lines for one supplier/order.
- **ReceiptLine:** PK, receipt FK, product/location FKs, optional order-line and transport-unit FKs, actual quantity/unit, measurement time/basis/actor, evidence and optional commercial price fields hidden by permission.
- **InventoryLot:** PK, unique origin receipt-line FK, product/company, supplier batch reference. Incoming provenance only; physical mixing prevents invented remaining-lot accuracy.
- **SupplierQualityValue:** batch FK, optional transport-unit override, passport version, parameter, numeric/text value, unit and evidence. Optional.
- **QualityInspection / LocalQualityValue:** optional wagon and receipt-line FKs (at least one required), date, inspector, comment; one-to-many parameter results. If both sources are present they must agree. Retain supplier/local comparison, never overwrite sender's original value.
- **ReleaseDecision:** receipt-line FK, optional inspection FK, released/held quantity, authorised actor/date/reason and status. Physical quantity and usable quantity are separate; no automatic lab pass rule.

## Manufacturing and stock
- **ProductionReport:** PK, company, date/shift, optional line reference, actor/state/version. Actual packed output.
- **OutputLine:** report FK, finished SKU FK, whole bag count, nominal kg snapshot, FINISHED location, RAW sack location, sack SKU/mapping snapshot. One positive output and one negative sack effect.
- **MaterialIssue / IssueLine:** document date/reason/basis, optional production report FK; lines specify wheat/material product/location and actual/estimated quantity. Manual issues never change production count.
- **StockAdjustment / AdjustmentLine:** correction or damage/write-off header with reason/authority; lines reference original effects when correcting and explicit signed product/location quantities. New damage is a loss fact, not a fictitious correction of receipt.
- **OpeningStock / OpeningLine:** authorised documented starting quantities for tests and later migration, with date/evidence. No editable free-floating balance.
- **StockPostingSource:** exactly one line FK from receipt/output/issue/adjustment/opening. Unique non-null line references.
- **StockLedgerEntry:** source FK, effect, company/location/product, signed Decimal base quantity, optional signed bag count and nominal kg, provenance/basis, dates/actor. Unique source/effect; posted rows protected.
- **ByproductObservation:** date, product, quantity/unit, basis ESTIMATED, source shipment reference if available, note about uncertainty. Informational; no core ledger posting.

## Settlements and support
- **SupplierObligation:** supplier/company/currency and unique order FK or explicit approved manual-source reference. Never both automatic order and receipt charges for one debt.
- **ObligationEntry:** obligation FK, signed amount, initial/amendment/correction source, effective date and actor. Source uniqueness.
- **SupplierPayment:** supplier/company, amount/currency, date, external payment reference, CASH/BANK descriptor and actor/state. Records an external fact; does not execute a transfer.
- **PaymentAllocation:** payment FK, obligation FK, allocated amount, date/reversal linkage; same supplier/company/currency, sum bounded by payment.
- **Attachment:** protected document FK, storage key, filename/type/hash, actor/time; no public file URLs.
- **AuditEvent:** actor, action, document, timestamp, reason and significant previous/new values; retained.
- **OperationKey:** company, actor/command, unique key, payload fingerprint and protected result; safe creation and confirmation retries.
- **ExceptionRecord:** related order/receipt/wagon, discrepancy reason, responsible director/authorised user, state and resolution note. In-app follow-up, no external messaging.

## Schema discipline
Supporting line/result tables above are normalised during implementation; do not replace them with unvalidated arbitrary text blobs. Quantities/prices use Decimal, whole counts enforce integers, and unknown prices remain null. Define numeric limits before migrations. Cross-company references, stock effect counts and financial/release invariants require meaningful PostgreSQL tests. Schema proposals can evolve through dated ADRs while preserving these business invariants.

