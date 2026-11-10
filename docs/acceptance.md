# Core acceptance scenarios
Planned tests only. All figures are synthetic; run against PostgreSQL and the Russian UI during implementation.

- **CORE-01 / supply debt:** draft 10,000 kg × 20 KGS causes no stock/debt. Confirmation creates 200,000 debt exactly once, including concurrent retry.
- **CORE-02 / split arrival:** batch with multiple wagons arrives 3,000, 3,000, 4,000 on different days. Each receipt adds its actual weight to the chosen A/B location. Plan and debt do not repost. Double submit/create retry cannot create another receipt.
- **CORE-03 / shortage and amendment:** received 9,800 against 10,000. Show discrepancy; debt remains 200,000 until authorised amendment to 196,000. Payment 50,000 leaves 146,000; preserve the original agreement.
- **CORE-04 / settlements:** multiple payments and multiple-order allocations stay within payment totals and supplier/company/currency. Amendment below paid amount shows supplier credit. A customs cash/bank portion never also reduces wheat debt.
- **CORE-05 / optional evidence:** order and receipt work without attachments/passport values. With evidence, authorised users compare sender/local wagon values and units; wrong-company/private attachments are rejected.
- **CORE-06 / manual release:** received grain increases physical stock but starts unreleased under A-06. Manual release of 2,000 permits only that quantity to be issued. Duplicate release, over-release and release revocation below used quantity fail; no automatic pass/release from lab values.
- **CORE-07 / real production fact:** seed 500 matching empty sacks using authorised opening stock. Confirm 100 × 50 kg finished bags: FINISHED +100 units/+5,000 nominal kg; RAW sacks −100; wheat unchanged until a manual issue. No keeper confirmation.
- **CORE-08 / packaging integrity:** wrong sack mapping, fractional bag count, missing mapping or insufficient sacks rejects all production effects. Two simultaneous reports cannot overdraw sacks. Retrying does not duplicate output or consumption. Snapshot survives later catalogue versions.
- **CORE-09 / manual grain:** issue weighed/estimated class 4 and 5 from their locations, optionally linked to production. Preserve basis, no automatic yield or exact lot attribution. Block issue exceeding released or physical balances.
- **CORE-10 / corrections:** +100 sacks corrected by −10 gives 90; repeat correction request is idempotent. Full cancellation offsets the net family, not the original twice. If 95 already consumed, correction is blocked and dependencies shown.
- **CORE-11 / backdating:** an operation that leaves today's stock positive but causes an earlier intervening deficit is rejected. Concurrent backdating/posts serialize. Later actual treasury must apply equivalent funds protection.
- **CORE-12 / output reversal:** reverse output and sack consumption atomically. Separately recorded wheat issue stays unless explicitly reversed. Downstream stock movement can block reversal.
- **CORE-13 / losses:** a counted month-end damaged-sack write-off reduces only the correct sack item/location, with reason/authority and no negative stock.
- **CORE-14 / by-products:** sales-derived estimate remains visibly ESTIMATED and does not add trusted FINISHED stock or pretend independent production evidence.
- **CORE-15 / access and audit:** manufacturing/cashier cannot read raw prices through UI, endpoints, exports, totals or attachments. Receiver can enter/confirm with grants. Every confirmation/amendment/release/correction has actor/time/source; forged company/location references fail.
- **CORE-16 / rollbacks and opening:** invalid later line rolls back all prior lines; opening balances are sourced/audited and seeded idempotently; all balance projections rebuild from facts.

Document-level Phase 0 checks do not count as passing these scenarios. Later full finance/sales/costing acceptance remains separate.

