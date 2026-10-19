"""Zestawy (pozycje nadrzędne) z własnym narzutem lub rabatem: różnica względem sumy dzieci to informacja."""
import json
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.check import sprawdz_dokument, sprawdz_partie
from amounts_calc.hierarchia import zbuduj_hierarchie
from amounts_calc.model import dokument_z_slownika
from amounts_calc.oferty import czynnik_zestawu, zestawy_z_narzutem


def dziecko(id_, netto, vat, brutto, **extra):
    d = {"id": id_, "parent_id": "Z", "ilosc": 1, "cena_netto_jedn": netto, "stawka_vat": 23, "netto": netto,
         "vat": vat, "brutto": brutto}
    d.update(extra)
    return d


def zestaw(netto, vat, brutto, **extra):
    d = {"id": "Z", "ilosc": 1, "stawka_vat": 23, "netto": netto, "vat": vat, "brutto": brutto}
    d.update(extra)
    return d


# dzieci: 100,00 + 50,00 = 150,00 netto, VAT 34,50, brutto 184,50
DZIECI = [dziecko("A", "100.00", "23.00", "123.00"), dziecko("B", "50.00", "11.50", "61.50")]


def dok(pozycje, netto="150.00", vat="34.50", brutto="184.50", **extra):
    d = {"id": "ZK/1", "typ": "ZK", "suma_netto": netto, "suma_vat": vat, "suma_brutto": brutto, "pozycje": pozycje}
    d.update(extra)
    return d


def kody(w):
    return {p["kod"] for p in w["przyczyny"]}


def finding_kody(w):
    return {n["kod"] for n in w["niespojnosci"]}


class TestCzynnik(unittest.TestCase):
    def test_czynniki(self):
        tabela = [({"narzut_proc": 10}, "1.1"), ({"marza_proc": 20}, "1.25"), ({"rabat_proc": 10}, "0.9"),
                  ({"narzut_proc": 10, "rabat_proc": 10}, "0.99"), ({"narzut_proc": 0}, "1"), ({}, None),
                  ({"narzut_proc": 10, "marza_proc": 10}, None), ({"marza_proc": 100}, None),
                  ({"narzut_proc": "abc"}, None)]
        for p, oczek in tabela:
            with self.subTest(p=p):
                c = czynnik_zestawu(p)
                self.assertEqual(c if c is None else c.quantize(D("0.0001")), None if oczek is None else D(oczek).quantize(D("0.0001")))


class TestZestawZNarzutem(unittest.TestCase):
    def test_bez_narzutu_zestaw_rozny_od_dzieci_jak_dotad(self):
        w = sprawdz_dokument(dok([zestaw("165.00", "37.95", "202.95")] + DZIECI))
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, finding_kody(w))
        self.assertNotIn(bledy.ZESTAW_Z_NARZUTEM, kody(w))

    def test_narzut_zestawu_tlumaczy_roznice(self):
        w = sprawdz_dokument(dok([zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI))
        self.assertEqual((w["status"], w["blad"]), ("spojny", None))
        self.assertNotIn(bledy.ZESTAW_ROZNY_OD_DZIECI, finding_kody(w))
        self.assertEqual(kody(w), {bledy.ZESTAW_Z_NARZUTEM})
        (p,) = w["przyczyny"]
        self.assertTrue(p["informacja"])
        z = p["zestawy"][0]
        self.assertEqual((z["indeks"], z["id"], z["suma_dzieci"], z["zapisane"], z["oczekiwane"], z["roznica"]),
                         (0, "Z", D("150.00"), D("165.00"), D("165.00"), D("15.00")))
        self.assertFalse(p["naglowek_uwzglednia_zestawy"])        # nagłówek = suma dzieci

    def test_rabat_zestawu(self):
        w = sprawdz_dokument(dok([zestaw("135.00", "31.05", "166.05", rabat_proc=10)] + DZIECI))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))

    def test_marza_zestawu(self):
        w = sprawdz_dokument(dok([zestaw("187.50", "43.13", "230.63", marza_proc=20)] + DZIECI))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))

    def test_narzut_i_rabat_razem(self):
        w = sprawdz_dokument(dok([zestaw("148.50", "34.16", "182.66", narzut_proc=10, rabat_proc=10)] + DZIECI))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))
        self.assertEqual(w["przyczyny"][0]["zestawy"][0]["czynnik"], D("0.990000"))

    def test_kwota_niezgodna_z_narzutem_zestawu_zostaje_bledem(self):
        w = sprawdz_dokument(dok([zestaw("160.00", "36.80", "196.80", narzut_proc=10)] + DZIECI))
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, finding_kody(w))
        self.assertNotIn(bledy.ZESTAW_Z_NARZUTEM, kody(w))

    def test_vat_i_brutto_tez_musza_pasowac(self):
        w = sprawdz_dokument(dok([zestaw("165.00", "30.00", "195.00", narzut_proc=10)] + DZIECI))
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, finding_kody(w))

    def test_tolerancja_grosza_na_netto(self):
        ok = sprawdz_dokument(dok([zestaw("165.01", "37.95", "202.96", narzut_proc=10)] + DZIECI))
        self.assertEqual(kody(ok), {bledy.ZESTAW_Z_NARZUTEM})
        zle = sprawdz_dokument(dok([zestaw("165.02", "37.95", "202.97", narzut_proc=10)] + DZIECI))
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, finding_kody(zle))

    def test_zadeklarowany_narzut_bez_roznicy_nic_nie_zglasza(self):
        w = sprawdz_dokument(dok([zestaw("150.00", "34.50", "184.50", narzut_proc=10)] + DZIECI))
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))

    def test_zestaw_bez_zapisanych_kwot(self):
        z = {"id": "Z", "ilosc": 1, "stawka_vat": 23, "narzut_proc": 10}
        w = sprawdz_dokument(dok([z] + DZIECI))
        self.assertEqual((w["status"], w["przyczyny"]), ("spojny", []))

    def test_dzieci_o_roznych_stawkach(self):
        dzieci = [dziecko("A", "100.00", "23.00", "123.00"), dziecko("B", "100.00", "8.00", "108.00", stawka_vat=8)]
        z = zestaw("220.00", "34.10", "254.10", narzut_proc=10)
        w = sprawdz_dokument(dok([z] + dzieci, "200.00", "31.00", "231.00"))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))

    def test_zestaw_zagniezdzony_z_narzutem(self):
        pozycje = [
            {"id": "Z", "ilosc": 1, "stawka_vat": 23},                                                  # zewnętrzny, bez kwot
            dict(zestaw("110.00", "25.30", "135.30", narzut_proc=10), id="W", parent_id="Z"),            # wewnętrzny
            dict(dziecko("A", "100.00", "23.00", "123.00"), parent_id="W"),
        ]
        w = sprawdz_dokument(dok(pozycje, "100.00", "23.00", "123.00"))
        self.assertEqual((w["status"], kody(w)), ("spojny", {bledy.ZESTAW_Z_NARZUTEM}))
        self.assertEqual(w["przyczyny"][0]["zestawy"][0]["id"], "W")

    def test_cena_zestawu_nie_zmienia_sum_dokumentu(self):
        w = sprawdz_dokument(dok([zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI))
        self.assertEqual(w["tryb_pasujacy"], "oba")


class TestNaglowekZNarzutemZestawow(unittest.TestCase):
    STANDALONE = {"ilosc": 1, "cena_netto_jedn": "20.00", "stawka_vat": 23, "netto": "20.00", "vat": "4.60", "brutto": "24.60"}

    def test_naglowek_liczy_zestaw_z_jego_narzutem(self):
        # zestaw 150 -> 165 (narzut 10%) + osobna pozycja 20,00; nagłówek = 165 + 20 = 185,00
        pozycje = [zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI + [self.STANDALONE]
        w = sprawdz_dokument(dok(pozycje, "185.00", "42.55", "227.55"))
        self.assertEqual((w["status"], w["niespojnosci"], kody(w)), ("spojny", [], {bledy.ZESTAW_Z_NARZUTEM}))
        self.assertTrue(w["przyczyny"][0]["naglowek_uwzglednia_zestawy"])
        self.assertEqual(w["tryb_pasujacy"], "oba")

    def test_naglowek_liczy_same_dzieci(self):
        pozycje = [zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI + [self.STANDALONE]
        w = sprawdz_dokument(dok(pozycje, "170.00", "39.10", "209.10"))
        self.assertEqual((w["status"], w["niespojnosci"]), ("spojny", []))
        self.assertFalse(w["przyczyny"][0]["naglowek_uwzglednia_zestawy"])

    def test_naglowek_nie_pasuje_do_zadnej_wersji(self):
        pozycje = [zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI + [self.STANDALONE]
        w = sprawdz_dokument(dok(pozycje, "180.00", "41.40", "221.40"))
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.NAGLOWEK_WYZSZY, kody(w))
        self.assertIn(bledy.ZESTAW_Z_NARZUTEM, kody(w))

    def test_naglowek_musi_pasowac_we_wszystkich_polach(self):
        pozycje = [zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI + [self.STANDALONE]
        w = sprawdz_dokument(dok(pozycje, "185.00", "42.55", "227.00"))        # brutto nie pasuje
        self.assertEqual(w["status"], "niespojny")


class TestRaportZestawow(unittest.TestCase):
    def test_partia_i_json(self):
        dokumenty = [dict(dok([zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI), id="z1"),
                     dict(dok([zestaw("165.00", "37.95", "202.95")] + DZIECI), id="z2")]
        wyniki, p = sprawdz_partie(dokumenty)
        self.assertEqual((p["spojne"], p["status"]["niespojny"]), (1, 1))
        self.assertEqual(p["kody"][bledy.ZESTAW_Z_NARZUTEM], 1)
        self.assertEqual(p["kody"][bledy.ZESTAW_ROZNY_OD_DZIECI], 1)

    def test_zestawy_z_narzutem_na_dokumencie_z_bazy(self):
        d = dok([zestaw("165.00", "37.95", "202.95", narzut_proc=10)] + DZIECI)
        zapis = dokument_z_slownika(d)
        pozycje = d["pozycje"]
        dzieci = zbuduj_hierarchie([(p.get("id"), p.get("parent_id")) for p in pozycje])
        (z,) = zestawy_z_narzutem(pozycje, zapis, dzieci)
        self.assertEqual(z["oczekiwane"], D("165.00"))
        self.assertEqual(json.dumps(z["id"]), '"Z"')


if __name__ == "__main__":
    unittest.main()
