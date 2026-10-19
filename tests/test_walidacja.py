import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, oblicz, Pozycja


def kod_bledu(testcase, **kw):
    with testcase.assertRaises(bledy.BladWalidacji) as cm:
        oblicz(**kw)
    return cm.exception


def p(**kw):
    dane = dict(ilosc=1, cena_netto_jedn="10", stawka_vat=23, rabat_proc=0)
    dane.update(kw)
    return Pozycja(**dane)


class TestWalidacja(unittest.TestCase):
    def test_ujemna_ilosc(self):
        e = kod_bledu(self, pozycje=[p(ilosc="-1")])
        self.assertEqual(e.kod, bledy.ILOSC_UJEMNA)
        self.assertIn("pozycje[0].ilosc", e.pole)

    def test_rabat_powyzej_100(self):
        for r in ("100.01", 101, 1000):
            with self.subTest(r=r):
                self.assertEqual(kod_bledu(self, pozycje=[p(rabat_proc=r)]).kod, bledy.RABAT_POZA_ZAKRESEM)

    def test_rabat_ujemny(self):
        self.assertEqual(kod_bledu(self, pozycje=[p(rabat_proc=-1)]).kod, bledy.RABAT_POZA_ZAKRESEM)

    def test_rabat_dokumentu_poza_zakresem(self):
        for r in (101, -5):
            self.assertEqual(kod_bledu(self, pozycje=[p()], rabat_dokumentu_proc=r).kod,
                             bledy.RABAT_POZA_ZAKRESEM)

    def test_nieznana_stawka(self):
        for st in (7, 22, "abc", None, "zwolniona"):
            with self.subTest(st=st):
                self.assertEqual(kod_bledu(self, pozycje=[p(stawka_vat=st)]).kod, bledy.NIEZNANA_STAWKA)

    def test_ujemna_cena(self):
        self.assertEqual(kod_bledu(self, pozycje=[p(cena_netto_jedn="-0.01")]).kod, bledy.CENA_UJEMNA)

    def test_float_wszedzie_odrzucony(self):
        for pole in ("ilosc", "cena_netto_jedn", "rabat_proc"):
            with self.subTest(pole=pole):
                e = kod_bledu(self, pozycje=[p(**{pole: 1.5})])
                self.assertEqual(e.kod, bledy.NIEPOPRAWNA_LICZBA)

    def test_smieci_jako_liczba(self):
        self.assertEqual(kod_bledu(self, pozycje=[p(ilosc="dużo")]).kod, bledy.NIEPOPRAWNA_LICZBA)

    def test_nan_i_inf(self):
        for v in ("NaN", "Infinity"):
            self.assertEqual(kod_bledu(self, pozycje=[p(cena_netto_jedn=v)]).kod, bledy.NIEPOPRAWNA_LICZBA)

    def test_brak_ceny(self):
        self.assertEqual(kod_bledu(self, pozycje=[p(cena_netto_jedn=None)]).kod, bledy.BRAK_CENY)
        self.assertEqual(kod_bledu(self, pozycje=[p()], tryb="brutto").kod, bledy.BRAK_CENY)

    def test_zly_tryb(self):
        self.assertEqual(kod_bledu(self, pozycje=[p()], tryb="x").kod, bledy.NIEPOPRAWNY_TRYB)
        self.assertEqual(kod_bledu(self, pozycje=[p()], tryb_vat="x").kod, bledy.NIEPOPRAWNY_TRYB)

    def test_zla_waluta(self):
        for w in ("pln", "PL", "PLNN", "", None, "P1N", 5):
            with self.subTest(w=w):
                self.assertEqual(kod_bledu(self, pozycje=[p()], waluta=w).kod, bledy.NIEPOPRAWNA_WALUTA)

    def test_blad_wskazuje_indeks_pozycji(self):
        e = kod_bledu(self, pozycje=[p(), p(), p(ilosc=-1)])
        self.assertIn("pozycje[2]", e.pole)

    def test_slownik_bez_wymaganego_pola(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([{"ilosc": 1, "cena_netto_jedn": "1"}])
        self.assertEqual(cm.exception.kod, bledy.BRAK_POLA)

    def test_blad_walidacji_jest_valueerror(self):
        with self.assertRaises(ValueError):
            oblicz([p(ilosc=-1)])

    def test_granice_dozwolone(self):
        d = oblicz([p(ilosc=0, rabat_proc=100)])
        self.assertEqual(d.suma_brutto, D("0.00"))
        oblicz([p(rabat_proc=0)], rabat_dokumentu_proc=100)


if __name__ == "__main__":
    unittest.main()
