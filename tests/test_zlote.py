"""Złote przypadki: generator jest deterministyczny, samodzielny, a oczekiwane = wynik oblicz()."""
import contextlib
import io
import json
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import oblicz
from amounts_calc import zlote


def oblicz_przypadek(p):
    if p["rodzaj"] == "pozycja":
        pozycje = [{"ilosc": 1, "cena_netto_jedn": p["netto"], "stawka_vat": p["stawka"]}]
    elif p["rodzaj"] == "rabat":
        pozycje = [{"ilosc": p["ilosc"], "cena_netto_jedn": p["cena_netto_jedn"], "rabat_proc": p["rabat_proc"],
                    "stawka_vat": p["stawka"]}]
    else:
        pozycje = [{"ilosc": 1, "cena_netto_jedn": x["netto"], "stawka_vat": x["stawka"]} for x in p["pozycje"]]
    return oblicz(pozycje, tryb_vat="per_pozycja", dopusc_ujemne=True)


class TestGenerator(unittest.TestCase):
    def test_deterministyczny(self):
        a, b = zlote.dokument(1, 500), zlote.dokument(1, 500)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(len(a["przypadki"]), 500)

    def test_inne_ziarno_daje_inne_losowe_przypadki_ale_te_same_graniczne(self):
        a, b = zlote.generuj(1, 300), zlote.generuj(2, 300)
        stale = len(zlote._graniczne())
        self.assertEqual(a[:stale], b[:stale])
        self.assertNotEqual(a[stale:], b[stale:])

    def test_prefiks_jest_stabilny_przy_zmianie_n(self):
        self.assertEqual(zlote.generuj(5, 100), zlote.generuj(5, 400)[:100])

    def test_n_mniejsze_od_granicznych(self):
        self.assertEqual(len(zlote.generuj(1, 3)), 3)
        self.assertEqual(zlote.generuj(1, 0), [])

    def test_przyklad_ze_specyfikacji(self):
        p = zlote.generuj(1, 1)[0]
        self.assertEqual((p["netto"], p["stawka"], p["oczekiwane"]),
                         ("49.50", 23, {"netto": "49.50", "vat": "11.39", "brutto": "60.89"}))

    def test_wszystkie_rodzaje_i_stawki_wystepuja(self):
        przyp = zlote.generuj(1, 2000)
        self.assertEqual({p["rodzaj"] for p in przyp}, {"pozycja", "rabat", "suma"})
        stawki = {p["stawka"] for p in przyp if "stawka" in p}
        self.assertEqual(stawki, set(zlote.STAWKI))
        nazwy = {p["nazwa"].split("-")[0] for p in przyp[len(zlote._graniczne()):]}
        self.assertTrue({"losowa", "polgrosze", "mala", "duza", "ujemna", "niezaokraglona", "suma", "rabat"} <= nazwy)
        self.assertTrue(any(D(p["oczekiwane"]["netto"]) < 0 for p in przyp))

    def test_polgrosze_naprawde_wypadaja_w_pol_grosza(self):
        for p in zlote.generuj(3, 1500):
            if p["nazwa"].startswith("polgrosze"):
                vat = D(p["netto"]) * (D(p["stawka"]) / 100)
                self.assertEqual(vat * 100 % 1, D("0.5"), p)

    def test_brutto_to_netto_plus_vat_i_zw_np_bez_vat(self):
        for p in zlote.generuj(4, 1500):
            o = p["oczekiwane"]
            self.assertEqual(D(o["netto"]) + D(o["vat"]), D(o["brutto"]))
            if p.get("stawka") in ("zw", "np"):
                self.assertEqual(D(o["vat"]), 0)

    def test_plik_jest_samodzielny_zwykly_json(self):
        wyjscie = io.StringIO()
        with contextlib.redirect_stdout(wyjscie):
            self.assertEqual(zlote.main(["--seed", "7", "--n", "120"]), 0)
        d = json.loads(wyjscie.getvalue())          # bez żadnej klasy z biblioteki
        self.assertEqual((d["format"], d["seed"], len(d["przypadki"])), (zlote.FORMAT, 7, 120))
        for p in d["przypadki"]:
            self.assertTrue({"nazwa", "rodzaj", "oczekiwane"} <= set(p))
            self.assertTrue(all(isinstance(v, str) for v in p["oczekiwane"].values()))
        self.assertIn("ROUND_HALF_UP", d["zasada"])

    def test_zly_argument(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(zlote.main(["--n", "-1"]), 2)


class TestZgodnoscZOblicz(unittest.TestCase):
    def sprawdz(self, przypadki):
        for p in przypadki:
            with self.subTest(nazwa=p["nazwa"]):
                r = oblicz_przypadek(p)
                o = p["oczekiwane"]
                oczek = (D(o["netto"]), D(o["vat"]), D(o["brutto"]))
                self.assertEqual((r.suma_netto, r.suma_vat, r.suma_brutto), oczek, p)
                if p["rodzaj"] != "suma":
                    poz = r.pozycje[0]
                    self.assertEqual((poz.netto, poz.vat, poz.brutto), oczek)

    def test_graniczne(self):
        self.sprawdz(zlote.generuj(1, len(zlote._graniczne())))

    def test_losowe_wielu_ziaren(self):
        for seed in (1, 2, 3):
            self.sprawdz(zlote.generuj(seed, 700))

    def test_zasada_pozycji_a_oczekiwane_per_stawka_dla_jednej_pozycji(self):
        n, v, b = zlote.kwoty_pozycji("49.50", 23)
        self.assertEqual((n, v, b), (D("49.50"), D("11.39"), D("60.89")))
        self.assertEqual(zlote.kwoty_pozycji("-0.125", 23)[0], D("-0.13"))
        self.assertEqual(zlote.kwoty_pozycji("100", "zw"), (D("100.00"), D("0.00"), D("100.00")))


if __name__ == "__main__":
    unittest.main()
