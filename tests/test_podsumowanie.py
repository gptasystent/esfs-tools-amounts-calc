"""Początek raportu: 5 linii "co jest do zrobienia", kod wyjścia i największe rozbieżności."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc.check import linie_do_zrobienia, main, sprawdz_partie, tekst_podsumowania


def pozycja(netto="10.00", vat="2.30", brutto="12.30"):
    return {"ilosc": 1, "cena_netto_jedn": "10", "stawka_vat": 23, "netto": netto, "vat": vat, "brutto": brutto}


def spojny(id, typ="FV"):
    return {"id": id, "typ": typ, "suma_netto": "10.00", "suma_vat": "2.30", "suma_brutto": "12.30",
            "pozycje": [pozycja()]}


def drobiazg(id):
    d = spojny(id)
    d["suma_brutto"] = "12.305"
    return d


def niepelny(id):
    return {"id": id, "typ": "FV", "suma_netto": "10.00", "suma_vat": "2.30", "suma_brutto": "12.30",
            "pozycje": [{"ilosc": 1, "cena_netto_jedn": "10", "stawka_vat": 23, "netto": "10.00"}]}


def niespojny(id, netto="99.00"):
    d = spojny(id)
    d["suma_netto"] = netto
    return d


def zly(id):
    return {"id": id, "typ": "FV", "pozycje": "x"}


def korekta(id):
    d = niespojny(id)
    d["typ"] = "KOREKTA"
    return d


PARTIA = ([spojny("s%d" % i) for i in range(5)] + [drobiazg("d1"), drobiazg("d2"), drobiazg("d3")]
          + [niepelny("n1"), niepelny("n2")] + [niespojny("x1"), niespojny("x2", "50.00")] + [zly("b1")]
          + [korekta("k%d" % i) for i in range(4)])


class TestPiecLinii(unittest.TestCase):
    def test_dokladnie_piec_linii_na_poczatku(self):
        wyniki, p = sprawdz_partie(PARTIA, pomin_typy="KOREKTA")
        linie = linie_do_zrobienia(p)
        self.assertEqual(len(linie), 5)
        self.assertEqual(linie, [
            "Do sprawdzenia: 3 (niespójne: 2, błędne: 1)",
            "Tylko drobiazgi (POLGROSZ): 3",
            "Niepełne dane (brak VAT w pozycjach): 2",
            "Pominięte typy (KOREKTA): 4",
            "Bez uwag: 5 z 17 dokumentów",
        ])
        self.assertEqual(sum(p["status"].values()), p["liczba_dokumentow"])

    def test_tekst_zaczyna_sie_od_tych_linii(self):
        wyniki, p = sprawdz_partie(PARTIA, pomin_typy="KOREKTA")
        t = tekst_podsumowania(p, wyniki)
        self.assertEqual(t.splitlines()[:5], linie_do_zrobienia(p))
        self.assertEqual(t.splitlines()[5], "")
        self.assertIn("Sprawdzono dokumentów: 17 (w tym pominięto: 4)", t)

    def test_bez_pomijania(self):
        wyniki, p = sprawdz_partie(PARTIA)
        linie = linie_do_zrobienia(p)
        self.assertEqual(linie[0], "Do sprawdzenia: 7 (niespójne: 6, błędne: 1)")
        self.assertEqual(linie[3], "Pominięte typy: brak (patrz --pomin-typy)")

    def test_pominiete_i_drobiazgi_nie_licza_sie_do_uwagi(self):
        _, p = sprawdz_partie([drobiazg("a"), niepelny("b"), korekta("k")], pomin_typy="korekta")
        self.assertEqual(p["wymaga_uwagi"], 0)
        self.assertEqual(p["status"]["drobiazg"], 1)

    def test_pusta_partia(self):
        wyniki, p = sprawdz_partie([])
        self.assertEqual(linie_do_zrobienia(p)[0], "Do sprawdzenia: 0 (niespójne: 0, błędne: 0)")
        self.assertEqual(linie_do_zrobienia(p)[4], "Bez uwag: 0 z 0 dokumentów")

    def test_drobiazgi_nie_zasmiecaja_najwiekszych_rozbieznosci(self):
        wyniki, p = sprawdz_partie(PARTIA, pomin_typy="KOREKTA")
        t = tekst_podsumowania(p, wyniki, 10)
        self.assertNotIn("id=d1", t)
        self.assertIn("id=x1", t)
        self.assertIn("NAGLOWEK_WYZSZY", t)         # kody przyczyn widać także w tej liście
        self.assertLess(t.index("id=x1"), t.index("id=x2"))     # 87 gr przed 40 gr


class TestKodWyjscia(unittest.TestCase):
    def kod(self, dokumenty, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            sciezka = os.path.join(tmp, "d.json")
            with open(sciezka, "w", encoding="utf-8") as f:
                json.dump(dokumenty, f)
            with contextlib.redirect_stdout(io.StringIO()):
                return main([sciezka] + list(argv))

    def test_drobiazgi_i_niepelne_nie_psuja_kodu_wyjscia(self):
        self.assertEqual(self.kod([spojny("a"), drobiazg("b"), niepelny("c")]), 0)

    def test_niespojny_albo_blad_daje_1(self):
        self.assertEqual(self.kod([niespojny("a")]), 1)
        self.assertEqual(self.kod([zly("a")]), 1)

    def test_pominiete_typy_daja_0(self):
        self.assertEqual(self.kod([korekta("k")], "--pomin-typy", "KOREKTA"), 0)


if __name__ == "__main__":
    unittest.main()
