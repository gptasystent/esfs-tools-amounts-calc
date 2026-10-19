import contextlib
import decimal
import io
import json
import os
import tempfile
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc.check import main, sprawdz_dokument, wynik_json
from amounts_calc.formatowanie import format_bez_zer, format_kwoty, miejsca_znaczace


class TestFormat(unittest.TestCase):
    def test_format_kwoty_tabela(self):
        tabela = [
            ("140220.000000000000000000000", "140220.00"),
            ("1758.285000000000000000000", "1758.285"),
            ("140220.0000", "140220.00"),
            ("0", "0.00"), ("0E-10", "0.00"), ("-0.00", "0.00"), ("0.000", "0.00"),
            ("12.5", "12.50"), ("12", "12.00"), ("1E+2", "100.00"), ("-3.10", "-3.10"),
            ("-3.1000", "-3.10"), ("0.005000", "0.005"), ("0.0100", "0.01"), ("-0.005", "-0.005"),
            ("1234567890123456789012345678901.1000", "1234567890123456789012345678901.10"),
            ("1E+30", "1000000000000000000000000000000.00"),
            ("0.1000000000000000055511151231257827", "0.1000000000000000055511151231257827"),
        ]
        for wej, oczek in tabela:
            with self.subTest(wej=wej):
                self.assertEqual(format_kwoty(D(wej)), oczek)

    def test_nic_nie_jest_zaokraglane(self):
        for wej in ("1758.285", "0.0049", "1.23456789012345678901234567890123456789"):
            self.assertEqual(D(format_kwoty(D(wej))), D(wej))

    def test_format_bez_zer(self):
        for wej, oczek in [("100.00", "100"), ("0.50", "0.5"), ("0.000", "0"), ("-0.0", "0"), ("7", "7"),
                           ("1E+2", "100")]:
            self.assertEqual(format_bez_zer(D(wej)), oczek)

    def test_miejsca_znaczace(self):
        for wej, n in [("1758.285000", 3), ("140220.0000", 0), ("0.01", 2), ("0.0100", 2), ("5", 0), ("1.1", 1)]:
            self.assertEqual(miejsca_znaczace(D(wej)), n, wej)

    def test_nie_zalezy_od_kontekstu_decimal(self):
        duza = D("1234567890123456789012345678901234567890.1234500")
        with decimal.localcontext() as ctx:
            ctx.prec = 5
            self.assertEqual(format_kwoty(duza), "1234567890123456789012345678901234567890.12345")


class TestFormatWRaporcie(unittest.TestCase):
    DOK = {"id": "Z", "suma_netto": "140220.000000000000000000000", "suma_vat": "0.000000000000000000000",
           "suma_brutto": "1758.285000000000000000000",
           "pozycje": [{"ilosc": 1, "cena_netto_jedn": "140220", "stawka_vat": "zw",
                        "netto": "140220.000000000000000000000", "vat": "0.000000000000000000000",
                        "brutto": "140220.000000000000000000000"}]}

    def test_json_bez_ogona_zer(self):
        w = wynik_json(sprawdz_dokument(self.DOK))
        tekst = json.dumps(w)
        self.assertNotIn("000000", tekst)
        brutto = [n for n in w["niespojnosci"] if n["pole"] == "suma_brutto" and n["zakres"] == "dokument"]
        self.assertTrue(brutto)
        self.assertIn(brutto[0]["jest"], ("1758.285",))
        self.assertEqual(brutto[0]["oczekiwano"], "140220.00")

    def test_plik_json_i_tekst(self):
        with tempfile.TemporaryDirectory() as tmp:
            wej, wyj = os.path.join(tmp, "d.json"), os.path.join(tmp, "w.json")
            with open(wej, "w", encoding="utf-8") as f:
                f.write(json.dumps([self.DOK]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main([wej, "--json", wyj])
            with open(wyj, encoding="utf-8") as f:
                surowy = f.read()
            self.assertNotIn("0000000", surowy)
            self.assertNotIn("0000000", out.getvalue())
            self.assertIn("1758.285", surowy)
            self.assertIn("140220.00", surowy)


if __name__ == "__main__":
    unittest.main()
