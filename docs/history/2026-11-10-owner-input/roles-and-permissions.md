# Roles and permissions — proposed, pending owner allocation
Source: §13. Default deny; check company, warehouse and action on every backend endpoint, report and attachment.
- Raw receiver: draft and view permitted RAW receipts; real confirmation authority OPEN. The synthetic §16 demo grants RAW confirmation and visibility of both warehouse names, with FINISHED quantities/documents separately restricted.
- Finished keeper: permitted FINISHED receipts and later dispatch; no RAW editing by default.
- Purchaser/bank operator: permitted contracts and shipments, RAW read access and only explicitly granted FINISHED visibility; commercial prices and financial rights separately assigned.
- Laboratory: related lot inspection and protected quality evidence; release authority OPEN.
- Production lead: relevant stock visibility and later output confirmation.
- Cashier: permitted finished availability and later sales/customer payments; no RAW changes.
- Director: scoped management visibility; exception approvals only where explicitly assigned.
- System administrator: technical administration does not automatically confer payment authority.

Synthetic prototype accounts use scoped roles, not universal superuser access. Deny self-approval of disputed corrections in the demo, consistent with §13. Actual correction creator/approver separation and overlapping employee roles require Q-01/Q-08 answers. A technical administrator can maintain access but is not automatically a bank operator. Maintain audited exceptional technical access.

Permission checks cover create, view, edit draft, confirm, correct, reverse, inspect, view commercial price and download evidence independently. Apply them to the result of a retried operation too. Warehouse permissions alone do not disclose supplier prices, contracts or bank details. The same object/field restrictions apply to searches, totals and exports. Test direct URLs, forged company/warehouse IDs, protected attachments and button visibility. Re-run AT-08 against actual financial routes when they are introduced; their absence now is not proof of future bank security.
