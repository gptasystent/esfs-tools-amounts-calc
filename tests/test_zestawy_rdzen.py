"""Rdzeń zestawów z ilością (zestawy.py): wartości oczekiwane, mnożniki, sumy, stawki, alternatywy."""
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.config import Konfiguracja
from amounts_calc.hierarchia import MAKS_GLEBOKOSC, zbuduj_hierarchie
from amounts_calc.zestawy import (grupy_alternatyw, pasuje_do_jednej_sztuki, podsumowanie_stawek, rozwin, sumy_pozycji,
                                  wybierz_alternatywy)


def w(indeks, netto=None, vat=None, brutto=None, ilosc=1, stawka="23", zestaw=False, alternatywa=None):
    f = lambda x: None if x is None else D(x)
    return {"indeks": indeks, "id": indeks, "ilosc": D(ilosc), "netto": f(netto), "vat": f(vat), "brutto": f(brutto),
            "stawka": stawka, "zestaw": zestaw, "alternatywa": alternatywa}


def dzieci_z(pary):
    return zbuduj_hierarchie(pary)


class TestRozwin(unittest.TestCase):
    def test_zestaw_n_razy_dzieci(self):
        # zestaw ilość 10, dzieci 1 szt.: 600.00 + 117.40
        wiersze = [w(0, ilosc=10, zestaw=True), w(1, "600.00", "138.00", "738.00"), w(2, "117.40", "27.00", "144.40")]
        dz = dzieci_z([(0, None), (1, 0), (2, 0)])
        r = rozwin(wiersze, dz, True)
        self.assertEqual(r["oczekiwane"][0], {"netto": D("7174.00"), "vat": D("1650.00"), "brutto": D("8824.00")})
        self.assertEqual(r["sumy_dzieci"][0]["netto"], D("717.40"))
        self.assertEqual(r["mnozniki"], {1: D(10), 2: D(10)})

    def test_bez_uwzgledniania_ilosci(self):
        wiersze = [w(0, ilosc=10, zestaw=True), w(1, "600.00", "138.00", "738.00"), w(2, "117.40", "27.00", "144.40")]
        dz = dzieci_z([(0, None), (1, 0), (2, 0)])
        r = rozwin(wiersze, dz, False)
        self.assertEqual(r["oczekiwane"][0]["netto"], D("717.40"))
        self.assertEqual(r["mnozniki"], {1: D(1), 2: D(1)})

    def test_n_rowne_1_nie_zaokragla(self):
        wiersze = [w(0, ilosc=1, zestaw=True), w(1, "1.005", "0.001", "1.006")]
        r = rozwin(wiersze, dzieci_z([(0, None), (1, 0)]), True)
        self.assertEqual(r["oczekiwane"][0]["netto"], D("1.005"))      # bez kwantyzacji - jak dawniej

    def test_ilosc_ulamkowa_i_zero(self):
        for n, oczek in [("0.5", "50.00"), ("2.5", "250.00"), ("0", "0.00"), ("1.25", "125.00")]:
            wiersze = [w(0, ilosc=n, zestaw=True), w(1, "100.00", "23.00", "123.00")]
            r = rozwin(wiersze, dzieci_z([(0, None), (1, 0)]), True)
            self.assertEqual(r["oczekiwane"][0]["netto"], D(oczek), n)

    def test_zaokraglenie_ulamkowej_ilosci_polowki_w_gore(self):
        wiersze = [w(0, ilosc="0.5", zestaw=True), w(1, "0.05", "0.01", "0.06")]
        r = rozwin(wiersze, dzieci_z([(0, None), (1, 0)]), True)
        self.assertEqual(r["oczekiwane"][0]["netto"], D("0.03"))          # 0,025 -> 0,03 (ROUND_HALF_UP)

    def test_zaokraglenie_wg_konfiguracji(self):
        from decimal import ROUND_HALF_EVEN
        wiersze = [w(0, ilosc="0.5", zestaw=True), w(1, "0.05", "0.01", "0.06")]
        r = rozwin(wiersze, dzieci_z([(0, None), (1, 0)]), True, Konfiguracja(zaokraglanie=ROUND_HALF_EVEN))
        self.assertEqual(r["oczekiwane"][0]["netto"], D("0.02"))

    def test_podzestaw_mnozy_swoje_dzieci(self):
        # zestaw Z (x2): dziecko A=10 oraz podzestaw P (x3) z dziećmi B=4, C=6  =>  Z = 2 * (10 + 3 * 10) = 80
        wiersze = [w(0, ilosc=2, zestaw=True), w(1, "10.00", "2.30", "12.30"), w(2, ilosc=3, zestaw=True),
                   w(3, "4.00", "0.92", "4.92"), w(4, "6.00", "1.38", "7.38")]
        dz = dzieci_z([(0, None), (1, 0), (2, 0), (3, 2), (4, 2)])
        r = rozwin(wiersze, dz, True)
        self.assertEqual(r["oczekiwane"][2]["netto"], D("30.00"))
        self.assertEqual(r["oczekiwane"][0]["netto"], D("80.00"))
        self.assertEqual(r["oczekiwane"][0]["brutto"], D("98.40"))
        self.assertEqual(r["mnozniki"], {1: D(2), 3: D(6), 4: D(6)})

    def test_brak_kwoty_dziecka_daje_none(self):
        wiersze = [w(0, ilosc=2, zestaw=True), w(1, "10.00", None, "12.30")]
        r = rozwin(wiersze, dzieci_z([(0, None), (1, 0)]), True)
        self.assertEqual(r["oczekiwane"][0], {"netto": D("20.00"), "vat": None, "brutto": D("24.60")})

    def test_limit_glebokosci(self):
        pary = [(0, None)] + [(i, i - 1) for i in range(1, MAKS_GLEBOKOSC + 1)]       # dokładnie na limicie
        zbuduj_hierarchie(pary)
        pary.append((MAKS_GLEBOKOSC + 1, MAKS_GLEBOKOSC))
        with self.assertRaises(bledy.BladWalidacji) as cm:
            zbuduj_hierarchie(pary)
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_HIERARCHIA)
        self.assertIn("zagnieżdżenie", cm.exception.wiadomosc)

    def test_glebokie_zagniezdzenie_rekurencyjnie(self):
        n = 6
        wiersze = [w(i, ilosc=2, zestaw=True) for i in range(n)] + [w(n, "1.00", "0.23", "1.23")]
        dz = dzieci_z([(i, None if i == 0 else i - 1) for i in range(n)] + [(n, n - 1)])
        r = rozwin(wiersze, dz, True)
        self.assertEqual(r["oczekiwane"][0]["netto"], D(2 ** n).quantize(D("0.01")))
        self.assertEqual(r["mnozniki"][n], D(2 ** n))

    def test_pasuje_do_jednej_sztuki(self):
        self.assertTrue(pasuje_do_jednej_sztuki({"netto": D("717.40"), "vat": D("1"), "brutto": D("2")},
                                                {"netto": D("717.40"), "vat": D("1"), "brutto": D("2")}))
        self.assertFalse(pasuje_do_jednej_sztuki({"netto": D("7174.00"), "vat": D("1")}, {"netto": D("717.40"), "vat": D("1")}))
        self.assertFalse(pasuje_do_jednej_sztuki({"netto": None}, {"netto": D("1")}))


class TestSumy(unittest.TestCase):
    def setUp(self):
        # zestaw x3 (dzieci 100 @23% i 50 @8%) + osobna pozycja 20 @23%
        self.wiersze = [w(0, ilosc=3, zestaw=True), w(1, "100.00", "23.00", "123.00", stawka="23"),
                        w(2, "50.00", "4.00", "54.00", stawka="8"), w(3, "20.00", "4.60", "24.60", stawka="23")]
        self.dz = dzieci_z([(0, None), (1, 0), (2, 0), (3, None)])

    def test_suma_pozycji_n_razy_dzieci_plus_reszta(self):
        r = rozwin(self.wiersze, self.dz, True)
        self.assertEqual(sumy_pozycji(self.wiersze, self.dz, r),
                         {"netto": D("470.00"), "vat": D("85.60"), "brutto": D("555.60")})

    def test_dzieci_nie_sa_liczone_drugi_raz(self):
        r = rozwin(self.wiersze, self.dz, True)
        naiwna = sum(x["netto"] for x in self.wiersze if not x["zestaw"])
        self.assertEqual(naiwna, D("170.00"))
        self.assertNotEqual(sumy_pozycji(self.wiersze, self.dz, r)["netto"], naiwna)
        self.assertEqual(sumy_pozycji(self.wiersze, self.dz, rozwin(self.wiersze, self.dz, False))["netto"], D("170.00"))

    def test_podsumowanie_stawek(self):
        r = rozwin(self.wiersze, self.dz, True)
        ps = podsumowanie_stawek(self.wiersze, self.dz, r)
        self.assertEqual(list(ps), ["23", "8"])
        self.assertEqual(ps["23"], {"netto": D("320.00"), "vat": D("73.60"), "brutto": D("393.60")})
        self.assertEqual(ps["8"], {"netto": D("150.00"), "vat": D("12.00"), "brutto": D("162.00")})

    def test_podsumowanie_stawek_zgadza_sie_z_suma_pozycji_przy_ulamkowej_ilosci(self):
        wiersze = [w(0, ilosc="0.5", zestaw=True), w(1, "0.05", "0.01", "0.06", stawka="23"),
                   w(2, "0.05", "0.01", "0.06", stawka="8"), w(3, "0.07", "0.02", "0.09", stawka="5")]
        dz = dzieci_z([(0, None), (1, 0), (2, 0), (3, 0)])
        r = rozwin(wiersze, dz, True)
        ps = podsumowanie_stawek(wiersze, dz, r)
        sumy = sumy_pozycji(wiersze, dz, r)
        for pole in ("netto", "vat", "brutto"):
            self.assertEqual(sum(v[pole] for v in ps.values()), sumy[pole], pole)

    def test_n_rowne_1_to_zwykle_sumy_bez_zaokraglen(self):
        wiersze = [w(0, ilosc=1, zestaw=True), w(1, "1.005", "0.001", "1.006"), w(2, "2.005", "0.002", "2.007", stawka="8")]
        dz = dzieci_z([(0, None), (1, 0), (2, 0)])
        r = rozwin(wiersze, dz, True)
        ps = podsumowanie_stawek(wiersze, dz, r)
        self.assertEqual((ps["23"]["netto"], ps["8"]["netto"]), (D("1.005"), D("2.005")))


class TestAlternatywy(unittest.TestCase):
    def setUp(self):
        self.wiersze = [w(0, "100.00", "23.00", "123.00"),
                        w(1, "40.00", "9.20", "49.20", alternatywa="opcje"),
                        w(2, "60.00", "13.80", "73.80", alternatywa="opcje")]
        self.dz = {}
        self.r = rozwin(self.wiersze, self.dz, True)

    def naglowek(self, netto, vat, brutto):
        return {"netto": D(netto), "vat": D(vat), "brutto": D(brutto)}

    def test_grupy(self):
        self.assertEqual(grupy_alternatyw(self.wiersze, self.r["rodzic"]), {"opcje": [1, 2]})

    def test_domyslnie_alternatywy_nie_wchodza_do_sumy(self):
        self.assertEqual(sumy_pozycji(self.wiersze, self.dz, self.r)["netto"], D("100.00"))
        self.assertEqual(sumy_pozycji(self.wiersze, self.dz, self.r, frozenset({2}))["netto"], D("160.00"))

    def test_wybor_zadnej(self):
        wybrane, tryb = wybierz_alternatywy(self.wiersze, self.dz, self.r, self.naglowek("100", "23", "123"))
        self.assertEqual((wybrane, tryb), (frozenset(), "zgodne"))

    def test_wybor_jednej(self):
        wybrane, tryb = wybierz_alternatywy(self.wiersze, self.dz, self.r, self.naglowek("160", "36.8", "196.8"))
        self.assertEqual((wybrane, tryb), (frozenset({2}), "zgodne"))

    def test_wszystkie_naraz_nie_pasuja(self):
        wybrane, tryb = wybierz_alternatywy(self.wiersze, self.dz, self.r, self.naglowek("200", "46", "246"))
        self.assertEqual(tryb, "najblizsze")
        self.assertEqual(len(wybrane), 1)

    def test_bez_alternatyw(self):
        wiersze = self.wiersze[:1]
        r = rozwin(wiersze, {}, True)
        self.assertEqual(wybierz_alternatywy(wiersze, {}, r, self.naglowek("1", "1", "1")), (frozenset(), "brak"))

    def test_dwie_grupy(self):
        wiersze = self.wiersze + [w(3, "10.00", "2.30", "12.30", alternatywa="B"), w(4, "20.00", "4.60", "24.60", alternatywa="B")]
        r = rozwin(wiersze, {}, True)
        wybrane, tryb = wybierz_alternatywy(wiersze, {}, r, self.naglowek("170", "39.1", "209.1"))   # 100 + 60 (grupa opcje) + 10 (grupa B)
        self.assertEqual(tryb, "zgodne")
        self.assertEqual(wybrane, frozenset({2, 3}))

    def test_zestaw_jako_opcja(self):
        wiersze = [w(0, "100.00", "23.00", "123.00"), w(1, ilosc=2, zestaw=True, alternatywa="A"),
                   w(2, "10.00", "2.30", "12.30")]
        dz = dzieci_z([(0, None), (1, None), (2, 1)])
        r = rozwin(wiersze, dz, True)
        wybrane, tryb = wybierz_alternatywy(wiersze, dz, r, self.naglowek("120", "27.6", "147.6"))
        self.assertEqual((wybrane, tryb), (frozenset({1}), "zgodne"))

    def test_zbyt_wiele_kombinacji_tryb_zachlanny(self):
        wiersze = [w(0, "1.00", "0.23", "1.23")]
        n_grup = 7
        for g in range(n_grup):
            for k in range(4):
                wiersze.append(w(len(wiersze), str(10 ** k), "0", str(10 ** k), alternatywa=g))
        r = rozwin(wiersze, {}, True)
        wybrane, tryb = wybierz_alternatywy(wiersze, {}, r, {"netto": D("1.00"), "vat": D("0.23"), "brutto": D("1.23")})
        self.assertEqual((wybrane, tryb), (frozenset(), "zgodne"))


if __name__ == "__main__":
    unittest.main()
