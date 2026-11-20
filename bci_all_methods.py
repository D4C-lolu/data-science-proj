"""
BCI weighting: Equal, PCA-only, FA-only and Hybrid PCA-FA (plus a reference-based extension) on the full
18-indicator / 5-pillar QES balance set.
Run on your laptop:  python bci_all_methods.py
 - Step 0 simulates a quarterly dataset (national balances + a reference series 'REF') and SAVES it to your laptop
   (DATA_PATH). Replace that file with your real QES balances (same column names B1..B18) and, optionally, a
   reference series called REF (for example real output growth); the rest of the script runs unchanged.
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
DATA_PATH   = BASE_DIR / "bci_simulated_dataset.csv"          # dataset on your laptop
OUTPUT_XLSX = BASE_DIR / "BCI_weighting_results.xlsx"         # results workbook created by this script
SEED, T     = 404, 64                                # random seed (reproducible) and number of quarters
N_BOOT, BLOCK = 300, 4                               # bootstrap resamples and block length (quarters)

# ----------------------------------------------------------------------------- 1. HELPER FUNCTIONS (commented)
def standardise(raw, polarity):                      # align polarity then convert to z-scores
    X = raw.copy()                                   # work on a copy so the raw data stay untouched
    for c in X.columns: X[c] = polarity[c] * X[c]    # multiply by +1 or -1 so higher always = better business conditions
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

def weights_reference(Z, ref, lead=0):               # EXTENSION: weights from association with a reference series
    ref = np.asarray(ref, float)                     # reference series (e.g. output growth), not part of the index
    cors = []                                        # correlation of each indicator with the reference
    for c in Z.columns:                              # loop over indicators
        x = Z[c].values[:len(Z) - lead] if lead > 0 else Z[c].values   # indicator at t
        y = ref[lead:] if lead > 0 else ref          # reference at t + lead
        cors.append(np.corrcoef(x, y)[0, 1])         # simple correlation
    pos = np.clip(np.array(cors), 0, None)           # keep positive correlations only (no negative weights)
    return pd.Series(pos / pos.sum(), index=Z.columns), pd.Series(cors, index=Z.columns)   # weights and raw correlations

def index_from(Z, wts):                              # build the composite index from z-scores and weights
    s = Z @ wts                                      # weighted sum of z-scores for each quarter
    return 100 + 10 * (s - s.mean()) / s.std(ddof=1) # rescale to mean 100 and standard deviation 10

def balance(answers, w):                             # QES stage 1: balance = % up minus % down (weighted)
    a, w = np.asarray(answers), np.asarray(w, float) # answers: +1 up, 0 same, -1 down
    return 100 * (w[a == 1].sum() - w[a == -1].sum()) / w.sum()

# ----------------------------------------------------------------------------- 2. INDICATOR SET (5 pillars, 18 indicators)
META = {  # id: (name, pillar, polarity)  polarity +1 = higher is better, -1 = higher is worse
 'B1':('Business confidence (current)','A Confidence and constraints',1),'B2':('Business situation vs last quarter','A Confidence and constraints',1),
 'B3':('Assessment of general economic outlook','A Confidence and constraints',1),'B18':('Weak demand cited as main constraint','A Confidence and constraints',-1),
 'B4':('Production volume','B Production and sales',1),'B5':('Sales / turnover','B Production and sales',1),'B6':('New orders / order books','B Production and sales',1),
 'B7':('Profitability','B Production and sales',1),'B8':('Export orders','B Production and sales',1),
 'B9':('Capacity utilisation','C Investment and capacity',1),'B10':('Capital expenditure','C Investment and capacity',1),'B11':('Investment plans (12 months)','C Investment and capacity',1),
 'B12':('Finished-goods stocks above normal','D Inventories',-1),'B13':('Raw-material stock adequacy','D Inventories',1),
 'B14':('Expected production (3 months)','E Expectations',1),'B15':('Expected orders / sales (3 months)','E Expectations',1),
 'B16':('Expected business conditions (12 months)','E Expectations',1),'B17':('Expected profitability (12 months)','E Expectations',1)}
COLS = list(META)                                                     # indicator IDs in order
POL  = {c: META[c][2] for c in COLS}                                  # polarity dictionary
PILLARS = {}                                                          # pillar -> list of indicator IDs
for c in COLS: PILLARS.setdefault(META[c][1], []).append(c)          # group indicators by pillar

# ----------------------------------------------------------------------------- 3. SIMULATE AND SAVE THE DATASET ("on your laptop")
def simulate_dataset(seed=SEED, T=T):                # builds quarterly national balances from four hidden factors
    rng = np.random.default_rng(seed)                # reproducible randomness
    Fs, Fa, Fi, Fv = (np.zeros(T) for _ in range(4)) # hidden factors: sentiment, activity, investment, inventories
    for t in range(T):                               # sentiment leads activity, activity leads investment
        Fs[t] = (0.7 * Fs[t-1] if t > 0 else 0) + rng.normal()
        Fa[t] = (0.5 * Fa[t-1] + 0.6 * Fs[t-1] if t > 0 else 0) + 0.8 * rng.normal()
        Fi[t] = (0.5 * Fi[t-1] + 0.5 * Fa[t-1] if t > 0 else 0) + 0.8 * rng.normal()
        Fv[t] = (0.5 * Fv[t-1] if t > 0 else 0) + rng.normal()
    F = np.c_[Fs, Fa, Fi, Fv]; F = (F - F.mean(0)) / F.std(0)       # standardise each hidden factor
    Lam = {'B1':[.85,.2,0,0],'B2':[.6,.5,0,0],'B3':[.8,.1,.1,0],'B18':[.3,.6,0,0],                  # true loadings on (sentiment, activity, investment, inventories)
           'B4':[.1,.85,.1,0],'B5':[.1,.8,.1,0],'B6':[.2,.75,.1,0],'B7':[.1,.6,.3,0],'B8':[.1,.5,.1,0],
           'B9':[0,.3,.8,0],'B10':[0,.2,.75,0],'B11':[.4,0,.6,0],'B12':[0,.1,0,.8],'B13':[0,.2,0,.6],
           'B14':[.3,.7,0,0],'B15':[.75,.3,0,0],'B16':[.85,0,.1,0],'B17':[.7,.1,.2,0]}
    noise = {c: rng.uniform(.5, .75) for c in COLS}  # indicator-specific noise level
    good = pd.DataFrame({c: F @ np.array(Lam[c]) + rng.normal(0, noise[c], T) for c in COLS})   # "better-direction" series
    raw = good.copy()
    for c in COLS: raw[c] = POL[c] * good[c]         # record negative-polarity indicators the way a survey would (higher = worse)
    raw['REF'] = Fa + rng.normal(0, .6, T)           # reference series (output-growth proxy), NOT part of the index
    raw.index = pd.period_range('2010Q1', periods=T, freq='Q').astype(str); raw.index.name = 'Quarter'
    return raw

if not DATA_PATH.exists():                           # create the dataset only if it is not already on the laptop
    simulate_dataset().to_csv(DATA_PATH)             # save it (replace this file with real QES balances later)
data = pd.read_csv(DATA_PATH, index_col=0)           # LOAD the dataset from the laptop
raw = data[COLS]                                     # the 18 indicators as recorded
ref = data['REF'].values if 'REF' in data.columns else None   # reference series (optional)

# ----------------------------------------------------------------------------- 4. COMMON PREPARATION (identical for all methods)
miss_before = raw.isna().sum()                       # (a) count missing values per indicator
raw = raw.interpolate(limit=2, limit_direction='both')   # (a) fill gaps of up to two quarters by linear interpolation
miss_after = raw.isna().sum()                        # missing values left after interpolation
# (seasonal adjustment would be applied here to real QES balances, e.g. with X-13 or STL, before standardising)
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

# ----------------------------------------------------------------------------- 5. THE METHODS
w_eq  = weights_equal(COLS)                          # Method 1a: equal weights, single level
w_eq2 = weights_equal(COLS, PILLARS, True)           # Method 1b: equal weights, two level (pillars equal)
w_pca = weights_pca_only(Z)                          # Method 2: PCA only
w_fa  = weights_fa_only(Z)                           # Method 3: factor analysis only (k by parallel analysis)
w_fa4 = weights_fa_only(Z, k=k_kaiser)               # Method 3b: factor analysis with k = Kaiser number (sensitivity)
w_hyb = weights_hybrid(Z)                            # Method 4: hybrid PCA-FA
cols_w = {'Equal (single level)': w_eq, 'Equal (two level)': w_eq2, 'PCA only': w_pca,
          f'FA only (k={k_pa})': w_fa, f'FA only (k={k_kaiser})': w_fa4, 'Hybrid PCA-FA': w_hyb}
if ref is not None:                                  # Method 5 (extension): reference-based weights
    w_ref, ref_corr = weights_reference(Z, ref); cols_w['Reference-based'] = w_ref
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
leadlag = None                                                  # lead-lag table vs the reference series
if ref is not None:
    leadlag = pd.DataFrame({m: [np.corrcoef(I[m].values[:n-l] if l else I[m].values, ref[l:] if l else ref)[0, 1] for l in range(5)] for m in W.columns},
                           index=[f'Index leads by {l} quarter(s)' for l in range(5)])   # corr of index(t) with reference(t+lead)
rb = np.random.default_rng(5); boot = {'PCA only': [], f'FA only (k={k_pa})': [], 'Hybrid PCA-FA': []}   # bootstrap containers
nb = int(np.ceil(n / BLOCK))                                    # number of blocks needed
for _ in range(N_BOOT):                                         # moving-block bootstrap (keeps time dependence)
    starts = rb.integers(0, n - BLOCK + 1, nb); ii = np.concatenate([np.arange(s, s + BLOCK) for s in starts])[:n]   # resampled quarters
    Zb = Z.iloc[ii].reset_index(drop=True); Zb = (Zb - Zb.mean()) / Zb.std(ddof=1)   # re-standardise the resample
    boot['PCA only'].append(weights_pca_only(Zb).values)
    boot[f'FA only (k={k_pa})'].append(weights_fa_only(Zb, k=k_pa).values)
    boot['Hybrid PCA-FA'].append(weights_hybrid(Zb).values)
boot_sd = pd.DataFrame({m: np.std(np.array(a), 0) for m, a in boot.items()}, index=COLS)   # SD of each weight across resamples

# ----------------------------------------------------------------------------- 7. BUILD THE RESULT SHEETS
sheets = {}                                          # sheet name -> DataFrame (each sheet lists its full result)
names = ['README','Indicators','Raw_Data','Prep_Z_Scores','Prep_Tests','Prep_Indicator_MSA','Correlation_Matrix','Eigenvalues','M1_Equal','M2_PCA_Only',
         'M3_FA_Only','M3b_FA_Kaiser_k','M4_Hybrid','M5_Reference_Based','Weights_All','Pillar_Totals','Indices_All','Method_Comparison','Lead_Lag_vs_Reference',
         'Bootstrap_Stability','Decision_Summary']
desc = ['Guide to the sheets','18 indicators, pillar, polarity','Dataset loaded from your laptop (as recorded)','Polarity-aligned, winsorised, standardised data (common to all methods)',
 'KMO, Bartlett test, Cronbach alpha per pillar, factor-count rules','Measure of sampling adequacy per indicator','Correlation matrix of the prepared indicators','Eigenvalues, variance explained, parallel-analysis thresholds',
 'Equal weights (single and two level)','PCA loadings and weights','FA loadings, communalities and weights (k by parallel analysis)','FA with k = Kaiser rule (sensitivity)',
 'Hybrid rotated loadings, assignment, within/factor/final weights','Reference-based weights (extension)','All weights side by side','Weight per pillar under each method','Index series under each method',
 'Correlations, rank correlations, direction agreement','Correlation of each index with the reference series at leads 0-4','Block-bootstrap standard deviation of weights','Automatic reading of the results']
sheets['README'] = pd.DataFrame({'Sheet': names[1:], 'Content': desc[1:]})
sheets['Indicators'] = pd.DataFrame([(c, META[c][0], META[c][1], '+' if POL[c] > 0 else '-') for c in COLS], columns=['ID','Indicator','Pillar','Polarity'])
sheets['Raw_Data'] = data.reset_index()
sheets['Prep_Z_Scores'] = Z.round(4).reset_index()
sheets['Prep_Tests'] = pd.DataFrame({'Test': ['Quarters (n)','Indicators (p)','Observations per indicator','Missing values before interpolation','Missing values after interpolation','KMO overall',
    'Bartlett chi-square','Bartlett df','Bartlett p-value','Factors: Kaiser rule (eigenvalue>1)','Factors: parallel analysis','Variance explained by Kaiser factors (PCA)']+[f'Cronbach alpha {k}' for k in alpha],
  'Value': [n,p,round(n/p,2),int(miss_before.sum()),int(miss_after.sum()),round(kmo,3),round(chi2,1),dof,pval,k_kaiser,k_pa,round(w_eig[:k_kaiser].sum()/p,3)]+[round(v,3) for v in alpha.values()]})
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
sheets['M5_Reference_Based'] = pd.DataFrame({'ID': COLS, 'Indicator': base_cols['Indicator'], 'Correlation with reference': ref_corr.round(3).values,
    'Reference-based weight': w_ref.values}) if ref is not None else pd.DataFrame({'Note': ['No REF column in the dataset']})
wa = W.reset_index().rename(columns={'index':'ID'}); wa.insert(1, 'Indicator', base_cols['Indicator'])
sheets['Weights_All'] = pd.concat([wa, pd.DataFrame([['Total', '', *W.sum().values]], columns=wa.columns)], ignore_index=True)
sheets['Pillar_Totals'] = pillar_tot.reset_index().rename(columns={'index':'Pillar'})
sheets['Indices_All'] = I.reset_index().rename(columns={'index':'Quarter'})
rows_cmp = []
for title, df_ in [('Correlation of index levels', corr), ('Rank correlation', rank_corr), ('Share of quarters with same direction of change', direction)]:
    rows_cmp.append(pd.DataFrame([[title] + [''] * len(df_.columns)], columns=['Block'] + list(df_.columns)))
    rows_cmp.append(df_.round(3).reset_index().rename(columns={'index': 'Block'}))
sheets['Method_Comparison'] = pd.concat(rows_cmp, ignore_index=True)
sheets['Lead_Lag_vs_Reference'] = leadlag.round(3).reset_index().rename(columns={'index':'Lead'}) if leadlag is not None else pd.DataFrame({'Note': ['No REF column in the dataset']})
bs = boot_sd.reset_index().rename(columns={'index':'ID'})
bs.loc[len(boot_sd)] = ['Mean SD', *boot_sd.mean().values]; bs.loc[len(boot_sd)+1] = ['Max SD', *boot_sd.max().values]
sheets['Bootstrap_Stability'] = bs
min_corr = corr.loc['Equal (single level)'].drop('Equal (single level)').min()      # lowest agreement with single-level equal weights
low_h = [c for c, h_ in zip(COLS, h_fa) if h_ < 0.20]                                  # indicators with communality below 0.20
cross = [COLS[i] for i in range(p) if (np.abs(L_hyb[i]) > 0.4).sum() > 1]              # indicators loading above 0.4 on two or more factors
sheets['Decision_Summary'] = pd.DataFrame({'Item': ['KMO reading','Bartlett test','Number of factors','Lowest correlation with single-level equal weights','Weight of pillar D (inventories): equal / two-level / PCA / FA / hybrid',
    'Indicators with FA communality below 0.20','Cross-loading indicators (hybrid)','Suggested weighting','Reminder'],
  'Result': [f'{kmo:.3f} ({"adequate" if kmo >= 0.6 else "inadequate"})', 'significant' if (not np.isnan(pval) and pval < 0.05) else f'chi-square {chi2:.1f}, df {dof}',
    f'Kaiser = {k_kaiser}, parallel analysis = {k_pa}: report both', f'{min_corr:.3f}',
    ' / '.join(f'{pillar_tot.loc[[x for x in PILLARS if x.startswith("D")][0], m]*100:.1f}%' for m in ['Equal (single level)','Equal (two level)','PCA only',f'FA only (k={k_pa})','Hybrid PCA-FA']),
    ', '.join(low_h) if low_h else 'none', ', '.join(cross) if cross else 'none',
    'Single-level equal weights after deciding how to treat inventories; keep statistical weights as robustness check' if min_corr >= 0.98 else 'Hybrid PCA-FA weights with guard-rails (indices differ materially)',
    'Freeze the weights; re-estimate only at an agreed review. Replace the simulated file by real QES balances (seasonally adjusted) before using the results.']})

# ----------------------------------------------------------------------------- 8. WRITE THE EXCEL WORKBOOK
with pd.ExcelWriter(OUTPUT_XLSX, engine='openpyxl') as xw:       # open the workbook for writing
    for name in names:                                           # one sheet per result block
        df_ = sheets[name]; df_.to_excel(xw, sheet_name=name[:31], index=False)   # Excel limits sheet names to 31 characters
        ws = xw.sheets[name[:31]]; ws.freeze_panes = 'A2'        # keep the header row visible
        for cell in ws[1]: cell.font = Font(bold=True)           # bold header
        for col in ws.columns:                                   # set a readable column width
            ws.column_dimensions[col[0].column_letter].width = min(48, max(10, max(len(str(c.value)) if c.value is not None else 0 for c in col[:60]) + 2))
print(f'Done: {OUTPUT_XLSX} written with {len(sheets)} sheets; dataset at {DATA_PATH}')
