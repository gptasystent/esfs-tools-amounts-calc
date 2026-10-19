"""Testy własności na losowych (deterministycznych, seed) dokumentach."""
import random
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import oblicz, sprawdz_spojnosc, Pozycja
from amounts_calc.config import TRYB_BRUTTO, TRYB_NETTO, VAT_PER_POZYCJA, VAT_PER_STAWKA

STAWKI = (23, 8, 5, 0, "zw", "np")


def losowy_dokument(rng, tryb):
    pole = "cena_netto_jedn" if tryb == TRYB_NETTO else "cena_brutto_jedn"
    pozycje = []
    for _ in range(rng.randint(0, 12)):
        pozycje.append(Pozycja(**{
            "ilosc": D(rng.randint(0, 5000)) / D(rng.choice((1, 10, 100, 1000))),
            pole: D(rng.randint(0, 2000000)) / D(rng.choice((100, 1000, 10000))),
            "rabat_proc": D(rng.randint(0, 10000)) / D(100),
            "stawka_vat": rng.choice(STAWKI),
        }))
    return pozycje, D(rng.randint(0, 3000)) / D(100)


class TestWlasnosci(unittest.TestCase):
    N = 250

    def kazdy_dokument(self):
        rng = random.Random(20240601)
        for tryb in (TRYB_NETTO, TRYB_BRUTTO):
            for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
                for _ in range(self.N):
                    pozycje, rabat = losowy_dokument(rng, tryb)
                    d = oblicz(pozycje, tryb=tryb, tryb_vat=tv, rabat_dokumentu_proc=rabat if rng.random() < .3 else 0)
                    yield tryb, tv, d

    def test_netto_plus_vat_rowna_sie_brutto(self):
        for tryb, tv, d in self.kazdy_dokument():
            for p in d.pozycje:
                self.assertEqual(p.netto + p.vat, p.brutto, (tryb, tv))
            for s in d.podsumowanie:
                self.assertEqual(s.netto + s.vat, s.brutto)
            self.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)

    def test_suma_pozycji_rowna_sumie_dokumentu(self):
        for tryb, tv, d in self.kazdy_dokument():
            self.assertEqual(sum((p.netto for p in d.pozycje), D(0)), d.suma_netto)
            self.assertEqual(sum((p.vat for p in d.pozycje), D(0)), d.suma_vat)
            self.assertEqual(sum((p.brutto for p in d.pozycje), D(0)), d.suma_brutto)

    def test_suma_stawek_rowna_sumie_dokumentu(self):
        for tryb, tv, d in self.kazdy_dokument():
            self.assertEqual(sum((s.netto for s in d.podsumowanie), D(0)), d.suma_netto)
            self.assertEqual(sum((s.vat for s in d.podsumowanie), D(0)), d.suma_vat)

    def test_sprawdz_spojnosc_pusta_dla_wyniku_oblicz(self):
        for tryb, tv, d in self.kazdy_dokument():
            self.assertEqual(sprawdz_spojnosc(d), [], (tryb, tv))

    def test_kwoty_maja_dwa_miejsca(self):
        for tryb, tv, d in self.kazdy_dokument():
            for v in (d.suma_netto, d.suma_vat, d.suma_brutto, *(p.netto for p in d.pozycje)):
                self.assertEqual(v, v.quantize(D("0.01")))

    def test_vat_zerowe_stawki(self):
        for tryb, tv, d in self.kazdy_dokument():
            for s in d.podsumowanie:
                if s.stawka_vat in ("0", "zw", "np"):
                    self.assertEqual(s.vat, D(0))
                    self.assertEqual(s.netto, s.brutto)

    def test_brutto_pozycji_nie_zalezy_od_trybu_vat_w_trybie_brutto(self):
        rng = random.Random(7)
        for _ in range(self.N):
            pozycje, _r = losowy_dokument(rng, TRYB_BRUTTO)
            a = oblicz(pozycje, tryb=TRYB_BRUTTO, tryb_vat=VAT_PER_POZYCJA)
            b = oblicz(pozycje, tryb=TRYB_BRUTTO, tryb_vat=VAT_PER_STAWKA)
            self.assertEqual([p.brutto for p in a.pozycje], [p.brutto for p in b.pozycje])
            self.assertEqual(a.suma_brutto, b.suma_brutto)

    def test_netto_pozycji_nie_zalezy_od_trybu_vat_w_trybie_netto(self):
        rng = random.Random(8)
        for _ in range(self.N):
            pozycje, _r = losowy_dokument(rng, TRYB_NETTO)
            a = oblicz(pozycje, tryb_vat=VAT_PER_POZYCJA)
            b = oblicz(pozycje, tryb_vat=VAT_PER_STAWKA)
            self.assertEqual(a.suma_netto, b.suma_netto)
            self.assertEqual(a.rozbieznosc_vat, b.rozbieznosc_vat)

    def test_roznica_trybow_vat_to_rozbieznosc(self):
        rng = random.Random(9)
        for _ in range(self.N):
            pozycje, _r = losowy_dokument(rng, TRYB_NETTO)
            a = oblicz(pozycje, tryb_vat=VAT_PER_POZYCJA)
            b = oblicz(pozycje, tryb_vat=VAT_PER_STAWKA)
            self.assertEqual(a.suma_vat - b.suma_vat, a.rozbieznosc_vat)

    def test_deterministyczne_i_niezalezne_od_kolejnosci_wywolan(self):
        rng = random.Random(10)
        pozycje, _r = losowy_dokument(rng, TRYB_NETTO)
        self.assertEqual(oblicz(pozycje), oblicz(list(pozycje)))

    def test_permutacja_pozycji_nie_zmienia_sum_per_pozycja(self):
        rng = random.Random(11)
        for _ in range(self.N):
            pozycje, _r = losowy_dokument(rng, TRYB_NETTO)
            tasowane = list(pozycje)
            rng.shuffle(tasowane)
            a, b = oblicz(pozycje, tryb_vat=VAT_PER_POZYCJA), oblicz(tasowane, tryb_vat=VAT_PER_POZYCJA)
            self.assertEqual((a.suma_netto, a.suma_vat, a.suma_brutto), (b.suma_netto, b.suma_vat, b.suma_brutto))

    def test_permutacja_pozycji_nie_zmienia_sum_per_stawka(self):
        rng = random.Random(12)
        for _ in range(self.N):
            pozycje, _r = losowy_dokument(rng, TRYB_BRUTTO)
            tasowane = list(pozycje)
            rng.shuffle(tasowane)
            a = oblicz(pozycje, tryb=TRYB_BRUTTO)
            b = oblicz(tasowane, tryb=TRYB_BRUTTO)
            self.assertEqual((a.suma_netto, a.suma_vat, a.suma_brutto), (b.suma_netto, b.suma_vat, b.suma_brutto))


if __name__ == "__main__":
    unittest.main()
