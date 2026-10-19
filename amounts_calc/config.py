"""Reguła zaokrąglania - JEDNO miejsce konfiguracji.

Wszystkie zaokrąglenia w bibliotece przechodzą przez `Konfiguracja.kwota/cena/procent`.
Zmiana trybu zaokrąglania lub liczby miejsc = zmiana tutaj (albo własna instancja
`Konfiguracja` przekazana do funkcji).
"""
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Context, Decimal

from .bledy import NIEPOPRAWNY_TRYB, BladWalidacji

# Tryb liczenia dokumentu
TRYB_NETTO = "netto"
TRYB_BRUTTO = "brutto"
TRYBY = (TRYB_NETTO, TRYB_BRUTTO)

# Sposób liczenia VAT
VAT_PER_POZYCJA = "per_pozycja"
VAT_PER_STAWKA = "per_stawka"
TRYBY_VAT = (VAT_PER_POZYCJA, VAT_PER_STAWKA)

# Rozkład korekty groszowej w trybie VAT per stawka (różnica: VAT z sumy stawki - suma VAT pozycji)
ROZKLAD_NAJWIEKSZA = "najwieksza"            # cała różnica na pozycję o największej wartości
ROZKLAD_PROPORCJONALNIE = "proporcjonalnie"  # po 1 gr wg największych reszt (metoda Hare'a)
ROZKLADY = (ROZKLAD_NAJWIEKSZA, ROZKLAD_PROPORCJONALNIE)

# Szeroki kontekst: duże ilości x ceny nie mogą zepsuć quantize (domyślne 28 cyfr bywa za mało).
KONTEKST = Context(prec=60, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Konfiguracja:
    zaokraglanie: str = ROUND_HALF_UP  # reguła dla WSZYSTKICH zaokrągleń
    miejsca_kwot: int = 2              # grosz: wartość pozycji, VAT, netto, brutto
    miejsca_ceny: int = 4              # cena jednostkowa po rabacie
    miejsca_procent: int = 2           # wynik narzutu/marży w %
    tryb_vat: str = VAT_PER_STAWKA     # domyślny sposób liczenia VAT
    rozklad_korekty: str = ROZKLAD_NAJWIEKSZA  # jak rozdzielić korektę groszową (per stawka)

    def __post_init__(self):
        if self.tryb_vat not in TRYBY_VAT:
            raise BladWalidacji(NIEPOPRAWNY_TRYB, "tryb_vat", "dozwolone: %s" % (TRYBY_VAT,))
        if self.rozklad_korekty not in ROZKLADY:
            raise BladWalidacji(NIEPOPRAWNY_TRYB, "rozklad_korekty", "dozwolone: %s" % (ROZKLADY,))

    def _kwantyzuj(self, x, miejsca):
        return x.quantize(Decimal(1).scaleb(-miejsca), rounding=self.zaokraglanie, context=KONTEKST)

    def kwota(self, x):
        return self._kwantyzuj(x, self.miejsca_kwot)

    def cena(self, x):
        return self._kwantyzuj(x, self.miejsca_ceny)

    def procent(self, x):
        return self._kwantyzuj(x, self.miejsca_procent)

    @property
    def grosz(self):
        return Decimal(1).scaleb(-self.miejsca_kwot)

    def podloga(self, x):
        """Zaokrąglenie w dół do grosza (używane tylko przez rozkład 'proporcjonalnie')."""
        return x.quantize(self.grosz, rounding=ROUND_FLOOR, context=KONTEKST)


DOMYSLNA = Konfiguracja()
