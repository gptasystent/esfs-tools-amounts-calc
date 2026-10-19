"""FLOAT_W_FUNKCJI_KWOTOWEJ w SQL: rzutowanie na końcu wyrażenia to format wyniku, nie obliczenie (runda 10)."""
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc.skan_kodu import skanuj, skanuj_tekst

FLOAT = "FLOAT_W_FUNKCJI_KWOTOWEJ"


def float_w(tekst, jezyk):
    return [z for z in skanuj_tekst(tekst, "x", jezyk) if z.kod == FLOAT]


def py_sql(zapytanie):
    return 'wiersze = cur.execute("""\n%s\n""")\n' % zapytanie


# 10 wymyślonych zapytań, w których ::float / CAST stoi na końcu wyrażenia (do JSON-a): żadne nie może dać znaleziska
KONCOWE = [
    "SELECT COALESCE(MAX(ps.kwota_pozostala), f.kwota_brutto - COALESCE(f.kwota_zaplacona, 0))::float FROM faktury f",
    "SELECT COALESCE(SUM(kwota_przypisana), 0)::float as suma FROM przypisania",
    "SELECT cena_calkowita::float AS cena_calkowita, stawka_vat::float AS stawka_vat FROM oferty",
    "SELECT SUM(p.wartosc_brutto)::float AS brutto FROM pozycje p",
    "SELECT ROUND(SUM(fz.kwota_brutto), 0)::float AS suma_brutto FROM zaplaty fz",
    "SELECT kwota_vat::float, id FROM pozycje",
    "SELECT id, wartosc_netto::double precision AS netto FROM pozycje",
    "SELECT CAST(SUM(wartosc_netto) AS float) AS suma_netto FROM pozycje",
    "SELECT json_build_object('brutto', SUM(wartosc_brutto)::float, 'n', COUNT(*)) FROM pozycje",
    "SELECT\n  f.id,\n  (f.kwota_brutto - f.kwota_zaplacona)::float\nFROM faktury f",
]

# zapytania, w których rzutowanie jest wewnątrz dalszego obliczenia albo porównania: muszą dać znalezisko
WEWNATRZ = [
    ("mnozenie", "SELECT (kwota_netto::float * stawka_vat::float / 100) AS vat FROM pozycje"),
    ("przed stawka", "SELECT wartosc_netto::float * stawka_vat FROM pozycje"),
    ("dzielenie", "SELECT wartosc_brutto::float / 1 FROM pozycje"),
    ("z lewej strony", "SELECT 0.5 * wartosc_netto::float FROM pozycje"),
    ("operand w nawiasie", "SELECT (kwota_netto)::float * stawka FROM pozycje"),
    ("suma przed mnozeniem", "SELECT SUM(kwota_netto)::float * stawka_vat FROM pozycje"),
    ("odejmowanie", "SELECT a.kwota_brutto::double precision - a.kwota_netto AS vat FROM pozycje a"),
    ("where", "SELECT id FROM faktury WHERE kwota_brutto::float > 100"),
    ("having", "SELECT dok_id FROM pozycje GROUP BY dok_id HAVING SUM(kwota_brutto)::float > 0"),
    ("cast mnozenie", "SELECT CAST(kwota_netto AS float) * stawka_vat FROM pozycje"),
    ("cast porownanie", "SELECT id FROM faktury WHERE CAST(kwota_brutto AS float) >= kwota_netto"),
    ("cast w nawiasie", "SELECT (CAST(wartosc_brutto AS real)) - wartosc_netto FROM pozycje"),
]


class TestRzutNaKoncuWyrazenia(unittest.TestCase):
    def test_koncowe_rzutowanie_w_tekscie_pythona_nie_daje_znalezisk(self):
        for zapytanie in KONCOWE:
            with self.subTest(zapytanie):
                self.assertEqual(float_w(py_sql(zapytanie), "py"), [])

    def test_koncowe_rzutowanie_w_pliku_sql_nie_daje_znalezisk(self):
        for zapytanie in KONCOWE:
            with self.subTest(zapytanie):
                self.assertEqual(float_w(zapytanie + ";\n", "sql"), [])

    def test_dziesiec_fragmentow_razem_spada_do_zera(self):
        with tempfile.TemporaryDirectory() as t:
            for i, zapytanie in enumerate(KONCOWE):
                with open(os.path.join(t, "r%d.py" % i), "w", encoding="utf-8") as f:
                    f.write(py_sql(zapytanie))
                with open(os.path.join(t, "q%d.sql" % i), "w", encoding="utf-8") as f:
                    f.write(zapytanie + ";\n")
            for tryb in ("pelny", "istotne"):
                znaleziska, stat = skanuj([t], tryb=tryb)
                self.assertEqual([z for z in znaleziska if z.kod == FLOAT], [], tryb)
                self.assertEqual(stat["przed_odszumieniem"]["wg_kodu"].get(FLOAT, 0), 0)

    def test_rzut_z_aliasem_przecinkiem_nawiasem_i_koncem_instrukcji(self):
        for koniec in (" AS x FROM p", ", id FROM p", " FROM p", ") FROM p", " ORDER BY 1"):
            with self.subTest(koniec):
                zapytanie = "SELECT (SUM(kwota_netto)::float%s" % koniec
                self.assertEqual(float_w(py_sql(zapytanie.replace("(SUM", "SUM", 1) if ")" not in koniec else zapytanie),
                                         "py"), [])


class TestRzutWewnatrzObliczenia(unittest.TestCase):
    def test_wewnatrz_obliczenia_trafia(self):
        for nazwa, zapytanie in WEWNATRZ:
            with self.subTest(nazwa):
                self.assertEqual(len(float_w(py_sql(zapytanie), "py")), 1)
                self.assertEqual(len(float_w(zapytanie + ";\n", "sql")), 1)

    def test_wiele_rzutow_w_jednym_obliczeniu_to_po_jednym_znalezisku_na_linie(self):
        z = float_w("SELECT a_netto::float * b_netto::float FROM p;\n", "sql")
        self.assertEqual([x.linia for x in z], [1])

    def test_wieloliniowe_zapytanie_numer_linii(self):
        tekst = "SELECT\n  id,\n  kwota_netto::float\n    * stawka_vat AS vat\nFROM p;\n"
        self.assertEqual([x.linia for x in float_w(tekst, "sql")], [3])

    def test_znaleziska_zostaja_w_trybie_istotne(self):
        with tempfile.TemporaryDirectory() as t:
            with open(os.path.join(t, "a.py"), "w", encoding="utf-8") as f:
                f.write(py_sql(WEWNATRZ[0][1]))
            znaleziska, _ = skanuj([t], tryb="istotne")
            self.assertEqual([(z.kod, z.waznosc) for z in znaleziska if z.kod == FLOAT], [(FLOAT, "srednia")])


class TestBezZmian(unittest.TestCase):
    def test_typ_kolumny_nadal_zgloszony(self):
        for tekst in ("CREATE TABLE p (id int, wartosc_netto float, kwota_vat real);\n",
                      "ALTER TABLE p ADD COLUMN suma_brutto double precision;\n"):
            self.assertTrue(float_w(tekst, "sql"), tekst)

    def test_python_float_w_arytmetyce_z_vat_nadal_zgloszony(self):
        z = float_w("brutto = float(netto) * (1 + float(vat) / 100)\n", "py")
        self.assertEqual([(x.waznosc, x.po_odszumieniu) for x in z], [("srednia", "srednia")])
        z = float_w("suma = float(row['netto']) + float(row['vat'])\n", "py")
        self.assertEqual([x.po_odszumieniu for x in z], ["niska"])

    def test_python_float_odczyt_nadal_szumem(self):
        z = float_w("kwota = float(row['kwota'])\n", "py")
        self.assertEqual([x.po_odszumieniu for x in z], [None])

    def test_rzut_niekwotowy_nigdy_nie_byl_zglaszany(self):
        self.assertEqual(float_w("SELECT waga::float * 2 FROM paczki;\n", "sql"), [])

    def test_inne_kody_sql_bez_zmian(self):
        kody = {z.kod for z in skanuj_tekst("SELECT SUM(kwota_brutto)::float, SUM(kwota_netto) FROM p;\n", "x", "sql")}
        self.assertEqual(kody, {"SUMOWANIE_NIESPOJNE"})


if __name__ == "__main__":
    unittest.main()
