"""Adapter: dowolny schemat (nazwy kolumn/pól) -> słownik dokumentu rozumiany przez bibliotekę.

Słownik kanoniczny (wejście dla sprawdz_spojnosc / porownaj / oblicz):
  id, waluta, tryb, rabat_dokumentu_proc, suma_netto, suma_vat, suma_brutto,
  pozycje[{ilosc, cena_netto_jedn, cena_brutto_jedn, rabat_proc, stawka_vat, netto, vat, brutto}],
  podsumowanie[{stawka_vat, netto, vat, brutto}]
Pola opcjonalne są pomijane, gdy ich nie znaleziono.

Mapowanie (słownik, zwykle z pliku JSON) wskazuje, pod jakimi nazwami szukać każdego pola
kanonicznego: nazwa albo lista nazw alternatywnych; ścieżka z kropką ("naglowek.netto") schodzi
w zagnieżdżone słowniki. Nazwy z mapowania są sprawdzane PRZED domyślnymi; pierwsza znaleziona
wartość różna od None wygrywa. Przykład:

  {"suma_netto": "kwota_netto", "suma_vat": ["kwota_vat", "podatek"],
   "pozycja": {"ilosc": "liczba_sztuk", "stawka_vat": "stawka"}}
"""
import json
from collections.abc import Mapping
from decimal import Decimal

from .bledy import BRAK_POLA, NIEPOPRAWNA_STRUKTURA, BladWalidacji

MAPOWANIE_DOMYSLNE = {
    "id": ["id", "numer", "nr", "numer_dokumentu"],
    "pozycje": ["pozycje", "linie", "items"],
    "suma_netto": ["suma_netto", "netto", "wartosc_netto"],
    "suma_vat": ["suma_vat", "kwota_vat", "vat", "wartosc_vat"],
    "suma_brutto": ["suma_brutto", "brutto", "wartosc_brutto"],
    "waluta": ["waluta", "currency"],
    "tryb": ["tryb"],
    "rabat_dokumentu_proc": ["rabat_dokumentu_proc", "rabat_dokumentu"],
    "podsumowanie": ["podsumowanie", "vat_wg_stawek"],
    "pozycja": {
        "ilosc": ["ilosc", "qty", "liczba_sztuk"],
        "cena_netto_jedn": ["cena_netto_jedn", "cena_netto"],
        "cena_brutto_jedn": ["cena_brutto_jedn", "cena_brutto"],
        "rabat_proc": ["rabat_proc", "rabat"],
        "stawka_vat": ["stawka_vat", "stawka"],
        "netto": ["netto", "wartosc_netto"],
        "vat": ["vat", "kwota_vat", "wartosc_vat"],
        "brutto": ["brutto", "wartosc_brutto"],
    },
    "podsumowanie_wiersz": {
        "stawka_vat": ["stawka_vat", "stawka"],
        "netto": ["netto", "wartosc_netto"],
        "vat": ["vat", "kwota_vat", "wartosc_vat"],
        "brutto": ["brutto", "wartosc_brutto"],
    },
}
_POLA_DOKUMENTU = ("id", "pozycje", "suma_netto", "suma_vat", "suma_brutto", "waluta", "tryb",
                   "rabat_dokumentu_proc", "podsumowanie")
_PODSLOWNIKI = ("pozycja", "podsumowanie_wiersz")
_BRAK = object()


def _nazwy(wartosc, pole):
    if isinstance(wartosc, str):
        return [wartosc]
    if isinstance(wartosc, (list, tuple)) and all(isinstance(x, str) for x in wartosc):
        return list(wartosc)
    raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "mapowanie." + pole,
                        "oczekiwano nazwy pola albo listy nazw, jest %r" % (wartosc,))


def scal_mapowanie(mapowanie=None):
    """Domyślne mapowanie + nazwy użytkownika (te mają pierwszeństwo). Nieznane klucze = błąd."""
    wynik = {k: (dict((kk, list(vv)) for kk, vv in v.items()) if isinstance(v, dict) else list(v))
             for k, v in MAPOWANIE_DOMYSLNE.items()}
    if mapowanie is None:
        return wynik
    if not isinstance(mapowanie, Mapping):
        raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "mapowanie", "mapowanie musi być słownikiem")
    for klucz, wartosc in mapowanie.items():
        if klucz in _PODSLOWNIKI:
            if not isinstance(wartosc, Mapping):
                raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "mapowanie." + klucz, "oczekiwano słownika")
            for pole, nazwy in wartosc.items():
                if pole not in wynik[klucz]:
                    raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "mapowanie.%s.%s" % (klucz, pole),
                                        "nieznane pole (dozwolone: %s)" % ", ".join(wynik[klucz]))
                wynik[klucz][pole] = _nazwy(nazwy, "%s.%s" % (klucz, pole)) + wynik[klucz][pole]
        elif klucz in _POLA_DOKUMENTU:
            wynik[klucz] = _nazwy(wartosc, klucz) + wynik[klucz]
        else:
            raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "mapowanie." + str(klucz),
                                "nieznany klucz (dozwolone: %s)" % ", ".join(_POLA_DOKUMENTU + _PODSLOWNIKI))
    return wynik


def _pobierz(wiersz, nazwy):
    for nazwa in nazwy:
        obiekt = wiersz
        for czesc in nazwa.split("."):
            if isinstance(obiekt, Mapping) and czesc in obiekt:
                obiekt = obiekt[czesc]
            else:
                obiekt = _BRAK
                break
        if obiekt is not _BRAK and obiekt is not None:
            return obiekt
    return _BRAK


def _przepisz(wiersz, mapowanie_pol):
    wynik = {}
    for pole, nazwy in mapowanie_pol.items():
        wartosc = _pobierz(wiersz, nazwy)
        if wartosc is not _BRAK:
            wynik[pole] = wartosc
    return wynik


def _lista_wierszy(wartosc, pole):
    if not isinstance(wartosc, (list, tuple)) or not all(isinstance(x, Mapping) for x in wartosc):
        raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, pole, "oczekiwano listy słowników")
    return wartosc


def z_wiersza(wiersz, mapowanie=None, pozycje=None, podsumowanie=None):
    """Buduje słownik kanoniczny z wiersza dokumentu o dowolnych nazwach pól.

    `pozycje` (i opcjonalnie `podsumowanie`): listy wierszy pobrane osobno (typowo z drugiej
    tabeli); gdy nie podane, szukane w wierszu pod mapowaną nazwą ('pozycje'). Błąd
    BRAK_POLA, gdy brakuje pozycji lub którejś z sum; NIEPOPRAWNA_STRUKTURA przy złym typie.
    """
    if not isinstance(wiersz, Mapping):
        raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "dokument", "dokument musi być słownikiem (obiektem JSON)")
    m = scal_mapowanie(mapowanie)
    wynik = {pole: w for pole in ("id", "waluta", "tryb", "rabat_dokumentu_proc")
             if (w := _pobierz(wiersz, m[pole])) is not _BRAK}
    for pole in ("suma_netto", "suma_vat", "suma_brutto"):
        w = _pobierz(wiersz, m[pole])
        if w is _BRAK:
            raise BladWalidacji(BRAK_POLA, pole, "nie znaleziono pola (szukano: %s)" % ", ".join(m[pole]))
        wynik[pole] = w
    if pozycje is None:
        pozycje = _pobierz(wiersz, m["pozycje"])
        if pozycje is _BRAK:
            raise BladWalidacji(BRAK_POLA, "pozycje", "nie znaleziono pozycji (szukano: %s)" % ", ".join(m["pozycje"]))
    wynik["pozycje"] = [_przepisz(p, m["pozycja"]) for p in _lista_wierszy(pozycje, "pozycje")]
    if podsumowanie is None:
        podsumowanie = _pobierz(wiersz, m["podsumowanie"])
    if podsumowanie is not _BRAK:
        wynik["podsumowanie"] = [_przepisz(p, m["podsumowanie_wiersz"])
                                 for p in _lista_wierszy(podsumowanie, "podsumowanie")]
    return wynik


def _odrzuc_stala(nazwa):
    raise ValueError("niedozwolona stała JSON: %s" % nazwa)


def wczytaj_json(tekst):
    """json.loads, w którym liczby ułamkowe są Decimal (bez utraty precyzji), a NaN/Infinity błędem."""
    return json.loads(tekst, parse_float=Decimal, parse_constant=_odrzuc_stala)


def wczytaj_plik_json(sciezka):
    """Czyta plik JSON w UTF-8 (z BOM lub bez), liczby ułamkowe jako Decimal."""
    with open(sciezka, encoding="utf-8-sig") as f:
        return wczytaj_json(f.read())
