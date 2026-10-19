import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import oblicz, Pozycja
from amounts_calc.config import TRYB_BRUTTO, VAT_PER_POZYCJA, VAT_PER_STAWKA


def pb(ilosc, cena, stawka=23, rabat=0):
    return Pozycja(ilosc=ilosc, cena_brutto_jedn=cena, stawka_vat=stawka, rabat_proc=rabat)


class TestOdBrutto(unittest.TestCase):
    def test_prosta_pozycja(self):
        d = oblicz([pb(1, "123.00")], tryb=TRYB_BRUTTO)
        p = d.pozycje[0]
        self.assertEqual((p.netto, p.vat, p.brutto), (D("100.00"), D("23.00"), D("123.00")))

    def test_brutto_nie_dryfuje(self):
        # brutto wejściowe zawsze zostaje brutto wynikowym
        for cena in ("0.01", "0.99", "1.00", "9.99", "12.34", "99.99", "1234.56"):
            for st in (23, 8, 5, 0, "zw", "np"):
                for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
                    with self.subTest(cena=cena, st=st, tv=tv):
                        d = oblicz([pb(1, cena, st)], tryb=TRYB_BRUTTO, tryb_vat=tv)
                        p = d.pozycje[0]
                        self.assertEqual(p.brutto, D(cena))
                        self.assertEqual(p.netto + p.vat, p.brutto)

    def test_netto_plus_vat_rowna_sie_brutto_dla_wielu_pozycji(self):
        d = oblicz([pb(3, "9.99"), pb(7, "0.33"), pb(2, "5.55", 8)], tryb=TRYB_BRUTTO)
        for p in d.pozycje:
            self.assertEqual(p.netto + p.vat, p.brutto)
        self.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)

    def test_per_stawka_roznica_groszy_na_najwiekszej_pozycji(self):
        pozycje = [pb(1, "1.23"), pb(1, "1.23"), pb(1, "10.00"), pb(1, "1.23")]
        d = oblicz(pozycje, tryb=TRYB_BRUTTO, tryb_vat=VAT_PER_STAWKA)
        # suma brutto 13.69 -> netto 11.13 (13.69/1.23 = 11.1301), vat 2.56
        self.assertEqual(d.suma_brutto, D("13.69"))
        self.assertEqual(d.suma_netto, D("11.13"))
        self.assertEqual(d.suma_vat, D("2.56"))
        self.assertEqual(sum(p.netto for p in d.pozycje), D("11.13"))
        self.assertEqual(sum(p.vat for p in d.pozycje), d.suma_vat)

    def test_per_stawka_vs_per_pozycja_roznica_brutto(self):
        pozycje = [pb(1, "0.35")] * 3
        a = oblicz(pozycje, tryb=TRYB_BRUTTO, tryb_vat=VAT_PER_POZYCJA)
        b = oblicz(pozycje, tryb=TRYB_BRUTTO, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual(a.suma_brutto, b.suma_brutto)
        self.assertEqual(a.suma_netto, D("0.84"))   # 3 x round(0.2846)=0.28
        self.assertEqual(b.suma_netto, D("0.85"))   # round(1.05/1.23 = 0.8537)
        self.assertEqual(a.suma_vat, D("0.21"))
        self.assertEqual(b.suma_vat, D("0.20"))

    def test_korekta_deterministyczna_remis(self):
        d1 = oblicz([pb(1, "0.35")] * 3, tryb=TRYB_BRUTTO)
        d2 = oblicz([pb(1, "0.35")] * 3, tryb=TRYB_BRUTTO)
        self.assertEqual(d1, d2)
        self.assertEqual([p.netto for p in d1.pozycje], [D("0.29"), D("0.28"), D("0.28")])

    def test_zw_np_brutto_rowne_netto(self):
        for st in ("zw", "np", 0):
            d = oblicz([pb(2, "5.55", st)], tryb=TRYB_BRUTTO)
            self.assertEqual((d.suma_netto, d.suma_vat), (D("11.10"), D("0.00")))

    def test_rabat_w_trybie_brutto(self):
        d = oblicz([pb(1, "123.00", rabat=50)], tryb=TRYB_BRUTTO)
        self.assertEqual((d.suma_brutto, d.suma_netto, d.suma_vat), (D("61.50"), D("50.00"), D("11.50")))

    def test_rabat_dokumentu_w_trybie_brutto(self):
        d = oblicz([pb(2, "61.50")], tryb=TRYB_BRUTTO, rabat_dokumentu_proc=50)
        self.assertEqual(d.suma_brutto, D("61.50"))
        self.assertEqual(d.suma_netto, D("50.00"))

    def test_symetria_netto_brutto_dla_okraglych_kwot(self):
        n = oblicz([Pozycja(ilosc=2, cena_netto_jedn="50.00", stawka_vat=23)])
        b = oblicz([pb(2, "61.50")], tryb=TRYB_BRUTTO)
        self.assertEqual((n.suma_netto, n.suma_vat, n.suma_brutto), (b.suma_netto, b.suma_vat, b.suma_brutto))

    def test_duze_brutto(self):
        d = oblicz([pb(10 ** 12, "123456.78")], tryb=TRYB_BRUTTO)
        self.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)
        self.assertEqual(d.suma_brutto, D("123456780000000000.00"))

    def test_tysiac_pozycji_001_brutto(self):
        d = oblicz([pb(1, "0.01")] * 1000, tryb=TRYB_BRUTTO)
        self.assertEqual(d.suma_brutto, D("10.00"))
        self.assertEqual(d.suma_netto, D("8.13"))     # 10.00 / 1.23 = 8.1301
        self.assertEqual(d.suma_vat, D("1.87"))
        self.assertEqual(sum(p.netto for p in d.pozycje), D("8.13"))
        for p in d.pozycje:
            self.assertEqual(p.netto + p.vat, p.brutto)


if __name__ == "__main__":
    unittest.main()
