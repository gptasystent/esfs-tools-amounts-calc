"""Niezależna implementacja referencyjna na fractions.Fraction. NIE importuje amounts_calc.

Dwa warianty, oba w trybie VAT "per pozycja" (zaokrąglenia zawsze half-up, kwoty >= 0):

policz_wg_specyfikacji  Te same PUNKTY zaokrąglania co biblioteka (cena po rabacie -> 4 miejsca,
                        wartość pozycji -> grosz, wartość po rabacie dokumentu -> grosz, rozbicie
                        na netto/vat/brutto -> grosz), ale arytmetyka wymierna zamiast Decimal.
                        Oczekiwana zgodność DOKŁADNA co do grosza.

policz_dokladnie        Wszystko dokładnie (bez żadnych zaokrągleń pośrednich); zaokrąglenie dopiero
                        na końcu każdej kwoty. Zgodność z biblioteką tylko do granic podanych w
                        `granica_netto` i `granica_vat`.

MIEJSCA, W KTÓRYCH METODY CELOWO SIĘ RÓŻNIĄ (biblioteka vs policz_dokladnie):
  1. Cena po rabacie jest zaokrąglana do 4 miejsc (policz_dokladnie: dokładna).
     Błąd wartości pozycji do ilosc * 0,00005.
  2. Wartość pozycji jest zaokrąglana do grosza ZANIM zostanie użyta do VAT-u (podwójne
     zaokrąglenie); referencja liczy VAT z wartości dokładnej. Błąd do 0,005 * stawka + zaokrąglenie.
  3. Rabat dokumentu jest stosowany do już zaokrąglonej wartości pozycji.
  4. W trybie od brutto netto jest liczone z zaokrąglonego brutto pozycji.
Tryb per_stawka (korekta groszowa) nie ma tu odpowiednika - referencja go nie modeluje.
"""
from fractions import Fraction

SETKA = Fraction(1, 100)


def zaokraglij(x, miejsca):
    """half-up dla x >= 0: floor(x * 10^m + 1/2) / 10^m."""
    skala = 10 ** miejsca
    return Fraction(int((x * skala + Fraction(1, 2)) // 1), skala)


def _ulamek(x):
    return Fraction(str(x)) if not isinstance(x, Fraction) else x


def _wartosci_dokladne(poz, rabat_dok):
    ilosc, cena, rabat, _ = poz
    return _ulamek(ilosc) * _ulamek(cena) * (1 - _ulamek(rabat) / 100) * (1 - _ulamek(rabat_dok) / 100)


def _rozbij(kwota, stawka, tryb, zaokr):
    r = Fraction(stawka, 100)
    if tryb == "netto":
        netto = kwota
        vat = zaokr(netto * r)
        return netto, vat, netto + vat
    netto = zaokr(kwota / (1 + r))
    return netto, kwota - netto, kwota


def policz_wg_specyfikacji(pozycje, tryb, rabat_dok=0, miejsca_ceny=4):
    """pozycje: [(ilosc, cena, rabat_proc, stawka_proc_int)]. Zwraca listę (netto, vat, brutto)."""
    wynik = []
    for ilosc, cena, rabat, stawka in pozycje:
        cena_po = zaokraglij(_ulamek(cena) * (1 - _ulamek(rabat) / 100), miejsca_ceny)
        wartosc = zaokraglij(_ulamek(ilosc) * cena_po, 2)
        if _ulamek(rabat_dok) > 0:
            wartosc = zaokraglij(wartosc * (1 - _ulamek(rabat_dok) / 100), 2)
        wynik.append(_rozbij(wartosc, stawka, tryb, lambda x: zaokraglij(x, 2)))
    return wynik


def policz_dokladnie(pozycje, tryb, rabat_dok=0):
    """Dokładne (Fraction) netto/vat/brutto każdej pozycji, BEZ zaokrągleń. Zwraca listę trójek."""
    wynik = []
    for poz in pozycje:
        kwota = _wartosci_dokladne(poz, rabat_dok)
        r = Fraction(poz[3], 100)
        if tryb == "netto":
            wynik.append((kwota, kwota * r, kwota * (1 + r)))
        else:
            netto = kwota / (1 + r)
            wynik.append((netto, kwota - netto, kwota))
    return wynik


def granica_netto(ilosc, rabat_dok=0):
    """Maks. |biblioteka - dokładna| dla kwoty pozycji (netto w trybie netto, brutto w brutto):
    zaokrąglenie ceny (ilosc * 0,00005), wartości pozycji (0,005), rabatu dok. (0,005)."""
    return _ulamek(ilosc) * Fraction(5, 100000) + Fraction(5, 1000) * 2


def granica_vat(ilosc, stawka, tryb, rabat_dok=0):
    """Maks. |biblioteka - dokładna| dla VAT pozycji."""
    b = granica_netto(ilosc, rabat_dok)
    if tryb == "netto":
        return Fraction(5, 1000) + Fraction(stawka, 100) * b
    return 2 * b + Fraction(5, 1000)
