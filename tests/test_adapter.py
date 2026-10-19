import os
import tempfile
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, sprawdz_spojnosc
from amounts_calc.adapter import (scal_mapowanie, wczytaj_json, wczytaj_plik_json, z_wiersza)


def bledny(tc, *args, **kw):
    with tc.assertRaises(bledy.BladWalidacji) as cm:
        z_wiersza(*args, **kw)
    return cm.exception


class TestZWiersza(unittest.TestCase):
    def test_nazwy_domyslne(self):
        d = z_wiersza({"id": "A1", "suma_netto": 10, "suma_vat": "2,30", "suma_brutto": "12,30",
                       "pozycje": [{"ilosc": 1, "stawka_vat": 23, "netto": 10, "vat": "2,30", "brutto": "12,30"}]})
        self.assertEqual(d["id"], "A1")
        self.assertEqual(d["pozycje"][0]["netto"], 10)
        self.assertEqual(sprawdz_spojnosc(d, tryb_vat="per_stawka"), [])

    def test_alternatywne_nazwy_domyslne(self):
        d = z_wiersza({"numer": "FV/1", "netto": 10, "kwota_vat": 2, "brutto": 12,
                       "linie": [{"qty": 2, "cena_netto": 5, "rabat": 0, "stawka": 23}]})
        self.assertEqual((d["id"], d["suma_vat"]), ("FV/1", 2))
        self.assertEqual(d["pozycje"][0], {"ilosc": 2, "cena_netto_jedn": 5, "rabat_proc": 0, "stawka_vat": 23})

    def test_wlasne_mapowanie(self):
        m = {"suma_netto": "kwota_netto", "suma_vat": ["podatek"], "suma_brutto": "do_zaplaty",
             "id": "klucz", "pozycje": "wiersze",
             "pozycja": {"ilosc": "liczba_sztuk_x", "stawka_vat": "vat_stawka_x"}}
        d = z_wiersza({"klucz": 7, "kwota_netto": "1", "podatek": "0,23", "do_zaplaty": "1,23",
                       "wiersze": [{"liczba_sztuk_x": 3, "vat_stawka_x": 23}]}, m)
        self.assertEqual(d["id"], 7)
        self.assertEqual(d["suma_vat"], "0,23")
        self.assertEqual(d["pozycje"], [{"ilosc": 3, "stawka_vat": 23}])

    def test_nazwy_uzytkownika_maja_pierwszenstwo(self):
        d = z_wiersza({"netto": 1, "kwota_netto": 2, "suma_vat": 0, "suma_brutto": 0, "pozycje": []},
                      {"suma_netto": "kwota_netto"})
        self.assertEqual(d["suma_netto"], 2)

    def test_sciezka_z_kropka(self):
        d = z_wiersza({"naglowek": {"netto": 5, "vat": 1, "brutto": 6}, "pozycje": []},
                      {"suma_netto": "naglowek.netto", "suma_vat": "naglowek.vat", "suma_brutto": "naglowek.brutto"})
        self.assertEqual((d["suma_netto"], d["suma_vat"], d["suma_brutto"]), (5, 1, 6))

    def test_pozycje_osobno(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1},
                      pozycje=[{"ilosc": 1, "stawka_vat": 0}])
        self.assertEqual(len(d["pozycje"]), 1)

    def test_none_traktowane_jak_brak(self):
        self.assertEqual(bledny(self, {"suma_netto": None, "netto": None, "suma_vat": 1, "suma_brutto": 1,
                                       "pozycje": []}).kod, bledy.BRAK_POLA)

    def test_brak_sumy_i_pozycji(self):
        e = bledny(self, {"suma_netto": 1, "suma_vat": 1, "pozycje": []})
        self.assertEqual((e.kod, e.pole), (bledy.BRAK_POLA, "suma_brutto"))
        e = bledny(self, {"suma_netto": 1, "suma_vat": 1, "suma_brutto": 2})
        self.assertEqual((e.kod, e.pole), (bledy.BRAK_POLA, "pozycje"))

    def test_zle_typy(self):
        self.assertEqual(bledny(self, [1, 2]).kod, bledy.NIEPOPRAWNA_STRUKTURA)
        e = bledny(self, {"suma_netto": 1, "suma_vat": 1, "suma_brutto": 2, "pozycje": "abc"})
        self.assertEqual(e.kod, bledy.NIEPOPRAWNA_STRUKTURA)
        e = bledny(self, {"suma_netto": 1, "suma_vat": 1, "suma_brutto": 2, "pozycje": [1]})
        self.assertEqual(e.kod, bledy.NIEPOPRAWNA_STRUKTURA)

    def test_zle_mapowanie(self):
        for m in ({"nieznany": "x"}, {"suma_netto": 5}, {"pozycja": {"nieznane": "x"}}, {"pozycja": "x"}, [1]):
            with self.subTest(m=m):
                with self.assertRaises(bledy.BladWalidacji) as cm:
                    scal_mapowanie(m)
                self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_STRUKTURA)

    def test_podsumowanie_mapowane(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1, "pozycje": [],
                       "vat_wg_stawek": [{"stawka": 23, "wartosc_netto": 1, "kwota_vat": 0, "wartosc_brutto": 1}]})
        self.assertEqual(d["podsumowanie"], [{"stawka_vat": 23, "netto": 1, "vat": 0, "brutto": 1}])

    def test_nie_modyfikuje_wejscia_ani_domyslnego(self):
        zrodlo = {"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1, "pozycje": []}
        z_wiersza(zrodlo, {"suma_netto": "x"})
        z_wiersza(zrodlo)
        self.assertEqual(scal_mapowanie()["suma_netto"][0], "suma_netto")


class TestWczytajJson(unittest.TestCase):
    def test_floaty_to_decimal_bez_utraty_precyzji(self):
        w = wczytaj_json('{"a": 0.1000000000000000055511151231257827, "b": 12, "c": "1,5", "d": 1e2}')
        self.assertEqual(w["a"], D("0.1000000000000000055511151231257827"))
        self.assertIsInstance(w["a"], D)
        self.assertEqual(w["b"], 12)
        self.assertIsInstance(w["b"], int)
        self.assertEqual(w["c"], "1,5")
        self.assertEqual(w["d"], D("1E+2"))

    def test_brak_floatow_w_zagniezdzonych(self):
        def chodz(x):
            if isinstance(x, dict):
                for v in x.values():
                    chodz(v)
            elif isinstance(x, list):
                for v in x:
                    chodz(v)
            else:
                self.assertNotIsInstance(x, float)
        chodz(wczytaj_json('[{"x": [0.33, {"y": 1.10}], "z": 2.5}]'))

    def test_nan_i_infinity_odrzucone(self):
        for tekst in ("[NaN]", "[Infinity]", "[-Infinity]"):
            with self.assertRaises(ValueError):
                wczytaj_json(tekst)

    def test_plik_z_bom_i_polskie_znaki(self):
        with tempfile.TemporaryDirectory() as tmp:
            sciezka = os.path.join(tmp, "w.json")
            with open(sciezka, "wb") as f:
                f.write(b"\xef\xbb\xbf" + '{"id": "zażółć", "k": 0.33}'.encode("utf-8"))
            w = wczytaj_plik_json(sciezka)
            self.assertEqual(w, {"id": "zażółć", "k": D("0.33")})


if __name__ == "__main__":
    unittest.main()
