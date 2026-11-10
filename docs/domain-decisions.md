# Domain decisions — core revision
2026-11-10. Owner answers override the previous Phase 0 proposals. See business-rules.md for exact authority and history/ for superseded designs.

## [CONFIRMED]
Supply-order debt starts at confirmation; physical stock starts at actual receipt; partial batches/wagons and variable customs ports; two warehouses with real RAW locations; optional documents; per-wagon quality comparison and manual release; output counted as finished bags with immediate warehouse responsibility; one empty sack per output bag; manual grain issues; immutable audit with corrections and no negative stock; restricted raw-material prices.

## [ASSUMPTION]
- A-01: Django modular monolith, PostgreSQL, templates/HTMX/Tailwind; one repository in the existing directory.
- A-02: PurchaseOrder is the user-facing supply agreement. An optional contract reference/document can attach to it; a separate full contract lifecycle is unnecessary for this core.
- A-03: Shipment means supplier delivery batch; TransportUnit identifies a wagon/truck. A batch and a wagon can have multiple receipt events. Incoming provenance lots stay stable without asserting exact depletion after mixing.
- A-04: one inventory posting service accepts typed receipt, production-output, manual-issue, adjustment and opening-stock lines. Source/effect uniqueness supports one output plus one sack-consumption effect per production line.
- A-05: every stock entry belongs to a location. Quantity protection is by company/location/product; incoming lot is provenance, not a fabricated remaining-lot balance after pooling.
- A-06: received wheat is physically counted but unavailable for production until an explicit manual release. Release alters the usable-quantity projection, not physical stock. Partial release can be stored explicitly. This implements BR-20; no automatic quality thresholds.
- A-07: production confirmation does not demand a fictional measured grain amount. It flags consumption pending until manual issues are recorded. It does require sufficient matching sacks.
- A-08: negative-stock checks cover both present and subsequent historical balances after a backdated operation, with serialized location/product updates.
- A-09: supplier charge/payment records are manual management facts, with currency-specific allocations. They are not an online bank or a claimed cash/bank account balance.
- A-10: retain original agreed order revision and later authorised amendments; never edit past posted financial facts. Supplier overpayment becomes a visible credit, not discarded payment.
- A-11: by-product estimates are informational observations with source and uncertainty; exclude them from reliable stock and costing until actual dispatch/counting is available.

## [OPEN]
D-01–08 in open-questions.md are implementation/operating details. No precise grain yields, FIFO/average valuation, laboratory tolerances, exchange rates or costing allocation are approved.

## Superseded proposals
The earlier Phase 0 design deferred production and payables, used synthetic finished receipts as the main Phase 3 feature, and delayed StorageLocation. Those choices are superseded by the owner's core scope and answers. Synthetic fixtures remain mandatory, but the workflow being tested is real production reporting, not a fake supplier receipt.
The prior one-ledger-entry-per-source constraint is replaced by one entry per source/effect, because production has output and packaging-consumption effects. A receipt still has exactly one original stock effect per line.
The previous suggested nested ebb-erp repository is replaced by this already isolated project root; keep one maintained document tree.
