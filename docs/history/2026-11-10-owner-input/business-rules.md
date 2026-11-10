# Confirmed business rules
Authority: original brief v1.0; later written owner decisions take precedence. [CONFIRMED] here means expressly required by that brief, not independently verified on site. Re-reviewed 2026-11-10; no new owner policy approvals.

- BR-01 (§0): management accounting pilot at Mariam-Osh; official accounting stays in 1C. [CONFIRMED]
- BR-02 (§4): RAW and FINISHED remain separate; no invented third warehouse. [CONFIRMED]
- BR-03 (§3): direct receipt is allowed; contracts and shipment plans do not post stock. [CONFIRMED]
- BR-04 (§5): confirmation posts once per line, even on retries. [Didnt understand this one]
- BR-05 (§5): receipt, obligation and payment are separate facts; no duplicated debt or cost.[CONFIRMED]
- BR-06 (§4): exact units and Decimal quantities; empty packaging is separate from finished SKU. [not sure what you mean, yes the numbers should be accurate]
- BR-07 (§4): retain measurement provenance; estimated quantities are not weighed facts. [CONFIRMED, for example the order supply might have not the same number of quintiy for the actual one, but the balance will be changed on factual one, and the debit is still calcualted on the order supply, one, if the price need to be changed we need to think where we will change the charged number maybe we could modify order supply directly for example]
- BR-08 (§5): confirmed history survives corrections and cancellation. [Give me example not sure about this one, it should allow to cancel the wrongly opeations, however if they are linked to different events, it should require to unlink them from linked events and then let it cancel hence]
- BR-09 (§5): actual dispatch is distinct from sale and payment. [the dispatch can be linked to the to the sale, because sometimes people buy and pay at the spot which means the lead is closed, sometimes they take it to the debt and pay later, which creates debit and then substrats so we need think the logic here too and make the decion and functionality]
- BR-10 (§7): costing is monthly; full management profit requires verified stock and cost data. [CONFIRMED]
- BR-11 (§0, §16): synthetic data only; no real 1C/bank integration without separate authorisation. [CONFIRMED, not running project for now, just tests functionality]
- BR-12 (§5.1): planned, received, accepted, billed quantities and paid amounts stay distinct; differences are visible rather than overwritten. [NOT SURE, i think planned and recieved/accepted enough, differences are visible its good idea but where the debit is going to be calculated this is the question, maybe we could do order and if cndotions change deacrease the price there and match to the condition of factual, however by storing history of it, idk think what should we do in which way. maybe u are right first planned, recieved could be used for debit allocation, and the one could be modified]
- BR-13 (§6.5): effective business dates differ from recording timestamps; unknown monetary values are not invented.[CONFIRMED]
- BR-14 (§9, §11): Russian desktop/tablet UI, backend authorisation, protected confidential documents and recoverable database/files are required. [HIGHLY CONFIRMED]
- BR-15 (§0, §3.5, §16): no compulsory production order, sales order or ordinary purchase order as a prerequisite to recording the real event. [CONFIRMED, for now the purchase order might be one we could implement and try]

The exact measurement-basis enumeration, role assignments, schema, state machines, precision, quality release, corrections after downstream usage, valuation and allocation remain proposals/open decisions. They are not approved merely by appearing in the design.

Decision log: no new owner answers yet. Record date, owner wording, affected rule, implementation and test impact when answers arrive. Architecture assumptions belong in domain-decisions.md, not in this confirmed register.
