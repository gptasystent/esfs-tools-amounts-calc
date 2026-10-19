import unittest
from decimal import ROUND_HALF_EVEN, Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.config import DOMYSLNA, Konfiguracja
from amounts_calc.stawki import do_decimal, normalizuj_stawke, wartosc_stawki


class TestZaokraglanie(unittest.TestCase):
    def test_polowki_w_gore(self):
        tabela = [("0.005", "0.01"), ("0.015", "0.02"), ("0.025", "0.03"), ("0.035", "0.04"),
                  ("0.004", "0.00"), ("0.0049999", "0.00"), ("1.005", "1.01"), ("2.675", "2.68")]
        for wej, oczek in tabela:
            with self.subTest(wej=wej):
                self.assertEqual(DOMYSLNA.kwota(D(wej)), D(oczek))

    def test_domyslna_regula_to_half_up(self):
        self.assertEqual(DOMYSLNA.zaokraglanie, "ROUND_HALF_UP")

    def test_inna_regula_w_jednym_miejscu(self):
        k = Konfiguracja(zaokraglanie=ROUND_HALF_EVEN)
        self.assertEqual(k.kwota(D("0.025")), D("0.02"))
        self.assertEqual(DOMYSLNA.kwota(D("0.025")), D("0.03"))

    def test_miejsca_ceny_i_procent(self):
        self.assertEqual(DOMYSLNA.cena(D("0.12345")), D("0.1235"))
        self.assertEqual(DOMYSLNA.procent(D("33.335")), D("33.34"))

    def test_bardzo_duza_liczba_nie_psuje_quantize(self):
        x = D("123456789012345678901234567890.125")
        self.assertEqual(DOMYSLNA.kwota(x), D("123456789012345678901234567890.13"))

    def test_zly_tryb_vat(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            Konfiguracja(tryb_vat="inny")
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNY_TRYB)


class TestLiczby(unittest.TestCase):
    def test_konwersje(self):
        self.assertEqual(do_decimal(5, "x"), D(5))
        self.assertEqual(do_decimal("12,50", "x"), D("12.50"))
        self.assertEqual(do_decimal(" 0.33 ", "x"), D("0.33"))
        self.assertEqual(do_decimal(D("1.1"), "x"), D("1.1"))

    def test_float_odrzucony(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            do_decimal(0.1, "cena")
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_LICZBA)
        self.assertEqual(cm.exception.pole, "cena")

    def test_bool_none_smieci_nan_inf(self):
        for wej in (True, None, "abc", "", D("NaN"), D("Infinity"), "inf", [1]):
            with self.subTest(wej=wej):
                with self.assertRaises(bledy.BladWalidacji):
                    do_decimal(wej, "x")


class TestStawki(unittest.TestCase):
    def test_poprawne(self):
        tabela = [(23, "23"), ("23", "23"), ("23%", "23"), (D("23"), "23"), (D("23.0"), "23"),
                  (8, "8"), (5, "5"), (0, "0"), ("0", "0"), ("zw", "zw"), ("ZW", "zw"),
                  (" np ", "np"), ("NP", "np")]
        for wej, oczek in tabela:
            with self.subTest(wej=wej):
                self.assertEqual(normalizuj_stawke(wej), oczek)

    def test_nieznane(self):
        for wej in (7, 22, -1, "abc", None, 23.0, True, D("8.5"), "", "zwolniona"):
            with self.subTest(wej=wej):
                with self.assertRaises(bledy.BladWalidacji) as cm:
                    normalizuj_stawke(wej)
                self.assertEqual(cm.exception.kod, bledy.NIEZNANA_STAWKA)

    def test_zw_np_maja_vat_zero(self):
        self.assertEqual(wartosc_stawki("zw"), 0)
        self.assertEqual(wartosc_stawki("np"), 0)
        self.assertEqual(wartosc_stawki("23"), 23)


if __name__ == "__main__":
    unittest.main()
