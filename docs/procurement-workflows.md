# Supply order → arrival → stock
Source: owner Q-01–05, BR-03/05/07/16–20/26. Current core; see domain-model.md for relations.

1. Procurement enters supplier, product lines, quantity, agreed price/unit/currency and optional contract/passport evidence. Draft has no stock or debt.
2. Authorised confirmation fixes the original agreement and creates supplier debt once. The same person may create/confirm if permitted.
3. Record one or more delivery batches, customs port, responsible worker and wagon/transport references. Plan remains visible across partial arrivals. Track optional customs/logistics expenses and their cash/bank portions separately from wheat debt.
4. At the factory, receiver selects order/batch/wagon if available, RAW location and actual weighed quantity. Optional paperwork must not block receipt. Confirming creates stock once and preserves the plan-versus-actual difference.
5. Laboratory records local values per wagon and compares with optional supplier values. Send significant discrepancies to the in-app director queue, without an invented tolerance.
6. An authorised person manually releases received wheat quantity for production. Lab results alone do not release it. Partial/held quantities remain visible.
7. Record supplier payments and allocations in the agreed currency. Each payment reduces debt once; receipt does not recreate liability.
8. If the director negotiates a change, record an authorised dated order amendment with reason and previous/new terms. Change debt by its delta; do not rewrite actual weight or erase the original order.
9. Close delivery explicitly when complete or when a short-delivery resolution is documented. “Delivery complete” and “paid in full” are different statuses.

Synthetic walkthrough: confirmed order 10,000 kg at 20 KGS/kg → debt 200,000 KGS, stock 0. Actual arrivals 3,000 + 3,000 + 4,000 → stock 10,000, debt unchanged. Payment 50,000 → debt 150,000. If the final actual total instead is 9,800, stock is 9,800; only an agreed amendment changes debt.

Direct material receipt: receive counted empty sacks without a prior order. If a financial basis is known, an authorised separate manual obligation can record it; do not fabricate an order or assume free materials. Commercial amounts are hidden from factory quantity views.

Correction/cancellation follows dependency-aware reversals, not deletion. Financial cancellation of an order must account for payments/credits; it does not mean delivered wheat disappeared.

