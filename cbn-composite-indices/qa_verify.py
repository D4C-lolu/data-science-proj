"""QA verification script for the CBN Composite Indices app.

>>> INTENDED LOCATION: `cbn-composite-indices/qa_verify.py` <<<
This copy lives in the plan folder only because the agent is currently in
Plan mode and cannot write into the repository. Move/copy it to the repo root
(alongside `run.py`) before running.

This is a *human-run* verification harness — it is intentionally separate from
the pytest suite. It exercises the real calculator code path against the
reference sample datasets, checks the result contract and a set of numerical
invariants, and can optionally probe a running HTTP deployment.

Run it inside the web container (which has all dependencies and the mounted
data) with::

    docker compose exec web python qa_verify.py

Or, to also probe the live web server from inside the network::

    docker compose exec web python qa_verify.py --base-url http://web:8000

Options
-------
--datasets-dir PATH   Folder holding the reference *_simulated_dataset.csv files
                      (default: /reference, then the repository parent directory).
--base-url URL        If given, run the HTTP end-to-end checks against a live app.
--keep-going          Continue past failures instead of stopping at the first one.

The script exits non-zero if any check fails, so it can gate CI later.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


# --------------------------------------------------------------------------- #
# Result recording
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self, keep_going: bool = True):
        self.keep_going = keep_going
        self.passed = 0
        self.failed = 0
        self.failures: list[tuple[str, str]] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            print(f"  [PASS] {name}")
            return True
        self.failed += 1
        self.failures.append((name, detail))
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         {detail}")
        if not self.keep_going:
            raise AssertionError(name)
        return False

    def section(self, title: str) -> None:
        print(f"\n=== {title} ===")

    def summary(self) -> int:
        print("\n" + "=" * 60)
        print(f"RESULT: {self.passed} passed, {self.failed} failed")
        if self.failures:
            print("\nFailures:")
            for name, detail in self.failures:
                print(f"  - {name}")
                if detail:
                    print(f"      {detail}")
        print("=" * 60)
        return 0 if self.failed == 0 else 1


# --------------------------------------------------------------------------- #
# Dataset discovery
# --------------------------------------------------------------------------- #
SAMPLES = {
    "BCI": "bci_simulated_dataset.csv",
    "CCI": "cci_simulated_dataset.csv",
    "HFCI": "hfci_simulated_dataset.csv",
    "IPI": "ipi_simulated_dataset.csv",
    "LMCI": "lmci_simulated_dataset.csv",
}


def find_datasets_dir(explicit):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        Path("/reference"),
        Path.cwd() / "reference",
        Path.cwd().parent,          # parent of the app repo (pp/ prototype root)
        Path("/data/reference"),
    ]
    for candidate in candidates:
        if candidate.is_dir() and all((candidate / f).exists() for f in SAMPLES.values()):
            return candidate
    return None


# --------------------------------------------------------------------------- #
# Calculator checks
# --------------------------------------------------------------------------- #
def check_calculator(report, datasets_dir):
    import pandas as pd

    from app.indices.calculators import compute
    from app.indices.configs import INDICES

    results = {}
    for code, filename in SAMPLES.items():
        report.section(f"Calculator — {code}")
        config = INDICES[code]
        path = datasets_dir / filename
        try:
            data = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001
            report.check(f"{code}: dataset loads", False, f"{path}: {exc}")
            continue

        try:
            result = compute(config, data)
        except Exception:  # noqa: BLE001
            report.check(f"{code}: compute() runs without error", False, traceback.format_exc())
            continue

        results[code] = result
        _validate_result(report, code, config, result)
    return results


def _validate_result(report, code, config, result):
    import math

    report.check(f"{code}: returns a dict", isinstance(result, dict))
    report.check(f"{code}: index_type matches", result.get("index_type") == code)
    report.check(f"{code}: has index_name", bool(result.get("index_name")))
    report.check(f"{code}: kind matches config", result.get("kind") == config.kind)

    meta = result.get("meta", {})
    report.check(f"{code}: meta.n is a positive int",
                 isinstance(meta.get("n"), int) and meta["n"] > 0, f"n={meta.get('n')!r}")
    report.check(f"{code}: meta.p equals indicator count",
                 meta.get("p") == len(config.columns),
                 f"p={meta.get('p')!r}, expected {len(config.columns)}")

    n = meta.get("n", 0)
    p = meta.get("p", 1)
    if config.kind != "household":
        report.check(f"{code}: enough observations to estimate (n > p)", n > p, f"n={n}, p={p}")

    report.check(f"{code}: KMO is a finite number in [0, 1]",
                 isinstance(meta.get("kmo"), (int, float)) and 0.0 <= meta["kmo"] <= 1.0,
                 f"kmo={meta.get('kmo')!r}")

    for key in ("k_kaiser", "k_parallel"):
        value = meta.get(key)
        report.check(f"{code}: {key} >= 1", isinstance(value, int) and value >= 1, f"{key}={value!r}")

    alphas = meta.get("alphas") or {}
    report.check(f"{code}: one Cronbach alpha per pillar",
                 set(alphas.keys()) == set(config.pillars.keys()),
                 f"got {sorted(alphas)} vs {sorted(config.pillars)}")
    report.check(f"{code}: alphas are numeric or None",
                 all(a is None or isinstance(a, float) for a in alphas.values()), f"alphas={alphas}")

    sections = result.get("sections", [])
    keys = [s.get("key") for s in sections]
    for required in ("indicators", "weights", "pillar_totals", "index_series", "decision_summary"):
        report.check(f"{code}: has '{required}' section", required in keys, f"keys={keys}")

    weights = next((s for s in sections if s.get("key") == "weights"), None)
    if weights:
        method_cols = [c for c in weights["columns"] if c not in ("id", "label")]
        for method in method_cols:
            total = sum((row.get(method) or 0.0) for row in weights["rows"])
            report.check(f"{code}: weights '{method}' sum to 1", abs(total - 1.0) < 1e-3,
                         f"sum={total:.5f}")

    chart = next((s for s in sections if s.get("key") == "index_series" and s.get("kind") == "chart"), None)
    if chart:
        flat = [v for series in chart["series"].values() for v in series]
        report.check(f"{code}: index series values are finite",
                     all(isinstance(v, (int, float)) and math.isfinite(v) for v in flat),
                     f"sample={flat[:3]}")
        report.check(f"{code}: index series length matches x-axis",
                     all(len(s) == len(chart["x"]) for s in chart["series"].values()))
        report.check(f"{code}: at least one weighting method present", len(chart["series"]) >= 1)

    if code == "HFCI":
        report.check("HFCI: has stress_share chart",
                     any(s.get("key") == "stress_share" for s in sections))


def check_pure_math(report):
    import numpy as np
    import pandas as pd

    from app.indices.calculators import (
        WINSOR,
        _index_from,
        _prepare_frame,
        _weighted_corr,
        weights_equal,
        weights_hybrid,
        weights_pca,
    )

    report.section("Primitives")
    cols = ["A", "B", "C"]
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(rng.normal(size=(40, 3)), columns=cols)
    polarity = {c: 1 for c in cols}

    z = _prepare_frame(frame, cols, polarity)
    report.check("z-scores are standardised (mean≈0, sd≈1)",
                 all(abs(z[c].mean()) < 1e-9 and abs(z[c].std(ddof=1) - 1) < 1e-9 for c in cols))
    report.check("z-scores are winsorised at ±WINSOR", z.abs().max().max() <= WINSOR + 1e-9)

    w_eq = weights_equal(cols)
    report.check("equal weights sum to 1", abs(w_eq.sum() - 1) < 1e-12)
    report.check("equal weights are uniform", np.allclose(w_eq.values, 1 / len(cols)))

    corr = np.corrcoef(z.values.T)
    for name, fn in (("pca", weights_pca), ("hybrid", weights_hybrid)):
        w = fn(corr, cols, 2)
        report.check(f"{name} weights sum to 1", abs(w.sum() - 1) < 1e-9, f"sum={w.sum()}")
        report.check(f"{name} weights are non-negative", (w.values >= -1e-12).all())

    idx = _index_from(z, w_eq)
    report.check("index mean is 100", abs(idx.mean() - 100) < 1e-6)
    report.check("index sd is 10", abs(idx.std(ddof=1) - 10) < 1e-6)

    weighted = _weighted_corr(z.values, np.ones(len(z)))
    report.check("equal-weight corr matrix is symmetric", np.allclose(weighted, weighted.T, atol=1e-9))
    report.check("equal-weight corr matrix has unit diagonal", np.allclose(np.diag(weighted), 1.0))


# --------------------------------------------------------------------------- #
# Export checks
# --------------------------------------------------------------------------- #
def check_exports(report, results):
    from app.indices import exports

    report.section("Exports")
    sample = results.get("BCI") or next(iter(results.values()), None)
    if sample is None:
        report.check("export checks skipped (no results)", False)
        return

    csv_text = exports.to_csv(sample)
    report.check("CSV has a header and at least one data row",
                 csv_text.count("\n") >= 2, f"lines={csv_text.count(chr(10))}")

    json_text = exports.to_json(sample)
    try:
        parsed = json.loads(json_text)
        report.check("JSON parses and keeps index_type", parsed.get("index_type") == sample["index_type"])
    except Exception as exc:  # noqa: BLE001
        report.check("JSON parses", False, str(exc))

    try:
        blob = exports.to_excel(sample)
        report.check("Excel bytes start with the zip signature",
                     blob[:2] == b"PK" and len(blob) > 1000, f"first2={blob[:2]!r}, len={len(blob)}")
    except Exception:  # noqa: BLE001
        report.check("Excel export runs", False, traceback.format_exc())


# --------------------------------------------------------------------------- #
# HTTP end-to-end checks (optional)
# --------------------------------------------------------------------------- #
def _csrf(resp):
    import re
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', resp.text)
    return m.group(1) if m else None


def check_http(report, base_url, datasets_dir):
    try:
        import requests
    except ImportError:
        report.check("HTTP checks (requests not installed; skipping)", True)
        return

    report.section(f"HTTP end-to-end ({base_url})")
    import time
    import uuid

    session = requests.Session()
    base = base_url.rstrip("/")

    health = session.get(f"{base}/health", timeout=10)
    report.check("GET /health returns 200", health.status_code == 200, f"status={health.status_code}")

    root = session.get(f"{base}/", allow_redirects=False, timeout=10)
    report.check("anonymous GET / redirects", root.status_code in (301, 302), f"status={root.status_code}")

    unique = uuid.uuid4().hex[:10]
    signup_form = session.get(f"{base}/auth/signup", timeout=10)
    token = _csrf(signup_form)
    report.check("signup form includes csrf_token", token is not None)
    signup = session.post(
        f"{base}/auth/signup",
        data={
            "csrf_token": token or "",
            "email": f"qa_{unique}@example.com",
            "username": f"qa_{unique}",
            "password": "qa-password-12345",
            "confirm_password": "qa-password-12345",
        },
        timeout=10,
        allow_redirects=False,
    )
    report.check("POST /auth/signup succeeds or redirects", signup.status_code in (200, 302),
                 f"status={signup.status_code}, body={signup.text[:200]}")

    landing = session.get(f"{base}/indices/", timeout=10)
    report.check("authenticated GET /indices/ returns 200", landing.status_code == 200,
                 f"status={landing.status_code}")

    upload_form = session.get(f"{base}/indices/upload", timeout=10)
    token = _csrf(upload_form)
    report.check("upload form includes csrf_token", token is not None)
    with open(datasets_dir / SAMPLES["BCI"], "rb") as handle:
        upload = session.post(
            f"{base}/indices/upload",
            data={"csrf_token": token or "", "index_type": "BCI"},
            files={"dataset": ("bci.csv", handle, "text/csv")},
            timeout=30,
            allow_redirects=False,
        )
    report.check("POST /indices/upload redirects to the run", upload.status_code in (301, 302),
                 f"status={upload.status_code}, body={upload.text[:200]}")

    detail_url = upload.headers.get("Location", "")
    run_id = detail_url.rstrip("/").split("/")[-1] if detail_url else None

    if run_id and run_id.isdigit():
        status = "queued"
        for _ in range(30):
            resp = session.get(f"{base}/indices/{run_id}/status", timeout=10)
            if resp.status_code == 200:
                status = resp.json().get("status", status)
            if status in ("succeeded", "failed"):
                break
            time.sleep(2)
        report.check("uploaded BCI run completes successfully", status == "succeeded",
                     f"final status={status}")

        for fmt in ("csv", "xlsx", "json"):
            dl = session.get(f"{base}/indices/{run_id}/download/{fmt}", timeout=20)
            report.check(f"download {fmt} returns 200", dl.status_code == 200, f"status={dl.status_code}")
    else:
        report.check("upload returned a parsable run id", False, f"Location={detail_url!r}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="QA verification for the CBN Composite Indices app.")
    parser.add_argument("--datasets-dir", default=None, help="Folder with the reference *_simulated_dataset.csv files.")
    parser.add_argument("--base-url", default=None, help="Probe a live deployment at this URL.")
    parser.add_argument("--keep-going", action="store_true", help="Continue past failures.")
    args = parser.parse_args()

    report = Report(keep_going=True)

    print("CBN Composite Indices — QA verification")
    print(f"Python: {sys.version.split()[0]}  |  cwd: {os.getcwd()}")

    report.section("Imports")
    try:
        import app.indices.calculators  # noqa: F401
        import app.indices.exports  # noqa: F401
        import app.tasks  # noqa: F401
        import numpy  # noqa: F401
        import pandas  # noqa: F401

        report.check("core modules import cleanly", True)
    except Exception:  # noqa: BLE001
        report.check("core modules import cleanly", False, traceback.format_exc())
        return report.summary()

    try:
        import scipy  # noqa: F401

        report.check("scipy available (Bartlett p-value)", True)
    except ImportError:
        report.check("scipy available (Bartlett p-value)", False,
                     "Install scipy for the Bartlett p-value; other checks still run.")

    check_pure_math(report)

    datasets_dir = find_datasets_dir(args.datasets_dir)
    if datasets_dir is None:
        report.section("Calculators")
        report.check("reference datasets located", False,
                     "Point --datasets-dir at the folder holding the *_simulated_dataset.csv files.")
        results = {}
    else:
        print(f"\nReference datasets: {datasets_dir}")
        results = check_calculator(report, datasets_dir)
        check_exports(report, results)

    if args.base_url:
        if datasets_dir:
            check_http(report, args.base_url, datasets_dir)
        else:
            report.check("HTTP checks skipped (no datasets for upload)", False)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())