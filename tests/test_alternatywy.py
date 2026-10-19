"""Alternatywy ("OPCJA 1" / "OPCJA 2"): do sumy wchodzi co najwyżej jedna z grupy."""
import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy, dokument_z_slownika, sprawdz_spojnosc
from amounts_calc.model import grupa_alternatywy
from tests.test_zestawy_ilosc import dokument, dziecko, kody, kwoty, zestaw


def poz(id_, netto, stawka=23, **extra):
    d = {"id": id_, "ilosc": 1, "stawka_vat": stawka}
    d.update(kwoty(netto, stawka))
    d.update(extra)
    return d


def dok(pozycje, netto, **extra):
    """Dokument z nagłówkiem o podanym netto (VAT 23% od całości)."""
    d = {"pozycje": pozycje}
    d.update({"suma_" + k: v for k, v in kwoty(netto).items()})
    d.update(extra)
    return d


BAZA = poz("B", "100.00")
OPCJE = [poz("O1", "40.00", alternatywa=True), poz("O2", "60.00", alternatywa=True)]


class TestGrupa(unittest.TestCase):
    def test_tabela(self):
        tabela = [((None, None), None), ((True, None), ""), (("tak", None), ""), ((1, None), ""),
                  ((False, None), None), (("nie", None), None), ((0, None), None), (("false", "A"), None),
                  ((None, "A"), "A"), ((True, "A"), "A"), (("", None), None), ((None, ""), None), ((None, "  "), None),
                  ((None, 7), 7), ((D(1), None), "")]
        for (alt, grupa), oczek in tabela:
            with self.subTest(alt=alt, grupa=grupa):
                self.assertEqual(grupa_alternatywy(alt, grupa), oczek)


class TestSumaZAlternatywami(unittest.TestCase):
    def test_naglowek_baza_plus_jedna_opcja_jest_zgodny(self):
        for netto, wybrana in [("100.00", ()), ("140.00", (1,)), ("160.00", (2,))]:
            with self.subTest(netto=netto):
                d = dok([BAZA] + OPCJE, netto)
                w = sprawdz_spojnosc(d)
                self.assertEqual(w, [])
                dok_ = dokument_z_slownika(d)
                self.assertEqual((dok_.wlaczone_alternatywy, dok_.alternatywy), (wybrana, "zgodne"))

    def test_naglowek_ze_wszystkimi_opcjami_jest_niespojny(self):
        d = dok([BAZA] + OPCJE, "200.00")             # obie opcje dodane "po cichu" do sumy
        dok_ = dokument_z_slownika(d)
        self.assertEqual(dok_.alternatywy, "najblizsze")
        w = sprawdz_spojnosc(d)
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))
        netto = [x for x in w if x["kod"] == bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU and x["pole"] == "suma_netto"][0]
        self.assertEqual(abs(netto["roznica"]), D("40.00"))     # najbliższa kombinacja: baza + O2 (160), różnica 40

    def test_bez_pol_alternatywy_zachowanie_dotychczasowe(self):
        pozycje = [dict(p) for p in [BAZA] + OPCJE]
        for p in pozycje:
            p.pop("alternatywa", None)
        self.assertEqual(sprawdz_spojnosc(dok(pozycje, "200.00")), [])
        w = sprawdz_spojnosc(dok(pozycje, "100.00"))
        self.assertIn(bledy.SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, kody(w))
        self.assertEqual(dokument_z_slownika(dok(pozycje, "200.00")).alternatywy, "brak")

    def test_dwie_grupy_niezaleznie(self):
        pozycje = [BAZA, poz("A1", "10.00", grupa_opcji="A"), poz("A2", "20.00", grupa_opcji="A"),
                   poz("B1", "5.00", grupa_opcji="B"), poz("B2", "7.00", grupa_opcji="B")]
        for netto, wybrana in [("100.00", ()), ("115.00", (1, 3)), ("127.00", (2, 4)), ("110.00", (1,)), ("107.00", (4,))]:
            d = dok(pozycje, netto)
            self.assertEqual(sprawdz_spojnosc(d), [], netto)
            self.assertEqual(dokument_z_slownika(d).wlaczone_alternatywy, wybrana, netto)

    def test_podsumowanie_stawek_tylko_z_wybranych(self):
        pozycje = [BAZA, poz("O1", "40.00", stawka=8, alternatywa=True), poz("O2", "60.00", alternatywa=True)]
        d = dok(pozycje, "140.00")
        d["suma_vat"], d["suma_brutto"] = "26.20", "166.20"          # 100 @23% + 40 @8%
        dok_ = dokument_z_slownika(d)
        self.assertEqual({s.stawka_vat: s.netto for s in dok_.podsumowanie}, {"23": D("100.00"), "8": D("40.00")})
        self.assertEqual(sprawdz_spojnosc(d), [])

    def test_alternatywa_zestawu(self):
        dzieci = [dziecko("c1", "10.00", parent="O")]
        o = zestaw(3, dzieci, id_="O", alternatywa=True)
        pozycje = [poz("B", "100.00"), o] + dzieci
        d = dok(pozycje, "130.00")
        self.assertEqual(sprawdz_spojnosc(dict(d, ilosc_zestawu=True)), [])
        self.assertEqual(dokument_z_slownika(d, ilosc_zestawu=True).wlaczone_alternatywy, (1,))

    def test_alternatywa_na_dziecku_jest_ignorowana(self):
        dzieci = [dziecko("c1", "10.00", alternatywa=True)]
        pozycje = [zestaw(1, dzieci)] + dzieci
        d = dokument(pozycje)
        self.assertEqual(sprawdz_spojnosc(d), [])
        self.assertEqual(dokument_z_slownika(d).alternatywy, "brak")

    def test_jedna_alternatywa_sama(self):
        pozycje = [BAZA, poz("O1", "40.00", alternatywa=True)]
        for netto in ("100.00", "140.00"):
            self.assertEqual(sprawdz_spojnosc(dok(pozycje, netto)), [], netto)


if __name__ == "__main__":
    unittest.main()
