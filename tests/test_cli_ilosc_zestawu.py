"""CLI: ilość zestawu (dzieci na 1 szt.), ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, alternatywy, --ilosc-zestawu."""
import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.adapter import z_wiersza
from amounts_calc.check import main, sprawdz_dokument, sprawdz_partie, tekst_podsumowania

K = D("0.01")


def kw(x):
    return D(x).quantize(K, rounding=ROUND_HALF_UP)


def kwoty(netto, stawka=23):
    n = D(netto)
    v = kw(n * stawka / 100)
    return {"netto": str(n), "vat": str(v), "brutto": str(n + v)}


def dziecko(id_, cena, parent="Z", ilosc=1, stawka=23, **extra):
    d = {"id": id_, "parent_id": parent, "ilosc": ilosc, "cena_netto_jedn": str(cena), "stawka_vat": stawka}
    d.update(kwoty(kw(D(cena) * D(ilosc)), stawka))
    d.update(extra)
    return d


def zestaw(n, dzieci, id_="Z", parent=None, mnoz=True, **extra):
    bezp = [c for c in dzieci if c["parent_id"] == id_]
    m = D(n) if mnoz else D(1)
    z = {"id": id_, "ilosc": n, "stawka_vat": 23}
    for k in ("netto", "vat", "brutto"):
        z[k] = str(kw(sum((D(c[k]) for c in bezp), D(0)) * m))
    if parent is not None:
        z["parent_id"] = parent
    z.update(extra)
    return z


def dok(pozycje, **extra):
    sumy = {k: D(0) for k in ("netto", "vat", "brutto")}
    for p in pozycje:
        if p.get("parent_id") is None and not p.get("alternatywa") and "netto" in p:
            for k in sumy:
                sumy[k] += D(p[k])
    d = {"id": "ZK/1", "typ": "ZK"}
    d.update({"suma_" + k: str(v) for k, v in sumy.items()})
    d["pozycje"] = pozycje
    d.update(extra)
    return d


def kody(w):
    return {p["kod"] for p in w["przyczyny"]}


def kody_findings(w):
    return {n["kod"] for n in w["niespojnosci"]}


PRZYPADKI = [(10, ["600.00", "117.40"]), (2, ["5000.00", "2692.82"]), (3, ["1000.00", "270.00"]),
             (20, ["30.00", "18.00"]), (3, ["100.00", "17.00"])]


class TestPotwierdzonePrzypadkiWCli(unittest.TestCase):
    def dokument(self, n, ceny):
        dzieci = [dziecko("D%d" % i, c) for i, c in enumerate(ceny)]
        return dok([zestaw(n, dzieci)] + dzieci)

    def test_pieciu_przypadkow_jest_spojnych(self):
        for n, ceny in PRZYPADKI:
            with self.subTest(n=n):
                w = sprawdz_dokument(self.dokument(n, ceny), ilosc_zestawu=True)
                self.assertEqual((w["status"], w["niespojnosci"], w["przyczyny"], w["blad"]), ("spojny", [], [], None))
                self.assertEqual(w["tryb_pasujacy"], "oba")

    def test_stare_zachowanie_daje_falszywe_niespojnosci(self):
        for n, ceny in PRZYPADKI:
            with self.subTest(n=n):
                w = sprawdz_dokument(self.dokument(n, ceny), ilosc_zestawu=False)
                self.assertEqual(w["status"], "niespojny")
                self.assertTrue({bledy.ZESTAW_ROZNY_OD_DZIECI, bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU} <= kody_findings(w))
                self.assertIn(bledy.NAGLOWEK_WYZSZY, kody(w))
                naglowek = [p for p in w["przyczyny"] if p["kod"] == bledy.NAGLOWEK_WYZSZY][0]
                self.assertEqual(naglowek["roznica"], (n - 1) * sum(D(c) for c in ceny))     # (N - 1) x suma dzieci

    def test_naglowek_n_razy_dzieci_nie_daje_naglowek_wyzszy(self):
        for n, ceny in PRZYPADKI:
            w = sprawdz_dokument(self.dokument(n, ceny), ilosc_zestawu=True)
            self.assertNotIn(bledy.NAGLOWEK_WYZSZY, kody(w))
            self.assertNotIn(bledy.NAGLOWEK_NIZSZY, kody(w))
            self.assertNotIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody_findings(w))
            self.assertNotIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody_findings(w))

    def test_n_rowne_1_bez_zmian_w_obu_modelach(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00")]
        d = dok([zestaw(1, dzieci)] + dzieci)
        a, b = sprawdz_dokument(d, ilosc_zestawu=True), sprawdz_dokument(d, ilosc_zestawu=False)
        for k in ("status", "niespojnosci", "przyczyny", "tryb_pasujacy", "pasuje"):
            self.assertEqual(a[k], b[k], k)
        d["pozycje"][0]["netto"] = "155.00"
        a, b = sprawdz_dokument(d, ilosc_zestawu=True), sprawdz_dokument(d, ilosc_zestawu=False)
        self.assertEqual((a["status"], a["niespojnosci"]), (b["status"], b["niespojnosci"]))
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody_findings(a))

    def test_ilosc_ulamkowa_i_zero(self):
        for n in ("0.5", "2.5", "0"):
            dzieci = [dziecko("A", "100.00"), dziecko("B", "40.00")]
            w = sprawdz_dokument(dok([zestaw(n, dzieci)] + dzieci), ilosc_zestawu=True)
            self.assertEqual((w["status"], w["przyczyny"], w["niespojnosci"]), ("spojny", [], []), n)

    def test_n_zero_i_naglowek_zero_nie_jest_naglowek_zero(self):
        dzieci = [dziecko("A", "100.00")]
        w = sprawdz_dokument(dok([zestaw(0, dzieci)] + dzieci), ilosc_zestawu=True)
        self.assertNotIn(bledy.NAGLOWEK_ZERO, kody(w))
        self.assertEqual(w["status"], "spojny")

    def test_zestaw_i_zwykla_pozycja_w_jednym_dokumencie(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00", stawka=8)]
        zwykla = {"id": "S", "ilosc": 2, "cena_netto_jedn": "20.00", "stawka_vat": 23, **kwoty("40.00")}
        w = sprawdz_dokument(dok([zestaw(3, dzieci), *dzieci, zwykla]), ilosc_zestawu=True)
        self.assertEqual((w["status"], w["przyczyny"], w["tryb_pasujacy"]), ("spojny", [], "oba"))


class TestRoznicaGrosza(unittest.TestCase):
    def test_grosz_przy_n_wiekszym_od_1_jak_dla_n_1(self):
        for n in (1, 4):
            dzieci = [dziecko("A", "100.00")]
            z = zestaw(n, dzieci)
            z["netto"] = str(D(z["netto"]) + D("0.01"))
            d = dok([z] + dzieci)
            w = sprawdz_dokument(d, ilosc_zestawu=True)
            self.assertEqual(w["status"], "niespojny", n)
            self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody_findings(w))
            # grosz to zaokrąglenie: bez podpowiedzi o braku mnożenia czy nieodświeżeniu zestawu
            hint = [x["podpowiedz"] for x in w["niespojnosci"] if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
            self.assertEqual(set(hint), {"inna"}, n)
            self.assertNotIn(bledy.ZESTAW_NIEODSWIEZONY, kody(w))
            self.assertNotIn(bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, kody(w))


class TestBezMnozenia(unittest.TestCase):
    def test_zestaw_rowny_1_x_dzieci(self):
        dzieci = [dziecko("A", "600.00"), dziecko("B", "117.40")]
        z = zestaw(10, dzieci, mnoz=False)
        # nagłówek poprawny (N x dzieci), a zestaw nie został pomnożony
        d = dok([z] + dzieci)
        d.update(suma_netto="7174.00", suma_vat="1650.00", suma_brutto="8824.00")
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(w["podpowiedz"], bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC)
        self.assertIn(bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, kody(w))
        self.assertNotIn(bledy.ZESTAW_NIEODSWIEZONY, kody(w))
        p = [x for x in w["przyczyny"] if x["kod"] == bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC][0]
        s = p["zestawy"][0]
        self.assertEqual((s["indeks"], s["ilosc"], s["zapisane"], s["oczekiwane"], s["suma_dzieci"], s["roznica"]),
                         (0, D(10), D("717.40"), D("7174.00"), D("717.40"), D("-6456.60")))
        self.assertFalse(p["naglowek_liczony_z_zapisanych_zestawow"])
        # kod ZESTAW_ROZNY_OD_DZIECI pozostaje, z podpowiedzią
        zr = [n for n in w["niespojnosci"] if n["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertEqual({n["podpowiedz"] for n in zr}, {bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC})
        self.assertIn("pasuje do 1 x suma dzieci", zr[0]["opis"])

    def test_naglowek_tez_pomija_ilosc(self):
        dzieci = [dziecko("A", "600.00"), dziecko("B", "117.40")]
        z = zestaw(10, dzieci, mnoz=False)
        d = dok([z] + dzieci)            # nagłówek = zapisany zestaw (1 x dzieci)
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        self.assertEqual(w["status"], "niespojny")
        p = [x for x in w["przyczyny"] if x["kod"] == bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC][0]
        self.assertTrue(p["naglowek_liczony_z_zapisanych_zestawow"])
        sumy = [n for n in w["niespojnosci"] if n["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU]
        self.assertTrue(sumy)
        self.assertEqual({n["podpowiedz"] for n in sumy}, {bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC})

    def test_n_rowne_1_to_nieodswiezony_a_nie_bez_mnozenia(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00")]
        z = zestaw(1, dzieci)
        z.update(netto="100.00", vat="23.00", brutto="123.00")       # zestaw sprzed dodania dziecka B
        d = dok([z] + dzieci)
        d.update(suma_netto="150.00", suma_vat="34.50", suma_brutto="184.50")
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        self.assertNotIn(bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, kody(w))
        self.assertIn(bledy.ZESTAW_NIEODSWIEZONY, kody(w))

    def test_dziecko_dodane_po_przeliczeniu_zestawu_o_ilosci_n(self):
        # zestaw x3 policzony tylko z A; dziecko B (50) dodano później; wartość brakująca = 3 x 50
        a, b = dziecko("A", "100.00"), dziecko("B", "50.00")
        z = zestaw(3, [a])
        d = dok([z, a, b])
        d.update(suma_netto="450.00", suma_vat="103.50", suma_brutto="553.50")        # nagłówek odświeżony
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        p = [x for x in w["przyczyny"] if x["kod"] == bledy.ZESTAW_NIEODSWIEZONY][0]
        self.assertEqual(p["zestawy"][0]["roznica"], D("-150.00"))
        self.assertIn("roznica_rowna_wartosci_dziecka", [x["dowod"] for x in p["zestawy"][0]["dowody"]])

    def test_podzestaw_bez_mnozenia(self):
        b, c = dziecko("B", "4.00", "P"), dziecko("C", "6.00", "P")
        p = zestaw(3, [b, c], id_="P", parent="Z", mnoz=False)         # podzestaw nie pomnożony
        a = dziecko("A", "10.00")
        z = zestaw(2, [a, {**p, "netto": "30.00", "vat": "6.90", "brutto": "36.90"}])
        d = dok([z, a, p, b, c])
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        self.assertEqual(w["status"], "niespojny")
        zr = {n["zakres"]: n["podpowiedz"] for n in w["niespojnosci"] if n["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI}
        self.assertEqual(zr, {"pozycja:2": bledy.ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC})


class TestPodzestawy(unittest.TestCase):
    def pozycje(self, n_zestawu=2, n_podzestawu=3):
        a = dziecko("A", "10.00")
        b, c = dziecko("B", "4.00", "P"), dziecko("C", "6.00", "P")
        p = zestaw(n_podzestawu, [b, c], id_="P", parent="Z")
        z = zestaw(n_zestawu, [a, p])
        return [z, a, p, b, c]

    def test_oba_z_n_wiekszym_od_1(self):
        w = sprawdz_dokument(dok(self.pozycje(2, 3)), ilosc_zestawu=True)
        self.assertEqual((w["status"], w["przyczyny"], w["niespojnosci"]), ("spojny", [], []))
        self.assertEqual(w["tryb_pasujacy"], "oba")

    def test_trzy_poziomy(self):
        c = dziecko("C", "1.00", "P2")
        p2 = zestaw(5, [c], id_="P2", parent="P1")
        p1 = zestaw(4, [p2], id_="P1", parent="Z")
        z = zestaw(3, [p1])
        w = sprawdz_dokument(dok([z, p1, p2, c]), ilosc_zestawu=True)
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))
        self.assertEqual(z["netto"], "60.00")

    def test_za_glebokie_zagniezdzenie_to_blad_hierarchii(self):
        pozycje = [{"id": "p0", "ilosc": 1, "stawka_vat": 23}]
        for i in range(1, 13):
            pozycje.append({"id": "p%d" % i, "parent_id": "p%d" % (i - 1), "ilosc": 1, "stawka_vat": 23})
        pozycje[-1].update(kwoty("1.00"))
        w = sprawdz_dokument(dok(pozycje, suma_netto="1.00", suma_vat="0.23", suma_brutto="1.23"), ilosc_zestawu=True)
        self.assertEqual((w["status"], w["blad"]["kod"]), ("blad", bledy.NIEPOPRAWNA_HIERARCHIA))


class TestZestawyZNarzutemIIloscia(unittest.TestCase):
    def test_narzut_zestawu_liczy_sie_od_n_razy_dzieci(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00")]
        z = zestaw(3, dzieci)                      # 450,00
        z.update(narzut_proc=10, netto="495.00", vat="113.85", brutto="608.85")
        d = dok([z] + dzieci)
        d.update(suma_netto="450.00", suma_vat="103.50", suma_brutto="553.50")        # nagłówek = N x dzieci
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))
        self.assertEqual(w["przyczyny"][0]["zestawy"][0]["oczekiwane"], D("495.00"))
        self.assertEqual(w["przyczyny"][0]["zestawy"][0]["suma_dzieci"], D("450.00"))

    def test_naglowek_uwzglednia_narzut_zestawu_przy_n(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00")]
        z = zestaw(3, dzieci)
        z.update(narzut_proc=10, netto="495.00", vat="113.85", brutto="608.85")
        d = dok([z] + dzieci)                      # nagłówek = wartość zestawu z narzutem
        w = sprawdz_dokument(d, ilosc_zestawu=True)
        self.assertEqual((w["status"], w["niespojnosci"]), ("spojny", []))
        self.assertTrue(w["przyczyny"][0]["naglowek_uwzglednia_zestawy"])


class TestAlternatywyWCli(unittest.TestCase):
    BAZA = {"id": "B", "ilosc": 1, "cena_netto_jedn": "100.00", "stawka_vat": 23, **kwoty("100.00")}
    O1 = {"id": "O1", "ilosc": 1, "cena_netto_jedn": "40.00", "stawka_vat": 23, "alternatywa": True, **kwoty("40.00")}
    O2 = {"id": "O2", "ilosc": 1, "cena_netto_jedn": "60.00", "stawka_vat": 23, "alternatywa": True, **kwoty("60.00")}

    def dokument(self, netto, **extra):
        d = {"id": "OF/1", "typ": "OFERTA", "pozycje": [self.BAZA, self.O1, self.O2]}
        d.update({"suma_" + k: v for k, v in kwoty(netto).items()})
        d.update(extra)
        return d

    def alt(self, w):
        return [p for p in w["przyczyny"] if p["kod"] == bledy.ALTERNATYWY_W_SUMIE]

    def test_baza_plus_jedna_opcja(self):
        for netto, wlaczona in [("140.00", "O1"), ("160.00", "O2"), ("100.00", None)]:
            with self.subTest(netto=netto):
                w = sprawdz_dokument(self.dokument(netto))
                self.assertEqual((w["status"], w["niespojnosci"], w["tryb_pasujacy"]), ("spojny", [], "oba"))
                (a,) = self.alt(w)
                self.assertTrue(a["informacja"])
                self.assertEqual(a["dopasowanie"], "zgodne")
                self.assertFalse(a["naglowek_zawiera_wszystkie_opcje"])
                opcje = {p["id"]: p["wliczona"] for g in a["grupy"] for p in g["pozycje"]}
                self.assertEqual(opcje, {"O1": wlaczona == "O1", "O2": wlaczona == "O2"})

    def test_informacja_pojawia_sie_w_raporcie_mimo_statusu_spojny(self):
        from amounts_calc.check import ma_problem
        w = sprawdz_dokument(self.dokument("140.00"))
        self.assertEqual(w["status"], "spojny")
        self.assertTrue(ma_problem(w))

    def test_opcje_dodane_do_sumy_po_cichu(self):
        w = sprawdz_dokument(self.dokument("200.00"))
        self.assertEqual(w["status"], "niespojny")
        (a,) = self.alt(w)
        self.assertEqual(a["dopasowanie"], "najblizsze")
        self.assertTrue(a["naglowek_zawiera_wszystkie_opcje"])
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody_findings(w))
        self.assertEqual([g["grupa"] for g in a["grupy"]], [""])
        self.assertEqual([p["indeks"] for p in a["grupy"][0]["pozycje"]], [1, 2])

    def test_bez_pol_alternatywy_dotychczasowe_zachowanie(self):
        d = self.dokument("200.00")
        d["pozycje"] = [{k: v for k, v in p.items() if k != "alternatywa"} for p in d["pozycje"]]
        w = sprawdz_dokument(d)
        self.assertEqual((w["status"], w["przyczyny"], w["niespojnosci"]), ("spojny", [], []))

    def test_dwie_pozycje_typu_opcja_i_zwykla_pozycja_z_grupa_opcji(self):
        d = {"id": "OF/2", "pozycje": [self.BAZA,
                                       {**self.O1, "alternatywa": None, "grupa_opcji": "stol"},
                                       {**self.O2, "alternatywa": None, "grupa_opcji": "stol"}],
             **{"suma_" + k: v for k, v in kwoty("160.00").items()}}
        w = sprawdz_dokument(d)
        self.assertEqual((w["status"], w["niespojnosci"]), ("spojny", []))
        (a,) = self.alt(w)
        self.assertEqual([g["grupa"] for g in a["grupy"]], ["stol"])

    def test_alternatywy_bez_kwot_pozycji(self):
        d = {"id": "OF/3", "pozycje": [{k: v for k, v in p.items() if k not in ("netto", "vat", "brutto")}
                                       for p in (self.BAZA, self.O1, self.O2)],
             **{"suma_" + k: v for k, v in kwoty("160.00").items()}}
        w = sprawdz_dokument(d)
        self.assertEqual(w["dane"], "brak_kwot")
        self.assertEqual((w["status"], w["niespojnosci"]), ("spojny", []))
        (a,) = self.alt(w)
        self.assertEqual(a["dopasowanie"], "zgodne")

    def test_alternatywy_bez_vat_w_pozycjach(self):
        d = {"id": "OF/4", "pozycje": [{k: v for k, v in p.items() if k not in ("vat", "brutto")}
                                       for p in (self.BAZA, self.O1, self.O2)],
             **{"suma_" + k: v for k, v in kwoty("160.00").items()}}
        w = sprawdz_dokument(d)
        self.assertEqual(w["dane"], "brak_vat")
        self.assertEqual(w["niespojnosci"], [])
        self.assertIn(bledy.VAT_WYLICZONY_ZGODNY, kody(w))        # VAT policzony tylko z bazy i wybranej opcji
        self.assertEqual(w["status"], "spojny")

    def test_mapowanie_alternatywy(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 1, "stawka_vat": 23, "opcja": True, "grupa_opcji": "A"}]})
        self.assertEqual((d["pozycje"][0]["alternatywa"], d["pozycje"][0]["grupa_opcji"]), (True, "A"))
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"ilosc": 1, "stawka_vat": 23, "czy_opcja": 1}]},
                      {"pozycja": {"alternatywa": "czy_opcja"}})
        self.assertEqual(d["pozycje"][0]["alternatywa"], 1)


class TestAdapterIlosc(unittest.TestCase):
    def test_ilosc_zestawu_z_aliasu_i_hierarchia_zachowana(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"id": "Z", "ilosc_zestawu": 10, "stawka_vat": 23},
                                   {"id": "A", "parent_id": "Z", "ilosc": 1, "stawka_vat": 23}]})
        self.assertEqual((d["pozycje"][0]["ilosc"], d["pozycje"][1]["parent_id"]), (10, "Z"))

    def test_wlasna_nazwa_ilosci_zestawu(self):
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"id": "Z", "krotnosc": 4, "stawka_vat": 23}]}, {"pozycja": {"ilosc": "krotnosc"}})
        self.assertEqual(d["pozycje"][0]["ilosc"], 4)


class TestFlagaCli(unittest.TestCase):
    def uruchom(self, dokumenty, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            wej, wyj_j, wyj_c = (os.path.join(tmp, n) for n in ("d.json", "w.json", "w.csv"))
            with open(wej, "w", encoding="utf-8") as f:
                json.dump(dokumenty, f)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    kod = main([wej, "--json", wyj_j, "--csv", wyj_c] + list(argv))
                except SystemExit as e:
                    return e.code, out.getvalue(), None, None
            with open(wyj_j, encoding="utf-8") as f:
                raport = json.load(f)
            with open(wyj_c, encoding="utf-8-sig", newline="") as f:
                wiersze = list(csv.DictReader(f, delimiter=";"))
        return kod, out.getvalue(), raport, wiersze

    def dokumenty(self):
        out = []
        for i, (n, ceny) in enumerate(PRZYPADKI):
            dzieci = [dziecko("D%d" % j, c) for j, c in enumerate(ceny)]
            out.append(dict(dok([zestaw(n, dzieci)] + dzieci), id="przypadek-%d" % (i + 1)))
        return out

    def test_domyslnie_tak_pieciu_przypadkow_bez_niespojnosci(self):
        kod, out, raport, wiersze = self.uruchom(self.dokumenty())
        self.assertEqual((kod, raport, wiersze), (0, [], []))
        self.assertIn("Bez uwag: 5 z 5 dokumentów", out)

    def test_flaga_tak_jawnie(self):
        self.assertEqual(self.uruchom(self.dokumenty(), "--ilosc-zestawu", "tak")[0], 0)
        self.assertEqual(self.uruchom(self.dokumenty(), "--ilosc-zestawu=tak")[0], 0)

    def test_flaga_nie_to_stare_zachowanie(self):
        kod, out, raport, wiersze = self.uruchom(self.dokumenty(), "--ilosc-zestawu", "nie")
        self.assertEqual(kod, 1)
        self.assertEqual(len(raport), 5)
        self.assertIn("NAGLOWEK_WYZSZY", out)
        self.assertEqual({r["status"] for r in raport}, {"niespojny"})

    def test_zla_wartosc_flagi(self):
        self.assertEqual(self.uruchom(self.dokumenty(), "--ilosc-zestawu", "moze")[0], 2)

    def test_podsumowanie_podpowiedzi_bez_mnozenia(self):
        dzieci = [dziecko("A", "600.00"), dziecko("B", "117.40")]
        d = dok([zestaw(10, dzieci, mnoz=False)] + dzieci)
        d.update(suma_netto="7174.00", suma_vat="1650.00", suma_brutto="8824.00")
        kod, out, raport, wiersze = self.uruchom([d])
        self.assertEqual(kod, 1)
        self.assertEqual(raport[0]["podpowiedz"], "ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC")
        self.assertIn("ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC=1", out)
        self.assertEqual(wiersze[0]["podpowiedz"], "ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC")
        self.assertIn("ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC", wiersze[0]["kody"])

    def test_alternatywy_w_raporcie_json_i_csv(self):
        d = TestAlternatywyWCli().dokument("140.00")
        kod, out, raport, wiersze = self.uruchom([d])
        self.assertEqual(kod, 0)
        self.assertEqual([r["id"] for r in raport], ["OF/1"])
        self.assertEqual(raport[0]["status"], "spojny")
        a = raport[0]["przyczyny"][0]
        self.assertEqual((a["kod"], a["dopasowanie"]), ("ALTERNATYWY_W_SUMIE", "zgodne"))
        self.assertEqual([p["wliczona"] for p in a["grupy"][0]["pozycje"]], [True, False])
        self.assertEqual(wiersze[0]["kody"], "ALTERNATYWY_W_SUMIE")
        self.assertIn("ALTERNATYWY_W_SUMIE", out)

    def test_wpisy_partii(self):
        wyniki, p = sprawdz_partie(self.dokumenty(), ilosc_zestawu=True)
        self.assertEqual((p["spojne"], p["z_niespojnosciami"]), (5, 0))
        wyniki, p = sprawdz_partie(self.dokumenty())            # domyślnie biblioteka ignoruje ilość zestawu
        self.assertEqual(p["z_niespojnosciami"], 5)
        self.assertIn("Do sprawdzenia: 5", tekst_podsumowania(p, wyniki))


if __name__ == "__main__":
    unittest.main()
