import random
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, oblicz, sprawdz_spojnosc, Pozycja
from amounts_calc.config import (Konfiguracja, ROZKLAD_NAJWIEKSZA, ROZKLAD_PROPORCJONALNIE, ROZKLADY,
                                 TRYB_BRUTTO, TRYB_NETTO, VAT_PER_STAWKA)

STAWKI = (23, 8, 5, 0, "zw", "np")


def netto(ilosc, cena, stawka=23):
    return Pozycja(ilosc=ilosc, cena_netto_jedn=cena, stawka_vat=stawka)


def brutto(ilosc, cena, stawka=23):
    return Pozycja(ilosc=ilosc, cena_brutto_jedn=cena, stawka_vat=stawka)


def sprawdz_niezmienniki(tc, d):
    for p in d.pozycje:
        tc.assertEqual(p.netto + p.vat, p.brutto)
    tc.assertEqual(sum((p.netto for p in d.pozycje), D(0)), d.suma_netto)
    tc.assertEqual(sum((p.vat for p in d.pozycje), D(0)), d.suma_vat)
    tc.assertEqual(sum((p.brutto for p in d.pozycje), D(0)), d.suma_brutto)
    tc.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)
    tc.assertEqual(sprawdz_spojnosc(d), [])


class TestRozkladKorekty(unittest.TestCase):
    def test_domyslnie_najwieksza(self):
        self.assertEqual(Konfiguracja().rozklad_korekty, ROZKLAD_NAJWIEKSZA)
        a = oblicz([netto(1, "0.33")] * 3)
        b = oblicz([netto(1, "0.33")] * 3, rozklad_korekty=ROZKLAD_NAJWIEKSZA)
        self.assertEqual(a, b)

    def test_3_x_033(self):
        d1 = oblicz([netto(1, "0.33")] * 3, rozklad_korekty=ROZKLAD_NAJWIEKSZA)
        d2 = oblicz([netto(1, "0.33")] * 3, rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        self.assertEqual([p.vat for p in d1.pozycje], [D("0.07"), D("0.08"), D("0.08")])
        self.assertEqual([p.vat for p in d2.pozycje], [D("0.08"), D("0.08"), D("0.07")])
        for d in (d1, d2):
            self.assertEqual(d.suma_vat, D("0.23"))
            sprawdz_niezmienniki(self, d)

    def test_tysiac_x_001_netto(self):
        d1 = oblicz([netto(1, "0.01")] * 1000, rozklad_korekty=ROZKLAD_NAJWIEKSZA)
        d2 = oblicz([netto(1, "0.01")] * 1000, rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        self.assertEqual(max(p.vat for p in d1.pozycje), D("2.30"))   # cała korekta na jednej
        self.assertEqual(max(p.vat for p in d2.pozycje), D("0.01"))   # po 1 gr
        self.assertEqual(sum(1 for p in d2.pozycje if p.vat), 230)
        self.assertEqual([p.indeks for p in d2.pozycje if p.vat], list(range(230)))  # remis -> niski indeks
        for d in (d1, d2):
            self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("10.00"), D("2.30"), D("12.30")))
            sprawdz_niezmienniki(self, d)

    def test_tysiac_x_001_brutto(self):
        d1 = oblicz([brutto(1, "0.01")] * 1000, tryb=TRYB_BRUTTO, rozklad_korekty=ROZKLAD_NAJWIEKSZA)
        d2 = oblicz([brutto(1, "0.01")] * 1000, tryb=TRYB_BRUTTO, rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        for d in (d1, d2):
            self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("8.13"), D("1.87"), D("10.00")))
            sprawdz_niezmienniki(self, d)
        self.assertEqual(max(p.netto for p in d2.pozycje), D("0.01"))
        self.assertEqual(sum(1 for p in d2.pozycje if p.netto), 813)
        self.assertGreaterEqual(min(p.netto for p in d2.pozycje), D(0))
        self.assertGreaterEqual(min(p.vat for p in d2.pozycje), D(0))
        # znana patologia metody "najwieksza": cała korekta spada na jedną pozycję i robi z niej ujemne netto
        self.assertEqual(min(p.netto for p in d1.pozycje), D("-1.86"))

    def test_korekta_zerowa_nic_nie_zmienia(self):
        poz = [netto(2, "10.00"), netto(1, "5.00", 8)]
        self.assertEqual(oblicz(poz, rozklad_korekty=ROZKLAD_NAJWIEKSZA),
                         oblicz(poz, rozklad_korekty=ROZKLAD_PROPORCJONALNIE))

    def test_per_pozycja_ignoruje_rozklad(self):
        poz = [netto(1, "0.33")] * 3
        a = oblicz(poz, tryb_vat="per_pozycja", rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        b = oblicz(poz, tryb_vat="per_pozycja", rozklad_korekty=ROZKLAD_NAJWIEKSZA)
        self.assertEqual(a, b)

    def test_rozklad_z_konfiguracji_i_nadpisanie(self):
        k = Konfiguracja(rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        poz = [netto(1, "0.33")] * 3
        self.assertEqual([p.vat for p in oblicz(poz, konfiguracja=k).pozycje], [D("0.08"), D("0.08"), D("0.07")])
        self.assertEqual([p.vat for p in oblicz(poz, konfiguracja=k, rozklad_korekty=ROZKLAD_NAJWIEKSZA).pozycje],
                         [D("0.07"), D("0.08"), D("0.08")])

    def test_zly_rozklad(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([netto(1, "1")], rozklad_korekty="losowo")
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNY_TRYB)
        with self.assertRaises(bledy.BladWalidacji):
            Konfiguracja(rozklad_korekty="x")

    def test_wieksze_reszty_dostaja_grosz_pierwsze(self):
        # exact vat: 0.0759 (0.33), 0.0782 (0.34), 0.0736 (0.32); suma netto 0.99 -> vat 0.23
        # podłogi 0.07 x3 = 0.21, brak 2 gr -> dostają pozycje z resztami 0.82 i 0.59 (0.34 i 0.33)
        d = oblicz([netto(1, "0.32"), netto(1, "0.33"), netto(1, "0.34")], rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        self.assertEqual([p.vat for p in d.pozycje], [D("0.07"), D("0.08"), D("0.08")])

    def test_rozne_stawki_osobno(self):
        d = oblicz([netto(1, "0.33", 23)] * 3 + [netto(1, "0.33", 8)] * 3 + [netto(1, "1", "zw")],
                   rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
        self.assertEqual(d.stawka("23").vat, D("0.23"))
        self.assertEqual(d.stawka("8").vat, D("0.08"))
        sprawdz_niezmienniki(self, d)

    def test_losowe_zestawy_obie_metody(self):
        rng = random.Random(424242)
        for tryb in (TRYB_NETTO, TRYB_BRUTTO):
            pole = "cena_netto_jedn" if tryb == TRYB_NETTO else "cena_brutto_jedn"
            for _ in range(300):
                poz = [Pozycja(**{"ilosc": D(rng.randint(0, 3000)) / D(rng.choice((1, 10, 100))),
                                  pole: D(rng.randint(0, 100000)) / D(rng.choice((100, 1000))),
                                  "rabat_proc": D(rng.randint(0, 5000)) / D(100) if rng.random() < .4 else 0,
                                  "stawka_vat": rng.choice(STAWKI)})
                       for _ in range(rng.randint(0, 40))]
                wyniki = {}
                for rozklad in ROZKLADY:
                    d = oblicz(poz, tryb=tryb, tryb_vat=VAT_PER_STAWKA, rozklad_korekty=rozklad)
                    sprawdz_niezmienniki(self, d)
                    wyniki[rozklad] = d
                a, b = wyniki[ROZKLAD_NAJWIEKSZA], wyniki[ROZKLAD_PROPORCJONALNIE]
                # sumy dokumentu nie zależą od metody rozkładu
                self.assertEqual((a.suma_netto, a.suma_vat, a.suma_brutto), (b.suma_netto, b.suma_vat, b.suma_brutto))
                self.assertEqual([(s.netto, s.vat) for s in a.podsumowanie], [(s.netto, s.vat) for s in b.podsumowanie])

    def test_proporcjonalnie_nie_odbiega_od_dokladnej_wartosci_o_wiecej_niz_grosz(self):
        rng = random.Random(99)
        for _ in range(200):
            poz = [netto(D(rng.randint(1, 50)), D(rng.randint(1, 500)) / 100, rng.choice((23, 8))) for _ in range(rng.randint(1, 30))]
            d = oblicz(poz, rozklad_korekty=ROZKLAD_PROPORCJONALNIE)
            for p in d.pozycje:
                dokladny = p.netto * D(p.stawka_vat) / 100
                self.assertLess(abs(p.vat - dokladny), D("0.01"))


if __name__ == "__main__":
    unittest.main()
