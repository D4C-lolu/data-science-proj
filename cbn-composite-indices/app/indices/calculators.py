"""Weighting and aggregation mathematics for the CBN composite indices.

The five indices share one methodology. For every index we:

1. align indicator polarity so that higher always means "better";
2. convert each indicator to a z-score and winsorise at ±3 standard
   deviations;
3. compute the (survey-weighted, for HFCI) correlation matrix and the
   accompanying KMO / Bartlett diagnostics;
4. derive indicator weights under several methods — equal (single and two
   level), PCA-only, factor-analysis-only, hybrid PCA-FA, and an optional
   reference-based method;
5. build the composite index from the weighted z-scores and rescale it to
   mean 100 and standard deviation 10.

Quarterly indices rescale quarter by quarter; the household index builds a
per-household score, rescales it, then averages by survey round to get a
national series with a pooled baseline of 100.

Only ``numpy`` and ``pandas`` are required.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.indices.configs import IndexConfig

WINSOR = 3.0
BLOCK_BOOTSTRAP = 4
N_BOOTSTRAP = 300
SEED = 404


# --------------------------------------------------------------------------- #
# Core linear algebra helpers
# --------------------------------------------------------------------------- #
def varimax(loadings: np.ndarray, iterations: int = 200, tol: float = 1e-9) -> np.ndarray:
    """Varimax-rotate a ``p x k`` loading matrix."""
    p, k = loadings.shape
    rotation = np.eye(k)
    prev = 0.0
    for _ in range(iterations):
        rotated = loadings @ rotation
        u, s, vt = np.linalg.svd(
            loadings.T @ (rotated ** 3 - rotated @ np.diag((rotated ** 2).sum(0)) / p)
        )
        rotation = u @ vt
        criterion = s.sum()
        if criterion < prev * (1 + tol):
            break
        prev = criterion
    return loadings @ rotation


def fix_sign(loadings: np.ndarray) -> np.ndarray:
    """Flip any factor whose loadings sum to a negative value."""
    return loadings * np.where(loadings.sum(0) < 0, -1, 1)


def paf(corr: np.ndarray, k: int, iterations: int = 500, tol: float = 1e-6):
    """Principal-axis factoring returning loadings and communalities."""
    communalities = 1 - 1 / np.diag(np.linalg.inv(corr))
    loadings = np.zeros((corr.shape[0], k))
    for _ in range(iterations):
        reduced = corr.copy()
        np.fill_diagonal(reduced, communalities)
        values, vectors = np.linalg.eigh(reduced)
        order = np.argsort(values)[::-1][:k]
        loadings = vectors[:, order] * np.sqrt(np.clip(values[order], 0, None))
        updated = np.clip((loadings ** 2).sum(1), 0, 0.995)
        if np.max(np.abs(updated - communalities)) < tol:
            communalities = updated
            break
        communalities = updated
    return loadings, communalities


def parallel_threshold(corr: np.ndarray, n: int, reps: int = 500, seed: int = 3) -> np.ndarray:
    """Horn's parallel-analysis eigenvalue thresholds derived from noise."""
    p = corr.shape[0]
    rng = np.random.default_rng(seed)
    sims = np.array(
        [
            np.sort(np.linalg.eigvalsh(np.corrcoef(rng.normal(size=(n, p)).T)))[::-1]
            for _ in range(reps)
        ]
    )
    return np.percentile(sims, 95, axis=0)


def _weighted_corr(z: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Survey-weighted correlation matrix."""
    z = np.asarray(z, float)
    weights = np.asarray(weights, float)
    weights = weights / weights.sum()
    mean = (z * weights[:, None]).sum(0)
    centered = z - mean
    cov = (centered * weights[:, None]).T @ centered
    std = np.sqrt(np.diag(cov))
    std[std == 0] = 1e-12
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    return corr


def _weighted_std(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    values = np.atleast_2d(values)
    weights = np.asarray(weights, float)
    weights = weights / weights.sum()
    mean = (values * weights).sum(1, keepdims=True)
    var = ((values - mean) ** 2 * weights).sum(1)
    return np.sqrt(var)


# --------------------------------------------------------------------------- #
# Weighting methods
# --------------------------------------------------------------------------- #
def weights_equal(cols, pillars=None):
    """Equal (or two-level, pillar-balanced) weights."""
    if not pillars:
        return pd.Series(1 / len(cols), index=cols)
    n_pillars = len(pillars)
    values = {c: 1 / n_pillars / len(members) for members in pillars.values() for c in members}
    return pd.Series(values)[cols]


def weights_pca(corr: np.ndarray, cols, k: int):
    values, vectors = np.linalg.eigh(corr)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    k = max(1, min(k, len(cols)))
    loadings = fix_sign(vectors[:, :k] * np.sqrt(np.clip(values[:k], 0, None)))
    share = values[:k] / values[:k].sum()
    raw = (loadings ** 2 * share).sum(1)
    raw = np.clip(raw, 0, None)
    total = raw.sum() or 1.0
    return pd.Series(raw / total, index=cols)


def _assign_weights(loadings: np.ndarray, cols) -> pd.Series:
    assigned = np.abs(loadings).argmax(1)
    ss = (loadings ** 2).sum(0)
    factor_weights = ss / (ss.sum() or 1.0)
    weights = np.zeros(len(cols))
    for f in range(loadings.shape[1]):
        mask = assigned == f
        if mask.any():
            within = (loadings[mask, f] ** 2)
            denom = within.sum() or 1.0
            weights[mask] = within / denom * factor_weights[f]
    total = weights.sum() or 1.0
    return pd.Series(weights / total, index=cols)


def weights_fa(corr: np.ndarray, cols, k: int):
    k = max(1, min(k, len(cols)))
    loadings, _ = paf(corr, k)
    loadings = fix_sign(varimax(loadings)) if k > 1 else fix_sign(loadings)
    return _assign_weights(loadings, cols)


def weights_hybrid(corr: np.ndarray, cols, k: int):
    values, vectors = np.linalg.eigh(corr)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    k = max(1, min(k, len(cols)))
    loadings = fix_sign(varimax(vectors[:, :k] * np.sqrt(np.clip(values[:k], 0, None))))
    return _assign_weights(loadings, cols)


def weights_reference(z: pd.DataFrame, reference: np.ndarray, cols):
    """Weights from the correlation of each indicator with a reference series."""
    correlations = []
    n = len(z)
    ref = np.asarray(reference, float)[:n]
    for c in cols:
        x = z[c].values[:n]
        if np.std(x) == 0 or np.std(ref) == 0:
            correlations.append(0.0)
        else:
            correlations.append(float(np.corrcoef(x, ref)[0, 1]))
    correlations = np.nan_to_num(np.array(correlations), nan=0.0)
    positive = np.clip(correlations, 0, None)
    total = positive.sum()
    if total == 0:
        weights = np.full(len(cols), 1 / len(cols))
    else:
        weights = positive / total
    return pd.Series(weights, index=cols), pd.Series(correlations, index=cols)


# --------------------------------------------------------------------------- #
# Preparation and diagnostics
# --------------------------------------------------------------------------- #
def _cronbach(z: pd.DataFrame, cols) -> float:
    subset = z[cols]
    k = len(cols)
    if k < 2:
        return float("nan")
    total_var = subset.sum(axis=1).var(ddof=1)
    var_sum = subset.var(ddof=1).sum()
    if total_var == 0:
        return float("nan")
    return k / (k - 1) * (1 - var_sum / total_var)


def _cronbach_weighted(z: np.ndarray, weights: np.ndarray, cols, all_cols) -> float:
    idx = [all_cols.index(c) for c in cols]
    subset = z[:, idx]
    k = len(cols)
    if k < 2:
        return float("nan")
    var_sum = (_weighted_std(subset.T, weights) ** 2).sum()
    total_var = _weighted_std(subset.sum(1, keepdims=True).T, weights)[0] ** 2
    if total_var == 0:
        return float("nan")
    return k / (k - 1) * (1 - var_sum / total_var)


def _diagnostics(corr: np.ndarray, n_effective: float, p: int):
    try:
        corr_inv = np.linalg.inv(corr)
        inv_diag = np.diag(corr_inv)
        # Guard against tiny negative/zero diagonals from near-singular matrices.
        inv_diag = np.where(inv_diag > 1e-12, inv_diag, 1e-12)
        with np.errstate(divide="ignore", invalid="ignore"):
            anti = -corr_inv / np.sqrt(np.outer(inv_diag, inv_diag))
        anti = np.nan_to_num(anti, nan=0.0, posinf=0.0, neginf=0.0)
        np.fill_diagonal(anti, 0)
        off = corr - np.eye(p)
        msa = (off ** 2).sum(0) / ((off ** 2).sum(0) + (anti ** 2).sum(0))
        kmo = float((off ** 2).sum() / ((off ** 2).sum() + (anti ** 2).sum()))
    except np.linalg.LinAlgError:
        msa = np.full(p, np.nan)
        kmo = float("nan")

    if n_effective <= 1:
        bartlett_chi2 = float("nan")
        p_value = float("nan")
    else:
        sign, logdet = np.linalg.slogdet(corr)
        bartlett_chi2 = float("nan") if sign <= 0 else float(-(n_effective - 1 - (2 * p + 5) / 6) * logdet)
        dof = p * (p - 1) // 2
        try:
            from scipy.stats import chi2 as _chi2  # optional

            p_value = float(_chi2.sf(bartlett_chi2, dof))
        except Exception:
            p_value = float("nan")
    return kmo, msa, bartlett_chi2, p * (p - 1) // 2, p_value


def _prepare_frame(raw: pd.DataFrame, cols, polarity) -> pd.DataFrame:
    frame = raw[cols].copy()
    for c in cols:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = frame.interpolate(limit=2, limit_direction="both")
    frame = frame.dropna(how="any")
    aligned = frame.copy()
    for c in cols:
        aligned[c] = polarity[c] * aligned[c]
    z = (aligned - aligned.mean()) / aligned.std(ddof=1)
    z = z.clip(-WINSOR, WINSOR)
    z = (z - z.mean()) / z.std(ddof=1)
    return z


def _index_from(z: pd.DataFrame, weights) -> np.ndarray:
    s = z.values @ np.asarray(weights, float)
    sd = s.std(ddof=1)
    if sd == 0:
        return np.full(len(s), 100.0)
    return 100 + 10 * (s - s.mean()) / sd


def _round(value, places=4):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, places)


# --------------------------------------------------------------------------- #
# Quarterly indices (BCI, CCI, IPI, LMCI)
# --------------------------------------------------------------------------- #
def compute_quarterly(config: IndexConfig, data: pd.DataFrame) -> dict:
    cols = config.columns
    polarity = config.polarity
    pillars = config.pillars

    missing_mask = data.reindex(columns=cols).apply(pd.to_numeric, errors="coerce").isna()

    z = _prepare_frame(data, cols, polarity)
    n, p = z.shape

    corr = np.corrcoef(z.values.T)
    n_eff = n
    kmo, msa, chi2, dof, pval = _diagnostics(corr, n_eff, p)

    values, _ = np.linalg.eigh(corr)
    values = np.sort(values)[::-1]
    threshold = parallel_threshold(corr, n) if n > p else np.zeros(p)
    k_kaiser = int((values > 1).sum())
    k_kaiser = max(1, k_kaiser)
    k_pa = int((values > threshold).sum())
    k_pa = max(1, k_pa)

    w_eq = weights_equal(cols)
    w_eq2 = weights_equal(cols, pillars)
    w_pca = weights_pca(corr, cols, k_kaiser)
    w_fa = weights_fa(corr, cols, k_pa)
    w_hyb = weights_hybrid(corr, cols, k_kaiser)

    weight_frames = {
        "Equal (single level)": w_eq,
        "Equal (two level)": w_eq2,
        "PCA only": w_pca,
        f"FA only (k={k_pa})": w_fa,
        "Hybrid PCA-FA": w_hyb,
    }

    reference = None
    ref_col = None
    for candidate in ("REF", "Reference", "reference"):
        if candidate in data.columns:
            ref_col = candidate
            break
    if ref_col is not None:
        aligned_ref = data.loc[z.index, ref_col].astype(float).values
        w_ref, ref_corr = weights_reference(z, aligned_ref, cols)
        weight_frames["Reference-based"] = w_ref
        reference = {"correlations": ref_corr, "name": ref_col, "values": aligned_ref}

    weights = pd.DataFrame(weight_frames)
    index_series = pd.DataFrame({m: _index_from(z, weights[m]) for m in weights.columns}, index=z.index)

    alphas = {pl: _round(_cronbach(z, cs), 3) for pl, cs in pillars.items()}

    meta = {
        "n": int(n),
        "p": int(p),
        "observations_dropped": int(len(data) - n),
        "missing_values": int(missing_mask.sum().sum()),
        "kmo": _round(kmo, 3),
        "bartlett_chi2": _round(chi2, 1),
        "bartlett_df": int(dof) if dof == dof else None,
        "bartlett_p": _round(pval, 4) if pval == pval else None,
        "k_kaiser": k_kaiser,
        "k_parallel": k_pa,
        "variance_explained": _round(values[:k_kaiser].sum() / p, 3),
        "alphas": alphas,
        "period_column": config.period_col,
    }

    return _assemble_result(
        config=config,
        z=z,
        meta=meta,
        values=values,
        threshold=threshold if len(threshold) == p else None,
        msa=msa,
        corr=corr,
        weights=weights,
        index_series=index_series,
        reference=reference,
        pillars=pillars,
    )


# --------------------------------------------------------------------------- #
# Household index (HFCI)
# --------------------------------------------------------------------------- #
def compute_household(config: IndexConfig, data: pd.DataFrame) -> dict:
    cols = config.columns
    polarity = config.polarity
    pillars = config.pillars

    missing_mask = data.reindex(columns=cols).apply(pd.to_numeric, errors="coerce").isna()

    round_col = "round" if "round" in data.columns else None
    weight_col = "w" if "w" in data.columns else None

    raw = data[cols].copy()
    for c in cols:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    if round_col is not None:
        raw = raw.fillna(raw.groupby(data[round_col]).transform("median"))
    raw = raw.fillna(raw.median())
    raw = raw.dropna(how="any")

    rounds = data.loc[raw.index, round_col].values if round_col else np.ones(len(raw), dtype=int)
    if weight_col:
        design_weights = data.loc[raw.index, weight_col].astype(float).values
    else:
        design_weights = np.ones(len(raw))

    aligned = raw.values * np.array([polarity[c] for c in cols])
    w_mean = np.average(aligned, axis=0, weights=design_weights)
    w_std = _weighted_std(aligned.T, design_weights)
    z = (aligned - w_mean) / w_std
    z = np.clip(z, -WINSOR, WINSOR)
    w_mean = np.average(z, axis=0, weights=design_weights)
    w_std = _weighted_std(z.T, design_weights)
    z = (z - w_mean) / w_std
    n, p = z.shape

    n_eff = design_weights.sum() ** 2 / (design_weights ** 2).sum()
    corr = _weighted_corr(z, design_weights)
    kmo, msa, chi2, dof, pval = _diagnostics(corr, n_eff, p)

    values, _ = np.linalg.eigh(corr)
    values = np.sort(values)[::-1]
    threshold = parallel_threshold(corr, int(n_eff)) if n > p else np.zeros(p)
    k_kaiser = max(1, int((values > 1).sum()))
    k_pa = max(1, int((values > threshold).sum()))

    w_eq = weights_equal(cols)
    w_eq2 = weights_equal(cols, pillars)
    w_pca = weights_pca(corr, cols, k_kaiser)
    w_fa = weights_fa(corr, cols, k_pa)
    w_hyb = weights_hybrid(corr, cols, k_kaiser)

    weights = pd.DataFrame(
        {
            "Equal (single level)": w_eq,
            "Equal (two level)": w_eq2,
            "PCA only": w_pca,
            f"FA only (k={k_pa})": w_fa,
            "Hybrid PCA-FA": w_hyb,
        }
    )

    # Per-household scores, rescaled so the weighted sd is 1.
    scores = pd.DataFrame({m: z @ weights[m].values for m in weights.columns})
    for m in scores.columns:
        s = scores[m].values
        sd = math.sqrt(np.average((s - np.average(s, weights=design_weights)) ** 2, weights=design_weights))
        scores[m] = s / sd if sd else s

    unique_rounds = np.unique(rounds)
    round_labels = [f"Round {int(r)}" for r in unique_rounds]
    series = {}
    for m in scores.columns:
        baseline = np.average(scores[m].values, weights=design_weights)
        series[m] = [
            100 + 10 * (np.average(scores[m].values[rounds == r], weights=design_weights[rounds == r]) - baseline)
            for r in unique_rounds
        ]
    index_series = pd.DataFrame(series, index=round_labels)

    alphas = {pl: _round(_cronbach_weighted(z, design_weights, cs, cols), 3) for pl, cs in pillars.items()}

    meta = {
        "n": int(n),
        "p": int(p),
        "n_effective": _round(n_eff, 1),
        "rounds": [int(r) for r in unique_rounds],
        "missing_values": int(missing_mask.sum().sum()),
        "kmo": _round(kmo, 3),
        "bartlett_chi2": _round(chi2, 1),
        "bartlett_df": int(dof) if dof == dof else None,
        "bartlett_p": _round(pval, 4) if pval == pval else None,
        "k_kaiser": k_kaiser,
        "k_parallel": k_pa,
        "variance_explained": _round(values[:k_kaiser].sum() / p, 3),
        "alphas": alphas,
        "period_column": "round",
    }

    z_frame = pd.DataFrame(z, columns=cols, index=raw.index)

    result = _assemble_result(
        config=config,
        z=z_frame,
        meta=meta,
        values=values,
        threshold=threshold if len(threshold) == p else None,
        msa=msa,
        corr=corr,
        weights=weights,
        index_series=index_series,
        reference=None,
        pillars=pillars,
    )

    # Household-specific extra sections.
    stress = {}
    for m in scores.columns:
        stress[m] = [
            100 * np.average((scores[m].values[rounds == r] < -1).astype(float), weights=design_weights[rounds == r])
            for r in unique_rounds
        ]
    result["sections"].append(
        {
            "kind": "chart",
            "key": "stress_share",
            "title": "Households in stress (score below baseline by 1 sd)",
            "x": round_labels,
            "series": {m: [_round(v, 2) for v in vals] for m, vals in stress.items()},
            "y_title": "% of weighted households",
        }
    )
    return result


# --------------------------------------------------------------------------- #
# Shared result assembly
# --------------------------------------------------------------------------- #
def _assemble_result(config, z, meta, values, threshold, msa, corr, weights, index_series, reference, pillars):
    cols = config.columns

    indicators_rows = [
        {
            "id": c,
            "label": config.meta[c].label,
            "pillar": config.meta[c].pillar,
            "polarity": "+" if config.meta[c].polarity > 0 else "−",
            **({"source": config.meta[c].source} if config.meta[c].source else {}),
        }
        for c in cols
    ]
    indicators_columns = ["id", "label", "pillar", "polarity"]
    if any(config.meta[c].source for c in cols):
        indicators_columns.append("source")

    weight_rows = []
    for c in cols:
        row = {"id": c, "label": config.meta[c].label}
        for m in weights.columns:
            row[m] = _round(weights.loc[c, m], 4)
        weight_rows.append(row)

    pillar_rows = [
        {"pillar": pl, **{m: _round(weights.loc[members, m].sum(), 4) for m in weights.columns}}
        for pl, members in pillars.items()
    ]

    series_columns = ["period"] + list(index_series.columns)
    series_rows = [
        {"period": str(period), **{m: _round(index_series.loc[period, m], 3) for m in index_series.columns}}
        for period in index_series.index
    ]

    eigenvalue_rows = [
        {
            "component": i + 1,
            "eigenvalue": _round(values[i], 3),
            "% variance": _round(values[i] / len(cols) * 100, 1),
            "cumulative %": _round(values[: i + 1].sum() / len(cols) * 100, 1),
            **({"parallel threshold": _round(threshold[i], 3)} if threshold is not None else {}),
        }
        for i in range(len(cols))
    ]

    msa_rows = [{"id": c, "label": config.meta[c].label, "msa": _round(msa[i], 3)} for i, c in enumerate(cols)]

    corr_rows = []
    for i, c in enumerate(cols):
        corr_rows.append({"id": c, **{cols[j]: _round(corr[i, j], 3) for j in range(len(cols))}})

    sections = [
        {"kind": "table", "key": "indicators", "title": "Indicators", "columns": indicators_columns, "rows": indicators_rows},
        {"kind": "table", "key": "weights", "title": "Indicator weights by method", "columns": ["id", "label"] + list(weights.columns), "rows": weight_rows},
        {"kind": "table", "key": "pillar_totals", "title": "Weight per pillar", "columns": ["pillar"] + list(weights.columns), "rows": pillar_rows},
        {"kind": "chart", "key": "index_series", "title": "Composite index by method", "x": [str(p) for p in index_series.index],
         "series": {m: [_round(index_series.loc[p, m], 3) for p in index_series.index] for m in index_series.columns},
         "y_title": f"{config.code} (mean 100, sd 10)"},
        {"kind": "table", "key": "index_series", "title": "Index values", "columns": series_columns, "rows": series_rows},
        {"kind": "table", "key": "eigenvalues", "title": "Eigenvalues", "columns": list(eigenvalue_rows[0].keys()), "rows": eigenvalue_rows},
        {"kind": "table", "key": "msa", "title": "Indicator sampling adequacy (MSA)", "columns": ["id", "label", "msa"], "rows": msa_rows},
        {"kind": "table", "key": "correlation", "title": "Correlation matrix", "columns": ["id"] + cols, "rows": corr_rows},
    ]

    # Quarterly results are small enough to include the prepared z-scores.
    if config.kind != "household":
        z_rows = [
            {"period": str(period), **{c: _round(z.loc[period, c], 3) for c in cols}}
            for period in z.index
        ]
        sections.insert(
            3,
            {"kind": "table", "key": "z_scores", "title": "Prepared z-scores",
             "columns": ["period"] + cols, "rows": z_rows},
        )

    if reference is not None:
        ref_rows = [
            {"id": c, "label": config.meta[c].label,
             "correlation with reference": _round(reference["correlations"].loc[c], 3),
             "reference-based weight": _round(weights.loc[c, "Reference-based"], 4)}
            for c in cols
        ]
        sections.append(
            {"kind": "table", "key": "reference", "title": f"Reference-based weights (vs {reference['name']})",
             "columns": ["id", "label", "correlation with reference", "reference-based weight"], "rows": ref_rows}
        )

    method_names = list(weights.columns)
    corr_methods = index_series.corr().round(3)
    comparison_rows = []
    for title, frame in (
        ("Correlation of index levels", corr_methods),
        ("Rank correlation", index_series.rank().corr().round(3)),
    ):
        comparison_rows.append({"block": title, **{m: "" for m in method_names}})
        for m in method_names:
            comparison_rows.append({"block": m, **{n: _round(frame.loc[m, n], 3) for n in method_names}})
    sections.append(
        {"kind": "table", "key": "method_comparison", "title": "Comparison between methods",
         "columns": ["block"] + method_names, "rows": comparison_rows}
    )

    sections.append(
        {"kind": "table", "key": "decision_summary", "title": "Decision summary",
         "columns": ["item", "result"], "rows": _decision_summary(config, meta, weights, index_series, pillars)}
    )

    result = {
        "index_type": config.code,
        "index_name": config.name,
        "kind": config.kind,
        "meta": meta,
        "sections": sections,
    }
    return result


def _decision_summary(config, meta, weights, index_series, pillars):
    kmo = meta.get("kmo")
    min_corr = None
    if "Equal (single level)" in index_series.columns:
        others = [c for c in index_series.columns if c != "Equal (single level)"]
        if others:
            min_corr = index_series["Equal (single level)"].corr(index_series[others[0]])
            for o in others[1:]:
                min_corr = min(min_corr, index_series["Equal (single level)"].corr(index_series[o]))
    low_alpha = [pl for pl, a in (meta.get("alphas") or {}).items() if a is not None and a < 0.6]

    rows = [
        {"item": "KMO reading", "result": f"{kmo} ({'adequate' if (kmo or 0) >= 0.6 else 'inadequate'})" if kmo is not None else "not available"},
        {"item": "Bartlett test", "result": "significant" if (meta.get("bartlett_p") or 1) < 0.05 else f"chi-square {meta.get('bartlett_chi2')}"},
        {"item": "Number of factors", "result": f"Kaiser = {meta.get('k_kaiser')}, parallel analysis = {meta.get('k_parallel')}"},
        {"item": "Variance explained (Kaiser factors)", "result": str(meta.get("variance_explained"))},
        {"item": "Lowest correlation with single-level equal weights", "result": _round(min_corr, 3) if min_corr is not None else "n/a"},
        {"item": "Pillars with Cronbach alpha below 0.6", "result": ", ".join(low_alpha) if low_alpha else "none"},
        {"item": "Suggested weighting", "result": "Hybrid PCA-FA with guard-rails; keep statistical weights as a robustness check"},
        {"item": "Reminder", "result": "Freeze the weights; re-estimate only at an agreed review. Confirm real data is seasonally adjusted before use."},
    ]
    return rows


def compute(index_config: IndexConfig, data: pd.DataFrame) -> dict:
    """Dispatch to the correct compute path for an index configuration."""
    if index_config.kind == "household":
        return compute_household(index_config, data)
    return compute_quarterly(index_config, data)