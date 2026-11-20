# CBN Composite Indices

A Flask application for computing and exploring the Central Bank of Nigeria's composite indices: BCI, CCI, HFCI, IPI, and LMCI.

## Features

- Upload a CSV/Excel dataset for any index through a protected web UI.
- Each run is dispatched to a Celery worker and processed asynchronously; the runs dashboard refreshes automatically while work is in progress.
- The five indices share one methodology implemented in `app/indices/calculators.py`: polarity alignment, z-scoring, winsorisation, correlation diagnostics (KMO / Bartlett / MSA / eigenvalues), and several weighting methods (equal single and two level, PCA-only, factor-analysis-only, hybrid PCA-FA, and optional reference-based).
- Interpretable results: metadata cards, weights per method, pillar totals, eigenvalue and correlation tables, a decision summary, and an interactive Plotly chart of the index series.
- Export any completed run as CSV, Excel (one sheet per section), or JSON.
- Email/username/password signup and login with password hashing, uniqueness validation, CSRF protection, and local-only post-login redirects.
- Excel-based exports use `openpyxl`; results and uploads persist on shared Docker volumes.

Index definitions (indicator labels, pillars, and polarity) live in Python in `app/indices/configs.py`; there is no UI editor for them.

> **Project status:** All feature phases are code-complete, but the app has **not
> yet been run or tested** — validation, tests, and polish are intentionally
> deferred to the end. See [`_PLAN.md`](_PLAN.md) for the full plan, current
> status table, and the *What's left* checklist.

## Structure

```
app/
  __init__.py          Flask app factory
  config.py            Configuration from environment variables
  extensions.py        SQLAlchemy, Flask-Login, CSRF, and the Celery instance
  models.py            User and IndexRun models
  auth.py              Signup / login / logout blueprint
  tasks.py             Celery compute_indices task
  indices/
    configs.py         Indicator sets for the five indices
    calculators.py     Weighting and aggregation methodology
    exports.py         CSV / Excel / JSON serialisation
migrations/            Handwritten Alembic migrations (schema source of truth)
```

## Run locally with Docker

1. Copy `.env.example` to `.env` and set `SECRET_KEY` and `POSTGRES_PASSWORD` to local values.
2. Start the services:

   ```sh
   docker compose up --build
   ```

3. Open <http://localhost:8000> and create an account, then upload a dataset. The health endpoint is at <http://localhost:8000/health>.
4. Stop the services with `docker compose down`. Persistent database, Redis, upload, and result volumes are retained. To remove all persisted data as well, run `docker compose down --volumes`.

Docker Compose starts the `migrate` one-shot job, `web`, `worker`, `db` (PostgreSQL), and `redis`. The migration job must complete successfully before the web and worker containers start. The web and worker containers share the `uploads` and `results` volumes. Set `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` in `.env` to configure the application connections; by default, both use the Compose Redis service (`redis`) on databases 0 and 1 respectively. Flask passes these environment settings into Celery in `app/config.py`, and `celery_app.py` configures the Celery instance from that Flask configuration. For a Redis instance outside Compose, set those URLs to its reachable hostname and credentials, and adjust/remove the `redis` service dependency as appropriate.

The Redis server itself is configured in `redis/redis.conf`, is reachable only on the private Compose network, and persists queue/backend data with AOF and periodic snapshots on the `redis_data` named volume. Redis does not publish a host port.

## Run the Flask app without Docker

Python 3.12 or newer is recommended. PostgreSQL and Redis must be available, and the environment variables in `.env.example` should be configured for those services.

```sh
python -m venv .venv
# Activate the virtual environment, then:
pip install -r requirements.txt
flask --app run.py run --debug
```

In separate terminals, start the worker with:

```sh
celery -A celery_app.celery worker --loglevel=info
```

## Database schema migrations

Alembic applies the handwritten migrations in `migrations/versions/`; those scripts are the schema source of truth. SQLAlchemy models map to the database but do not generate, apply, or alter schema. There is no `create_all()` usage and Flask-Migrate is not installed. Compose runs `alembic upgrade head` in a dedicated one-shot `migrate` service before starting the web app and worker.

## Tests

Tests use an isolated in-memory SQLite database and can be run with `python -m pytest` after installing `requirements.txt`, or inside the web container:

```sh
docker compose exec web python -m pytest
```

To apply migrations manually outside Compose, set `DATABASE_URL` and run:

```sh
alembic upgrade head
```

Create new revisions with `alembic revision -m "describe schema change"`, then write and review the `upgrade()` and `downgrade()` operations in the generated file. **Do not use `--autogenerate`**: Alembic autogeneration is deliberately disabled in `migrations/env.py`. Check the current database revision with `alembic current`; inspect pending SQL with `alembic upgrade head --sql` where supported.

## Input data formats

- **Quarterly indices (BCI, CCI, IPI, LMCI)**: a CSV/Excel file with a period column (for example `Quarter`) followed by the index's indicator columns (for example `B1`–`B18` for BCI). An optional reference column (`REF`) enables reference-based weights. Missing values in a series are linearly interpolated for gaps of up to two periods, then rows with any remaining gaps are dropped.
- **HFCI (household microdata)**: one row per household with the indicator columns (`H1`–`H18`), a `round` column, and a survey design weight column `w`.

The sample datasets and the reference methodology scripts are retained at the project root as reference material.
