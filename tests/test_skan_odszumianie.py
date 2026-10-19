"""Odszumianie skanera (runda 9): FLOAT_W_FUNKCJI_KWOTOWEJ, ROUND_PYTHON_BANKOWE, FUNKCJA_POZA_ZRODLEM_PRAWDY,
przełącznik --tryb pelny|istotne i liczby przed / po."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc import skan_kodu as sk
from amounts_calc.skan_kodu import skanuj, skanuj_tekst
from tests.skan_szum import FLOAT, FUNKCJA, ISTOTNE, NADAL_ZNAJDOWANE, ROUND, SZUM


def uruchom(argumenty):
    wyjscie = io.StringIO()
    with contextlib.redirect_stdout(wyjscie), contextlib.redirect_stderr(io.StringIO()):
        kod = sk.main(argumenty)
    return kod, wyjscie.getvalue()


def po(tekst, jezyk, kod):
    """Ważność po odszumieniu znaleziska `kod` (None, gdy nie ma znaleziska albo jest szumem)."""
    wyniki = [z for z in skanuj_tekst(tekst, "x", jezyk) if z.kod == kod]
    assert wyniki, "brak znaleziska %s w %r" % (kod, tekst)
    return wyniki[0].po_odszumieniu


class TestSzumNieTrafia(unittest.TestCase):
    def test_szum_jest_nadal_widoczny_w_trybie_pelnym_ale_odszumiony(self):
        for nazwa, jezyk, kod, szukany, oczekiwane in SZUM:
            with self.subTest(nazwa):
                self.assertEqual(po(kod, jezyk, szukany), oczekiwane)

    def test_istotne_trafiaja(self):
        for nazwa, jezyk, kod, szukany, oczekiwane in ISTOTNE:
            with self.subTest(nazwa):
                self.assertEqual(po(kod, jezyk, szukany), oczekiwane)


class TestPunkt1Float(unittest.TestCase):
    def test_tylko_dzialanie_z_druga_kwota_lub_stawka(self):
        self.assertIsNone(po("x = float(kwota)\n", "py", FLOAT))
        self.assertEqual(po("x = float(netto) + vat\n", "py", FLOAT), "niska")
        self.assertEqual(po("x = float(netto) * stawka\n", "py", FLOAT), "srednia")

    def test_operator_po_prawej_stronie_i_przed(self):
        self.assertEqual(po("x = vat + float(netto)\n", "py", FLOAT), "niska")
        self.assertEqual(po("x = stawka * float(netto)\n", "py", FLOAT), "srednia")
        self.assertIsNone(po("x = -float(kwota)\n", "py", FLOAT))

    def test_sql_float_zostaje_bez_zmian(self):
        z = skanuj_tekst("CREATE TABLE p (wartosc_netto float);\n", "x", "sql")[0]
        self.assertEqual((z.waznosc, z.po_odszumieniu), ("srednia", "srednia"))

    def test_domyslnie_niska_wiec_poza_trybem_istotne(self):
        self.assertEqual(po("s = float(row['netto']) + float(row['vat'])\n", "py", FLOAT), "niska")


class TestPunkt2Round(unittest.TestCase):
    def test_slowa_w_sasiednich_dwoch_liniach(self):
        blisko = "netto = 1\n\nx = round(cena * stawka, 2)\n"
        daleko = "netto = 1\n\n\nx = round(cena / 3, 2)\n"
        self.assertEqual(po(blisko, "py", ROUND), "wysoka")
        self.assertEqual(po(daleko, "py", ROUND), "niska")

    def test_komentarz_nie_liczy_sie_jako_kontekst(self):
        self.assertEqual(po("# netto\nx = round(cena / 3, 2)\n", "py", ROUND), "niska")

    def test_slowa_kluczowe_to_tokeny_nie_podciagi(self):
        self.assertEqual(po("private_cena = round(cena / 3, 2)\n", "py", ROUND), "niska")
        self.assertEqual(po("vat_cena = round(cena * vat, 2)\n", "py", ROUND), "wysoka")
        self.assertEqual(po("x = round(cena * vatProc, 2)  # nic\n", "py", ROUND), "wysoka")

    def test_round_niepoprawne_miejsca_bez_zmian(self):
        z = skanuj_tekst("x = round(cena)\n", "x", "py")[0]
        self.assertEqual((z.kod, z.waznosc, z.po_odszumieniu), ("ROUND_NIEPOPRAWNE_MIEJSCA", "wysoka", "wysoka"))


class TestPunkt3Funkcje(unittest.TestCase):
    def test_komponenty_i_formatery_pomijane_nawet_z_arytmetyka(self):
        self.assertIsNone(po("function formatBrutto(brutto) {\n  return brutto - 1;\n}\n", "ts", FUNKCJA))
        self.assertIsNone(po("const KwotyCard = ({ brutto }) => brutto + 1;\n", "ts", FUNKCJA))
        self.assertIsNone(po("def fmt_vat(vat):\n    return vat - 1\n", "py", FUNKCJA))
        # małą literą (nie komponent) z arytmetyką zostaje
        self.assertEqual(po("function kwotyCard(netto, vat) {\n  return netto + vat;\n}\n", "ts", FUNKCJA), "srednia")

    def test_tylko_dzialania_na_netto_brutto_vat(self):
        self.assertIsNone(po("def suma_x(cena, ilosc):\n    return cena * ilosc\n", "py", FUNKCJA))
        self.assertEqual(po("def suma_x(netto, ilosc):\n    return netto * ilosc\n", "py", FUNKCJA), "srednia")

    def test_operator_w_tekscie_i_kluczu_nie_jest_dzialaniem(self):
        self.assertIsNone(po("function liczBrutto(w) {\n  return w['brutto-netto'] + 'zł';\n}\n", "ts", FUNKCJA))
        self.assertEqual(po("function liczBrutto(w) {\n  return w['brutto'] + w.x;\n}\n", "ts", FUNKCJA), "srednia")

    def test_dzialanie_poza_cialem_nie_liczy_sie(self):
        tekst = "def suma_a(w):\n    return w.id\n\nbrutto = netto + vat\n"
        self.assertIsNone(po(tekst, "py", FUNKCJA))


class TestNadalZnajdowane(unittest.TestCase):
    def test_prawdziwe_wzorce_w_trybie_istotne(self):
        for nazwa, jezyk, kod, oczekiwane in NADAL_ZNAJDOWANE:
            with self.subTest(nazwa):
                istotne = {z.kod: z.po_odszumieniu for z in skanuj_tekst(kod, "x", jezyk)
                           if z.po_odszumieniu in ("wysoka", "srednia")}
                self.assertEqual(istotne, oczekiwane)

    def test_przez_cli_w_trybie_istotne(self):
        with tempfile.TemporaryDirectory() as t:
            for i, (nazwa, jezyk, kod, _) in enumerate(NADAL_ZNAJDOWANE):
                with open(os.path.join(t, "p%d.%s" % (i, "ts" if jezyk == "ts" else "py")), "w", encoding="utf-8") as f:
                    f.write(kod)
            znaleziska, stat = skanuj([t], tryb="istotne")
            self.assertEqual(len(znaleziska), len(NADAL_ZNAJDOWANE))
            self.assertEqual({z.waznosc for z in znaleziska}, {"wysoka"})


class TestTrybyICzliczby(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.korzen = self.tmp.name
        for i, (_, jezyk, kod, _, _) in enumerate(SZUM + ISTOTNE):
            if jezyk != "sql":
                kat = os.path.join(self.korzen, "modul%d" % (i % 3))
                os.makedirs(kat, exist_ok=True)
                with open(os.path.join(kat, "f%d.%s" % (i, "ts" if jezyk == "ts" else "py")), "w", encoding="utf-8") as f:
                    f.write(kod)

    def test_pelny_zwraca_wszystko_istotne_tylko_wysokie_i_srednie(self):
        pelny, st_p = skanuj([self.korzen], tryb="pelny")
        istotne, st_i = skanuj([self.korzen], tryb="istotne")
        self.assertGreater(len(pelny), len(istotne))
        self.assertEqual(st_p["przed_odszumieniem"], st_i["przed_odszumieniem"])
        self.assertEqual(st_p["po_odszumieniu"], st_i["po_odszumieniu"])
        self.assertEqual(st_p["przed_odszumieniem"]["znalezisk"], len(pelny))
        self.assertEqual(st_i["po_odszumieniu"]["znalezisk"], len(istotne))
        self.assertTrue(all(z.waznosc in ("wysoka", "srednia") for z in istotne))
        self.assertEqual(sorted(z.kod for z in istotne), sorted(z.kod for z in pelny if z.po_odszumieniu in ("wysoka", "srednia")))

    def test_pelny_jak_dotad_waznosc_bez_zmian(self):
        pelny, _ = skanuj([self.korzen], tryb="pelny")
        wg = {z.kod: z.waznosc for z in pelny}
        self.assertEqual(wg[FUNKCJA], "niska")
        self.assertEqual(wg[ROUND], "wysoka")

    def test_domyslny_tryb_biblioteki_to_pelny_a_cli_istotne(self):
        pelny, _ = skanuj([self.korzen])
        kod, wyj = uruchom([self.korzen])
        self.assertEqual(kod, 1)
        self.assertIn("Odszumianie (--tryb istotne):", wyj)
        self.assertNotIn("[niska]  ", wyj)
        kod, wyj_pelny = uruchom([self.korzen, "--tryb", "pelny"])
        self.assertIn("Odszumianie (--tryb pelny):", wyj_pelny)
        self.assertIn("[niska]  ", wyj_pelny)
        self.assertIn("znalezisk: %d" % len(pelny), wyj_pelny)

    def test_podsumowanie_pokazuje_obie_liczby_wg_kodu_i_waznosci(self):
        json_plik = os.path.join(self.korzen, "w.json")
        uruchom([self.korzen, "--json", json_plik, "--pomin", "w.json"])
        with open(json_plik, encoding="utf-8") as f:
            p = json.load(f)["podsumowanie"]
        self.assertEqual(p["tryb"], "istotne")
        przed, po_ = p["przed_odszumieniem"], p["po_odszumieniu"]
        self.assertGreater(przed["znalezisk"], po_["znalezisk"])
        self.assertEqual(p["znalezisk"], po_["znalezisk"])
        self.assertEqual(sum(przed["wg_waznosci"].values()), przed["znalezisk"])
        self.assertEqual(po_["wg_waznosci"]["niska"], 0)
        self.assertGreater(przed["wg_kodu"][FLOAT], po_["wg_kodu"].get(FLOAT, 0))
        _, tekst = uruchom([self.korzen, "--pomin", "w.json"])
        self.assertIn("Kody (po odszumieniu / przed odszumieniem):", tekst)
        self.assertRegex(tekst, r"FLOAT_W_FUNKCJI_KWOTOWEJ\s+\d+ / \d+")

    def test_zly_tryb(self):
        with self.assertRaises(ValueError):
            skanuj([self.korzen], tryb="losowy")


class TestKorpusPrzedPo(unittest.TestCase):
    """Liczby na wymyślonym korpusie szumu i prawdziwych wzorców (podawane w README)."""

    def licz(self):
        przed = po_ = 0
        szum_przed = szum_po = 0
        for grupa, jest_szum in ((SZUM, True), (ISTOTNE, False)):
            for _, jezyk, kod, szukany, _ in grupa:
                z = [x for x in skanuj_tekst(kod, "x", jezyk) if x.kod == szukany]
                przed += len(z)
                trafione = sum(1 for x in z if x.po_odszumieniu in ("wysoka", "srednia"))
                po_ += trafione
                if jest_szum:
                    szum_przed, szum_po = szum_przed + len(z), szum_po + trafione
        return przed, po_, szum_przed, szum_po

    def test_szum_znika_a_istotne_zostaje(self):
        przed, po_, szum_przed, szum_po = self.licz()
        self.assertEqual(szum_po, 0)                      # żaden szum nie jest wysoki ani średni
        self.assertGreaterEqual(szum_przed, len(SZUM))    # a w trybie pełnym wszystkie są widoczne
        istotne_przed = przed - szum_przed
        self.assertEqual(po_, istotne_przed - sum(1 for _, _, _, _, o in ISTOTNE if o == "niska"))


if __name__ == "__main__":
    unittest.main()
