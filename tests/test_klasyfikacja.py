"""Klasyfikacja przyczyn niespójności (POLGROSZ, NAGLOWEK_*, BRAK_VAT_W_POZYCJACH, ILOSC_X_CENA...)."""
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, oblicz
from amounts_calc.check import ma_problem, sprawdz_dokument, sprawdz_partie
from amounts_calc.klasyfikacja import (jest_polgroszem, przyczyna_ilosc_x_cena, przyczyna_polgrosz,
                                       przyczyny_naglowka)


def poz(ilosc, cena, netto, vat, brutto, stawka=23, **extra):
    d = {"ilosc": ilosc, "cena_netto_jedn": cena, "stawka_vat": stawka, "netto": netto, "vat": vat, "brutto": brutto}
    d.update(extra)
    return d


def dok(netto, vat, brutto, pozycje, **extra):
    d = {"id": "D", "suma_netto": netto, "suma_vat": vat, "suma_brutto": brutto, "pozycje": pozycje}
    d.update(extra)
    return d


def kody(w):
    return {p["kod"] for p in w["przyczyny"]}


def jedna(w, kod):
    return [p for p in w["przyczyny"] if p["kod"] == kod][0]


class TestJednostkowe(unittest.TestCase):
    def test_jest_polgroszem(self):
        tabela = [
            ("1758.28", "1758.285", "0.005", True),      # niezaokrąglone brutto
            ("1758.28", "1758.2850", "0.005", True),
            ("10.00", "10.01", "0.01", False),           # prawdziwy 1 gr przy zaokrąglonych wartościach
            ("10.00", "10.0149", "0.0149", False),       # > 0,01
            ("10.00", "10.0100", "0.01", False),
            ("10.004", "10.01", "0.006", True),
            ("10.00", "10.00", "0", False),
            ("10.00", "10.0001", "0.0001", True),
            ("-1.994", "-2.00", "-0.006", True),
        ]
        for o, j, r, oczek in tabela:
            with self.subTest(o=o, j=j):
                self.assertEqual(jest_polgroszem(D(o), D(j), D(r)), oczek)

    def test_przyczyna_polgrosz_zbiera_indeksy(self):
        p, idx = przyczyna_polgrosz([(D("1"), D("1.005"), D("0.005")), (D("2"), D("2.01"), D("0.01")),
                                     (D("3"), D("3.0031"), D("0.0031"))])
        self.assertEqual(idx, {0, 2})
        self.assertEqual((p["kod"], p["roznica"], p["liczba"]), (bledy.POLGROSZ, D("0.005"), 2))
        self.assertEqual(przyczyna_polgrosz([(D("2"), D("2.01"), D("0.01"))]), (None, set()))

    def test_naglowek_zero(self):
        z = przyczyny_naglowka({"netto": D(0), "vat": D(0), "brutto": D(0)},
                               {"netto": D("10"), "vat": D("2.3"), "brutto": D("12.3")}, [])
        self.assertEqual([p["kod"] for p in z], [bledy.NAGLOWEK_ZERO])
        # nagłówek zero przy zerowych pozycjach to nie przyczyna
        self.assertEqual(przyczyny_naglowka({"netto": D(0), "vat": D(0), "brutto": D(0)},
                                            {"netto": D(0), "vat": D(0), "brutto": D(0)}, []), [])

    def test_naglowek_nizszy_wyzszy_i_progi(self):
        pozycje = {"netto": D("100"), "vat": D("23"), "brutto": D("123")}
        wiersze = [{"indeks": 0, "id": "a", "zestaw": False, "netto": D("90"), "vat": D("20.7"), "brutto": D("110.7")},
                   {"indeks": 1, "id": "b", "zestaw": False, "netto": D("10"), "vat": D("2.3"), "brutto": D("12.3")}]
        nizszy = przyczyny_naglowka({"netto": D("90"), "vat": D("20.7"), "brutto": D("110.7")}, pozycje, wiersze)
        self.assertEqual(nizszy[0]["kod"], bledy.NAGLOWEK_NIZSZY)
        self.assertEqual(nizszy[0]["roznica"], D("-10"))
        self.assertEqual(nizszy[0]["pole"], "suma_netto")
        self.assertEqual([m["indeks"] for m in nizszy[0]["mozliwe_pozycje"]], [1])   # pozycja o wartości 10
        wyzszy = przyczyny_naglowka({"netto": D("110"), "vat": D("23"), "brutto": D("123")}, pozycje, wiersze)
        self.assertEqual((wyzszy[0]["kod"], wyzszy[0]["roznica"]), (bledy.NAGLOWEK_WYZSZY, D("10")))
        # <= 0,01 to nie NAGLOWEK_*
        self.assertEqual(przyczyny_naglowka({"netto": D("100.01"), "vat": D("23"), "brutto": D("123")}, pozycje, wiersze), [])
        self.assertEqual(len(przyczyny_naglowka({"netto": D("100.02"), "vat": D("23"), "brutto": D("123")},
                                                pozycje, wiersze)), 1)

    def test_naglowek_gdy_brak_vat_w_pozycjach(self):
        r = przyczyny_naglowka({"netto": D("50"), "vat": D("11.5"), "brutto": D("61.5")},
                               {"netto": D("100"), "vat": None, "brutto": None}, [])
        self.assertEqual((r[0]["kod"], r[0]["pole"], r[0]["roznica"]), (bledy.NAGLOWEK_NIZSZY, "suma_netto", D("-50")))

    def test_ilosc_x_cena(self):
        p = przyczyna_ilosc_x_cena([(0, "a", D("10.00"), D("10.01")), (1, "b", D("5.00"), D("5.50")),
                                    (2, "c", D("1.00"), D("1.00"))], "netto")
        self.assertEqual((p["kod"], p["liczba"], p["roznica"]), (bledy.ILOSC_X_CENA, 1, D("-0.50")))
        self.assertEqual(p["pozycje"][0]["id"], "b")
        self.assertIsNone(przyczyna_ilosc_x_cena([(0, "a", D("10.00"), D("10.01"))], "netto"))


class TestPolgrosz(unittest.TestCase):
    def doc(self, brutto):
        return dok("1500.00", "345.00", brutto,
                   [poz(1, "1500", "1500.00", "345.00", "1845.00", 23)])

    def test_brutto_z_trzema_miejscami_to_drobiazg(self):
        w = sprawdz_dokument(self.doc("1845.005"))
        self.assertEqual(w["status"], "drobiazg")
        self.assertEqual(kody(w), {bledy.POLGROSZ})
        self.assertEqual(jedna(w, bledy.POLGROSZ)["roznica"], D("0.005"))
        self.assertTrue(w["niespojnosci"])
        self.assertTrue(all(n.get("drobiazg") for n in w["niespojnosci"]))
        self.assertTrue(ma_problem(w))      # nadal w raporcie, ale jako drobiazg

    def test_ten_sam_grosz_przy_zaokraglonych_to_niespojnosc(self):
        w = sprawdz_dokument(self.doc("1845.01"))
        self.assertEqual(w["status"], "niespojny")
        self.assertNotIn(bledy.POLGROSZ, kody(w))
        self.assertFalse(any(n.get("drobiazg") for n in w["niespojnosci"]))

    def test_drobiazg_obok_prawdziwego_bledu_to_niespojny(self):
        d = self.doc("1845.005")
        d["suma_netto"] = "1499.00"       # ponad grosz
        w = sprawdz_dokument(d)
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.POLGROSZ, kody(w))

    def test_polgrosz_ze_zgodnosci_z_biblioteka(self):
        # zapisane sumy zgodne co do groszy z pozycjami, ale suma brutto niezaokrąglona
        w = sprawdz_dokument(dok("10.00", "2.30", "12.304", [poz(1, "10", "10.00", "2.30", "12.30")]))
        self.assertEqual(w["tryb_pasujacy"], "zaden")
        self.assertEqual(w["status"], "drobiazg")
        self.assertNotIn(bledy.NIEZGODNY_Z_BIBLIOTEKA, kody(w))

    def test_zaden_tryb_bez_wyjasnienia_to_niezgodny(self):
        d = dok("10.00", "2.00", "12.00", [poz(1, "10", "10.00", "2.00", "12.00")])
        w = sprawdz_dokument(d)
        self.assertEqual(w["status"], "niespojny")
        # tu VAT_STAWKI_ROZNY_OD_SUMY już tłumaczy problem, więc bez dodatkowego kodu
        self.assertNotIn(bledy.NIEZGODNY_Z_BIBLIOTEKA, kody(w))

    def test_niezgodny_z_biblioteka_gdy_dokument_wewnetrznie_spojny(self):
        # wewnętrznie spójny (sumy = pozycje), ale pozycje nie wynikają z ilość x cena -> ILOSC_X_CENA też
        d = dok("10.00", "2.30", "12.30", [poz(1, "10", "10.00", "2.30", "12.30", rabat_proc=10)])
        w = sprawdz_dokument(d)
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.ILOSC_X_CENA, kody(w))


class TestNaglowek(unittest.TestCase):
    POZ = [poz(1, "100", "100.00", "23.00", "123.00"), poz(2, "25", "50.00", "11.50", "61.50"),
           poz(1, "10", "10.00", "2.30", "12.30")]

    def test_naglowek_zero(self):
        w = sprawdz_dokument(dok("0.00", "0.00", "0.00", self.POZ))
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(kody(w) & {bledy.NAGLOWEK_ZERO, bledy.NAGLOWEK_NIZSZY}, {bledy.NAGLOWEK_ZERO})
        self.assertEqual(jedna(w, bledy.NAGLOWEK_ZERO)["suma_pozycji"]["netto"], D("160.00"))

    def test_naglowek_nizszy_z_podpowiedzia_pozycji(self):
        # nagłówek pomija ostatnią pozycję (netto 10.00)
        w = sprawdz_dokument(dok("150.00", "34.50", "184.50", self.POZ))
        p = jedna(w, bledy.NAGLOWEK_NIZSZY)
        self.assertEqual((p["roznica"], p["pole"]), (D("-10.00"), "suma_netto"))
        self.assertEqual([(m["indeks"], m["wartosc"]) for m in p["mozliwe_pozycje"]], [(2, D("10.00"))])
        self.assertEqual(p["zrodlo_pozycji"], "zapisane")
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(w["max_roznica"], D("12.30"))

    def test_naglowek_wyzszy(self):
        w = sprawdz_dokument(dok("175.00", "40.25", "215.25", self.POZ))
        p = jedna(w, bledy.NAGLOWEK_WYZSZY)
        self.assertEqual(p["roznica"], D("15.00"))
        self.assertEqual(p["mozliwe_pozycje"], [])      # żadna pozycja nie ma wartości 15.00

    def test_roznica_dokladnie_grosz_to_nie_naglowek(self):
        w = sprawdz_dokument(dok("160.01", "36.80", "196.81", self.POZ))
        self.assertFalse(kody(w) & {bledy.NAGLOWEK_NIZSZY, bledy.NAGLOWEK_WYZSZY, bledy.NAGLOWEK_ZERO})
        self.assertEqual(w["status"], "niespojny")         # zwykły 1 gr przy zaokrąglonych kwotach

    def test_naglowek_zero_w_dokumencie_bez_kwot_pozycji(self):
        d = dok("0", "0", "0", [{"ilosc": 2, "cena_netto_jedn": "10", "stawka_vat": 23}])
        w = sprawdz_dokument(d)
        self.assertEqual(w["dane"], "brak_kwot")
        self.assertEqual(jedna(w, bledy.NAGLOWEK_ZERO)["zrodlo_pozycji"], "obliczone")
        self.assertEqual(w["status"], "niespojny")

    def test_pusty_dokument_z_niezerowym_naglowkiem(self):
        w = sprawdz_dokument(dok("5.00", "0.00", "5.00", []))
        self.assertIn(bledy.NAGLOWEK_WYZSZY, kody(w))


class TestBrakVat(unittest.TestCase):
    def pozycje(self):
        return [{"ilosc": 1, "cena_netto_jedn": "100", "stawka_vat": 23, "netto": "100.00"},
                {"ilosc": 2, "cena_netto_jedn": "25", "stawka_vat": 23, "netto": "50.00"}]

    def test_brak_vat_nie_jest_bledem(self):
        w = sprawdz_dokument(dok("150.00", "34.50", "184.50", self.pozycje()))
        self.assertIsNone(w["blad"])
        self.assertEqual(w["dane"], "brak_vat")
        self.assertEqual(w["status"], "niepelny")
        self.assertEqual(kody(w), {bledy.BRAK_VAT_W_POZYCJACH})
        self.assertEqual(w["niespojnosci"], [])
        self.assertEqual(w["tryb_pasujacy"], "oba")
        self.assertTrue(ma_problem(w))

    def test_netto_pozycji_vs_naglowek(self):
        w = sprawdz_dokument(dok("140.00", "32.20", "172.20", self.pozycje()))
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(kody(w), {bledy.BRAK_VAT_W_POZYCJACH, bledy.NAGLOWEK_NIZSZY})
        n = [x for x in w["niespojnosci"] if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU]
        self.assertEqual((n[0]["pole"], n[0]["oczekiwano"], n[0]["jest"]), ("suma_netto", D("150.00"), D("140.00")))

    def test_brutto_pozycji_gdy_jest(self):
        poz_ = self.pozycje()
        poz_[0]["brutto"], poz_[1]["brutto"] = "123.00", "61.50"
        w = sprawdz_dokument(dok("150.00", "34.50", "184.00", poz_))
        self.assertEqual(w["dane"], "brak_vat")
        self.assertIn(bledy.NAGLOWEK_NIZSZY, kody(w))
        self.assertEqual(jedna(w, bledy.NAGLOWEK_NIZSZY)["pole"], "suma_brutto")

    def test_polgrosz_w_niepelnych(self):
        w = sprawdz_dokument(dok("150.004", "34.50", "184.50", self.pozycje()))
        self.assertEqual(w["status"], "niepelny")
        self.assertEqual(kody(w), {bledy.BRAK_VAT_W_POZYCJACH, bledy.POLGROSZ})

    def test_ilosc_x_cena_dziala_na_niepelnych(self):
        poz_ = self.pozycje()
        poz_[1]["netto"] = "49.00"          # 2 x 25 = 50
        w = sprawdz_dokument(dok("149.00", "34.27", "183.27", poz_))
        self.assertIn(bledy.ILOSC_X_CENA, kody(w))
        self.assertEqual(w["status"], "niespojny")

    def test_niepelne_to_nie_blad_ale_czesciowe_braki_tak(self):
        poz_ = self.pozycje()
        del poz_[1]["netto"]                # druga pozycja bez żadnej kwoty, pierwsza z netto
        w = sprawdz_dokument(dok("150.00", "34.50", "184.50", poz_))
        self.assertEqual(w["status"], "blad")
        self.assertEqual(w["blad"]["kod"], bledy.BRAK_POLA)

    def test_vat_null_jak_brak(self):
        poz_ = self.pozycje()
        for p in poz_:
            p["vat"] = None
        self.assertEqual(sprawdz_dokument(dok("150.00", "34.50", "184.50", poz_))["status"], "niepelny")

    def test_partia_liczy_niepelne(self):
        wyniki, p = sprawdz_partie([dok("150.00", "34.50", "184.50", self.pozycje())])
        self.assertEqual(p["status"]["niepelny"], 1)
        self.assertEqual(p["kody"], {bledy.BRAK_VAT_W_POZYCJACH: 1})
        self.assertEqual(p["spojne"], 0)


class TestIloscXCena(unittest.TestCase):
    def test_wartosc_pozycji_nie_zgadza_sie_z_ilosc_razy_cena(self):
        d = dok("120.00", "27.60", "147.60", [poz(3, "50", "120.00", "27.60", "147.60")])   # 3 x 50 = 150
        w = sprawdz_dokument(d)
        p = jedna(w, bledy.ILOSC_X_CENA)
        self.assertEqual(p["roznica"], D("-30.00"))
        self.assertEqual(p["pozycje"][0]["oczekiwane"], D("150.00"))
        self.assertEqual(p["pozycje"][0]["zapisane"], D("120.00"))
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(w["niespojnosci"], [])      # wewnętrznie spójny - tylko ILOSC_X_CENA go zdradza

    def test_prog_jednego_grosza(self):
        ok = sprawdz_dokument(dok("150.01", "34.50", "184.51", [poz(3, "50", "150.01", "34.50", "184.51")]))
        self.assertNotIn(bledy.ILOSC_X_CENA, kody(ok))
        zle = sprawdz_dokument(dok("150.02", "34.50", "184.52", [poz(3, "50", "150.02", "34.50", "184.52")]))
        self.assertIn(bledy.ILOSC_X_CENA, kody(zle))

    def test_rabat_pozycji_i_dokumentu_sa_uwzglednione(self):
        w = oblicz([{"ilosc": 3, "cena_netto_jedn": "50", "rabat_proc": 10, "stawka_vat": 23}], rabat_dokumentu_proc=5)
        d = dok(w.suma_netto, w.suma_vat, w.suma_brutto,
                [poz(3, "50", w.pozycje[0].netto, w.pozycje[0].vat, w.pozycje[0].brutto, rabat_proc=10)],
                rabat_dokumentu_proc=5)
        self.assertEqual(sprawdz_dokument(d)["przyczyny"], [])

    def test_tryb_brutto_porownuje_brutto(self):
        d = {"id": 1, "tryb": "brutto", "suma_netto": "100.00", "suma_vat": "23.00", "suma_brutto": "123.00",
             "pozycje": [{"ilosc": 2, "cena_brutto_jedn": "61.50", "stawka_vat": 23, "netto": "100.00",
                          "vat": "23.00", "brutto": "123.00"}]}
        self.assertEqual(sprawdz_dokument(d)["status"], "spojny")
        d["pozycje"][0]["ilosc"] = 3
        self.assertIn(bledy.ILOSC_X_CENA, kody(sprawdz_dokument(d)))

    def test_zestaw_nie_jest_sprawdzany_ilosc_x_cena(self):
        from tests.test_zestawy import dokument_zestaw
        d = dokument_zestaw()
        d["pozycje"][0]["ilosc"] = 99
        d["pozycje"][0]["cena_netto_jedn"] = "1000"      # ignorowane - nadrzędna liczy się z dzieci
        self.assertEqual(sprawdz_dokument(d)["status"], "spojny")


class TestZestawyKlasyfikacja(unittest.TestCase):
    def test_zestaw_policzony_podwojnie(self):
        from tests.test_zestawy import dokument_zestaw
        d = dokument_zestaw(suma_netto="297.00", suma_vat="62.10", suma_brutto="359.10")   # 162 + 135
        w = sprawdz_dokument(d)
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.ZESTAW_LICZONY_PODWOJNIE, kody(w))
        p = jedna(w, bledy.NAGLOWEK_WYZSZY)
        self.assertEqual(p["roznica"], D("135.00"))
        self.assertEqual([(m["indeks"], m["zestaw"]) for m in p["mozliwe_pozycje"]], [(0, True)])
        self.assertEqual(jedna(w, bledy.ZESTAW_LICZONY_PODWOJNIE)["pozycje"], [0])

    def test_poprawny_zestaw_bez_przyczyn(self):
        from tests.test_zestawy import dokument_zestaw
        w = sprawdz_dokument(dokument_zestaw())
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))


if __name__ == "__main__":
    unittest.main()
