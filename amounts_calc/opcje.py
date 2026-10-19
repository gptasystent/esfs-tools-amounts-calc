"""Opcje i alternatywy w trybie jawnym: pozycje najwyższego poziomu z `tryb_opcji` ("opcja" | "alternatywa").

Tryb "opcja": pozycja dodatkowa, nie wchodzi do sumy dokumentu, chyba że ma wybrana=true.
Tryb "alternatywa": pozycje wzajemnie się wykluczają w obrębie `grupa_opcji`; do sumy wchodzi dokładnie
jedna, ta z wybrana=true. Tryb "brak" (domyślny) to zwykła pozycja. Zestaw z ilością i dziećmi może być opcją
albo alternatywą - wnosi wtedy N x dzieci (patrz zestawy.py), jak każda inna pozycja.

Czyste funkcje na wierszach (słownikach) z zestawy.wiersze_z_pozycji: wymagają kluczy tryb_opcji, wybrana,
alternatywa (grupa). Nic tu nie dobiera kombinacji do nagłówka - to robi tylko tryb awaryjny (zestawy.py).
"""
from decimal import Decimal, localcontext
from itertools import combinations

from .bledy import ALTERNATYWA_BEZ_WYBORU, ALTERNATYWA_WIELE_WYBRANYCH, OPCJA_W_SUMIE
from .config import KONTEKST
from .klasyfikacja import PROG
from .zestawy import POLA, rodzice, sumy_pozycji, wklad

PROGLICZNY = Decimal("0.25")    # reszta dopasowania "najblizsze" względem kwot dodanych opcji
MAKS_PODZBIOROW_OPCJI = 10   # tyle niewybranych opcji sprawdzamy we wszystkich podzbiorach (reszta: tylko "wszystkie")


def _zero():
    return {f: Decimal(0) for f in POLA}


def _kwoty(i, wiersze, dzieci, rozw):
    """Kwoty, jakie pozycja wnosi do sumy (zestaw: N x dzieci); brakująca kwota (None) liczy się jako 0."""
    w = wklad(i, wiersze, dzieci, rozw)
    return {f: (w[f] if w[f] is not None else Decimal(0)) for f in POLA}


def _ujemna(kwoty):
    return {f: -v for f, v in kwoty.items()}


def _suma(kwoty):
    wynik = _zero()
    for k in kwoty:
        for f in POLA:
            wynik[f] += k[f]
    return wynik


def _opisz(i, wiersze, dzieci, rozw, wlaczone):
    return dict({"indeks": i, "id": wiersze[i].get("id"), "wybrana": i in wlaczone, "zestaw": i in dzieci},
                **_kwoty(i, wiersze, dzieci, rozw))


def pozycje_opcji(wiersze, rodzic):
    """(opcje, grupy): indeksy pozycji najwyższego poziomu w trybie "opcja" oraz {grupa: [indeksy]} alternatyw (tryb jawny albo awaryjny)."""
    opcje, grupy = [], {}
    for i, w in enumerate(wiersze):
        if i in rodzic:
            continue
        if w.get("tryb_opcji") == "opcja":
            opcje.append(i)
        elif w.get("tryb_opcji") == "alternatywa" or (w.get("tryb_opcji") is None and w.get("alternatywa") is not None):
            grupy.setdefault(w["alternatywa"], []).append(i)       # bez tryb_opcji: tryb awaryjny (alternatywa / grupa_opcji)
    return opcje, dict(sorted(grupy.items(), key=lambda kv: repr(kv[0])))


def _suma_n(kwoty):
    """Suma kwot; pole bez wartości (None) w którejkolwiek pozycji daje None."""
    wynik = {f: Decimal(0) for f in POLA}
    for k in kwoty:
        for f in POLA:
            wynik[f] = None if wynik[f] is None or k[f] is None else wynik[f] + k[f]
    return wynik


def poza_suma(wiersze, dzieci, rozw, wlaczone):
    """Pozycje opcjonalne niewliczone do sumy dokumentu - do pokazania pod sumą (np. w PDF) i w raporcie CLI.

    {"netto", "vat", "brutto", "pozycje": [{indeks, id, netto, vat, brutto}],
     "alternatywy_niewybrane": [{indeks, id, grupa, netto, vat, brutto}]}.
    Kwoty główne to suma niewybranych opcji (tryb "opcja"); zera i pusta lista, gdy takich opcji nie ma (pole bez
    wartości w pozycjach, np. VAT w dokumencie bez VAT, to None). Niewybrane alternatywy wykluczają się z wybraną,
    więc nie są dodawane do sumy, tylko wymienione osobno (również w dokumentach trybu awaryjnego, gdzie
    alternatywą jest pozycja z `alternatywa` / `grupa_opcji` spoza wybranej kombinacji)."""
    opcje, grupy = pozycje_opcji(wiersze, rodzice(dzieci))
    with localcontext(KONTEKST):
        def surowe(i):
            return wklad(i, wiersze, dzieci, rozw)

        pozycje = [dict({"indeks": i, "id": wiersze[i].get("id")}, **surowe(i)) for i in opcje if i not in wlaczone]
        alternatywy = [dict({"indeks": i, "id": wiersze[i].get("id"), "grupa": g}, **surowe(i))
                       for g, idx in grupy.items() for i in idx if i not in wlaczone]
        return dict(_suma_n(pozycje), pozycje=pozycje, alternatywy_niewybrane=alternatywy)


def _pasuje(naglowek, suma, pola):
    """Nagłówek zgadza się z sumą na wszystkich porównywalnych polach (tolerancja grosza jak w klasyfikacji)."""
    return bool(pola) and all(abs(naglowek[f] - suma[f]) <= PROG for f in pola)


def _roznice(naglowek, suma, pola):
    return {f: (naglowek[f] - suma[f] if f in pola else None) for f in POLA}


def _najwieksza(roznice):
    wartosci = [r for r in roznice.values() if r is not None]
    return max(wartosci, key=abs) if wartosci else None


def _przyczyna(kod, opis, naglowek, wliczona, pola, **reszta):
    roznice = _roznice(naglowek, wliczona, pola)
    return dict({"kod": kod, "pole": "netto", "roznica": _najwieksza(roznice), "opis": opis,
                 "roznica_wzgledem_naglowka": roznice, "suma_wliczona": dict(wliczona)}, **reszta)


def _odleglosc(naglowek, suma, pola):
    return sum((abs(naglowek[f] - suma[f]) for f in pola), Decimal(0))


def _opcje_w_sumie(wiersze, dzieci, rozw, naglowek, wliczona, pola, niewybrane, wlaczone):
    """OPCJA_W_SUMIE: najbardziej prawdopodobny podzbiór niewybranych opcji, który nagłówek ma w sumie.

    Dobór po kwotach ZAPISANYCH w pozycjach (netto/vat/brutto pozycji), nie po cenie x narzut: wybierany jest podzbiór,
    z którym suma jest najbliżej nagłówka (przy remisie mniejszy). `dopasowanie`: "zgodne" - różnica w granicach grosza;
    "najblizsze" - nagłówek różni się od tej sumy (np. o błąd narzutu, ILOSC_X_CENA_NARZUT), ale jest nią wyraźnie
    bliżej niż samą sumą wliczoną: reszta nie przekracza 25% kwot dodanych opcji. `reszta` = nagłówek - (suma
    wliczona + wybrane opcje)."""
    kandydaci = ([c for r in range(1, len(niewybrane) + 1) for c in combinations(niewybrane, r)]
                 if len(niewybrane) <= MAKS_PODZBIOROW_OPCJI else [tuple(niewybrane)])
    wklady = {i: _kwoty(i, wiersze, dzieci, rozw) for i in niewybrane}
    punktacja = []
    for c in kandydaci:
        razem = _suma([wliczona] + [wklady[i] for i in c])
        punktacja.append((_odleglosc(naglowek, razem, pola), len(c), c, razem))
    odleglosc, _, c, razem = min(punktacja, key=lambda x: (x[0], x[1]))
    dodane = _suma(wklady[i] for i in c)
    zgodne = _pasuje(naglowek, razem, pola)
    if not zgodne and not (odleglosc < _odleglosc(naglowek, wliczona, pola)
                           and odleglosc <= PROGLICZNY * sum((abs(dodane[f]) for f in pola), Decimal(0))):
        return []
    pozycje = [_opisz(i, wiersze, dzieci, rozw, wlaczone) for i in c]
    przyczyna = _przyczyna(
        OPCJA_W_SUMIE, "suma dokumentu zawiera opcje, które nie są wybrane (wybrana != true)",
        naglowek, wliczona, pola, liczba=len(pozycje), pozycje=pozycje, kwoty_pozycji=dodane,
        dopasowanie="zgodne" if zgodne else "najblizsze", reszta=_roznice(naglowek, razem, pola))
    return [przyczyna]


def przyczyny_opcji(wiersze, dzieci, rozw, naglowek, wlaczone):
    """Przyczyny OPCJA_W_SUMIE, ALTERNATYWA_BEZ_WYBORU i ALTERNATYWA_WIELE_WYBRANYCH dla dokumentu w trybie jawnym.

    naglowek: {pole: Decimal|None}; wlaczone: indeksy wybranych opcji i alternatyw. Porównywane są tylko pola, które
    mają wartość w nagłówku i we wszystkich pozycjach (dokument bez VAT w pozycjach: tylko netto i brutto). Wszystkie trzy są niespójnościami
    (nie informacją): pierwsze to zapisana suma obejmująca niewybrane opcje, kolejne - naruszenie zasady "do sumy
    wchodzi dokładnie jedna alternatywa z grupy". Każda niesie `roznica_wzgledem_naglowka` (nagłówek - suma
    wliczona) oraz kwoty listowanych pozycji."""
    opcje, grupy = pozycje_opcji(wiersze, rodzice(dzieci))
    wynik = []
    with localcontext(KONTEKST):
        wliczona = sumy_pozycji(wiersze, dzieci, rozw, wlaczone)
        wliczona = {f: (wliczona[f] if wliczona[f] is not None else Decimal(0)) for f in POLA}
        wszystkie = sumy_pozycji(wiersze, dzieci, rozw, frozenset(wlaczone) | set(opcje) | {i for g in grupy.values() for i in g})
        pola = [f for f in POLA if naglowek.get(f) is not None and wszystkie[f] is not None]
        zgodny = _pasuje(naglowek, wliczona, pola)

        niewybrane = [i for i in opcje if i not in wlaczone]
        if niewybrane and not zgodny and pola:
            wynik += _opcje_w_sumie(wiersze, dzieci, rozw, naglowek, wliczona, pola, niewybrane, wlaczone)

        bez, wiele = [], []
        for g, idx in grupy.items():
            wybrane = [i for i in idx if i in wlaczone]
            if not wybrane:
                bez.append((g, idx, [i for i in idx if _pasuje(naglowek, _suma([wliczona, _kwoty(i, wiersze, dzieci, rozw)]), pola)]))
            elif len(wybrane) > 1:
                bez_jednej = [i for i in wybrane
                              if _pasuje(naglowek, _suma([wliczona] + [_ujemna(_kwoty(j, wiersze, dzieci, rozw))
                                                                       for j in wybrane if j != i]), pola)]
                wiele.append((g, idx, bez_jednej))
        if bez:
            wynik.append(_przyczyna(
                ALTERNATYWA_BEZ_WYBORU, "w grupie alternatyw nie wybrano żadnej pozycji (wybrana=true)",
                naglowek, wliczona, pola, liczba=len(bez),
                grupy=[{"grupa": g, "pozycje": [_opisz(i, wiersze, dzieci, rozw, wlaczone) for i in idx],
                        "naglowek_pasuje_do": pasuje} for g, idx, pasuje in bez]))
        if wiele:
            wynik.append(_przyczyna(
                ALTERNATYWA_WIELE_WYBRANYCH, "w grupie alternatyw wybrano więcej niż jedną pozycję",
                naglowek, wliczona, pola, liczba=len(wiele), naglowek_zawiera_wszystkie_wybrane=zgodny,
                grupy=[{"grupa": g, "pozycje": [_opisz(i, wiersze, dzieci, rozw, wlaczone) for i in idx],
                        "wybranych": sum(1 for i in idx if i in wlaczone), "naglowek_pasuje_do_jednej": pasuje}
                       for g, idx, pasuje in wiele]))
    return wynik
