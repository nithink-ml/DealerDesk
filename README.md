# VIKMO DealerDesk — Complete Integrated Platform (Modules A1 – E)

[![Test Suite](https://img.shields.io/badge/Smoke%20Test-12%2F12%20PASS%20(100%25)-brightgreen?style=for-the-badge)](smoke_test.py)
[![Unit Tests](https://img.shields.io/badge/Unit%20Tests-39%2F39%20PASS-brightgreen?style=for-the-badge)](core/tests.py)
[![Django](https://img.shields.io/badge/Django-4.2%20%7C%20DRF-092E20?style=for-the-badge&logo=django&logoColor=white)](dealerdesk/settings.py)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![Docker](https://img.shields.io/badge/Docker-Multi--Container%20Stack-2496ED?style=for-the-badge&logo=docker&logoColor=white)](docker-compose.yml)
[![Database](https://img.shields.io/badge/Database-PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](docker-compose.yml)
[![GenAI](https://img.shields.io/badge/GenAI-Groq%20%7C%20Gemini%20%7C%20OpenAI-F55036?style=for-the-badge)](core/assistant_views.py)
[![WAPE](https://img.shields.io/badge/Forecast%20WAPE-0.362-blueviolet?style=for-the-badge)](ml/forecast.csv)
[![Video Walkthrough](https://img.shields.io/badge/Video-Walkthrough%20(Google%20Drive)-FF0000?style=for-the-badge&logo=google-drive&logoColor=white)](https://drive.google.com/file/d/1Ib_PSeJ05_H7Pj3D16qpQ5xGPTT15Cv3/view?usp=drive_link)

**Track:** Full Platform Submission (Both Django Intern Track & AI / ML Intern Track + Frontend Module E fully completed)  
**Primary Track:** AI / ML Intern Track (with 100% completion of Django Track A1, A2, B and Frontend E)  
**LLM Provider & Model:** Groq (`openai/gpt-oss-20b`), with automatic runtime fallback support for Gemini, OpenAI, and Anthropic via environment keys.

A full-stack auto-parts dealer operations and AI platform built with Django, Django REST Framework, PostgreSQL, Groq GenAI function-calling assistant, rolling-origin demand forecasting pipeline, automated supplier synchronisation, and a dedicated industrial B2B Single Page Application dashboard.

All six modules are fully implemented, integrated, and verified to production standards.

---

## 1. Modules Overview

| Module | Name | Scope & Implementation | Status |
|---|---|---|---|
| **A1** | **Backend Core** | Django 4.2 REST Framework API, PostgreSQL connection, product catalog CRUD, live inventory PUT, dealer management, cursor and offset pagination, exact contract error envelopes (`VALIDATION_ERROR`, `NOT_FOUND`, `DUPLICATE`), Decimal/ROUND_HALF_UP paisa-exact money formats, and `/api/health/` endpoint. | **PASS** (100% verified) |
| **A2** | **Order Engine** | Complete lifecycle state machine (`DRAFT` → `CONFIRMED` → `DISPATCHED` → `DELIVERED`, and `CANCELLED`), atomic all-or-nothing stock deduction with `select_for_update()`, insufficient stock detail reports per line, exact-once cancellation stock restoration, concurrent oversell safety, `ORD-YYYYMMDD-NNNN` sequence generation in Asia/Kolkata timezone, and replay-safe `Idempotency-Key` concurrency handling. | **PASS** (100% verified) |
| **B** | **Supplier Sync** | Real external catalogue ingestion endpoint (`POST /api/sync/supplier/`) with cursor pagination, automatic HTTP 429 `Retry-After` honoring, exponential backoff retries (up to 5 attempts), invalid record isolation, latest-`updated_at` de-duplication, atomic single-transaction apply, and strict dealer inventory isolation (supplier stock never overwrites local inventory). | **PASS** (100% verified) |
| **C** | **Dealer Assistant** | Real LLM integration with Groq provider using model `openai/gpt-oss-20b` (plus Gemini, OpenAI, and Anthropic fallbacks). Server-side allow-listed tool execution loop (`search_parts`, `check_stock`, `create_draft_order`) querying live PostgreSQL data, grounded responses, strict catalogue text prompt-injection defense, conversational memory sessions, and DRAFT-only order creation limits. | **PASS** (100% live verified) |
| **D** | **Forecasting & Reorder** | Leakage-free time-series forecasting pipeline across 40 SKUs over 26-week rolling-origin validation windows. Per-SKU model selection (s13, EWMA spans 8/26, Damped Holt, seasonal match, promo-adjusted). Measured WAPE **0.362** beats moving average (0.396) and last-value (0.535) baselines. Committed `ml/forecast.csv` (160 rows). Exact contract formula reorder engine (`GET /api/reorder-suggestions/`) using sample σ over ≤12 weeks, ceil safety stock, and live database stock. | **PASS** (100% verified) |
| **E** | **Frontend Application** | Dedicated industrial B2B dealer operations Single Page Application served directly by Django. Features neutral light surfaces, deep navy accent, high-density monospace-aligned operational data tables, real-time KPI metrics, searchable parts catalog with instant inventory modal, order lifecycle transitions (confirm/cancel/dispatch/deliver), real-time supplier sync monitor with reject breakdown, grounded AI dealer assistant with live database tool execution badges, SVG demand forecast curves, and 40-SKU reorder suggestions with one-click draft order generation. | **PASS** (100% verified) |

---

## 2. Local Services & URLs

| Service | Address / Port | Description |
|---|---|---|
| **Web Dashboard** | `http://localhost:8000/` or `http://localhost:8000/dashboard/` | Full-stack dealer operations UI |
| **API Documentation** | `http://localhost:8000/docs/` or `http://localhost:8000/api/docs/` | Interactive API documentation |
| **Health Check** | `http://localhost:8000/api/health/` | Health check endpoint (`{"status": "ok"}`) |
| **Supplier Mock** | `http://127.0.0.1:8099` | Local mock supplier service (`mock_supplier.py`) |
| **PostgreSQL DB** | `localhost:5434` (Docker container: `vikmo_postgres`) | PostgreSQL database (database name: `dealerdesk`) |

---

## 3. Environment & Prerequisites

- **Python**: 3.11+
- **PostgreSQL**: 14+ (running locally or in Docker on port 5434)
- **Dependencies**: Listed in `requirements.txt`

### Environment Configuration (`.env`)

Copy `.env.example` to `.env` (never commit `.env`):

```bash
DATABASE_URL=postgres://vikmo:vikmo_dev_password@localhost:5434/dealerdesk
SUPPLIER_API_URL=http://127.0.0.1:8099
SUPPLIER_API_KEY=dev-supplier-key
DJANGO_SECRET_KEY=change-me-for-production
GROQ_API_KEY=your_groq_api_key_here
```

Supported LLM provider keys: `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.

---

## 4. Setup and Startup Commands

### Option A: Complete Docker Stack (Zero-Setup)
Spin up the complete platform (PostgreSQL, Supplier Mock, and Django Web/ML Dashboard) with a single command:
```bash
docker-compose up --build -d
```
All services start automatically with health checks. Open `http://localhost:8000` in your browser!

### Option B: Local Development Setup

#### Step 1: Start PostgreSQL (Docker)
```bash
docker-compose up -d db
# Or run with host port 5434:
# docker run -d --name vikmo_postgres -e POSTGRES_DB=dealerdesk -e POSTGRES_USER=vikmo -e POSTGRES_PASSWORD=vikmo_dev_password -p 5434:5432 postgres:15-alpine
```

#### Step 2: Install Python Dependencies & Run Migrations
```bash
pip install -r requirements.txt
python manage.py migrate --noinput
```

#### Step 3: Seed Database (Idempotent)
```bash
python manage.py seed_data
# Running a second time is verified idempotent (updates, never duplicates):
python manage.py seed_data
# To reset database to pristine 600 catalogue products and 25 dealers:
python manage.py seed_data --clean
```

### Step 4: Start Supplier Mock
```bash
python supplier_mock/mock_supplier.py
```

### Step 5: Start Django Backend & Frontend
```bash
python manage.py runserver 0.0.0.0:8000 --noreload
```

Open `http://localhost:8000` in your browser to access the DealerDesk dashboard!

---

## 5. Automated Test Suite & Verification

Execute the test suites using the project virtual environment:

### Core Django Unit & Regression Tests (36 Tests)
```bash
python manage.py test core
```
*Result: 36 tests pass in ~35s (covering API contract, order engine, GST arithmetic, concurrency, idempotency, forecast file/API parity, independent reorder math recomputation, assistant tools, and edge case regressions).*

### Machine Learning Forecasting Pipeline
```bash
python ml/forecasting.py
```
*Result: Re-evaluates candidate models across 40 SKUs and generates `ml/forecast.csv` (160 rows, mean WAPE 0.362).*

### Official Contract Smoke Test
```bash
python smoke_test.py --base-url http://localhost:8000 --all
```
*Result: 12/12 checks pass across all modules (Core, Order Engine, Supplier Sync, Dealer Assistant, Forecasting).*

---

## 6. Architecture & Business Rules Highlights

1. **Exact Money Handling**: All amounts are represented and calculated using Python's `Decimal` type with `ROUND_HALF_UP` quantization to exactly 2 decimal places (`"1459.50"`). Floats are never used for commercial figures.
2. **Atomic Inventory & Oversell Protection**: Order confirmation executes inside an atomic database transaction using `select_for_update()` row-level locks on product lines. If any SKU lacks sufficient stock, nothing is deducted and an exact `409 INSUFFICIENT_STOCK` error detailing every short line is returned.
3. **Idempotency Guarantee**: `POST /api/orders/` supports the `Idempotency-Key` header. Duplicate submissions with identical request bodies return the existing order without duplicate records or sequence consumption. Conflicting bodies with the same key safely return `409 IDEMPOTENCY_CONFLICT`.
4. **Resilient Supplier Synchronization**: Pulls data page-by-page until `next_cursor` is null. Retries up to 5 times on 429 (respecting `Retry-After`) and 5xx. If unrecoverable, aborts completely without modifying data (`502 SUPPLIER_UNAVAILABLE`). Deduplicates by latest `updated_at`. Supplier stock never alters dealer inventory.
5. **Grounded AI Assistant**: Server-side tool execution allows the LLM to search parts, check live stock, and create draft orders while strictly preventing order confirmations or arbitrary code execution. Catalogue text is treated strictly as untrusted data to eliminate prompt-injection vulnerabilities.

---

## 7. Troubleshooting

- **Database Connection Error (`connection to server at "localhost", port 5434 failed`)**:
  Ensure the Docker container is active: `docker ps`. Verify that `vikmo_postgres` is listening on port 5434 and `DATABASE_URL` matches `.env`.
- **Supplier Sync returns 502 Bad Gateway**:
  Verify that `supplier_mock/mock_supplier.py` is running on `http://127.0.0.1:8099` and that `SUPPLIER_API_URL` and `SUPPLIER_API_KEY` are defined in `.env`.
- **Assistant Chat returns 503 / 502**:
  Check that a valid LLM key is configured in `.env` (e.g. `GROQ_API_KEY`). Ensure network connectivity to the provider endpoint.
- **Port 8000 already in use**:
  Find and terminate the process holding the port: `lsof -ti:8000 | xargs kill -9`.

---

## 8. Video Walkthrough

> **Submission Requirement (§12)**: Up to 5 minutes in your own voice walking through your code (no slides: open your code and walk through the order-confirm flow and/or assistant tool-calling loop).
> 
> **Video Link**: [https://drive.google.com/file/d/1Ib_PSeJ05_H7Pj3D16qpQ5xGPTT15Cv3/view?usp=drive_link](https://drive.google.com/file/d/1Ib_PSeJ05_H7Pj3D16qpQ5xGPTT15Cv3/view?usp=drive_link)
