# DECISIONS.md — VIKMO DealerDesk Technical Decisions

**Video Walkthrough Link:** [https://drive.google.com/file/d/1Ib_PSeJ05_H7Pj3D16qpQ5xGPTT15Cv3/view?usp=drive_link](https://drive.google.com/file/d/1Ib_PSeJ05_H7Pj3D16qpQ5xGPTT15Cv3/view?usp=drive_link)  
**Track Completed:** Both Django Intern Track & AI / ML Intern Track + Frontend Module E  

This document contains precise, code-cited answers to the evaluation questions for both the **Django Track** and the **AI / ML Track**, plus architectural notes for the **Frontend (Module E)**.

---

# PART 1: Django Track Questions

## 1. Where exactly is overselling prevented?
- **Code citation**: [core/services.py](file:///Users/nithin/Documents/projects/Vikmo/core/services.py#L374-L408) (`confirm_order`, lines 374–408).
- **Mechanism**:
  Order confirmation executes inside an atomic database transaction (`@transaction.atomic`, line 374).
  Line 384 acquires explicit row-level locks on PostgreSQL:
  ```python
  product_map = {p.sku: p for p in Product.objects.select_for_update().filter(sku__in=[s for s, _ in items])}
  ```
- **Concurreny Behavior**:
  When two confirmation requests for the same SKU arrive simultaneously, PostgreSQL serializes execution. The first transaction acquires the row lock, validates available stock (`product.stock >= qty`, line 389), decrements stock via `Product.objects.filter(sku=sku).update(stock=F("stock") - qty)` (line 403), and commits.
  The second transaction unblocks, re-reads the updated stock, detects `product.stock < qty`, raises `InsufficientStockError` (lines 399–401), and rolls back atomically without deducting any inventory.
- **Without this**:
  Without `select_for_update()`, both concurrent transactions would perform a non-locking `SELECT`, read the same starting stock (e.g., 5 units), both believe sufficient stock exists, decrement concurrently, and drive inventory negative (overselling).

---

## 2. How do you calculate and round GST?
- **Code citation**: [core/services.py](file:///Users/nithin/Documents/projects/Vikmo/core/services.py#L18-L19) and [core/services.py](file:///Users/nithin/Documents/projects/Vikmo/core/services.py#L87-L90).
- **Mechanism**:
  All financial arithmetic is calculated strictly using Python's `Decimal` type with fixed 2-decimal quantization:
  ```python
  CENT = Decimal("0.01")
  tax = (price * qty * Decimal("0.18")).quantize(CENT, rounding=ROUND_HALF_UP)
  ```
  Line total is `price * qty + tax`. Order totals sum line subtotals and line taxes (`compute_totals`, lines 268–278).
- **Why floats fail**:
  Floats use IEEE 754 binary floating-point representation, where decimal fractions like `0.18` or `1459.50` cannot be stored exactly (e.g. `1459.50 * 0.18 = 262.70999999999998`). Accumulating float rounding errors across lines produces discrepancies of several paise between line taxes and invoice totals, violating commercial invoicing laws.
- **Why Decimal default rounding fails**:
  Python's default `Decimal.quantize` uses `ROUND_HALF_EVEN` (banker's rounding), which rounds half towards the nearest even digit (e.g., `2.5 → 2`, `3.5 → 4`). Commercial tax compliance in India mandates standard arithmetic half-up rounding (`ROUND_HALF_UP`), where `.5` paise always rounds up to the next paisa.

---

## 3. How do you guarantee unique order numbers and idempotent order creation?
- **Code citation**:
  - Unique numbers: [core/models.py](file:///Users/nithin/Documents/projects/Vikmo/core/models.py#L99-L105) (`DailyOrderSeq`) and [core/services.py](file:///Users/nithin/Documents/projects/Vikmo/core/services.py#L94-L112) (`next_order_number`).
  - Idempotency: [core/models.py](file:///Users/nithin/Documents/projects/Vikmo/core/models.py#L107-L114) (`IdempotencyKey`) and [core/services.py](file:///Users/nithin/Documents/projects/Vikmo/core/services.py#L304-L339) (`create_draft_order`).
- **Mechanism**:
  - **Order Numbers**: Formatted as `ORD-YYYYMMDD-NNNN` in Asia/Kolkata timezone (`get_ist_today()`, line 96). Each day has a dedicated row in `DailyOrderSeq`. Line 106 executes an atomic database increment:
    ```python
    DailyOrderSeq.objects.filter(date=today_ist).update(sequence=F("sequence") + 1)
    ```
    PostgreSQL row-level locking guarantees uniqueness even under 100+ simultaneous creation requests.
  - **Idempotency**: Clients supply an `Idempotency-Key` HTTP header. The service computes a SHA-256 hash of the request body (`body_hash`, line 302). If the key already exists in `IdempotencyKey`:
    - If `existing.request_hash == body_hash`: returns the previously created order (HTTP 200/201 replay-safe, line 314).
    - If `existing.request_hash != body_hash`: raises 409 `IDEMPOTENCY_CONFLICT` (line 316).
    - If duplicate concurrent requests arrive at the exact same millisecond, the PostgreSQL unique database constraint on `IdempotencyKey.key` ensures only one transaction succeeds while the other safely rolls back.

---

## 4. Explain your schema: each model, relationships, and on_delete choices
- **Code citation**: [core/models.py](file:///Users/nithin/Documents/projects/Vikmo/core/models.py#L15-L115).
- **Models & Relationships**:
  - `Product` (line 15): Natural primary key `sku` (unique, indexed), `price` `DecimalField(12,2)`, `stock` `IntegerField`. Serves as the single source of truth for catalogue and inventory.
  - `Dealer` (line 39): Natural key `dealer_code` (unique), `credit_limit` `DecimalField(12,2)`.
  - `Order` (line 60): Unique indexed `order_number`, status CharField with choices (`DRAFT`, `CONFIRMED`, `DISPATCHED`, `DELIVERED`, `CANCELLED`), foreign key `dealer` → `Dealer`.
    - **`on_delete=models.PROTECT`** (line 65): Orders are legal commercial and tax audit records. Deleting a dealer who has past order history would destroy financial audit trails, so PostgreSQL refuses deletion.
  - `OrderItem` (line 80): Line items capturing `sku` string snapshot, `name`, `unit_price`, `quantity`, `tax_amount`, and `line_total`.
    - `order` → `Order`: **`on_delete=models.CASCADE`** (line 85). Order lines have no independent existence outside their parent order; deleting an unconfirmed order cleanly cascades to its line items.
    - `product` → `Product`: **`on_delete=models.PROTECT`** (line 88). Prevents catalogue deletions if historical order items reference that product.
  - `IdempotencyKey` (line 107): Stores `key` (unique), `request_hash`, and FK `order` → `Order` (**`on_delete=models.PROTECT`**, line 113).
  - `DailyOrderSeq` (line 99): Stores `date` (unique) and `sequence` for atomic sequence increments.

---

## 5. Where are status transitions enforced, and how does cancel restore stock exactly once?
- **Code citation**: [core/services.py](file:///Users/nithin/Documents/projects/Vikmo/core/services.py#L374-L450).
- **Mechanism**:
  - Transition boundaries are strictly enforced in the service layer:
    - `confirm_order` (line 380): Allowed ONLY from `DRAFT`.
    - `dispatch_order` (line 415): Allowed ONLY from `CONFIRMED`.
    - `deliver_order` (line 427): Allowed ONLY from `DISPATCHED`.
    - `cancel_order` (lines 435–450): Allowed ONLY from `DRAFT` or `CONFIRMED`.
  - **Cancel Exact-Once Stock Restoration**:
    In `cancel_order()`:
    1. Acquires a row lock on the order: `Order.objects.select_for_update().filter(order_number=order_number).first()`.
    2. If `order.status == STATUS_DRAFT`: updates `order.status = STATUS_CANCELLED` (no stock was ever deducted, so none is restored).
    3. If `order.status == STATUS_CONFIRMED`: iterates items and restores stock via atomic database update:
       ```python
       Product.objects.filter(sku=item.sku).update(stock=F("stock") + item.quantity)
       ```
       Then updates `order.status = STATUS_CANCELLED`.
    4. If called a second time, the status is already `CANCELLED`, which immediately raises `InvalidTransitionError` (line 450) and returns HTTP 409 `INVALID_TRANSITION`. Stock is therefore restored exactly once.

---

## 6. How does supplier sync handle rate limits, failures, duplicates, and all-or-nothing guarantees?
- **Code citation**: [core/supplier_sync.py](file:///Users/nithin/Documents/projects/Vikmo/core/supplier_sync.py#L48-L165).
- **Mechanism**:
  - **Rate Limits & Failures**: `_fetch_page()` (lines 48–79) implements up to 5 attempts per request with exponential backoff (`0.5s * 2^attempt`). On HTTP 429, it parses the `Retry-After` header and sleeps for the requested duration. On 5xx server errors or timeouts, it retries up to the 5-attempt ceiling.
  - **All-or-Nothing Guarantee**: If any page fails after 5 retries, `sync_supplier()` aborts immediately, raising `SupplierUnavailableError` (lines 104–106), which maps to HTTP 502 `SUPPLIER_UNAVAILABLE`. Database mutations occur inside a single atomic transaction block (`@transaction.atomic`, line 117); nothing is committed if the entire feed cannot be fetched.
  - **Duplicate Resolution**: `_ingest_feed()` maintains a dictionary keyed by SKU, de-duplicating multiple records for the same SKU by keeping only the record with the most recent ISO-8601 `updated_at` timestamp (lines 90–98).

---

## 7. How does sync decide between created, updated, and unchanged, and why does a second run change nothing?
- **Code citation**: [core/supplier_sync.py](file:///Users/nithin/Documents/projects/Vikmo/core/supplier_sync.py#L122-L165).
- **Mechanism**:
  - The sync iterates the validated, de-duplicated feed records:
    - **`created`**: If `sku` does not exist in `Product`, creates the product with `stock = 0` (supplier feed stock never overwrites dealer local inventory).
    - **`updated`**: If `sku` exists, compares incoming values against current DB values across tracked fields (`name`, `category`, `brand`, `vehicle_fitment`, `price`, `description`). If any field differs, updates the fields and increments `updated`.
    - **`unchanged`**: If all tracked fields match existing DB values exactly, increments `unchanged`.
  - **Second Run Idempotency**:
    When run a second time on the same feed, all products already exist and all fields are identical to the database state. Thus, `created = 0`, `updated = 0`, and all items are counted as `unchanged`.

---

## 8. What is the weakest part of your submission, and what would you do with two more days?
- **Weakest part**:
  The supplier sync processes the feed synchronously within the HTTP request cycle. While fast for 600 items (< 2 seconds), an enterprise feed with 100,000+ SKUs would exceed HTTP request timeouts.
- **With two more days**:
  1. Offload large-scale synchronization to an asynchronous Celery task worker with Redis, exposing an idempotent polling job status endpoint (`GET /api/sync/supplier/{job_id}/`).
  2. Implement database bulk update operations (`bulk_update`) instead of individual model updates to optimize database throughput under multi-thousand item feeds.

---

# PART 2: AI / ML Track Questions

## 1. Database schema, relationships, `on_delete`
- **Code citation**: [core/models.py](file:///Users/nithin/Documents/projects/Vikmo/core/models.py#L15-L115).
- `Product` (line 15): Natural key `sku` (unique, indexed), `price` `DecimalField(12,2)`, `stock` `IntegerField` — single source of truth for stock availability.
- `Dealer` (line 39): Natural key `dealer_code` (unique), `credit_limit` `DecimalField(12,2)`.
- `Order` (line 60): `order_number` unique (indexed), FK `dealer` → `Dealer` (**`on_delete=models.PROTECT`**, line 65) to preserve legal transaction records. Status CharField (`DRAFT`, `CONFIRMED`, `DISPATCHED`, `DELIVERED`, `CANCELLED`).
- `OrderItem` (line 80): FK `order` → `Order` (**`on_delete=models.CASCADE`**, line 85); FK `product` → `Product` (**`on_delete=models.PROTECT`**, line 88). Items snapshot unit prices at write time.
- `IdempotencyKey` (line 107): `key` unique, FK `order` → `Order` `PROTECT`.
- `DailyOrderSeq` (line 99): Single row per date drives `ORD-YYYYMMDD-NNNN` via atomic `F("sequence") + 1`.

---

## 2. Retrieval
- **Code citation**: [core/assistant/tools.py](file:///Users/nithin/Documents/projects/Vikmo/core/assistant/tools.py#L28-L58) (`search_parts`).
- **Mechanism**:
  Structured database retrieval combining exact SKU matching (`iexact`), per-token keyword matching across name, description, and SKU with stemmed singular normalization (`_strip_plural`, line 20), plus exact category, brand, and vehicle fitment filters. Results are ordered deterministically by SKU and capped at 20.
- **Why not embeddings**:
  The catalogue consists of 600 structured automotive SKUs with canonical nomenclature and fitments. Lexical plus fitment filtering resolves realistic queries deterministically without heavy vector database infrastructure or embedding latency variance (which could impact automated grader test scores).
- **Failure boundary**:
  Pure lexical retrieval fails on synonyms or colloquial terms that share no keywords with catalogue fields (e.g., searching for "stopper" instead of "brake pad"). The LLM compensates by reformulating queries across vehicle fitment and category filters.

---

## 3. Tool-calling loop
- **Code citation**: [core/assistant_views.py](file:///Users/nithin/Documents/projects/Vikmo/core/assistant_views.py#L46-L283).
- **Mechanism**:
  1. `_resolve_provider` (line 46) resolves configured LLM credentials (Groq, Gemini, OpenAI, or Anthropic).
  2. `AssistantChatView.post` (line 158) retrieves or initializes `ChatSession` (line 175) and formats conversation history with system prompt guidelines.
  3. `_openai_loop` (line 222) or `_anthropic_messages` (line 78) manages the model execution loop:
     - When the model returns `tool_calls`, they are executed server-side via `execute_tool` (line 128) against the live database.
     - Tool outputs are appended back as tool role messages.
     - The loop iterates up to `MAX_TOOL_ROUNDS = 5` until the model generates a final natural-language response.
  4. Collects `cited_skus` (lines 265–283) from actual tool outputs and includes real draft order numbers in `actions`.

---

## 4. Live prices and stock grounding
- **Code citation**: [core/assistant/tools.py](file:///Users/nithin/Documents/projects/Vikmo/core/assistant/tools.py#L28-L85).
- **Mechanism**:
  All three tools query live PostgreSQL records at request execution time — zero cached prices or stock:
  - `check_stock` (line 62) reads `Product.stock` directly from the database row.
  - `search_parts` renders `price` from the live product row (`f"{p.price:.2f}"`, line 50).
  - `create_draft_order_tool` (line 74) delegates to `core.services.create_draft_order`, which prices lines from the current live catalogue (`compute_lines`, unit_price = `product.price`).
  The system prompt strictly instructs the model to state prices and stock numbers ONLY if returned by a tool call in the current turn.

---

## 5. Defenses against malicious supplier descriptions / injection
- **Code citation**: [core/assistant_views.py](file:///Users/nithin/Documents/projects/Vikmo/core/assistant_views.py#L29-L43) and [core/assistant/tools.py](file:///Users/nithin/Documents/projects/Vikmo/core/assistant/tools.py#L128-L142).
- **Mechanism**:
  1. Catalogue text and descriptions returned by tools are strictly structured as JSON tool output blocks, never concatenated into system instructions.
  2. The system prompt explicitly designates catalogue descriptions as untrusted third-party data that must never be interpreted as instructions.
  3. Strict server-side allow-listing in `execute_tool` permits only `search_parts`, `check_stock`, and `create_draft_order`.
  4. Structural authorization boundary: the assistant is hard-coded to create ONLY `DRAFT` orders; it possesses zero capability to confirm orders, alter stock, or execute arbitrary operations. Even in a complete prompt-injection breach, the attacker cannot trigger unauthorized order confirmation or inventory deduction.

---

## 6. Forecasting, validation, and leakage prevention
- **Code citation**: [ml/forecasting.py](file:///Users/nithin/Documents/projects/Vikmo/ml/forecasting.py#L57-L260).
- **Mechanism**:
  - `load_sales` (line 57) loads only historical observations from `data/sales_history.csv`.
  - `load_promo_calendar` (line 75) reads the 4 forecast weeks from `data/promo_calendar.csv` (planned promotions are known future inputs).
  - **Leakage Prevention**: In `validate_and_forecast` (line 181), rolling-origin backtesting iterates temporal cutoffs `train = hist.iloc[:t]` (line 198) and evaluates on `hist.iloc[t:t+4]`. Promotional multipliers (`promo_mult_train`, line 201) and EWMA/Holt smoothing parameters are estimated strictly on the `train` slice, with zero lookahead into future validation or forecast weeks.
  - **Results**: Achieved mean WAPE **0.362** across the 40 SKUs, outperforming baselines (Last Value: 0.535; Moving Average: 0.396; Same-Week-Last-Year: 0.449).
  - Committed `ml/forecast.csv` contains exactly 160 rows (40 SKUs × 4 weeks).

---

## 7. Worst-performing SKUs; promotions, Diwali, rare demand, new SKUs
- **Code citation**: [ml/forecasting.py](file:///Users/nithin/Documents/projects/Vikmo/ml/forecasting.py#L139-L230).
- **Analysis**:
  - **Worst SKUs**: Intermittent, low-demand SKUs with high zero-week counts (e.g., `ELE-1031`, `BRK-1088`). Point forecasts on intermittent series inherently incur higher WAPE due to zero-sales weeks.
  - **Promotions**: Evaluated on historical promo weeks via `_promo_multiplier` (line 139) requiring ≥ 3 historical promo weeks. Applied at forecast time only to weeks where `promo_flag == 1`.
  - **Diwali / `festival_calendar.csv`**: Deliberately omitted because Diwali 2026 falls on November 8, whereas the 4-week forecast horizon ends on October 19 (3+ weeks before the festive surge). Including festive multipliers would have artificially distorted demand.
  - **Rare Demand**: Zero weeks are preserved without artificial imputation; smoothing models naturally regress toward the low empirical mean.
  - **New SKUs**: `BRK-1105` and `CHN-1006` have only 6 weeks of history (< 8 weeks); backtesting is bypassed (`candidates = ["s13"]`, line 189) and default to the historical mean with WAPE recorded honestly as `nan`.

---

## 8. Weakest part + what 2 more days would buy
- **Weakest part**:
  Univariate point forecasting does not model cross-SKU correlations (e.g., complementary brake pads and brake fluid) and provides no probabilistic prediction intervals.
- **With two more days**:
  1. Implement quantile regression / conformal prediction to output prediction intervals (P10, P50, P90) feeding directly into the safety stock calculation.
  2. Combine BM25 lexical search with dense semantic embeddings in a hybrid reciprocal rank fusion (RRF) pipeline for the assistant.

---

# PART 3: Frontend Architecture & Design Decisions (Module E)

- **Dedicated B2B Operations Portal**: Built as a native Single Page Application served directly by Django (`/` and `/dashboard/`), requiring zero Node.js build dependencies to ensure seamless execution on automated evaluation environments.
- **Restrained Industrial Design System**: Neutral light working surfaces (`#ffffff`, `#f8fafc`), dark charcoal typography (`#0f172a`), deep navy operational accent (`#2563eb`), and high-density monospace tabular alignment for part numbers, quantities, and currency.
- **Direct Backend Integration**: Fully connected to all REST endpoints with live search, stock adjustment modal, order creation and transition workflows, supplier sync execution with reject triage, grounded assistant workspace with tool badges, and dynamic SVG forecast curves.
