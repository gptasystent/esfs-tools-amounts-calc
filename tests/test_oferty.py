"""Oferty i zamówienia: pozycje z ceną zakupu i narzutem w raporcie CLI (ILOSC_X_CENA_NARZUT)."""
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
from amounts_calc.check import etykieta_kodu, main, sprawdz_dokument, sprawdz_partie
from amounts_calc.klasyfikacja import (OPIS_NARZUT_NIEZGODNA, OPIS_NARZUT_TLUMACZY, przyczyny_ilosc_x_cena_narzut)


def oferta_poz(netto="270.00", vat="62.10", brutto="332.10", **extra):
    """3 szt., zakup 80, narzut 25% (sprzedaż 100,00), rabat 10% => 270,00 netto."""
    p = {"ilosc": 3, "cena_zakupu_jedn": "80", "narzut_proc": 25, "rabat_proc": 10, "stawka_vat": 23,
         "netto": netto, "vat": vat, "brutto": brutto}
    p.update(extra)
    return p


def dok(pozycje, netto="270.00", vat="62.10", brutto="332.10", **extra):
    d = {"id": "OF/1", "typ": "OFERTA", "suma_netto": netto, "suma_vat": vat, "suma_brutto": brutto, "pozycje": pozycje}
    d.update(extra)
    return d


def narzutowe(w):
    return [p for p in w["przyczyny"] if p["kod"] == bledy.ILOSC_X_CENA_NARZUT]


def kody(w):
    return {p["kod"] for p in w["przyczyny"]}


class TestZgodnaOferta(unittest.TestCase):
    def test_bez_ceny_netto_jest_spojna_bez_przyczyn(self):
        w = sprawdz_dokument(dok([oferta_poz()]))
        self.assertEqual((w["status"], w["przyczyny"], w["niespojnosci"], w["blad"]), ("spojny", [], [], None))
        self.assertEqual(w["tryb_pasujacy"], "oba")

    def test_cena_netto_to_cena_zakupu_narzut_tlumaczy_roznice(self):
        # cena_netto_jedn = 80 (zakup): stary test ilość x cena dałby 216 zamiast 270 i fałszywe ILOSC_X_CENA
        w = sprawdz_dokument(dok([oferta_poz(cena_netto_jedn="80")]))
        self.assertEqual(w["status"], "spojny")
        self.assertNotIn(bledy.ILOSC_X_CENA, kody(w))
        (p,) = narzutowe(w)
        self.assertEqual((p["opis"], p["informacja"], p["liczba"]), (OPIS_NARZUT_TLUMACZY, True, 1))
        self.assertEqual(p["pozycje"][0]["bez_narzutu"], D("216.00"))
        self.assertEqual(p["pozycje"][0]["oczekiwane"], D("270.00"))
        self.assertEqual(etykieta_kodu(p), "ILOSC_X_CENA_NARZUT (informacja)")
        self.assertEqual(w["tryb_pasujacy"], "oba")       # (b) też liczy z narzutu

    def test_cena_netto_to_zapisana_cena_sprzedazy(self):
        w = sprawdz_dokument(dok([oferta_poz(cena_netto_jedn="100.00")]))
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))

    def test_tolerancja_grosza(self):
        ok = sprawdz_dokument(dok([oferta_poz("270.01", "62.10", "332.11")], "270.01", "62.10", "332.11"))
        self.assertEqual(narzutowe(ok), [])
        zle = sprawdz_dokument(dok([oferta_poz("270.02", "62.10", "332.12")], "270.02", "62.10", "332.12"))
        self.assertEqual(narzutowe(zle)[0]["opis"], OPIS_NARZUT_NIEZGODNA)

    def test_marza_zamiast_narzutu(self):
        p = oferta_poz(narzut_proc=None, marza_proc=20)         # 80 / 0,8 = 100,00
        self.assertEqual(sprawdz_dokument(dok([p]))["status"], "spojny")

    def test_narzut_zero(self):
        p = oferta_poz("216.00", "49.68", "265.68", narzut_proc=0)
        self.assertEqual(sprawdz_dokument(dok([p], "216.00", "49.68", "265.68"))["status"], "spojny")

    def test_rabat_dokumentu(self):
        p = oferta_poz("243.00", "55.89", "298.89")
        d = dok([p], "243.00", "55.89", "298.89", rabat_dokumentu_proc=10)
        self.assertEqual(sprawdz_dokument(d)["status"], "spojny")


class TestNiezgodnaOferta(unittest.TestCase):
    def blad(self, netto, vat, brutto, **extra):
        return sprawdz_dokument(dok([oferta_poz(netto, vat, brutto, **extra)], netto, vat, brutto))

    def test_narzut_nie_zostal_zastosowany(self):
        w = self.blad("216.00", "49.68", "265.68")
        self.assertEqual(w["status"], "niespojny")
        (p,) = narzutowe(w)
        self.assertEqual((p["opis"], p["liczba"], p["roznica"]), (OPIS_NARZUT_NIEZGODNA, 1, D("-54.00")))
        self.assertNotIn("informacja", p)
        d = p["pozycje"][0]
        self.assertEqual((d["zapisane"], d["oczekiwane"], d["wyjasnienie"], d["narzut_wynikowy"]),
                         (D("216.00"), D("270.00"), "narzut nie został zastosowany", D("0.00")))
        self.assertNotIn(bledy.NIEZGODNY_Z_BIBLIOTEKA, kody(w))      # przyczyna jest już wskazana
        self.assertNotIn(bledy.ILOSC_X_CENA, kody(w))

    def test_rabat_nie_zostal_zastosowany(self):
        w = self.blad("300.00", "69.00", "369.00")
        d = narzutowe(w)[0]["pozycje"][0]
        self.assertEqual(d["wyjasnienie"], "rabat nie został zastosowany")
        self.assertEqual(d["narzut_wynikowy"], D("38.89"))       # 300 / (3 * 0,9) / 80 - 1

    def test_ani_narzut_ani_rabat(self):
        w = self.blad("240.00", "55.20", "295.20")
        self.assertEqual(narzutowe(w)[0]["pozycje"][0]["wyjasnienie"], "nie zastosowano ani narzutu, ani rabatu")

    def test_bez_wyjasnienia(self):
        w = self.blad("123.45", "28.39", "151.84")
        d = narzutowe(w)[0]["pozycje"][0]
        self.assertIsNone(d["wyjasnienie"])
        self.assertEqual(d["narzut_wynikowy"], D("-42.85"))      # 123,45 / 2,7 / 80 - 1

    def test_zapisana_cena_sprzedazy_nie_zgadza_sie_z_zakup_plus_narzut(self):
        # cena sprzedaży 99 zamiast 100, a wartość policzona z 99: 3 * 99 * 0,9 = 267,30
        w = sprawdz_dokument(dok([oferta_poz("267.30", "61.48", "328.78", cena_netto_jedn="99.00")],
                                 "267.30", "61.48", "328.78"))
        d = narzutowe(w)[0]["pozycje"][0]
        self.assertEqual((d["cena_sprzedazy_zapisana"], d["cena_sprzedazy_oczekiwana"]), (D("99.00"), D("100.00")))
        self.assertEqual(w["status"], "niespojny")

    def test_zla_cena_sprzedazy_mimo_poprawnej_wartosci(self):
        w = sprawdz_dokument(dok([oferta_poz(cena_netto_jedn="99.00")]))
        self.assertEqual(narzutowe(w)[0]["opis"], OPIS_NARZUT_NIEZGODNA)
        self.assertEqual(narzutowe(w)[0]["pozycje"][0]["roznica"], D("0.00"))

    def test_max_roznica_uwzglednia_przyczyne(self):
        # największa z różnic: brutto względem bibliotecznego (332,10 - 265,68), nie mniejsza od różnicy netto
        self.assertEqual(self.blad("216.00", "49.68", "265.68")["max_roznica"], D("66.42"))

    def test_zwykla_pozycja_dalej_ma_ilosc_x_cena(self):
        zwykla = {"ilosc": 2, "cena_netto_jedn": "10", "stawka_vat": 23, "netto": "25.00", "vat": "5.75",
                  "brutto": "30.75"}
        w = sprawdz_dokument(dok([oferta_poz(), zwykla], "295.00", "67.85", "362.85"))
        self.assertEqual(kody(w), {bledy.ILOSC_X_CENA})
        self.assertEqual([p["indeks"] for p in [x for x in w["przyczyny"] if x["kod"] == bledy.ILOSC_X_CENA][0]["pozycje"]], [1])

    def test_oba_warianty_naraz(self):
        dobra = oferta_poz(cena_netto_jedn="80")                           # info
        zla = oferta_poz("216.00", "49.68", "265.68")                      # niezgodność
        w = sprawdz_dokument(dok([dobra, zla], "486.00", "111.78", "597.78"))
        warianty = sorted((p["opis"] for p in narzutowe(w)))
        self.assertEqual(warianty, sorted([OPIS_NARZUT_NIEZGODNA, OPIS_NARZUT_TLUMACZY]))
        self.assertEqual(w["status"], "niespojny")


class TestRodzajeDanych(unittest.TestCase):
    def test_pozycje_bez_vat_ze_stawka_i_narzutem(self):
        p = {"ilosc": 3, "cena_zakupu_jedn": "80", "narzut_proc": 25, "rabat_proc": 10, "stawka_vat": 23,
             "netto": "270.00"}
        w = sprawdz_dokument(dok([p]))
        self.assertEqual(w["dane"], "brak_vat")
        self.assertEqual(w["status"], "spojny")
        self.assertIn(bledy.VAT_WYLICZONY_ZGODNY, kody(w))
        p["netto"] = "216.00"
        w = sprawdz_dokument(dok([p], "216.00"))
        self.assertEqual(narzutowe(w)[0]["opis"], OPIS_NARZUT_NIEZGODNA)

    def test_tryb_brutto_ignoruje_narzut(self):
        p = {"ilosc": 1, "cena_brutto_jedn": "123.00", "cena_zakupu_jedn": "1", "narzut_proc": 5, "stawka_vat": 23,
             "netto": "100.00", "vat": "23.00", "brutto": "123.00"}
        w = sprawdz_dokument(dok([p], "100.00", "23.00", "123.00", tryb="brutto"))
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))

    def test_zestaw_z_dziecmi_o_narzucie(self):
        pozycje = [{"id": "Z", "ilosc": 1, "stawka_vat": 23, "netto": "400.00", "vat": "92.00", "brutto": "492.00"},
                   dict(oferta_poz("270.00", "62.10", "332.10"), parent_id="Z"),
                   {"parent_id": "Z", "ilosc": 1, "cena_zakupu_jedn": "104", "narzut_proc": 25, "stawka_vat": 23,
                    "netto": "130.00", "vat": "29.90", "brutto": "159.90"}]
        w = sprawdz_dokument(dok(pozycje, "400.00", "92.00", "492.00"))
        self.assertEqual((w["status"], w["przyczyny"], w["blad"]), ("spojny", [], None))

    def test_zly_narzut_to_blad_walidacji(self):
        w = sprawdz_dokument(dok([oferta_poz(marza_proc=10)]))
        self.assertEqual((w["status"], w["blad"]["kod"]), ("blad", bledy.NARZUT_I_MARZA))
        w = sprawdz_dokument(dok([oferta_poz(narzut_proc="abc")]))
        self.assertEqual(w["blad"]["kod"], bledy.NIEPOPRAWNA_LICZBA)

    def test_ujemna_linia_z_narzutem(self):
        p = oferta_poz("-270.00", "-62.10", "-332.10", ilosc=-3)
        d = dok([p], "-270.00", "-62.10", "-332.10")
        self.assertEqual(sprawdz_dokument(d, dopusc_ujemne=True)["status"], "spojny")
        self.assertEqual(sprawdz_dokument(d)["blad"]["kod"], bledy.ILOSC_UJEMNA)


class TestJednostkowe(unittest.TestCase):
    def rekord(self, **kw):
        r = {"indeks": 0, "id": "a", "zapisane": D("100"), "oczekiwane": D("100"), "cena_oczekiwana": D("10"),
             "cena_zapisana": None, "naiwne": None, "wyjasnienie": None, "narzut_wynikowy": None}
        r.update(kw)
        return r

    def test_brak_przyczyn(self):
        self.assertEqual(przyczyny_ilosc_x_cena_narzut([self.rekord()]), [])
        self.assertEqual(przyczyny_ilosc_x_cena_narzut([self.rekord(naiwne=D("100"))]), [])

    def test_informacja(self):
        (p,) = przyczyny_ilosc_x_cena_narzut([self.rekord(naiwne=D("80"))])
        self.assertEqual((p["opis"], p["informacja"], p["roznica"]), (OPIS_NARZUT_TLUMACZY, True, None))

    def test_niezgodnosc_ma_pierwszenstwo_per_pozycja(self):
        przyczyny = przyczyny_ilosc_x_cena_narzut([self.rekord(zapisane=D("90"), naiwne=D("90")),
                                                  self.rekord(indeks=1, naiwne=D("80"))])
        self.assertEqual([p["opis"] for p in przyczyny], [OPIS_NARZUT_NIEZGODNA, OPIS_NARZUT_TLUMACZY])
        self.assertEqual(przyczyny[0]["roznica"], D("-10"))

    def test_limit_pozycji_w_opisie(self):
        (p,) = przyczyny_ilosc_x_cena_narzut([self.rekord(indeks=i, zapisane=D("1")) for i in range(9)])
        self.assertEqual((p["liczba"], len(p["pozycje"])), (9, 5))


class TestRaport(unittest.TestCase):
    DOKUMENTY = [
        dict(dok([oferta_poz(cena_netto_jedn="80")]), id="info1"),
        dict(dok([oferta_poz(cena_netto_jedn="80")]), id="info2"),
        dict(dok([oferta_poz("216.00", "49.68", "265.68")], "216.00", "49.68", "265.68"), id="zla"),
    ]

    def test_rozklad_kodow_rozroznia_informacje(self):
        wyniki, p = sprawdz_partie(self.DOKUMENTY)
        self.assertEqual(p["kody"]["ILOSC_X_CENA_NARZUT (informacja)"], 2)
        self.assertEqual(p["kody"]["ILOSC_X_CENA_NARZUT"], 1)
        self.assertEqual((p["spojne"], p["status"]["niespojny"]), (2, 1))
        self.assertNotIn("ILOSC_X_CENA", p["kody"])

    def uruchom(self, *argv, mapowanie=None, dokumenty=None):
        with tempfile.TemporaryDirectory() as tmp:
            wej = os.path.join(tmp, "d.json")
            with open(wej, "w", encoding="utf-8") as f:
                json.dump(dokumenty or self.DOKUMENTY, f)
            wyj_j, wyj_c = os.path.join(tmp, "w.json"), os.path.join(tmp, "w.csv")
            args = [wej, "--json", wyj_j, "--csv", wyj_c] + list(argv)
            if mapowanie:
                m = os.path.join(tmp, "m.json")
                with open(m, "w", encoding="utf-8") as f:
                    json.dump(mapowanie, f)
                args += ["--mapowanie", m]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                kod = main(args)
            with open(wyj_j, encoding="utf-8") as f:
                raport = json.load(f)
            with open(wyj_c, encoding="utf-8-sig", newline="") as f:
                wiersze = list(csv.DictReader(f, delimiter=";"))
        return kod, out.getvalue(), raport, wiersze

    def test_cli_json_csv_tekst(self):
        kod, out, raport, wiersze = self.uruchom()
        self.assertEqual(kod, 1)
        self.assertEqual([r["id"] for r in raport], ["zla"])
        p = raport[0]["przyczyny"][0]
        self.assertEqual((p["kod"], p["opis"], p["roznica"]), ("ILOSC_X_CENA_NARZUT", OPIS_NARZUT_NIEZGODNA, "-54.00"))
        self.assertEqual(p["pozycje"][0]["wyjasnienie"], "narzut nie został zastosowany")
        self.assertEqual([w["kody"] for w in wiersze], ["ILOSC_X_CENA_NARZUT"])
        self.assertIn("ILOSC_X_CENA_NARZUT (informacja)", out)
        self.assertIn("Bez uwag: 2 z 3 dokumentów", out)

    def test_cli_mapowanie_nazw_zakupu_i_narzutu(self):
        """Pola zakupu i narzutu w innym schemacie, bez zmiany kodu."""
        doc = {"nr": "M/1", "netto": "270.00", "kwota_vat": "62.10", "brutto": "332.10",
               "linie": [{"qty": 3, "kosz": "80", "narz": 25, "rabat": 10, "stawka": 23,
                          "wartosc_netto": "270.00", "wartosc_vat": "62.10", "wartosc_brutto": "332.10"}]}
        m = {"pozycja": {"cena_zakupu_jedn": "kosz", "narzut_proc": "narz"}}
        kod, out, raport, _ = self.uruchom(dokumenty=[doc], mapowanie=m)
        self.assertEqual((kod, raport), (0, []))
        bez = self.uruchom(dokumenty=[doc])       # bez mapowania pól zakupu: cena pozycji nieznana => błąd
        self.assertEqual(bez[2][0]["blad"]["kod"], "BRAK_CENY")
        doc["linie"][0]["wartosc_netto"] = "216.00"
        doc["linie"][0]["wartosc_vat"], doc["linie"][0]["wartosc_brutto"] = "49.68", "265.68"
        doc["netto"], doc["kwota_vat"], doc["brutto"] = "216.00", "49.68", "265.68"
        kod, out, raport, _ = self.uruchom(dokumenty=[doc], mapowanie=m)
        self.assertEqual((kod, raport[0]["przyczyny"][0]["kod"]), (1, "ILOSC_X_CENA_NARZUT"))


if __name__ == "__main__":
    unittest.main()
