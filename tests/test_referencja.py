"""Porównanie biblioteki z niezależną referencją na Fraction (2000 losowych dokumentów)."""
import random
import unittest
from decimal import Decimal as D
from fractions import Fraction

from tests import _bootstrap  # noqa: F401
from tests import referencja as ref
from amounts_calc import oblicz, Pozycja
from amounts_calc.config import VAT_PER_POZYCJA

STAWKI = ((23, 23), (8, 8), (5, 5), (0, 0), ("zw", 0), ("np", 0))
LICZBA_DOKUMENTOW = 2000


def losowe_dokumenty(n, ziarno, tylko_bez_rabatow=False):
    rng = random.Random(ziarno)
    for _ in range(n):
        tryb = rng.choice(("netto", "brutto"))
        rabat_dok = D(rng.randint(0, 3000)) / 100 if (rng.random() < 0.3 and not tylko_bez_rabatow) else D(0)
        pozycje = []
        for _ in range(rng.randint(1, 15)):
            etykieta, proc = rng.choice(STAWKI)
            rabat = D(rng.randint(0, 9000)) / 100 if (rng.random() < 0.5 and not tylko_bez_rabatow) else D(0)
            ilosc = D(rng.randint(0, 20000)) / D(rng.choice((1, 10, 100, 1000)))
            cena = D(rng.randint(0, 5000000)) / D(rng.choice((100, 1000, 10000)))
            pozycje.append((ilosc, cena, rabat, etykieta, proc))
        yield tryb, rabat_dok, pozycje


def do_biblioteki(tryb, pozycje):
    pole = "cena_netto_jedn" if tryb == "netto" else "cena_brutto_jedn"
    return [Pozycja(ilosc=i, rabat_proc=r, stawka_vat=e, **{pole: c}) for i, c, r, e, _ in pozycje]


def do_referencji(pozycje):
    return [(i, c, r, proc) for i, c, r, _, proc in pozycje]


def jako_ulamek(d):
    return Fraction(d)


class TestReferencjaWgSpecyfikacji(unittest.TestCase):
    """Te same punkty zaokrąglania => wynik identyczny co do grosza."""

    def test_2000_dokumentow_zgodnosc_dokladna(self):
        for nr, (tryb, rabat_dok, pozycje) in enumerate(losowe_dokumenty(LICZBA_DOKUMENTOW, 20240901)):
            d = oblicz(do_biblioteki(tryb, pozycje), tryb=tryb, rabat_dokumentu_proc=rabat_dok,
                       tryb_vat=VAT_PER_POZYCJA)
            oczekiwane = ref.policz_wg_specyfikacji(do_referencji(pozycje), tryb, rabat_dok)
            for p, (n, v, b) in zip(d.pozycje, oczekiwane):
                self.assertEqual((jako_ulamek(p.netto), jako_ulamek(p.vat), jako_ulamek(p.brutto)), (n, v, b),
                                 "dokument %d pozycja %d" % (nr, p.indeks))
            self.assertEqual(jako_ulamek(d.suma_netto), sum(o[0] for o in oczekiwane))
            self.assertEqual(jako_ulamek(d.suma_vat), sum(o[1] for o in oczekiwane))
            self.assertEqual(jako_ulamek(d.suma_brutto), sum(o[2] for o in oczekiwane))

    def test_2000_dokumentow_per_stawka_sumy_stawek(self):
        # VAT per stawka = zaokrąglony VAT z sumy netto stawki (tryb netto) - liczone referencją
        for nr, (tryb, rabat_dok, pozycje) in enumerate(losowe_dokumenty(LICZBA_DOKUMENTOW, 31337)):
            if tryb != "netto":
                continue
            d = oblicz(do_biblioteki(tryb, pozycje), tryb=tryb, rabat_dokumentu_proc=rabat_dok)
            oczekiwane = ref.policz_wg_specyfikacji(do_referencji(pozycje), tryb, rabat_dok)
            for s in d.podsumowanie:
                idx = [i for i, p in enumerate(pozycje) if p[3] == s.stawka_vat or str(p[3]) == s.stawka_vat]
                suma_netto = sum(oczekiwane[i][0] for i in idx)
                proc = pozycje[idx[0]][4]
                self.assertEqual(jako_ulamek(s.netto), suma_netto, nr)
                self.assertEqual(jako_ulamek(s.vat), ref.zaokraglij(suma_netto * Fraction(proc, 100), 2), nr)


class TestReferencjaDokladna(unittest.TestCase):
    """Zaokrąglenie dopiero na końcu: zgodność tylko do granic wynikających z celowych różnic."""

    def test_2000_dokumentow_w_granicach_bledu(self):
        for nr, (tryb, rabat_dok, pozycje) in enumerate(losowe_dokumenty(LICZBA_DOKUMENTOW, 777)):
            d = oblicz(do_biblioteki(tryb, pozycje), tryb=tryb, rabat_dokumentu_proc=rabat_dok,
                       tryb_vat=VAT_PER_POZYCJA)
            dokladne = ref.policz_dokladnie(do_referencji(pozycje), tryb, rabat_dok)
            for p, (n, v, b), (ilosc, _c, _r, _e, proc) in zip(d.pozycje, dokladne, pozycje):
                kw = b if tryb == "brutto" else n
                kw_lib = p.brutto if tryb == "brutto" else p.netto
                self.assertLessEqual(abs(jako_ulamek(kw_lib) - kw), ref.granica_netto(ilosc, rabat_dok), (nr, p.indeks))
                self.assertLessEqual(abs(jako_ulamek(p.vat) - v), ref.granica_vat(ilosc, proc, tryb, rabat_dok),
                                     (nr, p.indeks))

    def test_bez_rabatow_kwota_pozycji_zgodna_dokladnie(self):
        # bez rabatów cena (<= 4 miejsca) nie jest zaokrąglana, więc kwota pozycji = round(dokładna)
        for nr, (tryb, rabat_dok, pozycje) in enumerate(losowe_dokumenty(LICZBA_DOKUMENTOW, 5150, True)):
            d = oblicz(do_biblioteki(tryb, pozycje), tryb=tryb, tryb_vat=VAT_PER_POZYCJA)
            dokladne = ref.policz_dokladnie(do_referencji(pozycje), tryb, 0)
            for p, (n, v, b) in zip(d.pozycje, dokladne):
                kw = b if tryb == "brutto" else n
                kw_lib = p.brutto if tryb == "brutto" else p.netto
                self.assertEqual(jako_ulamek(kw_lib), ref.zaokraglij(kw, 2), (nr, p.indeks))

    def test_bez_rabatow_vat_rozni_sie_co_najwyzej_o_grosz(self):
        # tu METODY SIĘ CELOWO RÓŻNIĄ: podwójne zaokrąglenie (wartość -> grosz -> VAT -> grosz)
        roznice = 0
        for nr, (tryb, rabat_dok, pozycje) in enumerate(losowe_dokumenty(LICZBA_DOKUMENTOW, 5150, True)):
            if tryb != "netto":
                continue
            d = oblicz(do_biblioteki(tryb, pozycje), tryb=tryb, tryb_vat=VAT_PER_POZYCJA)
            dokladne = ref.policz_dokladnie(do_referencji(pozycje), tryb, 0)
            for p, (_n, v, _b) in zip(d.pozycje, dokladne):
                delta = abs(jako_ulamek(p.vat) - ref.zaokraglij(v, 2))
                self.assertLessEqual(delta, Fraction(1, 100), (nr, p.indeks))
                roznice += delta != 0
        self.assertGreater(roznice, 0, "oczekiwano przynajmniej jednej różnicy wynikającej z podwójnego zaokrąglenia")

    def test_przyklad_podwojnego_zaokraglenia(self):
        # 1 szt. po 0,0218 netto, VAT 23%:
        #   biblioteka: wartość 0,0218 -> 0,02, VAT = 0,02 * 23% = 0,0046 -> 0,00
        #   referencja: VAT = 0,0218 * 23% = 0,005014 -> 0,01
        p = oblicz([Pozycja(ilosc=1, cena_netto_jedn="0.0218")], tryb_vat=VAT_PER_POZYCJA).pozycje[0]
        self.assertEqual((p.netto, p.vat), (D("0.02"), D("0.00")))
        vat_dokladny = ref.policz_dokladnie([(1, D("0.0218"), 0, 23)], "netto")[0][1]
        self.assertEqual(ref.zaokraglij(vat_dokladny, 2), Fraction(1, 100))


class TestSamaReferencja(unittest.TestCase):
    def test_zaokraglij_half_up(self):
        for x, oczek in [("1/200", "1/100"), ("3/200", "1/50"), ("1/250", "0"), ("5/2", "5/2")]:
            self.assertEqual(ref.zaokraglij(Fraction(x), 2), Fraction(oczek))

    def test_referencja_nie_importuje_biblioteki(self):
        with open(ref.__file__, encoding="utf-8") as f:
            zrodlo = f.read()
        self.assertNotIn("import amounts_calc", zrodlo)
        self.assertNotIn("from amounts_calc", zrodlo)


if __name__ == "__main__":
    unittest.main()
