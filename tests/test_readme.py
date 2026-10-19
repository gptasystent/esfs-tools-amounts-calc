"""README ma dla każdego kodu z bledy.py zalecenie w sekcji "Typowe wyniki i co z nimi zrobić"."""
import os
import re
import unittest

from tests import _bootstrap  # noqa: F401
from amounts_calc import bledy

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wczytaj_readme():
    with open(os.path.join(KORZEN, "README.md"), encoding="utf-8") as f:
        return f.read()


def kody_z_bledy():
    return sorted(n for n, v in vars(bledy).items() if n.isupper() and isinstance(v, str) and v == n)


class TestReadmeKody(unittest.TestCase):
    def sekcja(self):
        tekst = wczytaj_readme()
        poczatek = tekst.index("### Typowe wyniki i co z nimi zrobić")
        koniec = tekst.index("\n### ", poczatek + 5)
        return tekst[poczatek:koniec]

    def test_kazdy_kod_ma_wiersz_z_zaleceniem(self):
        sekcja = self.sekcja()
        wiersze = [l for l in sekcja.splitlines() if l.startswith("| `")]
        brakujace = [k for k in kody_z_bledy() if not any("`%s`" % k in w for w in wiersze)]
        self.assertEqual(brakujace, [])

    def test_kazdy_wiersz_ma_zalecenie(self):
        for l in self.sekcja().splitlines():
            if l.startswith("| `"):
                self.assertRegex(l, r"\*\*(zignoruj|sprawdź dokument|popraw regułę|popraw eksport|zignoruj albo uzupełnij"
                                    r"|sprawdź dokument i poprawę)|tylko API", l)

    def test_wymienione_kody_istnieja(self):
        znane = set(kody_z_bledy())
        for l in self.sekcja().splitlines():
            if l.startswith("| `"):
                for kod in re.findall(r"`([A-Z_]{4,})`", l.split("|")[1]):
                    self.assertIn(kod, znane, l)

    def test_opcje_cli_opisane(self):
        tekst = wczytaj_readme()
        for opcja in ("--dopusc-ujemne", "--nie-dopuszczaj-ujemnych", "VAT_WYLICZONY_ZGODNY", "VAT_WYLICZONY_ROZNY"):
            self.assertIn(opcja, tekst)

    def test_liczba_testow_w_readme_nie_jest_zanizona(self):
        m = re.search(r"\((\d+) test", wczytaj_readme())
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 369)


if __name__ == "__main__":
    unittest.main()
