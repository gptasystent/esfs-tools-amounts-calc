import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, marza, oblicz, Pozycja


class TestNarzutMarza(unittest.TestCase):
    def test_roznica_narzut_vs_marza(self):
        # koszt 80, cena 100: narzut 25%, marża 20%
        self.assertEqual(marza.narzut_z_cen("80", "100"), D("25.00"))
        self.assertEqual(marza.marza_z_cen("80", "100"), D("20.00"))

    def test_cena_z_narzutu(self):
        self.assertEqual(marza.cena_z_narzutu("80", "25"), D("100.0000"))
        self.assertEqual(marza.cena_z_narzutu("10", "0"), D("10.0000"))
        self.assertEqual(marza.cena_z_narzutu("10", "150"), D("25.0000"))

    def test_cena_z_marzy(self):
        self.assertEqual(marza.cena_z_marzy("80", "20"), D("100.0000"))
        self.assertEqual(marza.cena_z_marzy("10", "50"), D("20.0000"))
        self.assertEqual(marza.cena_z_marzy("10", "0"), D("10.0000"))

    def test_zaokraglanie_ceny(self):
        self.assertEqual(marza.cena_z_marzy("10", "30"), D("14.2857"))  # 10 / 0.7

    def test_odwrotnosc_narzut_cena(self):
        for koszt, narzut in [("80", "25"), ("12.50", "40"), ("1", "100"), ("0.5", "7.5")]:
            with self.subTest(koszt=koszt, narzut=narzut):
                cena = marza.cena_z_narzutu(koszt, narzut)
                # cena jest zaokrąglona do 4 miejsc, więc odwrotność zgadza się do 0,01 pp
                self.assertLessEqual(abs(marza.narzut_z_cen(koszt, cena) - D(narzut)), D("0.01"))

    def test_odwrotnosc_marza_cena(self):
        for koszt, m in [("80", "20"), ("12.50", "40"), ("1", "50"), ("0.5", "7.5")]:
            with self.subTest(koszt=koszt, m=m):
                cena = marza.cena_z_marzy(koszt, m)
                self.assertLessEqual(abs(marza.marza_z_cen(koszt, cena) - D(m)), D("0.01"))

    def test_przeliczenie_miedzy_soba(self):
        self.assertEqual(marza.marza_z_narzutu("25"), D("20.00"))
        self.assertEqual(marza.narzut_z_marzy("20"), D("25.00"))
        self.assertEqual(marza.marza_z_narzutu("100"), D("50.00"))
        self.assertEqual(marza.narzut_z_marzy("50"), D("100.00"))

    def test_marza_100_niedozwolona(self):
        for f in (lambda: marza.cena_z_marzy("10", "100"), lambda: marza.cena_z_marzy("10", "120"),
                  lambda: marza.narzut_z_marzy("100")):
            with self.assertRaises(bledy.BladWalidacji) as cm:
                f()
            self.assertEqual(cm.exception.kod, bledy.MARZA_POZA_ZAKRESEM)

    def test_dzielenie_przez_zero(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            marza.narzut_z_cen("0", "10")
        self.assertEqual(cm.exception.kod, bledy.DZIELENIE_PRZEZ_ZERO)
        with self.assertRaises(bledy.BladWalidacji) as cm:
            marza.marza_z_cen("10", "0")
        self.assertEqual(cm.exception.kod, bledy.DZIELENIE_PRZEZ_ZERO)

    def test_ujemny_koszt_i_float(self):
        with self.assertRaises(bledy.BladWalidacji):
            marza.cena_z_narzutu("-1", "10")
        with self.assertRaises(bledy.BladWalidacji):
            marza.cena_z_narzutu(10.0, "10")

    def test_ujemna_marza_i_narzut_dozwolone_sprzedaz_ponizej_kosztu(self):
        self.assertEqual(marza.marza_z_cen("100", "80"), D("-25.00"))
        self.assertEqual(marza.narzut_z_cen("100", "80"), D("-20.00"))


class TestNarzutWDokumencie(unittest.TestCase):
    def test_cena_z_kosztu_i_narzutu(self):
        d = oblicz([Pozycja(ilosc=2, koszt_zakupu_jedn="80", stawka_vat=23)], narzut_proc=25)
        self.assertEqual(d.suma_netto, D("200.00"))
        self.assertEqual(d.suma_brutto, D("246.00"))

    def test_cena_z_kosztu_i_marzy(self):
        d = oblicz([Pozycja(ilosc=1, koszt_zakupu_jedn="80", stawka_vat=23)], marza_proc=20)
        self.assertEqual(d.suma_netto, D("100.00"))

    def test_jawna_cena_ma_pierwszenstwo(self):
        d = oblicz([Pozycja(ilosc=1, cena_netto_jedn="50", koszt_zakupu_jedn="80")], narzut_proc=25)
        self.assertEqual(d.suma_netto, D("50.00"))

    def test_narzut_i_marza_naraz(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([Pozycja(ilosc=1, koszt_zakupu_jedn="1")], narzut_proc=10, marza_proc=10)
        self.assertEqual(cm.exception.kod, bledy.NARZUT_I_MARZA)

    def test_koszt_bez_narzutu_to_brak_ceny(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([Pozycja(ilosc=1, koszt_zakupu_jedn="1")])
        self.assertEqual(cm.exception.kod, bledy.BRAK_CENY)

    def test_narzut_w_trybie_brutto_niedozwolony(self):
        with self.assertRaises(bledy.BladWalidacji):
            oblicz([Pozycja(ilosc=1, cena_brutto_jedn="1")], tryb="brutto", narzut_proc=10)


if __name__ == "__main__":
    unittest.main()
