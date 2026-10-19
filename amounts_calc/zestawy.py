"""Zestawy z ilością i alternatywy: czyste obliczenia na wierszach (słownikach), bez zależności od modelu.

MODEL ZESTAWU. Pozycja nadrzędna (zestaw) ma ilość N, a jej dzieci opisują JEDNĄ sztukę zestawu
(ilości i ceny dzieci są na 1 szt.). Wartość zestawu = N x suma dzieci (netto, vat i brutto osobno,
z zaokrągleniem według Konfiguracja.kwota; dla N = 1 bez zaokrąglania - jak dawniej). Dziecko może
samo być podzestawem z własną ilością, która mnoży jego dzieci: ilość liścia w sumie dokumentu to
iloczyn ilości wszystkich jego przodków (`mnozniki`). Do sum dokumentu wchodzą wiersze najwyższego
poziomu: zwykłe pozycje i zestawy (oczekiwana wartość N x dzieci), a dzieci NIE są liczone drugi raz.
Głębokość zagnieżdżenia ogranicza hierarchia.MAKS_GLEBOKOSC. `uwzglednij_ilosc=False` daje stare
zachowanie: ilość zestawu jest ignorowana (traktowana jak 1).

ALTERNATYWY. Wiersz najwyższego poziomu z `alternatywa` (nazwa grupy; domyślna grupa to "") jest opcją
wzajemnie wykluczającą się z innymi opcjami tej grupy: do sumy wchodzi co najwyżej jedna z grupy.
`wybierz_alternatywy` dobiera kombinację (po jednej lub żadnej z każdej grupy) najlepiej zgodną z sumami
nagłówka.

Wiersz to słownik: indeks, ilosc, netto, vat, brutto (Decimal albo None), stawka (etykieta), zestaw (bool),
alternatywa (None albo nazwa grupy).
"""
from decimal import Decimal, localcontext
from itertools import product

from .config import DOMYSLNA, KONTEKST
from .hierarchia import liscie_pod
from .stawki import KOLEJNOSC_STAWEK

POLA = ("netto", "vat", "brutto")
MAKS_KOMBINACJI_ALTERNATYW = 4096
_1 = Decimal(1)


def wiersze_z_pozycji(pozycje):
    """PozycjaWynik -> wiersze (słowniki) dla funkcji z tego modułu."""
    return [{"indeks": p.indeks, "id": p.id, "ilosc": p.ilosc, "netto": p.netto, "vat": p.vat, "brutto": p.brutto,
             "stawka": p.stawka_vat, "zestaw": p.zestaw, "alternatywa": getattr(p, "alternatywa", None),
             "tryb_opcji": getattr(p, "tryb_opcji", None), "wybrana": getattr(p, "wybrana", None)}
            for p in pozycje]


def rodzice(dzieci):
    return {c: p for p, cs in dzieci.items() for c in cs}


def ilosc_wiersza(wiersz, uwzglednij_ilosc):
    if not uwzglednij_ilosc:
        return _1
    n = wiersz.get("ilosc")
    return _1 if n is None else n


def rozwin(wiersze, dzieci, uwzglednij_ilosc=True, konf=DOMYSLNA, pola=POLA):
    """Oczekiwane wartości zestawów (rekurencyjnie, od liści) i mnożniki liści.

    Zwraca słownik:
      oczekiwane  {indeks zestawu: {pole: N x suma dzieci}}  (None, gdy brakuje kwoty któregoś dziecka)
      sumy_dzieci {indeks zestawu: {pole: suma dzieci}}      (1 szt. zestawu, bez mnożenia przez N)
      mnozniki    {indeks liścia: iloczyn ilości jego przodków}
      rodzic      {indeks: indeks rodzica}
    Wartość zagnieżdżonego podzestawu to jego OCZEKIWANA wartość, więc błąd podzestawu nie przenosi się
    na zestaw nadrzędny."""
    rodzic = rodzice(dzieci)
    oczekiwane, sumy_dzieci = {}, {}
    with localcontext(KONTEKST):
        def wartosc(j):
            return zestaw(j) if j in dzieci else {f: wiersze[j].get(f) for f in pola}

        def zestaw(i):
            if i in oczekiwane:
                return oczekiwane[i]
            skladniki = [wartosc(c) for c in dzieci[i]]
            suma = {f: (None if any(s[f] is None for s in skladniki) else sum((s[f] for s in skladniki), Decimal(0)))
                    for f in pola}
            n = ilosc_wiersza(wiersze[i], uwzglednij_ilosc)
            sumy_dzieci[i] = suma
            oczekiwane[i] = {f: (None if suma[f] is None else suma[f] if n == 1 else konf.kwota(suma[f] * n))
                             for f in pola}
            return oczekiwane[i]

        for i in sorted(dzieci):
            zestaw(i)
        mnozniki = {}
        for l in range(len(wiersze)):
            if l in dzieci:
                continue
            m, a = _1, rodzic.get(l)
            while a is not None:
                m *= ilosc_wiersza(wiersze[a], uwzglednij_ilosc)
                a = rodzic.get(a)
            mnozniki[l] = m
    return {"oczekiwane": oczekiwane, "sumy_dzieci": sumy_dzieci, "mnozniki": mnozniki, "rodzic": rodzic}


def pasuje_do_jednej_sztuki(wiersz, suma_dzieci, pola=POLA):
    """Zapisane kwoty zestawu równają się sumie dzieci (1 x), czyli ilość zestawu została pominięta."""
    porownywane = [f for f in pola if wiersz.get(f) is not None and suma_dzieci.get(f) is not None]
    return bool(porownywane) and all(wiersz[f] == suma_dzieci[f] for f in porownywane)


def wiersze_najwyzszego_poziomu(wiersze, rodzic, wlaczone=frozenset()):
    """Indeksy wierszy najwyższego poziomu, które wchodzą do sum: wszystkie poza opcjami, których nie wybrano."""
    return [i for i, w in enumerate(wiersze)
            if i not in rodzic and (w.get("alternatywa") is None or i in wlaczone)]


def wklad(i, wiersze, dzieci, rozw, pola=POLA):
    """Kwoty, jakie wiersz najwyższego poziomu wnosi do sumy: zwykła pozycja - swoje, zestaw - N x dzieci."""
    return rozw["oczekiwane"][i] if i in dzieci else {f: wiersze[i].get(f) for f in pola}


def sumy_pozycji(wiersze, dzieci, rozw, wlaczone=frozenset(), pola=POLA):
    """Suma pozycji dokumentu {pole: Decimal|None} (None, gdy w którymś wierszu brakuje kwoty)."""
    sumy = {f: Decimal(0) for f in pola}
    with localcontext(KONTEKST):
        for i in wiersze_najwyzszego_poziomu(wiersze, rozw["rodzic"], wlaczone):
            w = wklad(i, wiersze, dzieci, rozw, pola)
            for f in pola:
                sumy[f] = None if sumy[f] is None or w[f] is None else sumy[f] + w[f]
    return sumy


def podsumowanie_stawek(wiersze, dzieci, rozw, wlaczone=frozenset(), konf=DOMYSLNA, pola=POLA):
    """Kwoty dokumentu rozbite na stawki VAT: {stawka: {pole: Decimal}} w stałej kolejności stawek.

    Zestaw o ilości różnej od 1 wnosi N x dzieci rozłożone na stawki jego liści (zaokrąglone do grosza,
    różnica względem oczekiwanej wartości zestawu trafia do największej stawki), więc suma stawek zawsze
    równa się sumie pozycji. Zestawy z samymi mnożnikami 1 wnoszą po prostu kwoty swoich liści (bez
    zaokrągleń). Brakujące kwoty (None) liczą się jako 0."""
    suma = {}

    def dodaj(stawka, pole, v):
        suma.setdefault(stawka, {p: Decimal(0) for p in pola})[pole] += v

    with localcontext(KONTEKST):
        for i in wiersze_najwyzszego_poziomu(wiersze, rozw["rodzic"], wlaczone):
            if i not in dzieci:
                for f in pola:
                    dodaj(wiersze[i]["stawka"], f, wiersze[i].get(f) or Decimal(0))
                continue
            liscie = liscie_pod(i, dzieci)
            if all(rozw["mnozniki"][l] == 1 for l in liscie):
                for l in liscie:
                    for f in pola:
                        dodaj(wiersze[l]["stawka"], f, wiersze[l].get(f) or Decimal(0))
                continue
            for f in pola:
                dokladne = {}
                for l in liscie:
                    dokladne[wiersze[l]["stawka"]] = (dokladne.get(wiersze[l]["stawka"], Decimal(0))
                                                      + (wiersze[l].get(f) or Decimal(0)) * rozw["mnozniki"][l])
                kolejnosc = sorted(dokladne, key=lambda s: KOLEJNOSC_STAWEK.index(s))
                zaokraglone = {s: konf.kwota(dokladne[s]) for s in kolejnosc}
                cel = rozw["oczekiwane"][i][f]
                if cel is not None and zaokraglone:
                    roznica = cel - sum(zaokraglone.values())
                    if roznica != 0:
                        najw = max(kolejnosc, key=lambda s: abs(zaokraglone[s]))
                        zaokraglone[najw] += roznica
                for s in kolejnosc:
                    dodaj(s, f, zaokraglone[s])
    return {s: suma[s] for s in KOLEJNOSC_STAWEK if s in suma}


def grupy_alternatyw(wiersze, rodzic):
    """{grupa: [indeksy opcji]} dla wierszy najwyższego poziomu z `alternatywa`, grupy w stałej kolejności."""
    grupy = {}
    for i, w in enumerate(wiersze):
        if i not in rodzic and w.get("alternatywa") is not None:
            grupy.setdefault(w["alternatywa"], []).append(i)
    return dict(sorted(grupy.items(), key=lambda kv: repr(kv[0])))


def wybierz_alternatywy(wiersze, dzieci, rozw, naglowek, pola=POLA):
    """Która kombinacja opcji (co najwyżej jedna z każdej grupy) odpowiada sumom nagłówka.

    naglowek: {pole: Decimal}. Zwraca (frozenset indeksów włączonych opcji, "brak" | "zgodne" | "najblizsze"):
    "zgodne" - baza + wybrane opcje równa się nagłówkowi na wszystkich polach; "najblizsze" - żadna kombinacja
    nie pasuje, zwrócona jest ta o najmniejszej sumie różnic (remis: wcześniejsza, a pusta jest pierwsza)."""
    grupy = grupy_alternatyw(wiersze, rozw["rodzic"])
    if not grupy:
        return frozenset(), "brak"
    with localcontext(KONTEKST):
        baza = sumy_pozycji(wiersze, dzieci, rozw, frozenset(), pola)
        wklady = {i: wklad(i, wiersze, dzieci, rozw, pola) for idx in grupy.values() for i in idx}

        def ocena(wybrane):
            roznice = []
            for f in pola:
                if naglowek.get(f) is None or baza[f] is None:
                    continue
                s = baza[f] + sum((wklady[i][f] or Decimal(0) for i in wybrane), Decimal(0))
                roznice.append(abs(naglowek[f] - s))
            return (0 if all(r == 0 for r in roznice) else 1, sum(roznice, Decimal(0)))

        opcje = [[None] + idx for idx in grupy.values()]
        liczba = 1
        for o in opcje:
            liczba *= len(o)
        if liczba <= MAKS_KOMBINACJI_ALTERNATYW:
            najlepsza, wynik = None, ()
            for kombinacja in product(*opcje):
                wybrane = tuple(i for i in kombinacja if i is not None)
                o = ocena(wybrane)
                if najlepsza is None or o < najlepsza:
                    najlepsza, wynik = o, wybrane
        else:   # zbyt wiele kombinacji: grupa po grupie
            wynik = ()
            for o in opcje:
                wybor = min(o, key=lambda i: ocena(wynik + ((i,) if i is not None else ())))
                if wybor is not None:
                    wynik += (wybor,)
            najlepsza = ocena(wynik)
    return frozenset(wynik), ("zgodne" if najlepsza[0] == 0 else "najblizsze")


def tolerancja_vat_stawek(wiersze, dzieci, rozw, wlaczone=frozenset()):
    """{stawka: tolerancja} dla sprawdzenia "VAT stawki == VAT z sumy stawki" w dokumentach z zestawami.

    VAT zestawu to N x VAT dzieci (dzieci są zaokrąglone na 1 szt.), więc błąd zaokrąglenia dziecka (do 0,005)
    rośnie N-krotnie: tolerancja stawki = 0,005 x suma mnożników jej liści o mnożniku różnym od 1. Stawki bez
    takich liści nie mają tolerancji (porównanie dokładne, jak dawniej)."""
    tol = {}
    for i in wiersze_najwyzszego_poziomu(wiersze, rozw["rodzic"], wlaczone):
        liscie = liscie_pod(i, dzieci) if i in dzieci else [i]
        for l in liscie:
            m = rozw["mnozniki"][l]
            if m != 1:
                tol[wiersze[l]["stawka"]] = tol.get(wiersze[l]["stawka"], Decimal(0)) + abs(m) * Decimal("0.005")
    return tol


def waga_liscia(l, wiersze, rozw, wlaczone=frozenset()):
    """Ile razy liść wchodzi do sum dokumentu: iloczyn ilości zestawów nad nim, 0 dla opcji spoza wyboru."""
    rodzic = rozw["rodzic"]
    gora = l
    while gora in rodzic:
        gora = rodzic[gora]
    if wiersze[gora].get("alternatywa") is not None and gora not in wlaczone:
        return Decimal(0)
    return rozw["mnozniki"][l]
