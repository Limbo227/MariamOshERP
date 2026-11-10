# Owner answers and remaining details
Updated 2026-11-10. All ten initial questions were answered. Exact wording is preserved in [owner input](history/2026-11-10-owner-input/open-questions.md); current rules are in [business rules](business-rules.md).

## Answer register
- **Q-01 answered:** same authorised person may enter/confirm; separate procurement/customs/factory participants; prices restricted; partial arrivals. BR-16–18.
Answer: [Yes, there will be user rights, some users will have granted permisions to see more things, some not, leave room so we can manage that, but dont focus too much here]
- **Q-02 answered:** actual factory weight controls stock; director handles discrepancies; debt follows agreed terms and amendments. BR-07/26.
Answer: [Not only director should control discrepanies, but the responsible people, for example supply order operationist and who manages material acceptance see the differences and manage and sort the things on their behalf, so less director work is envolved.]
- **Q-03 answered + follow-up:** optional supplier passport, local wagon results, stored comparison; manual authorised release. BR-19/20.
Answer: [This is not the main focus, but would be nice if for every batch it has its passports we could attach the passport or quality details and enter actual ones and see differences, but not mandotary action in order to create transaction]
- **Q-04 answered:** wheat A/B, packaging/material area, finished area; bagged output is production. BR-02/21.
Answer: [Yes finished is bagged output of production correct, however, other secondary products like bran might be sold not in packeged quanity but in kilograms, so it could be stored as finished product to but unit of meausre kg, also to simplify dont create different storages for raw materials, let it allow to create storages in warehouse but for now just have two, one for raw, second for finished product, and there can be block or something where each end product can have its "something", that will allow to see recipent what it requaires to get generated for exaple one sack]
- **Q-05 answered:** store useful documents as optional evidence; no attachment requirement to create/receive. BR-19.
Answer: [Correct]
- **Q-06 answered:** immediate finished warehouse responsibility; one matching sack consumed per output bag; damaged sack write-off. BR-21/22.
Answer: [Yes, correct, check answer above, also there should be functionality of inventory write off, where we actually can create inventory write off with category, damaged, or returned smth]
- **Q-07 answered:** weigh wheat, count empty/filled sacks; by-products estimated from sales, not a reliable independent production count. BR-07/24.
Answer: []
- **Q-08 answered:** audit, backdating and no negative stock; dependent errors require investigation. Proposed reversal procedure explained in BR-08.
- **Q-09 resolved by explicit follow-up:** confirmed order creates debt, receipt does not duplicate it, amendments and payments change the balance. BR-26.
- **Q-10 answered:** mixed classes; manual grain consumption; no forced lot-depletion method. BR-23.

## Nonblocking implementation details [OPEN]
These do not require another whole-ERP interview or prevent Phase 1.
- **D-01:** actual user names and who gets release, amendment and correction permissions. Demo uses distinct scoped users, with correction/release authority assigned explicitly. [Supply opetionist: creates orders, tracks orders, inputs information where it will arrive and so, Custom operationist: does all customs work, handeles documents, pays fees, nothing much for him to input, inputs that recieved batch and how many wagons recieved, he also might not recieve the whole batch in once as one batch can contain many wagons, manufacture/storage opertionist, creates reciept of good where have links of supply order, and custom reciept too]
- **D-02:** product grades, packaging sizes and which empty-sack SKU each finished SKU consumes. Demo mappings are clearly synthetic.
- **D-03:** laboratory parameter names, units, applicable thresholds and partial-release practices. Prototype permits optional named numeric/text results; no automatic acceptance thresholds. Default manual release is explicit per received quantity. [Create simple terms quality control for raw wheat]
- **D-04:** operating day/shift boundaries, acceptable backdating window and later closed-period policy. Store effective date plus timestamp; never silently allow edits to closed periods once introduced. [Correct]
- **D-05:** currencies, decimal precision/rounding rules and foreign-exchange handling. Prototype uses clearly labelled single-currency examples; no cross-currency allocation until specified. [Dont bother too much about currencies for now]
- **D-06:** operational handling of held grain that is physically mixed. Digital release balances cannot prove segregation; do not promise exact lot purity. [Yes, just store them in raw storage, which will be manually deducted]
- **D-07:** direct receipts with no order and their financial basis. Stock receipt remains allowed; use an explicitly approved manual supplier charge when finance is known, not an invented supply order or automatic receipt liability. [Correct]
- **D-08:** by-product opening/closing counts and dispatch records. Shipment-derived estimates stay outside trusted available stock until that workflow is designed.

The design proposals for D-01–08 are not statements of current factory policy. Ask when a specific feature needs its real rule. Phase 0 core design is complete with these bounded details documented; application tests and operational sign-off remain future work.
