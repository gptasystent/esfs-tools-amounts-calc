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
"""
from decimal import Decimal

from .bledy import (ILOSC_X_CENA, NAGLOWEK_NIZSZY, NAGLOWEK_WYZSZY, NAGLOWEK_ZERO, POLGROSZ,
                    ZESTAW_LICZONY_PODWOJNIE)
from .formatowanie import miejsca_znaczace

PROG = Decimal("0.01")
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
