"""Source-data helpers and checks (deterministic, no AI)."""
from __future__ import annotations

from ...schemas import ConfirmedMapping, Issue, SourceRow
from ..verification.common import make_issue, norm_cmp


def mapped_values(row: SourceRow, m: ConfirmedMapping) -> dict[str, str]:
    def g(col):
        return row.cells.get(col, "") if col else ""
    return {"name": g(m.name), "organisation": g(m.organisation), "award": g(m.award),
            "recipient_id": g(m.recipient_id)}


def source_issues(rows: list[SourceRow], m: ConfirmedMapping, require_name: bool = True) -> list[Issue]:
    issues: list[Issue] = []
    seen_full: dict[tuple, SourceRow] = {}
    ids: dict[str, SourceRow] = {}
    for r in rows:
        v = mapped_values(r, m)
        if require_name and not norm_cmp(v["name"]):
            issues.append(make_issue("MISSING_SOURCE_VALUE", row_id=r.row_id, row_index=r.row_index, field="name",
                                     message=f"Row {r.row_index} has no recipient name."))
        key = tuple(sorted((k, norm_cmp(x)) for k, x in r.cells.items()))
        if key in seen_full and any(x for _, x in key):
            first = seen_full[key]
            issues.append(make_issue("DUPLICATE_SOURCE_ROW", row_id=r.row_id, row_index=r.row_index,
                                     message=f"Row {r.row_index} is identical to row {first.row_index}."))
        else:
            seen_full[key] = r
        rid = norm_cmp(v["recipient_id"])
        if rid:
            if rid in ids and norm_cmp(mapped_values(ids[rid], m)["name"]) != norm_cmp(v["name"]):
                f = ids[rid]
                issues.append(make_issue(
                    "CONFLICTING_RECIPIENT_ID", row_id=r.row_id, row_index=r.row_index, field="recipient_id",
                    expected=mapped_values(f, m)["name"], actual=v["name"],
                    message=f"ID '{rid}' is used by row {f.row_index} and row {r.row_index} for different names."))
            ids.setdefault(rid, r)
    return issues
