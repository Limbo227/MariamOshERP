# Inventory workflows
Source: §§3.4–3.7, 4, 5, 12.

RAW: confirmed wheat/material receipt increases stock. Production issues later record actual measurement basis; no invented daily consumption.
FINISHED: controlled synthetic receipt increases only finished stock; future confirmed production handover supplies its source. Actual dispatch decreases stock independently of cashier sale/payment.
Internal locations are future subdivisions of the two warehouses. WIP is a separate future accounting decision.

Balances derive from confirmed signed movements and documented opening entries. Before a real pilot, opening balances require an approved dedicated source workflow; the first synthetic tests begin from zero. Corrections preserve originals, carry reasons/permissions and appear in history. Reversal includes original and offset in reports and accounts for prior partial corrections; see domain-model.md. Backdated reports distinguish effective dates from recording dates. Summing balances by effective date must not exclude original entries merely because their source document is now REVERSED: the compensating entries supply the reversal.

Mass uses Decimal kg; tonnes are explicit conversion. Empty bags use pieces. Finished flour retains whole counted bags and derived nominal kg on the same event, not two stock postings. Actual weighed mass is separate from nominal mass. Reports distinguish WEIGHED, COUNTED, DECLARED, ESTIMATED and RECONCILED. Aggregate mixed-certainty totals retain their breakdown rather than claim weighed accuracy. Record measurement time/actor/evidence as well as entry time/actor.

An estimated issue later measured at a different quantity receives a signed difference, not a second full issue or overwritten observation. Phase 2 tests this provenance/correction capability with synthetic stock records; the full AT-09 conveyor/production issue remains Phase 4. A quality hold changes availability only under an approved policy; it does not silently reduce physical stock or create a third warehouse. Sub-location transfers later have balanced outgoing/incoming effects and leave the warehouse total unchanged.
