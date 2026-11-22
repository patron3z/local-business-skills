import csv, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import competitor_watch as cw

REGION = r"(QC|Qu[ée]bec)\b"


class Sectors(unittest.TestCase):
    def test_city_before_region(self):
        self.assertEqual(cw.sector_of("12 Rue X, Laval, QC H7A 1A1", REGION, "none"), "Laval")

    def test_empty_address(self):
        self.assertEqual(cw.sector_of("", REGION, "none"), "none")

    def test_unify_accents(self):
        rows = [{"sector": "Montreal"}, {"sector": "Montréal"}, {"sector": "Laval"}]
        cw.unify_sector_names(rows)
        self.assertEqual({r["sector"] for r in rows}, {"Montréal", "Laval"})


class Prices(unittest.TestCase):
    PRICE = {"mode": "rate", "unit_regex": r"(?:/|par|de l.?|l.?)\s?(?:h\b|heure)", "min": 40, "max": 400}

    def test_hourly_rates(self):
        lines = ["Deux déménageurs et un camion à partir de 120 $/h", "Camion de 30 pieds : 175 $ de l'heure", "Piano 450 $"]
        self.assertEqual(cw.extract_rates(lines, self.PRICE), [120.0, 175.0])

    def test_out_of_range_ignored(self):
        self.assertEqual(cw.extract_rates(["5 $/h", "9999 $/h"], self.PRICE), [])

    def test_amounts(self):
        got = cw.extract_amounts(["Dès 99 $ la charge", "Camion complet 1 200 $", "Total 5 $"], {"min": 30, "max": 2000})
        self.assertEqual(got, [99.0, 1200.0])


class Reading(unittest.TestCase):
    HTML = ("<html><head><title>Prix</title><meta name='description' content='Nos tarifs'></head><body>"
            "<script>var x = '999 $';</script><h1>Nos prix</h1><p>À partir de 120 $/h, taxes en sus.</p>"
            "<p>Soumission gratuite sans engagement.</p></body></html>")

    def test_analyse(self):
        r = cw.analyse_html(self.HTML, {"mode": "rate", "unit_regex": r"/\s?h\b", "min": 40, "max": 400})
        self.assertEqual(r["title"], "Prix")
        self.assertEqual(r["rates"], [120.0])
        self.assertTrue(any("120" in p for p in r["prices"]))
        self.assertFalse(any("999" in p for p in r["prices"]))  # script content ignored
        self.assertTrue(any("gratuite" in p.lower() for p in r["promises"]))


class Diff(unittest.TestCase):
    T = cw.STRINGS["en"]

    def snap(self, prices, h="a"):
        return {"prices": prices, "headings": [], "hash": h, "excerpt": h}

    def test_first_visit(self):
        self.assertEqual(cw.diff_snapshots(None, self.snap([]), self.T), [self.T["first_visit"]])

    def test_price_change(self):
        out = cw.diff_snapshots(self.snap(["120 $/h"]), self.snap(["130 $/h"], "b"), self.T)
        self.assertTrue(any(o.startswith(self.T["new_price"]) for o in out))
        self.assertTrue(any(o.startswith(self.T["removed_price"]) for o in out))

    def test_no_change(self):
        self.assertEqual(cw.diff_snapshots(self.snap(["1 $"]), self.snap(["1 $"]), self.T), [self.T["no_change"]])


class MapsCsv(unittest.TestCase):
    def test_filter_and_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["title", "phone", "website", "category", "address", "review_rating", "review_count"])
                w.writeheader()
                w.writerow(dict(title="A Moving", phone="(514) 111-1111", website="https://a.ca", category="Service de déménagement",
                                address="1 Rue, Montréal, QC H1A", review_rating="4.8", review_count="120"))
                w.writerow(dict(title="A Moving", phone="514-111-1111", website="https://a.ca", category="Service de déménagement",
                                address="1 Rue, Montréal, QC H1A", review_rating="4.8", review_count="120"))  # duplicate
                w.writerow(dict(title="Pizza", phone="", website="", category="Restaurant", address="2 Rue, Laval, QC", review_rating="4", review_count="3"))
            cfg = {"address": {"region_pattern": REGION}, "_t": cw.STRINGS["fr"]}
            scfg = {"_regex": __import__("re").compile("d[ée]m[ée]nag|moving", 2)}
            rows = cw.read_maps_csv(p, scfg, cfg)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["sector"], "Montréal")
            self.assertEqual(rows[0]["reviews"], 120)


class Config(unittest.TestCase):
    def test_defaults_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"project": "X", "maps": {"depth": 3}}), encoding="utf8")
            cfg = cw.load_config(p)
            self.assertEqual(cfg["maps"]["depth"], 3)
            self.assertEqual(cfg["maps"]["lang"], "en")  # kept from defaults
            self.assertEqual(cfg["language"], "en")


if __name__ == "__main__":
    unittest.main()
