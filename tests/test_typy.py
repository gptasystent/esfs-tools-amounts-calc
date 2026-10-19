import contextlib
import io
import json
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy
from amounts_calc.adapter import typ_dokumentu, z_wiersza
from amounts_calc.check import (BRAK_TYPU, main, nazwa_typu, sprawdz_dokument, sprawdz_partie, tekst_podsumowania,
                                zbior_typow)


def faktura(typ=None, id="F", netto="10.00", vat="2.30", brutto="12.30", pozycje_netto="10.00", **extra):
    d = {"id": id, "suma_netto": netto, "suma_vat": vat, "suma_brutto": brutto,
         "pozycje": [{"ilosc": 1, "cena_netto_jedn": pozycje_netto, "stawka_vat": 23, "netto": pozycje_netto,
                      "vat": "2.30", "brutto": "12.30"}]}
    if typ is not None:
        d["typ"] = typ
    d.update(extra)
    return d


def korekta(id="K"):
    """Korekta z założenia: nagłówek (różnica) nie zgadza się z sumą pozycji."""
    return faktura("KOREKTA", id=id, netto="-5.00", vat="-1.15", brutto="-6.15")


class TestTyp(unittest.TestCase):
    def test_nazwa_typu(self):
        self.assertEqual(nazwa_typu("KOREKTA "), "KOREKTA")
        self.assertEqual(nazwa_typu(None), BRAK_TYPU)
        self.assertEqual(nazwa_typu("  "), BRAK_TYPU)
        self.assertEqual(nazwa_typu(3), "3")

    def test_zbior_typow(self):
        self.assertEqual(zbior_typow("KOREKTA, roz ,,"), frozenset({"korekta", "roz"}))
        self.assertEqual(zbior_typow(["A", " b "]), frozenset({"a", "b"}))
        self.assertEqual(zbior_typow(None), frozenset())
        self.assertEqual(zbior_typow(""), frozenset())

    def test_typ_dokumentu_domyslne_aliasy_i_mapowanie(self):
        self.assertEqual(typ_dokumentu({"typ": "FV"}), "FV")
        self.assertEqual(typ_dokumentu({"rodzaj": "ZK"}), "ZK")
        self.assertEqual(typ_dokumentu({"rodzaj_dok": "ROZ"}, {"typ": "rodzaj_dok"}), "ROZ")
        self.assertIsNone(typ_dokumentu({"x": 1}))
        self.assertIsNone(typ_dokumentu("nie slownik"))

    def test_z_wiersza_przenosi_typ(self):
        d = z_wiersza({"suma_netto": 0, "suma_vat": 0, "suma_brutto": 0, "pozycje": [], "kod_typu": "ROZ"},
                      {"typ": "kod_typu"})
        self.assertEqual(d["typ"], "ROZ")

    def test_typ_w_wyniku(self):
        self.assertEqual(sprawdz_dokument(faktura("FV"))["typ"], "FV")
        self.assertEqual(sprawdz_dokument(faktura())["typ"], BRAK_TYPU)
        self.assertEqual(sprawdz_dokument(faktura(7))["typ"], "7")


class TestPominTypy(unittest.TestCase):
    def test_pominiety_nie_jest_sprawdzany(self):
        w = sprawdz_dokument(korekta(), pomin_typy="korekta")
        self.assertEqual(w["status"], "pominiety")
        self.assertEqual(w["niespojnosci"], [])
        self.assertIsNone(w["tryb_pasujacy"])
        self.assertEqual(sprawdz_dokument(korekta())["status"], "niespojny")

    def test_pominiety_nawet_gdy_dane_sa_zepsute(self):
        zly = {"id": 1, "typ": "ROZ", "pozycje": "to nie lista"}
        self.assertEqual(sprawdz_dokument(zly, pomin_typy=["roz"])["status"], "pominiety")
        self.assertEqual(sprawdz_dokument(zly)["status"], "blad")

    def test_partia_z_pomijaniem(self):
        dok = [faktura("FV", id="a"), korekta("k1"), korekta("k2"), faktura("ROZ", id="r", netto="99.00"),
               faktura("FV", id="b", netto="99.00")]
        wyniki, p = sprawdz_partie(dok, pomin_typy="KOREKTA,roz")
        self.assertEqual([w["status"] for w in wyniki],
                         ["spojny", "pominiety", "pominiety", "pominiety", "niespojny"])
        self.assertEqual(p["liczba_dokumentow"], 5)
        self.assertEqual(p["pominiete"], 3)
        self.assertEqual(p["pominiete_typy"], ["korekta", "roz"])
        self.assertEqual(p["spojne"], 1)
        self.assertEqual(p["z_problemem"], 1)
        self.assertEqual(p["porownanych"], 2)
        # pominięte nie zasilają rozkładu kodów ani listy największych rozbieżności
        self.assertEqual(set(p["kody"].values()), {1})   # kody tylko z jednego sprawdzonego dokumentu "b"
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, p["kody"])
        self.assertEqual([wyniki[i]["id"] for i in p["najwieksze_indeksy"]], ["b"])

    def test_bez_pomijania_korekty_zalewaja_raport(self):
        dok = [korekta("k%d" % i) for i in range(5)] + [faktura("FV")]
        _, p = sprawdz_partie(dok)
        self.assertEqual(p["z_problemem"], 5)
        _, p2 = sprawdz_partie(dok, pomin_typy="KOREKTA")
        self.assertEqual(p2["z_problemem"], 0)


class TestGrupowaniePoTypie(unittest.TestCase):
    def setUp(self):
        self.dok = [faktura("FV", id=1), faktura("FV", id=2), faktura("FV", id=3, netto="99.00"),
                    faktura("ZK", id=4), {"id": 5, "typ": "ZK", "pozycje": "x"}, korekta("k"),
                    faktura(id=6), faktura(id=7, netto="1.00")]

    def test_liczby_per_typ(self):
        _, p = sprawdz_partie(self.dok, pomin_typy="KOREKTA")
        t = p["wg_typu"]
        self.assertEqual(t["FV"], {"dokumentow": 3, "spojny": 2, "niespojny": 1, "blad": 0, "pominiety": 0})
        self.assertEqual(t["ZK"], {"dokumentow": 2, "spojny": 1, "niespojny": 0, "blad": 1, "pominiety": 0})
        self.assertEqual(t["KOREKTA"], {"dokumentow": 1, "spojny": 0, "niespojny": 0, "blad": 0, "pominiety": 1})
        self.assertEqual(t[BRAK_TYPU]["dokumentow"], 2)
        self.assertEqual(sum(v["dokumentow"] for v in t.values()), len(self.dok))
        self.assertEqual(list(t)[0], "FV")   # malejąco wg liczby dokumentów

    def test_tekst_zawiera_tabele(self):
        wyniki, p = sprawdz_partie(self.dok, pomin_typy="KOREKTA")
        t = tekst_podsumowania(p, wyniki)
        self.assertIn("Wg typu dokumentu:", t)
        wiersz_fv = [l for l in t.splitlines() if l.strip().startswith("FV")][0]
        self.assertEqual(wiersz_fv.split(), ["FV", "3", "2", "1", "0", "0"])
        wiersz_k = [l for l in t.splitlines() if l.strip().startswith("KOREKTA")][0]
        self.assertEqual(wiersz_k.split(), ["KOREKTA", "1", "0", "0", "0", "1"])
        self.assertIn("w tym pominięto: 1", t)


class TestCliPominTypy(unittest.TestCase):
    def uruchom(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            kod = main(list(argv))
        return kod, out.getvalue()

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            wej, wyj = os.path.join(tmp, "d.json"), os.path.join(tmp, "w.json")
            with open(wej, "w", encoding="utf-8") as f:
                json.dump([faktura("FV"), korekta("k1"), korekta("k2")], f)
            kod, out = self.uruchom(wej)
            self.assertEqual(kod, 1)
            kod, out = self.uruchom(wej, "--pomin-typy", "KOREKTA", "--json", wyj)
            self.assertEqual(kod, 0)
            self.assertIn("w tym pominięto: 2", out)
            with open(wyj, encoding="utf-8") as f:
                self.assertEqual(json.load(f), [])

    def test_cli_typ_z_mapowania(self):
        with tempfile.TemporaryDirectory() as tmp:
            wej, map_ = os.path.join(tmp, "d.json"), os.path.join(tmp, "m.json")
            dok = faktura()
            dok["kod_rodzaju"] = "ROZ"
            dok["netto"] = dok.pop("suma_netto")
            dok["netto"] = "50.00"            # niezgodne - ale typ ROZ jest pomijany
            with open(wej, "w", encoding="utf-8") as f:
                json.dump([dok], f)
            with open(map_, "w", encoding="utf-8") as f:
                json.dump({"typ": "kod_rodzaju"}, f)
            self.assertEqual(self.uruchom(wej, "--mapowanie", map_)[0], 1)
            self.assertEqual(self.uruchom(wej, "--mapowanie", map_, "--pomin-typy", "roz")[0], 0)


if __name__ == "__main__":
    unittest.main()
