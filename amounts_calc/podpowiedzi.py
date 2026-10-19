"""Podpowiedzi przyczyn niespójności: czy pasuje do "zestaw nie odświeżony" albo "brutto równe netto".

Każda niespójność z sprawdz_spojnosc dostaje pole `podpowiedz`:
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

from .bledy import BRUTTO_ROWNE_NETTO, ZESTAW_NIEODSWIEZONY, ZESTAW_ROZNY_OD_DZIECI
from .hierarchia import liscie_pod
from .klasyfikacja import MAX_POZYCJI_W_OPISIE, POLA, PROG
from .stawki import wartosc_stawki

INNA = "inna"
PRIORYTET = (ZESTAW_NIEODSWIEZONY, BRUTTO_ROWNE_NETTO, INNA)
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
    return abs(naglowek["brutto"] - naglowek["netto"]) <= _POL and abs(vat_oczekiwany) > PROG


def zestawy_nieodswiezone(wiersze, dzieci, indeksy, naglowek, pozycje):
    """Zestawy (indeksy z ZESTAW_ROZNY_OD_DZIECI), dla których są dowody, że nie odświeżono ich po zmianie dziecka.

    Zwraca (lista {indeks, id, zapisane, suma_dzieci, roznica, dowody}, czy_naglowek_liczony_z_zapisanych_zestawow)."""
    liscie = [w for w in wiersze if not w["zestaw"]]
    suma_wszystkich = {k: sum((w[k] for w in liscie), Decimal(0)) for k in POLA}
    deltas = {}
    for i in indeksy:
        liscie_i = [wiersze[j] for j in liscie_pod(i, dzieci)]
        deltas[i] = {k: wiersze[i][k] - sum((l[k] for l in liscie_i), Decimal(0)) for k in POLA}
    # nagłówek = suma liści + różnice zestawów najwyższego poziomu => nagłówek policzony z zapisanych (starych) zestawów
    top = [i for i in indeksy if pozycje[i].get("parent_id") is None]
    delta_top = {k: sum((deltas[i][k] for i in top), Decimal(0)) for k in POLA}
    z_zapisanych = bool(top) and any(delta_top[k] != 0 for k in POLA) and all(
        abs(naglowek[k] - (suma_wszystkich[k] + delta_top[k])) <= PROG for k in POLA)
    wynik = []
    for i in sorted(indeksy):
        liscie_i = [wiersze[j] for j in liscie_pod(i, dzieci)]
        d = deltas[i]["netto"]
        dowody = []
        rowne = [l for l in liscie_i if abs(abs(l["netto"]) - abs(d)) <= PROG]
        if len(rowne) == 1 and d != 0:
            dowody.append({"dowod": "roznica_rowna_wartosci_dziecka", "dziecko": rowne[0]["indeks"], "id": rowne[0]["id"]})
        if abs(naglowek["netto"] - suma_wszystkich["netto"]) <= PROG:
            dowody.append({"dowod": "naglowek_zgodny_z_suma_dzieci"})
        if z_zapisanych:
            dowody.append({"dowod": "naglowek_zgodny_z_zapisanymi_zestawami"})
        if dowody:
            wynik.append({"indeks": i, "id": wiersze[i]["id"], "zapisane": wiersze[i]["netto"],
                          "suma_dzieci": wiersze[i]["netto"] - d, "roznica": d, "dowody": dowody})
    return wynik, z_zapisanych


def oznacz_podpowiedzi(niespojnosci, zapisany, wiersze, dzieci, pozycje, naglowek):
    """Dopisuje `podpowiedz` do każdej niespójności (mutuje słowniki) i zwraca przyczyny:
    ZESTAW_NIEODSWIEZONY i BRUTTO_ROWNE_NETTO (tylko gdy coś znaleziono). Wymaga kwot pozycji (wiersze)."""
    wiersz = {w["indeks"]: w for w in wiersze}
    indeksy_zestawow = [int(n["zakres"].split(":")[1]) for n in niespojnosci
                        if n["kod"] == ZESTAW_ROZNY_OD_DZIECI and not n.get("drobiazg")]
    nieodswiezone, z_zapisanych = zestawy_nieodswiezone(wiersze, dzieci, sorted(set(indeksy_zestawow)), naglowek,
                                                        pozycje) if indeksy_zestawow else ([], False)
    nieodswiezone_idx = {z["indeks"] for z in nieodswiezone}
    brutto_naglowek = _naglowek_brutto_rowne_netto(naglowek, wiersze)
    stawki = {s.stawka_vat: s for s in zapisany.podsumowanie}

    def podpowiedz(n):
        if n.get("drobiazg"):
            return "POLGROSZ"
        zakres, _, arg = n["zakres"].partition(":")
        if n["kod"] == ZESTAW_ROZNY_OD_DZIECI:
            return ZESTAW_NIEODSWIEZONY if int(arg) in nieodswiezone_idx else INNA
        if zakres == "pozycja":
            w = wiersz.get(int(arg))
            return BRUTTO_ROWNE_NETTO if w and brutto_rowne_netto(w["netto"], w["brutto"], w) else INNA
        if zakres == "stawka":
            s = stawki.get(arg)
            return BRUTTO_ROWNE_NETTO if s and brutto_rowne_netto(s.netto, s.brutto, arg) else INNA
        if z_zapisanych:
            return ZESTAW_NIEODSWIEZONY
        return BRUTTO_ROWNE_NETTO if brutto_naglowek else INNA

    for n in niespojnosci:
        n["podpowiedz"] = podpowiedz(n)

    przyczyny = []
    if nieodswiezone:
        przyczyny.append({
            "kod": ZESTAW_NIEODSWIEZONY, "pole": "netto", "roznica": max(nieodswiezone, key=lambda z: abs(z["roznica"]))["roznica"],
            "opis": "pozycja nadrzędna nie została przeliczona po zmianie dziecka (kwota zestawu != suma dzieci)",
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
