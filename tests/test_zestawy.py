"""Pozycje nadrzędne/podrzędne (zestawy) - ZK, oferty. Fikcyjny zestaw: krzesło + 4 nogi."""
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, dokument_z_slownika, oblicz, porownaj, sprawdz_spojnosc
from amounts_calc.config import TRYB_BRUTTO, VAT_PER_POZYCJA, VAT_PER_STAWKA
from amounts_calc.hierarchia import liscie_pod, zbuduj_hierarchie


def zestaw_krzeslo(**nadrzedna):
    """Zestaw 'Krzesło z nogami': siedzisko 120,00 + 4 nogi po 7,50, plus osobna poduszka 2 x 15,00 (8%)."""
    nad = {"id": "Z1", "ilosc": 1, "stawka_vat": 23}
    nad.update(nadrzedna)
    return [
        nad,
        {"id": "S1", "parent_id": "Z1", "ilosc": 1, "cena_netto_jedn": "120.00", "stawka_vat": 23},
        {"id": "N1", "parent_id": "Z1", "ilosc": 4, "cena_netto_jedn": "7.50", "stawka_vat": 23},
        {"id": "P1", "ilosc": 2, "cena_netto_jedn": "15.00", "stawka_vat": 8},
    ]


class TestHierarchia(unittest.TestCase):
    def test_brak_hierarchii(self):
        self.assertEqual(zbuduj_hierarchie([(None, None), (1, None)]), {})

    def test_dzieci_i_liscie(self):
        d = zbuduj_hierarchie([("a", None), ("b", "a"), ("c", "a"), ("d", "c"), ("e", None)])
        self.assertEqual(d, {0: [1, 2], 2: [3]})
        self.assertEqual(liscie_pod(0, d), [1, 3])
        self.assertEqual(liscie_pod(2, d), [3])

    def test_bledne_hierarchie(self):
        przypadki = {
            "nieznany rodzic": [(1, 99)],
            "wlasny rodzic": [(1, 1)],
            "cykl": [(1, 2), (2, 3), (3, 1)],
            "duplikat id z dzieckiem": [(1, None), (1, None), (2, 1)],
        }
        for nazwa, pary in przypadki.items():
            with self.subTest(nazwa):
                with self.assertRaises(bledy.BladWalidacji) as cm:
                    zbuduj_hierarchie(pary)
                self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_HIERARCHIA)

    def test_duplikat_id_bez_odwolan_jest_ok(self):
        self.assertEqual(zbuduj_hierarchie([(1, None), (1, None)]), {})

    def test_niehashowalne_id(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            zbuduj_hierarchie([([1], None)])
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_STRUKTURA)


class TestOblicz(unittest.TestCase):
    def test_nadrzedna_liczy_sie_z_dzieci_i_nie_podwaja_sum(self):
        d = oblicz(zestaw_krzeslo())
        z = d.pozycje[0]
        self.assertTrue(z.zestaw)
        self.assertEqual((z.netto, z.vat, z.brutto), (D("150.00"), D("34.50"), D("184.50")))   # 120 + 4*7,50
        self.assertEqual(sum(1 for p in d.pozycje if p.zestaw), 1)
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("180.00"), D("36.90"), D("216.90")))
        self.assertEqual(d.stawka("23").netto, D("150.00"))
        self.assertEqual(d.stawka("8").netto, D("30.00"))

    def test_wlasna_cena_nadrzednej_jest_ignorowana(self):
        a = oblicz(zestaw_krzeslo())
        b = oblicz(zestaw_krzeslo(cena_netto_jedn="999", rabat_proc=50, ilosc=3))
        self.assertEqual((a.suma_netto, a.suma_vat), (b.suma_netto, b.suma_vat))
        self.assertEqual(b.pozycje[0].netto, D("150.00"))

    def test_indeksy_zgodne_z_wejsciem(self):
        d = oblicz(zestaw_krzeslo())
        self.assertEqual([p.indeks for p in d.pozycje], [0, 1, 2, 3])
        self.assertEqual([p.id for p in d.pozycje], ["Z1", "S1", "N1", "P1"])
        self.assertEqual([p.parent_id for p in d.pozycje], [None, "Z1", "Z1", None])

    def test_rabat_dokumentu_wiele_stawek(self):
        d = oblicz(zestaw_krzeslo(), rabat_dokumentu_proc=10)
        self.assertEqual(d.pozycje[0].netto, D("135.00"))
        self.assertEqual(d.stawka("23").netto, D("135.00"))
        self.assertEqual(d.stawka("8").netto, D("27.00"))
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("162.00"), D("33.21"), D("195.21")))

    def test_dzieci_o_roznych_stawkach(self):
        d = oblicz([{"id": "Z", "ilosc": 1, "stawka_vat": 23},
                    {"parent_id": "Z", "ilosc": 1, "cena_netto_jedn": "100", "stawka_vat": 23},
                    {"parent_id": "Z", "ilosc": 1, "cena_netto_jedn": "100", "stawka_vat": 8}])
        self.assertEqual((d.pozycje[0].netto, d.pozycje[0].vat), (D("200.00"), D("31.00")))
        self.assertEqual((d.stawka("23").vat, d.stawka("8").vat, d.suma_vat), (D("23.00"), D("8.00"), D("31.00")))

    def test_zagniezdzone_zestawy(self):
        d = oblicz([{"id": "A", "ilosc": 1, "stawka_vat": 23},
                    {"id": "B", "parent_id": "A", "ilosc": 1, "stawka_vat": 23},
                    {"parent_id": "B", "ilosc": 2, "cena_netto_jedn": "10", "stawka_vat": 23},
                    {"parent_id": "A", "ilosc": 1, "cena_netto_jedn": "5", "stawka_vat": 23}])
        self.assertEqual([p.netto for p in d.pozycje], [D("25.00"), D("20.00"), D("20.00"), D("5.00")])
        self.assertEqual(d.suma_netto, D("25.00"))

    def test_tryb_brutto(self):
        d = oblicz([{"id": "Z", "ilosc": 1, "stawka_vat": 23},
                    {"parent_id": "Z", "ilosc": 1, "cena_brutto_jedn": "123.00", "stawka_vat": 23},
                    {"parent_id": "Z", "ilosc": 2, "cena_brutto_jedn": "12.30", "stawka_vat": 23}], tryb=TRYB_BRUTTO)
        self.assertEqual((d.pozycje[0].brutto, d.suma_brutto), (D("147.60"), D("147.60")))
        self.assertEqual((d.suma_netto, d.suma_vat), (D("120.00"), D("27.60")))

    def test_oba_tryby_vat_i_rozklady_zachowuja_niezmienniki(self):
        for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
            for rozklad in ("najwieksza", "proporcjonalnie"):
                with self.subTest(tv=tv, rozklad=rozklad):
                    d = oblicz(zestaw_krzeslo(), tryb_vat=tv, rozklad_korekty=rozklad, rabat_dokumentu_proc="7.5")
                    liscie = [p for p in d.pozycje if not p.zestaw]
                    self.assertEqual(sum(p.netto for p in liscie), d.suma_netto)
                    self.assertEqual(sum(p.vat for p in liscie), d.suma_vat)
                    self.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)
                    for p in d.pozycje:
                        self.assertEqual(p.netto + p.vat, p.brutto)
                    z = d.pozycje[0]
                    self.assertEqual(z.netto, d.pozycje[1].netto + d.pozycje[2].netto)
                    self.assertEqual(z.vat, d.pozycje[1].vat + d.pozycje[2].vat)
                    self.assertEqual(sprawdz_spojnosc(d), [])

    def test_blad_hierarchii_z_oblicz(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([{"parent_id": "brak", "ilosc": 1, "cena_netto_jedn": "1", "stawka_vat": 23}])
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_HIERARCHIA)
        self.assertIn("pozycje[0].parent_id", cm.exception.pole)

    def test_blad_w_dziecku_wskazuje_indeks_z_wejscia(self):
        poz = zestaw_krzeslo()
        poz[2]["ilosc"] = -4
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz(poz)
        self.assertEqual((cm.exception.kod, cm.exception.pole), (bledy.ILOSC_UJEMNA, "pozycje[2].ilosc"))

    def test_nadrzedna_ze_zla_stawka(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz(zestaw_krzeslo(stawka_vat=7))
        self.assertEqual(cm.exception.kod, bledy.NIEZNANA_STAWKA)

    def test_bez_hierarchii_wynik_jak_dawniej(self):
        d = oblicz([{"ilosc": 2, "cena_netto_jedn": "10", "stawka_vat": 23}])
        self.assertFalse(d.pozycje[0].zestaw)
        self.assertEqual(d.suma_brutto, D("24.60"))


class TestSprawdzSpojnosc(unittest.TestCase):
    def test_slownik_roundtrip(self):
        d = oblicz(zestaw_krzeslo())
        s = d.do_slownika()
        self.assertEqual([p.get("parent_id") for p in s["pozycje"]], [None, "Z1", "Z1", None])
        d2 = dokument_z_slownika(s)
        self.assertTrue(d2.pozycje[0].zestaw)
        self.assertEqual(sprawdz_spojnosc(d2), [])
        self.assertEqual(porownaj(d, d2), [])

    def test_nadrzedna_liczona_podwojnie_w_naglowku(self):
        d = oblicz(zestaw_krzeslo()).do_slownika()
        d["suma_netto"] = "330.00"      # 180 + 150 (zestaw policzony drugi raz)
        d["suma_vat"] = "71.40"
        d["suma_brutto"] = "401.40"
        w = sprawdz_spojnosc(d)
        sumy = {x["pole"]: x for x in w if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU}
        self.assertEqual(sumy["suma_netto"]["oczekiwano"], D("180.00"))
        self.assertEqual(sumy["suma_netto"]["roznica"], D("150.00"))

    def test_zapisana_suma_nadrzednej_inna_niz_dzieci(self):
        d = oblicz(zestaw_krzeslo()).do_slownika()
        d["pozycje"][0]["netto"] = "140.00"
        d["pozycje"][0]["brutto"] = "172.20"
        w = [x for x in sprawdz_spojnosc(d) if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertEqual({(x["zakres"], x["pole"]) for x in w}, {("pozycja:0", "netto"), ("pozycja:0", "brutto")})
        n = [x for x in w if x["pole"] == "netto"][0]
        self.assertEqual((n["oczekiwano"], n["jest"], n["roznica"]), (D("150.00"), D("140.00"), D("-10.00")))
        # sumy dokumentu nadal zgodne - zestaw nie wchodzi do sum
        self.assertFalse([x for x in sprawdz_spojnosc(d) if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU])

    def test_nadrzedna_bez_zapisanych_kwot_jest_uzupelniana(self):
        d = oblicz(zestaw_krzeslo()).do_slownika()
        for k in ("netto", "vat", "brutto"):
            del d["pozycje"][0][k]
        dok = dokument_z_slownika(d)
        self.assertEqual(dok.pozycje[0].netto, D("150.00"))
        self.assertEqual(sprawdz_spojnosc(dok), [])

    def test_stored_bledna_hierarchia(self):
        d = oblicz(zestaw_krzeslo()).do_slownika()
        d["pozycje"][1]["parent_id"] = "nie ma"
        with self.assertRaises(bledy.BladWalidacji) as cm:
            dokument_z_slownika(d)
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_HIERARCHIA)

    def test_podsumowanie_stawek_bez_zestawow(self):
        d = oblicz(zestaw_krzeslo()).do_slownika()
        dok = dokument_z_slownika(d)
        self.assertEqual(sum(s.netto for s in dok.podsumowanie), D("180.00"))

    def test_pozycja_nie_slownik(self):
        d = oblicz(zestaw_krzeslo()).do_slownika()
        d["pozycje"][1] = "x"
        with self.assertRaises(bledy.BladWalidacji) as cm:
            dokument_z_slownika(d)
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_STRUKTURA)


def dokument_zestaw(**nadpisz):
    wej = zestaw_krzeslo()
    d = oblicz(wej, rabat_dokumentu_proc=10)
    dok = {"id": "ZK/1", "typ": "ZK", "rabat_dokumentu_proc": 10, "suma_netto": d.suma_netto,
           "suma_vat": d.suma_vat, "suma_brutto": d.suma_brutto,
           "pozycje": [dict(e, netto=r.netto, vat=r.vat, brutto=r.brutto) for e, r in zip(wej, d.pozycje)]}
    dok.update(nadpisz)
    return dok


class TestCheckZestawy(unittest.TestCase):
    def test_zk_z_zestawem_jest_spojna(self):
        from amounts_calc.check import sprawdz_dokument
        w = sprawdz_dokument(dokument_zestaw())
        self.assertEqual((w["status"], w["niespojnosci"], w["blad"]), ("spojny", [], None))
        self.assertEqual(w["tryb_pasujacy"], "per_stawka")

    def test_mapowanie_nazw_pozycji_nadrzednych(self):
        from amounts_calc.adapter import z_wiersza
        d = z_wiersza({"suma_netto": 1, "suma_vat": 0, "suma_brutto": 1,
                       "pozycje": [{"nr": "A", "ilosc": 1, "stawka_vat": 0},
                                   {"id_nadrzednej": "A", "ilosc": 1, "stawka_vat": 0}]}, {"pozycja": {"id": "nr"}})
        self.assertEqual([p.get("id") for p in d["pozycje"]], ["A", None])
        self.assertEqual(d["pozycje"][1]["parent_id"], "A")

    def test_blad_hierarchii_w_dokumencie_to_blad_w_raporcie(self):
        from amounts_calc.check import sprawdz_dokument
        dok = dokument_zestaw()
        dok["pozycje"][1]["parent_id"] = "nie ma takiej"
        w = sprawdz_dokument(dok)
        self.assertEqual((w["status"], w["blad"]["kod"]), ("blad", bledy.NIEPOPRAWNA_HIERARCHIA))


if __name__ == "__main__":
    unittest.main()
