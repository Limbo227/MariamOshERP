# Raw materials → production → finished goods
Source: owner Q-04/06/07/08/10 and BR-21–25.

## Physical layout
RAW has Storage A and Storage B for wheat plus Packaging & materials for sacks/other materials. FINISHED holds packed flour and future measured by-products. Internal locations are introduced now because the owner described them. A/B commonly separate classes 4/5; assignment stays configurable.

## Daily production
Operator records date/shift, finished SKU and bag count. The SKU supplies nominal bag weight and the matching empty-sack item; select configured source/destination locations. Preview output and sacks required, then confirm once.
Example: 100 bags of 50 kg flour → +100 finished units / +5,000 nominal kg in FINISHED; −100 matching empty sacks in RAW. No second handover. Counted nominal mass is never labelled weighed.
If sacks are insufficient, reject the entire confirmation: neither output nor sack consumption posts. Concurrent confirmations must serialize stock checks.

## Wheat consumption
Enter a separate manual grain issue by class and location with quantity, date and WEIGHED/ESTIMATED or other supported basis. Optionally link it to the report/shift. Check physical and manually released availability. Do not use finished flour kg as a wheat consumption formula: mixing, bran, moisture and WIP make that false.
A production report can be complete as an output fact while showing wheat consumption pending. This is not proof of a reconciled mass balance.

## Damaged sacks and by-products
Record a month-end damaged-sack count as an authorised write-off with reason and date. Use actual counted loss, not an automatic percentage.
By-product quantities derived from sales/shipments are estimates that may contain old leftovers. Store informational observations with source, excluded from trusted available stock. The later dispatch/counting workflow must reconcile them before any automatic production/dispatch posting.

## Corrections and balances
Show physical and released grain quantities separately. Sum immutable ledger effects by company/location/product, retaining measurement provenance. Incoming lots are receipt evidence; pooled manual issues cannot truthfully identify exact remaining lots.
Correct mistakes using dated signed effects, keeping the original and actor/reason. Reject any subtraction that makes stock negative today or at a later point in the affected historical timeline. Show dependent output/issues to help resolve the error instead of silently unlinking them.
Reversing production reverses output and sack consumption together, subject to downstream stock availability. Separately entered grain issues require their own explicit reversal; they are not automatically erased.

