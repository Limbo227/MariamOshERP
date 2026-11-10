# Business rules — current core
Updated 2026-11-10. Source priority: explicit follow-up answers → annotated owner answers → original brief → marked technical assumptions.
Original owner wording is preserved in [annotated questions](history/2026-11-10-owner-input/open-questions.md) and [annotated rules](history/2026-11-10-owner-input/business-rules.md). CONFIRMED means stated by the owner, not verified on site.

## Existing rules, with the owner's clarifications
- **BR-01 [CONFIRMED]:** management ERP for Mariam-Osh; statutory accounting remains in 1C.
- **BR-02 [CONFIRMED]:** two main warehouses, RAW and FINISHED. RAW has Storage A, Storage B and packaging/material storage as locations, not additional main warehouses. A/B usually hold different wheat classes; do not hard-code a permanent class assignment.
- **BR-03 [CONFIRMED]:** implement supply orders and allow direct receipts. Orders/batches never increase physical stock.
- **BR-04 [TECHNICAL RULE; explained]:** one receipt line changes stock once. Example: a 3,000 kg receipt followed by a double-click or network retry still adds 3,000 kg, never 6,000. This implements the owner's requirement for accurate quantities; the original annotation asked for explanation.
- **BR-05 [CONFIRMED]:** order liability, goods receipt and payment are separate linked facts. Confirmed order creates debt, receipt adds actual stock, payment reduces debt.
- **BR-06 [CONFIRMED accuracy; technical representation]:** empty sacks are material items; flour in a sack is a finished SKU. 100 filled 50 kg bags means 100 finished units / 5,000 nominal kg and consumes 100 matching empty sacks. Decimal means exact decimal arithmetic for quantity/money, avoiding binary rounding errors.
- **BR-07 [CONFIRMED]:** wheat received is weighed; sacks and finished bags are counted. Stock uses actual received quantity; supplier debt follows the agreed order amount until an agreed amendment.
- **BR-08 [CONFIRMED cancellation need; proposed mechanism]:** users must be able to correct/cancel mistakes and inspect their history. Never erase dependencies to force cancellation. See the correction example below.
- **BR-09 [CONFIRMED future context]:** a sale, dispatch and payment may be linked and happen together or on different days; later payment reduces customer debt. Full sales/dispatch is outside this core.
- **BR-10 [CONFIRMED]:** monthly costing and full management profit are later goals.
- **BR-11 [CONFIRMED]:** synthetic functional testing only; no live integrations or production launch now.
- **BR-12 [CONFIRMED two user quantities; proposed internal separation]:** users chiefly see ordered and actually received quantities. Quality results/release are separate status/evidence. They do not need mandatory billed/accepted quantity fields in every form. Agreed financial amount and payments remain separately stored.
- **BR-13 [CONFIRMED]:** business effective date and recording time differ; unknown amounts are not invented.
- **BR-14 [CONFIRMED]:** Russian desktop/tablet UI, backend permissions, protected commercial data and recoverable records.
- **BR-15 [CONFIRMED]:** supply orders are useful and included; production/sales orders are not prerequisites for recording facts.

## New confirmed operating rules
- **BR-16 (Q-01):** the same authorised person may enter and confirm receipt. Order creation, customs handling and factory weighing can be performed by different people. Customs port varies by delivery batch.
- **BR-17 (Q-01/02):** one supplier batch can arrive through multiple wagons and on multiple dates. Preserve each actual arrival; e.g. 3,000 + 3,000 + 4,000 kg against a 10,000 kg plan.
- **BR-18 (Q-01):** supplier raw-material prices are available to authorised procurement/bank staff, not cashiers or manufacturing. Quantity/arrival information can be shared without prices.
- **BR-19 (Q-03/05):** supplier documents/passport and quality fields are optional for order/receipt creation. Store local results per wagon and compare with supplier evidence. Significant weight/quality discrepancies go to the director; thresholds are not yet specified.
- **BR-20 (follow-up):** quality results do not automatically release wheat. An authorised person records the release decision manually.
- **BR-21 (Q-04/06):** packed finished goods are the recorded production output and immediately become warehouse responsibility; no additional handover confirmation.
- **BR-22 (Q-06):** each finished flour bag consumes exactly one matching empty sack. Damaged sacks can be counted and written off separately at month end.
- **BR-23 (Q-10):** wheat classes can mix. Manual wheat deduction must be available. Do not invent a precise incoming-lot-to-output relationship or automatic yield.
- **BR-24 (Q-07):** current by-product production is inferred from shipments/sales and may include prior leftovers. Preserve this as an estimate, never an independent measured production fact.
- **BR-25 (Q-08):** log actions and allow reasoned backdated corrections, but reject operations that would create negative stock. Negative cash/bank balances must also be prevented when those actual account books are implemented.
- **BR-26 (follow-up):** confirming the agreed supply order creates debt once; drafts do not. Subsequent negotiated changes are dated amendments with preserved history. Payments reduce the debt, and physical receipt does not create it again.

## Examples answering the owner's comments
**Correct a receipt:** recorded +100 sacks, actual count 90. Preserve +100 and add a linked −10 correction with a reason; stock becomes 90. A cancellation adds an inverse effect and shows who cancelled it. If 95 sacks were already used, −10 would leave −5: block it, show affected later operations, and investigate/correct the wrong dependent facts first. Do not delete a production link to hide actual consumption.

**Amend an order:** synthetic 10,000 kg × 20 KGS = 200,000 KGS confirmed debt. Actual receipt 9,800 kg adds only 9,800 kg; debt remains 200,000 until agreement changes. An authorised amendment to 196,000 records −4,000 debt adjustment. A payment of 50,000 leaves 146,000 due. Keep the original 10,000 kg plan and received discrepancy visible.

**Overpayment after amendment:** preserve the payment. Show supplier credit separately if agreed debt falls below allocated payments; never fabricate a cash refund or silently discard the excess.

## Owner decision log
2026-11-10: Q-01–Q-10 answered in files; interpreted above with uncertainty retained. Two explicit follow-ups confirmed:
- “Yes—debt starts when the supply order is confirmed.”
- “Record results; an authorised person decides release manually.”

Technical defaults, authority assignments and later details are listed in domain-decisions.md and open-questions.md. The original “not sure” comments are not blanket approvals of every implementation detail.
