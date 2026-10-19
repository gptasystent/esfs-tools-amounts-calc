"""Pozycje ofert i zamówień: cena zakupu + narzut (marża) => cena sprzedaży zaokrąglona do grosza."""
import unittest
from decimal import ROUND_HALF_EVEN, Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, marza, oblicz, Pozycja
from amounts_calc.adapter import scal_mapowanie, z_wiersza
from amounts_calc.config import Konfiguracja, TRYB_BRUTTO


def of(ilosc, zakup, narzut=None, marza_=None, stawka=23, **kw):
    return Pozycja(ilosc=ilosc, cena_zakupu_jedn=zakup, narzut_proc=narzut, marza_proc=marza_, stawka_vat=stawka, **kw)


class TestCenaSprzedazy(unittest.TestCase):
    def test_narzut_tabela(self):
        tabela = [("80", "25", "100.00"), ("10", "0", "10.00"), ("10", "150", "25.00"), ("7.77", "23", "9.56"),
                  ("0.50", "23", "0.62"), ("0.50", "25", "0.63"), ("33.33", "12.5", "37.50"), ("100", "-10", "90.00"),
                  ("0", "40", "0.00"), ("19.99", "0.01", "19.99")]
        for zakup, narzut, oczek in tabela:
            with self.subTest(zakup=zakup, narzut=narzut):
                self.assertEqual(marza.cena_sprzedazy(zakup, narzut_proc=narzut), D(oczek))

    def test_marza_tabela(self):
        tabela = [("80", "20", "100.00"), ("10", "50", "20.00"), ("10", "0", "10.00"), ("10", "30", "14.29"),
                  ("1", "99", "100.00"), ("7.77", "-25", "6.22")]
        for zakup, m, oczek in tabela:
            with self.subTest(zakup=zakup, marza=m):
                self.assertEqual(marza.cena_sprzedazy(zakup, marza_proc=m), D(oczek))

    def test_zaokraglenie_wg_konfiguracji(self):
        self.assertEqual(marza.cena_sprzedazy("0.50", "25"), D("0.63"))
        self.assertEqual(marza.cena_sprzedazy("0.50", "25", konf=Konfiguracja(zaokraglanie=ROUND_HALF_EVEN)), D("0.62"))
        self.assertEqual(marza.cena_sprzedazy("0.50", "25", konf=Konfiguracja(miejsca_kwot=1)), D("0.6"))

    def test_zaokraglenie_do_grosza_a_do_miejsc_ceny(self):
        # cena_z_narzutu (koszt dokumentu) zostaje na 4 miejscach; cena sprzedaży pozycji jest do grosza
        self.assertEqual(marza.cena_z_narzutu("7.77", "23"), D("9.5571"))
        self.assertEqual(marza.cena_sprzedazy("7.77", "23"), D("9.56"))

    def test_bledy(self):
        przypadki = {
            "oba": (dict(narzut_proc="10", marza_proc="10"), bledy.NARZUT_I_MARZA),
            "marza 100": (dict(marza_proc="100"), bledy.MARZA_POZA_ZAKRESEM),
            "narzut < -100": (dict(narzut_proc="-101"), bledy.MARZA_POZA_ZAKRESEM),
            "smiec": (dict(narzut_proc="abc"), bledy.NIEPOPRAWNA_LICZBA),
            "float": (dict(narzut_proc=1.5), bledy.NIEPOPRAWNA_LICZBA),
        }
        for nazwa, (kw, kod) in przypadki.items():
            with self.subTest(nazwa):
                with self.assertRaises(bledy.BladWalidacji) as cm:
                    marza.cena_sprzedazy("10", **kw)
                self.assertEqual(cm.exception.kod, kod)

    def test_zakup_ujemny_tylko_z_opcja(self):
        with self.assertRaises(bledy.BladWalidacji):
            marza.cena_sprzedazy("-10", "10")
        self.assertEqual(marza.cena_sprzedazy("-10", "10", dopusc_ujemne=True), D("-11.00"))
        self.assertEqual(marza.cena_sprzedazy("-0.50", "25", dopusc_ujemne=True), D("-0.63"))   # symetrycznie

    def test_pole_w_komunikacie(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            marza.cena_sprzedazy("10", marza_proc="100", pole="pozycje[4]")
        self.assertEqual(cm.exception.pole, "pozycje[4].marza_proc")

    def test_marza_i_narzut_rownowazne(self):
        for narzut in ("0", "25", "100", "7.5"):
            m = marza.marza_z_narzutu(narzut)
            self.assertLessEqual(abs(marza.cena_sprzedazy("40", narzut_proc=narzut)
                                     - marza.cena_sprzedazy("40", marza_proc=m)), D("0.01"))


class TestOblicz(unittest.TestCase):
    def test_wartosc_z_zakupu_narzutu_i_rabatu(self):
        d = oblicz([of(3, "80", "25", rabat_proc=10)])
        p = d.pozycje[0]
        self.assertEqual((p.cena_po_rabacie, p.netto, p.vat, p.brutto), (D("90.0000"), D("270.00"), D("62.10"), D("332.10")))
        self.assertEqual(d.suma_netto, D("270.00"))

    def test_marza(self):
        self.assertEqual(oblicz([of(2, "80", marza_=20)]).suma_netto, D("200.00"))

    def test_narzut_zero(self):
        self.assertEqual(oblicz([of(2, "80", "0")]).suma_netto, D("160.00"))

    def test_pierwszenstwo_przed_cena_netto(self):
        p = Pozycja(ilosc=1, cena_netto_jedn="80", cena_zakupu_jedn="80", narzut_proc="25", stawka_vat=23)
        self.assertEqual(oblicz([p]).suma_netto, D("100.00"))

    def test_narzut_bez_zakupu_jest_ignorowany(self):
        p = Pozycja(ilosc=2, cena_netto_jedn="50", narzut_proc="25", stawka_vat=23)
        self.assertEqual(oblicz([p]).suma_netto, D("100.00"))
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([Pozycja(ilosc=1, narzut_proc="25", stawka_vat=23)])
        self.assertEqual(cm.exception.kod, bledy.BRAK_CENY)

    def test_zakup_bez_narzutu_nie_jest_cena(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([Pozycja(ilosc=1, cena_zakupu_jedn="80", stawka_vat=23)])
        self.assertEqual(cm.exception.kod, bledy.BRAK_CENY)

    def test_bledy_ze_wskazaniem_pozycji(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([of(1, "10", "5"), of(1, "10", "5", marza_="5")])
        self.assertEqual((cm.exception.kod, cm.exception.pole), (bledy.NARZUT_I_MARZA, "pozycje[1].narzut_proc"))
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([of(1, "10", marza_="100")])
        self.assertEqual(cm.exception.pole, "pozycje[0].marza_proc")

    def test_mieszane_pozycje_i_rabat_dokumentu(self):
        d = oblicz([of(3, "80", "25"), Pozycja(ilosc=2, cena_netto_jedn="10", stawka_vat=8)], rabat_dokumentu_proc=10)
        self.assertEqual([p.netto for p in d.pozycje], [D("270.00"), D("18.00")])

    def test_tryb_brutto_ignoruje_zakup_i_narzut(self):
        p = Pozycja(ilosc=1, cena_brutto_jedn="123", cena_zakupu_jedn="1", narzut_proc="5", stawka_vat=23)
        self.assertEqual(oblicz([p], tryb=TRYB_BRUTTO).suma_brutto, D("123.00"))

    def test_ujemne_ilosci_przy_narzucie(self):
        d = oblicz([of(-3, "80", "25")], dopusc_ujemne=True)
        self.assertEqual(d.suma_netto, D("-300.00"))
        with self.assertRaises(bledy.BladWalidacji):
            oblicz([of(-3, "80", "25")])

    def test_zgodnosc_z_cena_netto_obliczona_recznie(self):
        for zakup, narzut, ilosc in [("12.34", "17", "3"), ("0.99", "33.3", "10"), ("1000", "8.25", "0.5")]:
            sp = marza.cena_sprzedazy(zakup, narzut_proc=narzut)
            a = oblicz([of(ilosc, zakup, narzut)])
            b = oblicz([Pozycja(ilosc=ilosc, cena_netto_jedn=sp, stawka_vat=23)])
            self.assertEqual((a.suma_netto, a.suma_vat, a.suma_brutto), (b.suma_netto, b.suma_vat, b.suma_brutto))


class TestMapowanieNazw(unittest.TestCase):
    def test_domyslne_aliasy(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 1, "zakup": "80", "narzut": 25, "stawka": 23}]})
        self.assertEqual(d["pozycje"][0], {"ilosc": 1, "cena_zakupu_jedn": "80", "narzut_proc": 25, "stawka_vat": 23})

    def test_marza_alias(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 1, "cena_zakupu": "80", "marza": 20, "stawka": 23}]})
        self.assertEqual((d["pozycje"][0]["cena_zakupu_jedn"], d["pozycje"][0]["marza_proc"]), ("80", 20))

    def test_wlasne_nazwy_z_mapowania(self):
        m = {"pozycja": {"cena_zakupu_jedn": "kosz_zak", "narzut_proc": ["narzut_handl", "narzut"]}}
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 1, "kosz_zak": "80", "narzut_handl": 25, "stawka_vat": 23}]}, m)
        self.assertEqual((d["pozycje"][0]["cena_zakupu_jedn"], d["pozycje"][0]["narzut_proc"]), ("80", 25))
        self.assertEqual(scal_mapowanie(m)["pozycja"]["cena_zakupu_jedn"][0], "kosz_zak")

    def test_none_to_brak_pola(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 1, "zakup": "80", "narzut": None, "stawka": 23}]})
        self.assertNotIn("narzut_proc", d["pozycje"][0])

    def test_wynik_z_adaptera_trafia_do_oblicz(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 3, "zakup": "80", "narzut": 25, "rabat": 10, "stawka": 23}]})
        self.assertEqual(oblicz(d["pozycje"]).suma_netto, D("270.00"))


if __name__ == "__main__":
    unittest.main()
