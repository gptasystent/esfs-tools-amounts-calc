"""Skaner kodu: wzorce (trafia / nie trafia), wyłączenia, raport JSON/CSV, grupowanie po modułach, szybkość."""
import contextlib
import csv
import io
import json
import os
import tempfile
import time
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc import skan_kodu as sk
from amounts_calc.skan_kodu import KODY, main, skanuj, skanuj_tekst
from tests.skan_przyklady import DOBRE, ZLE


def kody(tekst, jezyk, **kw):
    return {z.kod for z in skanuj_tekst(tekst, "x", jezyk, **kw)}


def uruchom(argumenty):
    wyjscie, blad = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(wyjscie), contextlib.redirect_stderr(blad):
        try:
            kod = main(argumenty)
        except SystemExit as e:
            kod = e.code
    return kod, wyjscie.getvalue(), blad.getvalue()


class TestWzorce(unittest.TestCase):
    def test_zle_fragmenty_trafiaja_w_oczekiwane_kody(self):
        for nazwa, jezyk, kod, oczekiwane in ZLE:
            with self.subTest(nazwa):
                self.assertEqual(kody(kod, jezyk), oczekiwane)

    def test_dobre_fragmenty_nie_daja_znalezisk(self):
        for nazwa, jezyk, kod in DOBRE:
            with self.subTest(nazwa):
                self.assertEqual(skanuj_tekst(kod, "x", jezyk), [])

    def test_precyzja_i_czulosc_na_wlasnych_przykladach(self):
        tp = fp = fn = 0
        for _, jezyk, kod, oczekiwane in ZLE:
            znalezione = kody(kod, jezyk)
            tp += len(znalezione & oczekiwane)
            fp += len(znalezione - oczekiwane)
            fn += len(oczekiwane - znalezione)
        fp_dobre = sum(len(skanuj_tekst(kod, "x", jezyk)) for _, jezyk, kod in DOBRE)
        precyzja = tp / (tp + fp + fp_dobre)
        czulosc = tp / (tp + fn)
        self.assertGreaterEqual(precyzja, 0.95)
        self.assertGreaterEqual(czulosc, 0.95)
        self.assertEqual(fp_dobre, 0)

    def test_kazdy_kod_ma_przynajmniej_dwa_zle_i_ma_opis(self):
        for kod, (waznosc, opis, podpowiedz) in KODY.items():
            with self.subTest(kod):
                self.assertIn(waznosc, sk.WAZNOSCI)
                self.assertTrue(opis and podpowiedz)
                self.assertGreaterEqual(sum(1 for z in ZLE if kod in z[3]), 2)

    def test_jest_co_najmniej_jedenascie_kodow_i_siedem_wzorcow(self):
        self.assertEqual(len(KODY), 11)

    def test_waznosci(self):
        w = {z.kod: z.waznosc for z in skanuj_tekst("b = n * 1.23\nf = float(netto)\nx = '23%' # stawka vat\n", "x", "py")}
        self.assertEqual(w, {"VAT_MNOZENIE_BEZ_ZAOKRAGLENIA": "wysoka", "FLOAT_W_FUNKCJI_KWOTOWEJ": "srednia"})
        w = {z.kod: z.waznosc for z in skanuj_tekst("stawka = '23%'\ndef suma_x(): pass\n", "x", "py")}
        self.assertEqual(w, {"STAWKA_VAT_TEKSTOWA": "niska", "FUNKCJA_POZA_ZRODLEM_PRAWDY": "niska"})

    def test_js_toFixed_zwykle_vs_parseFloat(self):
        w = {z.linia: z.waznosc for z in skanuj_tekst("a = cena.toFixed(2);\nb = parseFloat(cena.toFixed(2));\n", "x", "ts")}
        self.assertEqual(w, {1: "srednia", 2: "wysoka"})


class TestKontekst(unittest.TestCase):
    def test_numery_linii_i_wieloliniowe_instrukcje(self):
        tekst = "a = 1\nb = 2\nx = (\n    netto\n    * 1.23\n)\n"
        z = skanuj_tekst(tekst, "x", "py")
        self.assertEqual([(i.linia, i.kod) for i in z], [(5, "VAT_MNOZENIE_BEZ_ZAOKRAGLENIA")])

    def test_zaokraglenie_w_tej_samej_instrukcji_zdejmuje_znalezisko(self):
        self.assertEqual(kody("v = round(\n    netto * 0.23,\n    2)\n", "py"), {"ROUND_PYTHON_BANKOWE"})
        self.assertEqual(kody("v = (netto * 0.23).quantize(D('0.01'), rounding=ROUND_HALF_UP)\n", "py"), set())

    def test_sql_w_potrojnym_tekscie_pythona_ma_numery_linii_pliku(self):
        tekst = 'x = 1\nzapytanie = """\nSELECT\n  SUM(wartosc_brutto),\n  SUM(wartosc_netto)\nFROM p\n"""\n'
        z = skanuj_tekst(tekst, "x", "py")
        self.assertEqual([(i.linia, i.kod) for i in z], [(4, "SUMOWANIE_NIESPOJNE")])

    def test_docstring_to_komentarz_ale_przypisany_potrojny_tekst_nie(self):
        self.assertEqual(kody('def f():\n    """brutto = netto * 1.23"""\n', "py", zrodlo_prawdy=("f",)), set())
        self.assertEqual(kody('q = """SELECT netto * 1.23 FROM p"""\n', "py"), {"VAT_MNOZENIE_BEZ_ZAOKRAGLENIA"})

    def test_wyrazenie_w_f_stringu_i_template_literal(self):
        self.assertEqual(kody('t = f"{brutto / 1.23}"\n', "py"), {"NETTO_Z_BRUTTO_DZIELENIE"})
        self.assertEqual(kody("const t = `${netto * 1.23}`;\n", "ts"), {"VAT_MNOZENIE_BEZ_ZAOKRAGLENIA"})
        self.assertEqual(kody("const u = `/api/1.23/${id}`;\n", "ts"), set())

    def test_kolejne_instrukcje_nie_zlewaja_sie(self):
        # zaokrąglenie w następnej instrukcji nie zdejmuje znaleziska z poprzedniej
        self.assertEqual(kody("a = netto * 1.23\nb = round(x, 2)\n", "py"), {"VAT_MNOZENIE_BEZ_ZAOKRAGLENIA"})

    def test_crlf_i_cr(self):
        z = skanuj_tekst("a = 1\r\nb = netto * 1.23\r\n".replace("\r\n", "\n"), "x", "py")
        self.assertEqual([i.linia for i in z], [2])

    def test_fragment_do_160_znakow(self):
        dlugi = "wartosc_brutto = netto * 1.23 + " + " + ".join(["pole%d" % i for i in range(60)])
        z = skanuj_tekst(dlugi + "\n", "x", "py")[0]
        self.assertLessEqual(len(z.fragment), 160)
        self.assertTrue(z.fragment.endswith("…"))
        krotki = skanuj_tekst("  b   =  netto  *  1.23   \n", "x", "py")[0]
        self.assertEqual(krotki.fragment, "b = netto * 1.23")


class TestWylaczenia(unittest.TestCase):
    def test_marker_w_roznych_miejscach(self):
        przypadki = [
            ("py", "b = n * 1.23  # kwoty-ok: powód\n"),
            ("py", "# kwoty-ok: powód\nb = n * 1.23\n"),
            ("py", "b = (\n    n * 1.23  # kwoty-ok: powód\n)\n"),
            ("ts", "const b = n * 1.23; // kwoty-ok: powód\n"),
            ("ts", "// kwoty-ok: powód\nconst b = n * 1.23;\n"),
            ("ts", "/* kwoty-ok: powód */ const b = n * 1.23;\n"),
            ("sql", "SELECT n * 1.23 FROM p; -- kwoty-ok: powód\n"),
            ("sql", "-- kwoty-ok: powód\nSELECT n * 1.23 FROM p;\n"),
            ("py", "# KWOTY-OK : raport\nb = n * 1.23\n"),
        ]
        for jezyk, tekst in przypadki:
            with self.subTest(tekst):
                self.assertEqual(skanuj_tekst(tekst, "x", jezyk), [])

    def test_marker_dziala_tylko_na_swoja_linie(self):
        z = skanuj_tekst("a = n * 1.23  # kwoty-ok: x\nb = n * 1.23\n", "x", "py")
        self.assertEqual([i.linia for i in z], [2])
        z = skanuj_tekst("# kwoty-ok: x\n\nb = n * 1.23\n", "x", "py")      # pusta linia przerywa
        self.assertEqual([i.linia for i in z], [3])
        z = skanuj_tekst("c = 1  # kwoty-ok: x\nb = n * 1.23\n", "x", "py")  # komentarz przy kodzie nie obejmuje następnej
        self.assertEqual([i.linia for i in z], [2])

    def test_marker_w_tekscie_nie_dziala(self):
        z = skanuj_tekst("opis = 'kwoty-ok: nie'; b = n * 1.23\n", "x", "py")
        self.assertEqual(len(z), 1)

    def test_zrodlo_prawdy_cialo_jest_pomijane_a_inne_funkcje_nie(self):
        tekst = ("def kwoty_pozycji(w, stawka):\n    vat = w * stawka / 100\n    return w, vat, w + vat\n\n"
                 "def inna(w, stawka):\n    return w * stawka / 100\n")
        z = skanuj_tekst(tekst, "x", "py")
        self.assertEqual([(i.linia, i.kod) for i in z], [(6, "VAT_MNOZENIE_BEZ_ZAOKRAGLENIA")])
        z = skanuj_tekst(tekst, "x", "py", zrodlo_prawdy=("kwoty_pozycji", "inna"))
        self.assertEqual(z, [])

    def test_zrodlo_prawdy_ts(self):
        tekst = "export function kwotyPozycji(w: number, stawka: number) {\n  const vat = w * stawka / 100;\n  return vat;\n}\n"
        self.assertEqual(skanuj_tekst(tekst, "x", "ts", zrodlo_prawdy=("kwoty_pozycji",)), [])
        self.assertNotEqual(skanuj_tekst(tekst, "x", "ts", zrodlo_prawdy=("inna",)), [])

    def test_wywolanie_zrodla_prawdy_w_zapisie(self):
        self.assertEqual(kody("p.wartosc_brutto = moja_funkcja(p.wartosc_netto) + 1\n", "py"),
                         {"BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI"})
        self.assertEqual(kody("p.wartosc_brutto = moja_funkcja(p.wartosc_netto) + 1\n", "py",
                              zrodlo_prawdy=("moja_funkcja",)), set())


class TestPliki(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.korzen = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.pliki = {
            "routes/faktury.py": "from flask import Blueprint\n\ndef policz(netto):\n    return netto * 1.23\n",
            "routes/ok.py": "netto, vat, brutto = kwoty_pozycji(w, m)\n",
            "utils/kwoty.py": "def suma_pozycji(p):\n    return sum(x.netto for x in p)\n\nbrutto = round(netto, 1)\n",
            "frontend/pages/Faktura.tsx": "export const A = () => <b>{(netto * 1.23).toFixed(2)}</b>;\n",
            "db/migracje/001.sql": "UPDATE pozycje SET wartosc_brutto = netto + vat;\n+ netto * 1.23;\n",
            "node_modules/x/index.js": "const b = netto * 1.23;\n",
            "frontend/app.min.js": "var b=netto*1.23;\n",
            "tests/test_x.py": "b = netto * 1.23\n",
            "README.md": "netto * 1.23\n",
            "korzen.py": "b = netto * 1.23\n",
        }
        for sciezka, tresc in self.pliki.items():
            pelna = os.path.join(self.korzen, sciezka)
            os.makedirs(os.path.dirname(pelna), exist_ok=True)
            with open(pelna, "w", encoding="utf-8", newline="") as f:
                f.write(tresc)

    def test_skanowanie_katalogu_grupuje_po_modulach(self):
        znaleziska, stat = skanuj([self.korzen])
        moduly = {}
        for z in znaleziska:
            moduly.setdefault(sk.modul(z.plik), set()).add(z.plik)
        self.assertEqual(sorted(moduly), ["(korzeń)", "db/migracje", "frontend/pages", "routes", "tests", "utils"])
        self.assertEqual(moduly["routes"], {"routes/faktury.py"})
        self.assertNotIn("node_modules", " ".join(z.plik for z in znaleziska))
        self.assertNotIn("app.min.js", " ".join(z.plik for z in znaleziska))
        self.assertEqual(stat["plikow"], 7)             # .md pominięty z rozszerzenia, node_modules bez wejścia
        self.assertEqual(stat["pominietych"], 1)        # *.min.js

    def test_pomin_glob(self):
        znaleziska, _ = skanuj([self.korzen], pomin=["tests/*", "test_*.py", "utils"])
        pliki = {z.plik for z in znaleziska}
        self.assertNotIn("tests/test_x.py", pliki)
        self.assertNotIn("utils/kwoty.py", pliki)
        self.assertIn("routes/faktury.py", pliki)
        znaleziska, _ = skanuj([self.korzen], pomin=["*.tsx", "korzen.py"])
        self.assertFalse({"frontend/pages/Faktura.tsx", "korzen.py"} & {z.plik for z in znaleziska})

    def test_raport_tekstowy_i_kod_wyjscia(self):
        kod, wyjscie, _ = uruchom([self.korzen])
        self.assertEqual(kod, 1)
        self.assertIn("== routes (1) ==", wyjscie)
        self.assertIn("routes/faktury.py:4  VAT_MNOZENIE_BEZ_ZAOKRAGLENIA [wysoka]  return netto * 1.23", wyjscie)
        self.assertIn("Jak poprawić (wg kodu):", wyjscie)
        kod, wyjscie, _ = uruchom([os.path.join(self.korzen, "routes", "ok.py")])
        self.assertEqual((kod, "Brak znalezisk." in wyjscie), (0, True))

    def test_blad_wejscia(self):
        kod, _, blad = uruchom([os.path.join(self.korzen, "nie_ma")])
        self.assertEqual(kod, 2)
        self.assertIn("brak ścieżki", blad)

    def test_json(self):
        wyj = os.path.join(self.korzen, "w.json")
        uruchom([self.korzen, "--json", wyj, "--pomin", "w.json"])
        with open(wyj, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["podsumowanie"]["znalezisk"], len(d["znaleziska"]))
        z = [x for x in d["znaleziska"] if x["plik"] == "routes/faktury.py"][0]
        self.assertEqual(set(z), {"plik", "linia", "kod", "waznosc", "modul", "fragment", "podpowiedz"})
        self.assertEqual((z["linia"], z["modul"], z["waznosc"]), (4, "routes", "wysoka"))
        self.assertIn("kwoty_pozycji", z["podpowiedz"])
        self.assertEqual(sum(d["podsumowanie"]["wg_modulu"].values()), d["podsumowanie"]["znalezisk"])

    def test_csv(self):
        wyj = os.path.join(self.korzen, "w.csv")
        uruchom([self.korzen, "--csv", wyj])
        with open(wyj, "rb") as f:
            surowe = f.read()
        self.assertTrue(surowe.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", surowe)
        wiersze = list(csv.reader(io.StringIO(surowe.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(tuple(wiersze[0]), sk.KOLUMNY_CSV)
        self.assertTrue(all(len(w) == len(sk.KOLUMNY_CSV) for w in wiersze))
        fragmenty = [dict(zip(sk.KOLUMNY_CSV, w))["fragment"] for w in wiersze[1:]]
        self.assertIn("'+ netto * 1.23;", fragmenty)            # ochrona przed formułą w arkuszu
        waznosci = [w[3] for w in wiersze[1:]]
        self.assertEqual(waznosci, sorted(waznosci, key=sk.WAZNOSCI.index))

    def test_filtr_waznosci(self):
        kod, wyjscie, _ = uruchom([self.korzen, "--waznosc", "wysoka"])
        self.assertNotIn("FUNKCJA_POZA_ZRODLEM_PRAWDY", wyjscie)
        self.assertIn("VAT_MNOZENIE_BEZ_ZAOKRAGLENIA", wyjscie)

    def test_zrodlo_prawdy_z_pliku(self):
        lista = os.path.join(self.korzen, "zrodlo.txt")
        with open(lista, "w", encoding="utf-8") as f:
            f.write("# funkcje dozwolone\nsuma_pozycji   # wspólna suma\n\n")
        znaleziska, _ = skanuj([os.path.join(self.korzen, "utils")])
        self.assertIn("FUNKCJA_POZA_ZRODLEM_PRAWDY", {z.kod for z in znaleziska})
        kod, wyjscie, _ = uruchom([os.path.join(self.korzen, "utils"), "--zrodlo-prawdy", lista])
        self.assertNotIn("FUNKCJA_POZA_ZRODLEM_PRAWDY", wyjscie)
        self.assertEqual(sk.wczytaj_zrodlo_prawdy(lista), ("suma_pozycji",))
        kod, _, blad = uruchom([self.korzen, "--zrodlo-prawdy", os.path.join(self.korzen, "brak.txt")])
        self.assertEqual(kod, 2)

    def test_pliki_crlf(self):
        pelna = os.path.join(self.korzen, "crlf.py")
        with open(pelna, "wb") as f:
            f.write(b"a = 1\r\nb = netto * 1.23\r\n")
        znaleziska, _ = skanuj([pelna])
        self.assertEqual([(z.linia, z.kod) for z in znaleziska], [(2, "VAT_MNOZENIE_BEZ_ZAOKRAGLENIA")])

    def test_binarne_i_dziwne_kodowanie_nie_wywracaja(self):
        pelna = os.path.join(self.korzen, "zly.py")
        with open(pelna, "wb") as f:
            f.write(b"x = '\xff\xfe'\nb = netto * 1.23\n\x00\x01")
        znaleziska, _ = skanuj([pelna])
        self.assertEqual(len(znaleziska), 1)

    def test_szybkosc_na_kilkuset_plikach(self):
        for i in range(400):
            sciezka = os.path.join(self.korzen, "duzo", "m%d" % (i % 10), "plik%d.py" % i)
            os.makedirs(os.path.dirname(sciezka), exist_ok=True)
            with open(sciezka, "w", encoding="utf-8") as f:
                f.write("\n".join("def funkcja_%d(a, b):\n    x = a + b * %d\n    return round(x, 2)  # %s"
                                  % (j, j, "komentarz") for j in range(60)))
        start = time.time()
        znaleziska, stat = skanuj([os.path.join(self.korzen, "duzo")])
        self.assertLess(time.time() - start, 15)
        self.assertEqual((stat["plikow"], znaleziska), (400, []))


class TestWlasnyKod(unittest.TestCase):
    def test_pakiet_amounts_calc_nie_ma_znalezisk_o_wysokiej_waznosci(self):
        korzen = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "amounts_calc")
        znaleziska, _ = skanuj([korzen], pomin=["skan_kodu.py"])
        self.assertEqual([z for z in znaleziska if z.waznosc == "wysoka"], [])


if __name__ == "__main__":
    unittest.main()
