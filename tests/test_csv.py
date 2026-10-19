import contextlib
import csv
import io
import json
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc.check import KOLUMNY_CSV, _komorka_tekstowa, main, sprawdz_partie, zapisz_csv
from tests.test_podsumowanie import PARTIA, korekta, niespojny, spojny


def wczytaj(sciezka):
    with open(sciezka, "rb") as f:
        surowy = f.read()
    with open(sciezka, encoding="utf-8-sig", newline="") as f:
        wiersze = list(csv.reader(f, delimiter=";"))
    return surowy, wiersze


class TestCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def sciezka(self, nazwa):
        return os.path.join(self.tmp.name, nazwa)

    def uruchom(self, dokumenty, *argv):
        wej = self.sciezka("d.json")
        with open(wej, "w", encoding="utf-8") as f:
            json.dump(dokumenty, f)
        with contextlib.redirect_stdout(io.StringIO()):
            return main([wej] + list(argv))

    def test_bom_separator_crlf(self):
        wyj = self.sciezka("w.csv")
        self.uruchom(PARTIA, "--csv", wyj)
        surowy, wiersze = wczytaj(wyj)
        self.assertTrue(surowy.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(surowy.count(b"\xef\xbb\xbf"), 1)
        self.assertIn(b"\r\n", surowy)
        self.assertNotIn(b"\n", surowy.replace(b"\r\n", b""))
        self.assertEqual(tuple(wiersze[0]), KOLUMNY_CSV)
        self.assertEqual(wiersze[0][0], "indeks")          # BOM nie wchodzi do pierwszej nazwy kolumny
        self.assertTrue(all(len(w) == len(KOLUMNY_CSV) for w in wiersze))
        self.assertIn(b";", surowy.split(b"\r\n")[0])

    def test_jedna_linia_na_dokument_z_problemem(self):
        wyj = self.sciezka("w.csv")
        self.uruchom(PARTIA, "--csv", wyj, "--pomin-typy", "KOREKTA")
        _, wiersze = wczytaj(wyj)
        ids = [w[1] for w in wiersze[1:]]
        self.assertEqual(sorted(ids), ["b1", "d1", "d2", "d3", "n1", "n2", "x1", "x2"])   # bez spójnych i pominiętych
        self.assertEqual(len(set(ids)), len(ids))

    def test_zawartosc_kolumn(self):
        wyj = self.sciezka("w.csv")
        self.uruchom(PARTIA, "--csv", wyj, "--pomin-typy", "KOREKTA")
        _, wiersze = wczytaj(wyj)
        po_id = {w[1]: dict(zip(KOLUMNY_CSV, w)) for w in wiersze[1:]}
        x1 = po_id["x1"]
        self.assertEqual((x1["typ"], x1["status"], x1["najwieksza_roznica"], x1["tryb_vat_pasuje"]),
                         ("FV", "niespojny", "89,00", "zaden"))
        self.assertIn("NAGLOWEK_WYZSZY", x1["kody"])
        self.assertIn("SUMA_POZYCJI_ROZNA_OD_DOKUMENTU", x1["kody"])
        self.assertEqual(po_id["d1"]["status"], "drobiazg")
        self.assertEqual(po_id["d1"]["kody"], "NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, POLGROSZ, SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, "
                                              "SUMA_STAWEK_ROZNA_OD_DOKUMENTU")
        self.assertEqual(po_id["n1"]["kody"], "BRAK_VAT_W_POZYCJACH")
        self.assertEqual(po_id["b1"]["kody"], "BRAK_POLA")
        self.assertEqual(po_id["b1"]["tryb_vat_pasuje"], "")
        self.assertEqual(po_id["b1"]["najwieksza_roznica"], "0,00")

    def test_przecinek_dziesietny(self):
        wyj = self.sciezka("w.csv")
        self.uruchom([niespojny("a", "10.5")], "--csv", wyj)
        _, wiersze = wczytaj(wyj)
        self.assertEqual(dict(zip(KOLUMNY_CSV, wiersze[1]))["najwieksza_roznica"], "0,50")

    def test_trudne_id_i_polskie_znaki(self):
        d = niespojny("zażółć; \"gęślą\"\njaźń")
        wyj = self.sciezka("w.csv")
        self.uruchom([d], "--csv", wyj)
        _, wiersze = wczytaj(wyj)
        self.assertEqual(wiersze[1][1], "zażółć; \"gęślą\"\njaźń")
        self.assertEqual(len(wiersze), 2)

    def test_typ_i_id_nietekstowe(self):
        d = niespojny(12345)
        d["typ"] = 7
        wyj = self.sciezka("w.csv")
        self.uruchom([d], "--csv", wyj)
        _, wiersze = wczytaj(wyj)
        self.assertEqual((wiersze[1][1], wiersze[1][2]), ("12345", "7"))

    def test_wstrzykniecie_formul(self):
        tabela = [("=SUM(A1)", "'=SUM(A1)"), ("+1+1", "'+1+1"), ("@cmd", "'@cmd"), ("-cmd", "'-cmd"),
                  ("-5", "-5"), ("-.5", "-.5"), ("FV/1", "FV/1"), ("", ""), (None, "")]
        for wej, oczek in tabela:
            with self.subTest(wej=wej):
                self.assertEqual(_komorka_tekstowa(wej), oczek)

    def test_pusty_plik_ma_naglowek(self):
        wyj = self.sciezka("w.csv")
        self.assertEqual(self.uruchom([spojny("a")], "--csv", wyj), 0)
        surowy, wiersze = wczytaj(wyj)
        self.assertEqual(wiersze, [list(KOLUMNY_CSV)])

    def test_zapisz_csv_bezposrednio(self):
        wyniki, _ = sprawdz_partie([korekta("k")])
        wyj = self.sciezka("w.csv")
        zapisz_csv(wyj, wyniki)
        _, wiersze = wczytaj(wyj)
        self.assertEqual(wiersze[1][2], "KOREKTA")

    def test_json_i_csv_razem_oraz_blad_zapisu(self):
        wyj_j, wyj_c = self.sciezka("w.json"), self.sciezka("w.csv")
        self.uruchom([niespojny("a")], "--json", wyj_j, "--csv", wyj_c)
        self.assertTrue(os.path.exists(wyj_j) and os.path.exists(wyj_c))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.uruchom([niespojny("a")], "--csv", os.path.join(self.tmp.name, "nie_ma", "w.csv")), 2)


if __name__ == "__main__":
    unittest.main()
