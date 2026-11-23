# CBN Composite Indices — Build Plan & Status

Professional Flask web app that computes five CBN composite indices
(**BCI, CCI, HFCI, IPI, LMCI**) from uploaded data, with async Celery
processing, an interactive HTMX UI, and Excel/CSV/JSON exports.

> **Build discipline:** build the full feature set first. **All validation
> and debugging happens at the END**, not between phases.

## Status at a glance

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Scaffold & auth | ✅ Done |
| 1 | Indices blueprint + navigation | ✅ Code complete |
| 2 | Upload handling | ✅ Code complete |
| 3 | Celery task + calculators | ✅ Code complete |
| 4 | HTMX runs dashboard | ✅ Code complete |
| 5 | Run detail + Plotly | ✅ Code complete |
| 6 | Exports (CSV/Excel/JSON) | ✅ Code complete |
| 7 | Validation & debugging | ✅ Done — see summary below |
| 8 | Polish & docs | ✅ Docs done; UI polish optional |

**Validation has been run.** Stack was brought up, bugs were fixed, the QA
harness passed, pytest passed, and all five indices were processed end-to-end.
See the summary below for what was fixed and verified.

---

## Stack

- Flask + Jinja2 + HTMX 2 + Tailwind CSS (CDN) + Plotly.js (CDN).
- PostgreSQL 16 via Docker; Redis 7 for Celery broker (`/0`) + result backend (`/1`).
- Celery worker for asynchronous index computation.
- Flask-Login (email + username + password; no verification, no reset, single role).
- Alembic handwritten migrations (`migrations/`) — the schema source of truth.
  No Flask-Migrate, no ORM autogeneration, no `create_all()`.
- Docker Compose runs a one-shot `migrate` service before `web` and `worker`.
- Uploads/results stored on Docker volumes via local filesystem keys.

## Configuration

- `.env` externalises `SECRET_KEY`, `DATABASE_URL`, `CELERY_BROKER_URL`,
  `CELERY_RESULT_BACKEND`, `MAX_CONTENT_LENGTH`.
- Index configurations live in Python (`app/indices/configs.py`), not a UI editor.
- Target deployment: local Docker Compose.

---

## Phases

### Phase 0 — Scaffold & Auth (DONE)
- Docker Compose, Dockerfile, requirements, config, app factory, extensions.
- Redis config + persistence; externalised Celery URLs.
- Alembic env + `0001_initial_schema` (`users`, `index_runs`).
- `User` / `IndexRun` models with relationships, constraints, password hashing.
- Full auth: signup, login, logout, CSRF, uniqueness, safe redirects.
- Auth templates, base shell nav, flash messages.
- Auth tests (`tests/conftest.py`, `tests/test_auth.py`).
- Workspace root redirects anonymous users to login.

### Phase 1 — Indices blueprint + navigation (DONE)
- `app/indices/__init__.py` with `indices_bp`:
  - `GET  /indices/` (landing / catalogue)
  - `GET  /indices/upload` (upload form)
  - `POST /indices/upload` (handle file, create run, dispatch Celery)
  - `GET  /indices/runs` (HTMX dashboard)
  - `GET  /indices/runs/fragment` (HTMX polling fragment)
  - `GET  /indices/<int:run_id>` (run detail + Plotly)
  - `GET  /indices/<int:run_id>/status` (JSON status, for polling)
  - `GET  /indices/<int:run_id>/download/<fmt>` (csv | xlsx | json)
- Registered in `app/__init__.py`; workspace root redirects to `indices.landing`.
- Nav entries added to `base.html`.

### Phase 2 — Upload handling (DONE)
- Safe extension check + uuid key; file saved to the `uploads/` volume.
- Creates `IndexRun(status="queued")`; dispatches `compute_indices.delay(run.id)`.
- `IndexRun` already carries `result_key`, `result_metadata`, `error_message`,
  `started_at`, `finished_at` in both the model and `0001_initial_schema`.

### Phase 3 — Celery task + calculators (DONE)
- `app/tasks.py`: `compute_indices` task (status transitions, error capture,
  writes JSON result to the `results/` volume).
- `app/indices/configs.py`: indicator sets (labels, pillars, polarity, kind),
  faithful to the reference scripts.
- `app/indices/calculators.py`: shared math —
  polarity → z-score → winsorise ±3 → correlation → KMO/Bartlett/MSA/eigenvalues
  → weights (Equal single/two-level, PCA, FA, Hybrid, Reference-based) →
  index rescaled to mean 100 / sd 10. Survey-weighted household path for HFCI
  with national index by round and stress-share chart.
- `app/indices/exports.py`: serialise result to CSV / XLSX / JSON.
- Celery instance lives in `app/extensions.py`; configured by the app factory so
  both the web process (`.delay`) and the worker share settings.

### Phase 4 — HTMX runs dashboard (DONE)
- `runs.html` + `_runs_table.html` fragment with auto-refresh while runs are
  active (start/stop polling via `HX-Trigger-After-Settle` events).

### Phase 5 — Run detail + Plotly (DONE)
- `detail.html`: metadata cards, Cronbach-alpha chips, section tables, and
  Plotly line charts for the index series (and HFCI stress share). In-progress
  runs show a spinner and self-refresh until complete.

### Phase 6 — Exports (DONE)
- CSV / Excel / JSON download routes backed by `exports.py`.

### Phase 7 — Validation & debugging (END ONLY — NOT STARTED)
1. Ensure `.env` exists (already created from `.env.example`).
2. `docker compose up --build`; confirm the one-shot `migrate` service applies
   `0001_initial_schema` before `web` and `worker` start.
3. Smoke-test the full flow: sign up → upload each index's sample dataset →
   confirm Celery processes the run → inspect dashboard + detail views →
   download CSV/Excel/JSON.
4. `docker compose exec web python -m pytest`; fix failures.
5. Add tests for: upload route behaviour, Celery task status transitions,
   calculator edge cases (missing/odd columns), HTMX runs fragment, detail
   rendering.
6. Security hardening pass (upload validation, error surfacing, redirects).

### Phase 8 — Polish & docs (NOT STARTED)
1. Tighten UI copy/layout; index-specific hints on the upload page.
2. Extend `README.md` with concrete per-index input-schema examples and a short
   "how to interpret the outputs" section.
3. Optional observability: structured logging around runs, worker-status panel.
4. Final review.

---

## Validation summary

Validation was run end-to-end. Results:

| Check | Result |
| --- | --- |
| `docker compose up --build` | ✅ All services healthy |
| `qa_verify.py --datasets-dir /reference --base-url http://web:8000` | ✅ **154 passed, 0 failed** |
| `smoke_all_indices.py` (uploads all 5 indices via HTTP) | ✅ All succeeded |
| `pytest -v` | ✅ **6 passed** (existing auth tests) |

### Bugs found and fixed during validation

1. **Redis protected mode** — `redis/redis.conf` had `protected-mode yes` while
   binding to `0.0.0.0`, so the Celery worker could not connect. Changed to
   `protected-mode no` (safe because port 6379 is not published).
2. **HFCI household calculator crash** — `compute_household` passed a DataFrame
   to `pd.to_numeric`. Aligned it with the quarterly path by using
   `.apply(pd.to_numeric, errors="coerce")`.
3. **HFCI missing-values count** — `missing_mask.isna().sum().sum()` counted
   `NaN` in an already-boolean mask; changed to `missing_mask.sum().sum()`.
4. **HFCI Cronbach alpha** — `_cronbach_weighted` passed an `(n, k)` matrix to
   `_weighted_std`, which expects `(k, n)`. Transposed the inputs.
5. **HTTP QA harness** — script didn't send CSRF tokens; updated to fetch forms
   and include `csrf_token` in signup/upload POSTs.
6. **Sample datasets not mounted** — added `../:/reference:ro` bind mounts to
   `web` and `worker` for dev/QA access to the parent `pp/` datasets.

### Files added or changed during validation

- `redis/redis.conf` — disabled protected mode.
- `docker-compose.yml` — added `/reference` bind mount to web/worker.
- `requirements.txt` — added `requests` for HTTP smoke tests.
- `qa_verify.py` — new QA harness in repo root.
- `smoke_all_indices.py` — new end-to-end smoke test for all 5 indices.
- `MANUAL_QA_CHECKLIST.md` — browser + CLI checklist.

## Remaining optional polish

- README input-schema / interpretation examples.
- UI copy tweaks (upload hints per index).
- Optional structured logging / worker status panel.

## File map

```
app/
  __init__.py            Flask app factory (configures Celery, registers blueprints)
  config.py              Config from environment variables
  extensions.py          db, login_manager, csrf, celery instance + FlaskContextTask
  models.py              User, IndexRun
  auth.py                signup / login / logout blueprint
  tasks.py               compute_indices Celery task
  indices/
    __init__.py          indices blueprint (upload, runs, detail, status, download)
    configs.py           indicator sets for BCI/CCI/HFCI/IPI/LMCI
    calculators.py       shared weighting + aggregation methodology
    exports.py           CSV / Excel / JSON serialisation
  templates/
    base.html            shell + nav
    indices/             landing, upload, runs, _runs_table, detail, _status_badge
migrations/versions/0001_initial_schema.py   schema source of truth
celery_app.py            worker entry point
docker-compose.yml       migrate → web / worker / db / redis
tests/                   conftest + auth tests
```

---

## Result contract (JSON-serialisable)

```python
{
  "index_type": "BCI",
  "index_name": "Business Confidence Index",
  "kind": "quarterly",                 # or "household"
  "meta": {n, p, missing_values, kmo, bartlett_chi2, bartlett_df, bartlett_p,
           k_kaiser, k_parallel, variance_explained, alphas: {pillar: value}},
  "sections": [                        # ordered, each table or chart
    {"kind": "table", "key": "indicators",   "title": "...", "columns": [...], "rows": [...]},
    {"kind": "table", "key": "weights", ...},
    {"kind": "table", "key": "pillar_totals", ...},
    {"kind": "table", "key": "z_scores", ...},      # quarterly only
    {"kind": "chart", "key": "index_series", "x": [...], "series": {method: [...]}},
    {"kind": "table", "key": "index_series", ...},
    {"kind": "table", "key": "eigenvalues", ...},
    {"kind": "table", "key": "msa", ...},
    {"kind": "table", "key": "correlation", ...},
    {"kind": "table", "key": "reference", ...},     # only if a REF column exists
    {"kind": "table", "key": "method_comparison", ...},
    {"kind": "table", "key": "decision_summary", ...},
    {"kind": "chart", "key": "stress_share", ...},  # household only
  ]
}
```

## Reference material (parent `pp/`)
- `bci_all_methods.py`, `cci_all_methods.py`, `ipi_all_methods.py`,
  `lmci_all_methods.py`, `hfci_all_methods.txt` — real methodology + indicator sets.
- `*_simulated_dataset.csv` — sample datasets for each index.
- `*_weighting_results.xlsx` — expected output workbooks.