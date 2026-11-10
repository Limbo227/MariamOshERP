# ADR-0002 — Core supply, receipt and production
Date: 2026-11-10. Business scope confirmed by owner; schema details proposed.

## Decision
Bring direct packaged production, automatic one-sack consumption, manual wheat issues, actual RAW locations and minimal order-based supplier settlements into the first core. Full sales, treasury, costing and integrations remain later.

Use PurchaseOrder as the supply agreement with optional contract evidence, Shipment as delivery batch and TransportUnit for wagons/trucks. Preserve partial receipts and order amendments. A separate mandatory contract lifecycle would add paperwork not required by this scope.

Reuse the existing clean directory as one repository root named Mariam-OSH-ERP (application/project ebb-erp). Keep docs with code. This replaces the prior nested-repository suggestion while preserving isolation from ERPNext.

## Why
The owner clarified that finished bags are the production fact, one matching sack is consumed per bag, wheat mixes and can be manually deducted, and supplier debt starts when an order is confirmed. Deferring these behaviours would leave the requested core incomplete.

## Consequences
Production confirmation has two stock effects per output line and needs transactional rollback/concurrency tests. Raw grain deductions stay separate; output is not automatically a mass balance. Price revisions change debt without rewriting physical receipts. Quality release is a manual record. Incoming-lot history is preserved without invented exact depletion after mixing.

