import io, json, sys, tempfile, unittest, zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import datapipe as dp


class Parsing(unittest.TestCase):
    def test_numbers(self):
        cases = {"1 234,56 $": 1234.56, "1,234.56": 1234.56, "(12.50)": -12.5, "12,5": 12.5, "1.234.567": 1234567.0, "$ 1 200": 1200.0, "-45": -45.0,
                 "abc": None, "": None, "N/A": None, "05/03/2026": None, "2026-03-05": None, "12 h": None}
        for raw, want in cases.items():
            self.assertEqual(dp.parse_number(raw), want, raw)

    def test_dates(self):
        self.assertEqual(dp.parse_date("2026-03-05"), date(2026, 3, 5))
        self.assertEqual(dp.parse_date("05/03/2026"), date(2026, 3, 5))          # day first by default
        self.assertEqual(dp.parse_date("05/03/2026", "mdy"), date(2026, 5, 3))    # month first when asked
        self.assertEqual(dp.parse_date("2026-03-05T14:30:00"), date(2026, 3, 5))
        self.assertEqual(dp.parse_date("45000"), date(2023, 3, 15))               # Excel serial number
        self.assertIsNone(dp.parse_date("hello"))

    def test_bool(self):
        self.assertTrue(dp.parse_bool("Oui"))
        self.assertFalse(dp.parse_bool("non"))
        self.assertIsNone(dp.parse_bool("peut-être"))


class Cleaning(unittest.TestCase):
    ROWS = [{"ID": "1", "Date": "2026-01-05", "Montant": "100 $", "Ville": "Laval"},
            {"ID": "1", "Date": "2026-01-05", "Montant": "100 $", "Ville": "Laval"},      # duplicate
            {"ID": "2", "Date": "06/01/2026", "Montant": "", "Ville": "Montréal"},        # missing amount
            {"ID": "3", "Date": "pas une date", "Montant": "50,5", "Ville": "N/A"},       # bad date, missing city
            {"ID": "4", "Date": "2026-02-01", "Montant": "9 999", "Ville": "Laval"}]      # filtered out

    def spec(self, **kw):
        base = {"columns": {"Montant": "amount"}, "types": {"date": "date", "amount": "money"}, "dedupe": ["id"],
                "drop_missing": ["amount"], "fill": {"ville": "Inconnue"}, "filters": [{"field": "amount", "op": "lte", "value": 5000}]}
        base.update(kw)
        return base

    def test_pipeline(self):
        rows, rep = dp.clean(self.ROWS, self.spec())
        self.assertEqual(rep["rows_in"], 5)
        self.assertEqual(rep["duplicates"], 1)
        self.assertEqual(rep["dropped"], 1)
        self.assertEqual(rep["filtered"], 1)
        self.assertEqual(rep["invalid"], {"date": 1})
        self.assertEqual([r["id"] for r in rows], ["1", "3"])
        self.assertEqual(rows[1]["ville"], "Inconnue")
        self.assertEqual(rows[0]["amount"], 100.0)

    def test_derived_column(self):
        rows, _ = dp.clean([{"Rev": "100", "Cout": "40"}, {"Rev": "10", "Cout": ""}],
                           {"types": {"rev": "number", "cout": "number"}, "derived": [{"name": "margin", "expr": "rev - cout"}]})
        self.assertEqual(rows[0]["margin"], 60.0)
        self.assertIsNone(rows[1]["margin"])

    def test_expression_is_safe(self):
        self.assertIsNone(dp.safe_eval("__import__('os').system('echo hi')", {}))
        self.assertEqual(dp.safe_eval("a * 2", {"a": 4}), 8)


class Metrics(unittest.TestCase):
    TABLE = [{"date": date(2026, 1, 3), "service": "A", "revenue": 100.0, "hours": 2.0},
             {"date": date(2026, 1, 20), "service": "B", "revenue": 50.0, "hours": 1.0},
             {"date": date(2026, 2, 2), "service": "A", "revenue": 300.0, "hours": 3.0},
             {"date": date(2026, 3, 2), "service": "A", "revenue": 120.0, "hours": 1.0}]

    def metric(self, **kw):
        return dp.run_metric({"id": "m", "source": "t", **kw}, {"t": self.TABLE})

    def test_total_and_ratio(self):
        self.assertEqual(self.metric(measure="sum", field="revenue")["total"], 570.0)
        self.assertAlmostEqual(self.metric(measure="ratio", num="revenue", den="hours")["total"], 570 / 7)

    def test_group_by_category(self):
        r = self.metric(measure="sum", field="revenue", by=["service"])
        self.assertEqual([(x["service"], x["value"]) for x in r["rows"]], [("A", 520.0), ("B", 50.0)])

    def test_group_by_month_and_change(self):
        r = self.metric(measure="sum", field="revenue", by=["month:date"])
        self.assertEqual([x["month_date"] for x in r["rows"]], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(r["rows"][1]["change_pct"], 100.0)   # 150 -> 300

    def test_last_period_marked_partial(self):
        r = self.metric(measure="sum", field="revenue", by=["month:date"])
        self.assertTrue(r["rows"][-1].get("partial"))          # data stops on March 2
        self.assertFalse(r["rows"][0].get("partial"))
        text = dp.findings(r, "en")
        self.assertTrue(all("2026-03" not in t for t in text))

    def test_rate(self):
        rows = [{"ok": True}, {"ok": True}, {"ok": False}, {"ok": None}]
        self.assertAlmostEqual(dp.measure(rows, {"measure": "rate", "field": "ok"}), 66.666, places=2)

    def test_top(self):
        self.assertEqual(len(self.metric(measure="count", by=["service"], top=1)["rows"]), 1)


class Joins(unittest.TestCase):
    def test_left_join_keeps_unmatched(self):
        left = [{"k": 1, "a": "x"}, {"k": 2, "a": "y"}]
        right = [{"k": 1, "b": "z"}]
        self.assertEqual(dp.join(left, right, ["k"], "left"), [{"k": 1, "a": "x", "b": "z"}, {"k": 2, "a": "y"}])
        self.assertEqual(len(dp.join(left, right, ["k"], "inner")), 1)

    def test_name_conflict_gets_prefix(self):
        out = dp.join([{"k": 1, "d": "a"}], [{"k": 1, "d": "b"}], ["k"], "left", "right_")
        self.assertEqual(out[0]["right_d"], "b")


class Loading(unittest.TestCase):
    def test_csv_delimiter_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.csv"
            p.write_text("a;b\n1;2\n3;4\n", encoding="utf-8")
            rows, _ = dp.load_rows({"path": str(p)}, Path(d))
            self.assertEqual(rows, [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}])

    def test_xlsx_reader(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>name</t></si><si><t>amount</t></si><si><t>Ana</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                       '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>12.5</v></c></row></sheetData></worksheet>')
        table = dp.read_xlsx(buf.getvalue())
        self.assertEqual(table, [["name", "amount"], ["Ana", "12.5"]])


class EndToEnd(unittest.TestCase):
    def test_run_writes_report_and_exports(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sales.csv").write_text("Date,Amount,Region\n2026-01-05,100,East\n2026-01-06,200,West\n2026-02-01,300,East\n", encoding="utf-8")
            cfg = {"project": "T", "language": "en", "kpis": ["total"],
                   "sources": {"sales": {"path": "sales.csv", "types": {"date": "date", "amount": "money"}}},
                   "metrics": [{"id": "total", "label": "Revenue", "source": "sales", "measure": "sum", "field": "amount", "unit": "$"},
                               {"id": "by_region", "label": "By region", "source": "sales", "measure": "sum", "field": "amount", "by": ["region"]}],
                   "outputs": {"dir": "out", "html": "r.html"}}
            (d / "config.json").write_text(json.dumps(cfg), encoding="utf8")
            dp.main(["run", "--config", str(d / "config.json")])
            html = (d / "out" / "r.html").read_text(encoding="utf8")
            self.assertIn("Revenue", html)
            self.assertIn("$600", html)
            self.assertEqual(json.loads((d / "out" / "export" / "by_region.json").read_text())[0]["region"], "East")


if __name__ == "__main__":
    unittest.main()
