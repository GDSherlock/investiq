"""
EXPERIMENTAL — isolated. Bounded first-pass formula dependency analysis.

Parses direct A1 references (same-sheet, cross-sheet, absolute, ranges, unicode sheet
names, named ranges) to build precedents and reverse dependents. It does NOT evaluate
formulas and it NEVER fabricates a dependency path: an external reference is recorded as
external and produces no internal precedent.
"""

from __future__ import annotations

import re
from typing import Any

# A1 cell token, optional $ anchors: C6, $C$4, D$4, AA12
_CELL = r"\$?[A-Z]{1,3}\$?\d+"
# sheet token: quoted 'anything' OR unquoted (letters/underscore/unicode + word chars, dots)
_SHEET_UNQUOTED = r"[A-Za-z_一-鿿][\w一-鿿.]*"

# external: [1]Sheet!A1  or  [book.xlsx]Sheet!A1  or  'path[book.xlsx]Sheet'!A1
_RE_EXTERNAL = re.compile(r"(?:'[^']*\[[^\]]+\][^']*'|\[[^\]]+\][^\s!]*)!" + _CELL + r"(?::" + _CELL + r")?")
_RE_QUOTED = re.compile(r"'([^']+)'!(" + _CELL + r")(?::(" + _CELL + r"))?")
_RE_UNQUOTED = re.compile(r"(?<![\w'\]])(" + _SHEET_UNQUOTED + r")!(" + _CELL + r")(?::(" + _CELL + r"))?")
_RE_BARE = re.compile(r"(?<![\w$!:'\]])(" + _CELL + r")(?![\w(])")
_RE_IDENT = re.compile(r"(?<![\w!$'\]])([A-Za-z_一-鿿][\w一-鿿.]*)(?!\s*\()")


def is_external_formula(formula: str | None) -> bool:
    """True if the formula references another workbook, e.g. =[1]Rates!B2."""
    return bool(formula) and bool(_RE_EXTERNAL.search(formula))


def _norm(ref: str) -> str:
    return ref.replace("$", "")


def _split_target(target: str) -> str | None:
    """Turn a defined-name target like 'Model!$C$3' or 'Sheet'!$C$3 into 'Model!C3'."""
    t = target.strip().lstrip("=")
    m = re.match(r"^(?:'([^']+)'|(" + _SHEET_UNQUOTED + r"))!(" + _CELL + r")(?::(" + _CELL + r"))?$", t)
    if not m:
        return None
    sheet = m.group(1) or m.group(2)
    cell = _norm(m.group(3))
    return f"{sheet}!{cell}"


def parse_formula_refs(formula: str, current_sheet: str, defined_names: dict[str, str] | None = None) -> dict[str, Any]:
    defined_names = defined_names or {}
    precedents: list[str] = []
    ranges: list[str] = []
    external: list[str] = []
    unsupported: list[str] = []

    if not isinstance(formula, str):
        return {"precedents": [], "ranges": [], "external": [], "unsupported": []}
    expr = formula[1:] if formula.startswith("=") else formula

    # 1) external references first — record and remove so they are not parsed as internal
    for m in _RE_EXTERNAL.finditer(expr):
        external.append(m.group(0))
    expr = _RE_EXTERNAL.sub(" ", expr)

    # 2) quoted-sheet refs
    def _take_quoted(m):
        sheet, c1, c2 = m.group(1), _norm(m.group(2)), m.group(3)
        if c2:
            ranges.append(f"{sheet}!{c1}:{_norm(c2)}")
        else:
            precedents.append(f"{sheet}!{c1}")
        return " "
    expr = _RE_QUOTED.sub(_take_quoted, expr)

    # 3) unquoted-sheet refs (incl. unicode sheet names)
    def _take_unquoted(m):
        sheet, c1, c2 = m.group(1), _norm(m.group(2)), m.group(3)
        if c2:
            ranges.append(f"{sheet}!{c1}:{_norm(c2)}")
        else:
            precedents.append(f"{sheet}!{c1}")
        return " "
    expr = _RE_UNQUOTED.sub(_take_unquoted, expr)

    # 4) bare same-sheet refs / ranges in the remainder
    #    handle ranges A1:B2 first
    for m in re.finditer(r"(" + _CELL + r"):(" + _CELL + r")", expr):
        ranges.append(f"{current_sheet}!{_norm(m.group(1))}:{_norm(m.group(2))}")
    expr = re.sub(r"(" + _CELL + r"):(" + _CELL + r")", " ", expr)
    for m in _RE_BARE.finditer(expr):
        precedents.append(f"{current_sheet}!{_norm(m.group(1))}")
    expr = _RE_BARE.sub(" ", expr)

    # 5) named ranges — only identifiers that are actually defined names count
    for m in _RE_IDENT.finditer(expr):
        token = m.group(1)
        if token in defined_names:
            resolved = _split_target(defined_names[token])
            if resolved:
                precedents.append(resolved)
            else:
                unsupported.append(f"named_range:{token}->{defined_names[token]}")

    # dedupe, preserve order
    def _dedupe(xs):
        seen, out = set(), []
        for x in xs:
            if x not in seen:
                seen.add(x); out.append(x)
        return out

    return {
        "precedents": _dedupe(precedents),
        "ranges": _dedupe(ranges),
        "external": _dedupe(external),
        "unsupported": _dedupe(unsupported),
    }


def build_dependency_graph(iter_formulas, defined_names: dict[str, str] | None = None) -> dict[str, Any]:
    """iter_formulas: iterable of (sheet, coord, formula). Returns precedents/dependents/external."""
    precedents: dict[str, list[str]] = {}
    dependents: dict[str, list[str]] = {}
    external_refs: dict[str, list[str]] = {}
    ranges: dict[str, list[str]] = {}

    for sheet, coord, formula in iter_formulas:
        ref = f"{sheet}!{coord}"
        parsed = parse_formula_refs(formula, sheet, defined_names)
        precedents[ref] = parsed["precedents"]
        ranges[ref] = parsed["ranges"]
        if parsed["external"]:
            external_refs[ref] = parsed["external"]
        for p in parsed["precedents"]:
            dependents.setdefault(p, [])
            if ref not in dependents[p]:
                dependents[p].append(ref)

    return {
        "precedents": precedents,
        "dependents": dependents,
        "external_refs": external_refs,
        "ranges": ranges,
    }


def has_dependents(graph: dict, ref: str) -> bool:
    return bool(graph.get("dependents", {}).get(ref))
