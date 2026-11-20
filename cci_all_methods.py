"""
CCI weighting: Equal, PCA-only, FA-only and Hybrid PCA-FA (plus a predictive extension, a tightening-episode test and an
out-of-sample test) on the full 18-indicator / 5-pillar set from QES, IHFCS and CBN supply-side series.
Run on your laptop:  python cci_all_methods.py
 - Step 0 simulates a quarterly dataset (indicators C1..C18 + an activity series 'ACT' used only as the validation
   target) and SAVES it to your laptop (DATA_PATH). Replace that file with your real indicators (same column names)
   and, optionally, an activity series called ACT (e.g. real GDP growth); the rest of the script runs unchanged.
 - Output: one Excel workbook (OUTPUT_XLSX) with one sheet per result block.
Requires: numpy, pandas, openpyxl  (scipy optional, only for the Bartlett p-value)
"""
import numpy as np                                   # numerical arrays and linear algebra
import pandas as pd                                  # tables (DataFrames) and Excel output
from pathlib import Path                             # portable file paths for your laptop
from openpyxl.styles import Font                     # used to bold the Excel header rows

# ----------------------------------------------------------------------------- 0. SETTINGS
BASE_DIR = Path(r"C:\Users\Olanrewaju Sanni\Downloads")      # your folder (edit if needed)
if not BASE_DIR.exists(): BASE_DIR = Path.cwd()               # if that folder is missing (e.g. another PC), use the current folder
DATA_PATH   = BASE_DIR / "cci_simulated_dataset.csv"          # dataset on your laptop
OUTPUT_XLSX = BASE_DIR / "CCI_weighting_results.xlsx"         # results workbook created by this script
SEED, T     = 909, 64                                # random seed (reproducible) and number of quarters
N_BOOT, BLOCK = 300, 4                               # bootstrap resamples and block length (quarters)
N_TRAIN     = 40                                     # quarters used to estimate weights in the out-of-sample test
K_FA_OVERRIDE = 3                                    # factors used for FA-only (None = use parallel analysis). Parallel analysis is borderline here
                                                     # (4th eigenvalue 1.608 vs threshold 1.606), so 3 is used, as in the guide; set None to follow the rule
STRESS      = list(range(27, 35))                    # positions of the tightening-episode quarters (0-based): 2016Q4-2018Q3 in the simulated data

# ----------------------------------------------------------------------------- 1. HELPER FUNCTIONS (commented)
def standardise(raw, polarity):                      # align polarity then convert to z-scores
    X = raw.copy()                                   # work on a copy so the raw data stay untouched
    for c in X.columns: X[c] = polarity[c] * X[c]    # multiply by +1 or -1 so higher always = easier credit conditions
    return (X - X.mean()) / X.std(ddof=1)            # z-score: subtract mean, divide by sample standard deviation

def varimax(L, it=200, tol=1e-9):                    # varimax rotation of a loading matrix L (p indicators x k factors)
    p, k = L.shape; R = np.eye(k); d = 0             # p = indicators, k = factors, R = rotation matrix, d = previous criterion
    for _ in range(it):                              # iterate until the criterion stops improving
        Lr = L @ R                                   # current rotated loadings
        u, s, vt = np.linalg.svd(L.T @ (Lr**3 - Lr @ np.diag((Lr**2).sum(0)) / p))   # SVD of the varimax gradient
        R = u @ vt; dn = s.sum()                     # update the rotation; dn = new value of the criterion
        if dn < d * (1 + tol): break                 # stop when the improvement is negligible
        d = dn                                       # remember the criterion for the next pass
    return L @ R                                     # return the rotated loadings

def fix_sign(L):                                     # make each factor's loadings mostly positive (sign is arbitrary)
    return L * np.where(L.sum(0) < 0, -1, 1)         # flip any column whose loadings sum to a negative number

def weights_equal(cols, pillars=None, two_level=False):  # METHOD 1: equal weights
    if not two_level: return pd.Series(1 / len(cols), index=cols)  # single level: every indicator gets 1/n
    P = len(pillars)                                 # two level: number of pillars
    return pd.Series({c: 1 / P / len(cs) for cs in pillars.values() for c in cs})[cols]  # each pillar 1/P, split equally inside

def weights_pca_only(Z, k=None):                     # METHOD 2: PCA-only weights
    R = np.corrcoef(Z.values.T)                      # correlation matrix of the indicators
    w, v = np.linalg.eigh(R); o = np.argsort(w)[::-1]; w, v = w[o], v[:, o]  # eigenvalues/vectors sorted large to small
    k = k or int((w > 1).sum())                      # number of components: Kaiser rule (eigenvalue > 1)
    L = fix_sign(v[:, :k] * np.sqrt(w[:k]))          # unrotated loadings = eigenvector x sqrt(eigenvalue)
    share = w[:k] / w[:k].sum()                      # each kept component's share of the retained variance
    raw = (L ** 2 * share).sum(1)                    # squared loadings weighted by variance share, summed over components
    return pd.Series(raw / raw.sum(), index=Z.columns)   # normalise so weights sum to 1

def assign_weights(L, cols):                         # shared by FA-only and Hybrid: loadings -> weights
    assign = np.abs(L).argmax(1)                     # assign each indicator to the factor with its largest |loading|
    ss = (L ** 2).sum(0); fw = ss / ss.sum()         # sum of squared loadings per factor; fw = factor weights
    wi = np.zeros(len(cols))                         # container for indicator weights
    for f in range(L.shape[1]):                      # loop over factors
        m = assign == f                              # indicators assigned to factor f
        if m.any(): wi[m] = (L[m, f] ** 2) / (L[m, f] ** 2).sum() * fw[f]  # within-factor share x factor weight
    return pd.Series(wi / wi.sum(), index=cols)      # normalise so weights sum to 1

def paf(R, k, it=500, tol=1e-6):                     # principal-axis factoring (common-factor model)
    h = 1 - 1 / np.diag(np.linalg.inv(R))            # starting communalities: squared multiple correlations
    for _ in range(it):                              # iterate communalities until they converge
        Rr = R.copy(); np.fill_diagonal(Rr, h)       # reduced correlation matrix: communalities on the diagonal
        w, v = np.linalg.eigh(Rr); o = np.argsort(w)[::-1][:k]            # keep the k largest eigenvalues
        L = v[:, o] * np.sqrt(np.clip(w[o], 0, None))                     # factor loadings (negative eigenvalues set to 0)
        hn = np.clip((L ** 2).sum(1), 0, 0.995)      # new communalities, capped to avoid Heywood cases
        if np.max(np.abs(hn - h)) < tol: h = hn; break                    # converged: stop
        h = hn                                       # otherwise carry the new communalities forward
    return L, h                                      # loadings and communalities

def parallel_threshold(R, n, reps=500, seed=3):      # Horn's parallel analysis: eigenvalues expected from pure noise
    p = R.shape[0]; rng = np.random.default_rng(seed)           # p indicators; reproducible random generator
    sims = np.array([np.sort(np.linalg.eigvalsh(np.corrcoef(rng.normal(size=(n, p)).T)))[::-1] for _ in range(reps)])  # random-data eigenvalues
    return np.percentile(sims, 95, axis=0)           # 95th percentile threshold for each component

def parallel_k(R, n, reps=500, seed=3):              # number of factors suggested by parallel analysis
    thr = parallel_threshold(R, n, reps, seed)       # noise thresholds
    return int((np.sort(np.linalg.eigvalsh(R))[::-1] > thr).sum())   # count observed eigenvalues above threshold

def weights_fa_only(Z, k=None):                      # METHOD 3: factor-analysis-only weights
    R = np.corrcoef(Z.values.T)                      # correlation matrix
    k = k or parallel_k(R, len(Z))                   # number of factors: parallel analysis unless supplied
    L, h = paf(R, k)                                 # principal-axis factoring
    L = fix_sign(varimax(L)) if k > 1 else fix_sign(L)   # rotate only if more than one factor
    return assign_weights(L, Z.columns)              # convert loadings to weights

def weights_hybrid(Z):                               # METHOD 4: hybrid PCA-FA (PCA extraction + varimax + assignment)
    R = np.corrcoef(Z.values.T)                      # correlation matrix
    w, v = np.linalg.eigh(R); o = np.argsort(w)[::-1]; w, v = w[o], v[:, o]   # PCA eigen-decomposition, sorted
    k = int((w > 1).sum())                           # PCA decides the number of factors (Kaiser rule)
    L = fix_sign(varimax(v[:, :k] * np.sqrt(w[:k]))) # rotate the retained PCA loadings
    return assign_weights(L, Z.columns)              # within- and between-factor weights

def weights_reference(Z, ref, lead=1):               # EXTENSION: predictive weights (association with FUTURE activity)
    ref = np.asarray(ref, float)                     # activity series (target), not part of the index
    cors = []                                        # correlation of each indicator with next-quarter activity
    for c in Z.columns:                              # loop over indicators
        x = Z[c].values[:len(Z) - lead] if lead > 0 else Z[c].values   # indicator at t
        y = ref[lead:] if lead > 0 else ref          # activity at t + lead
        cors.append(np.corrcoef(x, y)[0, 1])         # simple correlation
    pos = np.clip(np.array(cors), 0, None)           # keep positive correlations only (no negative weights)
    return pd.Series(pos / pos.sum(), index=Z.columns), pd.Series(cors, index=Z.columns)   # weights and raw correlations

def index_from(Z, wts):                              # build the composite index from z-scores and weights
    s = Z @ wts                                      # weighted sum of z-scores for each quarter
    return 100 + 10 * (s - s.mean()) / s.std(ddof=1) # rescale to mean 100 and standard deviation 10

# ----------------------------------------------------------------------------- 2. INDICATOR SET (5 pillars, 18 indicators)
META = {  # id: (name, pillar, polarity)  polarity +1 = higher means EASIER credit, -1 = tighter credit
 'C1':('Firms reporting easier access to finance','A Access and availability',1),'C2':('Firms denied or discouraged from credit','A Access and availability',-1),
 'C3':('Households denied or discouraged from credit','A Access and availability',-1),'C4':('Firms reporting tighter collateral requirements','A Access and availability',-1),
 'C5':('Prime lending rate','B Cost of credit',-1),'C6':('Maximum lending rate','B Cost of credit',-1),'C7':('Lending-deposit rate spread','B Cost of credit',-1),
 'C8':('Firms reporting higher borrowing costs','B Cost of credit',-1),
 'C9':('Real private-sector credit growth (y/y)','C Credit growth and demand',1),'C10':('New lending volume growth','C Credit growth and demand',1),
 'C11':("Firms' credit demand balance",'C Credit growth and demand',1),'C12':('Households taking new loans','C Credit growth and demand',1),
 'C13':('Non-performing loan ratio','D Financial stability',-1),'C14':('Banking-system liquidity ratio','D Financial stability',1),'C15':('Capital adequacy ratio','D Financial stability',1),
 'C16':('Household debt-service-to-income','E Borrower burden',-1),'C17':('Households in arrears','E Borrower burden',-1),'C18':('Firms with debt-servicing difficulty','E Borrower burden',-1)}
COLS = list(META)                                                     # indicator IDs in order
POL  = {c: META[c][2] for c in COLS}                                  # polarity dictionary
PILLARS = {}                                                          # pillar -> list of indicator IDs
for c in COLS: PILLARS.setdefault(META[c][1], []).append(c)          # group indicators by pillar

# ----------------------------------------------------------------------------- 3. SIMULATE AND SAVE THE DATASET ("on your laptop")
def simulate_dataset(seed=SEED, T=T):                # builds quarterly indicators from four hidden factors
    rng = np.random.default_rng(seed)                # reproducible randomness
    Fp, Fq, Fr, Fb = (np.zeros(T) for _ in range(4)) # hidden factors: price of credit, availability/volume, financial risk, borrower burden (easier = higher)
    for t in range(T):                               # price conditions lead availability and borrower burden
        Fp[t] = (0.8 * Fp[t-1] if t > 0 else 0) + 0.6 * rng.normal()
        Fq[t] = (0.6 * Fq[t-1] + 0.4 * Fp[t-1] if t > 0 else 0) + 0.8 * rng.normal()
        Fr[t] = (0.7 * Fr[t-1] if t > 0 else 0) + 0.7 * rng.normal()
        Fb[t] = (0.7 * Fb[t-1] + 0.3 * Fp[t-1] if t > 0 else 0) + 0.7 * rng.normal()
    st = np.array(STRESS)                            # tightening episode: price, availability and risk factors fall
    Fp[st] -= 1.5; Fq[st] -= 1.0; Fr[st] -= 1.0
    F = np.c_[Fp, Fq, Fr, Fb]; F = (F - F.mean(0)) / F.std(0)       # standardise each hidden factor
    Lam = {'C1':[.3,.8,0,0],'C2':[0,.75,0,.2],'C3':[0,.6,0,.4],'C4':[.2,.6,.3,0],                   # true loadings on (price, availability, risk, burden)
           'C5':[.9,0,0,0],'C6':[.85,.1,0,0],'C7':[.5,0,.3,.1],'C8':[.6,.3,0,0],
           'C9':[.3,.7,.1,0],'C10':[.2,.75,0,0],'C11':[.4,.4,0,0],'C12':[.2,.5,0,.3],
           'C13':[0,.1,.85,.1],'C14':[0,.2,.6,0],'C15':[0,0,.6,.2],
           'C16':[.2,0,0,.8],'C17':[0,0,.2,.75],'C18':[0,.2,.2,.7]}
    noise = {c: rng.uniform(.5, .75) for c in COLS}  # indicator-specific noise level
    good = pd.DataFrame({c: F @ np.array(Lam[c]) + rng.normal(0, noise[c], T) for c in COLS})   # "easier-credit-direction" series
    raw = good.copy()
    for c in COLS: raw[c] = POL[c] * good[c]         # record negative-polarity indicators the way the sources report them
    act = np.zeros(T)                                # activity (e.g. real GDP growth), driven by LAGGED factors
    for t in range(1, T): act[t] = 0.5*Fq[t-1] + 0.3*Fr[t-1] + 0.25*Fb[t-1] + 0.2*Fp[t-1] + 0.5 * rng.normal()
    raw['ACT'] = act                                 # NOT part of the index; used only for validation
    raw.index = pd.period_range('2010Q1', periods=T, freq='Q').astype(str); raw.index.name = 'Quarter'
    return raw

if not DATA_PATH.exists():                           # create the dataset only if it is not already on the laptop
    simulate_dataset().to_csv(DATA_PATH)             # save it (replace this file with real indicators later)
data = pd.read_csv(DATA_PATH, index_col=0)           # LOAD the dataset from the laptop
raw = data[COLS]                                     # the 18 indicators as recorded
ref = data['ACT'].values if 'ACT' in data.columns else None   # activity series (optional target)

# ----------------------------------------------------------------------------- 4. COMMON PREPARATION (identical for all methods)
miss_before = raw.isna().sum()                       # (a) count missing values per indicator
raw = raw.interpolate(limit=2, limit_direction='both')   # (a) fill gaps of up to two quarters by linear interpolation
miss_after = raw.isna().sum()                        # missing values left after interpolation
# (deflating credit growth, seasonal adjustment and stationarity transforms would be applied here to real data)
Z0 = standardise(raw, POL)                           # (b) polarity alignment + z-scores
Z = Z0.clip(-3, 3)                                   # (c) winsorise at +/-3 standard deviations
Z = (Z - Z.mean()) / Z.std(ddof=1)                   # (d) re-standardise after capping
n, p = Z.shape                                       # n = quarters, p = indicators
R = np.corrcoef(Z.values.T)                          # (e) correlation matrix used by every factor method
Rinv = np.linalg.inv(R)                              # inverse of R (needed for partial correlations)
anti = -Rinv / np.sqrt(np.outer(np.diag(Rinv), np.diag(Rinv)))   # (f) partial (anti-image) correlations
np.fill_diagonal(anti, 0); Ro = R - np.eye(p)        # off-diagonal parts only
msa = (Ro**2).sum(0) / ((Ro**2).sum(0) + (anti**2).sum(0))        # (f) MSA per indicator
kmo = (Ro**2).sum() / ((Ro**2).sum() + (anti**2).sum())           # (f) overall KMO
chi2 = -(n - 1 - (2*p + 5) / 6) * np.log(np.linalg.det(R)); dof = p*(p-1)//2   # (g) Bartlett chi-square and df
try:
    from scipy.stats import chi2 as _c; pval = float(_c.sf(chi2, dof))   # p-value if scipy is installed
except Exception:
    pval = np.nan                                    # otherwise leave blank
def cronbach(cols):                                  # (h) reliability of a pillar
    s = Z[cols]; k = len(cols)                       # standardised indicators of the pillar
    return k/(k-1) * (1 - s.var(ddof=1).sum() / s.sum(axis=1).var(ddof=1))   # alpha formula
alpha = {pl: cronbach(cs) for pl, cs in PILLARS.items()}   # alpha for each pillar
w_eig, v_eig = np.linalg.eigh(R); o = np.argsort(w_eig)[::-1]; w_eig, v_eig = w_eig[o], v_eig[:, o]  # (i) eigenvalues
thr = parallel_threshold(R, n)                       # (i) parallel-analysis thresholds
k_kaiser = int((w_eig > 1).sum()); k_pa = int((w_eig > thr).sum())   # (i) number of factors: Kaiser vs parallel analysis
k_pa_data = k_pa                                     # parallel-analysis answer from the data
if K_FA_OVERRIDE: k_pa = int(K_FA_OVERRIDE)          # optional override used for FA-only and its bootstrap

# ----------------------------------------------------------------------------- 5. THE METHODS
w_eq  = weights_equal(COLS)                          # Method 1a: equal weights, single level
w_eq2 = weights_equal(COLS, PILLARS, True)           # Method 1b: equal weights, two level (pillars equal)
w_pca = weights_pca_only(Z)                          # Method 2: PCA only
w_fa  = weights_fa_only(Z, k=k_pa)                   # Method 3: factor analysis only (k from parallel analysis, or the override)
w_fa4 = weights_fa_only(Z, k=k_kaiser)               # Method 3b: factor analysis with k = Kaiser number (sensitivity)
w_hyb = weights_hybrid(Z)                            # Method 4: hybrid PCA-FA
cols_w = {'Equal (single level)': w_eq, 'Equal (two level)': w_eq2, 'PCA only': w_pca,
          f'FA only (k={k_pa})': w_fa, f'FA only (k={k_kaiser})': w_fa4, 'Hybrid PCA-FA': w_hyb}
if ref is not None:                                  # Method 5 (extension): predictive weights (lead = 1 quarter)
    w_ref, ref_corr = weights_reference(Z, ref, lead=1); cols_w['Predictive'] = w_ref
W = pd.DataFrame(cols_w)                             # all weights side by side

L_pca = fix_sign(v_eig[:, :k_kaiser] * np.sqrt(w_eig[:k_kaiser]))               # unrotated PCA loadings
L_fa, h_fa = paf(R, k_pa); L_fa = fix_sign(varimax(L_fa)) if k_pa > 1 else fix_sign(L_fa)   # FA loadings, communalities
L_fa4, h_fa4 = paf(R, k_kaiser); L_fa4 = fix_sign(varimax(L_fa4)) if k_kaiser > 1 else fix_sign(L_fa4)   # FA with k = Kaiser
L_hyb = fix_sign(varimax(v_eig[:, :k_kaiser] * np.sqrt(w_eig[:k_kaiser])))      # hybrid rotated loadings
asg = np.abs(L_hyb).argmax(1); ss_h = (L_hyb**2).sum(0); fw_h = ss_h / ss_h.sum()   # hybrid assignment and factor weights
within = pd.Series([L_hyb[i, asg[i]]**2 / (L_hyb[asg == asg[i], asg[i]]**2).sum() for i in range(p)], index=COLS)  # within-factor weight

# ----------------------------------------------------------------------------- 6. INDICES AND COMPARISON
I = pd.DataFrame({m: index_from(Z, W[m]) for m in W.columns})   # composite index under each weight set
corr = I.corr(); rank_corr = I.rank().corr()                    # level and rank correlations between methods
dI = I.diff().dropna()                                          # quarterly changes
direction = pd.DataFrame({a: {b: (np.sign(dI[a]) == np.sign(dI[b])).mean() for b in W.columns} for a in W.columns})   # same-direction share
pillar_tot = pd.DataFrame({m: {pl: W.loc[cs, m].sum() for pl, cs in PILLARS.items()} for m in W.columns})   # weight per pillar
leadlag = None                                                  # lead-lag table vs the activity series
if ref is not None:
    leadlag = pd.DataFrame({m: [np.corrcoef(I[m].values[:n-l] if l else I[m].values, ref[l:] if l else ref)[0, 1] for l in range(5)] for m in W.columns},
                           index=[f'Index leads by {l} quarter(s)' for l in range(5)])   # corr of index(t) with activity(t+lead)
rb = np.random.default_rng(5); boot = {'PCA only': [], f'FA only (k={k_pa})': [], 'Hybrid PCA-FA': []}   # bootstrap containers
nb = int(np.ceil(n / BLOCK))                                    # number of blocks needed
for _ in range(N_BOOT):                                         # moving-block bootstrap (keeps time dependence)
    starts = rb.integers(0, n - BLOCK + 1, nb); ii = np.concatenate([np.arange(s, s + BLOCK) for s in starts])[:n]   # resampled quarters
    Zb = Z.iloc[ii].reset_index(drop=True); Zb = (Zb - Zb.mean()) / Zb.std(ddof=1)   # re-standardise the resample
    boot['PCA only'].append(weights_pca_only(Zb).values)
    boot[f'FA only (k={k_pa})'].append(weights_fa_only(Zb, k=k_pa).values)
    boot['Hybrid PCA-FA'].append(weights_hybrid(Zb).values)
boot_sd = pd.DataFrame({m: np.std(np.array(a), 0) for m, a in boot.items()}, index=COLS)   # SD of each weight across resamples


# ---- out-of-sample test: weights and baseline from the first N_TRAIN quarters only, then forecast activity(t+1) from index(t)
oos_rows = []                                        # results per method
if ref is not None:
    sgn = np.array([POL[c] for c in COLS])           # polarity vector
    Xp = raw.values * sgn                            # polarity-aligned data
    mu_tr, sd_tr = Xp[:N_TRAIN].mean(0), Xp[:N_TRAIN].std(0, ddof=1)   # baseline from the training window only
    Zall = pd.DataFrame((Xp - mu_tr) / sd_tr, columns=COLS)            # all quarters standardised with training baseline
    Ztr = Zall.iloc[:N_TRAIN]; Ztr = (Ztr - Ztr.mean()) / Ztr.std(ddof=1)   # training sample, re-standardised for estimation
    Wtr = {'Equal (single level)': weights_equal(COLS), 'Equal (two level)': weights_equal(COLS, PILLARS, True),
           'PCA only': weights_pca_only(Ztr), 'FA only': weights_fa_only(Ztr, k=k_pa), 'Hybrid PCA-FA': weights_hybrid(Ztr),
           'Predictive': weights_reference(Ztr, ref[:N_TRAIN], lead=1)[0]}   # weights estimated on training data only
    for m, wv in Wtr.items():                        # evaluate each weight set
        sc = (Zall @ wv).values                      # index score for every quarter
        Xr = np.c_[np.ones(N_TRAIN - 1), sc[:N_TRAIN - 1]]                 # regress activity(t+1) on index(t) in training
        beta = np.linalg.lstsq(Xr, ref[1:N_TRAIN], rcond=None)[0]          # intercept and slope
        te = np.arange(N_TRAIN - 1, n - 1)           # forecast origins in the test window
        pred = beta[0] + beta[1] * sc[te]; act = ref[te + 1]               # forecasts and actual next-quarter activity
        bench = np.full(len(act), ref[1:N_TRAIN].mean())                   # benchmark: training-sample mean activity
        sse, sseb = ((act - pred) ** 2).sum(), ((act - bench) ** 2).sum()  # squared errors: model vs benchmark
        oos_rows.append([m, len(te), float(np.corrcoef(sc[te], act)[0, 1]), float(1 - sse / sseb), float(np.sqrt(sse / len(act)))])
oos_df = pd.DataFrame(oos_rows, columns=['Method','Test quarters','Out-of-sample correlation','Out-of-sample R2 vs mean benchmark','RMSE'])


# ---- tightening-episode capture and sub-indices
sm = np.zeros(n, bool); sm[[i for i in STRESS if i < n]] = True          # quarters inside the stress window
stress_df = pd.DataFrame({m: {'Mean index inside window': I[m][sm].mean(), 'Mean index outside window': I[m][~sm].mean(),
        'Gap (index points)': I[m][sm].mean() - I[m][~sm].mean(), 'Lowest value': I[m].min(), 'Quarter of lowest value': I.index[int(np.argmin(I[m].values))]} for m in W.columns}).T
sub = pd.DataFrame({pl: Z[cs].mean(axis=1) for pl, cs in PILLARS.items()})   # equal-weighted pillar scores (sub-indices)
pil_corr = sub.corr()                                                    # correlation between pillar scores
price_q = Z[PILLARS['B Cost of credit']].mean(axis=1)                    # price sub-index (pillar B)
qty_q = Z[PILLARS['A Access and availability'] + PILLARS['C Credit growth and demand']].mean(axis=1)   # quantity sub-index (A + C)
pq = pd.DataFrame({'Item': ['Correlation price vs quantity sub-index', 'Price sub-index: mean inside minus outside window (sd units)', 'Quantity sub-index: mean inside minus outside window (sd units)'],
                   'Value': [np.corrcoef(price_q, qty_q)[0, 1], price_q[sm].mean() - price_q[~sm].mean(), qty_q[sm].mean() - qty_q[~sm].mean()]})

# ----------------------------------------------------------------------------- 7. BUILD THE RESULT SHEETS
sheets = {}                                          # sheet name -> DataFrame (each sheet lists its full result)
names = ['README','Indicators','Raw_Data','Prep_Z_Scores','Prep_Tests','Prep_Indicator_MSA','Correlation_Matrix','Eigenvalues','M1_Equal','M2_PCA_Only',
         'M3_FA_Only','M3b_FA_Kaiser_k','M4_Hybrid','M5_Predictive_Weights','Weights_All','Pillar_Totals','Indices_All','Method_Comparison','Lead_Lag_vs_Activity',
         'Stress_Episode','Pillar_Correlations','OutOfSample_Test','Bootstrap_Stability','Decision_Summary']
desc = ['Guide to the sheets','18 indicators, pillar, polarity','Dataset loaded from your laptop (as recorded)','Polarity-aligned, winsorised, standardised data (common to all methods)',
 'KMO, Bartlett test, Cronbach alpha per pillar, factor-count rules','Measure of sampling adequacy per indicator','Correlation matrix of the prepared indicators','Eigenvalues, variance explained, parallel-analysis thresholds',
 'Equal weights (single and two level)','PCA loadings and weights','FA loadings, communalities and weights (k by parallel analysis)','FA with k = Kaiser rule (sensitivity)',
 'Hybrid rotated loadings, assignment, within/factor/final weights','Predictive (activity-based) weights (extension)','All weights side by side','Weight per pillar under each method','Index series under each method',
 'Correlations, rank correlations, direction agreement','Correlation of each index with activity at leads 0-4 (index leads activity)','Index level inside vs outside the tightening episode, by method','Correlation between pillar scores and price vs quantity sub-indices','Out-of-sample test: weights fitted on the first quarters, tested on the rest','Block-bootstrap standard deviation of weights','Automatic reading of the results']
sheets['README'] = pd.DataFrame({'Sheet': names[1:], 'Content': desc[1:]})
sheets['Indicators'] = pd.DataFrame([(c, META[c][0], META[c][1], '+' if POL[c] > 0 else '-') for c in COLS], columns=['ID','Indicator','Pillar','Polarity'])
sheets['Raw_Data'] = data.reset_index()
sheets['Prep_Z_Scores'] = Z.round(4).reset_index()
sheets['Prep_Tests'] = pd.DataFrame({'Test': ['Quarters (n)','Indicators (p)','Observations per indicator','Missing values before interpolation','Missing values after interpolation','KMO overall',
    'Bartlett chi-square','Bartlett df','Bartlett p-value','Factors: Kaiser rule (eigenvalue>1)','Factors: parallel analysis (from data)','Factors used for FA-only','Variance explained by Kaiser factors (PCA)']+[f'Cronbach alpha {k}' for k in alpha],
  'Value': [n,p,round(n/p,2),int(miss_before.sum()),int(miss_after.sum()),round(kmo,3),round(chi2,1),dof,pval,k_kaiser,k_pa_data,k_pa,round(w_eig[:k_kaiser].sum()/p,3)]+[round(v,3) for v in alpha.values()]})
sheets['Prep_Indicator_MSA'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], 'MSA': msa.round(3)})
sheets['Correlation_Matrix'] = pd.DataFrame(R, index=COLS, columns=COLS).round(3).reset_index().rename(columns={'index':'ID'})
sheets['Eigenvalues'] = pd.DataFrame({'Component': range(1, p+1), 'Eigenvalue': w_eig.round(3), '% variance': (w_eig/p*100).round(1), 'Cumulative %': (np.cumsum(w_eig)/p*100).round(1),
    'Parallel threshold': thr.round(3), 'Kaiser (>1)': w_eig > 1, 'Passes parallel': w_eig > thr})
base_cols = {'ID': COLS, 'Indicator': [META[c][0] for c in COLS], 'Pillar': [META[c][1] for c in COLS]}
sheets['M1_Equal'] = pd.DataFrame({**base_cols, 'Weight single level': w_eq.values, 'Weight two level': w_eq2.values})
sheets['M2_PCA_Only'] = pd.DataFrame({'ID': COLS, 'Indicator': base_cols['Indicator'], **{f'PC{j+1} loading': L_pca[:, j].round(3) for j in range(k_kaiser)}, 'PCA weight': w_pca.values})
sheets['M3_FA_Only'] = pd.DataFrame({'ID': COLS, 'Indicator': base_cols['Indicator'], **{f'F{j+1} loading': np.atleast_2d(L_fa.T)[j].round(3) for j in range(k_pa)},
    'Communality': h_fa.round(3), 'Flag (<0.20)': h_fa < 0.20, 'FA weight': w_fa.values})
sheets['M3b_FA_Kaiser_k'] = pd.DataFrame({'ID': COLS, 'Indicator': base_cols['Indicator'], **{f'F{j+1} loading': np.atleast_2d(L_fa4.T)[j].round(3) for j in range(k_kaiser)},
    'Communality': h_fa4.round(3), 'FA weight': w_fa4.values})
sheets['M4_Hybrid'] = pd.DataFrame({'ID': COLS, 'Indicator': base_cols['Indicator'], **{f'F{j+1} rotated loading': L_hyb[:, j].round(3) for j in range(k_kaiser)},
    'Assigned factor': [f'F{a+1}' for a in asg], 'Cross-loading >0.4 on another factor': [bool((np.abs(L_hyb[i]) > 0.4).sum() > 1) for i in range(p)],
    'Within-factor weight': within.values, 'Factor weight': [fw_h[a] for a in asg], 'Final weight': w_hyb.values})
sheets['M5_Predictive_Weights'] = pd.DataFrame({'ID': COLS, 'Indicator': base_cols['Indicator'], 'Correlation with activity next quarter': ref_corr.round(3).values,
    'Predictive weight': w_ref.values}) if ref is not None else pd.DataFrame({'Note': ['No ACT column in the dataset']})
wa = W.reset_index().rename(columns={'index':'ID'}); wa.insert(1, 'Indicator', base_cols['Indicator'])
sheets['Weights_All'] = pd.concat([wa, pd.DataFrame([['Total', '', *W.sum().values]], columns=wa.columns)], ignore_index=True)
sheets['Pillar_Totals'] = pillar_tot.reset_index().rename(columns={'index':'Pillar'})
sheets['Indices_All'] = I.reset_index().rename(columns={'index':'Quarter'})
rows_cmp = []
for title, df_ in [('Correlation of index levels', corr), ('Rank correlation', rank_corr), ('Share of quarters with same direction of change', direction)]:
    rows_cmp.append(pd.DataFrame([[title] + [''] * len(df_.columns)], columns=['Block'] + list(df_.columns)))
    rows_cmp.append(df_.round(3).reset_index().rename(columns={'index': 'Block'}))
sheets['Method_Comparison'] = pd.concat(rows_cmp, ignore_index=True)
sheets['Lead_Lag_vs_Activity'] = leadlag.round(3).reset_index().rename(columns={'index':'Lead'}) if leadlag is not None else pd.DataFrame({'Note': ['No ACT column in the dataset']})
sheets['Stress_Episode'] = stress_df.round(3).reset_index().rename(columns={'index':'Method'})
sheets['Pillar_Correlations'] = pd.concat([pil_corr.round(3).reset_index().rename(columns={'index':'Pillar'}), pd.DataFrame([['']*len(pil_corr.columns)+['']], columns=['Pillar']+list(pil_corr.columns)).iloc[0:0], pq.rename(columns={'Item':'Pillar','Value':'A Access and availability'})], ignore_index=True)
sheets['OutOfSample_Test'] = oos_df.round(4) if len(oos_df) else pd.DataFrame({'Note': ['No ACT column in the dataset']})
bs = boot_sd.reset_index().rename(columns={'index':'ID'})
bs.loc[len(boot_sd)] = ['Mean SD', *boot_sd.mean().values]; bs.loc[len(boot_sd)+1] = ['Max SD', *boot_sd.max().values]
sheets['Bootstrap_Stability'] = bs
min_corr = corr.loc['Equal (single level)'].drop('Equal (single level)').min()      # lowest agreement with single-level equal weights
low_h = [c for c, h_ in zip(COLS, h_fa) if h_ < 0.20]                                  # indicators with communality below 0.20
cross = [COLS[i] for i in range(p) if (np.abs(L_hyb[i]) > 0.4).sum() > 1]              # indicators loading above 0.4 on two or more factors
sheets['Decision_Summary'] = pd.DataFrame({'Item': ['KMO reading','Bartlett test','Number of factors','Lowest correlation with single-level equal weights','Weight of pillars D+E (financial stability + borrower burden): equal / two-level / PCA / FA / hybrid',
    'Indicators with FA communality below 0.20','Cross-loading indicators (hybrid)','Suggested weighting','Reminder'],
  'Result': [f'{kmo:.3f} ({"adequate" if kmo >= 0.6 else "inadequate"})', 'significant' if (not np.isnan(pval) and pval < 0.05) else f'chi-square {chi2:.1f}, df {dof}',
    f'Kaiser = {k_kaiser}, parallel analysis = {k_pa_data} (borderline), FA-only uses {k_pa}: report both', f'{min_corr:.3f}',
    ' / '.join(f'{(pillar_tot.loc[[x for x in PILLARS if x.startswith("D")][0], m] + pillar_tot.loc[[x for x in PILLARS if x.startswith("E")][0], m])*100:.1f}%' for m in ['Equal (single level)','Equal (two level)','PCA only',f'FA only (k={k_pa})','Hybrid PCA-FA']),
    ', '.join(low_h) if low_h else 'none', ', '.join(cross) if cross else 'none',
    'Equal weights: indices agree closely; publish sub-indices' if min_corr >= 0.98 else 'Indices differ materially (multi-dimensional structure): use hybrid PCA-FA or two-level equal weights, avoid PCA-only and predictive weights, and publish four sub-indices (access and volume, cost, financial stability, borrower burden)',
    'Freeze the weights; re-estimate only at an agreed review. Replace the simulated file by real, deflated and seasonally adjusted indicators before using the results.']})

# ----------------------------------------------------------------------------- 8. WRITE THE EXCEL WORKBOOK
with pd.ExcelWriter(OUTPUT_XLSX, engine='openpyxl') as xw:       # open the workbook for writing
    for name in names:                                           # one sheet per result block
        df_ = sheets[name]; df_.to_excel(xw, sheet_name=name[:31], index=False)   # Excel limits sheet names to 31 characters
        ws = xw.sheets[name[:31]]; ws.freeze_panes = 'A2'        # keep the header row visible
        for cell in ws[1]: cell.font = Font(bold=True)           # bold header
        for col in ws.columns:                                   # set a readable column width
            ws.column_dimensions[col[0].column_letter].width = min(48, max(10, max(len(str(c.value)) if c.value is not None else 0 for c in col[:60]) + 2))
print(f'Done: {OUTPUT_XLSX} written with {len(sheets)} sheets; dataset at {DATA_PATH}')
