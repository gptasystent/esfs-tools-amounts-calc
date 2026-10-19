"""Losowo uszkadzane dokumenty nie mogą przerwać partii ani wywrócić CLI (stałe ziarno)."""
import contextlib
import copy
import io
import json
import os
import random
import tempfile
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import oblicz
from amounts_calc.check import STATUSY, main, sprawdz_partie

ZLE_WARTOSCI = [None, "", "abc", -1, "-5", 1.5, True, [], {}, "NaN", "1E+999", D("1E+500"), 10 ** 40, "0,333", "7"]


def dokument(rng, i):
    wej = [{"id": "p%d" % j, "ilosc": D(rng.randint(1, 30)) / 10, "cena_netto_jedn": D(rng.randint(1, 9999)) / 100,
            "rabat_proc": rng.choice((0, 5, 10)), "stawka_vat": rng.choice((23, 8, 5, 0, "zw"))}
           for j in range(rng.randint(0, 6))]
    if len(wej) > 2 and rng.random() < 0.4:
        wej[1]["parent_id"] = "p0"
        wej[2]["parent_id"] = "p0"
    w = oblicz(wej)
    return {"id": i, "typ": rng.choice(("FV", "KOREKTA", None)), "suma_netto": w.suma_netto, "suma_vat": w.suma_vat,
            "suma_brutto": w.suma_brutto,
            "pozycje": [dict(e, netto=r.netto, vat=r.vat, brutto=r.brutto) for e, r in zip(wej, w.pozycje)]}


def uszkodz(rng, d):
    d = copy.deepcopy(d)
    for _ in range(rng.randint(1, 3)):
        cel = rng.choice(["dok", "poz", "usun_dok", "usun_poz", "struktura"])
        if cel == "dok":
            d[rng.choice(("suma_netto", "suma_vat", "suma_brutto", "typ", "id", "pozycje"))] = rng.choice(ZLE_WARTOSCI)
        elif cel == "poz" and isinstance(d.get("pozycje"), list) and d["pozycje"]:
            p = rng.choice(d["pozycje"])
            if isinstance(p, dict):
                p[rng.choice(("ilosc", "cena_netto_jedn", "stawka_vat", "netto", "vat", "brutto", "rabat_proc",
                              "id", "parent_id"))] = rng.choice(ZLE_WARTOSCI)
        elif cel == "usun_dok":
            d.pop(rng.choice(("suma_netto", "suma_vat", "suma_brutto", "pozycje")), None)
        elif cel == "usun_poz" and isinstance(d.get("pozycje"), list) and d["pozycje"]:
            p = rng.choice(d["pozycje"])
            if isinstance(p, dict) and p:
                p.pop(rng.choice(sorted(p)), None)
        else:
            d["pozycje"] = rng.choice([[1, 2], "x", [[]], [None], {"a": 1}])
    return d


def oferta(rng, i):
    """Oferta z cenami zakupu i narzutami oraz (czasem) zestawem z własnym narzutem."""
    poz = []
    for j in range(rng.randint(0, 6)):
        p = {"id": "p%d" % j, "ilosc": rng.randint(1, 5), "cena_zakupu_jedn": str(rng.randint(1, 100)),
             "narzut_proc": rng.choice((0, 10, 25)), "stawka_vat": rng.choice((23, 8, "zw")),
             "rabat_proc": rng.choice((0, 5)), "cena_netto_jedn": str(rng.randint(1, 100))}
        v = D(p["ilosc"]) * D(p["cena_zakupu_jedn"]) * (1 + D(p["narzut_proc"]) / 100)
        p.update(netto=str(v.quantize(D("0.01"))), vat="1.00", brutto="2.00")
        poz.append(p)
    if len(poz) > 2 and rng.random() < 0.5:
        poz[1]["parent_id"] = poz[2]["parent_id"] = "p0"
        poz[0]["narzut_proc"] = rng.choice((None, 10))
    return {"id": i, "typ": rng.choice(("OF", "ZK")), "suma_netto": "10.00", "suma_vat": "2.30",
            "suma_brutto": "12.30", "pozycje": poz}


def uszkodz_oferte(rng, d):
    d = copy.deepcopy(d)
    for _ in range(rng.randint(1, 3)):
        if d["pozycje"]:
            p = rng.choice(d["pozycje"])
            p[rng.choice(("cena_zakupu_jedn", "narzut_proc", "marza_proc", "rabat_proc", "ilosc", "netto", "vat",
                          "brutto", "stawka_vat", "cena_netto_jedn", "parent_id", "id"))] = rng.choice(ZLE_WARTOSCI)
        if rng.random() < 0.2:
            d[rng.choice(("suma_netto", "suma_vat", "suma_brutto"))] = rng.choice(ZLE_WARTOSCI)
    return d


class TestOdpornosc(unittest.TestCase):
    def test_uszkodzone_oferty_z_narzutem_i_zestawami(self):
        rng = random.Random(1234)
        dokumenty = [uszkodz_oferte(rng, oferta(rng, i)) for i in range(500)]
        for ujemne in (False, True):
            wyniki, p = sprawdz_partie(dokumenty, dopusc_ujemne=ujemne)
            self.assertEqual(len(wyniki), len(dokumenty))
            self.assertTrue(all(w["status"] in STATUSY for w in wyniki))
            self.assertEqual(sum(p["status"].values()), len(dokumenty))
            for w in wyniki:
                self.assertTrue(all("podpowiedz" in n for n in w["niespojnosci"]))


    def test_uszkodzone_dokumenty_nie_przerywaja_partii(self):
        rng = random.Random(8675309)
        dokumenty = [uszkodz(rng, dokument(rng, i)) for i in range(600)] + ["smiec", 5, None, [1], {}]
        wyniki, p = sprawdz_partie(dokumenty, pomin_typy="KOREKTA")
        self.assertEqual(len(wyniki), len(dokumenty))
        self.assertTrue(all(w["status"] in STATUSY for w in wyniki))
        self.assertEqual(sum(p["status"].values()), len(dokumenty))
        self.assertGreater(p["status"]["blad"], 50)          # uszkodzenia faktycznie dają błędy...
        self.assertGreater(p["status"]["spojny"] + p["status"]["pominiety"], 50)   # ...ale nie wszystkie dokumenty
        for w in wyniki:
            if w["status"] == "blad":
                self.assertTrue(w["blad"]["kod"])

    def test_nieuszkodzone_sa_spojne(self):
        rng = random.Random(1)
        wyniki, p = sprawdz_partie([dokument(rng, i) for i in range(300)])
        self.assertEqual(p["status"]["spojny"], 300, [w for w in wyniki if w["status"] != "spojny"][:1])

    def test_cli_na_uszkodzonych_danych_konczy_sie_kodem_0_lub_1(self):
        rng = random.Random(42)
        dokumenty = [uszkodz(rng, dokument(rng, i)) for i in range(200)]
        with tempfile.TemporaryDirectory() as tmp:
            wej = os.path.join(tmp, "d.json")
            with open(wej, "w", encoding="utf-8") as f:
                json.dump(dokumenty, f, default=str)
            with contextlib.redirect_stdout(io.StringIO()):
                kod = main([wej, "--json", os.path.join(tmp, "w.json"), "--csv", os.path.join(tmp, "w.csv")])
            self.assertIn(kod, (0, 1))
            with open(os.path.join(tmp, "w.json"), encoding="utf-8") as f:
                self.assertIsInstance(json.load(f), list)


if __name__ == "__main__":
    unittest.main()
