"""Wartości ujemne: rabat jako linia, korekta, zwrot; zaokrąglanie symetryczne względem zera."""
import random
import unittest
from decimal import ROUND_HALF_EVEN, Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, dokument_z_slownika, oblicz, porownaj, sprawdz_spojnosc, Pozycja
from amounts_calc.config import (DOMYSLNA, Konfiguracja, ROZKLADY, TRYB_BRUTTO, TRYB_NETTO, VAT_PER_POZYCJA,
                                 VAT_PER_STAWKA)


def n(ilosc, cena, stawka=23, **kw):
    return Pozycja(ilosc=ilosc, cena_netto_jedn=cena, stawka_vat=stawka, **kw)


class TestZaokraglanieSymetryczne(unittest.TestCase):
    def test_tabela_kwot(self):
        tabela = [("12.345", "12.35"), ("-12.345", "-12.35"), ("0.005", "0.01"), ("-0.005", "-0.01"),
                  ("0.015", "0.02"), ("-0.015", "-0.02"), ("0.025", "0.03"), ("-0.025", "-0.03"),
                  ("0.0049", "0.00"), ("-0.0049", "0.00"), ("-0.004", "0.00"), ("-1.999", "-2.00"),
                  ("-100", "-100.00"), ("0", "0.00")]
        for wej, oczek in tabela:
            with self.subTest(wej=wej):
                self.assertEqual(DOMYSLNA.kwota(D(wej)), D(oczek))

    def test_zero_nie_ma_znaku(self):
        for wej in ("-0.004", "-0.0001", "-0", "0"):
            self.assertFalse(DOMYSLNA.kwota(D(wej)).is_signed(), wej)

    def test_cena_i_procent_tez_symetryczne(self):
        self.assertEqual(DOMYSLNA.cena(D("-0.12345")), D("-0.1235"))
        self.assertEqual(DOMYSLNA.cena(D("0.12345")), D("0.1235"))
        self.assertEqual(DOMYSLNA.procent(D("-33.335")), D("-33.34"))

    def test_inna_regula_tez_dziala_na_module(self):
        k = Konfiguracja(zaokraglanie=ROUND_HALF_EVEN)
        self.assertEqual(k.kwota(D("0.025")), D("0.02"))
        self.assertEqual(k.kwota(D("-0.025")), D("-0.02"))
        self.assertEqual(k.kwota(D("-0.035")), D("-0.04"))

    def test_duze_liczby_nie_traca_cyfr(self):
        x = D("123456789012345678901234567890.125")
        self.assertEqual(DOMYSLNA.kwota(x), D("123456789012345678901234567890.13"))
        self.assertEqual(DOMYSLNA.kwota(x.copy_negate()), D("-123456789012345678901234567890.13"))

    def test_vat_od_ujemnego_netto_jest_lustrzany(self):
        for cena in ("0.50", "0.30", "1.01", "12.345"):
            plus = oblicz([n(1, cena)], tryb_vat=VAT_PER_POZYCJA).pozycje[0]
            minus = oblicz([n(1, "-" + cena)], tryb_vat=VAT_PER_POZYCJA, dopusc_ujemne=True).pozycje[0]
            self.assertEqual((minus.netto, minus.vat, minus.brutto), (-plus.netto, -plus.vat, -plus.brutto), cena)
        # 0,50 * 23% = 0,115 -> 0,12 (half up); -0,50 -> -0,12
        self.assertEqual(oblicz([n(1, "-0.50")], dopusc_ujemne=True).suma_vat, D("-0.12"))


class TestOpcjaDopuscUjemne(unittest.TestCase):
    def test_domyslnie_blad(self):
        for poz, kod in [(n(-1, "10"), bledy.ILOSC_UJEMNA), (n(1, "-10"), bledy.CENA_UJEMNA)]:
            with self.subTest(kod=kod):
                with self.assertRaises(bledy.BladWalidacji) as cm:
                    oblicz([poz])
                self.assertEqual(cm.exception.kod, kod)
                with self.assertRaises(bledy.BladWalidacji):
                    oblicz([poz], dopusc_ujemne=False)

    def test_ujemna_ilosc_i_cena(self):
        d = oblicz([n(-2, "10"), n(1, "-5")], dopusc_ujemne=True)
        self.assertEqual([p.netto for p in d.pozycje], [D("-20.00"), D("-5.00")])
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("-25.00"), D("-5.75"), D("-30.75")))

    def test_dwa_minusy_daja_plus(self):
        self.assertEqual(oblicz([n(-2, "-10")], dopusc_ujemne=True).suma_netto, D("20.00"))

    def test_rabat_i_cena_zero_dalej_poprawne_i_rabat_ujemny_dalej_blad(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([n(1, "10", rabat_proc=-5)], dopusc_ujemne=True)
        self.assertEqual(cm.exception.kod, bledy.RABAT_POZA_ZAKRESEM)
        with self.assertRaises(bledy.BladWalidacji):
            oblicz([n(1, "10")], rabat_dokumentu_proc=101, dopusc_ujemne=True)

    def test_rabat_pozycji_na_ujemnej_linii(self):
        d = oblicz([n(1, "-100", rabat_proc=10)], dopusc_ujemne=True)
        self.assertEqual((d.pozycje[0].cena_po_rabacie, d.suma_netto), (D("-90.0000"), D("-90.00")))

    def test_rabat_dokumentu_na_liniach_ujemnych(self):
        d = oblicz([n(1, "100"), n(1, "-20")], rabat_dokumentu_proc=10, dopusc_ujemne=True)
        self.assertEqual((d.pozycje[0].netto, d.pozycje[1].netto, d.suma_netto), (D("90.00"), D("-18.00"), D("72.00")))

    def test_tryb_brutto(self):
        d = oblicz([Pozycja(ilosc=1, cena_brutto_jedn="123.00", stawka_vat=23),
                    Pozycja(ilosc=-1, cena_brutto_jedn="12.30", stawka_vat=23)], tryb=TRYB_BRUTTO, dopusc_ujemne=True)
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("90.00"), D("20.70"), D("110.70")))
        self.assertEqual(sprawdz_spojnosc(d), [])

    def test_koszt_ujemny_nadal_blad(self):
        with self.assertRaises(bledy.BladWalidacji):
            oblicz([Pozycja(ilosc=1, koszt_zakupu_jedn="-1", stawka_vat=23)], narzut_proc=10, dopusc_ujemne=True)


class TestDokumentyZLiniamiUjemnymi(unittest.TestCase):
    def test_faktura_z_rabatem_jako_linia_ujemna(self):
        pozycje = [n(10, "25.00"), n(2, "40.00", 8), n(1, "-30.00"), n(1, "-4.00", 8)]
        d = oblicz(pozycje, dopusc_ujemne=True)
        self.assertEqual([p.netto for p in d.pozycje], [D("250.00"), D("80.00"), D("-30.00"), D("-4.00")])
        self.assertEqual((d.stawka("23").netto, d.stawka("23").vat), (D("220.00"), D("50.60")))
        self.assertEqual((d.stawka("8").netto, d.stawka("8").vat), (D("76.00"), D("6.08")))
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("296.00"), D("56.68"), D("352.68")))
        self.assertEqual(sprawdz_spojnosc(d), [])
        self.assertEqual(porownaj(d, d.do_slownika()), [])

    def test_korekta_w_calosci_ujemna(self):
        orygina = oblicz([n(3, "19.99"), n(1, "5.55", 8)])
        korekta = oblicz([n(-3, "19.99"), n(-1, "5.55", 8)], dopusc_ujemne=True)
        self.assertEqual((korekta.suma_netto, korekta.suma_vat, korekta.suma_brutto),
                         (-orygina.suma_netto, -orygina.suma_vat, -orygina.suma_brutto))
        self.assertTrue(korekta.suma_brutto < 0)
        self.assertEqual(sprawdz_spojnosc(korekta), [])
        r = {x["pole"]: x for x in porownaj(orygina, korekta)}
        self.assertEqual(r["suma_brutto"]["roznica"], -2 * orygina.suma_brutto)

    def test_suma_zerowa(self):
        d = oblicz([n(1, "123.45"), n(-1, "123.45")], dopusc_ujemne=True)
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("0.00"), D("0.00"), D("0.00")))
        self.assertEqual(d.rozbieznosc_vat, D("0.00"))
        self.assertEqual(sprawdz_spojnosc(d), [])
        self.assertEqual([p.netto for p in d.pozycje], [D("123.45"), D("-123.45")])

    def test_sprawdz_spojnosc_wykrywa_blad_w_ujemnym_dokumencie(self):
        d = oblicz([n(-1, "100")], dopusc_ujemne=True).do_slownika()
        self.assertEqual(sprawdz_spojnosc(d), [])
        d["suma_brutto"] = "-123.01"
        w = sprawdz_spojnosc(d)
        kody = {x["kod"] for x in w}
        self.assertIn(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, kody)
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody)
        x = [x for x in w if x["kod"] == bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO][0]
        self.assertEqual((x["oczekiwano"], x["jest"], x["roznica"]), (D("-123.00"), D("-123.01"), D("-0.01")))

    def test_vat_stawki_z_sumy_dla_ujemnych(self):
        d = oblicz([n(-1, "0.33")] * 3, dopusc_ujemne=True, tryb_vat=VAT_PER_STAWKA).do_slownika()
        d["tryb_vat"] = VAT_PER_STAWKA
        self.assertEqual(sprawdz_spojnosc(d), [])
        self.assertEqual(dokument_z_slownika(d).suma_vat, D("-0.23"))
        d["podsumowanie"][0]["vat"] = "-0.24"
        d["podsumowanie"][0]["brutto"] = "-1.23"
        self.assertIn(bledy.VAT_STAWKI_ROZNY_OD_SUMY, {x["kod"] for x in sprawdz_spojnosc(d)})

    def test_porownaj_dokumentow_z_ujemnymi_liniami(self):
        a = oblicz([n(1, "-0.33")] * 3, dopusc_ujemne=True, tryb_vat=VAT_PER_POZYCJA)
        b = oblicz([n(1, "-0.33")] * 3, dopusc_ujemne=True, tryb_vat=VAT_PER_STAWKA)
        r = {x["pole"]: x for x in porownaj(a, b)}
        self.assertEqual(r["suma_vat"], {"pole": "suma_vat", "a": D("-0.24"), "b": D("-0.23"), "roznica": D("0.01")})


class TestLustrzanosc(unittest.TestCase):
    """Dokument z odwróconymi znakami => dokładnie odwrócone wyniki, w każdym trybie."""

    def test_losowe_dokumenty(self):
        rng = random.Random(31337)
        for tryb in (TRYB_NETTO, TRYB_BRUTTO):
            pole = "cena_netto_jedn" if tryb == TRYB_NETTO else "cena_brutto_jedn"
            for _ in range(120):
                wej = [{"ilosc": D(rng.randint(1, 5000)) / D(rng.choice((1, 10, 100))),
                        pole: D(rng.randint(1, 300000)) / D(rng.choice((100, 1000, 10000))),
                        "rabat_proc": D(rng.randint(0, 5000)) / 100 if rng.random() < .3 else 0,
                        "stawka_vat": rng.choice((23, 8, 5, 0, "zw"))} for _ in range(rng.randint(1, 25))]
                odwrocone = [dict(p, ilosc=-p["ilosc"]) for p in wej]
                rabat_dok = D(rng.randint(0, 2000)) / 100 if rng.random() < .3 else 0
                for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
                    for rozklad in ROZKLADY:
                        a = oblicz(wej, tryb=tryb, tryb_vat=tv, rozklad_korekty=rozklad, rabat_dokumentu_proc=rabat_dok)
                        b = oblicz(odwrocone, tryb=tryb, tryb_vat=tv, rozklad_korekty=rozklad,
                                   rabat_dokumentu_proc=rabat_dok, dopusc_ujemne=True)
                        for pa, pb in zip(a.pozycje, b.pozycje):
                            self.assertEqual((pb.netto, pb.vat, pb.brutto), (-pa.netto, -pa.vat, -pa.brutto),
                                             (tryb, tv, rozklad))
                        self.assertEqual((b.suma_netto, b.suma_vat, b.suma_brutto),
                                         (-a.suma_netto, -a.suma_vat, -a.suma_brutto))
                        self.assertEqual(b.rozbieznosc_vat, -a.rozbieznosc_vat)
                        self.assertEqual(sprawdz_spojnosc(b), [])

    def test_niezmienniki_dla_mieszanych_znakow(self):
        rng = random.Random(77)
        for _ in range(300):
            wej = [{"ilosc": D(rng.choice((-1, 1))) * D(rng.randint(1, 3000)) / D(rng.choice((1, 10, 100))),
                    "cena_netto_jedn": D(rng.randint(1, 100000)) / 100,
                    "stawka_vat": rng.choice((23, 8, 0))} for _ in range(rng.randint(1, 20))]
            for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
                for rozklad in ROZKLADY:
                    d = oblicz(wej, tryb_vat=tv, rozklad_korekty=rozklad, dopusc_ujemne=True)
                    for p in d.pozycje:
                        self.assertEqual(p.netto + p.vat, p.brutto)
                    self.assertEqual(sum(p.netto for p in d.pozycje), d.suma_netto)
                    self.assertEqual(sum(p.vat for p in d.pozycje), d.suma_vat)
                    self.assertEqual(sprawdz_spojnosc(d), [])

    def test_najwieksza_pozycja_to_najwiekszy_modul(self):
        # grupa tylko ujemna: korekta groszowa ma trafić na pozycję o największym module
        d = oblicz([n(1, "-0.33"), n(1, "-0.34"), n(1, "-0.33")], dopusc_ujemne=True,
                   rozklad_korekty="najwieksza")
        self.assertEqual([p.vat for p in d.pozycje], [D("-0.08"), D("-0.07"), D("-0.08")])
        plus = oblicz([n(1, "0.33"), n(1, "0.34"), n(1, "0.33")], rozklad_korekty="najwieksza")
        self.assertEqual([p.vat for p in plus.pozycje], [D("0.08"), D("0.07"), D("0.08")])

    def test_tysiac_ujemnych_groszy_proporcjonalnie(self):
        d = oblicz([n(1, "-0.01")] * 1000, dopusc_ujemne=True, rozklad_korekty="proporcjonalnie")
        self.assertEqual(d.suma_vat, D("-2.30"))
        self.assertEqual(min(p.vat for p in d.pozycje), D("-0.01"))
        self.assertEqual(sum(1 for p in d.pozycje if p.vat), 230)


if __name__ == "__main__":
    unittest.main()


# ---- CLI i sprawdz_dokument ----
import contextlib
import io
import json
import os
import tempfile

from amounts_calc.check import main, sprawdz_dokument, sprawdz_partie


def pz(ilosc, cena, netto, vat, brutto, stawka=23):
    return {"ilosc": ilosc, "cena_netto_jedn": cena, "stawka_vat": stawka, "netto": netto, "vat": vat,
            "brutto": brutto}


FAKTURA_Z_RABATEM = {   # 100 zł + linia rabatowa -10 zł (23%): 90,00 + 20,70
    "id": "FV/R", "typ": "FV", "suma_netto": "90.00", "suma_vat": "20.70", "suma_brutto": "110.70",
    "pozycje": [pz(1, "100", "100.00", "23.00", "123.00"), pz(1, "-10", "-10.00", "-2.30", "-12.30")]}
KOREKTA_UJEMNA = {
    "id": "KOR/1", "typ": "KOREKTA", "suma_netto": "-100.00", "suma_vat": "-23.00", "suma_brutto": "-123.00",
    "pozycje": [pz(-1, "100", "-100.00", "-23.00", "-123.00")]}
SUMA_ZEROWA = {
    "id": "Z/0", "typ": "FV", "suma_netto": "0.00", "suma_vat": "0.00", "suma_brutto": "0.00",
    "pozycje": [pz(1, "50", "50.00", "11.50", "61.50"), pz(-1, "50", "-50.00", "-11.50", "-61.50")]}


class TestSprawdzDokumentUjemne(unittest.TestCase):
    def test_domyslnie_w_bibliotece_blad(self):
        w = sprawdz_dokument(KOREKTA_UJEMNA)
        self.assertEqual((w["status"], w["blad"]["kod"], w["blad"]["etap"]), ("blad", bledy.ILOSC_UJEMNA, "obliczenia"))

    def test_z_opcja_dokumenty_ujemne_sa_spojne(self):
        for dok in (FAKTURA_Z_RABATEM, KOREKTA_UJEMNA, SUMA_ZEROWA):
            with self.subTest(id=dok["id"]):
                w = sprawdz_dokument(dok, dopusc_ujemne=True)
                self.assertEqual((w["status"], w["blad"], w["niespojnosci"], w["przyczyny"]), ("spojny", None, [], []))
                self.assertEqual(w["tryb_pasujacy"], "oba")

    def test_suma_zerowa_nie_jest_naglowkiem_zero(self):
        w = sprawdz_dokument(SUMA_ZEROWA, dopusc_ujemne=True)
        self.assertNotIn(bledy.NAGLOWEK_ZERO, {p["kod"] for p in w["przyczyny"]})

    def test_blad_w_ujemnym_dokumencie_jest_wykrywany(self):
        d = json.loads(json.dumps(FAKTURA_Z_RABATEM))
        d["suma_netto"] = "100.00"      # rabat pominięty w nagłówku
        w = sprawdz_dokument(d, dopusc_ujemne=True)
        kody = {p["kod"] for p in w["przyczyny"]}
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.NAGLOWEK_WYZSZY, kody)
        p = [x for x in w["przyczyny"] if x["kod"] == bledy.NAGLOWEK_WYZSZY][0]
        self.assertEqual(p["roznica"], D("10.00"))
        self.assertEqual([m["indeks"] for m in p["mozliwe_pozycje"]], [1])   # linia rabatowa (moduł 10,00)

    def test_ilosc_x_cena_dla_ujemnej_linii(self):
        d = json.loads(json.dumps(KOREKTA_UJEMNA))
        d["pozycje"][0]["ilosc"] = -2
        w = sprawdz_dokument(d, dopusc_ujemne=True)
        self.assertIn(bledy.ILOSC_X_CENA, {p["kod"] for p in w["przyczyny"]})

    def test_polgrosz_dla_ujemnych(self):
        d = json.loads(json.dumps(KOREKTA_UJEMNA))
        d["suma_brutto"] = "-123.005"
        w = sprawdz_dokument(d, dopusc_ujemne=True)
        self.assertEqual(w["status"], "drobiazg")

    def test_partia(self):
        wyniki, p = sprawdz_partie([FAKTURA_Z_RABATEM, KOREKTA_UJEMNA, SUMA_ZEROWA], dopusc_ujemne=True)
        self.assertEqual((p["spojne"], p["z_bledem"]), (3, 0))
        _, p2 = sprawdz_partie([FAKTURA_Z_RABATEM, KOREKTA_UJEMNA, SUMA_ZEROWA])
        self.assertEqual((p2["spojne"], p2["z_bledem"]), (0, 3))     # wszystkie mają ujemną linię


class TestCliUjemne(unittest.TestCase):
    def uruchom(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                kod = main(list(argv))
            except SystemExit as e:
                kod = e.code
        return kod, out.getvalue()

    def plik(self, tmp, dokumenty):
        sciezka = os.path.join(tmp, "d.json")
        with open(sciezka, "w", encoding="utf-8") as f:
            json.dump(dokumenty, f)
        return sciezka

    def test_domyslnie_dopuszcza_ujemne(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.plik(tmp, [FAKTURA_Z_RABATEM, KOREKTA_UJEMNA, SUMA_ZEROWA])
            kod, out = self.uruchom(p)
            self.assertEqual(kod, 0, out)
            self.assertIn("Bez uwag: 3 z 3 dokumentów", out)

    def test_flaga_jawna_i_wylaczenie(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.plik(tmp, [KOREKTA_UJEMNA])
            self.assertEqual(self.uruchom(p, "--dopusc-ujemne")[0], 0)
            kod, out = self.uruchom(p, "--nie-dopuszczaj-ujemnych")
            self.assertEqual(kod, 1)
            self.assertIn("ILOSC_UJEMNA", out)
            wyj = os.path.join(tmp, "w.json")
            self.uruchom(p, "--nie-dopuszczaj-ujemnych", "--json", wyj)
            with open(wyj, encoding="utf-8") as f:
                self.assertEqual(json.load(f)[0]["blad"]["kod"], "ILOSC_UJEMNA")

    def test_pomin_typy_korekta_nadal_dziala_razem_z_ujemnymi(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.plik(tmp, [KOREKTA_UJEMNA, FAKTURA_Z_RABATEM])
            kod, out = self.uruchom(p, "--pomin-typy", "KOREKTA", "--nie-dopuszczaj-ujemnych")
            self.assertEqual(kod, 1)       # faktura z ujemną linią, a ujemne wyłączone
            self.assertIn("Pominięte typy (KOREKTA): 1", out)

    def test_csv_i_json_dla_dokumentu_ujemnego_z_bledem_danych(self):
        d = json.loads(json.dumps(KOREKTA_UJEMNA))
        d["suma_brutto"] = "-123.50"
        with tempfile.TemporaryDirectory() as tmp:
            p = self.plik(tmp, [d])
            wyj = os.path.join(tmp, "w.csv")
            kod, out = self.uruchom(p, "--csv", wyj)
            self.assertEqual(kod, 1)
            with open(wyj, encoding="utf-8-sig") as f:
                tekst = f.read()
            self.assertIn("KOR/1;KOREKTA;niespojny;", tekst)
            self.assertIn(";0,50;", tekst)           # największa różnica jako moduł, z przecinkiem
