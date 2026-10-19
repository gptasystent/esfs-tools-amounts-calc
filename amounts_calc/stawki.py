"""Stawki VAT i konwersja liczb wejściowych (nigdy float)."""
from decimal import Decimal, InvalidOperation

from .bledy import NIEPOPRAWNA_LICZBA, NIEZNANA_STAWKA, BladWalidacji

# Etykieta stawki -> wartość procentowa. 'zw' i 'np' mają vat = 0.
STAWKI = {
    "23": Decimal(23),
    "8": Decimal(8),
    "5": Decimal(5),
    "0": Decimal(0),
    "zw": Decimal(0),
    "np": Decimal(0),
}
KOLEJNOSC_STAWEK = ("23", "8", "5", "0", "zw", "np")


def do_decimal(wartosc, pole):
    """int / Decimal / str ('12,50' i '12.50') -> Decimal. float i bool są odrzucane."""
    if isinstance(wartosc, (bool, float)):
        raise BladWalidacji(NIEPOPRAWNA_LICZBA, pole, "typ %s niedozwolony (użyj Decimal/int/str)"
                            % type(wartosc).__name__)
    if isinstance(wartosc, Decimal):
        d = wartosc
    elif isinstance(wartosc, int):
        d = Decimal(wartosc)
    elif isinstance(wartosc, str):
        try:
            d = Decimal(wartosc.strip().replace(",", "."))
        except InvalidOperation:
            raise BladWalidacji(NIEPOPRAWNA_LICZBA, pole, "nie jest liczbą: %r" % wartosc) from None
    else:
        raise BladWalidacji(NIEPOPRAWNA_LICZBA, pole, "nieobsługiwany typ %s" % type(wartosc).__name__)
    if not d.is_finite():
        raise BladWalidacji(NIEPOPRAWNA_LICZBA, pole, "wartość musi być skończona: %r" % wartosc)
    return d


def normalizuj_stawke(stawka, pole="stawka_vat"):
    """23 / '23' / '23%' / Decimal('23') / 'ZW' -> etykieta ('23', '8', '5', '0', 'zw', 'np')."""
    if isinstance(stawka, str):
        s = stawka.strip().lower().rstrip("%").strip()
        if s in ("zw", "np"):
            return s
        stawka = s
    if isinstance(stawka, (bool, float)):
        raise BladWalidacji(NIEZNANA_STAWKA, pole, "nieznana stawka: %r" % (stawka,))
    try:
        d = do_decimal(stawka, pole)
    except BladWalidacji:
        raise BladWalidacji(NIEZNANA_STAWKA, pole, "nieznana stawka: %r" % (stawka,)) from None
    if d == d.to_integral_value():
        etykieta = str(int(d))
        if etykieta in STAWKI and etykieta not in ("zw", "np"):
            return etykieta
    raise BladWalidacji(NIEZNANA_STAWKA, pole, "nieznana stawka: %r (dozwolone: %s)"
                        % (stawka, ", ".join(KOLEJNOSC_STAWEK)))


def wartosc_stawki(etykieta):
    return STAWKI[etykieta]
