#!/usr/bin/env python3
"""datapipe : pipeline d'analyse de données pour petites entreprises.
Data-analysis pipeline for small businesses: load several files, clean them, join them,
compute metrics and write an HTML report plus JSON/CSV files for a dashboard.

Python standard library only. No API key. Everything is described in one JSON config.

  python datapipe.py run     --config config.json
  python datapipe.py profile data/jobs.csv

See README.md and config.example.json.
"""
import argparse, ast, csv, html, io, json, math, re, statistics, sys, unicodedata, urllib.request, zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

__version__ = "0.1.0"

MISSING = {"", "n/a", "na", "null", "none", "nan", "-", "--", "#n/a"}
STR = {
    "fr": dict(report="Rapport d'analyse", generated="Généré le {d}. Données lues dans {n} fichier(s).", kpis="Chiffres clés", findings="Constats",
               quality="Qualité des données", rows_in="Lignes lues", rows_out="Lignes gardées", dup="Doublons retirés", dropped="Lignes sans valeur requise",
               invalid="Valeurs illisibles", missing="Manquant", outliers="Valeurs extrêmes", none="aucun", total="Total", n="Nb", change="Variation",
               top="{g} domine : {v} ({s} % du total).", up="{p} : {v}, en hausse de {c} % par rapport à {q}.", down="{p} : {v}, en baisse de {c} % par rapport à {q}.",
               flat="{p} : {v}, stable par rapport à {q}.", best="Meilleure période : {p} ({v}). Plus faible : {w} ({x}).",
               trend_up="Sur la durée, la deuxième moitié de la période est au-dessus de la première ({c} %).",
               trend_down="Sur la durée, la deuxième moitié de la période est sous la première ({c} %).", nofind="Aucun constat automatique pour ces données.",
               col="Colonne", empty="Aucune ligne à afficher.", partial="période incomplète"),
    "en": dict(report="Analysis report", generated="Generated on {d}. Data read from {n} file(s).", kpis="Key figures", findings="Findings",
               quality="Data quality", rows_in="Rows read", rows_out="Rows kept", dup="Duplicates removed", dropped="Rows missing a required value",
               invalid="Unreadable values", missing="Missing", outliers="Outliers", none="none", total="Total", n="Count", change="Change",
               top="{g} leads: {v} ({s}% of the total).", up="{p}: {v}, up {c}% from {q}.", down="{p}: {v}, down {c}% from {q}.",
               flat="{p}: {v}, flat compared with {q}.", best="Best period: {p} ({v}). Weakest: {w} ({x}).",
               trend_up="Over time, the second half of the period is above the first ({c}%).",
               trend_down="Over time, the second half of the period is below the first ({c}%).", nofind="No automatic finding for this data.",
               col="Column", empty="No rows to show.", partial="incomplete period"),
}


# ----------------------------------------------------------------------------- helpers
def deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_header(s):
    return re.sub(r"[^a-z0-9]+", "_", deaccent(str(s)).lower()).strip("_")


def parse_number(s):
    """'1 234,56 $' -> 1234.56 ; '(12.50)' -> -12.5 ; '1,234.56' -> 1234.56."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if t.lower() in MISSING:
        return None
    t = re.sub(r"[$€£\s  ]", "", t)      # currency symbols and spaces
    if not re.fullmatch(r"[-+(]?\d[\d.,]*\)?-?", t):  # anything else (letters, slashes) is not a number
        return None
    neg = t.startswith("(") and t.endswith(")") or t.endswith("-") or t.startswith("-")
    t = re.sub(r"[^\d.,]", "", t)
    if not t:
        return None
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in t:
        t = t.replace(",", ".") if re.search(r",\d{1,2}$", t) and t.count(",") == 1 else t.replace(",", "")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


DATE_FORMATS = {"dmy": ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"],
                "mdy": ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y"]}


def parse_date(s, order="dmy", formats=None):
    if s is None:
        return None
    if isinstance(s, (datetime, date)):
        return s.date() if isinstance(s, datetime) else s
    t = str(s).strip()
    if t.lower() in MISSING:
        return None
    if re.fullmatch(r"\d{4,6}(\.\d+)?", t):  # Excel serial number
        n = float(t)
        if 20000 < n < 80000:
            return (datetime(1899, 12, 30) + timedelta(days=n)).date()
    t = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", "", t)
    for f in (formats or DATE_FORMATS[order]):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def parse_bool(s):
    t = str(s).strip().lower()
    if t in ("1", "true", "vrai", "oui", "yes", "y", "o"):
        return True
    if t in ("0", "false", "faux", "non", "no", "n"):
        return False
    return None


def fmt_num(v, unit="", lang="fr"):
    if v is None:
        return "—"
    if abs(v) >= 100 or float(v).is_integer():
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.2f}"
    s = s.replace(",", " ") if lang == "fr" else s
    if lang == "fr":
        s = s.replace(".", ",")
    if unit in ("$", "€", "£"):
        return f"{s} {unit}" if lang == "fr" else f"{unit}{s}"
    return f"{s} {unit}" if unit else s


# ----------------------------------------------------------------------------- loading
def read_xlsx(raw, sheet=None):
    """Minimal .xlsx reader (first sheet or the named one). Returns a list of rows (lists of strings)."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        names = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        target = names[0]
        if sheet and "xl/workbook.xml" in z.namelist():
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            for i, s in enumerate(wb.find("m:sheets", ns)):
                if s.get("name") == sheet and i < len(names):
                    target = names[i]
        rows = []
        for r in ET.fromstring(z.read(target)).iter("{%s}row" % ns["m"]):
            row = {}
            for c in r.findall("m:c", ns):
                col = re.match(r"[A-Z]+", c.get("r")).group(0)
                idx = 0
                for ch in col:
                    idx = idx * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else ""
                row[idx] = val
            if row:
                rows.append([row.get(i, "") for i in range(1, max(row) + 1)])
        return rows


def load_rows(spec, root):
    """Return (list of dict with string values, origin label)."""
    kind = (spec.get("type") or "").lower()
    if spec.get("url"):
        req = urllib.request.Request(spec["url"], headers={"User-Agent": "datapipe/%s" % __version__})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, origin = r.read(50_000_000), spec["url"]
        kind = kind or ("xlsx" if spec["url"].split("?")[0].endswith(".xlsx") else "csv")
    else:
        p = (root / spec["path"]).resolve() if not Path(spec["path"]).is_absolute() else Path(spec["path"])
        raw, origin = p.read_bytes(), str(p)
        kind = kind or {".xlsx": "xlsx", ".json": "json"}.get(p.suffix.lower(), "csv")
    if kind == "xlsx":
        table = read_xlsx(raw, spec.get("sheet"))
        head = [str(h) for h in table[0]]
        return [dict(zip(head, [str(x) for x in r])) for r in table[1:]], origin
    text = raw.decode(spec.get("encoding", "utf-8-sig"), errors="replace")
    if kind == "json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in data], origin
    delim = spec.get("delimiter")
    if not delim:
        sample = text[:4000]
        delim = max([",", ";", "\t", "|"], key=sample.count)
    return list(csv.DictReader(io.StringIO(text), delimiter=delim)), origin


# ----------------------------------------------------------------------------- cleaning
def safe_eval(expr, row):
    """Arithmetic on column values only: + - * / and parentheses."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            v = row.get(n.id)
            if not isinstance(v, (int, float)):
                raise ValueError
            return v
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(n.left), ev(n.right)
            return a + b if isinstance(n.op, ast.Add) else a - b if isinstance(n.op, ast.Sub) else a * b if isinstance(n.op, ast.Mult) else a / b
        raise ValueError("unsupported expression")
    try:
        return ev(ast.parse(expr, mode="eval"))
    except (ValueError, ZeroDivisionError, SyntaxError, TypeError):
        return None


def matches(row, f):
    v, op, ref = row.get(f["field"]), f.get("op", "eq"), f.get("value")
    if op == "in":
        return v in ref
    if op == "not_in":
        return v not in ref
    if v is None:
        return False
    if op == "contains":
        return str(ref).lower() in str(v).lower()
    try:
        return {"eq": v == ref, "ne": v != ref, "gt": v > ref, "gte": v >= ref, "lt": v < ref, "lte": v <= ref}[op]
    except TypeError:
        return False


def clean(rows, spec):
    """Rename, convert types, dedupe, drop, fill, filter, derive. Returns (rows, report)."""
    rep = {"rows_in": len(rows), "duplicates": 0, "dropped": 0, "filtered": 0, "invalid": defaultdict(int)}
    colmap = {norm_header(k): v for k, v in spec.get("columns", {}).items()}
    types = spec.get("types", {})
    order = spec.get("date_order", "dmy")
    out = []
    for r in rows:
        n = {}
        for k, v in r.items():
            if k is None:
                continue
            name = colmap.get(norm_header(k), norm_header(k))
            v = None if v is None or str(v).strip().lower() in MISSING else str(v).strip()
            t = types.get(name, "text")
            if v is not None and t != "text":
                cv = {"number": parse_number, "money": parse_number, "int": lambda x: (lambda f: None if f is None else int(round(f)))(parse_number(x)),
                      "date": lambda x: parse_date(x, order, spec.get("date_formats")), "bool": parse_bool}[t](v)
                if cv is None:
                    rep["invalid"][name] += 1
                v = cv
            n[name] = v
        out.append(n)
    for d in spec.get("derived", []):
        for r in out:
            r[d["name"]] = safe_eval(d["expr"], r)
    keys = spec.get("dedupe")
    if keys:
        seen, kept = set(), []
        for r in out:
            k = tuple(sorted(r.items(), key=lambda kv: kv[0])) if keys == "all" else tuple(r.get(x) for x in keys)
            if k in seen:
                rep["duplicates"] += 1
                continue
            seen.add(k)
            kept.append(r)
        out = kept
    need = spec.get("drop_missing", [])
    before = len(out)
    out = [r for r in out if all(r.get(x) is not None for x in need)]
    rep["dropped"] = before - len(out)
    for k, v in spec.get("fill", {}).items():
        for r in out:
            if r.get(k) is None:
                r[k] = v
    before = len(out)
    out = [r for r in out if all(matches(r, f) for f in spec.get("filters", []))]
    rep["filtered"] = before - len(out)
    rep["rows_out"] = len(out)
    cols = sorted({c for r in out for c in r})
    rep["missing"] = {c: round(100 * sum(1 for r in out if r.get(c) is None) / len(out), 1) for c in cols if out} if out else {}
    rep["outliers"] = {}
    for c in cols:
        vals = [r[c] for r in out if isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)]
        if len(vals) >= 8:
            q = statistics.quantiles(vals, n=4)
            lo, hi = q[0] - 1.5 * (q[2] - q[0]), q[2] + 1.5 * (q[2] - q[0])
            cnt = sum(1 for v in vals if v < lo or v > hi)
            if cnt:
                rep["outliers"][c] = cnt
    rep["invalid"] = dict(rep["invalid"])
    return out, rep


def join(left, right, on, how="left", prefix=""):
    idx = defaultdict(list)
    for r in right:
        idx[tuple(r.get(k) for k in on)].append(r)
    out = []
    for l in left:
        m = idx.get(tuple(l.get(k) for k in on))
        if not m:
            if how == "left":
                out.append(dict(l))
            continue
        for r in m:
            row = dict(l)
            for k, v in r.items():
                if k in on:
                    continue
                row[(prefix + k) if k in row else k] = v
            out.append(row)
    return out


# ----------------------------------------------------------------------------- metrics
def group_key(v, grain):
    if v is None:
        return None
    if grain == "month":
        return v.strftime("%Y-%m")
    if grain == "year":
        return v.strftime("%Y")
    if grain == "quarter":
        return f"{v.year}-T{(v.month - 1) // 3 + 1}"
    if grain == "week":
        y, w, _ = v.isocalendar()
        return f"{y}-S{w:02d}"
    if grain == "weekday":
        return v.strftime("%u")
    return v.isoformat()


def period_end(key, grain):
    """Last day of a period key made by group_key()."""
    if grain == "month":
        y, mo = map(int, key.split("-"))
        return (date(y + mo // 12, mo % 12 + 1, 1) - timedelta(days=1))
    if grain == "year":
        return date(int(key), 12, 31)
    if grain == "quarter":
        y, q = key.split("-T")
        return period_end(f"{y}-{int(q) * 3:02d}", "month")
    if grain == "week":
        y, w = key.split("-S")
        return date.fromisocalendar(int(y), int(w), 7)
    return date.fromisoformat(key)


def measure(rows, m):
    kind, f = m.get("measure", "sum"), m.get("field")
    if kind == "count":
        return float(len(rows))
    if kind == "distinct":
        return float(len({r.get(f) for r in rows if r.get(f) is not None}))
    if kind == "rate":  # share of True values, in percent
        flags = [r.get(f) for r in rows if isinstance(r.get(f), bool)]
        return 100 * sum(flags) / len(flags) if flags else None
    if kind == "ratio":
        num = sum(r.get(m["num"]) or 0 for r in rows)
        den = sum(r.get(m["den"]) or 0 for r in rows)
        return num / den if den else None
    vals = [r[f] for r in rows if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)]
    if not vals:
        return None
    return {"sum": sum, "mean": statistics.mean, "median": statistics.median, "min": min, "max": max}[kind](vals)


def run_metric(m, tables):
    rows = [r for r in tables[m["source"]] if all(matches(r, f) for f in m.get("where", []))]
    by = m.get("by", [])
    groups, time_grain, max_date = defaultdict(list), None, None
    for r in rows:
        key = []
        for b in by:
            grain, _, fld = b.partition(":") if ":" in b else (None, None, b)
            if grain:
                time_grain = grain
                if r.get(fld) is not None and (max_date is None or r[fld] > max_date):
                    max_date = r[fld]
                key.append(group_key(r.get(fld), grain))
            else:
                key.append(r.get(fld))
        if None in key and by:
            continue
        groups[tuple(key)].append(r)
    res = []
    for key, rs in groups.items():
        res.append({**{b.split(":")[-1] if ":" not in b else b.replace(":", "_"): k for b, k in zip(by, key)}, "value": measure(rs, m), "n": len(rs)})
    if time_grain:
        res.sort(key=lambda r: [str(r[k]) for k in r if k not in ("value", "n")])
        if len(by) == 1:
            prev = None
            for r in res:
                r["change_pct"] = round(100 * (r["value"] - prev) / prev, 1) if prev and r["value"] is not None else None
                prev = r["value"]
            gk = [k for k in res[-1] if k not in ("value", "n", "change_pct")][0] if res else None
            if res and max_date and time_grain != "weekday" and max_date < period_end(str(res[-1][gk]), time_grain):
                res[-1]["partial"] = True  # the data stops before the end of the last period
                res[-1]["change_pct"] = None
    else:
        res.sort(key=lambda r: -(r["value"] if r["value"] is not None else -math.inf))
    if m.get("top"):
        res = res[: m["top"]]
    total = measure(rows, m) if not by else None
    return {"id": m["id"], "label": m.get("label", m["id"]), "unit": m.get("unit", ""), "by": by, "measure": m.get("measure", "sum"),
            "time": bool(time_grain), "rows": res, "total": total if not by else (measure(rows, m) if m.get("measure", "sum") in ("sum", "count") else None)}


def findings(result, lang):
    t, out, rows = STR[lang], [], [r for r in result["rows"] if r["value"] is not None and not r.get("partial")]
    if not rows or not result["by"]:
        return out
    dec = (lambda x: str(x).replace(".", ",")) if lang == "fr" else str
    gk = [k for k in rows[0] if k not in ("value", "n", "change_pct")][0]
    u = result["unit"]
    if result["time"]:
        if len(rows) >= 2:
            a, b = rows[-1], rows[-2]
            c = round(100 * (a["value"] - b["value"]) / b["value"], 1) if b["value"] else None
            if c is not None:
                tpl = t["flat"] if abs(c) < 1 else t["up"] if c > 0 else t["down"]
                out.append(f"{result['label']} : " + tpl.format(p=a[gk], v=fmt_num(a["value"], u, lang), c=dec(abs(c)), q=b[gk]))
            best, worst = max(rows, key=lambda r: r["value"]), min(rows, key=lambda r: r["value"])
            out.append(f"{result['label']} : " + t["best"].format(p=best[gk], v=fmt_num(best["value"], u, lang), w=worst[gk], x=fmt_num(worst["value"], u, lang)))
        if len(rows) >= 6:
            h = len(rows) // 2
            f, s = statistics.mean(r["value"] for r in rows[:h]), statistics.mean(r["value"] for r in rows[-h:])
            if f:
                c = round(100 * (s - f) / f, 1)
                if abs(c) >= 5:
                    out.append(f"{result['label']} : " + (t["trend_up"] if c > 0 else t["trend_down"]).format(c=dec(abs(c))))
    elif result["measure"] in ("sum", "count") and len(rows) >= 2:
        tot = sum(r["value"] for r in rows)
        if tot:
            out.append(f"{result['label']} : " + t["top"].format(g=rows[0][gk], v=fmt_num(rows[0]["value"], u, lang), s=round(100 * rows[0]["value"] / tot)))
    return out


# ----------------------------------------------------------------------------- report
CSS = ("<style>:root{--bg:#f6f7f9;--panel:#fff;--fg:#17212b;--muted:#5b6874;--line:#d9dee3;--accent:#0e6e66;--accent2:#c27a1a}"
       "@media(prefers-color-scheme:dark){:root{--bg:#0f161c;--panel:#17212a;--fg:#e5edf2;--muted:#94a3ae;--line:#2b3a46;--accent:#4fc3b6;--accent2:#e0a64a}}"
       "body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,'Segoe UI',sans-serif;margin:0;padding:32px max(16px,env(safe-area-inset-left))}"
       ".w{max-width:920px;margin:0 auto}h1{font-size:2rem;margin:0 0 4px}h2{margin:36px 0 10px;font-size:1.3rem}small,.m{color:var(--muted)}"
       ".k{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.c{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}"
       ".c b{display:block;font-size:1.7rem;line-height:1.1}.s{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}"
       "table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}"
       ".r{text-align:right}.sc{overflow-x:auto}svg{width:100%;height:auto}svg text{fill:var(--muted);font:12px system-ui}ul{padding-left:1.2em}</style>")


def svg_bars(rows, gk, unit, lang):
    rows = rows[:15]
    mx = max((r["value"] or 0) for r in rows) or 1
    left, W, h = 170, 640, 26
    parts = [f'<svg viewBox="0 0 {W} {h * len(rows) + 6}" role="img" aria-label="bar chart">']
    for i, r in enumerate(rows):
        w = (W - left - 90) * (r["value"] or 0) / mx
        y = i * h + 3
        parts.append(f'<text x="0" y="{y + 16}">{html.escape(str(r[gk])[:26])}</text><rect x="{left}" y="{y + 3}" width="{max(w, 1):.1f}" height="{h - 9}" rx="3" fill="var(--accent)"/>'
                     f'<text x="{left + w + 6:.1f}" y="{y + 16}">{html.escape(fmt_num(r["value"], unit, lang))}</text>')
    return "".join(parts) + "</svg>"


def svg_line(rows, gk, unit, lang):
    pts = [(r[gk], r["value"]) for r in rows if r["value"] is not None]
    if len(pts) < 2:
        return svg_bars(rows, gk, unit, lang)
    W, H, l, b = 640, 220, 56, 28
    lo, hi = min(0, min(v for _, v in pts)), max(v for _, v in pts)
    hi = hi if hi != lo else lo + 1
    x = lambda i: l + (W - l - 12) * i / (len(pts) - 1)
    y = lambda v: 10 + (H - 10 - b) * (1 - (v - lo) / (hi - lo))
    d = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="line chart">', f'<line x1="{l}" x2="{W - 12}" y1="{y(lo):.1f}" y2="{y(lo):.1f}" stroke="var(--line)"/>',
             f'<text x="0" y="{y(hi) + 4:.1f}">{html.escape(fmt_num(hi, "", lang))}</text><text x="0" y="{y(lo) + 4:.1f}">{html.escape(fmt_num(lo, "", lang))}</text>',
             f'<path d="{d}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>']
    step = max(1, len(pts) // 8)
    for i, (k, v) in enumerate(pts):
        parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3.5" fill="var(--accent)"/>')
        if i % step == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{html.escape(str(k))}</text>')
    return "".join(parts) + "</svg>"


def render(cfg, results, reports, finds, today):
    lang = cfg["language"]
    t = STR[lang]
    p = [f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(cfg["project"])}</title>{CSS}<div class="w">',
         f'<h1>{html.escape(cfg["project"])}</h1><p class="m">{html.escape(cfg.get("subtitle", t["report"]))}. {t["generated"].format(d=today, n=len(reports))}</p>']
    if cfg.get("sample_notice"):
        p.append(f'<p class="s"><b>{html.escape(cfg["sample_notice"])}</b></p>')
    kp = [r for r in results if r["id"] in cfg.get("kpis", [])]
    if kp:
        p.append(f'<h2>{t["kpis"]}</h2><div class="k">' + "".join(f'<div class="c"><b>{html.escape(fmt_num(r["total"] if r["total"] is not None else (r["rows"][0]["value"] if r["rows"] else None), r["unit"], lang))}</b><span class="m">{html.escape(r["label"])}</span></div>' for r in kp) + "</div>")
    if finds:
        p.append(f'<h2>{t["findings"]}</h2><ul>' + "".join(f"<li>{html.escape(f)}</li>" for f in finds) + "</ul>")
    for r in results:
        if r["id"] in cfg.get("kpis", []) or not r["by"]:
            continue
        gk = [k for k in r["rows"][0] if k not in ("value", "n", "change_pct")][0] if r["rows"] else ""
        p.append(f'<h2>{html.escape(r["label"])}</h2><div class="s">')
        if r["rows"]:
            p.append((svg_line if r["time"] else svg_bars)(r["rows"], gk, r["unit"], lang))
            p.append(f'<div class="sc"><table><tr><th>{html.escape(gk)}</th><th class="r">{html.escape(r["label"])}</th><th class="r">{t["n"]}</th>' + (f'<th class="r">{t["change"]}</th>' if r["time"] and len(r["by"]) == 1 else "") + "</tr>")
            for row in r["rows"][:40]:
                ch = row.get("change_pct")
                p.append(f'<tr><td>{html.escape(str(row[gk]))}{" (" + t["partial"] + ")" if row.get("partial") else ""}</td><td class="r">{html.escape(fmt_num(row["value"], r["unit"], lang))}</td><td class="r">{row["n"]}</td>'
                         + (f'<td class="r">{"" if ch is None else ("+" if ch > 0 else "") + str(ch).replace(".", "," if lang == "fr" else ".") + " %"}</td>' if r["time"] and len(r["by"]) == 1 else "") + "</tr>")
            p.append("</table></div>")
        else:
            p.append(f'<p class="m">{t["empty"]}</p>')
        p.append("</div>")
    p.append(f'<h2>{t["quality"]}</h2>')
    for name, rp in reports.items():
        p.append(f'<div class="s"><b>{html.escape(name)}</b><br><span class="m">{t["rows_in"]} : {rp["rows_in"]} · {t["rows_out"]} : {rp["rows_out"]} · {t["dup"]} : {rp["duplicates"]} · {t["dropped"]} : {rp["dropped"]}</span>')
        bad = {k: v for k, v in rp["missing"].items() if v >= 5}
        if bad:
            p.append(f'<br><span class="m">{t["missing"]} : ' + ", ".join(f"{k} {v} %" for k, v in bad.items()) + "</span>")
        if rp["invalid"]:
            p.append(f'<br><span class="m">{t["invalid"]} : ' + ", ".join(f"{k} ({v})" for k, v in rp["invalid"].items()) + "</span>")
        if rp["outliers"]:
            p.append(f'<br><span class="m">{t["outliers"]} : ' + ", ".join(f"{k} ({v})" for k, v in rp["outliers"].items()) + "</span>")
        p.append("</div>")
    return "".join(p) + "</div>"


# ----------------------------------------------------------------------------- commands
def cmd_run(args):
    cfgp = Path(args.config).resolve()
    cfg = {"language": "en", "project": "Analysis", "outputs": {"dir": "out"}, **json.loads(cfgp.read_text(encoding="utf8"))}
    root, lang = cfgp.parent, cfg["language"] if cfg.get("language") in STR else "en"
    cfg["language"] = lang
    tables, reports = {}, {}
    for name, spec in cfg["sources"].items():
        rows, origin = load_rows(spec, root)
        tables[name], reports[name] = clean(rows, spec)
        print(f"{name}: {reports[name]['rows_in']} -> {reports[name]['rows_out']} rows ({origin})")
    for j in cfg.get("joins", []):
        tables[j["name"]] = join(tables[j["left"]], tables[j["right"]], j["on"], j.get("how", "left"), j["right"] + "_")
        print(f"join {j['name']}: {len(tables[j['name']])} rows")
    results = [run_metric(m, tables) for m in cfg.get("metrics", [])]
    finds = [f for r in results for f in findings(r, lang)]
    out = root / cfg["outputs"].get("dir", "out")
    (out / "export").mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (out / cfg["outputs"].get("html", "report.html")).write_text(render(cfg, results, reports, finds, today), encoding="utf8")
    for r in results:
        (out / "export" / f"{r['id']}.json").write_text(json.dumps(r["rows"], ensure_ascii=False, indent=1), encoding="utf8")
    (out / "export" / "summary.json").write_text(json.dumps({"project": cfg["project"], "generated": today, "findings": finds, "quality": reports,
                                                               "metrics": [{"id": r["id"], "label": r["label"], "unit": r["unit"], "total": r["total"]} for r in results]},
                                                              ensure_ascii=False, indent=1, default=str), encoding="utf8")
    if cfg["outputs"].get("clean_csv"):
        (out / "clean").mkdir(exist_ok=True)
        for name, rows in tables.items():
            cols = sorted({c for r in rows for c in r})
            with open(out / "clean" / f"{name}.csv", "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in rows:
                    w.writerow(["" if r.get(c) is None else (r[c].isoformat() if isinstance(r[c], date) else r[c]) for c in cols])
    print(f"Report: {out / cfg['outputs'].get('html', 'report.html')}")
    for f in finds:
        print(" -", f)


def cmd_profile(args):
    rows, _ = load_rows({"path": args.file, "delimiter": args.delimiter}, Path.cwd())
    print(f"{len(rows)} rows, {len(rows[0]) if rows else 0} columns")
    for c in (rows[0].keys() if rows else []):
        vals = [r[c] for r in rows if r.get(c) is not None and str(r[c]).strip().lower() not in MISSING]
        nums = [parse_number(v) for v in vals]
        dates = [parse_date(v) for v in vals]
        kind = ("date" if vals and sum(d is not None for d in dates) > 0.9 * len(vals) else
                "number" if vals and sum(n is not None for n in nums) > 0.9 * len(vals) else "text")
        extra = f" min={min(n for n in nums if n is not None)} max={max(n for n in nums if n is not None)}" if kind == "number" else (
            f" {min(d for d in dates if d)} -> {max(d for d in dates if d)}" if kind == "date" else "")
        print(f"  {c}: {kind}, {100 * (len(rows) - len(vals)) // max(len(rows), 1)}% missing, {len(set(vals))} distinct{extra}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", default="config.json")
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("profile")
    p.add_argument("file")
    p.add_argument("--delimiter")
    p.set_defaults(fn=cmd_profile)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
