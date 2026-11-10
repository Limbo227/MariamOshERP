# Procurement workflows
Source: §§3.1–3.3, 5, 6, 8–12.

AS-IS: wheat is purchased from a small supplier group; contracts and transport precede arrival by weeks; laboratory compares quality with the passport. Logistics charges can arrive later. Bank operator manages transfers independently. Materials may be bought and paid immediately but those remain different facts.

TO-BE [ASSUMPTION implementing confirmed requirements]: optional contract → optional shipment → actual receipt draft → authorised confirmation → one stock entry per line. A direct receipt can start without either upstream document; a contract can be linked directly without a shipment. Match lines when shipment/contract details are known and validate supplier/company/product consistency. Partial receipts retain original planned quantities and expose discrepancies. A shipment's arrival/closure never posts inventory.

Phase 2 records known price/currency/price unit and source evidence without invented amounts, plus basic PurchaseCharge records linked to shipment/receipt as §14 requires. Late freight/customs/rail charges do not change posted quantities. Later allocation links charges to receipts/lots and retains its policy/history. Payments allocate to obligations, potentially many-to-many, without reposting inventory. Recognition date, allocation, rounding and approval powers remain OPEN. Neither a payment nor a service purchase creates physical stock.

Create a stable operation key before submitting a draft, reuse it on network retries, and confirm that same document idempotently. Preserve original evidence and planned/received/accepted quantities separately. Quality inspections can attach to a draft lot before stock confirmation. Q-02/Q-03 decide physical received quantity versus rejected/held quantity; the prototype does not infer usable stock.

Synthetic walkthrough: contract 100 t; shipments 60 t and 40 t; actual first receipt 59.5 t = 59,500 kg. RAW gains only 59,500 kg, FINISHED remains unchanged, first-shipment difference is −0.5 t. The outstanding plan is not stock and is not automatically a supplier debt. A repeated creation/confirmation request returns the same document/result.
