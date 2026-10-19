"""Narzut vs marża.

narzut % = (cena - koszt) / koszt * 100     (względem KOSZTU)
marża %  = (cena - koszt) / cena  * 100     (względem CENY SPRZEDAŻY)

Koszt 80, cena 100: narzut 25%, marża 20%. Marża < 100% zawsze; narzut może przekraczać 100%.
"""
from decimal import Decimal, localcontext

from .bledy import (DZIELENIE_PRZEZ_ZERO, MARZA_POZA_ZAKRESEM, NARZUT_I_MARZA, NIEPOPRAWNA_LICZBA,
                    BladWalidacji)
from .config import DOMYSLNA, KONTEKST
from .stawki import do_decimal

_100 = Decimal(100)


def _nieujemna(wartosc, pole):
    d = do_decimal(wartosc, pole)
    if d < 0:
        raise BladWalidacji(NIEPOPRAWNA_LICZBA, pole, "wartość nie może być ujemna: %s" % d)
    return d


def cena_z_narzutu(koszt, narzut_proc, konf=DOMYSLNA):
    """cena = koszt * (1 + narzut/100), zaokrąglona do miejsc ceny."""
    k, n = _nieujemna(koszt, "koszt"), do_decimal(narzut_proc, "narzut_proc")
    if n < -_100:
        raise BladWalidacji(MARZA_POZA_ZAKRESEM, "narzut_proc", "narzut < -100%% daje cenę ujemną: %s" % n)
    return konf.cena(k * (1 + n / _100))


def cena_z_marzy(koszt, marza_proc, konf=DOMYSLNA):
    """cena = koszt / (1 - marża/100); marża musi być < 100%."""
    k, m = _nieujemna(koszt, "koszt"), do_decimal(marza_proc, "marza_proc")
    if m >= _100:
        raise BladWalidacji(MARZA_POZA_ZAKRESEM, "marza_proc", "marża musi być < 100%%: %s" % m)
    return konf.cena(k / (1 - m / _100))


def narzut_z_cen(koszt, cena, konf=DOMYSLNA):
    k, c = _nieujemna(koszt, "koszt"), _nieujemna(cena, "cena")
    if k == 0:
        raise BladWalidacji(DZIELENIE_PRZEZ_ZERO, "koszt", "narzut względem kosztu 0 jest nieokreślony")
    return konf.procent((c - k) / k * _100)


def marza_z_cen(koszt, cena, konf=DOMYSLNA):
    k, c = _nieujemna(koszt, "koszt"), _nieujemna(cena, "cena")
    if c == 0:
        raise BladWalidacji(DZIELENIE_PRZEZ_ZERO, "cena", "marża względem ceny 0 jest nieokreślona")
    return konf.procent((c - k) / c * _100)


def marza_z_narzutu(narzut_proc, konf=DOMYSLNA):
    n = do_decimal(narzut_proc, "narzut_proc")
    if n <= -_100:
        raise BladWalidacji(MARZA_POZA_ZAKRESEM, "narzut_proc", "narzut musi być > -100%%: %s" % n)
    return konf.procent(n / (_100 + n) * _100)


def narzut_z_marzy(marza_proc, konf=DOMYSLNA):
    m = do_decimal(marza_proc, "marza_proc")
    if m >= _100:
        raise BladWalidacji(MARZA_POZA_ZAKRESEM, "marza_proc", "marża musi być < 100%%: %s" % m)
    return konf.procent(m / (_100 - m) * _100)


def cena_sprzedazy(zakup, narzut_proc=None, marza_proc=None, konf=DOMYSLNA, dopusc_ujemne=False, pole="pozycja"):
    """Jednostkowa cena sprzedaży pozycji oferty/zamówienia z ceny zakupu i narzutu albo marży.

    cena = zakup * (1 + narzut/100)    albo    zakup / (1 - marża/100),
    zaokrąglona do grosza według konfiguracji (konf.kwota; w oblicz() to JEDNO zaokrąglenie ceny
    sprzedaży, przed rabatem). Podaj dokładnie jedno z: narzut_proc, marza_proc.
    `pole` to przedrostek nazwy pola w komunikatach błędów (np. "pozycje[3]").
    """
    if narzut_proc is not None and marza_proc is not None:
        raise BladWalidacji(NARZUT_I_MARZA, pole + ".narzut_proc", "podaj narzut albo marżę, nie oba")
    z = do_decimal(zakup, pole + ".cena_zakupu_jedn")
    if z < 0 and not dopusc_ujemne:
        raise BladWalidacji(NIEPOPRAWNA_LICZBA, pole + ".cena_zakupu_jedn", "cena zakupu nie może być ujemna: %s" % z)
    with localcontext(KONTEKST):
        if narzut_proc is not None:
            n = do_decimal(narzut_proc, pole + ".narzut_proc")
            if n < -_100:
                raise BladWalidacji(MARZA_POZA_ZAKRESEM, pole + ".narzut_proc", "narzut < -100%% daje cenę ujemną: %s" % n)
            return konf.kwota(z * (1 + n / _100))
        m = do_decimal(marza_proc, pole + ".marza_proc")
        if m >= _100:
            raise BladWalidacji(MARZA_POZA_ZAKRESEM, pole + ".marza_proc", "marża musi być < 100%%: %s" % m)
        return konf.kwota(z / (1 - m / _100))
