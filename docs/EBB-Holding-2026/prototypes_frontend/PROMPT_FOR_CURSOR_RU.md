# TASK FOR CODING AGENT — Mariam ERP frontend (Django / HTMX)

You are working inside the **existing Mariam ERP repository**. The user has supplied a ZIP containing **21 PNG screenshots** and a separate `Mariam_ERP_Interactive_Prototype.html` as **visual UI references**. Implement the frontend by integrating with the real existing Django backend. **Do not create a separate fake application, do not seed the sample values from the screenshots, and do not change the business domain according to guesses.**

The application interface is in **Russian**. This file is the agreed functional scope for the current phase. The screenshots determine visual style, layout, table structure and navigation; this prompt determines the domain constraints and safety requirements. **If a screenshot and the existing verified backend disagree, inspect and explain the conflict. Do not silently change accounting logic.**

## 0. Critical rules

1. **Frontend phase only.** Reuse existing Django models, forms/services, transaction logic, permissions, `Document` lifecycle, financial ledgers and validations. Prefer edits to `ui`, templates, frontend-oriented views/forms, CSS/HTMX and read-only reporting/query services. Do not introduce new financial/accounting rules.
2. **DO NOT implement production.** No production reports, recipes, milling runs, ingredient deductions, flour-output calculations, packaging consumption, or production menu. Existing production code must remain untouched; the production business process has NOT been approved.
3. **DO NOT implement sales business workflows.** A customer payment is a financial operation only. Do not infer sales document lifecycle, invoice, shipment or receivable rules not already approved.
4. **DO NOT remove `StorageLocation` or migrate stock tables in this task.** The user wants the UI to show only the warehouse, without exposing the internal location `Основное`. A future backend migration removing locations is separate and requires explicit approval. For now, use existing warehouse-only backend helpers / compatibility and calculate balances across *all* locations in a warehouse.
5. **NO destructive data operations.** No database reset, truncate, delete, reseed, automatic reconciliation, altering existing receipts/shipments, migration rewriting existing history, hard-coded assumption that working DB contains only demo data. Use isolated test DB for automated tests.
6. **One admin user for now.** No multi-user role system, employee approvals, row-level permissions or permission-management module. Use Django's existing authentication/admin protection as appropriate.
7. No arbitrary user-defined money operation semantics. Operation types are predefined. Admin can create **expense categories/articles** and existing supported directories, but cannot define a new operation with custom debit/credit/effect rules.
8. **Never invent unapproved business rules.** If a crucial detail is missing, isolate that feature, clearly mark it as awaiting approval and continue with independent approved frontend work. Do not improvise accounting, allocation or costing rules.
9. Do not claim a feature works because the screenshot depicts it. Verify the corresponding backend endpoint/service and integrate the actual functionality. No silent no-op save/post buttons in the delivered app.

## 1. Existing stack / models to inspect first

Expected architecture: **Django + PostgreSQL + Django Templates + Tailwind + HTMX**. Existing apps likely include `core`, `inventory`, `procurement`, `finance`, `production`, `sales`, `ui`. Inspect the repository and actual names before coding.

Relevant models/services (verify before use):

- Master data: `Party`, `Product`, `ProductCategory`, `Warehouse`, `StorageLocation`, `DeliveryTerm`, `RailwayStation`, `ExpenseCategory`, `MoneyAccount`, supported currencies / units.
- Purchases: `PurchaseContract`, `PurchaseOrder` (used in one workflow as **specification**, and in another as **ordinary goods order**), `Shipment`, `ShipmentWagon`, `GoodsReceipt`, receipt line model(s).
- Documents and ledgers: `Document`, `StockMove`, `MoneyDocument`, `MoneyMove`, `OpenItem`, `Allocation`, `AuditEntry`.
- Production code may exist but is **out of scope**.

Audit actual routes, existing templates, forms, DTOs, service calls, constraints, state transitions and tests before implementing. Summarise missing hooks and avoid duplicate business logic in views.

## 2. Visual design system

Use the PNGs as close visual guidance, not pixel-perfect images that need to be embedded as page backgrounds. Build reusable templates/components:

- Dark navy left sidebar, teal accent, light gray workspace, white rounded cards, compact dense tables, subtle borders and status chips.
- Russian labels, clear formatting for `KGS`, `RUB`, `USD`, `кг`, `т`, `шт`, `л`, `мш`. Currency symbols may supplement but ISO codes must remain unambiguous.
- Consistent page header, breadcrumbs and **real Back navigation**. Back must go to previous meaningful screen, preserve list filters, selected page/sort, and ideally scroll position. Browser Back/Forward should also work.
- Lists have real search, filters, sortable columns, pagination (where needed), create/open actions and clear empty states.
- Document cards show Draft/Posted state, actions available for that actual state, field-level validation, confirmation for financial/inventory posting, and service errors in Russian.
- No artificial workflow steps modeled after 1C. The target is 1C-style table clarity with fewer clicks.
- Desktop is primary (screenshots 1600px wide). Make narrower screens usable without clipping essential controls. Large monitoring tables can scroll horizontally.
- Do not hardcode demonstration prices/dates/names. The screenshots contain **fictional demonstration data**.

## 3. Navigation / pages

Recommended sidebar:

- `Главная`: overview and links, only real calculated widgets.
- `Закупки`: tabs `СВОД`, `Контракты`, `Спецификации`, `Поставки пшеницы`, `Заказы товаров`, `Приёмки товаров`.
- `Финансы`: `Журнал операций`, `Счета и кассы`, `Платежи`, `Расходы`, `Переводы`, `Конвертация`.
- `Склад`: `Остатки`, `Движения`.
- `Справочники`: all actual supported directories.
- `Отчёты` only if grounded in implemented report functionality; not required to invent extra datasets.

Avoid duplicate fragmented entry points: clicking a supplier contract opens its specifications; clicking a specification opens its posted shipments, receipts/expenses/settlement summary as supported.

## 4. Master data (screens 05, 19, 20)

Build functional CRUD/list-detail views for **all existing supported editable dictionaries**, including:

- `Контрагенты` (supplier/buyer attributes that actually exist in backend; do not invent required fields).
- `Номенклатура` / products: name, category, unit, unit-weight if relevant, existing editable attributes.
- `Категории товаров`: editable user category name plus the existing **technical role** (`WHEAT`, `FLOUR`, `BYPRODUCT`, `SACK`, `MATERIAL`, `OTHER`) according to real model.
- `Склады` (the two current physical warehouses: `Склад сырья`, `Склад готовой продукции`; show actual DB values, not hardcoded records).
- `ЖД станции`: station name, optional code/country when supported.
- `Условия поставки`: editable directory.
- `Банковские счета и кассы`: `MoneyAccount` and currency, existing fields.
- `Статьи расходов`: `ExpenseCategory`, free creation/editing/deactivation if backend supports it.
- Units: **four existing fixed values** `PCS`, `KG`, `L`, `BAG`, displayed as `шт`, `кг`, `л`, `мш`. These are selectors, not a user-editable units CRUD screen.
- Financial operation types: an **informational read-only list** of approved operations, not generic user-defined effect rules.

Product inventory quantity is always in the product's base unit; e.g. a product measured in `BAG` with `unit_weight_kg=50` has 100 BAG in stock, not 5000 stock units. Don't recalculate legacy KG stock into bags.

## 5. Contracts / wheat specifications (screens 02, 03, 06, 07)

### Contracts

- Contract creation/editing and list. Supplier, contract number/date, currency only where supported. Contract can have many specifications. A contract alone does not create stock or supplier debt.

### Specifications

- A wheat specification is linked to a contract; it has a product, planned weight **in kilograms**, unit price **per kilogram in contract currency**, delivery term and informational quantity tolerance, as supported by the verified model.
- Supplier/currency inherit from the parent contract.
- Display planned monetary total = planned kg × price/kg, without creating debt for the plan.
- `operational_status`: `IN_PROGRESS` = `В работе`, `COMPLETED` = `Выполнено`. Its status is **independent** of the posting status of each shipment.
- Show action to complete/reopen specification only if service exists. When completed, new shipments are blocked until reopened per current backend. Completing does not change stock/debt. Do not prevent completion merely because volume is 80% or 110%; tolerance is informational.

## 6. Wheat supply shipments (screens 04, 10, 11)

- The flow is **Contract → Specification → Shipment → [automatic internal GoodsReceipt] → StockMove + supplier OpenItem**.
- Creating a draft shipment does not affect actual stock or debt.
- Shipment form: selected specification, departure railway station, departure date (optional), arrival date (required **to post**, not necessarily to save draft), wagon count, total documented kg. Price, currency, supplier read-only inherited from specification.
- Two UI modes: quick summary entry (count + total kg, no wagon details required), and detailed wagon list (wagon number and weight per row). Detailed wagon rows are complete only if wagon count and total kg match shipment header, and required row fields are present.
- Allow adding detailed wagon rows after posting where supported, **without changing posted total kg or generated debt**.
- Posting uses existing services, creates only one internal receipt and its stock/debt effects; do not show a second manual `Принять товар по этой закупке` action for a shipment-backed purchase line.
- Unpost uses the existing service and must respect downstream stock/accounting constraints. Never independently unpost, edit or delete shipment-generated `GoodsReceipt`.
- Shipment status: `DRAFT`/`POSTED` displayed `Черновик`/`Выполнено`. Do not invent logistics/customs states.

## 7. Ordinary goods orders & receipts (screens 08, 09, 21)

- Ordinary goods workflow: **Ordinary PurchaseOrder → manually posted GoodsReceipt → StockMove + payable OpenItem**. Not a railway `Shipment`.
- In a purchase order, user enters item lines, unit, ordered quantity and **price per product unit**, currency and supplier. Show totals.
- Support multiple partial receipts per ordinary order when existing services allow. No stock/debt on creation of order; only upon posted receipt.
- **Critical approved UI rule: DO NOT show or allow editing price in receipt form.** The person receiving goods selects the order and enters actual received quantity, date and warehouse. The backend resolves the exact original purchase line price for payable calculation; it must not rely on hidden form fields or a user-submitted receipt price.
- Ensure each receipt references the correct purchase lines; for a multi-line order do not apply a random header price.
- A PurchaseLine must never be received via both Shipment-generated receipt and manual GoodsReceipt channel. Respect existing backend locking and idempotency logic.

## 8. Wheat purchase monitoring / reporting (screens 01, 02, 03, 04)

This is the **core feature** of the current frontend. Think of a cleaner live version of a 1C/Excel `СВОД`.

Main monitoring table: group by supplier → contract → specification, one specification-level row with:

- supplier, contract, specification, wheat product;
- contract currency and price **per kg**;
- planned weight (kg; display tonnes for readability), posted received weight, difference, % execution, informational tolerance;
- planned value, **actual posted received value**, allocated supplier payments, outstanding payable after allocations, specification operational status;
- drill down into individual shipments with shipment ID, arrival/departure dates where available, departure station, wagon count, documented weight, inherited unit price, shipment amount and posting state;
- totals and filters by supplier/contract/spec/product/date/status/station; basic export to Excel **only if feasible without destabilizing existing stack**.

**Accounting correctness:**

- Actual received volume and debt **only from POSTED shipments/receipts**; exclude drafts from realized totals. A draft's `theoretical amount` can be displayed in a separate clearly marked column but never added to actuals.
- Currency must be explicit; never sum RUB and KGS in one number. For multi-currency totals group by currency.
- Settled/payments amounts must be calculated from actual allocation/settlement records. An unallocated supplier payment is an **advance/unallocated payment**, not proof a specific specification is paid. Show advances separately when data exists.
- The amount/period filters need a clear documented definition; do not silently misstate retrospective debt/volume.
- Over-100% progress should be visible (e.g. `110%`) and visual bar can cap at 100%, without blocking.
- Cost/landed KGS/kg is **NOT** approved. Do not invent an FX rate or automatic distribution of logistics costs.

## 9. Financial operations (screens 12, 13, 14, 15, 16, 20)

Expose exactly the currently approved **six top-level operation types** using existing supported services:

1. `Поступление от покупателя` — money in; no new sales workflow.
2. `Оплата поставщику` — money out; store supplier and amount in account currency.
3. `Общий расход` — money out, expense category selected from directory.
4. `Расход поставки` — money out, category, link to **either a specific shipment OR the whole specification**, never counted twice.
5. `Перевод между своими счетами` — balanced money out / money in; not a business expense or revenue; respect compatible currencies according to existing service.
6. `Конвертация валют` — actual amount debited in one currency and actual amount credited in the other, FX rate derived. Do not automatically tie exchange to wheat price or supplier debt.

`MoneyAccount` represents bank/cash accounts per currency. These forms **record** actual payments; they do **not** initiate bank transfers through APIs.

`Allocation` can match payments and `OpenItem` debts. **Automatic supplier-payment allocation rule has NOT been approved.** Do not implement auto-distribution by FIFO, proportion, contract, etc. Build supplier payment creation with explicit unallocated status or the verified existing manual mechanism, and show balances correctly. If no approved/user-facing manual allocation flow exists, keep it clearly marked as pending and do not pretend a payment closed a specific shipment.

Create expense **articles** in `Справочники → Статьи расходов`; do not give admins a generic `Create operation type` form. Any optional restriction of an article to a specific operation type is not agreed yet; do not invent that validation. Preserve current backend effect semantics.

No synthetic single-currency grand totals. Bank balances should come from posted MoneyMove per currency/account. No double-counting of own-account transfers as revenue or costs.

## 10. Stock (screens 17, 18)

Two pages: `Остатки` and `Движения`:

- All products, actual warehouses, quantities in product's original units. Optionally display derived physical kg separately for weighted units, clearly labelled as derived.
- Warehouse and product/category/date search/filter; navigate from StockMove to source `Document` when safe.
- Do not expose `StorageLocation`, internal `Основное`, bin, rack or picking locations to the user.
- Reuse existing warehouse-only compatibility logic. **Do NOT delete location rows or rewrite historic StockMove as part of this task**.
- No stock movements are created from the Stock page by the new UI unless this corresponds to a pre-existing, explicitly approved backend service. In particular, no production forms.

## 11. Documents, correctness and audit

- Use existing `DRAFT → POSTED → DRAFT` service transitions only where supported. Do not directly mutate `Document.status`.
- Reposting and cancelling must be idempotent/safe according to service-layer rules and should return genuine errors when downstream movements make unpost unsafe.
- Existing `AuditEntry` / `snapshot` is an audit trail. If an existing read-only query/API is already present, a document `История` tab may show it. Do not invent unconfirmed audit fields or rewrite history.
- Opening balances, storno-only document families, settlement restrictions must retain their actual service behavior.
- Display both document operational state and posting state independently where applicable.

## 12. Navigation, quality, verification

- Build accessible/reusable Russian UI elements for main nav, table, filters, editable master-data form, document detail, money input, status, posting actions, breadcrumbs, user feedback.
- Back button should go to parent document or prior list and restore list query/filter. `Создать → Сохранить → Открыть` should be predictable. Provide valid Cancel actions and explicit “unsaved changes” warning if navigation would lose entered data.
- Form validation server-side; no trust in client totals. Use Decimal for financial calculation, avoid float for money.
- Use actual app endpoints; protect POST with CSRF; avoid duplicate submission.
- Inspect current tests and add tests for key new views and integration paths using an isolated database. Run targeted and full pytest where possible, Django system checks, and render/smoke checks. Report results precisely (don't claim passed tests without running them).
- If an action needs a backend API that does not exist, either reuse a confirmed existing service or **report a blocker and leave that action unavailable**, not a fake success.

## 13. Deliverables

Implement the frontend in the existing repository. At the end provide:

1. File list and route map for all implemented screens.
2. A concise **IMPLEMENTED / PARTIAL / BLOCKED / NOT TOUCHED** matrix for every screen below.
3. A list of any screens where the screenshots requested a backend capability that was absent, and the exact gap.
4. Test commands actually run, counts and outcomes, with any failures.
5. Clear statement that existing production and sales modules, source accounting logic, existing data and `StorageLocation` schema have not been modified.
6. Any essential unresolved business question explicitly separated from working frontend functionality.

## 14. Screenshot map

| File | Intended page |
|---|---|
| `01_dashboard.png` | Главная |
| `02_wheat_summary.png` | Мониторинг закупок «СВОД» |
| `03_specification_details.png` | Карточка спецификации, поставки, оплачено/долг |
| `04_shipments_monitor.png` | Общий журнал поставок пшеницы |
| `05_create_product.png` | Создать номенклатуру |
| `06_create_contract.png` | Создать контракт |
| `07_create_specification.png` | Создать спецификацию пшеницы |
| `08_create_order.png` | Создать заказ мешков/материалов с ценами |
| `09_create_receipt.png` | Приёмка обычных товаров без цены |
| `10_create_shipment.png` | Быстрый ввод поставки |
| `11_shipment_wagons.png` | Номера вагонов и вес каждой строки |
| `12_supplier_payment.png` | Оплата поставщику |
| `13_finance_journal.png` | Журнал денежных операций |
| `14_between_accounts.png` | Перевод между своими счетами |
| `15_currency_exchange.png` | Конвертация валют |
| `16_expenses.png` | Общий расход / расход поставки |
| `17_stock_balances.png` | Остатки склада |
| `18_stock_movements.png` | Складские движения |
| `19_directories.png` | Главная справочников |
| `20_expense_categories.png` | Справочник статей расходов |
| `21_materials_monitor.png` | Мониторинг заказов мешков и приёмок |

**Run autonomously on the approved UI parts after auditing the code. Do not stop for nonessential style choices. But if implementing a requested business behavior would require making up an unapproved accounting rule, STOP on that individual feature, document the question, and proceed with the safe independent screens.**
