"""Podpowiedzi przyczyn niespójności: czy pasuje do "zestaw nie odświeżony" albo "brutto równe netto".

Każda niespójność z sprawdz_spojnosc dostaje pole `podpowiedz`:
  ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC  zestaw o ilości N != 1 ma kwoty równe 1 x suma dzieci: ilość pominięta
  ZESTAW_NIEODSWIEZONY  pozycja nadrzędna (zestaw) nie została przeliczona po zmianie dziecka: jej kwota różni się
                        od sumy dzieci (bez wyjaśnienia narzutem/rabatem zestawu), a do tego (dowody, wystarczy jeden)
                        - różnica równa się wartości dokładnie jednego dziecka (dziecko dodane/usunięte po przeliczeniu),
                        - nagłówek zgadza się z sumą dzieci, a zestaw nie (nagłówek odświeżony, zestaw nie),
                        - nagłówek zgadza się z zapisanymi kwotami zestawów (nieodświeżony razem z nimi);
                        dotyczy też niespójności sum dokumentu, jeśli nagłówek = suma liści + różnice zestawów
  BRUTTO_ROWNE_NETTO    kwota brutto równa netto mimo stawki VAT > 0 (brak VAT w brutto): dla pozycji, wiersza
                        stawki albo sum dokumentu, którego dotyczy niespójność
  POLGROSZ              drobiazg (patrz klasyfikacja.py)
  inna                  nic z powyższego
Funkcje czyste na Decimal; nie rzucają z powodu danych.
"""
from decimal import Decimal

from .bledy import (BRUTTO_ROWNE_NETTO, ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, ZESTAW_NIEODSWIEZONY,
                    ZESTAW_ROZNY_OD_DZIECI)
from .hierarchia import liscie_pod
from .klasyfikacja import MAX_POZYCJI_W_OPISIE, POLA, PROG
from .stawki import wartosc_stawki
from .zestawy import ilosc_wiersza, pasuje_do_jednej_sztuki, rozwin, sumy_pozycji

INNA = "inna"
PRIORYTET = (ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, ZESTAW_NIEODSWIEZONY, BRUTTO_ROWNE_NETTO, INNA)
_1 = Decimal(1)
_POL = Decimal("0.005")


def _stawka(wiersz_lub_etykieta):
    etykieta = wiersz_lub_etykieta.get("stawka") if isinstance(wiersz_lub_etykieta, dict) else wiersz_lub_etykieta
    return wartosc_stawki(etykieta) if etykieta in ("23", "8", "5", "0", "zw", "np") else None


def brutto_rowne_netto(netto, brutto, stawka):
    """Brutto = netto mimo stawki > 0 i kwoty, od której VAT zaokrągla się do co najmniej grosza."""
    r = _stawka(stawka)
    if netto is None or brutto is None or r is None or r <= 0:
        return False
    return abs(brutto - netto) <= _POL and abs(netto) * r / 100 > PROG


def _naglowek_brutto_rowne_netto(naglowek, wiersze):
    liscie = [w for w in wiersze if not w["zestaw"] and w["netto"] is not None and _stawka(w) is not None]
    vat_oczekiwany = sum((w["netto"] * _stawka(w) / 100 for w in liscie), Decimal(0))   # ze znakiem: suma zerowa => 0
    return abs(naglowek["brutto"] - naglowek["netto"]) <= _POL and abs(vat_oczekiwany) > PROG and abs(naglowek["netto"]) > PROG


def _mnoznik_wzgledny(l, i, rodzic, wiersze, uwzglednij):
    """Iloczyn ilości zestawów od rodzica liścia l w górę do zestawu i włącznie."""
    m, a = _1, rodzic[l]
    while True:
        m *= ilosc_wiersza(wiersze[a], uwzglednij)
        if a == i:
            return m
        a = rodzic[a]


def zestawy_z_dowodami(wiersze, dzieci, indeksy, naglowek, pozycje, rozw, uwzglednij_ilosc=True,
                       wlaczone=frozenset()):
    """Zestawy (indeksy z ZESTAW_ROZNY_OD_DZIECI) z dowodami, że ich kwoty są nieaktualne.

    Zwraca (nieodswiezone, bez_mnozenia, z_zapisanych):
      nieodswiezone  [{indeks, id, zapisane, oczekiwane, roznica, dowody}] - zestaw nie został przeliczony po zmianie
                     dziecka (dowody: różnica = wartość dokładnie jednego dziecka; nagłówek zgadza się z N x dzieci;
                     nagłówek zgadza się z zapisanymi kwotami zestawów)
      bez_mnozenia   [{..., ilosc}] - zapisane kwoty zestawu o ilości N != 1 równają się 1 x suma dzieci
      z_zapisanych   nagłówek = suma pozycji + różnice zestawów najwyższego poziomu (policzony z zapisanych zestawów)
    Oczekiwana wartość zestawu to N x suma dzieci (rozw["oczekiwane"])."""
    suma_poz = sumy_pozycji(wiersze, dzieci, rozw, wlaczone)
    rodzic = rozw["rodzic"]
    deltas = {i: {f: wiersze[i][f] - rozw["oczekiwane"][i][f] for f in POLA} for i in indeksy}
    bez_idx = {i for i in indeksy if ilosc_wiersza(wiersze[i], uwzglednij_ilosc) != 1
               and pasuje_do_jednej_sztuki(wiersze[i], rozw["sumy_dzieci"][i])}
    top = [i for i in indeksy if pozycje[i].get("parent_id") is None]
    delta_top = {k: sum((deltas[i][k] for i in top), Decimal(0)) for k in POLA}
    z_zapisanych = bool(top) and any(delta_top[k] != 0 for k in POLA) and all(
        suma_poz[k] is not None and abs(naglowek[k] - (suma_poz[k] + delta_top[k])) <= PROG for k in POLA)
    nieodswiezone, bez_mnozenia = [], []
    for i in sorted(indeksy):
        d = deltas[i]["netto"]
        if abs(d) <= PROG:      # grosz różnicy to zaokrąglenie, a nie zestaw sprzed zmiany dziecka
            continue
        opis = {"indeks": i, "id": wiersze[i]["id"], "zapisane": wiersze[i]["netto"],
                "oczekiwane": rozw["oczekiwane"][i]["netto"], "roznica": d}
        if i in bez_idx:
            bez_mnozenia.append(dict(opis, ilosc=ilosc_wiersza(wiersze[i], uwzglednij_ilosc),
                                     suma_dzieci=rozw["sumy_dzieci"][i]["netto"]))
            continue
        dowody = []
        liscie_i = liscie_pod(i, dzieci)
        rowne = [l for l in liscie_i
                 if abs(abs(wiersze[l]["netto"] * _mnoznik_wzgledny(l, i, rodzic, wiersze, uwzglednij_ilosc)) - abs(d)) <= PROG]
        if len(rowne) == 1 and d != 0:
            dowody.append({"dowod": "roznica_rowna_wartosci_dziecka", "dziecko": rowne[0], "id": wiersze[rowne[0]]["id"]})
        elif not rowne and d != 0:       # może to cały podzestaw (dziecko bezpośrednie będące zestawem)
            n_i = ilosc_wiersza(wiersze[i], uwzglednij_ilosc)
            podzestawy = [c for c in dzieci[i] if c in dzieci
                          and abs(abs(rozw["oczekiwane"][c]["netto"] * n_i) - abs(d)) <= PROG]
            if len(podzestawy) == 1:
                dowody.append({"dowod": "roznica_rowna_wartosci_dziecka", "dziecko": podzestawy[0],
                               "id": wiersze[podzestawy[0]]["id"]})
        if suma_poz["netto"] is not None and abs(naglowek["netto"] - suma_poz["netto"]) <= PROG:
            dowody.append({"dowod": "naglowek_zgodny_z_suma_dzieci"})
        if z_zapisanych:
            dowody.append({"dowod": "naglowek_zgodny_z_zapisanymi_zestawami"})
        if dowody:
            nieodswiezone.append(dict(opis, suma_dzieci=rozw["sumy_dzieci"][i]["netto"], dowody=dowody))
    return nieodswiezone, bez_mnozenia, z_zapisanych


def zestawy_nieodswiezone(wiersze, dzieci, indeksy, naglowek, pozycje):
    """Jak zestawy_z_dowodami, ale w dawnym modelu (ilość zestawu ignorowana); zwraca (nieodswiezone, z_zapisanych)."""
    rozw = rozwin(wiersze, dzieci, False)
    nieodswiezone, _, z_zapisanych = zestawy_z_dowodami(wiersze, dzieci, indeksy, naglowek, pozycje, rozw, False)
    return nieodswiezone, z_zapisanych


def oznacz_podpowiedzi(niespojnosci, zapisany, wiersze, dzieci, pozycje, naglowek, wlaczone=None):
    """Dopisuje `podpowiedz` do każdej niespójności (mutuje słowniki) i zwraca przyczyny:
    ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, ZESTAW_NIEODSWIEZONY i BRUTTO_ROWNE_NETTO (tylko gdy coś znaleziono).
    Wymaga kwot pozycji (wiersze)."""
    wiersz = {w["indeks"]: w for w in wiersze}
    wlaczone = frozenset(zapisany.wlaczone_alternatywy) if wlaczone is None else frozenset(wlaczone)
    uwzglednij = zapisany.ilosc_zestawu
    rozw = rozwin(wiersze, dzieci, uwzglednij)
    indeksy_zestawow = [int(n["zakres"].split(":")[1]) for n in niespojnosci
                        if n["kod"] == ZESTAW_ROZNY_OD_DZIECI and not n.get("drobiazg")]
    if indeksy_zestawow:
        nieodswiezone, bez_mnozenia, z_zapisanych = zestawy_z_dowodami(
            wiersze, dzieci, sorted(set(indeksy_zestawow)), naglowek, pozycje, rozw, uwzglednij, wlaczone)
    else:
        nieodswiezone, bez_mnozenia, z_zapisanych = [], [], False
    nieodswiezone_idx = {z["indeks"] for z in nieodswiezone}
    bez_idx = {z["indeks"] for z in bez_mnozenia}
    # naglowek policzony z zapisanych zestawów: jeśli wszystkie zestawy najwyższego poziomu z niespójnością
    # pomijają ilość - to brak mnożenia, w przeciwnym razie nieodświeżenie
    top = {i for i in indeksy_zestawow if pozycje[i].get("parent_id") is None}
    naglowek_bez_mnozenia = bool(top) and top <= bez_idx
    brutto_naglowek = _naglowek_brutto_rowne_netto(naglowek, wiersze)
    stawki = {s.stawka_vat: s for s in zapisany.podsumowanie}

    def podpowiedz(n):
        if n.get("drobiazg"):
            return "POLGROSZ"
        zakres, _, arg = n["zakres"].partition(":")
        if n["kod"] == ZESTAW_ROZNY_OD_DZIECI:
            i = int(arg)
            return (ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC if i in bez_idx
                    else ZESTAW_NIEODSWIEZONY if i in nieodswiezone_idx else INNA)
        if zakres == "pozycja":
            w = wiersz.get(int(arg))
            return BRUTTO_ROWNE_NETTO if w and brutto_rowne_netto(w["netto"], w["brutto"], w) else INNA
        if zakres == "stawka":
            s = stawki.get(arg)
            return BRUTTO_ROWNE_NETTO if s and brutto_rowne_netto(s.netto, s.brutto, arg) else INNA
        if z_zapisanych:
            return ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC if naglowek_bez_mnozenia else ZESTAW_NIEODSWIEZONY
        return BRUTTO_ROWNE_NETTO if brutto_naglowek else INNA

    for n in niespojnosci:
        n["podpowiedz"] = podpowiedz(n)

    przyczyny = []
    if bez_mnozenia:
        przyczyny.append({
            "kod": ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC, "pole": "netto",
            "roznica": max(bez_mnozenia, key=lambda z: abs(z["roznica"]))["roznica"],
            "opis": "wartość zestawu odpowiada 1 x suma dzieci: ilość zestawu została pominięta",
            "liczba": len(bez_mnozenia), "naglowek_liczony_z_zapisanych_zestawow": z_zapisanych,
            "zestawy": bez_mnozenia[:MAX_POZYCJI_W_OPISIE]})
    if nieodswiezone:
        przyczyny.append({
            "kod": ZESTAW_NIEODSWIEZONY, "pole": "netto", "roznica": max(nieodswiezone, key=lambda z: abs(z["roznica"]))["roznica"],
            "opis": "pozycja nadrzędna nie została przeliczona po zmianie dziecka (kwota zestawu != N x suma dzieci)",
            "liczba": len(nieodswiezone), "naglowek_liczony_z_zapisanych_zestawow": z_zapisanych,
            "zestawy": nieodswiezone[:MAX_POZYCJI_W_OPISIE]})
    pozycje_bn = [w for w in wiersze if not w["zestaw"] and brutto_rowne_netto(w["netto"], w["brutto"], w)]
    if pozycje_bn or brutto_naglowek:
        przyczyny.append({
            "kod": BRUTTO_ROWNE_NETTO, "pole": "brutto", "roznica": None,
            "opis": "brutto równe netto mimo stawki VAT > 0 (brak VAT w brutto)", "liczba": len(pozycje_bn),
            "naglowek": brutto_naglowek,
            "pozycje": [{"indeks": w["indeks"], "id": w["id"], "stawka": w.get("stawka"), "netto": w["netto"],
                         "vat": w["vat"], "brutto": w["brutto"]} for w in pozycje_bn[:MAX_POZYCJI_W_OPISIE]]})
    return przyczyny


def podpowiedz_dokumentu(niespojnosci):
    """Najważniejsza podpowiedź dokumentu (wśród niespójności, które nie są drobiazgiem) albo None."""
    hinty = {n.get("podpowiedz") for n in niespojnosci if not n.get("drobiazg")}
    for h in PRIORYTET:
        if h in hinty:
            return h
    return None
