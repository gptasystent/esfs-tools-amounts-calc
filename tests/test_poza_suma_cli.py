"""Runda 8: poza_suma w JSON/CSV z CLI oraz wykrywanie opcji/alternatyw w nagłówku mimo błędu narzutu."""
import csv
import json
import os
import tempfile
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.check import KOLUMNY_CSV, ma_problem, main, sprawdz_dokument, sprawdz_partie, wynik_json
from tests.test_opcje_jawne import BAZA, alt, dok, kody_przyczyn, kwoty, opcja, poz


def przyczyna(w, kod):
    return [c for c in w["przyczyny"] if c["kod"] == kod][0]


class TestPozaSumaWRaporcie(unittest.TestCase):
    def test_dokument_z_niewybrana_opcja_trafia_do_raportu_mimo_spojnosci(self):
        w = sprawdz_dokument(dok([BAZA, opcja("O1", "50.00")], "100.00"))
        self.assertEqual(w["status"], "spojny")
        self.assertTrue(ma_problem(w))
        ps = w["poza_suma"]
        self.assertEqual((ps["netto"], ps["vat"], ps["brutto"]), (D("50.00"), D("11.50"), D("61.50")))
        self.assertEqual([(p["id"], p["netto"]) for p in ps["pozycje"]], [("O1", D("50.00"))])

    def test_wybrana_opcja_nie_jest_poza_suma(self):
        w = sprawdz_dokument(dok([BAZA, opcja("O1", "50.00", True)], "150.00"))
        self.assertIsNone(w["poza_suma"])
        self.assertFalse(ma_problem(w))

    def test_zwykly_dokument_nie_ma_poza_suma(self):
        w = sprawdz_dokument(dok([BAZA], "100.00"))
        self.assertIsNone(w["poza_suma"])
        self.assertFalse(ma_problem(w))

    def test_niewybrane_alternatywy_sa_wymienione_osobno(self):
        w = sprawdz_dokument(dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00")], "300.00"))
        ps = w["poza_suma"]
        self.assertEqual(ps["netto"], 0)
        self.assertEqual([(a["id"], a["grupa"], a["netto"]) for a in ps["alternatywy_niewybrane"]],
                         [("A2", "kolor", D("300.00"))])
        self.assertTrue(ma_problem(w))

    def test_tryb_awaryjny_niewybrana_alternatywa(self):
        d = dok([BAZA, poz("O1", "40.00", alternatywa=True), poz("O2", "60.00", alternatywa=True)], "160.00")
        w = sprawdz_dokument(d)
        self.assertEqual([a["id"] for a in w["poza_suma"]["alternatywy_niewybrane"]], ["O1"])

    def test_dokument_bez_vat_w_pozycjach_ma_vat_none(self):
        def bez(p):
            return {k: v for k, v in p.items() if k not in ("vat", "brutto")}
        w = sprawdz_dokument(dok([bez(BAZA), bez(opcja("O1", "50.00"))], "100.00"))
        self.assertEqual((w["poza_suma"]["netto"], w["poza_suma"]["vat"]), (D("50.00"), None))

    def test_json_i_csv(self):
        dokumenty = [dok([BAZA, opcja("O1", "50.00")], "100.00"), dict(dok([BAZA], "100.00"), id="OF/2")]
        with tempfile.TemporaryDirectory() as t:
            wejscie, jsn, plik_csv = (os.path.join(t, n) for n in ("d.json", "w.json", "w.csv"))
            with open(wejscie, "w", encoding="utf-8") as f:
                json.dump(dokumenty, f)
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([wejscie, "--json", jsn, "--csv", plik_csv]), 0)
            with open(jsn, encoding="utf-8") as f:
                raport = json.load(f)
            self.assertEqual([r["id"] for r in raport], ["OF/1"])
            self.assertEqual(raport[0]["poza_suma"]["netto"], "50.00")
            self.assertEqual(raport[0]["poza_suma"]["pozycje"][0]["brutto"], "61.50")
            with open(plik_csv, encoding="utf-8-sig", newline="") as f:
                wiersze = list(csv.reader(f, delimiter=";"))
            self.assertEqual(len(wiersze), 2)
            rekord = dict(zip(KOLUMNY_CSV, wiersze[1]))
            self.assertEqual((rekord["poza_suma_netto"], rekord["poza_suma_vat"], rekord["poza_suma_brutto"]),
                             ("50,00", "11,50", "61,50"))
            self.assertEqual(KOLUMNY_CSV[-1], "podpowiedz")

    def test_wynik_json_ma_klucz_poza_suma_none_dla_zwyklego_dokumentu(self):
        self.assertIsNone(wynik_json(sprawdz_dokument(dok([BAZA], "100.00")))["poza_suma"])

    def test_wlasnosc_podsumowania_partii_liczy_dokumenty_z_opcjami_w_raporcie(self):
        _, p = sprawdz_partie([dok([BAZA, opcja("O1", "50.00")], "100.00"), dok([BAZA], "100.00")])
        self.assertEqual((p["z_problemem"], p["spojne"]), (1, 2))


def opcja_z_narzutem(id_, zakup, narzut, zapisane_netto, **extra):
    """Opcja z ceną zakupu i narzutem; zapisane netto celowo różni się od zakup x (1 + narzut)."""
    return poz(id_, zapisane_netto, cena_zakupu_jedn=zakup, narzut_proc=narzut, tryb_opcji="opcja", wybrana=False,
               **extra)


class TestBladNarzutuWOpcjach(unittest.TestCase):
    """Nagłówek = baza + opcja policzona z narzutem 25% (50,00), a zapisane netto opcji to 48,00."""

    def dokument(self, naglowek="150.00"):
        return dok([BAZA, opcja_z_narzutem("O1", "40.00", "25", "48.00")], naglowek)

    def test_opcja_w_sumie_wykryta_po_zapisanym_netto_mimo_bledu_narzutu(self):
        w = sprawdz_dokument(self.dokument())
        self.assertEqual(w["status"], "niespojny")
        c = przyczyna(w, bledy.OPCJA_W_SUMIE)
        self.assertEqual(c["dopasowanie"], "najblizsze")
        self.assertEqual([p["id"] for p in c["pozycje"]], ["O1"])
        self.assertEqual(c["kwoty_pozycji"]["netto"], D("48.00"))        # zapisane netto, nie 40 x 1,25
        self.assertEqual(c["reszta"]["netto"], D("2.00"))                # nagłówek - (baza + zapisane netto opcji)
        self.assertEqual(c["roznica_wzgledem_naglowka"]["netto"], D("50.00"))

    def test_dokladny_naglowek_ma_dopasowanie_zgodne(self):
        c = przyczyna(sprawdz_dokument(dok([BAZA, opcja("O1", "50.00")], "150.00")), bledy.OPCJA_W_SUMIE)
        self.assertEqual((c["dopasowanie"], c["reszta"]["netto"]), ("zgodne", 0))

    def test_zbyt_duza_reszta_to_nie_opcja_w_sumie(self):
        # nagłówek 125,00: reszta względem baza + opcja = 27,00 > 25% x 48,00; względem samej bazy - 25,00
        w = sprawdz_dokument(self.dokument("125.00"))
        self.assertNotIn(bledy.OPCJA_W_SUMIE, kody_przyczyn(w))
        self.assertEqual(w["status"], "niespojny")

    def test_naglowek_zgodny_z_wliczona_suma_nie_zglasza_opcji(self):
        w = sprawdz_dokument(self.dokument("100.00"))
        self.assertNotIn(bledy.OPCJA_W_SUMIE, kody_przyczyn(w))

    def test_wybor_podzbioru_po_zapisanych_kwotach(self):
        p = [BAZA, opcja_z_narzutem("O1", "40.00", "25", "48.00"), opcja("O2", "30.00"), opcja("O3", "7.00")]
        c = przyczyna(sprawdz_dokument(dok(p, "150.00")), bledy.OPCJA_W_SUMIE)        # najbliżej: baza + O1
        self.assertEqual([x["id"] for x in c["pozycje"]], ["O1"])

    def test_biblioteka_sprawdz_spojnosc_tez_wykrywa(self):
        from amounts_calc import sprawdz_spojnosc
        w = sprawdz_spojnosc(self.dokument())
        self.assertIn(bledy.OPCJA_W_SUMIE, [x["kod"] for x in w])
        self.assertEqual(w.opcje[0]["dopasowanie"], "najblizsze")


class TestNaglowekZawieraWszystkieOpcje(unittest.TestCase):
    """Tryb awaryjny: ALTERNATYWY_W_SUMIE.naglowek_zawiera_wszystkie_opcje także z błędem narzutu."""

    P = [BAZA, poz("O1", "40.00", alternatywa=True), poz("O2", "60.00", alternatywa=True)]

    def flaga(self, naglowek):
        return przyczyna(sprawdz_dokument(dok(self.P, naglowek)), bledy.ALTERNATYWY_W_SUMIE)[
            "naglowek_zawiera_wszystkie_opcje"]

    def test_dokladnie_wszystkie(self):
        self.assertTrue(self.flaga("200.00"))

    def test_wszystkie_z_bledem_narzutu(self):
        self.assertTrue(self.flaga("197.00"))          # 3,00 od sumy ze wszystkimi, 37,00 od najlepszej kombinacji
        self.assertTrue(self.flaga("203.50"))

    def test_zwykla_kombinacja_nie_jest_wszystkimi(self):
        self.assertFalse(self.flaga("160.00"))
        self.assertFalse(self.flaga("140.00"))

    def test_zbyt_daleko_od_sumy_ze_wszystkimi(self):
        self.assertFalse(self.flaga("180.00"))


if __name__ == "__main__":
    unittest.main()
