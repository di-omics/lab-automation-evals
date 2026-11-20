"""A simulated plate reader, and a grader that works from plate-reader output alone.

The same checks grade a simulated run (reads computed from the simulated plate) or a real run
(a CSV exported from a real reader after the plan ran with a fluorescent dye in place of the
compounds). The grader never sees volumes or the plan: only what the reader saw.

Reads are a dict: {"assay": {well: value}, "blank": [values], "standard": [values], "problems": [text]}.
"blank" holds plain buffer read on a second plate; "standard" holds a hand-made solution at the
top concentration, read on the same second plate.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import statistics

from .environment import ROWS

TRACE_FRACTION = 5e-4  # a foreign trace reads as 0.05% of its stock concentration (a modelling choice)
REF_VOLUME_UL = 100.0  # signal scales with the amount of dye in the well (concentration x fill volume)
WELL_RE = re.compile(r"^\s*([A-Ha-h])\s*0*(\d{1,2})\s*$|^\s*0*(\d{1,2})\s*([A-Ha-h])\s*$")
RFU_NAMES = ("rfu", "value", "signal", "reading", "fluorescence")
ASSAY_LABELS = {"assay", "assay plate"}
BLANK_LABELS = {"blank", "blanks", "blank plate"}
STANDARD_LABELS = {"standard", "standards", "std", "standard plate"}  # anything else (e.g. "Blank SD") is refused


def _noise(key: str) -> float:
    """A deterministic draw, roughly standard normal (sum of 4 uniforms, bounded at +/-3.46), from a key."""
    h = hashlib.sha256(key.encode()).digest()
    u = [int.from_bytes(h[i : i + 4], "big") / 2**32 for i in range(0, 16, 4)]
    return (sum(u) - 2.0) / math.sqrt(4 / 12)


def _read_value(model: dict, signal: float, key: str) -> float:
    value = model["background"] + model["gain"] * signal
    sd = math.hypot(model["sd_add"], model["cv"] * value)
    return round(min(model["saturation"], max(0.0, value + sd * _noise(key))), 1)


def simulate_read(deck, labware: str, model: dict, tag: str = "") -> dict:
    """Read every well of `labware`, plus 8 blanks and 8 hand-made top standards on a second plate."""
    lw = deck[labware]
    assay = {}
    for w, well in lw.wells.items():
        signal = 0.0
        for liquid, stock in model["dyes"].items():
            signal += well.concentration(liquid, stock) * well.volume / REF_VOLUME_UL
            if liquid in well.traces and well.composition().get(liquid, 0.0) <= 0.0:
                signal += TRACE_FRACTION * stock  # a foreign trace; a liquid present by volume is already counted
        assay[w] = _read_value(model, signal, f"{tag}:{labware}:{w}")
    blank = [_read_value(model, 0.0, f"{tag}:blank:{i}") for i in range(8)]
    standard = [_read_value(model, model["standard_conc"], f"{tag}:standard:{i}") for i in range(8)]
    return {"assay": assay, "blank": blank, "standard": standard, "problems": []}


def reads_to_csv(reads: dict) -> str:
    buf = io.StringIO()
    buf.write("plate,well,rfu\n")
    for w, v in reads["assay"].items():
        buf.write(f"assay,{w},{v}\n")
    for name in ("blank", "standard"):
        for i, v in enumerate(reads[name]):
            buf.write(f"{name},{ROWS[i]}1,{v}\n")
    return buf.getvalue()


GROUPED_DOT_DECIMAL = re.compile(r"^[-+]?\d{1,3}(,\d{3})+\.\d+$")
GROUPED_COMMA_DECIMAL = re.compile(r"^[-+]?\d{1,3}(\.\d{3})+,\d+$")
LONE = re.compile(r"^[-+]?\d+([.,])(\d+)$")


def _clean(text: str) -> str:
    return text.strip().replace(" ", "").replace(chr(0xA0), "")


def _decimal_mark(values) -> str | None:
    """The file's decimal mark, from values that settle it; None if no value settles it."""
    votes = set()
    for v in values:
        t = _clean(v)
        if GROUPED_DOT_DECIMAL.match(t):
            votes.add(".")
        elif GROUPED_COMMA_DECIMAL.match(t):
            votes.add(",")
        else:
            m = LONE.match(t)
            if m and len(m.group(2)) != 3:  # 1, 2 or 4+ digits after a lone mark: it is a decimal mark
                votes.add(m.group(1))
    return votes.pop() if len(votes) == 1 else None


def _number(text: str, mark: str | None) -> float | None:
    """Parse one value. With no settled decimal mark, a lone mark before exactly 3 digits is ambiguous: refuse it."""
    t = _clean(text)
    if not t:
        return None
    if "," in t and "." in t:
        if mark is None:
            mark = "." if t.rfind(".") > t.rfind(",") else ","
        group = "," if mark == "." else "."
        t = t.replace(group, "").replace(",", ".")
    elif "," in t or "." in t:
        m = LONE.match(t)
        if m is None:
            return None
        sep = m.group(1)
        if mark is None and len(m.group(2)) == 3:
            return None  # "12,345" or "12.345": thousands or decimals? refuse rather than guess
        if mark is not None and sep != mark:
            t = t.replace(sep, "")  # a grouping mark
        else:
            t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _well(text: str) -> str | None:
    m = WELL_RE.match(text or "")
    if not m:
        return None
    row, col = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    col = int(col)
    return f"{row.upper()}{col}" if 1 <= col <= 12 else None


def read_export(path) -> str:
    """Read a reader export as text: UTF-8 (with or without BOM), UTF-16 with BOM, else Latin-1."""
    raw = open(path, "rb").read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def csv_to_reads(text: str) -> dict:
    """Parse a reader export with columns plate, well, rfu. Unreadable rows become problems, never exceptions."""
    reads = {"assay": {}, "blank": [], "standard": [], "problems": []}
    text = text.lstrip(chr(0xFEFF))
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        reads["problems"].append("the file is empty")
        return reads
    header = [h.strip().lower() for h in rows[0]]
    try:
        i_plate = header.index("plate")
        i_well = header.index("well")
        i_val = next(header.index(n) for n in RFU_NAMES if n in header)
    except (ValueError, StopIteration):
        reads["problems"].append(f"need columns plate, well and rfu; found {header}")
        return reads
    body = [(n, row) for n, row in enumerate(rows[1:], start=2) if any(cell.strip() for cell in row)]
    mark = _decimal_mark(row[i_val] for _, row in body if len(row) > i_val)
    for n, row in body:
        if len(row) <= max(i_plate, i_well, i_val):
            reads["problems"].append(f"line {n}: too few columns")
            continue
        plate = row[i_plate].strip().lower()
        value = _number(row[i_val], mark)
        if value is None:
            reads["problems"].append(f"line {n}: unreadable or ambiguous value {row[i_val].strip()!r}")
            continue
        if plate in BLANK_LABELS:
            reads["blank"].append(value)
        elif plate in STANDARD_LABELS:
            reads["standard"].append(value)
        elif plate in ASSAY_LABELS:
            w = _well(row[i_well])
            if w is None:
                reads["problems"].append(f"line {n}: unreadable well {row[i_well].strip()!r}")
            elif w in reads["assay"]:
                reads["problems"].append(f"line {n}: well {w} appears twice")
            else:
                reads["assay"][w] = value
        else:
            reads["problems"].append(f"line {n}: unknown plate label {row[i_plate].strip()!r}")
    return reads


def _fail_all(names, detail):
    return {n: {"passed": False, "detail": detail} for n in names}


CHECK_NAMES = ["reader_input", "controls_clean", "tops_equal", "top_matches_standard", "dilution_series"]


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_reads(reads: dict, cfg: dict) -> dict:
    """Checks on reader output: valid input, clean controls, equal tops, the right top level, and a 3-fold series."""
    problems = list(reads.get("problems", []))
    blank = [v for v in reads.get("blank", []) if _finite(v)]
    standard = [v for v in reads.get("standard", []) if _finite(v)]
    assay = {w: v for w, v in reads.get("assay", {}).items() if _finite(v)}
    if len(blank) < cfg["min_blanks"]:
        problems.append(f"{len(blank)} usable blank reads; need {cfg['min_blanks']}")
    if len(standard) < cfg["min_standards"]:
        problems.append(f"{len(standard)} usable standard reads; need {cfg['min_standards']}")
    missing = [f"{r}{c}" for c in range(1, 13) for r in ROWS if f"{r}{c}" not in assay]
    if missing:
        problems.append(f"{len(missing)} assay wells missing or unreadable, first {missing[0]}")
    saturated = [w for w, v in assay.items() if v >= cfg["saturation"]]
    if saturated:
        problems.append(f"{len(saturated)} wells at the reader's ceiling, first {saturated[0]}")
    cv_std = None
    if len(blank) >= 2 and len(standard) >= 2:
        std_net_med = statistics.median(standard) - statistics.median(blank)
        if std_net_med <= 0:
            problems.append("the hand-made standards read as blank")
        else:
            # The gate uses a robust spread (median absolute deviation), so one stray standard does not refuse
            # the plate. Tolerances widen with the ordinary CV, which estimates noise better from 8 reads;
            # the caps below keep a stray standard from widening them far.
            mad = statistics.median(abs(v - statistics.median(standard)) for v in standard)
            robust_cv = 1.4826 * mad / std_net_med
            cv_std = statistics.stdev(standard) / std_net_med
            if robust_cv > cfg["max_standard_cv"]:
                problems.append(f"the hand-made standards disagree (robust CV {robust_cv:.1%}): re-read or re-make them")
    if problems:
        out = {"reader_input": {"passed": False, "detail": "; ".join(problems[:4])}}
        out.update(_fail_all(CHECK_NAMES[1:], "reader input is not usable"))
        return out
    fields = {"reader_input": {"passed": True, "detail": f"96 wells, {len(blank)} blanks, {len(standard)} standards"}}

    b_mean = statistics.fmean(blank)
    b_sd = max(statistics.stdev(blank), cfg["min_blank_sd"])
    net = {w: v - b_mean for w, v in assay.items()}

    dirty = [f"{r}{c}" for c in cfg["control_cols"] for r in ROWS if net[f"{r}{c}"] > cfg["control_sd"] * b_sd]
    fields["controls_clean"] = {"passed": not dirty,
                                "detail": "control wells read as blank" if not dirty else f"signal in {', '.join(dirty[:8])}"}

    # Tolerances widen with the replicate noise measured in the standards, within caps. Single wells get k x CV;
    # the median of 8 tops against the median of the standards gets k x its standard error (about 0.63 x CV).
    top_tol = min(cfg["top_tol_cap"], max(cfg["top_tol"], cfg["k_cv"] * cv_std))
    std_tol = min(cfg["standard_tol_cap"], max(cfg["standard_tol"], cfg["k_cv"] * 0.63 * cv_std))
    tops = {r: net[f"{r}{cfg['top_col']}"] for r in ROWS}
    med = statistics.median(tops.values())
    off = [r for r, v in tops.items() if med <= 0 or abs(v - med) > top_tol * med]
    fields["tops_equal"] = {"passed": not off,
                            "detail": "top wells agree" if not off else f"rows off the median top: {', '.join(off)}"}

    std_net = statistics.median(standard) - b_mean
    ok_std = std_net > 0 and abs(med - std_net) <= std_tol * std_net
    fields["top_matches_standard"] = {
        "passed": ok_std,
        "detail": f"top wells read {med / std_net:.2f} x the hand-made standard" if std_net > 0 else "standard reads as blank"}

    visible = cfg["visible_sd"] * b_sd  # a column expected to read above this must read as expected
    expected_cols = [c for c in cfg["series_cols"]
                     if std_net / cfg["fold"] ** (c - cfg["series_cols"][0]) > visible]
    bad, folds = [], []
    if len(expected_cols) < cfg["min_points"]:
        bad.append(f"only {len(expected_cols)} columns are expected above the visibility limit")
    for r in ROWS:
        pts = []
        for i, c in enumerate(expected_cols):
            want = std_net / cfg["fold"] ** i
            got = net[f"{r}{c}"]
            # expected relative noise of this column: additive (blank SD) plus proportional (standards' CV,
            # with a little extra for the noise in the standard itself), widened k times, within a cap
            rel_sd = math.hypot(b_sd / want, 1.1 * cv_std)
            col_tol = min(cfg["column_tol_cap"], max(cfg["column_tol"], cfg["k_cv"] * rel_sd))
            if got <= 0 or abs(math.log(got / want)) > math.log(1 + col_tol):
                bad.append(f"{r}{c} reads {max(got, 0) / want:.2f} x its expected signal")
            if got > 0:
                pts.append((c, math.log(got)))
        if len(pts) >= 2:
            n = len(pts)
            mx = sum(x for x, _ in pts) / n
            my = sum(y for _, y in pts) / n
            slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
            folds.append(math.exp(-slope))
            if abs(folds[-1] - cfg["fold"]) > cfg["fold_tol"] * cfg["fold"]:
                bad.append(f"row {r}: {folds[-1]:.2f}-fold per column")
    detail = (f"columns {expected_cols[0]}-{expected_cols[-1]} as expected in all 8 rows, "
              f"{min(folds):.2f}- to {max(folds):.2f}-fold per column" if not bad and folds else "; ".join(bad[:4]))
    fields["dilution_series"] = {"passed": not bad, "detail": detail}
    return fields


def grade_reads(reads: dict, cfg: dict) -> dict:
    fields = check_reads(reads, cfg)
    n = sum(f["passed"] for f in fields.values())
    return {"passed": n == len(fields), "score": round(n / len(fields), 4), "fields": fields}


def grade_plan_by_reader(answer, task_config: dict, reader_config: dict, tag: str = "la01") -> dict:
    """Run the plan in the simulator, read the plate with the simulated reader, grade the reads."""
    from .grade import parse_answer
    from .sim import run

    ans = parse_answer(answer)
    plan = ans.get(task_config["plan_key"]) if ans else None
    res = run(task_config["deck"], plan if plan is not None else "missing")
    if not res.ok:
        return {"passed": False, "score": 0.0,
                "fields": {"run_completes": {"passed": False, "detail": str(res.error)}}}
    reads = simulate_read(res.deck, reader_config["labware"], reader_config["model"], tag=tag)
    out = grade_reads(reads, reader_config["checks"])
    out["fields"] = {"run_completes": {"passed": True, "detail": "completed"}, **out["fields"]}
    out["reads"] = reads
    return out
