"""oblicz() z ilością zestawu: dzieci na 1 szt., zestaw N x dzieci, sumy bez podwójnego liczenia."""
import random
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, oblicz, porownaj, sprawdz_spojnosc
from amounts_calc.config import ROZKLADY, TRYB_BRUTTO, VAT_PER_POZYCJA, VAT_PER_STAWKA


def dz(id_, cena, parent="Z", ilosc=1, stawka=23, **kw):
    d = {"id": id_, "parent_id": parent, "ilosc": ilosc, "cena_netto_jedn": cena, "stawka_vat": stawka}
    d.update(kw)
    return d


def zest(n, id_="Z", parent=None, stawka=23, **kw):
    d = {"id": id_, "ilosc": n, "stawka_vat": stawka}
    if parent is not None:
        d["parent_id"] = parent
    d.update(kw)
    return d


class TestOdpowiednikPrzypadkow(unittest.TestCase):
    def test_zestaw_ilosc_10(self):
        d = oblicz([zest(10), dz("A", "600.00"), dz("B", "117.40")], ilosc_zestawu=True)
        self.assertEqual([p.netto for p in d.pozycje], [D("7174.00"), D("600.00"), D("117.40")])
        self.assertEqual(d.pozycje[0].vat, D("1650.00"))           # 10 x (138,00 + 27,00)
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("7174.00"), D("1650.00"), D("8824.00")))
        self.assertTrue(d.ilosc_zestawu)
        self.assertEqual(sprawdz_spojnosc(d), [])

    def test_domyslnie_ilosc_zestawu_jest_ignorowana(self):
        a = oblicz([zest(10), dz("A", "600.00"), dz("B", "117.40")])
        self.assertEqual((a.pozycje[0].netto, a.suma_netto), (D("717.40"), D("717.40")))
        self.assertFalse(a.ilosc_zestawu)

    def test_n_1_identyczne_z_dawnym(self):
        wej = [zest(1), dz("A", "600.00"), dz("B", "117.40"), {"ilosc": 2, "cena_netto_jedn": "10", "stawka_vat": 8}]
        self.assertEqual(oblicz(wej, ilosc_zestawu=True).do_slownika()["suma_vat"], oblicz(wej).do_slownika()["suma_vat"])
        a, b = oblicz(wej, ilosc_zestawu=True), oblicz(wej)
        self.assertEqual((a.pozycje, a.podsumowanie, a.suma_netto, a.suma_vat, a.suma_brutto),
                         (b.pozycje, b.podsumowanie, b.suma_netto, b.suma_vat, b.suma_brutto))

    def test_ilosc_zestawu_ulamkowa_i_zero(self):
        for n, oczek in [("0.5", "50.00"), ("2.5", "250.00"), ("0", "0.00"), ("3", "300.00")]:
            d = oblicz([zest(n), dz("A", "100.00")], ilosc_zestawu=True)
            self.assertEqual((d.pozycje[0].netto, d.suma_netto), (D(oczek), D(oczek)), n)

    def test_zestaw_i_zwykla_pozycja_w_jednym_dokumencie(self):
        d = oblicz([zest(3), dz("A", "100.00"), dz("B", "50.00", stawka=8),
                    {"ilosc": 2, "cena_netto_jedn": "20.00", "stawka_vat": 23}], ilosc_zestawu=True)
        self.assertEqual({s.stawka_vat: (s.netto, s.vat) for s in d.podsumowanie},
                         {"23": (D("340.00"), D("78.20")), "8": (D("150.00"), D("12.00"))})
        self.assertEqual(d.suma_netto, D("490.00"))

    def test_podzestaw_mnozy_swoje_dzieci(self):
        d = oblicz([zest(2), dz("A", "10.00"), zest(3, "P", "Z"), dz("B", "4.00", "P"), dz("C", "6.00", "P")],
                   ilosc_zestawu=True)
        self.assertEqual([p.netto for p in d.pozycje], [D("80.00"), D("10.00"), D("30.00"), D("4.00"), D("6.00")])
        self.assertEqual(d.suma_netto, D("80.00"))
        self.assertEqual(sprawdz_spojnosc(d), [])

    def test_dzieci_o_ilosci_wiekszej_niz_1(self):
        # dziecko: 4 szt. po 2,50 na 1 szt. zestawu; zestaw x5 => 20 szt. razem
        d = oblicz([zest(5), dz("A", "2.50", ilosc=4)], ilosc_zestawu=True)
        self.assertEqual((d.pozycje[1].netto, d.pozycje[0].netto, d.suma_netto), (D("10.00"), D("50.00"), D("50.00")))

    def test_zestaw_z_rabatem_dokumentu(self):
        d = oblicz([zest(2), dz("A", "100.00")], ilosc_zestawu=True, rabat_dokumentu_proc=10)
        self.assertEqual((d.pozycje[1].netto, d.pozycje[0].netto, d.suma_netto), (D("90.00"), D("180.00"), D("180.00")))

    def test_tryb_brutto(self):
        d = oblicz([zest(3), {"id": "A", "parent_id": "Z", "ilosc": 1, "cena_brutto_jedn": "123.00", "stawka_vat": 23}],
                   tryb=TRYB_BRUTTO, ilosc_zestawu=True)
        self.assertEqual((d.pozycje[0].brutto, d.suma_brutto, d.suma_netto, d.suma_vat),
                         (D("369.00"), D("369.00"), D("300.00"), D("69.00")))

    def test_vat_zestawu_to_n_razy_vat_dzieci(self):
        # VAT dziecka 0,33 x 23% = 0,0759 -> 0,08 na 1 szt.; zestaw x10 => 0,80 (a nie 0,759 -> 0,76 z sumy)
        d = oblicz([zest(10), dz("A", "0.33")], ilosc_zestawu=True, tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual((d.pozycje[0].netto, d.pozycje[0].vat), (D("3.30"), D("0.80")))
        self.assertEqual(sprawdz_spojnosc(d), [])
        d2 = oblicz([zest(10), dz("A", "0.33")], ilosc_zestawu=True, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual(d2.suma_vat, D("0.80"))           # brak liścia o wadze 1 => bez korekty
        self.assertEqual(sprawdz_spojnosc(d2), [])          # tolerancja VAT stawki uwzględnia mnożnik

    def test_korekta_groszowa_trafia_do_pozycji_o_wadze_1(self):
        wej = [zest(10), dz("A", "0.33"), {"id": "S1", "ilosc": 1, "cena_netto_jedn": "0.33", "stawka_vat": 23},
               {"id": "S2", "ilosc": 1, "cena_netto_jedn": "0.34", "stawka_vat": 23}]
        for rozklad in ROZKLADY:
            d = oblicz(wej, ilosc_zestawu=True, tryb_vat=VAT_PER_STAWKA, rozklad_korekty=rozklad)
            self.assertEqual(d.pozycje[1].vat, D("0.08"))          # dziecko (waga 10) nie dostaje korekty
            self.assertEqual(d.pozycje[0].vat, D("0.80"))
            vat_poza_zestawem = d.pozycje[2].vat + d.pozycje[3].vat
            # cel stawki: 23% z (3,30 + 0,33 + 0,34 = 3,97) = 0,9131 -> 0,91; zestaw wnosi 0,80, reszta 0,11
            self.assertEqual(d.suma_vat, D("0.91"))
            self.assertEqual(vat_poza_zestawem, D("0.11"))

    def test_bledy_w_podzestawie_i_limit(self):
        wej = [zest(1, "p0")]
        for i in range(1, 13):
            wej.append(zest(1, "p%d" % i, "p%d" % (i - 1)))
        wej.append(dz("L", "1.00", "p12"))
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz(wej, ilosc_zestawu=True)
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_HIERARCHIA)

    def test_ilosc_zestawu_nie_jest_liczba(self):
        with self.assertRaises(bledy.BladWalidacji) as cm:
            oblicz([zest("abc"), dz("A", "1.00")], ilosc_zestawu=True)
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_LICZBA)

    def test_porownaj_z_wynikiem_slownikowym(self):
        d = oblicz([zest(3), dz("A", "100.00"), dz("B", "50.00", stawka=8)], ilosc_zestawu=True)
        self.assertEqual(porownaj(d, dict(d.do_slownika())), [])


class TestAlternatywyWOblicz(unittest.TestCase):
    WEJ = [{"ilosc": 1, "cena_netto_jedn": "100.00", "stawka_vat": 23},
           {"ilosc": 1, "cena_netto_jedn": "40.00", "stawka_vat": 23, "alternatywa": True},
           {"ilosc": 1, "cena_netto_jedn": "60.00", "stawka_vat": 23, "alternatywa": True}]

    def test_domyslnie_zadna_alternatywa_nie_wchodzi(self):
        d = oblicz(self.WEJ)
        self.assertEqual((d.suma_netto, d.wlaczone_alternatywy, d.alternatywy), (D("100.00"), (), "wybrane"))
        self.assertEqual([p.alternatywa for p in d.pozycje], [None, "", ""])

    def test_wybrana_jedna(self):
        d = oblicz(self.WEJ, wlaczone_alternatywy=[2])
        self.assertEqual((d.suma_netto, d.wlaczone_alternatywy), (D("160.00"), (2,)))
        self.assertEqual(sprawdz_spojnosc(d), [])

    def test_wszystkie(self):
        d = oblicz(self.WEJ, wlaczone_alternatywy="wszystkie")
        self.assertEqual(d.suma_netto, D("200.00"))

    def test_bez_pol_zachowanie_dotychczasowe(self):
        wej = [dict(p) for p in self.WEJ]
        for p in wej:
            p.pop("alternatywa", None)
        d = oblicz(wej)
        self.assertEqual((d.suma_netto, d.alternatywy), (D("200.00"), "brak"))

    def test_grupa_opcji_i_jawne_nie(self):
        wej = [{"ilosc": 1, "cena_netto_jedn": "10.00", "stawka_vat": 23, "grupa_opcji": "A"},
               {"ilosc": 1, "cena_netto_jedn": "20.00", "stawka_vat": 23, "grupa_opcji": "A", "alternatywa": False},
               {"ilosc": 1, "cena_netto_jedn": "30.00", "stawka_vat": 23, "alternatywa": "nie"}]
        d = oblicz(wej, wlaczone_alternatywy="wszystkie")
        self.assertEqual([p.alternatywa for p in d.pozycje], ["A", None, None])
        self.assertEqual(d.suma_netto, D("60.00"))

    def test_opcja_bedaca_zestawem_n_razy_dzieci(self):
        wej = [{"ilosc": 1, "cena_netto_jedn": "100.00", "stawka_vat": 23},
               dict(zest(2, "O1"), alternatywa=True), dz("A", "10.00", "O1")]
        d = oblicz(wej, ilosc_zestawu=True, wlaczone_alternatywy=[1])
        self.assertEqual((d.pozycje[1].netto, d.suma_netto), (D("20.00"), D("120.00")))

    def test_alternatywa_dziecka_jest_ignorowana(self):
        wej = [zest(1), dz("A", "10.00", alternatywa=True), dz("B", "5.00")]
        d = oblicz(wej, ilosc_zestawu=True)
        self.assertEqual((d.suma_netto, d.alternatywy), (D("15.00"), "brak"))


class TestWlasnosci(unittest.TestCase):
    def test_losowe_dokumenty_ze_zestawami(self):
        rng = random.Random(606060)
        for tryb in ("netto", TRYB_BRUTTO):
            pole = "cena_netto_jedn" if tryb == "netto" else "cena_brutto_jedn"
            for _ in range(150):
                wej, n_zest = [], 0
                for _ in range(rng.randint(1, 8)):
                    wej.append({"id": "s%d" % len(wej), "ilosc": rng.randint(1, 5),
                                pole: D(rng.randint(1, 20000)) / 100, "stawka_vat": rng.choice((23, 8, "zw"))})
                if rng.random() < 0.8:
                    z = "Z%d" % n_zest
                    wej.append(zest(rng.choice((1, 2, 3, 7, 10)), z))
                    for _ in range(rng.randint(1, 4)):
                        wej.append({"id": "c%d" % len(wej), "parent_id": z, "ilosc": rng.randint(1, 3),
                                    pole: D(rng.randint(1, 20000)) / 100, "stawka_vat": rng.choice((23, 8, 5))})
                    if rng.random() < 0.5:
                        p = "P%d" % len(wej)
                        wej.append(zest(rng.choice((2, 4)), p, z))
                        for _ in range(2):
                            wej.append({"id": "d%d" % len(wej), "parent_id": p, "ilosc": 1,
                                        pole: D(rng.randint(1, 20000)) / 100, "stawka_vat": rng.choice((23, 8))})
                for tv in (VAT_PER_POZYCJA, VAT_PER_STAWKA):
                    for rozklad in ROZKLADY:
                        d = oblicz(wej, tryb=tryb, tryb_vat=tv, rozklad_korekty=rozklad, ilosc_zestawu=True)
                        self.assertEqual(sprawdz_spojnosc(d), [], (tryb, tv, rozklad))
                        self.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)
                        self.assertEqual(sum(s.netto for s in d.podsumowanie), d.suma_netto)
                        for p in d.pozycje:
                            self.assertEqual(p.netto + p.vat, p.brutto)
                        # model wsteczny: bez ilości zestawu wszystkie niezmienniki też zachodzą
                        d0 = oblicz(wej, tryb=tryb, tryb_vat=tv, rozklad_korekty=rozklad)
                        self.assertEqual(sprawdz_spojnosc(d0), [])

    def test_calkowite_n_daje_sumy_jak_rozwiniete_pozycje(self):
        # zestaw x N z dziećmi == N osobnych kopii dzieci (netto): suma netto taka sama
        rng = random.Random(5)
        for _ in range(100):
            n = rng.choice((2, 3, 5, 10))
            dzieci = [{"ilosc": rng.randint(1, 4), "cena_netto_jedn": D(rng.randint(1, 5000)) / 100,
                       "stawka_vat": rng.choice((23, 8))} for _ in range(rng.randint(1, 4))]
            z = [zest(n)] + [dict(c, id="c%d" % i, parent_id="Z") for i, c in enumerate(dzieci)]
            rozwiniete = [c for _ in range(n) for c in dzieci]
            a = oblicz(z, ilosc_zestawu=True, tryb_vat=VAT_PER_POZYCJA)
            b = oblicz(rozwiniete, tryb_vat=VAT_PER_POZYCJA)
            self.assertEqual(a.suma_netto, b.suma_netto)


if __name__ == "__main__":
    unittest.main()
