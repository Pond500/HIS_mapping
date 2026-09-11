# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Converts Thai hospital information system (HIS) health-check data (occupational health / อาชีวอนามัย) into a fixed 45-column "result template". HIS data is usually Long/EAV (one row per lab result); the template is Wide (one row per person + visit date). Much of the code, comments, UI text and error messages are in Thai. Keep that as it is.

**Direction:** this is being rebuilt as a POC that takes in any CSV/XLSX layout through a LangGraph multi-agent pipeline (OpenRouter, cheap models) with human review. The agreed requirements, decisions (D1–D16) and the 3-week plan are in [docs/requirements.md](docs/requirements.md). Read it before making design changes. The core rule is that every value is either correct or flagged for a human, so nothing wrong is saved silently.

## Commands

```bash
pip install -r requirements.txt            # pandas pinned to 1.3.5 with numpy<2
docker compose up -d                       # Postgres 15 on :5432 (db/user/pass: his_mapping / his_admin / his_secret_2026)
uvicorn app.main:app --reload              # web app at http://localhost:8000 (run from repo root)
python3 main.py                            # standalone CLI pipeline: sample data → output_result.xlsx (no DB needed)
```

`DATABASE_URL` overrides the default Postgres connection string in `app/database.py`.

There is no test framework, linter or build step. `test_pipeline.py`, `test_pipeline2.py` and `test_validation.py` are ad-hoc scripts that run against the live Postgres DB and print results (`python3 test_validation.py`). They write real rows, using `upload_id` 999/888.

## Architecture

There are two separate code paths that share `mapping_config.py`:

1. **Legacy CLI pipeline**: `main.py` → `his_to_template.py` (`run_pipeline`: load → map lab names → pivot to wide → transform values, e.g. Normal→1/Abnormal→2 and CE→BE dates → export Excel with openpyxl). Input comes from the in-memory fixtures in `sample_his_data.py`.

2. **FastAPI web app** (`app/`): upload CSV/XLSX → map → upsert into Postgres → dashboard/export. The web app does **not** use `his_to_template.py`. It reimplements the logic in `app/routes/upload.py`:
   - `detect_file_format` decides long vs wide from column names. Each XLSX sheet is detected and processed on its own.
   - `convert_long_to_wide` normalizes HIS column aliases (cid/pid/vstdate/…), maps `lab_name` to a template column, splits BP values like `"120/80"` into systolic and diastolic, applies `unit_factor`, and pivots on (cid, visit_date).
   - `process_wide_dataframe` maps each column to a DB column in this order: `TEMPLATE_TO_DB` exact match (Thai template headers → English DB names), then a direct DB column name, then a DB mapping or fuzzy match. It validates values per row (numeric, categorical 1/2, dates where a year > 2500 is treated as Buddhist Era) and **upserts** on `(cid, visit_date)`. Row errors are collected as Thai messages and are not raised.
   - Lab-name mapping goes through `get_mapped_col`: an exact lowercase match against the `lab_mappings` table, then a RapidFuzz `token_sort_ratio` fallback at ≥ 85.

### Where mappings live

- `mapping_config.py`: `TEMPLATE_COLUMNS` (the exact column order of the output template, which must match `result_template_v1.1.xlsx`), `LAB_NAME_TO_TEMPLATE`, `NORMAL_ABNORMAL_MAP`, `CLINICAL_CATEGORICAL_IN_LONG`, and related constants.
- `lab_mappings` DB table: `init_db()` seeds it from `LAB_NAME_TO_TEMPLATE` only when the table is empty. After that, the web app reads only the DB. Edits to the config dict won't reach an existing DB. Use the `/api/mappings` CRUD routes (`app/routes/mapping.py`) or clear the table.
- `app/routes/upload.py` has its own `TEMPLATE_TO_DB`, `NUMERIC_FIELDS` and `CATEGORICAL_FIELDS`.

### Schema is defined in three places

Adding or renaming a template field means keeping all of these in sync:
- `init.sql`, which runs only on first Postgres volume creation.
- The SQLAlchemy models in `app/database.py`, including `Employee.to_dict()`. `create_all` builds missing tables but never alters existing ones.
- `TEMPLATE_TO_DB` and the field sets in `upload.py`, `TEMPLATE_COLUMNS` in `mapping_config.py`, and the Excel export in `app/routes/dashboard.py`.

### Frontend

A single page, `app/templates/index.html`, with vanilla JS and `app/static/css/style.css`. It calls the JSON API: `/api/upload`, `/api/stats`, `/api/employees`, `/api/upload-logs`, `/api/export`, `/api/mappings`.
