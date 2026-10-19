"""Klasyfikacja przyczyn niespójności - odróżnia drobiazg od błędu.

Czyste funkcje na Decimal; zwracają słowniki-przyczyny:
  {kod, opis, roznica, pole, ...szczegóły}
Kody (stałe w bledy.py):
  POLGROSZ                  różnica <= 0,01, a któraś z porównywanych wartości ma więcej niż 2 miejsca
                            po przecinku (niezaokrąglona), np. brutto 1758.285
  NAGLOWEK_ZERO             sumy nagłówka równe 0 przy niezerowych pozycjach
  NAGLOWEK_NIZSZY/WYZSZY    nagłówek różni się od sumy pozycji o więcej niż 0,01 (z podpowiedzią,
                            które pozycje mogą różnicę tłumaczyć)
  ZESTAW_LICZONY_PODWOJNIE  nagłówek = suma liści + kwoty pozycji nadrzędnych (zestawów)
  ILOSC_X_CENA              wartość pozycji różni się od ilość x cena po rabacie o więcej niż 0,01
  BRAK_VAT_W_POZYCJACH      pozycje nie mają pola VAT (dane niepełne, nie błąd) - ustawiane przez CLI
  ILOSC_X_CENA_NARZUT       pozycje z ceną zakupu i narzutem (marżą): wartość pozycji vs ilość x cena sprzedaży
                            (zakup + narzut, po rabacie). Dwa warianty opisu: "narzut/rabat tłumaczy różnicę"
                            (informacja: ilość x cena_netto_jedn by się nie zgadzała, a z narzutem się zgadza)
                            i "cena sprzedaży nie zgadza się z zakup+narzut" (niezgodność)
  VAT_WYLICZONY_ZGODNY      pozycje bez VAT, ale ze stawką i netto: VAT wyliczony biblioteką zgadza się z
                            nagłówkiem (pozycje przestają być "niepełne")
  VAT_WYLICZONY_ROZNY       jw., ale suma wyliczonego VAT różni się od nagłówka (z podpowiedzią, które
                            stawki tłumaczą różnicę)
"""
from decimal import Decimal
from itertools import combinations

from .bledy import (ILOSC_X_CENA, ILOSC_X_CENA_NARZUT, NAGLOWEK_NIZSZY, NAGLOWEK_WYZSZY, NAGLOWEK_ZERO, POLGROSZ,
                    VAT_WYLICZONY_ROZNY, VAT_WYLICZONY_ZGODNY, ZESTAW_LICZONY_PODWOJNIE)
from .formatowanie import miejsca_znaczace

PROG = Decimal("0.01")
OPIS_NARZUT_TLUMACZY = "narzut/rabat tłumaczy różnicę"
OPIS_NARZUT_NIEZGODNA = "cena sprzedaży nie zgadza się z zakup+narzut"
POLA = ("netto", "vat", "brutto")
_KOLEJNOSC_GLOWNEGO = ("netto", "brutto", "vat")
MAX_POZYCJI_W_OPISIE = 5


def jest_polgroszem(oczekiwano, jest, roznica):
    """Różnica <= 0,01 (i niezerowa), a któraś z wartości jest niezaokrąglona (> 2 miejsca)."""
    return (roznica != 0 and abs(roznica) <= PROG
            and (miejsca_znaczace(oczekiwano) > 2 or miejsca_znaczace(jest) > 2))


def przyczyna_polgrosz(pary):
    """pary: [(oczekiwano, jest, roznica)]. Zwraca (przyczyna lub None, zbiór indeksów będących drobiazgiem)."""
    indeksy = {i for i, (o, j, r) in enumerate(pary) if jest_polgroszem(o, j, r)}
    if not indeksy:
        return None, indeksy
    najwieksza = max(abs(pary[i][2]) for i in indeksy)
    return ({"kod": POLGROSZ, "opis": "różnica <= 0,01 wynikająca z niezaokrąglonej wartości",
             "roznica": najwieksza, "pole": None, "liczba": len(indeksy)}, indeksy)


def _wartosc(w, pole):
    return w.get(pole)


def _mozliwe_pozycje(wiersze, pole, roznica):
    szukana = abs(roznica)
    wynik = []
    for w in wiersze:
        v = _wartosc(w, pole)
        if v is not None and abs(abs(v) - szukana) <= PROG:
            wynik.append({"indeks": w["indeks"], "id": w.get("id"), "pole": pole, "wartosc": v,
                          "zestaw": bool(w.get("zestaw"))})
    return wynik[:MAX_POZYCJI_W_OPISIE]


def przyczyny_naglowka(naglowek, pozycje, wiersze, zrodlo="zapisane"):
    """Porównuje sumy nagłówka z sumą pozycji.

    naglowek, pozycje: {netto, vat, brutto} -> Decimal (pozycje: None = brak danych).
    wiersze: [{indeks, id, zestaw, netto, vat, brutto}] - do wskazania pozycji tłumaczących różnicę.
    zrodlo: "zapisane" (kwoty pozycji z dokumentu) albo "obliczone" (policzone przez bibliotekę).
    """
    dostepne = [p for p in POLA if pozycje.get(p) is not None]
    if all(naglowek[p] == 0 for p in POLA) and any(pozycje[p] != 0 for p in dostepne):
        return [{"kod": NAGLOWEK_ZERO, "opis": "sumy nagłówka równe 0 przy niezerowych pozycjach",
                 "roznica": -pozycje[dostepne[0]], "pole": "suma_" + dostepne[0], "zrodlo_pozycji": zrodlo,
                 "suma_pozycji": {p: pozycje[p] for p in dostepne}}]
    roznice = {p: naglowek[p] - pozycje[p] for p in dostepne}
    duze = {p: r for p, r in roznice.items() if abs(r) > PROG}
    if not duze:
        return []
    glowne = next(p for p in _KOLEJNOSC_GLOWNEGO if p in duze)
    r = duze[glowne]
    kod = NAGLOWEK_NIZSZY if r < 0 else NAGLOWEK_WYZSZY
    wynik = [{"kod": kod, "opis": "nagłówek %s sumy pozycji o więcej niż 0,01 (%s)"
                                  % ("niższy od" if r < 0 else "wyższy od", glowne),
              "roznica": r, "pole": "suma_" + glowne, "zrodlo_pozycji": zrodlo,
              "roznice_pol": {"suma_" + p: d for p, d in duze.items()},
              "mozliwe_pozycje": _mozliwe_pozycje(wiersze, glowne, r)}]
    zestawy = [w for w in wiersze if w.get("zestaw") and _wartosc(w, glowne) is not None]
    if r > 0 and zestawy and abs(r - sum((w[glowne] for w in zestawy), Decimal(0))) <= PROG:
        wynik.append({"kod": ZESTAW_LICZONY_PODWOJNIE,
                      "opis": "nagłówek = suma liści + kwoty pozycji nadrzędnych (zestawy policzone drugi raz)",
                      "roznica": r, "pole": "suma_" + glowne,
                      "pozycje": [w["indeks"] for w in zestawy]})
    return wynik


def przyczyna_ilosc_x_cena(porownania, pole):
    """porownania: [(indeks, id, zapisane, oczekiwane)] dla pozycji (bez zestawów).

    oczekiwane = wartość policzona z ilości, ceny, rabatu pozycji i rabatu dokumentu."""
    zle = [(i, id_, z, o, z - o) for i, id_, z, o in porownania if abs(z - o) > PROG]
    if not zle:
        return None
    najgorsza = max(zle, key=lambda x: abs(x[4]))
    return {"kod": ILOSC_X_CENA, "opis": "wartość %s pozycji różni się od ilość x cena po rabacie o więcej niż 0,01" % pole,
            "roznica": najgorsza[4], "pole": pole, "liczba": len(zle),
            "pozycje": [{"indeks": i, "id": id_, "zapisane": z, "oczekiwane": o, "roznica": r}
                        for i, id_, z, o, r in zle[:MAX_POZYCJI_W_OPISIE]]}


def stawki_tlumaczace(wg_stawek, roznica, maks=3):
    """Zbiory stawek, których łączny VAT równa się modułowi różnicy (z dokładnością do 0,01).

    wg_stawek: [{"stawka", "vat", ...}]. Zwraca do `maks` najmniejszych zbiorów (listy etykiet), np. gdy
    nagłówek pomija VAT całej stawki 8%: [["8"]]. Stawki z VAT równym 0 nic nie tłumaczą."""
    szukana = abs(roznica)
    grupy = [(g["stawka"], g["vat"]) for g in wg_stawek if g["vat"] != 0]
    wynik = []
    for rozmiar in range(1, len(grupy) + 1):
        for podzbior in combinations(grupy, rozmiar):
            if abs(abs(sum((v for _, v in podzbior), Decimal(0))) - szukana) <= PROG:
                wynik.append([s for s, _ in podzbior])
        if wynik:
            break
    return wynik[:maks]


def przyczyna_vat_wyliczony(warianty, vat_naglowka, brutto_naglowka, netto_niezaokraglone=False):
    """Porównuje VAT wyliczony z (stawka, netto) pozycji z VAT w nagłówku.

    warianty: {tryb_vat: {"vat", "brutto", "netto", "wg_stawek": [{"stawka", "netto", "vat"}]}} - wyliczone
    biblioteką w trybach per_stawka i per_pozycja. Zgodność z DOWOLNYM trybem wystarcza.
    netto_niezaokraglone: któreś zapisane netto ma > 2 miejsca; wtedy różnica <= 0,01 to POLGROSZ.
    Zwraca przyczynę: VAT_WYLICZONY_ZGODNY, POLGROSZ albo VAT_WYLICZONY_ROZNY (roznica = nagłówek - wyliczony).
    """
    zgodne = [tv for tv, w in warianty.items() if w["vat"] == vat_naglowka]
    if zgodne:
        w = warianty[zgodne[0]]
        return {"kod": VAT_WYLICZONY_ZGODNY, "pole": "suma_vat", "roznica": Decimal(0),
                "opis": "VAT wyliczony ze stawki i netto pozycji zgadza się z nagłówkiem",
                "vat_wyliczony": w["vat"], "vat_naglowka": vat_naglowka, "brutto_wyliczone": w["brutto"],
                "brutto_naglowka": brutto_naglowka, "tryby_vat": zgodne, "wg_stawek": w["wg_stawek"]}
    tv = min(warianty, key=lambda t: abs(vat_naglowka - warianty[t]["vat"]))
    w = warianty[tv]
    r = vat_naglowka - w["vat"]
    if abs(r) <= PROG and netto_niezaokraglone:
        return {"kod": POLGROSZ, "pole": "suma_vat", "roznica": abs(r), "liczba": 1,
                "opis": "VAT wyliczony różni się od nagłówka o <= 0,01, a netto pozycji jest niezaokrąglone"}
    return {"kod": VAT_WYLICZONY_ROZNY, "pole": "suma_vat", "roznica": r,
            "opis": "suma VAT wyliczonego ze stawek i netto pozycji różni się od VAT w nagłówku",
            "vat_wyliczony": w["vat"], "vat_naglowka": vat_naglowka, "brutto_wyliczone": w["brutto"],
            "brutto_naglowka": brutto_naglowka, "roznica_brutto": brutto_naglowka - w["brutto"],
            "tryb_vat": tv, "wg_stawek": w["wg_stawek"], "stawki_tlumaczace": stawki_tlumaczace(w["wg_stawek"], r)}


def przyczyny_ilosc_x_cena_narzut(rekordy):
    """Sprawdzenie ilość x cena sprzedaży (zakup + narzut, po rabacie) vs zapisana wartość pozycji.

    rekordy: [{indeks, id, zapisane, oczekiwane, cena_oczekiwana, cena_zapisana (lub None), naiwne (lub None),
    wyjasnienie, narzut_wynikowy}]. Zwraca do dwóch przyczyn ILOSC_X_CENA_NARZUT:
      - niezgodność (OPIS_NARZUT_NIEZGODNA): zapisana wartość różni się od oczekiwanej o więcej niż 0,01
        albo zapisana cena sprzedaży różni się od zakup+narzut o więcej niż 0,01;
      - informacja (OPIS_NARZUT_TLUMACZY, `informacja`: True): wartość się zgadza, choć ilość x cena_netto_jedn
        (bez narzutu) by się nie zgadzała - narzut/rabat tłumaczy różnicę.
    """
    zle, wyjasnione = [], []
    for r in rekordy:
        zla_wartosc = abs(r["zapisane"] - r["oczekiwane"]) > PROG
        zla_cena = r.get("cena_zapisana") is not None and abs(r["cena_zapisana"] - r["cena_oczekiwana"]) > PROG
        if zla_wartosc or zla_cena:
            zle.append(r)
        elif r.get("naiwne") is not None and abs(r["zapisane"] - r["naiwne"]) > PROG:
            wyjasnione.append(r)
    wynik = []
    if zle:
        gorsza = max(zle, key=lambda r: abs(r["zapisane"] - r["oczekiwane"]))
        wynik.append({
            "kod": ILOSC_X_CENA_NARZUT, "opis": OPIS_NARZUT_NIEZGODNA, "pole": "netto", "liczba": len(zle),
            "roznica": gorsza["zapisane"] - gorsza["oczekiwane"],
            "pozycje": [{"indeks": r["indeks"], "id": r["id"], "zapisane": r["zapisane"], "oczekiwane": r["oczekiwane"],
                         "roznica": r["zapisane"] - r["oczekiwane"], "cena_sprzedazy_oczekiwana": r["cena_oczekiwana"],
                         "cena_sprzedazy_zapisana": r.get("cena_zapisana"), "wyjasnienie": r.get("wyjasnienie"),
                         "narzut_wynikowy": r.get("narzut_wynikowy")} for r in zle[:MAX_POZYCJI_W_OPISIE]]})
    if wyjasnione:
        wynik.append({
            "kod": ILOSC_X_CENA_NARZUT, "opis": OPIS_NARZUT_TLUMACZY, "pole": "netto", "roznica": None,
            "informacja": True, "etykieta": ILOSC_X_CENA_NARZUT + " (informacja)", "liczba": len(wyjasnione),
            "pozycje": [{"indeks": r["indeks"], "id": r["id"], "zapisane": r["zapisane"],
                         "bez_narzutu": r["naiwne"], "oczekiwane": r["oczekiwane"]}
                        for r in wyjasnione[:MAX_POZYCJI_W_OPISIE]]})
    return wynik
