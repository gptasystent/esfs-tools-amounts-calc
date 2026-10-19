"""Opcje i alternatywy w trybie jawnym (tryb_opcji / grupa_opcji / wybrana) oraz tryb awaryjny dla dokumentów bez pól."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, dokument_z_slownika, oblicz, sprawdz_spojnosc
from amounts_calc.adapter import z_wiersza
from amounts_calc.check import main, sprawdz_dokument, sprawdz_partie
from amounts_calc.model import ustal_opcje, tryb_opcji_pozycji, wybrana_pozycji
from amounts_calc.bledy import BladWalidacji

K = D("0.01")


def kwoty(netto, stawka=23):
    n = D(netto)
    v = (n * stawka / 100).quantize(K, rounding=ROUND_HALF_UP)
    return {"netto": str(n), "vat": str(v), "brutto": str(n + v)}


def poz(id_, netto, **extra):
    d = {"id": id_, "ilosc": 1, "cena_netto_jedn": str(netto), "stawka_vat": 23}
    d.update(kwoty(netto))
    d.update(extra)
    return d


def opcja(id_, netto, wybrana=False, **extra):
    return poz(id_, netto, tryb_opcji="opcja", wybrana=wybrana, **extra)


def alt(id_, netto, grupa="kolor", wybrana=False, **extra):
    return poz(id_, netto, tryb_opcji="alternatywa", grupa_opcji=grupa, wybrana=wybrana, **extra)


def dok(pozycje, netto, **extra):
    d = {"id": "OF/1", "typ": "OF", "pozycje": pozycje}
    d.update({"suma_" + k: v for k, v in kwoty(netto).items()})
    d.update(extra)
    return d


def kody(wyniki):
    return [x["kod"] for x in wyniki]


def kody_przyczyn(w):
    return {c["kod"] for c in w["przyczyny"]}


# fikcyjna oferta: bazowa usługa 100,00 + opcja 50,00 + dwie alternatywy w grupie "kolor" (200,00 / 300,00)
BAZA = poz("B", "100.00")


class TestAlternatywa(unittest.TestCase):
    def test_wybrana_wchodzi_do_sumy_niewybrana_nie(self):
        for pierwsza, druga, netto, wlaczone in [(True, False, "300.00", (1,)), (False, True, "400.00", (2,))]:
            with self.subTest(wybrana=(pierwsza, druga)):
                d = dok([BAZA, alt("A1", "200.00", wybrana=pierwsza), alt("A2", "300.00", wybrana=druga)], netto)
                w = sprawdz_spojnosc(d)
                self.assertEqual(w, [])
                dw = dokument_z_slownika(d)
                self.assertEqual((dw.wlaczone_alternatywy, dw.alternatywy, dw.opcje_jawne), (wlaczone, "jawne", True))

    def test_zadnej_dobieranej_kombinacji_naglowek_z_inna_alternatywa_jest_niespojny(self):
        d = dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00")], "400.00")   # nagłówek jak dla A2
        w = sprawdz_spojnosc(d)
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))
        self.assertEqual(dokument_z_slownika(d).wlaczone_alternatywy, (1,))     # wybór wynika z pola, nie z nagłówka

    def test_brak_wyboru(self):
        d = dok([BAZA, alt("A1", "200.00"), alt("A2", "300.00")], "100.00")
        w = sprawdz_spojnosc(d)
        self.assertEqual([x for x in w if x["kod"] == bledy.ALTERNATYWA_BEZ_WYBORU][0]["zakres"], "grupa:kolor")
        self.assertEqual(kody(w).count(bledy.ALTERNATYWA_BEZ_WYBORU), 1)
        c = w.opcje[0]
        self.assertEqual(c["kod"], bledy.ALTERNATYWA_BEZ_WYBORU)
        self.assertEqual([p["indeks"] for p in c["grupy"][0]["pozycje"]], [1, 2])
        self.assertEqual(c["grupy"][0]["pozycje"][1]["netto"], D("300.00"))
        self.assertEqual(c["roznica_wzgledem_naglowka"], {"netto": 0, "vat": 0, "brutto": 0})
        self.assertEqual(c["grupy"][0]["naglowek_pasuje_do"], [])

    def test_brak_wyboru_naglowek_z_jedna_alternatywa_wskazuje_ktora(self):
        d = dok([BAZA, alt("A1", "200.00"), alt("A2", "300.00")], "400.00")
        c = sprawdz_spojnosc(d).opcje[0]
        self.assertEqual(c["grupy"][0]["naglowek_pasuje_do"], [2])
        self.assertEqual(c["roznica_wzgledem_naglowka"]["netto"], D("300.00"))

    def test_wiele_wybranych(self):
        d = dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00", wybrana=True)], "300.00")
        w = sprawdz_spojnosc(d)
        wpis = [x for x in w if x["kod"] == bledy.ALTERNATYWA_WIELE_WYBRANYCH]
        self.assertEqual(len(wpis), 1)
        self.assertEqual((wpis[0]["zakres"], wpis[0]["oczekiwano"], wpis[0]["jest"]), ("grupa:kolor", 1, 2))
        c = [c for c in w.opcje if c["kod"] == bledy.ALTERNATYWA_WIELE_WYBRANYCH][0]
        self.assertEqual(c["grupy"][0]["wybranych"], 2)
        self.assertEqual(c["grupy"][0]["naglowek_pasuje_do_jednej"], [1])
        self.assertEqual(c["roznica_wzgledem_naglowka"]["netto"], D("-300.00"))   # wliczono obie: 600 wobec 300
        self.assertFalse(c["naglowek_zawiera_wszystkie_wybrane"])

    def test_wiele_wybranych_naglowek_z_obiema(self):
        d = dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00", wybrana=True)], "600.00")
        w = sprawdz_spojnosc(d)
        self.assertEqual(kody(w), [bledy.ALTERNATYWA_WIELE_WYBRANYCH])     # sumy się zgadzają, łamana jest zasada wyboru
        self.assertTrue(w.opcje[0]["naglowek_zawiera_wszystkie_wybrane"])

    def test_dwie_grupy_niezalezne(self):
        p = [BAZA, alt("K1", "10.00", "kolor", True), alt("K2", "20.00", "kolor"),
             alt("R1", "5.00", "rozmiar"), alt("R2", "7.00", "rozmiar", True)]
        self.assertEqual(sprawdz_spojnosc(dok(p, "117.00")), [])
        w = sprawdz_spojnosc(dok([BAZA, alt("K1", "10.00", "kolor"), alt("R1", "5.00", "rozmiar")], "100.00"))
        self.assertEqual([x["zakres"] for x in w if x["kod"] == bledy.ALTERNATYWA_BEZ_WYBORU],
                         ["grupa:kolor", "grupa:rozmiar"])

    def test_alternatywa_bez_nazwy_grupy_to_jedna_grupa_domyslna(self):
        p = [BAZA, poz("A1", "10.00", tryb_opcji="alternatywa", wybrana=True),
             poz("A2", "20.00", tryb_opcji="alternatywa", wybrana=True)]
        w = sprawdz_spojnosc(dok(p, "110.00"))
        self.assertIn(bledy.ALTERNATYWA_WIELE_WYBRANYCH, kody(w))


class TestOpcja(unittest.TestCase):
    def test_niewybrana_opcja_jest_poza_suma(self):
        d = dok([BAZA, opcja("O1", "50.00")], "100.00")
        w = sprawdz_spojnosc(d)
        self.assertEqual(w, [])
        self.assertEqual(w.opcje, [])
        self.assertEqual({k: w.poza_suma[k] for k in ("netto", "vat", "brutto")},
                         {"netto": D("50.00"), "vat": D("11.50"), "brutto": D("61.50")})
        self.assertEqual([p["indeks"] for p in w.poza_suma["pozycje"]], [1])

    def test_wybrana_opcja_wchodzi_do_sumy_i_nie_jest_poza_suma(self):
        w = sprawdz_spojnosc(dok([BAZA, opcja("O1", "50.00", True)], "150.00"))
        self.assertEqual(w, [])
        self.assertEqual((w.poza_suma["netto"], w.poza_suma["pozycje"]), (0, []))

    def test_naglowek_zawiera_niewybrana_opcje(self):
        d = dok([BAZA, opcja("O1", "50.00")], "150.00")
        w = sprawdz_spojnosc(d)
        self.assertEqual(sorted(x["pole"] for x in w if x["kod"] == bledy.OPCJA_W_SUMIE),
                         ["suma_brutto", "suma_netto", "suma_vat"])
        c = w.opcje[0]
        self.assertEqual(c["kod"], bledy.OPCJA_W_SUMIE)
        self.assertEqual([(p["indeks"], p["netto"], p["vat"], p["brutto"]) for p in c["pozycje"]],
                         [(1, D("50.00"), D("11.50"), D("61.50"))])
        self.assertEqual(c["roznica_wzgledem_naglowka"], {"netto": D("50.00"), "vat": D("11.50"), "brutto": D("61.50")})
        self.assertEqual(c["suma_wliczona"]["netto"], D("100.00"))
        self.assertEqual(c["roznica"], D("61.50"))

    def test_opcja_w_sumie_wskazuje_ktore_opcje(self):
        p = [BAZA, opcja("O1", "50.00"), opcja("O2", "30.00"), opcja("O3", "7.00")]
        c = sprawdz_spojnosc(dok(p, "157.00")).opcje[0]      # nagłówek = baza + O1 (50) + O3 (7)
        self.assertEqual([x["indeks"] for x in c["pozycje"]], [1, 3])
        self.assertEqual(c["kwoty_pozycji"]["netto"], D("57.00"))

    def test_nagledek_niepasujacy_do_zadnego_podzbioru_nie_daje_opcji_w_sumie(self):
        w = sprawdz_spojnosc(dok([BAZA, opcja("O1", "50.00")], "123.00"))
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))
        self.assertNotIn(bledy.OPCJA_W_SUMIE, kody(w))

    def test_opcja_z_iloscia_zero_nic_nie_wnosi(self):
        o = opcja("O1", "50.00", True)
        o.update(ilosc=0, **{"netto": "0.00", "vat": "0.00", "brutto": "0.00"})
        self.assertEqual(sprawdz_spojnosc(dok([BAZA, o], "100.00")), [])


class TestMieszanka(unittest.TestCase):
    P = [poz("Z1", "100.00"), opcja("O1", "50.00"), opcja("O2", "20.00", True),
         alt("A1", "200.00", wybrana=True), alt("A2", "300.00"), poz("Z2", "10.00")]

    def test_zwykle_opcje_i_alternatywy(self):
        w = sprawdz_spojnosc(dok(self.P, "330.00"))      # 100 + 20 (O2) + 200 (A1) + 10
        self.assertEqual(w, [])
        self.assertEqual(w.poza_suma["netto"], D("50.00"))

    def test_poza_suma_nie_zawiera_niewybranych_alternatyw(self):
        w = sprawdz_spojnosc(dok(self.P, "330.00"))
        self.assertEqual([p["id"] for p in w.poza_suma["pozycje"]], ["O1"])

    def test_wynik_oblicz_zgodny_z_zapisanym(self):
        pozycje = [{k: v for k, v in p.items() if k not in ("netto", "vat", "brutto")} for p in self.P]
        r = oblicz(pozycje)
        self.assertEqual((r.suma_netto, r.suma_vat, r.suma_brutto), (D("330.00"), D("75.90"), D("405.90")))
        self.assertEqual((r.wlaczone_alternatywy, r.alternatywy, r.opcje_jawne), ((2, 3), "jawne", True))
        self.assertEqual(sprawdz_spojnosc(r), [])

    def test_wlaczone_alternatywy_jest_ignorowane_w_trybie_jawnym(self):
        pozycje = [{k: v for k, v in p.items() if k not in ("netto", "vat", "brutto")} for p in self.P]
        self.assertEqual(oblicz(pozycje, wlaczone_alternatywy="wszystkie").suma_netto, D("330.00"))
        self.assertEqual(oblicz(pozycje, wlaczone_alternatywy=[1, 4]).suma_netto, D("330.00"))

    def test_podsumowanie_stawek_i_vat_per_pozycja(self):
        pozycje = [{"id": "a", "ilosc": 1, "cena_netto_jedn": "10.00", "stawka_vat": 23},
                   {"id": "b", "ilosc": 1, "cena_netto_jedn": "10.00", "stawka_vat": 8, "tryb_opcji": "opcja"},
                   {"id": "c", "ilosc": 1, "cena_netto_jedn": "10.00", "stawka_vat": 8, "tryb_opcji": "opcja",
                    "wybrana": "tak"}]
        for tv in ("per_stawka", "per_pozycja"):
            r = oblicz(pozycje, tryb_vat=tv)
            self.assertEqual([(s.stawka_vat, s.netto) for s in r.podsumowanie], [("23", D("10.00")), ("8", D("10.00"))])
            self.assertEqual(sprawdz_spojnosc(r), [])


class TestZestawJakoOpcja(unittest.TestCase):
    """Zestaw z ilością N i dziećmi na 1 szt. (runda 6) jako opcja albo alternatywa: wnosi N x dzieci."""

    @staticmethod
    def zestaw(id_, n, dzieci, **extra):
        suma = sum((D(c["netto"]) for c in dzieci), D(0)) * n
        z = {"id": id_, "ilosc": n, "stawka_vat": 23}
        z.update(kwoty(suma))
        z.update(extra)
        return [z] + [dict(c, parent_id=id_) for c in dzieci]

    def test_zestaw_n3_jako_alternatywa(self):
        dz = [poz("A_1", "30.00"), poz("A_2", "9.00")]                  # 39 na 1 szt. -> 117 dla N = 3
        p = ([BAZA] + self.zestaw("A", 3, dz, tryb_opcji="alternatywa", grupa_opcji="komplet", wybrana=True)
             + [alt("B", "500.00", "komplet")])
        self.assertEqual(sprawdz_spojnosc(dok(p, "217.00"), ilosc_zestawu=True), [])
        w = sprawdz_spojnosc(dok(p, "217.00", ilosc_zestawu=True))
        self.assertEqual(w, [])
        self.assertEqual(dokument_z_slownika(dok(p, "217.00"), True).wlaczone_alternatywy, (1,))

    def test_zestaw_n3_nie_wybrany_nie_wchodzi_ani_razem_z_dziecmi(self):
        dz = [poz("A_1", "30.00"), poz("A_2", "9.00")]
        p = ([BAZA] + self.zestaw("A", 3, dz, tryb_opcji="alternatywa", grupa_opcji="komplet")
             + [alt("B", "500.00", "komplet", wybrana=True)])
        self.assertEqual(sprawdz_spojnosc(dok(p, "600.00"), ilosc_zestawu=True), [])

    def test_zestaw_n3_jako_opcja_poza_suma_ma_wartosc_n_razy_dzieci(self):
        dz = [poz("A_1", "30.00"), poz("A_2", "9.00")]
        p = [BAZA] + self.zestaw("A", 3, dz, tryb_opcji="opcja")
        w = sprawdz_spojnosc(dok(p, "100.00"), ilosc_zestawu=True)
        self.assertEqual(w, [])
        self.assertEqual((w.poza_suma["netto"], w.poza_suma["vat"], w.poza_suma["brutto"]),
                         (D("117.00"), D("26.91"), D("143.91")))
        self.assertEqual([p_["indeks"] for p_ in w.poza_suma["pozycje"]], [1])

    def test_zestaw_jako_wybrana_opcja_w_sumie_n_razy_dzieci(self):
        dz = [poz("A_1", "30.00"), poz("A_2", "9.00")]
        p = [BAZA] + self.zestaw("A", 3, dz, tryb_opcji="opcja", wybrana=True)
        self.assertEqual(sprawdz_spojnosc(dok(p, "217.00"), ilosc_zestawu=True), [])
        w = sprawdz_spojnosc(dok(p, "139.00"), ilosc_zestawu=True)       # nagłówek policzony z 1 x dzieci
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))

    def test_oblicz_zestaw_jako_opcja(self):
        pozycje = [{"id": "B", "ilosc": 1, "cena_netto_jedn": "100.00", "stawka_vat": 23},
                   {"id": "A", "ilosc": 3, "stawka_vat": 23, "tryb_opcji": "opcja", "wybrana": True},
                   {"id": "A_1", "parent_id": "A", "ilosc": 1, "cena_netto_jedn": "30.00", "stawka_vat": 23},
                   {"id": "A_2", "parent_id": "A", "ilosc": 1, "cena_netto_jedn": "9.00", "stawka_vat": 23}]
        r = oblicz(pozycje, ilosc_zestawu=True)
        self.assertEqual(r.suma_netto, D("217.00"))
        r2 = oblicz([dict(pozycje[0]), dict(pozycje[1], wybrana=False)] + pozycje[2:], ilosc_zestawu=True)
        self.assertEqual((r2.suma_netto, r2.wlaczone_alternatywy), (D("100.00"), ()))


class TestRegresjaBezNowychPol(unittest.TestCase):
    def test_dokument_bez_pol_nie_jest_jawny(self):
        d = dok([BAZA, poz("O1", "40.00", alternatywa=True), poz("O2", "60.00", alternatywa=True)], "160.00")
        dw = dokument_z_slownika(d)
        self.assertEqual((dw.opcje_jawne, dw.alternatywy, dw.wlaczone_alternatywy), (False, "zgodne", (2,)))
        w = sprawdz_spojnosc(d)
        self.assertEqual((list(w), w.opcje, w.poza_suma["pozycje"]), ([], (), []))

    def test_zwykly_dokument_ma_zerowa_poza_suma(self):
        w = sprawdz_spojnosc(dok([BAZA], "100.00"))
        self.assertEqual((w, w.poza_suma["netto"], w.poza_suma["pozycje"]), ([], 0, []))

    def test_cli_dokument_awaryjny_nadal_daje_alternatywy_w_sumie(self):
        d = dok([BAZA, poz("O1", "40.00", alternatywa=True), poz("O2", "60.00", alternatywa=True)], "160.00")
        w = sprawdz_dokument(d)
        self.assertEqual(w["status"], "spojny")
        self.assertEqual(kody_przyczyn(w), {bledy.ALTERNATYWY_W_SUMIE})
        self.assertNotIn(bledy.ALTERNATYWY_W_SUMIE, [p["kod"] for p in sprawdz_dokument(d, tryb_opcji="jawny")["przyczyny"]])

    def test_dokument_bez_pol_i_bez_opcji_ma_ten_sam_wynik_co_przed_ta_runda(self):
        d = dok([BAZA, poz("X", "12.34")], "112.34")
        w = sprawdz_dokument(d)
        self.assertEqual((w["status"], w["niespojnosci"], w["przyczyny"], w["tryb_pasujacy"]), ("spojny", [], [], "oba"))
        self.assertEqual(sprawdz_dokument(d, tryb_opcji="jawny")["status"], "spojny")

    def test_wymuszony_tryb_awaryjny_ignoruje_pola_jawne(self):
        d = dok([BAZA, opcja("O1", "50.00")], "150.00")
        self.assertFalse(dokument_z_slownika(d, tryb_opcji="awaryjny").opcje_jawne)
        self.assertEqual(sprawdz_spojnosc(dict(d, tryb_opcji="awaryjny")), [])      # opcja liczona jak zwykła pozycja
        self.assertEqual(sprawdz_spojnosc(d, tryb_opcji="awaryjny"), [])
        self.assertIn(bledy.OPCJA_W_SUMIE, kody(sprawdz_spojnosc(d)))

    def test_wymuszony_tryb_awaryjny_dobiera_kombinacje_zamiast_wybrana(self):
        d = dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00")], "400.00")   # grupa_opcji = alternatywa
        dw = dokument_z_slownika(d, tryb_opcji="awaryjny")
        self.assertEqual((dw.opcje_jawne, dw.wlaczone_alternatywy, dw.alternatywy), (False, (2,), "zgodne"))
        self.assertEqual(sprawdz_spojnosc(d, tryb_opcji="awaryjny"), [])

    def test_wymuszony_tryb_jawny_bez_pol_traktuje_wszystko_jak_brak(self):
        d = dok([BAZA, poz("O1", "40.00", alternatywa=True)], "140.00")
        dw = dokument_z_slownika(d, tryb_opcji="jawny")
        self.assertEqual((dw.opcje_jawne, dw.wlaczone_alternatywy, dw.alternatywy), (True, (), "jawne"))
        self.assertEqual(sprawdz_spojnosc(d, tryb_opcji=None), [])


class TestWalidacja(unittest.TestCase):
    def test_tryby(self):
        for x, oczek in [(None, None), ("", None), (" ", None), ("Opcja", "opcja"), (" ALTERNATYWA ", "alternatywa"),
                         ("brak", "brak")]:
            self.assertEqual(tryb_opcji_pozycji(x), oczek)
        for zle in ("dodatkowa", 1, True):
            with self.subTest(zle=zle), self.assertRaises(BladWalidacji) as e:
                tryb_opcji_pozycji(zle)
            self.assertEqual(e.exception.kod, bledy.NIEPOPRAWNY_TRYB)

    def test_wybrana(self):
        for x, oczek in [(True, True), ("tak", True), ("TRUE", True), (1, True), ("1", True), (False, False),
                         ("nie", False), (0, False), (None, False), ("", False)]:
            self.assertIs(wybrana_pozycji(x), oczek, x)
        with self.assertRaises(BladWalidacji) as e:
            wybrana_pozycji("moze")
        self.assertEqual(e.exception.kod, bledy.NIEPOPRAWNA_STRUKTURA)

    def test_zly_tryb_w_dokumencie_to_blad_walidacji_z_polem(self):
        with self.assertRaises(BladWalidacji) as e:
            dokument_z_slownika(dok([BAZA, poz("O", "1.00", tryb_opcji="dodatkowa")], "101.00"))
        self.assertEqual((e.exception.kod, e.exception.pole), (bledy.NIEPOPRAWNY_TRYB, "pozycje[1].tryb_opcji"))

    def test_zly_wybor_trybu(self):
        with self.assertRaises(BladWalidacji):
            ustal_opcje([], {}, "losowy")

    def test_pola_opcji_dzieci_sa_ignorowane(self):
        pozycje = [{"id": "Z", "ilosc": 2, "stawka_vat": 23, "tryb_opcji": "opcja"},
                   {"id": "Z_1", "parent_id": "Z", "tryb_opcji": "alternatywa", "wybrana": True}]
        o = ustal_opcje(pozycje, {1: 0})
        self.assertEqual((o["jawny"], o["tryby"], o["alt"][1], o["wybrane" if False else "wlaczone"]),
                         (True, {0: "opcja"}, None, frozenset()))

    def test_pola_dzieci_nie_wlaczaja_trybu_jawnego(self):
        pozycje = [{"id": "Z", "ilosc": 2, "stawka_vat": 23, "alternatywa": True},
                   {"id": "Z_1", "parent_id": "Z", "tryb_opcji": "opcja"}]
        self.assertFalse(ustal_opcje(pozycje, {1: 0})["jawny"])


class TestSlownikIAdapter(unittest.TestCase):
    def test_do_slownika_zachowuje_pola_i_odtwarza_dokument(self):
        pozycje = [{"id": "B", "ilosc": 1, "cena_netto_jedn": "100.00", "stawka_vat": 23},
                   {"id": "O", "ilosc": 1, "cena_netto_jedn": "50.00", "stawka_vat": 23, "tryb_opcji": "opcja"},
                   {"id": "A", "ilosc": 1, "cena_netto_jedn": "20.00", "stawka_vat": 23, "tryb_opcji": "alternatywa",
                    "grupa_opcji": "g", "wybrana": True}]
        r = oblicz(pozycje)
        s = r.do_slownika()
        self.assertEqual([(p.get("tryb_opcji"), p.get("wybrana")) for p in s["pozycje"]],
                         [("brak", None), ("opcja", False), ("alternatywa", True)])
        d2 = dokument_z_slownika(s)
        self.assertTrue(d2.opcje_jawne)
        self.assertEqual(d2.wlaczone_alternatywy, r.wlaczone_alternatywy)
        self.assertEqual(sprawdz_spojnosc(s), [])

    def test_aliasy_w_adapterze(self):
        d = z_wiersza({"netto": 1, "vat": 0, "brutto": 1,
                       "pozycje": [{"ilosc": 1, "stawka": 23, "tryb_pozycji": "opcja", "wliczona": True,
                                    "grupa_opcji": "x"}]})
        self.assertEqual((d["pozycje"][0]["tryb_opcji"], d["pozycje"][0]["wybrana"], d["pozycje"][0]["grupa_opcji"]),
                         ("opcja", True, "x"))

    def test_mapowanie_uzytkownika(self):
        m = {"pozycja": {"tryb_opcji": "rodzaj_linii", "wybrana": "w_ofercie", "grupa_opcji": "wariant"}}
        d = z_wiersza({"netto": 1, "vat": 0, "brutto": 1,
                       "pozycje": [{"ilosc": 1, "stawka": 23, "rodzaj_linii": "alternatywa", "w_ofercie": "tak",
                                    "wariant": "A"}]}, m)
        p = d["pozycje"][0]
        self.assertEqual((p["tryb_opcji"], p["wybrana"], p["grupa_opcji"]), ("alternatywa", "tak", "A"))


class TestCli(unittest.TestCase):
    def test_poprawna_oferta_z_opcjami_jest_spojna(self):
        d = dok([BAZA, opcja("O1", "50.00"), alt("A1", "200.00", wybrana=True), alt("A2", "300.00")], "300.00")
        w = sprawdz_dokument(d)
        self.assertEqual((w["status"], w["niespojnosci"], w["przyczyny"], w["tryb_pasujacy"]),
                         ("spojny", [], [], "oba"))

    def test_opcja_w_sumie_to_niespojnosc(self):
        d = dok([BAZA, opcja("O1", "50.00")], "150.00")
        w = sprawdz_dokument(d)
        self.assertEqual(w["status"], "niespojny")
        self.assertIn(bledy.OPCJA_W_SUMIE, kody_przyczyn(w))
        c = [c for c in w["przyczyny"] if c["kod"] == bledy.OPCJA_W_SUMIE][0]
        self.assertFalse(c.get("informacja"))
        self.assertEqual(c["pozycje"][0]["id"], "O1")
        self.assertEqual(c["roznica_wzgledem_naglowka"]["netto"], D("50.00"))

    def test_brak_wyboru_i_wiele_wybranych_to_niespojnosci(self):
        w1 = sprawdz_dokument(dok([BAZA, alt("A1", "200.00"), alt("A2", "300.00")], "100.00"))
        self.assertEqual(w1["status"], "niespojny")
        self.assertIn(bledy.ALTERNATYWA_BEZ_WYBORU, kody_przyczyn(w1))
        w2 = sprawdz_dokument(dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00", wybrana=True)], "600.00"))
        self.assertEqual(w2["status"], "niespojny")
        self.assertIn(bledy.ALTERNATYWA_WIELE_WYBRANYCH, kody_przyczyn(w2))

    def test_w_trybie_jawnym_nie_ma_alternatywy_w_sumie(self):
        w = sprawdz_dokument(dok([BAZA, alt("A1", "200.00", wybrana=True), alt("A2", "300.00")], "300.00"))
        self.assertNotIn(bledy.ALTERNATYWY_W_SUMIE, kody_przyczyn(w))

    def test_tryb_awaryjny_flaga_ignoruje_pola_jawne(self):
        d = dok([BAZA, opcja("O1", "50.00")], "100.00")
        self.assertEqual(sprawdz_dokument(d)["status"], "spojny")
        w = sprawdz_dokument(d, tryb_opcji="awaryjny")           # opcja liczona jak zwykła pozycja
        self.assertEqual(w["status"], "niespojny")
        self.assertFalse(kody_przyczyn(w) & {bledy.OPCJA_W_SUMIE, bledy.ALTERNATYWY_W_SUMIE})

    def test_zly_tryb_opcji_w_pozycji_to_blad_dokumentu(self):
        w = sprawdz_dokument(dok([BAZA, poz("X", "1.00", tryb_opcji="dodatkowa")], "101.00"))
        self.assertEqual((w["status"], w["blad"]["kod"]), ("blad", bledy.NIEPOPRAWNY_TRYB))

    def test_dokument_bez_vat_w_pozycjach(self):
        def bez(p):
            return {k: v for k, v in p.items() if k not in ("vat", "brutto")}
        d = dok([bez(BAZA), bez(opcja("O1", "50.00")), bez(alt("A1", "200.00", wybrana=True)), bez(alt("A2", "300.00"))],
                "300.00")
        w = sprawdz_dokument(d)
        self.assertNotIn(w["status"], ("blad",))
        self.assertEqual(w["niespojnosci"], [])
        w2 = sprawdz_dokument(dict(d, **{"suma_" + k: v for k, v in kwoty("350.00").items()}))
        self.assertIn(bledy.OPCJA_W_SUMIE, kody_przyczyn(w2))

    def test_dokument_bez_kwot_pozycji(self):
        def bez(p):
            return {k: v for k, v in p.items() if k not in ("netto", "vat", "brutto")}
        d = dok([bez(BAZA), bez(opcja("O1", "50.00")), bez(alt("A1", "200.00", wybrana=True)),
                 bez(alt("A2", "300.00"))], "300.00")
        w = sprawdz_dokument(d)
        self.assertEqual((w["status"], w["blad"]), ("spojny", None))
        w2 = sprawdz_dokument(dict(d, **{"suma_" + k: v for k, v in kwoty("350.00").items()}))
        self.assertEqual(w2["status"], "niespojny")

    def test_partia_i_main_z_flaga(self):
        dokumenty = [dok([BAZA, opcja("O1", "50.00")], "100.00"),
                     dict(dok([BAZA, opcja("O1", "50.00")], "150.00"), id="OF/2")]
        wyniki, podsumowanie = sprawdz_partie(dokumenty)
        self.assertEqual([w["status"] for w in wyniki], ["spojny", "niespojny"])
        self.assertEqual(podsumowanie["kody"].get(bledy.OPCJA_W_SUMIE), 1)
        with tempfile.TemporaryDirectory() as t:
            sciezka = os.path.join(t, "d.json")
            with open(sciezka, "w", encoding="utf-8") as f:
                json.dump(dokumenty, f)
            for tryb, kod in [("auto", 1), ("jawny", 1), ("awaryjny", 1)]:
                with self.subTest(tryb=tryb), contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(main([sciezka, "--tryb-opcji", tryb]), kod)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                main([sciezka])
            self.assertIn("OPCJA_W_SUMIE", out.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
                main([sciezka, "--tryb-opcji", "losowy"])
            self.assertEqual(e.exception.code, 2)

    def test_json_raportu_ma_kwoty_jako_stringi(self):
        from amounts_calc.check import wynik_json
        w = sprawdz_dokument(dok([BAZA, opcja("O1", "50.00")], "150.00"))
        j = json.loads(json.dumps(wynik_json(w)))
        c = [c for c in j["przyczyny"] if c["kod"] == bledy.OPCJA_W_SUMIE][0]
        self.assertEqual(c["roznica_wzgledem_naglowka"]["netto"], "50.00")
        self.assertEqual(c["pozycje"][0]["brutto"], "61.50")


if __name__ == "__main__":
    unittest.main()
