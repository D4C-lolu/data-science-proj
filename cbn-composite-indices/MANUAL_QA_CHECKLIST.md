# Manual QA Checklist — CBN Composite Indices

Use this checklist after `docker compose up --build` to verify the app through
the browser and command line.

## 1. Stack health

- [ ] `docker compose ps` shows `db`, `redis`, `web`, `worker` healthy/running.
- [ ] `docker compose logs --tail=20 worker` shows no Redis connection errors.
- [ ] `docker compose exec redis redis-cli CONFIG GET protected-mode` returns `no`.
- [ ] `curl http://localhost:8000/health` returns `200 OK`.

## 2. Automated harness (run first)

```bash
docker compose exec web python qa_verify.py --datasets-dir /reference --base-url http://web:8000
```

- [ ] Result: `154 passed, 0 failed`.

```bash
docker compose exec web python smoke_all_indices.py
```

- [ ] All five indices (BCI, CCI, HFCI, IPI, LMCI) report `OK`.

```bash
docker compose exec web python -m pytest -v
```

- [ ] All tests pass.

## 3. Authentication (browser)

Open `http://localhost:8000`.

- [ ] Anonymous root `/` redirects to `/auth/login`.
- [ ] Click **Sign up**, create a user with email, username, password.
- [ ] After signup you land on `/indices/` (the catalogue).
- [ ] Log out via the nav; log back in with username + password.
- [ ] Log in with email + password also works.
- [ ] Bad credentials show a clear error and do not log you in.

## 4. Upload & processing (browser)

From `/indices/upload`:

- [ ] **BCI** — upload `bci_simulated_dataset.csv`. Run status goes `queued → running → succeeded`.
- [ ] **CCI** — upload `cci_simulated_dataset.csv`. Run succeeds.
- [ ] **HFCI** — upload `hfci_simulated_dataset.csv`. Run succeeds (this is the household path).
- [ ] **IPI** — upload `ipi_simulated_dataset.csv`. Run succeeds.
- [ ] **LMCI** — upload `lmci_simulated_dataset.csv`. Run succeeds.

For each run:
- [ ] Dashboard `/indices/runs` auto-refreshes while the run is active.
- [ ] Detail page shows metadata cards, weights table, pillar totals, index chart.
- [ ] Plotly line chart renders for the index series.
- [ ] HFCI detail page additionally shows the stress-share chart.
- [ ] No 500 errors in `docker compose logs web`.

## 5. Exports (browser)

On any completed run detail page:

- [ ] Download **CSV** — file downloads and contains a header + data rows.
- [ ] Download **Excel** — file opens, one sheet per result section.
- [ ] Download **JSON** — valid JSON, includes `index_type`, `meta`, `sections`.

## 6. Error handling

- [ ] Upload a non-CSV/XLSX file (e.g. `.txt`) — rejected with a clear message.
- [ ] Upload a CSV with missing required columns — run fails gracefully and shows `error_message`.
- [ ] Upload a CSV for the wrong index type (e.g. HFCI columns selected as BCI) — run fails with a helpful error.

## 7. Security / hardening spot checks

- [ ] CSRF token is present on signup, login, and upload forms.
- [ ] `POST /indices/upload` without a CSRF token returns `400`.
- [ ] After login, `/auth/login` redirects away (already-authenticated users can't reuse login).
- [ ] `docker compose exec redis redis-cli CONFIG GET protected-mode` is `no` **only because** port 6379 is not published. Do not expose Redis to the internet without auth.

## Sign-off

| Checked by | Date | Result |
|------------|------|--------|
|            |      |        |
