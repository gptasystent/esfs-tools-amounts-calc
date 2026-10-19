import unittest
from decimal import Decimal as D

from tests import _bootstrap  # noqa: F401
from amounts_calc import oblicz, Pozycja
from amounts_calc.config import Konfiguracja, VAT_PER_POZYCJA, VAT_PER_STAWKA


def poz(ilosc, cena, stawka=23, rabat=0):
    return Pozycja(ilosc=ilosc, cena_netto_jedn=cena, stawka_vat=stawka, rabat_proc=rabat)


class TestPodstawy(unittest.TestCase):
    def test_jedna_pozycja(self):
        d = oblicz([poz(2, "10.00")])
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("20.00"), D("4.60"), D("24.60")))

    def test_pusty_dokument(self):
        d = oblicz([])
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D(0), D(0), D(0)))
        self.assertEqual(d.pozycje, ())

    def test_zw_np_vat_zero(self):
        for st in ("zw", "np", 0):
            with self.subTest(st=st):
                d = oblicz([poz(3, "7.77", st)])
                self.assertEqual(d.suma_vat, D("0.00"))
                self.assertEqual(d.suma_brutto, D("23.31"))

    def test_stawki_podsumowanie_kolejnosc(self):
        d = oblicz([poz(1, "1", "np"), poz(1, "1", 5), poz(1, "1", 23), poz(1, "1", "zw"),
                    poz(1, "1", 8), poz(1, "1", 0)])
        self.assertEqual([s.stawka_vat for s in d.podsumowanie], ["23", "8", "5", "0", "zw", "np"])

    def test_podsumowanie_sumuje_pozycje_stawki(self):
        d = oblicz([poz(1, "10", 23), poz(2, "5", 23), poz(1, "100", 8)])
        s23, s8 = d.stawka("23"), d.stawka("8")
        self.assertEqual((s23.netto, s23.vat, s23.brutto), (D("20.00"), D("4.60"), D("24.60")))
        self.assertEqual((s8.netto, s8.vat, s8.brutto), (D("100.00"), D("8.00"), D("108.00")))
        self.assertIsNone(d.stawka("5"))

    def test_wejscie_jako_slownik_i_stringi_z_przecinkiem(self):
        d = oblicz([{"ilosc": "2", "cena_netto_jedn": "12,50", "stawka_vat": "23"}])
        self.assertEqual(d.suma_netto, D("25.00"))

    def test_waluta_etykieta(self):
        self.assertEqual(oblicz([poz(1, "1")], waluta="EUR").waluta, "EUR")

    def test_wynik_to_decimal(self):
        d = oblicz([poz(1, "1.10")])
        for v in (d.suma_netto, d.suma_vat, d.suma_brutto, d.pozycje[0].netto):
            self.assertIsInstance(v, D)


class TestVatPerPozycjaVsPerStawka(unittest.TestCase):
    """Test pokazujący różnicę w groszach między trybami VAT."""

    def setUp(self):
        self.poz = [poz(1, "0.33")] * 3

    def test_roznica_w_groszach(self):
        a = oblicz(self.poz, tryb_vat=VAT_PER_POZYCJA)
        b = oblicz(self.poz, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual(a.suma_netto, D("0.99"))
        self.assertEqual(b.suma_netto, D("0.99"))
        self.assertEqual(a.suma_vat, D("0.24"))   # 3 x round(0.0759) = 3 x 0.08
        self.assertEqual(b.suma_vat, D("0.23"))   # round(0.99 * 0.23 = 0.2277)
        self.assertEqual(a.suma_vat - b.suma_vat, D("0.01"))

    def test_rozbieznosc_vat_niezalezna_od_trybu(self):
        a = oblicz(self.poz, tryb_vat=VAT_PER_POZYCJA)
        b = oblicz(self.poz, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual(a.rozbieznosc_vat, D("0.01"))
        self.assertEqual(b.rozbieznosc_vat, D("0.01"))

    def test_per_stawka_koryguje_najwieksza_pozycje(self):
        d = oblicz([poz(1, "0.33"), poz(1, "0.34"), poz(1, "0.33")], tryb_vat=VAT_PER_STAWKA)
        # naive: 0.08 + 0.08 + 0.08 = 0.24; per stawka: round(1.00*0.23)=0.23; korekta -0.01 na pozycji 1
        self.assertEqual([p.vat for p in d.pozycje], [D("0.08"), D("0.07"), D("0.08")])
        self.assertEqual(d.suma_vat, D("0.23"))

    def test_remis_najnizszy_indeks(self):
        d = oblicz([poz(1, "0.33")] * 3, tryb_vat=VAT_PER_STAWKA)
        self.assertEqual([p.vat for p in d.pozycje], [D("0.07"), D("0.08"), D("0.08")])

    def test_konfiguracja_domyslna_per_stawka(self):
        self.assertEqual(oblicz(self.poz).tryb_vat, VAT_PER_STAWKA)
        k = Konfiguracja(tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual(oblicz(self.poz, konfiguracja=k).suma_vat, D("0.24"))

    def test_tryb_vat_param_nadpisuje_konfiguracje(self):
        k = Konfiguracja(tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual(oblicz(self.poz, tryb_vat=VAT_PER_STAWKA, konfiguracja=k).suma_vat, D("0.23"))

    def test_rozne_stawki_korekta_tylko_w_swojej_grupie(self):
        d = oblicz([poz(1, "0.33", 23)] * 3 + [poz(1, "0.33", 8)] * 3)
        self.assertEqual(d.stawka("23").vat, D("0.23"))
        self.assertEqual(d.stawka("8").vat, D("0.08"))  # round(0.99*0.08=0.0792)
        self.assertEqual(sum(p.vat for p in d.pozycje if p.stawka_vat == "8"), D("0.08"))


class TestRegresja3x033(unittest.TestCase):
    """Regresja: 3 x 0,33 = 0,99 vs 1,00 (suma zaokrąglonych vs zaokrąglona suma)."""

    def test_trzy_pozycje_po_033(self):
        d = oblicz([poz(1, "0.33")] * 3)
        self.assertEqual(d.suma_netto, D("0.99"))
        self.assertEqual(d.suma_netto, sum(p.netto for p in d.pozycje))

    def test_ilosc_3_x_033(self):
        self.assertEqual(oblicz([poz(3, "0.33")]).suma_netto, D("0.99"))

    def test_cena_3333_trzy_pozycje(self):
        # 3 x 0.3333 = 0.9999 -> "zaokrąglona suma" dałaby 1.00; reguła: zaokrąglamy wartość
        # każdej pozycji (0.33), więc dokument = 0.99 i zgadza się z sumą pozycji.
        d = oblicz([poz(1, "0.3333")] * 3)
        self.assertEqual(d.suma_netto, D("0.99"))
        self.assertEqual(sum(p.netto for p in d.pozycje), d.suma_netto)

    def test_jedna_pozycja_ilosc_3_cena_3333_daje_100(self):
        # tutaj zaokrąglenie dotyczy wartości pozycji 0.9999 -> 1.00
        self.assertEqual(oblicz([poz(3, "0.3333")]).suma_netto, D("1.00"))


class TestPrzypadkiGraniczne(unittest.TestCase):
    def test_polgrosza_wartosc_pozycji(self):
        tabela = [("0.005", 1, "0.01"), ("0.015", 1, "0.02"), ("0.025", 1, "0.03"),
                  ("0.001", 5, "0.01"), ("0.0049", 1, "0.00"), ("0.5", "0.01", "0.01")]
        for cena, ilosc, oczek in tabela:
            with self.subTest(cena=cena, ilosc=ilosc):
                d = oblicz([poz(ilosc, cena, 0)])
                self.assertEqual(d.suma_netto, D(oczek))

    def test_vat_23_od_001(self):
        d = oblicz([poz(1, "0.01")])
        self.assertEqual((d.suma_netto, d.suma_vat, d.suma_brutto), (D("0.01"), D("0.00"), D("0.01")))

    def test_vat_polgrosza(self):
        # 0.50 * 23% = 0.115 -> 0.12 (half up)
        self.assertEqual(oblicz([poz(1, "0.50")]).suma_vat, D("0.12"))
        # 0.30 * 5% = 0.015 -> 0.02
        self.assertEqual(oblicz([poz(1, "0.30", 5)]).suma_vat, D("0.02"))

    def test_bardzo_duze_ilosci(self):
        d = oblicz([poz(10 ** 15, "99999.99")])
        self.assertEqual(d.suma_netto, D("99999990000000000000.00"))
        self.assertEqual(d.suma_vat, D("22999997700000000000.00"))
        self.assertEqual(d.suma_netto + d.suma_vat, d.suma_brutto)

    def test_ilosc_ulamkowa(self):
        self.assertEqual(oblicz([poz("0.333", "3.00")]).suma_netto, D("1.00"))  # 0.999
        self.assertEqual(oblicz([poz("2.5", "1.01")]).suma_netto, D("2.53"))    # 2.525

    def test_tysiac_pozycji_po_001(self):
        d = oblicz([poz(1, "0.01")] * 1000)
        self.assertEqual(d.suma_netto, D("10.00"))
        self.assertEqual(d.suma_vat, D("2.30"))           # per stawka: 10.00 * 23%
        self.assertEqual(d.suma_brutto, D("12.30"))
        self.assertEqual(sum(p.vat for p in d.pozycje), d.suma_vat)
        self.assertEqual(d.rozbieznosc_vat, D("-2.30"))   # per pozycja każdy vat = 0.00

    def test_tysiac_pozycji_per_pozycja(self):
        d = oblicz([poz(1, "0.01")] * 1000, tryb_vat=VAT_PER_POZYCJA)
        self.assertEqual(d.suma_vat, D("0.00"))
        self.assertEqual(d.suma_brutto, D("10.00"))

    def test_zero_ilosci_i_zero_ceny(self):
        d = oblicz([poz(0, "10"), poz(5, "0")])
        self.assertEqual(d.suma_brutto, D("0.00"))

    def test_33_33_proc_rabatu_x_3_pozycje(self):
        d = oblicz([poz(1, "10.00", rabat="33.33")] * 3)
        # cena po rabacie 6.667 -> 6.6670 (4 miejsca), wartość 6.67 x 3
        self.assertEqual([p.netto for p in d.pozycje], [D("6.67")] * 3)
        self.assertEqual(d.suma_netto, D("20.01"))


class TestRabaty(unittest.TestCase):
    def test_rabat_pozycji(self):
        d = oblicz([poz(2, "100.00", rabat=10)])
        self.assertEqual(d.pozycje[0].cena_po_rabacie, D("90.0000"))
        self.assertEqual(d.suma_netto, D("180.00"))

    def test_rabat_100(self):
        self.assertEqual(oblicz([poz(2, "100.00", rabat=100)]).suma_brutto, D("0.00"))

    def test_rabat_dokumentu(self):
        d = oblicz([poz(1, "100.00")], rabat_dokumentu_proc=10)
        self.assertEqual(d.suma_netto, D("90.00"))
        self.assertEqual(d.suma_vat, D("20.70"))

    def test_kolejnosc_rabatow_pozycja_potem_dokument(self):
        d = oblicz([poz(1, "200.00", rabat=10)], rabat_dokumentu_proc=10)
        self.assertEqual(d.suma_netto, D("162.00"))  # 200 -> 180 -> 162, nie 200 * 0.80

    def test_rabat_pozycji_zaokraglany_do_cen(self):
        d = oblicz([poz(3, "0.33", rabat=10)])
        self.assertEqual(d.pozycje[0].cena_po_rabacie, D("0.2970"))
        self.assertEqual(d.suma_netto, D("0.89"))  # 3 * 0.297 = 0.891

    def test_miejsca_ceny_konfigurowalne(self):
        k = Konfiguracja(miejsca_ceny=2)
        d = oblicz([poz(3, "0.33", rabat=10)], konfiguracja=k)
        self.assertEqual(d.pozycje[0].cena_po_rabacie, D("0.30"))
        self.assertEqual(d.suma_netto, D("0.90"))

    def test_rabat_dokumentu_na_wielu_stawkach(self):
        d = oblicz([poz(1, "100", 23), poz(1, "100", 8)], rabat_dokumentu_proc=50)
        self.assertEqual(d.stawka("23").netto, D("50.00"))
        self.assertEqual(d.stawka("8").vat, D("4.00"))


if __name__ == "__main__":
    unittest.main()
