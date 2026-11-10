# Core permissions
Backend enforcement on every action, query, download, export and retry. Company/location scope plus action/field grants. Actual staff assignments are D-01; names below are role capabilities, not appointed people.

- **Procurement:** orders, batches, optional documents and authorised commercial prices; confirmation/amendment grants explicit.
- **Customs worker:** batch/port/transport processing and expense evidence. No automatic supplier-price visibility unless separately granted.
- **Factory receiver:** quantity-only arrival plans, actual weights and RAW receipts. May create and confirm the same receipt when granted both. Both warehouse names can be visible; data access remains scoped.
- **Laboratory:** supplier/local quality evidence, per-wagon comparison and comments. Release is a separate permission, not automatically implied by a lab login.
- **Production:** raw quantities, available released grain, finished reports and permitted manual issues. No raw-material prices or financial attachments.
- **Finished keeper:** finished quantity/history views. No extra handover needed to recognise output.
- **Bank operator / settlement recorder:** authorised commercial data and recorded supplier payments/allocations. No online banking execution.
- **Director / authorised reviewer:** discrepancy queue, reasoned release, amendments and corrections according to grants.
- **Cashier:** only permitted finished quantities in this core; no raw prices. Customer finance later.
- **Technical administrator:** maintenance rights do not automatically mean business payment or release authority.

Demo users are scoped. A receiver may confirm their own normal receipt, while disputed corrections require an explicitly authorised reviewer; actual self-approval policy for those exceptions remains a proposed control. Protect prices both in forms and serialized results. A quantity-only receipt view must not expose its supplier invoice attachment. Audit grants, confirmations, amendments, release, correction and cancellation.

