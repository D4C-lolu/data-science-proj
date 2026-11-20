"""Index definitions for the five CBN composite indices.

Each index is described by:

* ``code``       – short identifier used in the ``index_runs.index_type`` column.
* ``name``       – human-readable name shown in the UI.
* ``kind``       – ``"quarterly"`` for time-series indices (BCI, CCI, IPI, LMCI)
                   or ``"household"`` for survey microdata (HFCI).
* ``period_col`` – the column holding the quarter label (quarterly indices only).
* ``columns``    – indicator IDs in the order they should be read.
* ``meta``       – ``{id: (label, pillar, polarity[, source])}``.

``polarity`` is ``+1`` when a higher raw value moves the index up and ``-1``
when it moves the index down. The indicator sets mirror the reference
methodology scripts kept at the repository root.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Indicator:
    code: str
    label: str
    pillar: str
    polarity: int
    source: Optional[str] = None


@dataclass(frozen=True)
class IndexConfig:
    code: str
    name: str
    kind: str
    description: str
    columns: List[str] = field(default_factory=list)
    meta: Dict[str, Indicator] = field(default_factory=dict)
    period_col: Optional[str] = None

    @property
    def polarity(self) -> Dict[str, int]:
        return {c: self.meta[c].polarity for c in self.columns}

    @property
    def pillars(self) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for c in self.columns:
            grouped.setdefault(self.meta[c].pillar, []).append(c)
        return grouped


def _build(code, name, kind, description, rows, period_col=None):
    meta = {}
    columns = []
    for row in rows:
        if len(row) == 5:
            c, label, pillar, polarity, source = row
        else:
            c, label, pillar, polarity = row
            source = None
        meta[c] = Indicator(code=c, label=label, pillar=pillar, polarity=polarity, source=source)
        columns.append(c)
    return IndexConfig(
        code=code,
        name=name,
        kind=kind,
        description=description,
        columns=columns,
        meta=meta,
        period_col=period_col,
    )


BCI = _build(
    "BCI",
    "Business Confidence Index",
    "quarterly",
    "Composite of 18 QES business balances across five pillars: confidence "
    "and constraints, production and sales, investment and capacity, "
    "inventories, and expectations.",
    [
        ("B1", "Business confidence (current)", "A Confidence and constraints", 1),
        ("B2", "Business situation vs last quarter", "A Confidence and constraints", 1),
        ("B3", "Assessment of general economic outlook", "A Confidence and constraints", 1),
        ("B18", "Weak demand cited as main constraint", "A Confidence and constraints", -1),
        ("B4", "Production volume", "B Production and sales", 1),
        ("B5", "Sales / turnover", "B Production and sales", 1),
        ("B6", "New orders / order books", "B Production and sales", 1),
        ("B7", "Profitability", "B Production and sales", 1),
        ("B8", "Export orders", "B Production and sales", 1),
        ("B9", "Capacity utilisation", "C Investment and capacity", 1),
        ("B10", "Capital expenditure", "C Investment and capacity", 1),
        ("B11", "Investment plans (12 months)", "C Investment and capacity", 1),
        ("B12", "Finished-goods stocks above normal", "D Inventories", -1),
        ("B13", "Raw-material stock adequacy", "D Inventories", 1),
        ("B14", "Expected production (3 months)", "E Expectations", 1),
        ("B15", "Expected orders / sales (3 months)", "E Expectations", 1),
        ("B16", "Expected business conditions (12 months)", "E Expectations", 1),
        ("B17", "Expected profitability (12 months)", "E Expectations", 1),
    ],
    period_col="Quarter",
)

CCI = _build(
    "CCI",
    "Credit Conditions Index",
    "quarterly",
    "Composite of 18 credit indicators across five pillars: access and "
    "availability, cost of credit, credit growth and demand, financial "
    "stability, and borrower burden. Higher values mean easier credit.",
    [
        ("C1", "Firms reporting easier access to finance", "A Access and availability", 1),
        ("C2", "Firms denied or discouraged from credit", "A Access and availability", -1),
        ("C3", "Households denied or discouraged from credit", "A Access and availability", -1),
        ("C4", "Firms reporting tighter collateral requirements", "A Access and availability", -1),
        ("C5", "Prime lending rate", "B Cost of credit", -1),
        ("C6", "Maximum lending rate", "B Cost of credit", -1),
        ("C7", "Lending-deposit rate spread", "B Cost of credit", -1),
        ("C8", "Firms reporting higher borrowing costs", "B Cost of credit", -1),
        ("C9", "Real private-sector credit growth (y/y)", "C Credit growth and demand", 1),
        ("C10", "New lending volume growth", "C Credit growth and demand", 1),
        ("C11", "Firms' credit demand balance", "C Credit growth and demand", 1),
        ("C12", "Households taking new loans", "C Credit growth and demand", 1),
        ("C13", "Non-performing loan ratio", "D Financial stability", -1),
        ("C14", "Banking-system liquidity ratio", "D Financial stability", 1),
        ("C15", "Capital adequacy ratio", "D Financial stability", 1),
        ("C16", "Household debt-service-to-income", "E Borrower burden", -1),
        ("C17", "Households in arrears", "E Borrower burden", -1),
        ("C18", "Firms with debt-servicing difficulty", "E Borrower burden", -1),
    ],
    period_col="Quarter",
)

HFCI = _build(
    "HFCI",
    "Household Financial Conditions Index",
    "household",
    "Composite of 18 IHFCS household indicators across five pillars: income "
    "and income stability, consumption, debt burden, savings and liquidity, "
    "and vulnerability and access. Estimated from survey microdata with "
    "design weights and reported as a national index by survey round.",
    [
        ("H1", "Real household income growth", "1 Income and income stability", 1),
        ("H2", "Households reporting income decline", "1 Income and income stability", -1),
        ("H3", "Irregular or volatile income", "1 Income and income stability", -1),
        ("H4", "Multiple income sources", "1 Income and income stability", 1),
        ("H5", "Real consumption growth", "2 Consumption", 1),
        ("H6", "Food share of consumption", "2 Consumption", -1),
        ("H7", "Households cutting consumption", "2 Consumption", -1),
        ("H8", "Debt-to-income ratio", "3 Debt burden", -1),
        ("H9", "Debt-service-to-income ratio", "3 Debt burden", -1),
        ("H10", "Missed or late repayments (arrears)", "3 Debt burden", -1),
        ("H11", "Borrowing to meet basic needs", "3 Debt burden", -1),
        ("H12", "Savings rate", "4 Savings and liquidity", 1),
        ("H13", "Emergency buffer of 3+ months", "4 Savings and liquidity", 1),
        ("H14", "Unable to raise emergency funds", "4 Savings and liquidity", -1),
        ("H15", "Difficulty making ends meet", "5 Vulnerability and access", -1),
        ("H16", "Access to formal financial services", "5 Vulnerability and access", 1),
        ("H17", "Denied or discouraged from credit", "5 Vulnerability and access", -1),
        ("H18", "Expected financial situation (12 months)", "5 Vulnerability and access", 1),
    ],
)

IPI = _build(
    "IPI",
    "Inflation Pressure Index",
    "quarterly",
    "Composite of 18 inflation indicators across five pillars: input and cost "
    "pressures, pricing and pass-through, demand pressure, expectations, and "
    "external. Higher values mean more inflationary pressure.",
    [
        ("I1", "Input cost balance", "A Input and cost pressures", 1),
        ("I2", "Wage cost growth balance", "A Input and cost pressures", 1),
        ("I3", "Imported input cost balance", "A Input and cost pressures", 1),
        ("I4", "Energy and fuel cost balance", "A Input and cost pressures", 1),
        ("I5", "Selling-price change balance", "B Pricing and pass-through", 1),
        ("I6", "Price-increase intentions (3 months)", "B Pricing and pass-through", 1),
        ("I7", "Firms passing on cost increases in full", "B Pricing and pass-through", 1),
        ("I8", "Firms discounting or cutting prices", "B Pricing and pass-through", -1),
        ("I9", "Capacity utilisation above normal", "C Demand pressure", 1),
        ("I10", "New orders / order backlog balance", "C Demand pressure", 1),
        ("I11", "Household real consumption growth", "C Demand pressure", 1),
        ("I12", "Households reporting higher food spending", "C Demand pressure", 1),
        ("I13", "Firms' inflation expectations", "D Expectations", 1),
        ("I14", "Households' inflation expectations (12 months)", "D Expectations", 1),
        ("I15", "Households' perceived current inflation", "D Expectations", 1),
        ("I16", "Firms expecting higher input costs (3 months)", "D Expectations", 1),
        ("I17", "Exchange-rate depreciation (y/y)", "E External", 1),
        ("I18", "Import price growth (y/y)", "E External", 1),
    ],
    period_col="Quarter",
)

LMCI = _build(
    "LMCI",
    "Labour Market Conditions Index",
    "quarterly",
    "Composite of 19 labour-market indicators from the QES and IHFCS across "
    "five pillars: employment and hiring, unemployment and underutilisation, "
    "wages and earnings, productivity and capacity, and job security and "
    "expectations.",
    [
        ("A1", "Net employment balance", "A: Employment and hiring", 1, "QES"),
        ("A2", "Employment growth (y/y)", "A: Employment and hiring", 1, "QES"),
        ("A3", "Vacancy rate", "A: Employment and hiring", 1, "QES"),
        ("A4", "Net hiring intentions", "A: Employment and hiring", 1, "QES"),
        ("A5", "Separation (layoff) rate", "A: Employment and hiring", -1, "QES"),
        ("B1", "Household unemployment rate", "B: Unemployment and underutilisation", -1, "IHFCS"),
        ("B2", "Households with no employed member", "B: Unemployment and underutilisation", -1, "IHFCS"),
        ("B3", "Underemployment rate", "B: Unemployment and underutilisation", -1, "IHFCS"),
        ("B4", "Discouraged / willing-inactive share", "B: Unemployment and underutilisation", -1, "IHFCS"),
        ("C1", "Nominal wage growth", "C: Wages and earnings", 1, "QES"),
        ("C2", "Real wage growth", "C: Wages and earnings", 1, "QES + CPI"),
        ("C3", "Real household labour income growth", "C: Wages and earnings", 1, "IHFCS + CPI"),
        ("C4", "Households reporting job/wage income loss", "C: Wages and earnings", -1, "IHFCS"),
        ("D1", "Output per employee growth", "D: Productivity and capacity", 1, "QES"),
        ("D2", "Capacity utilisation", "D: Productivity and capacity", 1, "QES"),
        ("D3", "Hours per employee", "D: Productivity and capacity", 1, "QES"),
        ("E1", "Expected employment (next 12 months)", "E: Job security and expectations", 1, "QES"),
        ("E2", "Workers fearing job loss", "E: Job security and expectations", -1, "IHFCS"),
        ("E3", "Formal (written contract) employment share", "E: Job security and expectations", 1, "IHFCS"),
    ],
    period_col="Quarter",
)


INDICES: Dict[str, IndexConfig] = {
    cfg.code: cfg for cfg in (BCI, CCI, HFCI, IPI, LMCI)
}

INDEX_ORDER: Tuple[str, ...] = ("BCI", "CCI", "HFCI", "IPI", "LMCI")


def get_config(index_type: str) -> IndexConfig:
    """Return the configuration for an index code, raising ``KeyError`` if unknown."""
    return INDICES[index_type.upper()]