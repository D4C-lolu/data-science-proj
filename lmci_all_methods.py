"""
LMCI weighting: Equal, PCA-only, FA-only and Hybrid PCA-FA on the full 19-indicator / 5-pillar set.
Run on your laptop:  python lmci_all_methods.py
 - Step 0 simulates a quarterly dataset and SAVES it to your laptop (DATA_PATH). Replace that file with your
   real QES/IHFCS indicators (same column names) and the rest of the script runs unchanged.
 - Output: one Excel workbook (OUTPUT_XLSX) with one sheet per result block.
Requires: numpy, pandas, openpyxl  (scipy optional, only for the Bartlett p-value)
"""
import numpy as np                                   # numerical arrays and linear algebra
import pandas as pd                                  # tables (DataFrames) and Excel output
from pathlib import Path                             # portable file paths for your laptop
from openpyxl.styles import Font                     # used to bold the Excel header rows

# ----------------------------------------------------------------------------- 0. SETTINGS
DATA_PATH   = Path("lmci_simulated_dataset.csv")     # where the dataset lives on your laptop (edit if needed)
OUTPUT_XLSX = Path("LMCI_weighting_results.xlsx")    # results workbook created by this script
SEED, T     = 2026, 72                               # random seed (reproducible) and number of quarters
N_BOOT      = 300                                    # bootstrap resamples for weight stability

# ----------------------------------------------------------------------------- 1. YOUR FUNCTIONS (commented)
def standardise(raw, polarity):                      # align polarity then convert to z-scores
    X = raw.copy()                                   # work on a copy so the raw data stay untouched
    for c in X.columns: X[c] = polarity[c] * X[c]    # multiply by +1 or -1 so higher always = stronger labour market
    return (X - X.mean()) / X.std(ddof=1)            # z-score: subtract mean, divide by sample standard deviation

def varimax(L, it=200, tol=1e-9):                    # varimax rotation of a loading matrix L (p indicators x k factors)
    p, k = L.shape; R = np.eye(k); d = 0             # p = indicators, k = factors, R = rotation matrix, d = previous criterion
    for _ in range(it):                              # iterate until the criterion stops improving
        Lr = L @ R                                   # current rotated loadings
        u, s, vt = np.linalg.svd(L.T @ (Lr**3 - Lr @ np.diag((Lr**2).sum(0)) / p))  # SVD of the varimax gradient
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
        w, v = np.linalg.eigh(Rr); o = np.argsort(w)[::-1][:k]   # keep the k largest eigenvalues
        L = v[:, o] * np.sqrt(np.clip(w[o], 0, None))            # factor loadings (negative eigenvalues set to 0)
        hn = np.clip((L ** 2).sum(1), 0, 0.995)      # new communalities, capped to avoid Heywood cases
        if np.max(np.abs(hn - h)) < tol: h = hn; break           # converged: stop
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

def index_from(Z, wts):                              # build the composite index from z-scores and weights
    s = Z @ wts                                      # weighted sum of z-scores for each quarter
    return 100 + 10 * (s - s.mean()) / s.std(ddof=1) # rescale to mean 100 and standard deviation 10

# ----------------------------------------------------------------------------- 2. INDICATOR SET (5 pillars, 19 indicators)
META = {  # id: (name, pillar, source, polarity)  polarity +1 = higher is better, -1 = higher is worse
 'A1':('Net employment balance','A: Employment and hiring','QES',1),'A2':('Employment growth (y/y)','A: Employment and hiring','QES',1),
 'A3':('Vacancy rate','A: Employment and hiring','QES',1),'A4':('Net hiring intentions','A: Employment and hiring','QES',1),
 'A5':('Separation (layoff) rate','A: Employment and hiring','QES',-1),
 'B1':('Household unemployment rate','B: Unemployment and underutilisation','IHFCS',-1),
 'B2':('Households with no employed member','B: Unemployment and underutilisation','IHFCS',-1),
 'B3':('Underemployment rate','B: Unemployment and underutilisation','IHFCS',-1),
 'B4':('Discouraged / willing-inactive share','B: Unemployment and underutilisation','IHFCS',-1),
 'C1':('Nominal wage growth','C: Wages and earnings','QES',1),'C2':('Real wage growth','C: Wages and earnings','QES + CPI',1),
 'C3':('Real household labour income growth','C: Wages and earnings','IHFCS + CPI',1),
 'C4':('Households reporting job/wage income loss','C: Wages and earnings','IHFCS',-1),
 'D1':('Output per employee growth','D: Productivity and capacity','QES',1),'D2':('Capacity utilisation','D: Productivity and capacity','QES',1),
 'D3':('Hours per employee','D: Productivity and capacity','QES',1),
 'E1':('Expected employment (next 12 months)','E: Job security and expectations','QES',1),
 'E2':('Workers fearing job loss','E: Job security and expectations','IHFCS',-1),
 'E3':('Formal (written contract) employment share','E: Job security and expectations','IHFCS',1)}
COLS = list(META)                                                     # indicator IDs in order
POL  = {c: META[c][3] for c in COLS}                                  # polarity dictionary used by standardise()
PILLARS = {}                                                          # pillar -> list of indicator IDs
for c in COLS: PILLARS.setdefault(META[c][1], []).append(c)           # group indicators by pillar

# ----------------------------------------------------------------------------- 3. SIMULATE AND SAVE THE DATASET ("on your laptop")
def simulate_dataset(seed=SEED, T=T):                # builds a quarterly panel from four hidden factors
    rng = np.random.default_rng(seed)                # reproducible randomness
    Cf = np.array([[1,.20,.15,.10],[.20,1,.15,.10],[.15,.15,1,.10],[.10,.10,.10,1]])   # correlation between the 4 hidden factors
    E = rng.normal(size=(T, 4)) @ np.linalg.cholesky(Cf).T            # correlated random shocks
    F = np.zeros((T, 4))                             # hidden factors: hiring, slack, earnings, productivity
    for t in range(T): F[t] = (0.5 * F[t-1] if t > 0 else 0) + E[t]   # AR(1) persistence of 0.5
    F = (F - F.mean(0)) / F.std(0)                   # standardise each hidden factor
    Lam = {'A1':[.85,.1,.1,.1],'A2':[.75,.1,.1,.35],'A3':[.8,.1,.1,.15],'A4':[.78,.15,.1,.1],'A5':[.65,.3,.05,.05],   # true loadings
           'B1':[.1,.85,.1,.05],'B2':[.1,.8,.1,.05],'B3':[.05,.75,.2,.1],'B4':[.1,.7,.15,.05],
           'C1':[.25,.1,.7,.1],'C2':[.1,.1,.78,.1],'C3':[.1,.25,.75,.1],'C4':[.05,.3,.65,.05],
           'D1':[.2,.05,.1,.8],'D2':[.4,.05,.05,.65],'D3':[.2,.05,.05,.7],
           'E1':[.7,.2,.1,.15],'E2':[.15,.6,.25,.05],'E3':[.05,.55,.3,.2]}
    noise = {c: rng.uniform(.45, .7) for c in COLS}  # indicator-specific noise level
    good = pd.DataFrame({c: F @ np.array(Lam[c]) + rng.normal(0, noise[c], T) for c in COLS})   # "better-direction" series
    raw = good.copy()
    for c in COLS: raw[c] = POL[c] * good[c]         # record negative-polarity indicators the way a survey would (higher = worse)
    q = pd.period_range('2008Q1', periods=T, freq='Q').astype(str)    # quarter labels
    raw.index = q; raw.index.name = 'Quarter'
    return raw

if not DATA_PATH.exists():                           # create the dataset only if it is not already on the laptop
    simulate_dataset().to_csv(DATA_PATH)             # save it (replace this file with real data later)
raw = pd.read_csv(DATA_PATH, index_col=0)            # LOAD the dataset from the laptop
raw = raw[COLS]                                      # keep indicators in the standard order

# ----------------------------------------------------------------------------- 4. COMMON PREPARATION (identical for all four methods)
miss_before = raw.isna().sum()                       # (a) count missing values per indicator
raw = raw.interpolate(limit=2, limit_direction='both')   # (a) fill gaps of up to two quarters by linear interpolation
miss_after = raw.isna().sum()                        # missing values left after interpolation
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
    from scipy.stats import chi2 as _c; pval = float(_c.sf(chi2, dof))          # p-value if scipy is installed
except Exception:
    pval = np.nan                                    # otherwise leave blank
def cronbach(cols):                                  # (h) reliability of a pillar
    s = Z[cols]; k = len(cols)                       # standardised indicators of the pillar
    return k/(k-1) * (1 - s.var(ddof=1).sum() / s.sum(axis=1).var(ddof=1))   # alpha formula
alpha = {pl: cronbach(cs) for pl, cs in PILLARS.items()}   # alpha for each pillar
w_eig, v_eig = np.linalg.eigh(R); o = np.argsort(w_eig)[::-1]; w_eig, v_eig = w_eig[o], v_eig[:, o]  # (i) eigenvalues
thr = parallel_threshold(R, n)                       # (i) parallel-analysis thresholds
k_kaiser = int((w_eig > 1).sum()); k_pa = int((w_eig > thr).sum())   # (i) number of factors: Kaiser vs parallel analysis

# ----------------------------------------------------------------------------- 5. THE FOUR METHODS
w_eq  = weights_equal(COLS)                          # Method 1a: equal weights, single level
w_eq2 = weights_equal(COLS, PILLARS, True)           # Method 1b: equal weights, two level (pillars equal)
w_pca = weights_pca_only(Z)                          # Method 2: PCA only
w_fa  = weights_fa_only(Z)                           # Method 3: factor analysis only (k by parallel analysis)
w_fa4 = weights_fa_only(Z, k=k_kaiser)               # Method 3b: factor analysis with k = Kaiser number (sensitivity)
w_hyb = weights_hybrid(Z)                            # Method 4: hybrid PCA-FA
W = pd.DataFrame({'Equal (single level)': w_eq, 'Equal (two level)': w_eq2, 'PCA only': w_pca,
                  f'FA only (k={k_pa})': w_fa, f'FA only (k={k_kaiser})': w_fa4, 'Hybrid PCA-FA': w_hyb})   # all weights side by side

# loadings behind each method (for reporting)
L_pca = fix_sign(v_eig[:, :k_kaiser] * np.sqrt(w_eig[:k_kaiser]))               # unrotated PCA loadings
L_fa, h_fa = paf(R, k_pa); L_fa = fix_sign(varimax(L_fa)) if k_pa > 1 else fix_sign(L_fa)   # FA loadings, communalities
L_fa4, h_fa4 = paf(R, k_kaiser); L_fa4 = fix_sign(varimax(L_fa4))               # FA with k = Kaiser
L_hyb = fix_sign(varimax(v_eig[:, :k_kaiser] * np.sqrt(w_eig[:k_kaiser])))      # hybrid rotated loadings
asg = np.abs(L_hyb).argmax(1); ss_h = (L_hyb**2).sum(0); fw_h = ss_h / ss_h.sum()   # hybrid assignment and factor weights
within = pd.Series([L_hyb[i, asg[i]]**2 / (L_hyb[asg == asg[i], asg[i]]**2).sum() for i in range(p)], index=COLS)  # within-factor weight

# ----------------------------------------------------------------------------- 6. INDICES AND COMPARISON
I = pd.DataFrame({m: index_from(Z, W[m]) for m in W.columns})   # composite index under each weight set
corr = I.corr(); rank_corr = I.rank().corr()                    # level and rank correlations between methods
dI = I.diff().dropna()                                          # quarterly changes
direction = pd.DataFrame({a: {b: (np.sign(dI[a]) == np.sign(dI[b])).mean() for b in W.columns} for a in W.columns})   # share of quarters with same direction
pillar_tot = pd.DataFrame({m: {pl: W.loc[cs, m].sum() for pl, cs in PILLARS.items()} for m in W.columns})   # weight per pillar
rng_b = np.random.default_rng(5); boot = {'PCA only': [], f'FA only (k={k_pa})': [], 'Hybrid PCA-FA': []}   # bootstrap containers
for _ in range(N_BOOT):                                          # resample quarters with replacement
    Zb = Z.iloc[rng_b.integers(0, n, n)].reset_index(drop=True); Zb = (Zb - Zb.mean()) / Zb.std(ddof=1)   # re-standardise the resample
    boot['PCA only'].append(weights_pca_only(Zb).values)
    boot[f'FA only (k={k_pa})'].append(weights_fa_only(Zb, k=k_pa).values)
    boot['Hybrid PCA-FA'].append(weights_hybrid(Zb).values)
boot_sd = pd.DataFrame({m: np.std(np.array(a), 0) for m, a in boot.items()}, index=COLS)   # SD of each weight across resamples

# ----------------------------------------------------------------------------- 7. BUILD THE RESULT SHEETS
sheets = {}                                                      # sheet name -> DataFrame (each sheet lists its full result)
sheets['README'] = pd.DataFrame({'Sheet': ['Indicators','Raw_Data','Prep_Z_Scores','Prep_Tests','Prep_Indicator_MSA','Correlation_Matrix','Eigenvalues',
    'M1_Equal','M2_PCA_Only','M3_FA_Only','M3b_FA_Kaiser_k','M4_Hybrid','Weights_All','Pillar_Totals','Indices_All','Method_Comparison','Bootstrap_Stability','Decision_Summary'],
  'Content': ['19 indicators, pillar, source, polarity','Dataset loaded from your laptop (as recorded, before polarity)','Polarity-aligned, winsorised, standardised data (common to all methods)',
    'KMO, Bartlett test, Cronbach alpha per pillar, factor-count rules','Measure of sampling adequacy per indicator','Correlation matrix of the prepared indicators',
    'Eigenvalues, variance explained, parallel-analysis thresholds','Equal weights (single and two level)','PCA loadings and weights','FA loadings, communalities and weights (k by parallel analysis)',
    'FA with k = Kaiser rule (sensitivity)','Hybrid rotated loadings, assignment, within/factor/final weights','All weights side by side','Weight per pillar under each method',
    'Index series under each method','Correlations, rank correlations, direction agreement','Bootstrap standard deviation of weights','Automatic reading of the results']})
sheets['Indicators'] = pd.DataFrame([(c, *META[c][:3], '+' if POL[c] > 0 else '-') for c in COLS], columns=['ID','Indicator','Pillar','Source','Polarity'])
sheets['Raw_Data'] = raw.reset_index()
sheets['Prep_Z_Scores'] = Z.reset_index()
tests = pd.DataFrame({'Test': ['Quarters (n)','Indicators (p)','Observations per indicator','Missing values before interpolation','Missing values after interpolation','KMO overall',
    'Bartlett chi-square','Bartlett df','Bartlett p-value','Factors: Kaiser rule (eigenvalue>1)','Factors: parallel analysis','Variance explained by Kaiser factors (PCA)']+[f'Cronbach alpha {k}' for k in alpha],
  'Value': [n,p,round(n/p,2),int(miss_before.sum()),int(miss_after.sum()),round(kmo,3),round(chi2,1),dof,pval,k_kaiser,k_pa,round(w_eig[:k_kaiser].sum()/p,3)]+[round(v,3) for v in alpha.values()]})
sheets['Prep_Tests'] = tests
sheets['Prep_Indicator_MSA'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], 'MSA': msa.round(3)})
sheets['Correlation_Matrix'] = pd.DataFrame(R, index=COLS, columns=COLS).round(3).reset_index().rename(columns={'index':'ID'})
sheets['Eigenvalues'] = pd.DataFrame({'Component': range(1, p+1), 'Eigenvalue': w_eig.round(3), '% variance': (w_eig/p*100).round(1),
    'Cumulative %': (np.cumsum(w_eig)/p*100).round(1), 'Parallel threshold': thr.round(3), 'Kaiser (>1)': w_eig > 1, 'Passes parallel': w_eig > thr})
sheets['M1_Equal'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], 'Pillar': [META[c][1] for c in COLS],
    'Weight single level': w_eq.values, 'Weight two level': w_eq2.values})
sheets['M2_PCA_Only'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], **{f'PC{j+1} loading': L_pca[:, j].round(3) for j in range(k_kaiser)}, 'PCA weight': w_pca.values})
sheets['M3_FA_Only'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], **{f'F{j+1} loading': np.atleast_2d(L_fa.T)[j].round(3) for j in range(k_pa)},
    'Communality': h_fa.round(3), 'Flag (<0.20)': h_fa < 0.20, 'FA weight': w_fa.values})
sheets['M3b_FA_Kaiser_k'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], **{f'F{j+1} loading': L_fa4[:, j].round(3) for j in range(k_kaiser)},
    'Communality': h_fa4.round(3), 'FA weight': w_fa4.values})
sheets['M4_Hybrid'] = pd.DataFrame({'ID': COLS, 'Indicator': [META[c][0] for c in COLS], **{f'F{j+1} rotated loading': L_hyb[:, j].round(3) for j in range(k_kaiser)},
    'Assigned factor': [f'F{a+1}' for a in asg], 'Within-factor weight': within.values, 'Factor weight': [fw_h[a] for a in asg], 'Final weight': w_hyb.values})
sheets['Weights_All'] = W.reset_index().rename(columns={'index':'ID'}); sheets['Weights_All'].insert(1, 'Indicator', [META[c][0] for c in COLS])
sheets['Weights_All'] = pd.concat([sheets['Weights_All'], pd.DataFrame([['Total', '', *W.sum().values]], columns=sheets['Weights_All'].columns)], ignore_index=True)
sheets['Pillar_Totals'] = pillar_tot.reset_index().rename(columns={'index':'Pillar'})
sheets['Indices_All'] = I.reset_index().rename(columns={'index':'Quarter'})
cmp_blocks = [('Correlation of index levels', corr), ('Rank correlation', rank_corr), ('Share of quarters with same direction of change', direction)]
rows_cmp = []
for title, df_ in cmp_blocks:
    rows_cmp.append(pd.DataFrame([[title] + [''] * len(df_.columns)], columns=['Block'] + list(df_.columns)))
    rows_cmp.append(df_.round(3).reset_index().rename(columns={'index': 'Block'}))
sheets['Method_Comparison'] = pd.concat(rows_cmp, ignore_index=True)
sheets['Bootstrap_Stability'] = boot_sd.reset_index().rename(columns={'index':'ID'})
sheets['Bootstrap_Stability'].loc[len(boot_sd)] = ['Mean SD', *boot_sd.mean().values]
sheets['Bootstrap_Stability'].loc[len(boot_sd)+1] = ['Max SD', *boot_sd.max().values]
min_corr = corr.loc['Equal (two level)'].drop('Equal (two level)').min()
low_h = [c for c, h_ in zip(COLS, h_fa) if h_ < 0.20]
sheets['Decision_Summary'] = pd.DataFrame({'Item': ['KMO reading','Bartlett test','Number of factors','Lowest correlation of any method with two-level equal weights',
    'Indicators with FA communality below 0.20','Suggested weighting','Reminder'],
  'Result': [f'{kmo:.3f} ({"adequate" if kmo >= 0.6 else "inadequate"})', 'significant' if (not np.isnan(pval) and pval < 0.05) else f'chi-square {chi2:.1f}, df {dof}',
    f'Kaiser = {k_kaiser}, parallel analysis = {k_pa}: report both', f'{min_corr:.3f}', ', '.join(low_h) if low_h else 'none',
    'Two-level equal weights (indices agree closely); keep statistical weights as robustness check' if min_corr >= 0.98 else 'Hybrid PCA-FA weights with guard-rails (indices differ materially)',
    'Freeze the weights; re-estimate only at an agreed review. Replace the simulated file by real QES/IHFCS data before using the results.']})

# ----------------------------------------------------------------------------- 8. WRITE THE EXCEL WORKBOOK
with pd.ExcelWriter(OUTPUT_XLSX, engine='openpyxl') as xw:       # open the workbook for writing
    for name, df_ in sheets.items():                             # one sheet per result block
        df_.to_excel(xw, sheet_name=name[:31], index=False)      # Excel limits sheet names to 31 characters
        ws = xw.sheets[name[:31]]; ws.freeze_panes = 'A2'        # keep the header row visible
        for cell in ws[1]: cell.font = Font(bold=True)            # bold header
        for col in ws.columns:                                   # set a readable column width
            ws.column_dimensions[col[0].column_letter].width = min(48, max(10, max(len(str(c.value)) if c.value is not None else 0 for c in col[:60]) + 2))
print(f'Done: {OUTPUT_XLSX} written with {len(sheets)} sheets; dataset at {DATA_PATH}')
