import copy
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, oblicz, porownaj, sprawdz_spojnosc, Pozycja, dokument_z_slownika
from amounts_calc.config import TRYB_BRUTTO, VAT_PER_POZYCJA, VAT_PER_STAWKA


def dok_slownik(**nadpisz):
    d = oblicz([Pozycja(ilosc=1, cena_netto_jedn="0.33")] * 3 + [Pozycja(ilosc=2, cena_netto_jedn="10", stawka_vat=8)],
               tryb_vat=VAT_PER_STAWKA).do_slownika()
    d.update(nadpisz)
    return d


def kody(wyniki):
    return sorted({w["kod"] for w in wyniki})


class TestSprawdzSpojnosc(unittest.TestCase):
    def test_wynik_oblicz_jest_spojny(self):
        for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
            for tryb in ("netto", TRYB_BRUTTO):
                with self.subTest(tv=tv, tryb=tryb):
                    pole = "cena_netto_jedn" if tryb == "netto" else "cena_brutto_jedn"
                    d = oblicz([{"ilosc": 3, pole: "0.33", "stawka_vat": 23},
                                {"ilosc": 1, pole: "9.99", "stawka_vat": 8}], tryb=tryb, tryb_vat=tv)
                    self.assertEqual(sprawdz_spojnosc(d), [])

    def test_slownik_spojny(self):
        self.assertEqual(sprawdz_spojnosc(dok_slownik()), [])

    def test_suma_pozycji_rozna_od_dokumentu(self):
        w = sprawdz_spojnosc(dok_slownik(suma_netto="100.00"))
        k = [x for x in w if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU]
        self.assertEqual(len(k), 1)
        self.assertEqual(k[0]["pole"], "suma_netto")
        self.assertEqual(k[0]["oczekiwano"], D("20.99"))
        self.assertEqual(k[0]["roznica"], D("100.00") - D("20.99"))

    def test_netto_plus_vat_rozne_od_brutto_dokument(self):
        d = dok_slownik()
        d["suma_brutto"] = str(D(d["suma_brutto"]) + D("0.01"))
        w = sprawdz_spojnosc(d)
        self.assertIn(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, kody(w))
        self.assertTrue(any(x["zakres"] == "dokument" and x["roznica"] == D("0.01") for x in w))

    def test_netto_plus_vat_rozne_od_brutto_pozycja(self):
        d = dok_slownik()
        d["pozycje"][0]["brutto"] = "9.99"
        w = sprawdz_spojnosc(d)
        self.assertTrue(any(x["kod"] == bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO and x["zakres"] == "pozycja:0"
                            for x in w))

    def test_vat_stawki_rozny_od_sumy(self):
        d = dok_slownik()
        # VAT stawki 23 policzony "po pozycjach": 3 x 0.08 = 0.24 zamiast 0.23 z sumy
        d["podsumowanie"][0]["vat"] = "0.24"
        d["podsumowanie"][0]["brutto"] = "1.23"
        w = sprawdz_spojnosc(d)
        k = [x for x in w if x["kod"] == bledy.VAT_STAWKI_ROZNY_OD_SUMY]
        self.assertEqual(len(k), 1)
        self.assertEqual((k[0]["zakres"], k[0]["oczekiwano"], k[0]["jest"]), ("stawka:23", D("0.23"), D("0.24")))

    def test_vat_per_pozycja_nie_jest_bledem_gdy_tryb_per_pozycja(self):
        d = oblicz([Pozycja(ilosc=1, cena_netto_jedn="0.33")] * 3, tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual(sprawdz_spojnosc(d), [])
        w = sprawdz_spojnosc(d, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual(kody(w), [bledy.VAT_STAWKI_ROZNY_OD_SUMY])

    def test_vat_stawki_w_trybie_brutto(self):
        d = oblicz([Pozycja(ilosc=1, cena_brutto_jedn="0.35")] * 3, tryb=TRYB_BRUTTO, tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual(kody(sprawdz_spojnosc(d, tryb_vat=VAT_PER_STAWKA)), [bledy.VAT_STAWKI_ROZNY_OD_SUMY])

    def test_podsumowanie_stawki_rozne_od_pozycji(self):
        d = dok_slownik()
        d["podsumowanie"][1]["netto"] = "21.00"
        w = sprawdz_spojnosc(d)
        self.assertIn(bledy.PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI, kody(w))
        self.assertIn(bledy.SUMA_STAWEK_ROZNA_OD_DOKUMENTU, kody(w))

    def test_stawka_w_pozycjach_bez_wiersza_podsumowania(self):
        d = dok_slownik()
        d["podsumowanie"] = [s for s in d["podsumowanie"] if s["stawka_vat"] != "8"]
        w = sprawdz_spojnosc(d)
        self.assertTrue(any(x["kod"] == bledy.PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI and x["zakres"] == "stawka:8"
                            and x["jest"] == 0 for x in w))

    def test_dokument_bez_podsumowania_liczy_je_z_pozycji(self):
        d = dok_slownik()
        del d["podsumowanie"]
        self.assertEqual(sprawdz_spojnosc(d), [])

    def test_wpis_ma_stale_klucze(self):
        w = sprawdz_spojnosc(dok_slownik(suma_vat="9.99"))
        self.assertTrue(w)
        for x in w:
            self.assertEqual(set(x), {"kod", "zakres", "pole", "oczekiwano", "jest", "roznica", "opis"})

    def test_kody_to_stale(self):
        for nazwa in ("SUMA_POZYCJI_ROZNA_OD_DOKUMENTU", "NETTO_PLUS_VAT_ROZNE_OD_BRUTTO",
                      "VAT_STAWKI_ROZNY_OD_SUMY"):
            self.assertEqual(getattr(bledy, nazwa), nazwa)

    def test_brakujace_pole_dokumentu(self):
        d = dok_slownik()
        del d["suma_vat"]
        with self.assertRaises(bledy.BladWalidacji) as cm:
            sprawdz_spojnosc(d)
        self.assertEqual(cm.exception.kod, bledy.BRAK_POLA)

    def test_nie_modyfikuje_wejscia(self):
        d = dok_slownik(suma_netto="1.00")
        kopia = copy.deepcopy(d)
        sprawdz_spojnosc(d)
        self.assertEqual(d, kopia)

    def test_dokument_z_slownika_float_odrzucony(self):
        with self.assertRaises(bledy.BladWalidacji):
            sprawdz_spojnosc(dok_slownik(suma_netto=1.5))


class TestPorownaj(unittest.TestCase):
    def test_identyczne(self):
        d = oblicz([Pozycja(ilosc=1, cena_netto_jedn="1")])
        self.assertEqual(porownaj(d, d), [])

    def test_tryby_vat_roznia_sie_o_grosz(self):
        poz = [Pozycja(ilosc=1, cena_netto_jedn="0.33")] * 3
        a = oblicz(poz, tryb_vat=VAT_PER_POZYCJA)
        b = oblicz(poz, tryb_vat=VAT_PER_STAWKA)
        r = {x["pole"]: x for x in porownaj(a, b)}
        self.assertEqual(r["suma_vat"], {"pole": "suma_vat", "a": D("0.24"), "b": D("0.23"), "roznica": D("-0.01")})
        self.assertEqual(r["suma_brutto"]["roznica"], D("-0.01"))
        self.assertNotIn("suma_netto", r)
        self.assertIn("stawka:23.vat", r)
        self.assertIn("pozycje[0].vat", r)

    def test_rozna_liczba_pozycji(self):
        a = oblicz([Pozycja(ilosc=1, cena_netto_jedn="1")])
        b = oblicz([Pozycja(ilosc=1, cena_netto_jedn="1")] * 2)
        r = {x["pole"]: x for x in porownaj(a, b)}
        self.assertEqual(r["liczba_pozycji"]["roznica"], 1)  # int, nie Decimal
        self.assertEqual(r["suma_netto"]["roznica"], D("1.00"))

    def test_brak_stawki_po_jednej_stronie(self):
        a = oblicz([Pozycja(ilosc=1, cena_netto_jedn="1", stawka_vat=23)])
        b = oblicz([Pozycja(ilosc=1, cena_netto_jedn="1", stawka_vat=8)])
        r = {x["pole"]: x for x in porownaj(a, b)}
        self.assertIsNone(r["stawka:23.netto"]["b"])
        self.assertEqual(r["stawka:23.netto"]["roznica"], D("-1.00"))
        self.assertIsNone(r["stawka:8.netto"]["a"])
        self.assertEqual(r["stawka:8.netto"]["roznica"], D("1.00"))
        self.assertIn("pozycje[0].stawka_vat", r)

    def test_waluta(self):
        a = oblicz([], waluta="PLN")
        b = oblicz([], waluta="EUR")
        r = porownaj(a, b)
        self.assertEqual(r, [{"pole": "waluta", "a": "PLN", "b": "EUR", "roznica": None}])

    def test_slownik_vs_wynik(self):
        d = oblicz([Pozycja(ilosc=2, cena_netto_jedn="5")])
        self.assertEqual(porownaj(d, d.do_slownika()), [])

    def test_roundtrip_slownika(self):
        d = oblicz([Pozycja(ilosc=2, cena_netto_jedn="5.55", stawka_vat=8)] * 3)
        d2 = dokument_z_slownika(d.do_slownika())
        self.assertEqual(d2.suma_vat, d.suma_vat)
        self.assertEqual([p.netto for p in d2.pozycje], [p.netto for p in d.pozycje])

    def test_roznice_to_b_minus_a(self):
        a = dok_slownik()
        b = dok_slownik(suma_netto="21.99")
        r = [x for x in porownaj(a, b) if x["pole"] == "suma_netto"][0]
        self.assertEqual(r["roznica"], D("21.99") - D("20.99"))


if __name__ == "__main__":
    unittest.main()
