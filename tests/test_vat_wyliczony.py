"""VAT wyliczony ze stawki i netto pozycji (gdy pozycje nie mają zapisanego VAT)."""
import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.check import main, ma_problem, sprawdz_dokument, sprawdz_partie
from amounts_calc.klasyfikacja import przyczyna_vat_wyliczony, stawki_tlumaczace


def poz(netto, stawka=23, **extra):
    d = {"stawka_vat": stawka, "netto": netto}
    d.update(extra)
    return d


def dok(netto, vat, brutto, pozycje, **extra):
    d = {"id": "D", "typ": "FV", "suma_netto": netto, "suma_vat": vat, "suma_brutto": brutto, "pozycje": pozycje}
    d.update(extra)
    return d


def kody(w):
    return {p["kod"] for p in w["przyczyny"]}


def jedna(w, kod):
    return [p for p in w["przyczyny"] if p["kod"] == kod][0]


DWIE_STAWKI = [poz("100.00", 23), poz("27.00", 8)]       # VAT 23,00 + 2,16 = 25,16


class TestStawkiTlumaczace(unittest.TestCase):
    WG = [{"stawka": "23", "netto": D("100"), "vat": D("23.00")}, {"stawka": "8", "netto": D("27"), "vat": D("2.16")},
          {"stawka": "5", "netto": D("10"), "vat": D("0.50")}, {"stawka": "zw", "netto": D("9"), "vat": D("0.00")}]

    def test_pojedyncza_stawka(self):
        self.assertEqual(stawki_tlumaczace(self.WG, D("-2.16")), [["8"]])
        self.assertEqual(stawki_tlumaczace(self.WG, D("2.16")), [["8"]])      # po drugiej stronie też
        self.assertEqual(stawki_tlumaczace(self.WG, D("-23.00")), [["23"]])

    def test_kilka_stawek(self):
        self.assertEqual(stawki_tlumaczace(self.WG, D("-25.16")), [["23", "8"]])
        self.assertEqual(stawki_tlumaczace(self.WG, D("-2.66")), [["8", "5"]])

    def test_prog_grosza_i_brak_wyjasnienia(self):
        self.assertEqual(stawki_tlumaczace(self.WG, D("-2.17")), [["8"]])
        self.assertEqual(stawki_tlumaczace(self.WG, D("-2.18")), [])
        self.assertEqual(stawki_tlumaczace(self.WG, D("-0.01")), [])

    def test_stawki_zerowe_nic_nie_tlumacza(self):
        self.assertEqual(stawki_tlumaczace([{"stawka": "zw", "netto": D(5), "vat": D(0)}], D("0.00")), [])

    def test_maks_i_najmniejsze_zbiory(self):
        wg = [{"stawka": s, "netto": D(1), "vat": D("1.00")} for s in ("a", "b", "c", "d")]
        self.assertEqual(stawki_tlumaczace(wg, D("1.00")), [["a"], ["b"], ["c"]])


class TestPrzyczynaVatWyliczony(unittest.TestCase):
    W = {"per_stawka": {"vat": D("0.23"), "brutto": D("1.22"), "netto": D("0.99"), "wg_stawek": []},
         "per_pozycja": {"vat": D("0.24"), "brutto": D("1.23"), "netto": D("0.99"), "wg_stawek": []}}

    def test_zgodny_z_jednym_trybem(self):
        p = przyczyna_vat_wyliczony(self.W, D("0.24"), D("1.23"))
        self.assertEqual((p["kod"], p["tryby_vat"], p["roznica"]), (bledy.VAT_WYLICZONY_ZGODNY, ["per_pozycja"], D(0)))
        p = przyczyna_vat_wyliczony(self.W, D("0.2300"), D("1.22"))
        self.assertEqual(p["tryby_vat"], ["per_stawka"])

    def test_zgodny_z_oboma(self):
        w = {k: dict(v, vat=D("0.23")) for k, v in self.W.items()}
        self.assertEqual(przyczyna_vat_wyliczony(w, D("0.23"), D("1.22"))["tryby_vat"], ["per_stawka", "per_pozycja"])

    def test_rozny_wybiera_blizszy_tryb(self):
        p = przyczyna_vat_wyliczony(self.W, D("0.25"), D("1.24"))
        self.assertEqual((p["kod"], p["tryb_vat"], p["roznica"]), (bledy.VAT_WYLICZONY_ROZNY, "per_pozycja", D("0.01")))
        self.assertEqual(p["roznica_brutto"], D("0.01"))

    def test_polgrosz_gdy_netto_niezaokraglone(self):
        self.assertEqual(przyczyna_vat_wyliczony(self.W, D("0.25"), D("1.24"), True)["kod"], bledy.POLGROSZ)
        # większa różnica nie jest półgroszem nawet przy niezaokrąglonym netto
        self.assertEqual(przyczyna_vat_wyliczony(self.W, D("0.30"), D("1.24"), True)["kod"], bledy.VAT_WYLICZONY_ROZNY)


class TestVatWyliczonyWDokumencie(unittest.TestCase):
    def test_zgodny(self):
        w = sprawdz_dokument(dok("127.00", "25.16", "152.16", DWIE_STAWKI))
        self.assertEqual((w["status"], w["blad"], w["dane"]), ("spojny", None, "brak_vat"))
        self.assertEqual(kody(w), {bledy.VAT_WYLICZONY_ZGODNY})
        self.assertNotIn(bledy.BRAK_VAT_W_POZYCJACH, kody(w))
        p = jedna(w, bledy.VAT_WYLICZONY_ZGODNY)
        self.assertEqual((p["vat_wyliczony"], p["vat_naglowka"], p["brutto_wyliczone"], p["brutto_naglowka"]),
                         (D("25.16"), D("25.16"), D("152.16"), D("152.16")))
        self.assertEqual({g["stawka"]: g["vat"] for g in p["wg_stawek"]}, {"23": D("23.00"), "8": D("2.16")})
        self.assertFalse(ma_problem(w))

    def test_rozny_i_stawki_tlumaczace(self):
        w = sprawdz_dokument(dok("127.00", "23.00", "150.00", DWIE_STAWKI))      # nagłówek pomija VAT 8%
        self.assertEqual(w["status"], "niespojny")
        p = jedna(w, bledy.VAT_WYLICZONY_ROZNY)
        self.assertEqual((p["roznica"], p["vat_wyliczony"], p["vat_naglowka"]), (D("-2.16"), D("25.16"), D("23.00")))
        self.assertEqual(p["stawki_tlumaczace"], [["8"]])
        self.assertEqual(p["roznica_brutto"], D("150.00") - D("152.16"))
        self.assertNotIn(bledy.BRAK_VAT_W_POZYCJACH, kody(w))
        self.assertEqual(w["max_roznica"], D("2.16"))

    def test_rozny_przy_wszystkich_stawkach_naraz(self):
        w = sprawdz_dokument(dok("127.00", "0.00", "127.00", DWIE_STAWKI))
        self.assertEqual(jedna(w, bledy.VAT_WYLICZONY_ROZNY)["stawki_tlumaczace"], [["23", "8"]])

    def test_tryb_vat_ktory_pasuje(self):
        trzy = [poz("0.33")] * 3
        for vat, tryby in (("0.23", ["per_stawka"]), ("0.24", ["per_pozycja"])):
            w = sprawdz_dokument(dok("0.99", vat, str(D("0.99") + D(vat)), trzy))
            self.assertEqual(jedna(w, bledy.VAT_WYLICZONY_ZGODNY)["tryby_vat"], tryby, vat)
        w = sprawdz_dokument(dok("0.99", "0.25", "1.24", trzy))
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.VAT_WYLICZONY_ROZNY, kody(w))

    def test_stawki_zwolnione(self):
        w = sprawdz_dokument(dok("30.00", "0.00", "30.00", [poz("10.00", "zw"), poz("20.00", "np")]))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.VAT_WYLICZONY_ZGODNY}))

    def test_pozycje_nadrzedne_nie_sa_liczone_podwojnie(self):
        pozycje = [{"id": "Z", "stawka_vat": 23}, {"parent_id": "Z", "stawka_vat": 23, "netto": "100.00"},
                   {"parent_id": "Z", "stawka_vat": 23, "netto": "50.00"}, poz("27.00", 8)]
        w = sprawdz_dokument(dok("177.00", "36.66", "213.66", pozycje))        # 34,50 + 2,16
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.VAT_WYLICZONY_ZGODNY}))

    def test_brak_stawki_zostaje_brak_vat(self):
        w = sprawdz_dokument(dok("127.00", "25.16", "152.16", [{"netto": "100.00"}, {"netto": "27.00", "stawka_vat": 8}]))
        self.assertEqual((w["status"], kody(w)), ("niepelny", {bledy.BRAK_VAT_W_POZYCJACH}))

    def test_nieznana_stawka_to_blad(self):
        w = sprawdz_dokument(dok("100.00", "23.00", "123.00", [poz("100.00", 7)]))
        self.assertEqual((w["status"], w["blad"]["kod"]), ("blad", bledy.NIEZNANA_STAWKA))

    def test_zle_netto_to_blad(self):
        w = sprawdz_dokument(dok("100.00", "23.00", "123.00", [poz("abc")]))
        self.assertEqual(w["status"], "blad")

    def test_ujemne_netto(self):
        pozycje = [poz("100.00"), poz("-10.00")]
        w = sprawdz_dokument(dok("90.00", "20.70", "110.70", pozycje), dopusc_ujemne=True)
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.VAT_WYLICZONY_ZGODNY}))
        w = sprawdz_dokument(dok("90.00", "20.70", "110.70", pozycje))
        self.assertEqual((w["status"], w["blad"]["kod"]), ("blad", bledy.CENA_UJEMNA))

    def test_zgodny_vat_ale_zle_brutto_w_naglowku(self):
        w = sprawdz_dokument(dok("127.00", "25.16", "152.99", DWIE_STAWKI))
        self.assertEqual(w["status"], "niespojny")                  # brutto != netto + vat wykrywa sprawdz_spojnosc
        self.assertIn(bledy.VAT_WYLICZONY_ZGODNY, kody(w))
        self.assertEqual(jedna(w, bledy.VAT_WYLICZONY_ZGODNY)["brutto_wyliczone"], D("152.16"))

    def test_netto_niezaokraglone_i_polgrosz(self):
        w = sprawdz_dokument(dok("127.004", "25.17", "152.17", [poz("100.004"), poz("27.00", 8)]))
        # VAT wyliczony 25,16 (23% od 100,00 + 2,16), nagłówek 25,17: różnica 0,01 przy niezaokrąglonym netto
        self.assertEqual(w["status"], "drobiazg")
        self.assertIn(bledy.POLGROSZ, kody(w))
        self.assertNotIn(bledy.VAT_WYLICZONY_ROZNY, kody(w))

    def test_jeden_grosz_przy_zaokraglonych_to_rozny(self):
        w = sprawdz_dokument(dok("127.00", "25.17", "152.17", DWIE_STAWKI))
        self.assertEqual(jedna(w, bledy.VAT_WYLICZONY_ROZNY)["roznica"], D("0.01"))
        self.assertEqual(w["status"], "niespojny")


class TestVatWyliczonyWRaporcie(unittest.TestCase):
    DOKUMENTY = [
        dict(dok("127.00", "25.16", "152.16", DWIE_STAWKI), id="zgodny1"),
        dict(dok("30.00", "0.00", "30.00", [poz("10.00", "zw"), poz("20.00", "np")]), id="zgodny2"),
        dict(dok("127.00", "23.00", "150.00", DWIE_STAWKI), id="rozny"),
        dict(dok("127.00", "25.16", "152.16", [{"netto": "100.00"}, {"netto": "27.00"}]), id="niepelny"),
    ]

    def uruchom(self, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            wej = os.path.join(tmp, "d.json")
            with open(wej, "w", encoding="utf-8") as f:
                json.dump(self.DOKUMENTY, f)
            wyj_j, wyj_c = os.path.join(tmp, "w.json"), os.path.join(tmp, "w.csv")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                kod = main([wej, "--json", wyj_j, "--csv", wyj_c] + list(argv))
            with open(wyj_j, encoding="utf-8") as f:
                raport = json.load(f)
            with open(wyj_c, encoding="utf-8-sig", newline="") as f:
                wiersze = list(csv.DictReader(f, delimiter=";"))
        return kod, out.getvalue(), raport, wiersze

    def test_partia_zlicza_osobno(self):
        wyniki, p = sprawdz_partie(self.DOKUMENTY)
        self.assertEqual(p["status"]["niepelny"], 1)
        self.assertEqual(p["status"]["niespojny"], 1)
        self.assertEqual(p["status"]["spojny"], 2)
        self.assertEqual(p["kody"][bledy.VAT_WYLICZONY_ZGODNY], 2)
        self.assertEqual(p["kody"][bledy.VAT_WYLICZONY_ROZNY], 1)
        self.assertEqual(p["kody"][bledy.BRAK_VAT_W_POZYCJACH], 1)

    def test_tekst_json_csv_zawieraja_nowe_kody(self):
        kod, out, raport, wiersze = self.uruchom()
        self.assertEqual(kod, 1)
        self.assertIn("VAT_WYLICZONY_ZGODNY", out)
        self.assertIn("VAT_WYLICZONY_ROZNY", out)
        self.assertEqual([r["id"] for r in raport], ["rozny", "niepelny"])
        rozny = raport[0]["przyczyny"][0]
        self.assertEqual((rozny["kod"], rozny["roznica"], rozny["stawki_tlumaczace"]),
                         ("VAT_WYLICZONY_ROZNY", "-2.16", [["8"]]))
        self.assertEqual({w["id"]: w["kody"] for w in wiersze},
                         {"rozny": "VAT_WYLICZONY_ROZNY", "niepelny": "BRAK_VAT_W_POZYCJACH"})
        self.assertEqual(wiersze[0]["najwieksza_roznica"], "2,16")


if __name__ == "__main__":
    unittest.main()
