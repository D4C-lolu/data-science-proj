"""Serialise a computed index result into CSV, Excel, or JSON.

The result dictionary produced by :mod:`app.indices.calculators` contains an
ordered list of ``sections``. Tabular sections become sheets (Excel) or files
(CSV), while chart sections are flattened into simple tables so exports remain
portable.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone


def _chart_to_table(section):
    columns = ["period"] + list(section["series"].keys())
    rows = []
    for i, period in enumerate(section["x"]):
        row = {"period": period}
        for name, values in section["series"].items():
            row[name] = values[i] if i < len(values) else None
        rows.append(row)
    return columns, rows


def iter_tables(result):
    """Yield ``(sheet_name, columns, rows)`` for every section in the result."""
    base = result.get("index_type", "INDEX")
    used = set()
    for index, section in enumerate(result.get("sections", []), start=1):
        if section["kind"] == "table":
            columns, rows = section["columns"], section["rows"]
            title = section["title"]
        elif section["kind"] == "chart":
            columns, rows = _chart_to_table(section)
            title = section["title"]
        else:
            continue
        name = _sheet_name(f"{index:02d} {title}")
        while name in used:
            name = _sheet_name(name + " ")
        used.add(name)
        yield base, name, columns, rows


def _sheet_name(name):
    return name[:31]


def to_json(result):
    payload = dict(result)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(payload, indent=2, default=str)


def to_csv(result):
    """Return a UTF-8 CSV string for the primary (index series) table."""
    series = next((s for s in result.get("sections", []) if s["key"] == "index_series" and s["kind"] == "table"), None)
    if series is None:
        series = next((s for s in result.get("sections", []) if s["kind"] == "table"), None)
    if series is None:
        return ""
    lines = [",".join(series["columns"])]
    for row in series["rows"]:
        lines.append(",".join(_csv_cell(row.get(c)) for c in series["columns"]))
    return "\n".join(lines) + "\n"


def _csv_cell(value):
    if value is None:
        return ""
    text = str(value)
    if any(ch in text for ch in (",", '"', "\n")):
        return '"' + text.replace('"', '""') + '"'
    return text


def to_excel(result):
    """Return the bytes of an ``.xlsx`` workbook with one sheet per section."""
    import pandas as pd
    from openpyxl.styles import Font

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        meta = result.get("meta", {})
        overview = pd.DataFrame(
            {
                "Field": ["Index", "Name", "Observations", "Indicators", "KMO", "Bartlett p-value", "Generated at"],
                "Value": [
                    result.get("index_type"),
                    result.get("index_name"),
                    meta.get("n"),
                    meta.get("p"),
                    meta.get("kmo"),
                    meta.get("bartlett_p"),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                ],
            }
        )
        overview.to_excel(writer, sheet_name="Overview", index=False)

        used = {"Overview"}
        for _base, name, columns, rows in iter_tables(result):
            name = name[:31]
            while name in used:
                name = (name + " ")[:31]
            used.add(name)
            frame = pd.DataFrame(rows, columns=columns)
            frame.to_excel(writer, sheet_name=name, index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            for cell in worksheet[1]:
                cell.font = Font(bold=True)
            for column_cells in worksheet.columns:
                width = max((len(str(c.value)) if c.value is not None else 0) for c in column_cells[:60])
                worksheet.column_dimensions[column_cells[0].column_letter].width = min(48, max(10, width + 2))

    buffer.seek(0)
    return buffer.getvalue()