"""CSV / XLSX import. Cell strings and original row coordinates are preserved.
Formulas and macros are never executed."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from ...schemas import SourceData, SourceRow


class ImportProblem(Exception):
    pass


def _headers(raw: list[str]) -> list[str]:
    out, seen = [], {}
    for i, h in enumerate(raw):
        h = (h or "").strip() or f"Column {i+1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        out.append(h)
    return out


def _finish(kind, filename, sheet, sheets, header_row, grid, max_rows, extra_findings=None, warnings=None) -> SourceData:
    """grid: list of (original_row_index, [cell strings]) after the header row."""
    if not grid:
        raise ImportProblem("The file has no header row at that position.")
    (_, hdr_raw), body = grid[0], grid[1:]
    headers = _headers(hdr_raw)
    rows: list[SourceRow] = []
    for idx, cells in body:
        if not any((c or "").strip() for c in cells) and not (extra_findings or {}).get(idx):
            continue
        cells = (list(cells) + [""] * len(headers))[:len(headers)]
        rows.append(SourceRow(row_id=f"r{len(rows)+1}", sheet=sheet, row_index=idx,
                              cells=dict(zip(headers, cells)),
                              findings=(extra_findings or {}).get(idx, [])))
    if len(rows) > max_rows:
        raise ImportProblem(f"The file has {len(rows)} data rows; the limit is {max_rows}. Split the file or raise MAX_ROWS.")
    return SourceData(filename=filename, kind=kind, sheet=sheet, sheets=sheets, header_row=header_row,
                      headers=headers, rows=rows, warnings=warnings or [])


def parse_csv(data: bytes, filename: str, header_row: int, max_rows: int) -> SourceData:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportProblem("This CSV is not valid UTF-8. Re-save it as 'CSV UTF-8' so names keep their exact letters; "
                            "CertProof will not guess an encoding.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    grid = [(i + 1, row) for i, row in enumerate(csv.reader(io.StringIO(text), dialect))]
    grid = [g for g in grid if g[0] >= header_row]
    return _finish("csv", filename, "csv", ["csv"], header_row, grid, max_rows)


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def parse_xlsx(data: bytes, filename: str, sheet: str | None, header_row: int, max_rows: int) -> SourceData:
    from openpyxl import load_workbook
    try:
        wb_v = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
        wb_f = load_workbook(io.BytesIO(data), data_only=False, read_only=False)
    except Exception as e:
        raise ImportProblem("This file could not be read as an .xlsx workbook.") from e
    sheets = wb_v.sheetnames
    sheet = sheet if sheet in sheets else sheets[0]
    wv, wf = wb_v[sheet], wb_f[sheet]
    if wv.max_row and wv.max_row - header_row > max_rows * 5:
        raise ImportProblem(f"The sheet has far more than {max_rows} rows; split it first.")
    grid, findings, warnings = [], {}, []
    id_cols_numeric = set()
    hdr_cells = [c.value for c in wv[header_row]] if wv.max_row >= header_row else []
    for r in range(header_row, wv.max_row + 1):
        row = []
        for c in range(1, wv.max_column + 1):
            cv, cf = wv.cell(r, c), wf.cell(r, c)
            if cf.data_type == "f" and cv.value is None:
                findings.setdefault(r, []).append("FORMULA_NO_CACHED_VALUE")
            if r > header_row and isinstance(cv.value, (int, float)) and not isinstance(cv.value, bool):
                h = str(hdr_cells[c - 1] if c - 1 < len(hdr_cells) else "")
                if "id" in h.lower():
                    id_cols_numeric.add(h)
            if r > header_row and isinstance(cv.value, (datetime, date)):
                findings.setdefault(r, []).append("DATE_CELL_ISO")
            row.append(_cell_str(cv.value))
        grid.append((r, row))
    if any("FORMULA_NO_CACHED_VALUE" in f for f in findings.values()):
        warnings.append("Some formula cells have no cached value (the file was never opened and saved in Excel). "
                        "Those cells are empty here and need review. Formulas are never executed.")
    if id_cols_numeric:
        warnings.append("Column(s) " + ", ".join(sorted(id_cols_numeric)) +
                        " hold numeric cells; leading zeros may already have been lost. Store IDs as text.")
    if any("DATE_CELL_ISO" in f for f in findings.values()):
        warnings.append("Date cells are shown as ISO dates (YYYY-MM-DD). Confirm the final event date text yourself.")
    return _finish("xlsx", filename, sheet, sheets, header_row, grid, max_rows, findings, warnings)


def parse_upload(data: bytes, filename: str, sheet: str | None, header_row: int, max_rows: int) -> SourceData:
    low = filename.lower()
    if low.endswith((".xlsm", ".xlsb", ".xls")):
        raise ImportProblem("Macro-enabled and legacy Excel files are not accepted. Save as .xlsx or .csv.")
    if low.endswith(".xlsx"):
        return parse_xlsx(data, filename, sheet, header_row, max_rows)
    if low.endswith((".csv", ".txt", ".tsv")):
        return parse_csv(data, filename, header_row, max_rows)
    raise ImportProblem("Unsupported file type. Use .csv or .xlsx.")


def manual_source(rows: list[dict]) -> SourceData:
    headers = ["Name", "Organisation", "Award", "ID"]
    out = []
    for i, r in enumerate(rows):
        cells = {"Name": r.get("name", ""), "Organisation": r.get("organisation", ""),
                 "Award": r.get("award", ""), "ID": r.get("recipient_id", "")}
        out.append(SourceRow(row_id=f"r{i+1}", sheet="manual", row_index=i + 1, cells=cells))
    return SourceData(filename="manual entry", kind="manual", sheet="manual", sheets=["manual"], header_row=0,
                      headers=headers, rows=out)


def paste_source(text: str) -> SourceData:
    names = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    return manual_source([{"name": n.strip()} for n in names])
