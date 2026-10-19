"""Pozycje nadrzędne/podrzędne (zestawy): pozycja nadrzędna liczy się z sumy dzieci.

Pozycja z `parent_id` wskazującym `id` innej pozycji jest jej dzieckiem. Pozycja, która ma dzieci,
jest wierszem zbiorczym (zestawem): jej kwoty to suma kwot liści pod nią i NIE wchodzą do sum
dokumentu ani do podsumowania stawek (inaczej zestaw byłby liczony podwójnie). Zagnieżdżenie
dowolnej głębokości jest dozwolone.
"""
from .bledy import NIEPOPRAWNA_HIERARCHIA, NIEPOPRAWNA_STRUKTURA, BladWalidacji


def zbuduj_hierarchie(pary, pole="pozycje"):
    """pary: lista (id, parent_id) w kolejności pozycji. Zwraca {indeks_rodzica: [indeksy dzieci]}.

    Błędy (NIEPOPRAWNA_HIERARCHIA): nieznany parent_id, parent_id równy własnemu id, cykl,
    niejednoznaczny rodzic (ten sam id u kilku pozycji, a któraś się do niego odwołuje).
    """
    po_id = {}
    for i, (id_, _) in enumerate(pary):
        if id_ is None:
            continue
        try:
            po_id.setdefault(id_, []).append(i)
        except TypeError:
            raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "%s[%d].id" % (pole, i), "id pozycji musi być wartością skalarną") from None
    rodzic = {}
    for i, (_, parent_id) in enumerate(pary):
        if parent_id is None:
            continue
        miejsce = "%s[%d].parent_id" % (pole, i)
        try:
            kandydaci = po_id.get(parent_id)
        except TypeError:
            raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, miejsce, "parent_id musi być wartością skalarną") from None
        if not kandydaci:
            raise BladWalidacji(NIEPOPRAWNA_HIERARCHIA, miejsce, "nie ma pozycji o id %r" % (parent_id,))
        if len(kandydaci) > 1:
            raise BladWalidacji(NIEPOPRAWNA_HIERARCHIA, miejsce, "id %r występuje u kilku pozycji" % (parent_id,))
        if kandydaci[0] == i:
            raise BladWalidacji(NIEPOPRAWNA_HIERARCHIA, miejsce, "pozycja nie może być własnym rodzicem")
        rodzic[i] = kandydaci[0]
    for start in rodzic:
        widziane, i = {start}, start
        while i in rodzic:
            i = rodzic[i]
            if i in widziane:
                raise BladWalidacji(NIEPOPRAWNA_HIERARCHIA, "%s[%d].parent_id" % (pole, start), "cykl w hierarchii pozycji")
            widziane.add(i)
    dzieci = {}
    for i, r in rodzic.items():
        dzieci.setdefault(r, []).append(i)
    return dzieci


def liscie_pod(i, dzieci):
    """Indeksy liści (pozycji bez dzieci) pod pozycją i, w kolejności pozycji."""
    wynik, stos = [], [i]
    while stos:
        j = stos.pop()
        if j in dzieci:
            stos.extend(dzieci[j])
        else:
            wynik.append(j)
    return sorted(wynik)
