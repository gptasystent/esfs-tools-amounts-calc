"""Podpowiedzi przyczyn niespójności: ZESTAW_NIEODSWIEZONY, BRUTTO_ROWNE_NETTO, POLGROSZ, inna."""
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
from amounts_calc.check import KOLUMNY_CSV, main, sprawdz_dokument, sprawdz_partie, tekst_podsumowania
from amounts_calc.podpowiedzi import INNA, brutto_rowne_netto, podpowiedz_dokumentu, zestawy_nieodswiezone


def poz(netto, vat, brutto, stawka=23, **extra):
    d = {"ilosc": 1, "cena_netto_jedn": netto, "stawka_vat": stawka, "netto": netto, "vat": vat, "brutto": brutto}
    d.update(extra)
    return d


def dok(pozycje, netto, vat, brutto, **extra):
    d = {"id": "D", "typ": "FV", "suma_netto": netto, "suma_vat": vat, "suma_brutto": brutto, "pozycje": pozycje}
    d.update(extra)
    return d


def hinty(w):
    return {(n["kod"], n["zakres"], n["pole"]): n["podpowiedz"] for n in w["niespojnosci"]}


def kody(w):
    return {p["kod"] for p in w["przyczyny"]}


def jedna(w, kod):
    return [p for p in w["przyczyny"] if p["kod"] == kod][0]


def zestaw_pozycje(zestaw_kwoty, standalone=False):
    """Zestaw Z z dziećmi A (100) i B (50) oraz opcjonalnie osobna pozycja S (20)."""
    n, v, b = zestaw_kwoty
    pozycje = [{"id": "Z", "ilosc": 1, "stawka_vat": 23, "netto": n, "vat": v, "brutto": b},
               dict(poz("100.00", "23.00", "123.00"), id="A", parent_id="Z"),
               dict(poz("50.00", "11.50", "61.50"), id="B", parent_id="Z")]
    if standalone:
        pozycje.append(poz("20.00", "4.60", "24.60", id="S"))
    return pozycje


class TestBruttoRowneNetto(unittest.TestCase):
    def test_brutto_bez_vat_w_pozycji(self):
        w = sprawdz_dokument(dok([poz("100.00", "23.00", "100.00")], "100.00", "23.00", "100.00"))
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(hinty(w)[(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "pozycja:0", "brutto")], bledy.BRUTTO_ROWNE_NETTO)
        self.assertEqual(hinty(w)[(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "dokument", "suma_brutto")], bledy.BRUTTO_ROWNE_NETTO)
        self.assertTrue(all(h == bledy.BRUTTO_ROWNE_NETTO for h in hinty(w).values()))
        p = jedna(w, bledy.BRUTTO_ROWNE_NETTO)
        self.assertEqual((p["liczba"], p["naglowek"], p["pozycje"][0]["indeks"]), (1, True, 0))
        self.assertEqual(w["podpowiedz"], bledy.BRUTTO_ROWNE_NETTO)

    def test_vat_zero_i_brutto_rowne_netto_mimo_stawki_23(self):
        w = sprawdz_dokument(dok([poz("100.00", "0.00", "100.00")], "100.00", "0.00", "100.00"))
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.BRUTTO_ROWNE_NETTO, kody(w))
        self.assertEqual(hinty(w)[(bledy.VAT_STAWKI_ROZNY_OD_SUMY, "stawka:23", "vat")], bledy.BRUTTO_ROWNE_NETTO)
        self.assertNotIn(bledy.NIEZGODNY_Z_BIBLIOTEKA, kody(w))

    def test_stawki_zwolnione_nie_sa_podejrzane(self):
        for st in ("zw", "np", 0):
            w = sprawdz_dokument(dok([poz("100.00", "0.00", "100.00", st)], "100.00", "0.00", "100.00"))
            self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []), st)

    def test_grosze_nie_sa_podejrzane(self):
        # 23% od 0,02 = 0,0046 -> VAT 0,00, więc brutto = netto jest poprawne
        w = sprawdz_dokument(dok([poz("0.02", "0.00", "0.02")], "0.02", "0.00", "0.02"))
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))

    def test_naglowek_z_brutto_rownym_netto(self):
        w = sprawdz_dokument(dok([poz("100.00", "23.00", "123.00")], "100.00", "23.00", "100.00"))
        h = hinty(w)
        self.assertEqual(h[(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "dokument", "suma_brutto")], bledy.BRUTTO_ROWNE_NETTO)
        self.assertEqual(h[(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, "dokument", "suma_brutto")], bledy.BRUTTO_ROWNE_NETTO)
        self.assertEqual(jedna(w, bledy.BRUTTO_ROWNE_NETTO)["liczba"], 0)           # pozycje w porządku, tylko nagłówek
        self.assertTrue(jedna(w, bledy.BRUTTO_ROWNE_NETTO)["naglowek"])

    def test_inna_przyczyna_brutto(self):
        w = sprawdz_dokument(dok([poz("100.00", "23.00", "123.00")], "100.00", "23.00", "123.50"))
        self.assertEqual(set(hinty(w).values()), {INNA})
        self.assertEqual(w["podpowiedz"], INNA)
        self.assertNotIn(bledy.BRUTTO_ROWNE_NETTO, kody(w))

    def test_dokument_o_sumie_zerowej_bez_falszywego_alarmu(self):
        w = sprawdz_dokument(dok([poz("50.00", "11.50", "61.50"), poz("-50.00", "-11.50", "-61.50")],
                                 "0.00", "0.00", "0.00"), dopusc_ujemne=True)
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))

    def test_ujemne_symetrycznie(self):
        w = sprawdz_dokument(dok([poz("-100.00", "-23.00", "-100.00")], "-100.00", "-23.00", "-100.00"),
                             dopusc_ujemne=True)
        self.assertIn(bledy.BRUTTO_ROWNE_NETTO, kody(w))

    def test_polgrosz_ma_wlasna_podpowiedz(self):
        w = sprawdz_dokument(dok([poz("100.00", "23.00", "123.00")], "100.00", "23.00", "123.005"))
        self.assertEqual(w["status"], "drobiazg")
        self.assertEqual(set(hinty(w).values()), {"POLGROSZ"})
        self.assertIsNone(w["podpowiedz"])                  # drobiazg nie jest "przyczyną niespójności"

    def test_funkcja_brutto_rowne_netto(self):
        tabela = [(D("100"), D("100"), "23", True), (D("100"), D("100"), "zw", False), (D("100"), D("123"), "23", False),
                  (D("0.02"), D("0.02"), "23", False), (D("-100"), D("-100"), "8", True), (None, D("1"), "23", False),
                  (D("100"), D("100"), None, False), (D("100"), D("100.004"), "23", True), (D("100"), D("100.01"), "23", False)]
        for netto, brutto, st, oczek in tabela:
            self.assertEqual(brutto_rowne_netto(netto, brutto, st), oczek, (netto, brutto, st))


class TestZestawNieodswiezony(unittest.TestCase):
    def test_dziecko_dodane_po_przeliczeniu(self):
        # zestaw ma kwoty samego dziecka A; B dodano później; nagłówek jest odświeżony (150)
        w = sprawdz_dokument(dok(zestaw_pozycje(("100.00", "23.00", "123.00")), "150.00", "34.50", "184.50"))
        self.assertEqual(w["status"], "niespojny")
        self.assertEqual(hinty(w)[(bledy.ZESTAW_ROZNY_OD_DZIECI, "pozycja:0", "netto")], bledy.ZESTAW_NIEODSWIEZONY)
        p = jedna(w, bledy.ZESTAW_NIEODSWIEZONY)
        z = p["zestawy"][0]
        self.assertEqual((z["indeks"], z["id"], z["zapisane"], z["suma_dzieci"], z["roznica"]),
                         (0, "Z", D("100.00"), D("150.00"), D("-50.00")))
        dowody = [d["dowod"] for d in z["dowody"]]
        self.assertIn("roznica_rowna_wartosci_dziecka", dowody)
        self.assertIn("naglowek_zgodny_z_suma_dzieci", dowody)
        self.assertEqual([d["id"] for d in z["dowody"] if d["dowod"] == "roznica_rowna_wartosci_dziecka"], ["B"])
        self.assertEqual(w["podpowiedz"], bledy.ZESTAW_NIEODSWIEZONY)

    def test_tylko_naglowek_zgodny_z_dziecmi(self):
        w = sprawdz_dokument(dok(zestaw_pozycje(("160.00", "36.80", "196.80")), "150.00", "34.50", "184.50"))
        z = jedna(w, bledy.ZESTAW_NIEODSWIEZONY)["zestawy"][0]
        self.assertEqual([d["dowod"] for d in z["dowody"]], ["naglowek_zgodny_z_suma_dzieci"])

    def test_naglowek_policzony_ze_starego_zestawu(self):
        # zestaw 160 (powinno być 150) + osobna pozycja 20; nagłówek = 160 + 20 = 180 (też nieodświeżony)
        pozycje = zestaw_pozycje(("160.00", "36.80", "196.80"), standalone=True)
        w = sprawdz_dokument(dok(pozycje, "180.00", "41.40", "221.40"))
        p = jedna(w, bledy.ZESTAW_NIEODSWIEZONY)
        self.assertTrue(p["naglowek_liczony_z_zapisanych_zestawow"])
        self.assertEqual([d["dowod"] for d in p["zestawy"][0]["dowody"]], ["naglowek_zgodny_z_zapisanymi_zestawami"])
        # niespójności sum dokumentu też wskazują na nieodświeżony zestaw
        sumy = [n for n in w["niespojnosci"] if n["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU]
        self.assertTrue(sumy)
        self.assertEqual({n["podpowiedz"] for n in sumy}, {bledy.ZESTAW_NIEODSWIEZONY})

    def test_bez_dowodow_jest_inna(self):
        pozycje = zestaw_pozycje(("160.00", "36.80", "196.80"), standalone=True)
        w = sprawdz_dokument(dok(pozycje, "175.00", "40.25", "215.25"))
        self.assertEqual(hinty(w)[(bledy.ZESTAW_ROZNY_OD_DZIECI, "pozycja:0", "netto")], INNA)
        self.assertNotIn(bledy.ZESTAW_NIEODSWIEZONY, kody(w))

    def test_zestaw_z_narzutem_nie_jest_nieodswiezony(self):
        pozycje = zestaw_pozycje(("165.00", "37.95", "202.95"))
        pozycje[0]["narzut_proc"] = 10
        w = sprawdz_dokument(dok(pozycje, "150.00", "34.50", "184.50"))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))

    def test_poprawny_zestaw_bez_podpowiedzi(self):
        w = sprawdz_dokument(dok(zestaw_pozycje(("150.00", "34.50", "184.50")), "150.00", "34.50", "184.50"))
        self.assertEqual((w["status"], w["przyczyny"], w["podpowiedz"]), ("spojny", [], None))

    def test_funkcja_zestawy_nieodswiezone(self):
        wiersze = [{"indeks": 0, "id": "Z", "zestaw": True, "netto": D("100"), "vat": D("23"), "brutto": D("123")},
                   {"indeks": 1, "id": "A", "zestaw": False, "netto": D("100"), "vat": D("23"), "brutto": D("123")},
                   {"indeks": 2, "id": "B", "zestaw": False, "netto": D("50"), "vat": D("11.5"), "brutto": D("61.5")}]
        dzieci = {0: [1, 2]}
        pozycje = [{"id": "Z"}, {"parent_id": "Z"}, {"parent_id": "Z"}]
        naglowek = {"netto": D("150"), "vat": D("34.5"), "brutto": D("184.5")}
        wynik, z_zapisanych = zestawy_nieodswiezone(wiersze, dzieci, [0], naglowek, pozycje)
        self.assertEqual((len(wynik), z_zapisanych), (1, False))
        naglowek_inny = {"netto": D("999"), "vat": D("1"), "brutto": D("1")}
        wynik, z_zapisanych = zestawy_nieodswiezone(wiersze, dzieci, [0], naglowek_inny, pozycje)
        # różnica równa wartości dziecka B nadal jest dowodem, ale nagłówek nic nie potwierdza
        self.assertEqual([d["dowod"] for d in wynik[0]["dowody"]], ["roznica_rowna_wartosci_dziecka"])
        self.assertFalse(z_zapisanych)
        # brak jakiegokolwiek dowodu: różnica 7 nie jest wartością dziecka, nagłówek niczego nie potwierdza
        wiersze[0]["netto"] = D("157")
        self.assertEqual(zestawy_nieodswiezone(wiersze, dzieci, [0], naglowek_inny, pozycje), ([], False))


class TestPodpowiedzWRaporcie(unittest.TestCase):
    DOKUMENTY = [
        dict(dok(zestaw_pozycje(("100.00", "23.00", "123.00")), "150.00", "34.50", "184.50"), id="zestaw"),
        dict(dok([poz("100.00", "23.00", "100.00")], "100.00", "23.00", "100.00"), id="brutto1"),
        dict(dok([poz("200.00", "46.00", "200.00")], "200.00", "46.00", "200.00"), id="brutto2"),
        dict(dok([poz("100.00", "23.00", "123.00")], "100.00", "23.00", "123.50"), id="inna"),
        dict(dok([poz("100.00", "23.00", "123.00")], "100.00", "23.00", "123.00"), id="ok"),
        dict(dok([poz("100.00", "23.00", "123.00")], "100.00", "23.00", "123.005"), id="drobiazg"),
    ]

    def test_podsumowanie(self):
        wyniki, p = sprawdz_partie(self.DOKUMENTY)
        self.assertEqual(p["podpowiedzi"], {bledy.ZESTAW_NIEODSWIEZONY: 1, bledy.BRUTTO_ROWNE_NETTO: 2, INNA: 1})
        t = tekst_podsumowania(p, wyniki)
        self.assertIn("Podpowiedź przyczyny niespójności (liczba dokumentów): "
                      "ZESTAW_NIEODSWIEZONY=1, BRUTTO_ROWNE_NETTO=2, inna=1", t)

    def test_brak_sekcji_gdy_brak_niespojnosci(self):
        wyniki, p = sprawdz_partie(self.DOKUMENTY[4:])
        self.assertEqual(p["podpowiedzi"], {})
        self.assertNotIn("Podpowiedź przyczyny", tekst_podsumowania(p, wyniki))

    def test_cli_json_i_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            wej, wyj_j, wyj_c = (os.path.join(tmp, n) for n in ("d.json", "w.json", "w.csv"))
            with open(wej, "w", encoding="utf-8") as f:
                json.dump(self.DOKUMENTY, f)
            with contextlib.redirect_stdout(io.StringIO()):
                main([wej, "--json", wyj_j, "--csv", wyj_c])
            with open(wyj_j, encoding="utf-8") as f:
                raport = {r["id"]: r for r in json.load(f)}
            with open(wyj_c, encoding="utf-8-sig", newline="") as f:
                wiersze = {r["id"]: r for r in csv.DictReader(f, delimiter=";")}
        for r in raport.values():
            self.assertTrue(all("podpowiedz" in n for n in r["niespojnosci"]))
        self.assertEqual(raport["zestaw"]["podpowiedz"], "ZESTAW_NIEODSWIEZONY")
        self.assertEqual(raport["zestaw"]["przyczyny"][0]["zestawy"][0]["dowody"][0]["dowod"],
                         "roznica_rowna_wartosci_dziecka")
        self.assertEqual({k: v["podpowiedz"] for k, v in wiersze.items()},
                         {"zestaw": "ZESTAW_NIEODSWIEZONY", "brutto1": "BRUTTO_ROWNE_NETTO",
                          "brutto2": "BRUTTO_ROWNE_NETTO", "inna": "inna", "drobiazg": ""})
        self.assertEqual(KOLUMNY_CSV[-1], "podpowiedz")

    def test_podpowiedz_dokumentu_wybiera_najwazniejsza(self):
        n = lambda h, drobiazg=False: {"podpowiedz": h, "drobiazg": drobiazg}
        self.assertEqual(podpowiedz_dokumentu([n(INNA), n(bledy.BRUTTO_ROWNE_NETTO)]), bledy.BRUTTO_ROWNE_NETTO)
        self.assertEqual(podpowiedz_dokumentu([n(bledy.BRUTTO_ROWNE_NETTO), n(bledy.ZESTAW_NIEODSWIEZONY)]),
                         bledy.ZESTAW_NIEODSWIEZONY)
        self.assertIsNone(podpowiedz_dokumentu([n("POLGROSZ", True)]))
        self.assertIsNone(podpowiedz_dokumentu([]))

    def test_dokument_bez_kwot_pozycji(self):
        d = {"id": "x", "suma_netto": "10.00", "suma_vat": "2.30", "suma_brutto": "13.00",
             "pozycje": [{"ilosc": 1, "cena_netto_jedn": "10", "stawka_vat": 23}]}
        w = sprawdz_dokument(d)
        self.assertEqual(w["dane"], "brak_kwot")
        self.assertEqual({n["podpowiedz"] for n in w["niespojnosci"]}, {INNA})

    def test_dokument_niepelny_ma_podpowiedzi(self):
        d = {"id": "x", "suma_netto": "100.00", "suma_vat": "23.00", "suma_brutto": "100.00",
             "pozycje": [{"ilosc": 1, "cena_netto_jedn": "100", "stawka_vat": 23, "netto": "100.00", "brutto": "100.00"}]}
        w = sprawdz_dokument(d)
        self.assertEqual(w["dane"], "brak_vat")
        self.assertIn(bledy.BRUTTO_ROWNE_NETTO, kody(w))
        self.assertEqual(w["status"], "niespojny")


if __name__ == "__main__":
    unittest.main()
