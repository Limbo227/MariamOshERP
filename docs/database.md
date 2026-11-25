# Схема базы

Имена таблиц — как в живой базе Django. Префикса `books_` у них нет. Старые рисунки с таким префиксом лежат в `docs/EBB-Holding-2026/architecture-2026-11-10/` и описывают целевой набросок, не эти таблицы.

Остаток склада — сумма `stock_move.qty_delta`. Остаток счёта — сумма `money_move.amount_delta`. Долг — `open_item` минус неотменённые `allocation`. Отдельной ячейки «текущий остаток» для этого нет. `stock_position` только запирает пару «место + товар» на время проводки.

```mermaid
erDiagram
    organization ||--o{ document : owns
    party ||--o{ purchase_contract : supplies
    party ||--o{ purchase_order : supplies
    party ||--o{ goods_receipt : delivers
    party ||--o{ open_item : settles
    party ||--o{ money_document : paid

    document ||--o| purchase_order : purchase
    document ||--o| goods_receipt : receipt
    document ||--o| goods_issue : issue
    document ||--o| money_document : money
    document ||--o| sale : sale
    document ||--o| document : reversal
    document ||--o{ stock_move : posts
    document ||--o{ money_move : posts
    document ||--o{ open_item : opens
    document ||--o{ allocation : matches

    purchase_contract ||--o{ purchase_order : specifications
    purchase_order ||--|{ purchase_line : lines
    purchase_order ||--o{ shipment : ships
    product ||--o{ purchase_line : ordered
    product_category ||--o{ product : groups
    product_category ||--o{ warehouse : limits

    shipment ||--o{ shipment_wagon : wagons
    shipment |o--o| goods_receipt : posts
    goods_receipt ||--|{ receipt_line : lines
    purchase_line ||--o{ receipt_line : received
    warehouse ||--o{ storage_location : holds
    storage_location ||--o{ stock_move : at
    product ||--o{ stock_move : of

    money_account ||--o{ money_move : balance
    money_document }o--|| money_account : from
    open_item }o--o| purchase_order : about
    allocation }o--|| open_item : debt
    allocation }o--|| open_item : credit
```

Закупка с заполненным `purchase_contract` — спецификация. Закупка без договора — обычный заказ. У обеих один `document` вида `PURCHASE`.

```mermaid
flowchart TD
    plan["Провести закупку PUR"] --> work["В работе"]
    work --> draft["Черновик поставки"]
    work --> receipt["Приёмка заказа RCP"]
    draft --> posted["Провести поставку"]
    posted --> stock["stock_move плюс"]
    posted --> debt["open_item: мы должны"]
    posted --> rcp["Приёмка RCP этой поставки"]
    receipt --> stock
    receipt --> debt
    pay["Оплата MON"] --> cash["money_move минус"]
    pay --> advance["open_item: аванс"]
    advance --> alloc["allocation на выбранный заказ"]
    alloc --> debt
    work --> done["Выполнено"]
    done --> work
```

«Выполнено» на диаграмме только закрывает новые поставки и новые приёмки. Стрелки склада и долга оно не рисует: эти стрелки идут от проведения поставки и от приёмки.
