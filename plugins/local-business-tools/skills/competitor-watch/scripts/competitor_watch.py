#!/usr/bin/env python3
"""competitor-watch : cartographier la concurrence locale et suivre ses prix.
Map local competition and track published prices. Works for any local business.

Python standard library only. No API key. No paid service.

  python competitor_watch.py scrape   --config config.json --service moving   # Google Maps (optional, needs the kit)
  python competitor_watch.py map      --config config.json --service moving --csv results.csv
  python competitor_watch.py watch    --config config.json
  python competitor_watch.py export   --config config.json --service moving

Config schema: see config.example.json and README.md.
"""
import argparse, csv, difflib, hashlib, html, json, re, statistics, subprocess, sys, time
import unicodedata, urllib.parse, urllib.request, urllib.robotparser
from collections import defaultdict
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

__version__ = "0.1.0"

STRINGS = {
    "fr": dict(
        map_source="Source : Google Maps, relevé du {today}. {n} entreprises uniques, {s} secteurs. Les notes et avis sont ceux publiés par Google.",
        sector_line="Note moyenne : {avg} · sans site web : {nosite}", no_address="Sans adresse (service mobile)",
        company="Entreprise", rating="Note", reviews="Avis", phone="Téléphone", site="Site",
        watch_title="Veille concurrentielle", watch_intro="Visite du {today}. Données lues sur les sites publics des concurrents : à valider avant toute décision de prix.",
        changes="Changements depuis la dernière visite", prices="Prix et montants trouvés", promises="Promesses et conditions",
        nothing="rien trouvé", unread="Non lu", first_visit="Première visite : rien à comparer.", no_change="Aucun changement.",
        new_price="NOUVEAU prix", removed_price="RETIRÉ prix", new_heading="Nouveau titre",
        text_changed="Texte modifié (similarité {r}), sans changement de prix.", js_warning="peu de texte lu (page probablement chargée par JavaScript)",
        robots="bloqué par robots.txt (sauté)"),
    "en": dict(
        map_source="Source: Google Maps, collected on {today}. {n} unique businesses, {s} areas. Ratings and reviews are as published by Google.",
        sector_line="Average rating: {avg} · without website: {nosite}", no_address="No address (mobile service)",
        company="Business", rating="Rating", reviews="Reviews", phone="Phone", site="Website",
        watch_title="Competitor watch", watch_intro="Visit of {today}. Data read from competitors' public websites: verify before any pricing decision.",
        changes="Changes since last visit", prices="Prices and amounts found", promises="Promises and conditions",
        nothing="nothing found", unread="Not read", first_visit="First visit: nothing to compare.", no_change="No change.",
        new_price="NEW price", removed_price="REMOVED price", new_heading="New heading",
        text_changed="Text changed (similarity {r}), no price change.", js_warning="little text read (page probably rendered by JavaScript)",
        robots="blocked by robots.txt (skipped)"),
}

DEFAULTS = {
    "project": "My market",
    "language": "en",
    "data_dir": "data",
    "user_agent": "Mozilla/5.0 (compatible; competitor-watch/%s)" % __version__,
    "delay_seconds": 2,
    "address": {"region_pattern": r"(QC|Qu[ée]bec)\b"},
    "directories_to_skip": ["facebook.", "instagram.", "kijiji.", "yelp.", "pagesjaunes.", "yellowpages.", "linkedin.",
                            "tiktok.", "youtube.", "google.", "uhaul."],
    "maps": {"kit_path": "", "lang": "en", "country": "", "depth": 2, "cities": []},
    "services": {},
    "competitors": [],
}


# ----------------------------------------------------------------------------- config
def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config(path):
    cfg = merge(DEFAULTS, json.loads(Path(path).read_text(encoding="utf8")))
    cfg["_root"] = Path(path).resolve().parent
    cfg["_t"] = STRINGS.get(cfg["language"], STRINGS["en"])
    return cfg


def data_dir(cfg, *parts):
    d = cfg["_root"] / cfg["data_dir"]
    for p in parts:
        d = d / p
    return d


def service_cfg(cfg, sid):
    if sid not in cfg["services"]:
        sys.exit(f"Unknown service '{sid}'. Defined: {', '.join(cfg['services']) or '(none)'}")
    s = dict(cfg["services"][sid])
    s["_regex"] = re.compile(s["category_regex"], re.I)
    s.setdefault("label", sid)
    s.setdefault("top_per_sector", 3)
    s.setdefault("price", {"mode": "amounts", "min": 20, "max": 5000})
    return s


# ----------------------------------------------------------------------------- Google Maps rows
def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def sector_of(address, region_pattern, no_address):
    """City/area of a business: the part of the address just before the region (QC, ON, ...)."""
    if not (address or "").strip():
        return no_address
    parts = [p.strip() for p in address.split(",")]
    rx = re.compile(region_pattern, re.I)
    for i, p in enumerate(parts):
        if i and rx.match(p):
            return parts[i - 1]
    return parts[-2] if len(parts) >= 3 else "?"


def accent_count(s):
    """Number of accented letters in s."""
    return sum(1 for c in unicodedata.normalize("NFD", s) if unicodedata.combining(c))


def unify_sector_names(rows):
    """'Montreal' and 'Montréal' become one area (the spelling with the most accents wins)."""
    best = {}
    for r in rows:
        k = strip_accents(r["sector"])
        if k not in best or accent_count(r["sector"]) > accent_count(best[k]):
            best[k] = r["sector"]
    for r in rows:
        r["sector"] = best[strip_accents(r["sector"])]


def to_num(v, cast=float):
    try:
        return cast(str(v).replace(",", ".").replace(" ", "").replace(" ", ""))
    except Exception:
        return None


def read_maps_csv(csv_path, scfg, cfg):
    seen, rows = set(), []
    no_addr = cfg["_t"]["no_address"]
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            blob = " ".join([r.get("category", ""), r.get("categories", ""), r.get("title", "")])
            if not scfg["_regex"].search(blob):
                continue
            key = (r.get("title", "").strip().lower(), re.sub(r"\D", "", r.get("phone", "")))
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(name=r.get("title", "").strip(), phone=r.get("phone", ""), website=r.get("website", ""),
                             address=r.get("address", ""), sector=sector_of(r.get("address", ""), cfg["address"]["region_pattern"], no_addr),
                             rating=to_num(r.get("review_rating")), reviews=to_num(r.get("review_count"), int) or 0))
    unify_sector_names(rows)
    return rows


def domain(url):
    return urllib.parse.urlparse(url).netloc.replace("www.", "") if url else ""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", strip_accents(s)).strip("-")[:60]


# ----------------------------------------------------------------------------- command: scrape
def cmd_scrape(cfg, args):
    kit = Path(cfg["maps"]["kit_path"] or "")
    scrape = kit / "scripts" / "scrape.py"
    if not scrape.exists():
        sys.exit("Set maps.kit_path in the config to the Google Maps scraper kit folder (it must contain scripts/scrape.py).")
    scfg = service_cfg(cfg, args.service)
    out = args.out or str(data_dir(cfg, "maps") / f"results-{args.service}-{date.today().isoformat()}.csv")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    kws = scfg["keywords"]
    cmd = [sys.executable if sys.platform != "win32" else "py", str(scrape), kws[0]]
    for k in kws[1:]:
        cmd += ["--keyword", k]
    for c in cfg["maps"]["cities"]:
        cmd += ["--city", c]
    cmd += ["--depth", str(cfg["maps"]["depth"]), "--lang", cfg["maps"]["lang"], "--no-email", "--no-socials",
            "--max-time", "3000", "--out", str(out)]
    if cfg["maps"].get("country"):
        cmd += ["--country", cfg["maps"]["country"]]
    print("Heavy use can get your IP temporarily rate-limited by Google. Keep depth low.")
    print("Run from the kit folder (engine must be running):", " ".join(cmd))
    sys.exit(subprocess.call(cmd, cwd=str(kit)))


# ----------------------------------------------------------------------------- command: map
def cmd_map(cfg, args):
    scfg, t, today = service_cfg(cfg, args.service), cfg["_t"], date.today().isoformat()
    rows = read_maps_csv(args.csv, scfg, cfg)
    by = defaultdict(list)
    for r in rows:
        by[r["sector"]].append(r)
    (data_dir(cfg, "maps")).mkdir(parents=True, exist_ok=True)
    data_dir(cfg, "maps", f"{args.service}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf8")

    known = {domain(u) for c in cfg["competitors"] for u in c["pages"]}
    watch, seen, body = [], set(), []
    for sec, lst in sorted(by.items(), key=lambda kv: -len(kv[1])):
        notes = [r["rating"] for r in lst if r["rating"]]
        top = sorted(lst, key=lambda r: -r["reviews"])
        body.append(f"<h2>{html.escape(sec)} <small>— {len(lst)}</small></h2>")
        if notes:
            body.append("<p><small>" + t["sector_line"].format(avg=f"{statistics.mean(notes):.2f}", nosite=sum(1 for r in lst if not r["website"])) + "</small></p>")
        body.append(f"<table><tr><th>{t['company']}</th><th>{t['rating']}</th><th>{t['reviews']}</th><th>{t['phone']}</th><th>{t['site']}</th></tr>")
        for r in top[:8]:
            d = domain(r["website"])
            link = f'<a href="{html.escape(r["website"])}">{html.escape(d)}</a>' if d else "—"
            body.append(f"<tr><td>{html.escape(r['name'])}</td><td>{r['rating'] or '—'}</td><td>{r['reviews']}</td><td>{html.escape(r['phone'])}</td><td>{link}</td></tr>")
        body.append("</table>")
        n = 0
        for r in top:
            d = domain(r["website"])
            if n >= scfg["top_per_sector"]:
                break
            if not d or any(x in d for x in cfg["directories_to_skip"]) or d in known or d in seen:
                continue
            seen.add(d)
            watch.append({"name": f"{r['name']} ({sec})", "service": args.service, "pages": [r["website"]]})
            n += 1
    page = (f'<!doctype html><html lang="{cfg["language"]}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(cfg["project"])} – {html.escape(scfg["label"])} {today}</title>{CSS_MAP}'
            f'<h1>{html.escape(cfg["project"])} – {html.escape(scfg["label"])}</h1>'
            f'<p><small>{t["map_source"].format(today=today, n=len(rows), s=len(by))}</small></p>{"".join(body)}')
    out = data_dir(cfg, "reports"); out.mkdir(parents=True, exist_ok=True)
    out = out / f"map-{args.service}-{today}.html"
    out.write_text(page, encoding="utf8")
    sites = data_dir(cfg, "maps", f"sites-{args.service}.json")
    sites.write_text(json.dumps({"competitors": watch}, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"{len(rows)} businesses, {len(by)} areas -> {out}")
    print(f"{len(watch)} sites to watch -> {sites}")


CSS_MAP = ("<style>body{font:16px/1.5 system-ui,sans-serif;max-width:960px;margin:0 auto;padding:24px 16px;background:#fafaf7;color:#1a2230}"
           "h2{margin-top:34px;border-bottom:2px solid #d9822b;padding-bottom:4px}small{color:#5d6b7a;font-weight:400}"
           "table{border-collapse:collapse;width:100%;background:#fff;font-size:15px}th,td{border:1px solid #e3ddd0;padding:6px 10px;text-align:left}th{background:#f1ece0}</style>")


# ----------------------------------------------------------------------------- page reading
BLOCK = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "td", "th", "ul", "ol", "table"}


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip, self.title, self.in_title = [], 0, "", False
        self.head, self.cur, self.meta = [], None, ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag in ("h1", "h2", "h3"):
            self.cur = []
        if tag == "meta":
            d = dict(attrs)
            if (d.get("name") or "").lower() == "description":
                self.meta = d.get("content") or ""
        if tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.in_title = False
        if tag in ("h1", "h2", "h3") and self.cur is not None:
            h = " ".join("".join(self.cur).split())
            if h:
                self.head.append(h)
            self.cur = None
        if tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
        if self.cur is not None:
            self.cur.append(data)
        self.out.append(data)


AMOUNT = re.compile(r"(\d{1,4}(?:[  ]\d{3})*(?:[.,]\d{1,2})?)\s?[$€£]|[$€£]\s?(\d{1,4}(?:[  ]\d{3})*(?:[.,]\d{1,2})?)")
PROMISE_KEYS = ["hour", "heure", "/h", "minimum", "insurance", "assurance", "guarantee", "garantie", "cancel", "annulation",
                "free", "gratuit", "deposit", "acompte", "dépôt", "no hidden", "sans frais", "flat", "fixe", "forfait", "taxes",
                "24/7", "quote", "soumission", "estimate", "estimation"]


def extract_rates(lines, price_cfg):
    """Numbers followed by a unit (e.g. '120 $/h') inside [min, max]."""
    if price_cfg.get("mode") != "rate":
        return []
    rx = re.compile(r"(\d{2,4}(?:[.,]\d{1,2})?)\s?[$€£]?\s?(?:" + price_cfg["unit_regex"] + ")", re.I)
    found = set()
    for line in lines:
        for m in rx.finditer(line):
            v = float(m.group(1).replace(",", "."))
            if price_cfg.get("min", 0) <= v <= price_cfg.get("max", 10**6):
                found.add(v)
    return sorted(found)


def extract_amounts(lines, price_cfg):
    found = set()
    for line in lines:
        for m in AMOUNT.finditer(line):
            raw = (m.group(1) or m.group(2)).replace(" ", "").replace(" ", "").replace(",", ".")
            try:
                v = float(raw)
            except ValueError:
                continue
            if price_cfg.get("min", 0) <= v <= price_cfg.get("max", 10**6):
                found.add(v)
    return sorted(found)


def allowed(url, ua):
    p = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:  # read robots.txt with our own user agent (Python's default one is often refused)
        req = urllib.request.Request(f"{p.scheme}://{p.netloc}/robots.txt", headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=15) as r:
            rp.parse(r.read(200_000).decode("utf-8", errors="replace").splitlines())
        return rp.can_fetch(ua, url)
    except Exception:
        return True


def fetch(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def analyse_html(raw_html, price_cfg):
    p = PageText()
    p.feed(raw_html)
    lines = [" ".join(l.split()) for l in html.unescape("".join(p.out)).split("\n")]
    lines = [l for l in lines if len(l) > 2]
    text = "\n".join(lines)
    price_lines = [l[:220] for l in lines if AMOUNT.search(l)]
    promises = [l[:200] for l in lines if any(k in l.lower() for k in PROMISE_KEYS) and not AMOUNT.search(l) and 12 < len(l) < 220]
    return dict(title=" ".join(p.title.split()), description=p.meta[:250], headings=p.head[:12],
                prices=list(dict.fromkeys(price_lines))[:25], promises=list(dict.fromkeys(promises))[:15],
                rates=extract_rates(price_lines + promises, price_cfg),
                amounts=extract_amounts(price_lines, price_cfg) if price_cfg.get("mode") == "amounts" else [],
                chars=len(text), hash=hashlib.sha1(text.encode()).hexdigest(), excerpt=text[:6000])


def diff_snapshots(old, new, t):
    if not old:
        return [t["first_visit"]]
    out = [f"{t['new_price']}: {l}" for l in new["prices"] if l not in old.get("prices", [])]
    out += [f"{t['removed_price']}: {l}" for l in old.get("prices", []) if l not in new["prices"]]
    out += [f"{t['new_heading']}: {h}" for h in new["headings"] if h not in old.get("headings", [])]
    if not out and old.get("hash") != new["hash"]:
        r = difflib.SequenceMatcher(None, old.get("excerpt", ""), new["excerpt"]).ratio()
        out.append(t["text_changed"].format(r=f"{r:.0%}"))
    return out or [t["no_change"]]


# ----------------------------------------------------------------------------- command: watch
def cmd_watch(cfg, args):
    t, today = cfg["_t"], date.today().isoformat()
    entries = list(cfg["competitors"])
    for f in sorted(data_dir(cfg, "maps").glob("sites-*.json")):
        entries += json.loads(f.read_text(encoding="utf8"))["competitors"]
    seen, rows = set(), []
    for e in entries:
        if args.service and e.get("service") != args.service:
            continue
        pcfg = service_cfg(cfg, e["service"])["price"] if e.get("service") in cfg["services"] else {"mode": "amounts"}
        for url in e["pages"]:
            if url in seen:
                continue
            seen.add(url)
            print("->", url, flush=True)
            r = dict(competitor=e["name"], service=e.get("service", ""), url=url, ok=False)
            if not allowed(url, cfg["user_agent"]):
                r["error"] = t["robots"]
            else:
                try:
                    r.update(analyse_html(fetch(url, cfg["user_agent"]), pcfg), ok=True)
                    if r["chars"] < 400:
                        r["warning"] = t["js_warning"]
                except Exception as ex:
                    r["error"] = str(ex)[:120]
            d = data_dir(cfg, "snapshots", slug(e["name"] + "-" + urllib.parse.urlparse(url).path))
            if r["ok"]:
                d.mkdir(parents=True, exist_ok=True)
                prev = sorted(d.glob("*.json"))
                r["changes"] = diff_snapshots(json.loads(prev[-1].read_text(encoding="utf8")) if prev else None, r, t)
                (d / f"{today}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf8")
            rows.append(r)
            time.sleep(cfg["delay_seconds"])
    out = data_dir(cfg, "reports"); out.mkdir(parents=True, exist_ok=True)
    out = out / f"watch-{today}.html"
    out.write_text(watch_report(rows, today, cfg), encoding="utf8")
    print("Report:", out)


def li(items, t):
    return "".join(f"<li>{html.escape(i)}</li>" for i in items) or f"<li><em>{t['nothing']}</em></li>"


def watch_report(rows, today, cfg):
    t = cfg["_t"]
    parts = [f'<!doctype html><html lang="{cfg["language"]}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<title>{t["watch_title"]} {today}</title>{CSS_MAP}<h1>{html.escape(cfg["project"])} – {t["watch_title"]}</h1>'
             f'<p><small>{t["watch_intro"].format(today=today)}</small></p>']
    cur = None
    for r in rows:
        if r["competitor"] != cur:
            cur = r["competitor"]
            parts.append(f"<h2>{html.escape(cur)}</h2>")
        parts.append(f'<h3><a href="{html.escape(r["url"])}">{html.escape(r["url"])}</a></h3>')
        if not r["ok"]:
            parts.append(f"<p>{t['unread']}: {html.escape(r.get('error', ''))}</p>")
            continue
        if r.get("warning"):
            parts.append(f"<p>⚠ {html.escape(r['warning'])}</p>")
        parts.append(f"<p><b>{html.escape(r['title'])}</b><br><small>{html.escape(r['description'])}</small></p>")
        parts.append(f"<b>{t['changes']}</b><ul>{li(r['changes'], t)}</ul><b>{t['prices']}</b><ul>{li(r['prices'], t)}</ul>"
                     f"<b>{t['promises']}</b><ul>{li(r['promises'], t)}</ul>")
    return "".join(parts)


# ----------------------------------------------------------------------------- command: export
def cmd_export(cfg, args):
    """JSON files for a dashboard or a spreadsheet: sectors, businesses, prices."""
    sid = args.service
    mp = data_dir(cfg, "maps", f"{sid}.json")
    if not mp.exists():
        sys.exit(f"Run 'map' for service '{sid}' first.")
    rows = json.loads(mp.read_text(encoding="utf8"))
    by = defaultdict(list)
    for r in rows:
        by[r["sector"]].append(r)
    sectors = sorted(({"sector": s, "count": len(l),
                       "avg_rating": round(statistics.mean([r["rating"] for r in l if r["rating"]]), 2) if any(r["rating"] for r in l) else None,
                       "total_reviews": sum(r["reviews"] for r in l), "without_website": sum(1 for r in l if not r["website"])}
                      for s, l in by.items()), key=lambda s: -s["count"])
    businesses = [dict(r, domain=domain(r["website"])) for r in sorted(rows, key=lambda r: -r["reviews"])]
    sector_by_domain = {b["domain"]: b["sector"] for b in businesses if b["domain"]}
    snaps = defaultdict(lambda: {"rates": set(), "amounts": set(), "url": "", "samples": []})
    for f in data_dir(cfg, "snapshots").glob("*/*.json"):
        r = json.loads(f.read_text(encoding="utf8"))
        if r.get("service") != sid:
            continue
        e = snaps[re.sub(r"\s*\(.*?\)$", "", r["competitor"])]
        e["url"] = e["url"] or r["url"]
        e["rates"].update(r.get("rates", []))
        e["amounts"].update(r.get("amounts", []))
        e["samples"] += r.get("prices", [])[:2]
    prices = []
    for name, e in snaps.items():
        vals = sorted(e["rates"] or e["amounts"])
        if vals:
            prices.append(dict(name=name, sector=sector_by_domain.get(domain(e["url"]), "n/a"), min=vals[0], max=vals[-1],
                               count=len(vals), site=domain(e["url"]), samples=e["samples"][:2]))
    prices.sort(key=lambda p: p["min"])
    out = data_dir(cfg, "export"); out.mkdir(parents=True, exist_ok=True)
    for name, data in (("sectors", sectors), ("businesses", businesses), ("prices", prices)):
        (out / f"{name}-{sid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"{len(sectors)} areas, {len(businesses)} businesses, {len(prices)} with prices -> {out}")


# ----------------------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, need_service, need_csv in (("scrape", cmd_scrape, True, False), ("map", cmd_map, True, True),
                                             ("watch", cmd_watch, False, False), ("export", cmd_export, True, False)):
        p = sub.add_parser(name)
        p.add_argument("--config", default="config.json")
        p.add_argument("--service", required=need_service, help="service id defined in the config")
        if need_csv:
            p.add_argument("--csv", required=True, help="CSV exported by the Google Maps scraper")
        if name == "scrape":
            p.add_argument("--out")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    args.fn(load_config(args.config), args)


if __name__ == "__main__":
    main()
