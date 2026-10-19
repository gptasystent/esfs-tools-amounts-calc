"""Ilość zestawu (pozycji nadrzędnej): dzieci opisują 1 szt., wartość zestawu = N x suma dzieci."""
import unittest
from decimal import ROUND_HALF_UP, Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, dokument_z_slownika, sprawdz_spojnosc
from amounts_calc.model import podsumowanie_dokumentu

K = D("0.01")


def kw(x):
    return D(x).quantize(K, rounding=ROUND_HALF_UP)


def kwoty(netto, stawka=23):
    n = D(netto)
    vat = kw(n * stawka / 100)
    return {"netto": str(n), "vat": str(vat), "brutto": str(n + vat)}


def dziecko(id_, netto, parent="Z", stawka=23, **extra):
    d = {"id": id_, "parent_id": parent, "ilosc": 1, "stawka_vat": stawka}
    d.update(kwoty(netto, stawka))
    d.update(extra)
    return d


def zestaw(n, dzieci, id_="Z", parent=None, mnoz=True, stawka=23, **extra):
    """Zestaw o ilości n; kwoty zestawu = n x suma dzieci (mnoz=True) albo 1 x suma dzieci (mnoz=False)."""
    suma = {k: sum((D(c[k]) for c in dzieci if c["parent_id"] == id_), D(0)) for k in ("netto", "vat", "brutto")}
    m = D(n) if mnoz else D(1)
    z = {"id": id_, "ilosc": n, "stawka_vat": stawka}
    z.update({k: str(kw(v * m)) for k, v in suma.items()})
    if parent is not None:
        z["parent_id"] = parent
    z.update(extra)
    return z


def dokument(pozycje, **extra):
    """Dokument, którego nagłówek jest sumą wierszy najwyższego poziomu (zestaw liczy się raz)."""
    sumy = {k: D(0) for k in ("netto", "vat", "brutto")}
    for p in pozycje:
        if p.get("parent_id") is None and p.get("alternatywa") is None and "netto" in p:
            for k in sumy:
                sumy[k] += D(p[k])
    d = {"suma_" + k: str(v) for k, v in sumy.items()}
    d["pozycje"] = pozycje
    d.update(extra)
    return d


def kody(wyniki):
    return [w["kod"] for w in wyniki]


PRZYPADKI = [   # (ilosc, dzieci netto, oczekiwane netto zestawu z opisu)
    (10, ["600.00", "117.40"], "7174.00"),
    (2, ["5000.00", "2692.82"], "15385.64"),
    (3, ["1000.00", "270.00"], "3810.00"),
    (20, ["30.00", "18.00"], "960.00"),
    (3, ["100.00", "17.00"], "351.00"),
]


class TestPotwierdzonePrzypadki(unittest.TestCase):
    def test_pieciu_przypadkow_brak_niespojnosci(self):
        for n, dzieci_netto, oczek in PRZYPADKI:
            with self.subTest(n=n, dzieci=dzieci_netto):
                dzieci = [dziecko("D%d" % i, x) for i, x in enumerate(dzieci_netto)]
                z = zestaw(n, dzieci)
                self.assertEqual(z["netto"], oczek)
                d = dokument([z] + dzieci)
                self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])
                self.assertEqual(sprawdz_spojnosc(dict(d, ilosc_zestawu=True)), [])

    def test_stare_zachowanie_zglasza_falszywe_niespojnosci(self):
        for n, dzieci_netto, oczek in PRZYPADKI:
            with self.subTest(n=n):
                dzieci = [dziecko("D%d" % i, x) for i, x in enumerate(dzieci_netto)]
                d = dokument([zestaw(n, dzieci)] + dzieci)
                stare = sprawdz_spojnosc(d, ilosc_zestawu=False)
                self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody(stare))
                self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(stare))
                # różnica wynosi dokładnie (N - 1) x suma dzieci
                roznica = [w for w in stare if w["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI and w["pole"] == "netto"][0]
                self.assertEqual(roznica["roznica"], (n - 1) * sum(D(x) for x in dzieci_netto))

    def test_domyslnie_biblioteka_ignoruje_ilosc_zestawu(self):
        dzieci = [dziecko("A", "100.00")]
        d = dokument([zestaw(3, dzieci)] + dzieci)
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody(sprawdz_spojnosc(d)))       # jak przed zmianą
        self.assertEqual(sprawdz_spojnosc(dict(d, ilosc_zestawu=True)), [])

    def test_dokument_zapamietuje_model(self):
        dzieci = [dziecko("A", "100.00")]
        d = dokument([zestaw(3, dzieci)] + dzieci)
        self.assertFalse(dokument_z_slownika(d).ilosc_zestawu)
        self.assertTrue(dokument_z_slownika(d, ilosc_zestawu=True).ilosc_zestawu)
        self.assertTrue(dokument_z_slownika(dict(d, ilosc_zestawu=True)).ilosc_zestawu)


class TestIloscSpecjalne(unittest.TestCase):
    def sprawdz(self, n, dzieci_netto, **kw_):
        dzieci = [dziecko("D%d" % i, x) for i, x in enumerate(dzieci_netto)]
        return sprawdz_spojnosc(dokument([zestaw(n, dzieci, **kw_)] + dzieci), ilosc_zestawu=True)

    def test_n_rowne_1_bez_zmian(self):
        for flaga in (True, False):
            dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00")]
            d = dokument([zestaw(1, dzieci)] + dzieci)
            self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=flaga), [])
            d["pozycje"][0]["netto"] = "155.00"
            w = sprawdz_spojnosc(d, ilosc_zestawu=flaga)
            self.assertEqual(kody(w).count(bledy.ZESTAW_ROZNY_OD_DZIECI), 1)
            self.assertEqual([x["opis"] for x in w if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI],
                             ["kwota pozycji nadrzędnej != suma jej dzieci"])        # opis jak dawniej

    def test_n_ulamkowe_i_zero(self):
        for n in ("0.5", "2.5", "1.5", "0", "0.25", "12.5"):
            with self.subTest(n=n):
                self.assertEqual(self.sprawdz(n, ["100.00", "40.00"]), [])

    def test_n_zero_wnosi_zero_do_sumy(self):
        dzieci = [dziecko("A", "100.00")]
        z = zestaw(0, dzieci)
        self.assertEqual((z["netto"], z["brutto"]), ("0.00", "0.00"))
        d = dokument([z] + dzieci)
        self.assertEqual((d["suma_netto"], d["suma_brutto"]), ("0.00", "0.00"))
        self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])
        self.assertEqual(dokument_z_slownika(d, ilosc_zestawu=True).podsumowanie[0].netto, D("0.00"))

    def test_n_ulamkowe_zaokraglanie_polowki_w_gore(self):
        # 0,5 x 0,05 = 0,025 -> 0,03 (ROUND_HALF_UP biblioteki)
        dzieci = [dziecko("A", "0.05")]
        d = dokument([zestaw("0.5", dzieci)] + dzieci)
        self.assertEqual(d["pozycje"][0]["netto"], "0.03")
        w = sprawdz_spojnosc(d, ilosc_zestawu=True)
        self.assertNotIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody(w))
        self.assertNotIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))
        # netto, vat i brutto zestawu są zaokrąglane OSOBNO, więc przy ułamkowej ilości i groszowych kwotach
        # tożsamość netto + vat = brutto w samym wierszu zestawu może się rozjechać o grosz
        self.assertEqual({(x["kod"], x["zakres"]) for x in w}, {(bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "pozycja:0"),
                                                                (bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "stawka:23"),
                                                                (bledy.NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "dokument")})

    def test_ilosc_zestawu_jest_stringiem_lub_decimalem(self):
        for n in ("3", D("3"), 3, "3.0", "3,0"):
            dzieci = [dziecko("A", "100.00")]
            z = zestaw(3, dzieci)
            z["ilosc"] = n
            self.assertEqual(sprawdz_spojnosc(dokument([z] + dzieci), ilosc_zestawu=True), [], n)

    def test_zestaw_bez_kwot_uzupelniany_n_razy_dzieci(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00")]
        z = {"id": "Z", "ilosc": 4, "stawka_vat": 23}
        d = dokument([z] + dzieci)
        d.update(suma_netto="600.00", suma_vat="138.00", suma_brutto="738.00")
        dok = dokument_z_slownika(d, ilosc_zestawu=True)
        self.assertEqual((dok.pozycje[0].netto, dok.pozycje[0].vat, dok.pozycje[0].brutto),
                         (D("600.00"), D("138.00"), D("738.00")))
        self.assertEqual(sprawdz_spojnosc(dok), [])


class TestBezMnozenia(unittest.TestCase):
    def test_zestaw_rowny_1_x_dzieci_przy_n_wiekszym_od_1(self):
        dzieci = [dziecko("A", "600.00"), dziecko("B", "117.40")]
        d = dokument([zestaw(10, dzieci, mnoz=False)] + dzieci)
        w = sprawdz_spojnosc(d, ilosc_zestawu=True)
        zestawowe = [x for x in w if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertEqual({x["pole"] for x in zestawowe}, {"netto", "vat", "brutto"})
        for x in zestawowe:
            self.assertIn("pasuje do 1 x suma dzieci (ilość zestawu pominięta)", x["opis"])
            self.assertIn("ilość (10)", x["opis"])
        netto = [x for x in zestawowe if x["pole"] == "netto"][0]
        self.assertEqual((netto["oczekiwano"], netto["jest"], netto["roznica"]), (D("7174.00"), D("717.40"), D("-6456.60")))

    def test_inna_niezgodnosc_nie_ma_dopisku(self):
        dzieci = [dziecko("A", "100.00")]
        z = zestaw(3, dzieci)
        z["netto"] = "250.00"
        w = [x for x in sprawdz_spojnosc(dokument([z] + dzieci), ilosc_zestawu=True) if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertTrue(w)
        self.assertNotIn("pasuje do 1 x", w[0]["opis"])

    def test_n_rowne_1_nie_jest_bez_mnozenia(self):
        dzieci = [dziecko("A", "100.00")]
        z = zestaw(1, dzieci)
        z["netto"] = "99.00"
        w = [x for x in sprawdz_spojnosc(dokument([z] + dzieci), ilosc_zestawu=True) if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertNotIn("pasuje do 1 x", w[0]["opis"])


class TestTolerancja(unittest.TestCase):
    def test_roznica_grosza_przy_n_wiekszym_od_1_jak_dla_n_1(self):
        # bez ukrytej tolerancji: różnica 0,01 jest zgłaszana tak samo jak dla N = 1
        for n in (1, 3, 10):
            dzieci = [dziecko("A", "100.00")]
            z = zestaw(n, dzieci)
            z["netto"] = str(D(z["netto"]) + D("0.01"))
            w = [x for x in sprawdz_spojnosc(dokument([z] + dzieci), ilosc_zestawu=True)
                 if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
            self.assertEqual([(x["pole"], x["roznica"]) for x in w], [("netto", D("0.01"))], n)

    def test_zaokraglenia_dzieci_przy_wielokrotnosci(self):
        # dziecko 33,33 (z ceny 33,333) x 3: zestaw liczony ze źródła = 100,00 vs 3 x 33,33 = 99,99 -> zgłoszone o 0,01
        dzieci = [dziecko("A", "33.33")]
        z = zestaw(3, dzieci)
        z["netto"] = "100.00"
        w = [x for x in sprawdz_spojnosc(dokument([z] + dzieci), ilosc_zestawu=True) if x["pole"] == "netto"
             and x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertEqual(w[0]["roznica"], D("0.01"))


class TestPodzestawy(unittest.TestCase):
    def dokument_zagniezdzony(self, n_zestawu=2, n_podzestawu=3):
        # zestaw Z (xN) = dziecko A + podzestaw P (xM) z dziećmi B i C
        a = dziecko("A", "10.00")
        b = dziecko("B", "4.00", parent="P")
        c = dziecko("C", "6.00", parent="P")
        p = zestaw(n_podzestawu, [b, c], id_="P", parent="Z")
        z = zestaw(n_zestawu, [a, p], id_="Z")
        return [z, a, p, b, c]

    def test_oba_z_n_wiekszym_od_1(self):
        pozycje = self.dokument_zagniezdzony(2, 3)
        self.assertEqual([p["netto"] for p in pozycje], ["80.00", "10.00", "30.00", "4.00", "6.00"])
        d = dokument(pozycje)
        self.assertEqual(d["suma_netto"], "80.00")
        self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])
        dok = dokument_z_slownika(d, ilosc_zestawu=True)
        self.assertEqual(dok.podsumowanie[0].netto, D("80.00"))

    def test_blad_podzestawu_nie_przenosi_sie_na_zestaw(self):
        pozycje = self.dokument_zagniezdzony(2, 3)
        pozycje[2].update(netto="10.00", vat="2.30", brutto="12.30")     # podzestaw bez mnożenia (1 x dzieci)
        w = sprawdz_spojnosc(dokument(pozycje), ilosc_zestawu=True)
        zestawowe = [x for x in w if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI]
        self.assertEqual({x["zakres"] for x in zestawowe}, {"pozycja:2"})        # tylko podzestaw P, nie Z
        self.assertIn("pasuje do 1 x", zestawowe[0]["opis"])

    def test_zestaw_nadrzedny_bez_mnozenia_podzestawu(self):
        pozycje = self.dokument_zagniezdzony(2, 3)
        pozycje[0]["netto"] = "40.00"          # 2 x (10 + 10), czyli podzestaw policzony jako 1 x
        w = sprawdz_spojnosc(dokument(pozycje), ilosc_zestawu=True)
        self.assertEqual({x["zakres"] for x in w if x["kod"] == bledy.ZESTAW_ROZNY_OD_DZIECI}, {"pozycja:0"})

    def test_trzy_poziomy(self):
        c = dziecko("C", "1.00", parent="P2")
        p2 = zestaw(5, [c], id_="P2", parent="P1")
        p1 = zestaw(4, [p2], id_="P1", parent="Z")
        z = zestaw(3, [p1], id_="Z")
        d = dokument([z, p1, p2, c])
        self.assertEqual(z["netto"], "60.00")
        self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])

    def test_zestawy_obok_siebie_i_zwykla_pozycja(self):
        d1 = [dziecko("A1", "10.00", parent="Z1")]
        d2 = [dziecko("A2", "5.00", parent="Z2"), dziecko("B2", "5.00", parent="Z2")]
        zwykla = {"id": "S", "ilosc": 1, "stawka_vat": 8, **kwoty("100.00", 8)}
        pozycje = [zestaw(7, d1, id_="Z1"), *d1, zestaw(2, d2, id_="Z2"), *d2, zwykla]
        d = dokument(pozycje)
        self.assertEqual(d["suma_netto"], "190.00")
        self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])
        dok = dokument_z_slownika(d, ilosc_zestawu=True)
        self.assertEqual({s.stawka_vat: s.netto for s in dok.podsumowanie}, {"23": D("90.00"), "8": D("100.00")})

    def test_za_glebokie_zagniezdzenie(self):
        pozycje = [{"id": "p0", "ilosc": 1, "stawka_vat": 23}]
        for i in range(1, 13):
            pozycje.append({"id": "p%d" % i, "parent_id": "p%d" % (i - 1), "ilosc": 1, "stawka_vat": 23})
        pozycje[-1].update(kwoty("1.00"))
        d = {"suma_netto": "1.00", "suma_vat": "0.23", "suma_brutto": "1.23", "pozycje": pozycje}
        with self.assertRaises(bledy.BladWalidacji) as cm:
            dokument_z_slownika(d, ilosc_zestawu=True)
        self.assertEqual(cm.exception.kod, bledy.NIEPOPRAWNA_HIERARCHIA)


class TestSumyDokumentu(unittest.TestCase):
    def test_naglowek_n_razy_dzieci_jest_zgodny_a_naiwna_suma_liści_nie(self):
        dzieci = [dziecko("A", "600.00"), dziecko("B", "117.40")]
        d = dokument([zestaw(10, dzieci)] + dzieci)
        self.assertEqual(d["suma_netto"], "7174.00")
        self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])
        naiwna = sprawdz_spojnosc(d, ilosc_zestawu=False)
        sumy = [x for x in naiwna if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU and x["pole"] == "suma_netto"]
        self.assertEqual(sumy[0]["oczekiwano"], D("717.40"))

    def test_naglowek_liczony_z_dzieci_bez_mnozenia_jest_niespojny(self):
        dzieci = [dziecko("A", "600.00"), dziecko("B", "117.40")]
        d = dokument([zestaw(10, dzieci)] + dzieci)
        d.update(suma_netto="717.40", suma_vat="165.00", suma_brutto="882.40")
        w = sprawdz_spojnosc(d, ilosc_zestawu=True)
        self.assertEqual({x["pole"] for x in w if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU},
                         {"suma_netto", "suma_vat", "suma_brutto"})

    def test_suma_to_wartosc_zestawu_gdy_zgodna_i_oczekiwana_gdy_nie(self):
        dzieci = [dziecko("A", "100.00")]
        z = zestaw(3, dzieci)
        z["netto"] = "250.00"                 # zapisana wartość zestawu jest zła
        d = dokument([z] + dzieci)
        d.update(suma_netto="300.00", suma_vat="69.00", suma_brutto="369.00")          # nagłówek = 3 x dzieci
        w = sprawdz_spojnosc(d, ilosc_zestawu=True)
        self.assertNotIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))                # do sumy wchodzi N x dzieci
        self.assertIn(bledy.ZESTAW_ROZNY_OD_DZIECI, kody(w))                            # a zestaw sam jest zgłoszony

    def test_podsumowanie_dokumentu(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00", stawka=8)]
        d = dokument([zestaw(3, dzieci)] + dzieci)
        ps = podsumowanie_dokumentu(dokument_z_slownika(d, ilosc_zestawu=True).pozycje, True)
        self.assertEqual({s.stawka_vat: (s.netto, s.vat) for s in ps}, {"23": (D("300.00"), D("69.00")),
                                                                         "8": (D("150.00"), D("12.00"))})

    def test_podsumowanie_stawek_zestawu_w_pliku_zgadza_sie(self):
        dzieci = [dziecko("A", "100.00"), dziecko("B", "50.00", stawka=8)]
        d = dokument([zestaw(3, dzieci)] + dzieci)
        d["podsumowanie"] = [{"stawka_vat": 23, "netto": "300.00", "vat": "69.00", "brutto": "369.00"},
                             {"stawka_vat": 8, "netto": "150.00", "vat": "12.00", "brutto": "162.00"}]
        self.assertEqual(sprawdz_spojnosc(d, ilosc_zestawu=True), [])


if __name__ == "__main__":
    unittest.main()
