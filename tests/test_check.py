import contextlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, oblicz, Pozycja
from amounts_calc.adapter import wczytaj_json
from amounts_calc.check import (main, ma_problem, sprawdz_dokument, sprawdz_partie, tekst_podsumowania)
from amounts_calc.config import VAT_PER_POZYCJA, VAT_PER_STAWKA


def poz(ilosc, cena, netto, vat, brutto, stawka=23, **extra):
    d = {"ilosc": ilosc, "cena_netto_jedn": cena, "stawka_vat": stawka, "netto": netto, "vat": vat, "brutto": brutto}
    d.update(extra)
    return d


def dok_trzy_033(vat_pozycji, suma_vat, suma_brutto, id="D"):
    return {"id": id, "suma_netto": "0.99", "suma_vat": suma_vat, "suma_brutto": suma_brutto,
            "pozycje": [poz(1, "0.33", "0.33", v, str(D("0.33") + D(v))) for v in vat_pozycji]}


class TestSprawdzDokument(unittest.TestCase):
    def test_per_stawka_dokument(self):
        w = sprawdz_dokument(dok_trzy_033(["0.07", "0.08", "0.08"], "0.23", "1.22"))
        self.assertEqual(w["niespojnosci"], [])
        self.assertIsNone(w["blad"])
        self.assertEqual(w["tryb_pasujacy"], "per_stawka")
        self.assertEqual(w["pasuje"], {VAT_PER_STAWKA: True, VAT_PER_POZYCJA: False})
        self.assertFalse(ma_problem(w))

    def test_per_pozycja_dokument(self):
        d = dok_trzy_033(["0.08"] * 3, "0.24", "1.23")
        w = sprawdz_dokument(d, tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual(w["tryb_pasujacy"], "per_pozycja")
        self.assertEqual(w["niespojnosci"], [])
        self.assertEqual(w["liczba_roznic_pozycji"][VAT_PER_POZYCJA], 0)
        # przy założeniu per_stawka ten sam dokument ma niespójność VAT stawki
        w2 = sprawdz_dokument(d, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual([n["kod"] for n in w2["niespojnosci"]], [bledy.VAT_STAWKI_ROZNY_OD_SUMY])
        self.assertTrue(ma_problem(w2))

    def test_oba_tryby_pasuja(self):
        d = {"id": 1, "suma_netto": "10.00", "suma_vat": "2.30", "suma_brutto": "12.30",
             "pozycje": [poz(1, "10", "10.00", "2.30", "12.30")]}
        self.assertEqual(sprawdz_dokument(d)["tryb_pasujacy"], "oba")

    def test_zaden_tryb_nie_pasuje(self):
        d = {"id": 1, "suma_netto": "10.00", "suma_vat": "2.00", "suma_brutto": "12.00",
             "pozycje": [poz(1, "10", "10.00", "2.00", "12.00")]}
        w = sprawdz_dokument(d)
        self.assertEqual(w["tryb_pasujacy"], "zaden")
        self.assertEqual(w["niespojnosci"][0]["kod"], bledy.VAT_STAWKI_ROZNY_OD_SUMY)
        self.assertEqual(w["max_roznica"], D("0.30"))
        self.assertTrue(ma_problem(w))
        r = {x["pole"]: x for x in w["rozbieznosci"][VAT_PER_STAWKA]}
        self.assertEqual((r["suma_vat"]["zapisane"], r["suma_vat"]["biblioteka"], r["suma_vat"]["roznica"]),
                         (D("2.00"), D("2.30"), D("0.30")))

    def test_niespojna_suma_zapisana(self):
        d = dok_trzy_033(["0.07", "0.08", "0.08"], "0.23", "1.22")
        d["suma_brutto"] = "1.23"
        w = sprawdz_dokument(d)
        kody = {n["kod"] for n in w["niespojnosci"]}
        self.assertIn(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, kody)
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody)
        self.assertEqual(w["max_roznica"], D("0.01"))

    def test_liczby_json_nigdy_float(self):
        # 0.1 + 0.2 w float = 0.30000000000000004; z Decimal dokument jest spójny
        tekst = ('{"id": "F", "suma_netto": 0.3, "suma_vat": 0, "suma_brutto": 0.3, "pozycje": ['
                 '{"ilosc": 1, "cena_netto_jedn": 0.1, "stawka_vat": "zw", "netto": 0.1, "vat": 0, "brutto": 0.1},'
                 '{"ilosc": 1, "cena_netto_jedn": 0.2, "stawka_vat": "zw", "netto": 0.2, "vat": 0, "brutto": 0.2}]}')
        w = sprawdz_dokument(wczytaj_json(tekst))
        self.assertEqual(w["niespojnosci"], [])
        self.assertEqual(w["tryb_pasujacy"], "oba")

    def test_przecinek_i_stringi(self):
        d = {"id": "S", "suma_netto": "10,00", "suma_vat": "2,30", "suma_brutto": "12,30",
             "pozycje": [poz("1", "10,00", "10,00", "2,30", "12,30", "23")]}
        self.assertEqual(sprawdz_dokument(d)["tryb_pasujacy"], "oba")

    def test_tryb_brutto_i_rabat_dokumentu(self):
        d = {"id": "B", "tryb": "brutto", "rabat_dokumentu_proc": 50, "suma_netto": "50.00", "suma_vat": "11.50",
             "suma_brutto": "61.50",
             "pozycje": [{"ilosc": 1, "cena_brutto_jedn": "123.00", "stawka_vat": 23, "netto": "50.00",
                          "vat": "11.50", "brutto": "61.50"}]}
        w = sprawdz_dokument(d)
        self.assertEqual((w["blad"], w["niespojnosci"], w["tryb_pasujacy"]), (None, [], "oba"))

    def test_pozycje_bez_kwot_porownuja_tylko_sumy(self):
        d = {"id": "P", "suma_netto": "20.00", "suma_vat": "4.60", "suma_brutto": "24.60",
             "pozycje": [{"ilosc": 2, "cena_netto_jedn": "10", "stawka_vat": 23}]}
        w = sprawdz_dokument(d)
        self.assertTrue(w["pominieto_pozycje"])
        self.assertEqual((w["blad"], w["niespojnosci"], w["tryb_pasujacy"]), (None, [], "oba"))
        d["suma_vat"] = "4.61"
        w = sprawdz_dokument(d)
        self.assertEqual(w["tryb_pasujacy"], "zaden")

    def test_czesciowe_kwoty_pozycji_to_blad(self):
        d = {"id": "P", "suma_netto": "1", "suma_vat": "0", "suma_brutto": "1",
             "pozycje": [poz(1, 1, 1, 0, 1, 0), {"ilosc": 1, "cena_netto_jedn": 1, "stawka_vat": 0}]}
        self.assertEqual(sprawdz_dokument(d)["blad"]["kod"], bledy.BRAK_POLA)

    def test_bledy_nie_rzucaja(self):
        przypadki = {
            "ilosc ujemna": ({"id": 1, "suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                              "pozycje": [poz(-1, 1, 1, 0, 1, 0)]}, bledy.ILOSC_UJEMNA, "obliczenia"),
            "rabat": ({"id": 1, "suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [poz(1, 1, 1, 0, 1, 0, rabat_proc=101)]}, bledy.RABAT_POZA_ZAKRESEM, "obliczenia"),
            "stawka": ({"id": 1, "suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                        "pozycje": [poz(1, 1, 1, 0, 1, 7)]}, bledy.NIEZNANA_STAWKA, "wejscie"),
            "brak sumy": ({"id": 1, "suma_netto": 1, "suma_vat": 0, "pozycje": []}, bledy.BRAK_POLA, "wejscie"),
            "nie slownik": ("tekst", bledy.NIEPOPRAWNA_STRUKTURA, "wejscie"),
            "smieci w kwocie": ({"id": 1, "suma_netto": "abc", "suma_vat": 0, "suma_brutto": 1, "pozycje": []},
                                bledy.NIEPOPRAWNA_LICZBA, "wejscie"),
            "ogromna liczba": ({"id": 1, "suma_netto": "1E+999", "suma_vat": 0, "suma_brutto": 0,
                                "pozycje": [poz(1, "1E+999", "1E+999", 0, "1E+999", 0)]}, bledy.NIEPOPRAWNA_LICZBA, None),
        }
        for nazwa, (dok, kod, etap) in przypadki.items():
            with self.subTest(nazwa):
                w = sprawdz_dokument(dok)
                self.assertEqual(w["blad"]["kod"], kod)
                if etap:
                    self.assertEqual(w["blad"]["etap"], etap)
                self.assertTrue(ma_problem(w))

    def test_niespojnosci_zachowane_gdy_oblicz_zawiedzie(self):
        d = {"id": 1, "suma_netto": 1, "suma_vat": 0, "suma_brutto": 5, "pozycje": [poz(-1, 1, 1, 0, 1, 0)]}
        w = sprawdz_dokument(d)
        self.assertEqual(w["blad"]["etap"], "obliczenia")
        self.assertTrue(w["niespojnosci"])

    def test_id_bez_zmian(self):
        for id_ in ("FV/1", 7, None, True, ["a", 1], {"k": "v"}, D("1.5"), "zażółć"):
            with self.subTest(id=id_):
                d = {"id": id_, "suma_netto": 0, "suma_vat": 0, "suma_brutto": 0, "pozycje": []}
                w = sprawdz_dokument(d)
                self.assertEqual(w["id"], id_)
                self.assertIs(type(w["id"]), type(id_))


class TestPartia(unittest.TestCase):
    def test_podsumowanie_i_kody(self):
        dokumenty = [
            dok_trzy_033(["0.07", "0.08", "0.08"], "0.23", "1.22", id="ok"),
            dok_trzy_033(["0.08"] * 3, "0.24", "1.23", id="per_poz"),
            {"id": "zly", "suma_netto": 1, "suma_vat": 0, "suma_brutto": 1, "pozycje": [poz(-1, 1, 1, 0, 1, 0)]},
            17,
        ]
        wyniki, p = sprawdz_partie(dokumenty)
        self.assertEqual(p["liczba_dokumentow"], 4)
        self.assertEqual(p["z_bledem"], 2)
        self.assertEqual(p["porownanych"], 2)
        self.assertEqual(p["pasuje_per_stawka"], 1)
        self.assertEqual(p["pasuje_per_pozycja"], 1)
        self.assertEqual(p["dopasowanie"], {"oba": 0, "per_stawka": 1, "per_pozycja": 1, "zaden": 0})
        self.assertEqual(p["kody"][bledy.ILOSC_UJEMNA], 1)
        self.assertEqual(p["kody"][bledy.NIEPOPRAWNA_STRUKTURA], 1)
        self.assertEqual(p["kody"][bledy.VAT_STAWKI_ROZNY_OD_SUMY], 1)   # per_poz przy założeniu per_stawka
        self.assertEqual(p["spojne"], 1)
        self.assertEqual([w["indeks"] for w in wyniki], [0, 1, 2, 3])

    def test_wlasciwosc_zgodnosc_z_trybem_uzytym_do_wygenerowania(self):
        rng = random.Random(2468)
        dokumenty = {VAT_PER_STAWKA: [], VAT_PER_POZYCJA: []}
        for tv in dokumenty:
            for n in range(150):
                tryb = rng.choice(("netto", "brutto"))
                pole = "cena_netto_jedn" if tryb == "netto" else "cena_brutto_jedn"
                wej = [{"ilosc": D(rng.randint(1, 3000)) / 10, pole: D(rng.randint(1, 200000)) / 1000,
                        "rabat_proc": D(rng.randint(0, 3000)) / 100 if rng.random() < .3 else 0,
                        "stawka_vat": rng.choice((23, 8, 5, 0, "zw", "np"))} for _ in range(rng.randint(1, 12))]
                w = oblicz(wej, tryb=tryb, tryb_vat=tv)
                dok = {"id": "%s-%d" % (tv, n), "tryb": tryb, "suma_netto": w.suma_netto, "suma_vat": w.suma_vat,
                       "suma_brutto": w.suma_brutto,
                       "pozycje": [dict(e, netto=r.netto, vat=r.vat, brutto=r.brutto) for e, r in zip(wej, w.pozycje)]}
                dokumenty[tv].append(dok)
        for tv, docs in dokumenty.items():
            wyniki, p = sprawdz_partie(docs, tryb_vat=tv)
            self.assertEqual(p["z_bledem"], 0, tv)
            self.assertEqual(p["z_niespojnosciami"], 0, tv)
            self.assertEqual(p["spojne"], len(docs))
            self.assertEqual(p["dopasowanie"]["zaden"], 0, tv)
            klucz = "pasuje_" + tv
            self.assertEqual(p[klucz], len(docs), tv)
            for w in wyniki:   # także różnice pozycyjne: ten sam tryb => zero
                self.assertEqual(w["liczba_roznic_pozycji"][tv], 0)

    def test_tekst_podsumowania(self):
        wyniki, p = sprawdz_partie([dok_trzy_033(["0.08"] * 3, "0.24", "1.23", id="X1")])
        t = tekst_podsumowania(p, wyniki, 5)
        for fragment in ("Sprawdzono dokumentów: 1", "VAT_STAWKI_ROZNY_OD_SUMY", "pasuje per_pozycja: 1",
                         "pasuje per_stawka:  0", "id=X1", "0.01 (1 gr)"):
            self.assertIn(fragment, t)

    def test_max_przyklady_ogranicza_liste(self):
        dokumenty = [dok_trzy_033(["0.08"] * 3, "0.24", "1.23", id="d%d" % i) for i in range(6)]
        wyniki, p = sprawdz_partie(dokumenty)
        t = tekst_podsumowania(p, wyniki, 2)
        self.assertIn("(2 z 6)", t)
        self.assertEqual(t.count("id=d"), 2)
        self.assertIn("(0 z 6)", tekst_podsumowania(p, wyniki, 0))

    def test_zle_mapowanie_od_razu(self):
        with self.assertRaises(bledy.BladWalidacji):
            sprawdz_partie([], mapowanie={"nieznany": "x"})

    def test_mapowanie_w_partii(self):
        m = {"suma_netto": "kwota_netto", "suma_vat": "podatek", "suma_brutto": "razem", "id": "nr_dok",
             "pozycje": "wiersze", "pozycja": {"stawka_vat": "vat_proc", "netto": "wart_n", "vat": "wart_v",
                                              "brutto": "wart_b", "ilosc": "szt", "cena_netto_jedn": "cena"}}
        dok = {"nr_dok": "ZZ/1", "kwota_netto": "10.00", "podatek": "2.30", "razem": "12.30",
               "wiersze": [{"szt": 1, "cena": "10.00", "vat_proc": 23, "wart_n": "10.00", "wart_v": "2.30",
                            "wart_b": "12.30"}]}
        wyniki, p = sprawdz_partie([dok], mapowanie=m)
        self.assertEqual((wyniki[0]["id"], p["spojne"], p["dopasowanie"]["oba"]), ("ZZ/1", 1, 1))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def sciezka(self, nazwa):
        return os.path.join(self.tmp.name, nazwa)

    def zapisz(self, nazwa, obiekt_lub_tekst):
        sciezka = self.sciezka(nazwa)
        tekst = obiekt_lub_tekst if isinstance(obiekt_lub_tekst, str) else json.dumps(obiekt_lub_tekst)
        with open(sciezka, "w", encoding="utf-8", newline="\n") as f:
            f.write(tekst)
        return sciezka

    def uruchom(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                kod = main(list(argv))
            except SystemExit as e:     # argparse
                kod = e.code
        return kod, out.getvalue(), err.getvalue()

    def test_wszystko_ok_kod_0(self):
        p = self.zapisz("d.json", [dok_trzy_033(["0.07", "0.08", "0.08"], "0.23", "1.22")])
        kod, out, _ = self.uruchom(p)
        self.assertEqual(kod, 0)
        self.assertIn("Sprawdzono dokumentów: 1", out)

    def test_problemy_kod_1_i_json(self):
        dokumenty = [dok_trzy_033(["0.07", "0.08", "0.08"], "0.23", "1.22", id="ok"),
                     dok_trzy_033(["0.08"] * 3, "0.24", "1.23", id=42),
                     {"id": "zly", "suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                      "pozycje": [poz(-1, 1, 1, 0, 1, 0)]}]
        p = self.zapisz("d.json", dokumenty)
        wynik = self.sciezka("wynik.json")
        # ujemna ilość jest błędem tylko przy --nie-dopuszczaj-ujemnych (domyślnie CLI ją dopuszcza)
        kod, out, _ = self.uruchom(p, "--json", wynik, "--nie-dopuszczaj-ujemnych")
        self.assertEqual(kod, 1)
        with open(wynik, encoding="utf-8") as f:
            raport = json.load(f)
        self.assertEqual([r["id"] for r in raport], [42, "zly"])          # tylko z problemami, id bez zmian
        self.assertIsInstance(raport[0]["id"], int)
        self.assertEqual(raport[0]["niespojnosci"][0]["kod"], "VAT_STAWKI_ROZNY_OD_SUMY")
        self.assertEqual(raport[0]["niespojnosci"][0]["roznica"], "0.01")   # kwoty jako string
        self.assertEqual(raport[0]["tryb_pasujacy"], "per_pozycja")
        self.assertEqual(raport[1]["blad"]["kod"], "ILOSC_UJEMNA")
        self.assertEqual([r["indeks"] for r in raport], [1, 2])

    def test_tryb_vat_per_pozycja_usuwa_niespojnosc(self):
        p = self.zapisz("d.json", [dok_trzy_033(["0.08"] * 3, "0.24", "1.23")])
        self.assertEqual(self.uruchom(p)[0], 1)
        self.assertEqual(self.uruchom(p, "--tryb-vat", "per_pozycja")[0], 0)
        self.assertEqual(self.uruchom(p, "--tryb-vat", "per_stawka")[0], 1)

    def test_zly_tryb_vat(self):
        p = self.zapisz("d.json", [])
        self.assertEqual(self.uruchom(p, "--tryb-vat", "xx")[0], 2)

    def test_id_dziesietny_zachowany_w_json(self):
        tekst = ('[{"id": 1.50, "suma_netto": 1, "suma_vat": 0, "suma_brutto": 2, "pozycje": []}]')
        p = self.zapisz("d.json", tekst)
        wynik = self.sciezka("w.json")
        self.assertEqual(self.uruchom(p, "--json", wynik)[0], 1)
        with open(wynik, encoding="utf-8") as f:
            surowy = f.read()
        self.assertIn('"id": 1.50', surowy)       # liczba, nie string, z zachowaną precyzją zapisu

    def test_plik_json_utf8_lf(self):
        p = self.zapisz("d.json", [{"id": "zażółć", "suma_netto": 1, "suma_vat": 0, "suma_brutto": 2, "pozycje": []}])
        wynik = self.sciezka("w.json")
        self.uruchom(p, "--json", wynik)
        with open(wynik, "rb") as f:
            surowy = f.read()
        self.assertNotIn(b"\r\n", surowy)
        self.assertIn("zażółć".encode("utf-8"), surowy)

    def test_bledy_wejscia_kod_2(self):
        pusty = self.zapisz("pusty.json", [])
        przypadki = {
            "brak pliku": [self.sciezka("nie_ma.json")],
            "zly json": [self.zapisz("z.json", "[1, 2")],
            "nie lista": [self.zapisz("n.json", {"a": 1})],
            "NaN": [self.zapisz("nan.json", "[NaN]")],
            "zle mapowanie": [pusty, "--mapowanie", self.zapisz("m.json", {"nieznany": "x"})],
            "brak mapowania": [pusty, "--mapowanie", self.sciezka("brak.json")],
            "ujemne max": [pusty, "--max-przyklady", "-1"],
        }
        for nazwa, argv in przypadki.items():
            with self.subTest(nazwa):
                kod, out, err = self.uruchom(*argv)
                self.assertEqual(kod, 2)
                self.assertEqual(out, "")

    def test_mapowanie_z_pliku(self):
        m = self.zapisz("m.json", {"suma_netto": "kwota_netto", "suma_vat": "podatek", "suma_brutto": "razem",
                                   "pozycja": {"stawka_vat": "stawka_proc"}})
        dok = [{"id": 1, "kwota_netto": 10, "podatek": 2.30, "razem": 12.30,
                "pozycje": [{"ilosc": 1, "cena_netto_jedn": 10, "stawka_proc": 23}]}]
        p = self.zapisz("d.json", dok)
        kod, out, _ = self.uruchom(p, "--mapowanie", m)
        self.assertEqual(kod, 0, out)
        self.assertIn("pasuje per_stawka:  1", out)

    def test_plik_z_bom(self):
        sciezka = self.sciezka("bom.json")
        with open(sciezka, "wb") as f:
            f.write(b"\xef\xbb\xbf[]")
        self.assertEqual(self.uruchom(sciezka)[0], 0)

    def test_plik_z_crlf_jak_z_windowsa(self):
        sciezka = self.sciezka("crlf.json")
        tekst = json.dumps([dok_trzy_033(["0.07", "0.08", "0.08"], "0.23", "1.22")], indent=2)
        with open(sciezka, "wb") as f:
            f.write(tekst.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.uruchom(sciezka)[0], 0)

    def test_pusta_lista(self):
        kod, out, _ = self.uruchom(self.zapisz("p.json", []))
        self.assertEqual(kod, 0)
        self.assertIn("Sprawdzono dokumentów: 0", out)
        self.assertIn("(brak)", out)

    def test_python_m(self):
        p = self.zapisz("d.json", [dok_trzy_033(["0.08"] * 3, "0.24", "1.23", id="zażółć")])
        korzen = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-m", "amounts_calc.check", p, "--max-przyklady", "3"], cwd=korzen,
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("id=zażółć", r.stdout)
        self.assertEqual(r.stderr, "")


if __name__ == "__main__":
    unittest.main()
