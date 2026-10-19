"""Reguła zaokrąglania - JEDNO miejsce konfiguracji.

Wszystkie zaokrąglenia w bibliotece przechodzą przez `Konfiguracja.kwota/cena/procent`.
Zmiana trybu zaokrąglania lub liczby miejsc = zmiana tutaj (albo własna instancja
`Konfiguracja` przekazana do funkcji).
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal

from .bledy import NIEPOPRAWNY_TRYB, BladWalidacji

# Tryb liczenia dokumentu
TRYB_NETTO = "netto"
TRYB_BRUTTO = "brutto"
TRYBY = (TRYB_NETTO, TRYB_BRUTTO)

# Sposób liczenia VAT
VAT_PER_POZYCJA = "per_pozycja"
VAT_PER_STAWKA = "per_stawka"
TRYBY_VAT = (VAT_PER_POZYCJA, VAT_PER_STAWKA)

# Szeroki kontekst: duże ilości x ceny nie mogą zepsuć quantize (domyślne 28 cyfr bywa za mało).
KONTEKST = Context(prec=60, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Konfiguracja:
    zaokraglanie: str = ROUND_HALF_UP  # reguła dla WSZYSTKICH zaokrągleń
    miejsca_kwot: int = 2              # grosz: wartość pozycji, VAT, netto, brutto
    miejsca_ceny: int = 4              # cena jednostkowa po rabacie
    miejsca_procent: int = 2           # wynik narzutu/marży w %
    tryb_vat: str = VAT_PER_STAWKA     # domyślny sposób liczenia VAT

    def __post_init__(self):
        if self.tryb_vat not in TRYBY_VAT:
            raise BladWalidacji(NIEPOPRAWNY_TRYB, "tryb_vat", "dozwolone: %s" % (TRYBY_VAT,))

    def _kwantyzuj(self, x, miejsca):
        return x.quantize(Decimal(1).scaleb(-miejsca), rounding=self.zaokraglanie, context=KONTEKST)

    def kwota(self, x):
        return self._kwantyzuj(x, self.miejsca_kwot)

    def cena(self, x):
        return self._kwantyzuj(x, self.miejsca_ceny)

    def procent(self, x):
        return self._kwantyzuj(x, self.miejsca_procent)


DOMYSLNA = Konfiguracja()
