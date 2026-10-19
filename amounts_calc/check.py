"""Wsadowe sprawdzanie dokumentów (np. wyeksportowanych z bazy do JSON) - bez wysyłania danych do repo.

    python -m amounts_calc.check dokumenty.json [--tryb-vat per_stawka|per_pozycja]
        [--json wynik.json] [--csv wynik.csv] [--max-przyklady N] [--pomin-typy TYP1,TYP2]
        [--dopusc-ujemne | --nie-dopuszczaj-ujemnych] [--mapowanie mapowanie.json]

Dla każdego dokumentu:
  a) sprawdz_spojnosc na zapisanych danych (niespójność zapisanych sum),
  b) oblicz() z pozycji w OBU trybach VAT i porownaj() z zapisanymi sumami; zapisuje, który tryb
     pasuje (żaden / oba / jeden). Zgodność oceniana jest po sumach dokumentu i po podsumowaniu
     stawek; różnice na poziomie pozycji są tylko liczone (korekta groszowa per stawka może
     legalnie trafić na inną pozycję niż w systemie źródłowym).
Błędny dokument nie przerywa całości - trafia do raportu z kodem błędu.

Kod wyjścia: 0 = nic nie wymaga uwagi (drobiazgi i dane niepełne nie liczą się), 1 = są dokumenty
niespójne lub błędne, 2 = błąd wejścia (plik/JSON/mapowanie).
"""
import argparse
import csv
import json
import sys
import uuid
from collections import Counter
from decimal import Decimal, DecimalException

from .adapter import id_dokumentu, scal_mapowanie, typ_dokumentu, wczytaj_plik_json, z_wiersza
from .bledy import (BRAK_CENY, BRAK_POLA, BRAK_VAT_W_POZYCJACH, ILOSC_X_CENA, ILOSC_X_CENA_NARZUT, NAGLOWEK_NIZSZY, NAGLOWEK_WYZSZY, NAGLOWEK_ZERO,
                    NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, NIEPOPRAWNA_LICZBA, NIEZGODNY_Z_BIBLIOTEKA, POLGROSZ, VAT_WYLICZONY_ZGODNY,
                    SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, VAT_WYLICZONY_ROZNY, ZESTAW_LICZONY_PODWOJNIE, ZESTAW_ROZNY_OD_DZIECI,
                    BladWalidacji)
from .config import TRYBY_VAT, VAT_PER_POZYCJA, VAT_PER_STAWKA
from .formatowanie import format_bez_zer, format_kwoty
from .hierarchia import zbuduj_hierarchie
from .formatowanie import miejsca_znaczace
from .oferty import (delta_zestawow_najwyzszego_poziomu, ma_narzut, przyczyna_zestaw_z_narzutem, rekordy_narzutu,
                     zestawy_z_narzutem)
from .klasyfikacja import (PROG, przyczyna_ilosc_x_cena, przyczyna_polgrosz, przyczyna_vat_wyliczony,
                           przyczyny_ilosc_x_cena_narzut, przyczyny_naglowka)
from .model import dokument_z_slownika
from .obliczenia import oblicz
from .stawki import do_decimal
from .spojnosc import _wpis, porownaj, sprawdz_spojnosc

DOPASOWANIA = ("oba", "per_stawka", "per_pozycja", "zaden")
STATUSY = ("spojny", "drobiazg", "niepelny", "niespojny", "blad", "pominiety")
BRAK_TYPU = "(brak typu)"
_POZYCJA_KLUCZE = ("netto", "vat", "brutto")


def _dopasowanie(ps, pp):
    return "oba" if ps and pp else "per_stawka" if ps else "per_pozycja" if pp else "zaden"


def _blad(kod, pole, wiadomosc, etap):
    return {"kod": kod, "pole": pole, "etap": etap, "wiadomosc": wiadomosc}


def _blad_z_wyjatku(e, etap):
    if isinstance(e, BladWalidacji):
        return _blad(e.kod, e.pole, e.wiadomosc, etap)
    return _blad(NIEPOPRAWNA_LICZBA, None, "wartość liczbowa poza zakresem (%s)" % type(e).__name__, etap)


def _kryterium(roznice, z_stawkami):
    """Różnice istotne dla oceny trybu: sumy dokumentu (+ podsumowanie stawek)."""
    return [r for r in roznice
            if r["pole"].startswith("suma_") or (z_stawkami and r["pole"].startswith("stawka:"))]


def _opisz_roznice(roznice):
    return [{"pole": r["pole"], "zapisane": r["a"], "biblioteka": r["b"], "roznica": r["roznica"]}
            for r in roznice]


def nazwa_typu(typ):
    """Typ dokumentu jako tekst do grupowania (None / puste -> BRAK_TYPU)."""
    tekst = "" if typ is None else str(typ).strip()
    return tekst or BRAK_TYPU


def zbior_typow(typy):
    """'KOREKTA, roz' albo lista -> zbiór nazw porównywanych bez względu na wielkość liter."""
    if isinstance(typy, str):
        typy = typy.split(",")
    return frozenset(t.strip().casefold() for t in (typy or ()) if t.strip())


ISTOTNE = frozenset({NAGLOWEK_ZERO, NAGLOWEK_NIZSZY, NAGLOWEK_WYZSZY, ILOSC_X_CENA, ILOSC_X_CENA_NARZUT,
                     ZESTAW_LICZONY_PODWOJNIE, NIEZGODNY_Z_BIBLIOTEKA, VAT_WYLICZONY_ROZNY})


def _istotna(przyczyna):
    """Przyczyna z ISTOTNE, która nie jest tylko informacją (np. ILOSC_X_CENA_NARZUT: "narzut tłumaczy")."""
    return przyczyna["kod"] in ISTOTNE and not przyczyna.get("informacja")


def etykieta_kodu(przyczyna):
    """Nazwa kodu w rozkładzie kodów i w CSV (informacyjny wariant kodu ma dopisek)."""
    return przyczyna.get("etykieta") or przyczyna["kod"]


def nazwy_typow(typy):
    """Nazwy typów tak, jak je wpisano (do wyświetlania), bez powtórzeń z pominięciem wielkości liter."""
    if isinstance(typy, str):
        typy = typy.split(",")
    wynik, widziane = [], set()
    for t in typy or ():
        t = t.strip()
        if t and t.casefold() not in widziane:
            widziane.add(t.casefold())
            wynik.append(t)
    return wynik


def _status(wynik):
    """blad > niespojny > niepelny > drobiazg > spojny."""
    if wynik["blad"]:
        return "blad"
    kody = {p["kod"] for p in wynik["przyczyny"]}
    if any(not n.get("drobiazg") for n in wynik["niespojnosci"]) or any(_istotna(p) for p in wynik["przyczyny"]):
        return "niespojny"
    if BRAK_VAT_W_POZYCJACH in kody:
        return "niepelny"
    if POLGROSZ in kody:
        return "drobiazg"
    return "spojny"


def _rodzaj_danych(pozycje, dzieci):
    """"pelne" (netto/vat/brutto w pozycjach), "brak_kwot" (żadnych kwot w pozycjach) albo
    "brak_vat" (netto - i ewentualnie brutto - są, pola VAT brak we wszystkich pozycjach).
    Pozycje nadrzędne (zestawy) nie są brane pod uwagę. Mieszanka braków to dane "pelne" -> BRAK_POLA."""
    liscie = [p for i, p in enumerate(pozycje) if i not in dzieci]
    if not liscie:
        return "pelne"
    ma = {k: all(k in p for p in liscie) for k in _POZYCJA_KLUCZE}
    zadne = {k: not any(k in p for p in liscie) for k in _POZYCJA_KLUCZE}
    if all(zadne.values()):
        return "brak_kwot"
    if ma["netto"] and zadne["vat"] and (ma["brutto"] or zadne["brutto"]):
        return "brak_vat"
    return "pelne"


def _dane_pozycji(rodzaj, pozycje, zapisany, dzieci, obliczony):
    """(wiersze, sumy pozycji, źródło) - to, z czego da się porównać nagłówek z pozycjami."""
    if rodzaj == "pelne":
        wiersze = [{"indeks": p.indeks, "id": p.id, "zestaw": p.zestaw, "netto": p.netto, "vat": p.vat,
                    "brutto": p.brutto} for p in zapisany.pozycje]
        zrodlo = "zapisane"
    elif rodzaj == "brak_vat":
        wiersze = []
        for i, p in enumerate(pozycje):
            w = {"indeks": i, "id": p.get("id"), "zestaw": i in dzieci, "vat": None}
            for k in ("netto", "brutto"):
                w[k] = do_decimal(p[k], "pozycje[%d].%s" % (i, k)) if k in p else None
            wiersze.append(w)
        zrodlo = "zapisane"
    else:
        if obliczony is None:
            return [], None, "obliczone"
        wiersze = [{"indeks": p.indeks, "id": p.id, "zestaw": p.zestaw, "netto": p.netto, "vat": p.vat,
                    "brutto": p.brutto} for p in obliczony.pozycje]
        zrodlo = "obliczone"
    liscie = [w for w in wiersze if not w["zestaw"]]
    sumy = {k: sum((w[k] for w in liscie), Decimal(0)) if all(w[k] is not None for w in liscie) else None
            for k in _POZYCJA_KLUCZE}
    return wiersze, sumy, zrodlo


def _wylicz_vat(pozycje, dzieci, dopusc_ujemne):
    """VAT i brutto wyliczone biblioteką ze `stawka_vat` i zapisanego `netto` każdej pozycji (w obu trybach VAT).

    Zapisane netto pozycji traktowane jest jako gotowa wartość (bez ponownego rabatu). None, gdy któraś
    pozycja nie ma stawki - wtedy zostaje BRAK_VAT_W_POZYCJACH."""
    liscie = [p for i, p in enumerate(pozycje) if i not in dzieci]
    if not liscie or any(p.get("stawka_vat") is None for p in liscie):
        return None
    wejscie = [{"ilosc": 1, "cena_netto_jedn": p["netto"], "stawka_vat": p["stawka_vat"]} for p in liscie]
    warianty = {}
    for tv in (VAT_PER_STAWKA, VAT_PER_POZYCJA):
        d = oblicz(wejscie, tryb="netto", tryb_vat=tv, dopusc_ujemne=dopusc_ujemne)
        warianty[tv] = {"vat": d.suma_vat, "brutto": d.suma_brutto, "netto": d.suma_netto,
                        "wg_stawek": [{"stawka": s.stawka_vat, "netto": s.netto, "vat": s.vat}
                                      for s in d.podsumowanie]}
    return warianty


def _scal_polgrosze(przyczyny):
    pg = [c for c in przyczyny if c["kod"] == POLGROSZ]
    if len(pg) < 2:
        return przyczyny
    pierwszy = dict(pg[0], roznica=max(c["roznica"] for c in pg), liczba=sum(c.get("liczba", 1) for c in pg))
    return [pierwszy if c is pg[0] else c for c in przyczyny if c is pg[0] or c["kod"] != POLGROSZ]


def _przyczyny(wynik, rodzaj, zapisany, wiersze, sumy, zrodlo, obliczony, dopasowanie_zaden, najlepsze_roznice,
               wyliczony=None, pozycje=(), rabat_dok=0, dopusc_ujemne=False, wstepne=()):
    """Lista przyczyn (kody z klasyfikacja.py); oznacza `drobiazg` na niespójnościach będących POLGROSZEM.
    `wstepne`: przyczyny ustalone wcześniej (np. ZESTAW_Z_NARZUTEM)."""
    przyczyny = list(wstepne)
    if rodzaj == "brak_vat" and wyliczony is None:
        przyczyny.append({"kod": BRAK_VAT_W_POZYCJACH, "pole": "vat", "roznica": None,
                          "opis": "pozycje nie mają pola VAT ani (wszystkie) stawki - sprawdzono tylko netto "
                                  "(i brutto) pozycji z nagłówkiem; dane niepełne, nie błąd"})
    elif rodzaj == "brak_vat":
        niezaokraglone = any(w["netto"] is not None and miejsca_znaczace(w["netto"]) > 2
                             for w in wiersze if not w["zestaw"])
        przyczyny.append(przyczyna_vat_wyliczony(wyliczony, zapisany.suma_vat, zapisany.suma_brutto, niezaokraglone))
    if sumy is not None:
        naglowek = {"netto": zapisany.suma_netto, "vat": zapisany.suma_vat, "brutto": zapisany.suma_brutto}
        przyczyny += przyczyny_naglowka(naglowek, sumy, wiersze, zrodlo)
    if obliczony is not None and rodzaj in ("pelne", "brak_vat"):
        pole = "netto" if zapisany.tryb == "netto" else "brutto"
        # pozycje z ceną zakupu i narzutem (tylko tryb od netto) mają własne sprawdzenie ILOSC_X_CENA_NARZUT
        narzutowe = {i for i, p in enumerate(pozycje) if ma_narzut(p)} if pole == "netto" else set()
        porownania = [(w["indeks"], w["id"], w[pole], getattr(obliczony.pozycje[w["indeks"]], pole))
                      for w in wiersze if not w["zestaw"] and w[pole] is not None and w["indeks"] not in narzutowe]
        p = przyczyna_ilosc_x_cena(porownania, pole)
        if p:
            przyczyny.append(p)
        if narzutowe:
            przyczyny += przyczyny_ilosc_x_cena_narzut(
                rekordy_narzutu(pozycje, wiersze, obliczony, rabat_dok, dopusc_ujemne))
    # POLGROSZ: z niespójności zapisanych danych i (gdy żaden tryb nie pasuje) z różnic wobec biblioteki
    pary = [(n["oczekiwano"], n["jest"], n["roznica"]) for n in wynik["niespojnosci"]]
    pary_b = [(r["biblioteka"] or Decimal(0), r["zapisane"] or Decimal(0), r["roznica"]) for r in najlepsze_roznice]
    pg, idx = przyczyna_polgrosz(pary + (pary_b if dopasowanie_zaden else []))
    for i in idx:
        if i < len(pary):
            wynik["niespojnosci"][i]["drobiazg"] = True
    if pg:
        przyczyny.append(pg)
    przyczyny = _scal_polgrosze(przyczyny)
    istotne = any(not n.get("drobiazg") for n in wynik["niespojnosci"]) or any(_istotna(c) for c in przyczyny)
    if dopasowanie_zaden and not istotne:
        reszta = [r for i, r in enumerate(najlepsze_roznice) if len(pary) + i not in idx]
        if reszta:
            najw = max(reszta, key=lambda r: abs(r["roznica"]))
            przyczyny.append({"kod": NIEZGODNY_Z_BIBLIOTEKA, "pole": najw["pole"], "roznica": najw["roznica"],
                              "opis": "żaden tryb VAT nie odtwarza zapisanych sum"})
    return przyczyny


def _uwzglednij_zestawy_w_naglowku(kan, zapisany, zestawy, pozycje):
    """Jeśli nagłówek = suma liści + różnice wyjaśnionych zestawów (narzut/rabat zestawu wchodzi do sum
    dokumentu), zwraca dokument z nagłówkiem pomniejszonym o te różnice - wtedy sumy liczone z liści
    zgadzają się z nagłówkiem. Inaczej zwraca dokument bez zmian. Drugi wynik: czy nagłówek je uwzględnia."""
    delta = delta_zestawow_najwyzszego_poziomu(zestawy, pozycje)
    if all(d == 0 for d in delta.values()):
        return zapisany, False
    liscie = [p for p in zapisany.pozycje if not p.zestaw]
    naglowek = {"netto": zapisany.suma_netto, "vat": zapisany.suma_vat, "brutto": zapisany.suma_brutto}
    suma = {k: sum((getattr(p, k) for p in liscie), Decimal(0)) for k in naglowek}
    if not all(abs(naglowek[k] - (suma[k] + delta[k])) <= PROG for k in naglowek):
        return zapisany, False
    return dokument_z_slownika(dict(kan, suma_netto=naglowek["netto"] - delta["netto"],
                                    suma_vat=naglowek["vat"] - delta["vat"],
                                    suma_brutto=naglowek["brutto"] - delta["brutto"])), True


def _policz_oba_tryby(kan, zapisany, rodzaj, dopusc_ujemne=False):
    z_stawkami = rodzaj == "pelne" or "podsumowanie" in kan
    obliczone, rozbieznosci, pozycyjne, pasuje = {}, {}, {}, {}
    for tv in (VAT_PER_STAWKA, VAT_PER_POZYCJA):
        obliczone[tv] = oblicz(kan["pozycje"], tryb=kan.get("tryb", "netto"), waluta=kan.get("waluta", "PLN"),
                               rabat_dokumentu_proc=kan.get("rabat_dokumentu_proc", 0), tryb_vat=tv,
                               dopusc_ujemne=dopusc_ujemne)
        wszystkie = porownaj(zapisany, obliczone[tv])
        istotne = _kryterium(wszystkie, z_stawkami)
        rozbieznosci[tv] = _opisz_roznice(istotne)
        pozycyjne[tv] = sum(1 for r in wszystkie if r["pole"].startswith("pozycje["))
        pasuje[tv] = not istotne
    return obliczone, rozbieznosci, pozycyjne, pasuje


def sprawdz_dokument(surowy, indeks=0, tryb_vat=VAT_PER_STAWKA, mapowanie=None, pomin_typy=(),
                     dopusc_ujemne=False):
    """Sprawdza jeden dokument (słownik o dowolnych nazwach pól + mapowanie). Nie rzuca z powodu danych.

    Dokument, którego typ jest w `pomin_typy`, nie jest sprawdzany (status "pominiety").
    `dopusc_ujemne` dopuszcza ujemne ilości i ceny pozycji; w bibliotece domyślnie False (jak w oblicz()),
    a CLI włącza je domyślnie, bo w zapisanych dokumentach to normalne (rabat jako linia, korekta, zwrot).
    Wynik: status (spojny / drobiazg / niepelny / niespojny / blad / pominiety), niespojnosci
    (z sprawdz_spojnosc), przyczyny (kody z klasyfikacja.py) i dopasowanie do trybów VAT.
    """
    typ = nazwa_typu(typ_dokumentu(surowy, mapowanie))
    wynik = {"indeks": indeks, "id": id_dokumentu(surowy, mapowanie), "typ": typ, "status": None,
             "blad": None, "niespojnosci": [], "przyczyny": [], "dane": None, "pasuje": None,
             "tryb_pasujacy": None, "rozbieznosci": None, "liczba_roznic_pozycji": None,
             "pominieto_pozycje": False, "max_roznica": Decimal(0)}
    if typ.casefold() in zbior_typow(pomin_typy):
        wynik["status"] = "pominiety"
        return wynik
    etap = "wejscie"
    najlepsze = []
    try:
        kan = z_wiersza(surowy, mapowanie)
        pozycje = kan["pozycje"]
        dzieci = zbuduj_hierarchie([(p.get("id"), p.get("parent_id")) for p in pozycje])
        rodzaj = _rodzaj_danych(pozycje, dzieci)
        wynik["dane"] = rodzaj
        wynik["pominieto_pozycje"] = rodzaj != "pelne"
        zapisany = dokument_z_slownika(dict(kan, pozycje=pozycje if rodzaj == "pelne" else []))
        przyczyny_zestawow = []
        if rodzaj == "pelne" and dzieci:
            # zestaw z własnym narzutem/rabatem może różnić się od sumy dzieci - to informacja, nie błąd
            wyjasnione = zestawy_z_narzutem(pozycje, zapisany, dzieci)
            if wyjasnione:
                zapisany, naglowek_uwzglednia = _uwzglednij_zestawy_w_naglowku(kan, zapisany, wyjasnione, pozycje)
                przyczyny_zestawow.append(przyczyna_zestaw_z_narzutem(wyjasnione, naglowek_uwzglednia))
        niespojnosci = sprawdz_spojnosc(zapisany, tryb_vat=tryb_vat)
        if przyczyny_zestawow:
            objete = {z["indeks"] for z in przyczyny_zestawow[0]["zestawy"]}
            niespojnosci = [n for n in niespojnosci if not (
                n["kod"] == ZESTAW_ROZNY_OD_DZIECI and int(n["zakres"].split(":")[1]) in objete)]
        if rodzaj != "pelne":   # bez kwot (i VAT) pozycji zostaje sprawdzenie sum dokumentu
            niespojnosci = [n for n in niespojnosci
                            if n["kod"] == NETTO_PLUS_VAT_ROZNE_OD_BRUTTO and n["zakres"] == "dokument"]
        wiersze, sumy, zrodlo = _dane_pozycji(rodzaj, pozycje, zapisany, dzieci, None)
        if rodzaj == "brak_vat":
            naglowek = {"netto": zapisany.suma_netto, "brutto": zapisany.suma_brutto}
            for pole in ("netto", "brutto"):
                if sumy[pole] is not None and sumy[pole] != naglowek[pole]:
                    niespojnosci.append(_wpis(SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, "dokument", "suma_" + pole,
                                              sumy[pole], naglowek[pole], "suma pozycji != suma dokumentu"))
        wynik["niespojnosci"] = niespojnosci

        etap = "obliczenia"
        obliczone = wyliczony = None
        try:
            if rodzaj == "brak_vat":
                wyliczony = _wylicz_vat(pozycje, dzieci, dopusc_ujemne)
            try:
                obliczone, rozbieznosci, pozycyjne, pasuje = _policz_oba_tryby(kan, zapisany, rodzaj, dopusc_ujemne)
                wynik.update(pasuje=pasuje, rozbieznosci=rozbieznosci, liczba_roznic_pozycji=pozycyjne,
                             tryb_pasujacy=_dopasowanie(pasuje[VAT_PER_STAWKA], pasuje[VAT_PER_POZYCJA]))
                # do "największej rozbieżności" liczy się lepszy z trybów (mniejsza suma różnic)
                najlepszy = min((VAT_PER_STAWKA, VAT_PER_POZYCJA),
                                key=lambda t: sum(abs(r["roznica"]) for r in rozbieznosci[t]))
                najlepsze = rozbieznosci[najlepszy]
            except BladWalidacji as e:
                # bez ilości/ceny/stawki w pozycjach bez VAT nie ma czego porównać z biblioteką - zostają sumy
                if not (rodzaj == "brak_vat" and e.kod in (BRAK_POLA, BRAK_CENY)):
                    raise
        except (BladWalidacji, DecimalException) as e:
            wynik["blad"] = _blad_z_wyjatku(e, etap)
        obliczony = obliczone[VAT_PER_STAWKA] if obliczone else None
        if rodzaj == "brak_kwot":
            wiersze, sumy, zrodlo = _dane_pozycji(rodzaj, pozycje, zapisany, dzieci, obliczony)
        wynik["przyczyny"] = _przyczyny(wynik, rodzaj, zapisany, wiersze, sumy, zrodlo, obliczony,
                                        wynik["tryb_pasujacy"] == "zaden", najlepsze, wyliczony, pozycje,
                                        kan.get("rabat_dokumentu_proc", 0), dopusc_ujemne, przyczyny_zestawow)
    except (BladWalidacji, DecimalException) as e:
        wynik["blad"] = _blad_z_wyjatku(e, etap)

    kandydaci = [abs(n["roznica"]) for n in wynik["niespojnosci"]]
    kandydaci += [abs(r["roznica"]) for r in najlepsze]
    kandydaci += [abs(c["roznica"]) for c in wynik["przyczyny"] if c.get("roznica") is not None]
    wynik["max_roznica"] = max(kandydaci, default=Decimal(0))
    wynik["status"] = _status(wynik)
    return wynik


def ma_problem(wynik):
    """Czy dokument trafia do raportu (JSON/CSV): wszystko poza spójnymi i pominiętymi."""
    return wynik["status"] not in ("spojny", "pominiety")


def _ma_kod(wynik, kod):
    return any(c["kod"] == kod for c in wynik["przyczyny"])


def _wg_typu(wyniki):
    tabela = {}
    for w in wyniki:
        wiersz = tabela.setdefault(w["typ"], dict.fromkeys(("dokumentow",) + STATUSY, 0))
        wiersz["dokumentow"] += 1
        wiersz[w["status"]] += 1
    return dict(sorted(tabela.items(), key=lambda kv: (-kv[1]["dokumentow"], kv[0])))


def sprawdz_partie(dokumenty, tryb_vat=VAT_PER_STAWKA, mapowanie=None, pomin_typy=(), dopusc_ujemne=False):
    """Zwraca (lista wyników per dokument, podsumowanie). Błędny dokument nie przerywa partii."""
    scal_mapowanie(mapowanie)  # wczesny błąd przy złym mapowaniu
    pomin = zbior_typow(pomin_typy)
    wyniki = [sprawdz_dokument(d, i, tryb_vat, mapowanie, pomin, dopusc_ujemne) for i, d in enumerate(dokumenty)]
    kody = Counter()
    for w in wyniki:
        kody.update({n["kod"] for n in w["niespojnosci"]} | {etykieta_kodu(c) for c in w["przyczyny"]})
        if w["blad"]:
            kody[w["blad"]["kod"]] += 1
    porownane = [w for w in wyniki if w["tryb_pasujacy"] is not None]
    rozklad = Counter(w["tryb_pasujacy"] for w in porownane)
    najwieksze = sorted((w for w in wyniki if w["max_roznica"] > 0 and w["status"] not in ("pominiety", "drobiazg")), key=lambda w: (-w["max_roznica"], w["indeks"]))
    podsumowanie = {
        "liczba_dokumentow": len(wyniki),
        "spojne": sum(1 for w in wyniki if w["status"] == "spojny"),
        "pominiete": sum(1 for w in wyniki if w["status"] == "pominiety"),
        "status": {s: sum(1 for w in wyniki if w["status"] == s) for s in STATUSY},
        "pominiete_typy": nazwy_typow(pomin_typy),
        "wg_typu": _wg_typu(wyniki),
        "z_niespojnosciami": sum(1 for w in wyniki if w["niespojnosci"]),
        "z_bledem": sum(1 for w in wyniki if w["blad"]),
        "z_problemem": sum(1 for w in wyniki if ma_problem(w)),
        "vat_wyliczony_zgodny": sum(1 for w in wyniki if _ma_kod(w, VAT_WYLICZONY_ZGODNY)),
        "vat_wyliczony_rozny": sum(1 for w in wyniki if _ma_kod(w, VAT_WYLICZONY_ROZNY)),
        "spojne_z_wyliczonym_vat": sum(1 for w in wyniki
                                       if w["status"] == "spojny" and _ma_kod(w, VAT_WYLICZONY_ZGODNY)),
        "wymaga_uwagi": sum(1 for w in wyniki if w["status"] in ("niespojny", "blad")),
        "kody": dict(sorted(kody.items(), key=lambda kv: (-kv[1], kv[0]))),
        "porownanych": len(porownane),
        "dopasowanie": {k: rozklad.get(k, 0) for k in DOPASOWANIA},
        "pasuje_per_stawka": rozklad.get("oba", 0) + rozklad.get("per_stawka", 0),
        "pasuje_per_pozycja": rozklad.get("oba", 0) + rozklad.get("per_pozycja", 0),
        "najwieksze_indeksy": [w["indeks"] for w in najwieksze],
    }
    return wyniki, podsumowanie


def _gr(kwota):
    return "%s (%s gr)" % (format_kwoty(kwota), format_bez_zer(kwota.scaleb(2)))


def _tabela_typow(wg_typu):
    naglowki = ("typ", "dokumentów", "spójne", "drobiazg", "niepełne", "niespójne", "błędne", "pominięte")
    wiersze = [(typ, w["dokumentow"], w["spojny"], w["drobiazg"], w["niepelny"], w["niespojny"], w["blad"],
                w["pominiety"]) for typ, w in wg_typu.items()]
    szer = [max(len(str(r[i])) for r in wiersze + [naglowki]) for i in range(len(naglowki))]
    def linia(r):
        return "  " + "  ".join(str(c).ljust(szer[0]) if i == 0 else str(c).rjust(szer[i])
                                for i, c in enumerate(r))
    return ["Wg typu dokumentu:", linia(naglowki)] + [linia(r) for r in wiersze]


def linie_do_zrobienia(p):
    """Dokładnie 5 linii na początek raportu: co wymaga decyzji, a co można zignorować."""
    s = p["status"]
    zgodne = (" (w tym VAT wyliczony z pozycji i zgodny z nagłówkiem: %d)" % p["spojne_z_wyliczonym_vat"]
              if p["spojne_z_wyliczonym_vat"] else "")
    pominiete = ("Pominięte typy (%s): %d" % (", ".join(p["pominiete_typy"]), p["pominiete"])
                 if p["pominiete_typy"] else "Pominięte typy: brak (patrz --pomin-typy)")
    return [
        "Do sprawdzenia: %d (niespójne: %d, błędne: %d)" % (p["wymaga_uwagi"], s["niespojny"], s["blad"]),
        "Tylko drobiazgi (POLGROSZ): %d" % s["drobiazg"],
        "Niepełne dane (brak VAT w pozycjach): %d" % s["niepelny"],
        pominiete,
        "Bez uwag: %d z %d dokumentów%s" % (s["spojny"], p["liczba_dokumentow"], zgodne),
    ]


def tekst_podsumowania(podsumowanie, wyniki, max_przyklady=10):
    p = podsumowanie
    linie = linie_do_zrobienia(p) + [
        "",
        "Sprawdzono dokumentów: %d (w tym pominięto: %d)" % (p["liczba_dokumentow"], p["pominiete"]),
        "  spójnych (bez przyczyn):              %d" % p["spojne"],
        "  z niespójnością zapisanych sum:       %d" % p["z_niespojnosciami"],
        "  z błędem (walidacja/struktura):       %d" % p["z_bledem"],
        "  w raporcie (JSON/CSV): %d" % p["z_problemem"],
        "",
        "Rozkład kodów (liczba dokumentów):",
    ]
    linie += ["  %-40s %d" % (k, v) for k, v in p["kody"].items()] or ["  (brak)"]
    d = p["dopasowanie"]
    linie += [
        "",
        "Zgodność zapisanych sum z biblioteką (dokumenty bez błędu: %d):" % p["porownanych"],
        "  pasuje per_stawka:  %d" % p["pasuje_per_stawka"],
        "  pasuje per_pozycja: %d" % p["pasuje_per_pozycja"],
        "  rozkład: oba=%d, tylko per_stawka=%d, tylko per_pozycja=%d, żaden=%d"
        % (d["oba"], d["per_stawka"], d["per_pozycja"], d["zaden"]),
        "",
    ]
    linie += _tabela_typow(p["wg_typu"]) + [""]
    ostatnie = [wyniki[i] for i in p["najwieksze_indeksy"][:max_przyklady]]
    linie.append("Największe rozbieżności (%d z %d):" % (len(ostatnie), len(p["najwieksze_indeksy"])))
    for n, w in enumerate(ostatnie, 1):
        kody = sorted({x["kod"] for x in w["niespojnosci"]} | {etykieta_kodu(x) for x in w["przyczyny"]})
        opis = ", ".join(kody) if kody else "zgodność z biblioteką: %s" % w["tryb_pasujacy"]
        linie.append("  %d. id=%s (indeks %d): %s - %s" % (n, w["id"], w["indeks"], _gr(w["max_roznica"]), opis))
    if not ostatnie:
        linie.append("  (brak)")
    return "\n".join(linie)


def _jako_json(x):
    if isinstance(x, Decimal):
        return format_kwoty(x)
    if isinstance(x, dict):
        return {k: _jako_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jako_json(v) for v in x]
    return x


def wynik_json(w):
    """Wpis raportu JSON: kwoty jako stringi; `id` bez zmian."""
    wpis = _jako_json({k: v for k, v in w.items() if k not in ("id", "pominieto_pozycje")})
    wpis["id"] = w["id"]
    wpis["pominieto_pozycje"] = w["pominieto_pozycje"]
    return wpis


def zapisz_json(sciezka, obiekt):
    """Zapis UTF-8/LF. Surowy Decimal (tylko `id` z pliku wejściowego) trafia jako liczba, nie string."""
    znacznik = "@@DEC_%s@@" % uuid.uuid4().hex

    def domyslnie(o):
        if isinstance(o, Decimal):
            return znacznik + format(o, "f")
        raise TypeError("nieserializowalne: %r" % (o,))

    tekst = json.dumps(obiekt, default=domyslnie, ensure_ascii=False, indent=2)
    tekst = tekst.replace('"%s' % znacznik, "\0").split("\0")
    # po znaczniku do najbliższego cudzysłowu stoi liczba
    wynik = [tekst[0]]
    for kawalek in tekst[1:]:
        liczba, reszta = kawalek.split('"', 1)
        wynik.append(liczba + reszta)
    with open(sciezka, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(wynik) + "\n")


KOLUMNY_CSV = ("indeks", "id", "typ", "status", "kody", "najwieksza_roznica", "tryb_vat_pasuje")


def _komorka_tekstowa(x):
    """Tekst do CSV; wartości zaczynające się od =, +, @ (i - przed nie-cyfrą) dostają apostrof,
    żeby arkusz nie wykonał ich jako formuły."""
    if x is None:
        return ""
    if isinstance(x, Decimal):
        t = format(x, "f")
    elif isinstance(x, (dict, list)):
        t = json.dumps(x, ensure_ascii=False)
    else:
        t = str(x)
    if t[:1] in ("=", "+", "@", "\t", "\r") or (t[:1] == "-" and not t[1:2].isdigit() and t[1:2] != "."):
        return "'" + t
    return t


def zapisz_csv(sciezka, wyniki):
    """Jedna linia na dokument z problemem. Separator ';', UTF-8 z BOM, końce linii CRLF i przecinek
    dziesiętny w kwotach - tak, żeby polski Excel otworzył plik dwuklikiem."""
    with open(sciezka, "w", encoding="utf-8-sig", newline="") as f:
        zapis = csv.writer(f, delimiter=";", lineterminator="\r\n")
        zapis.writerow(KOLUMNY_CSV)
        for w in wyniki:
            if not ma_problem(w):
                continue
            kody = sorted({n["kod"] for n in w["niespojnosci"]} | {etykieta_kodu(c) for c in w["przyczyny"]}
                          | ({w["blad"]["kod"]} if w["blad"] else set()))
            zapis.writerow([w["indeks"], _komorka_tekstowa(w["id"]), _komorka_tekstowa(w["typ"]), w["status"],
                            ", ".join(kody), format_kwoty(w["max_roznica"]).replace(".", ","),
                            w["tryb_pasujacy"] or ""])


def _parser():
    p = argparse.ArgumentParser(prog="python -m amounts_calc.check", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plik", help="JSON: lista dokumentów [{id, pozycje, suma_netto, suma_vat, suma_brutto}, ...]")
    p.add_argument("--tryb-vat", choices=TRYBY_VAT, default=VAT_PER_STAWKA, dest="tryb_vat",
                   help="tryb VAT zakładany przy sprawdzaniu zapisanych sum (domyślnie per_stawka)")
    p.add_argument("--json", dest="json_wyjscie", metavar="WYNIK.json",
                   help="zapisz listę dokumentów z problemami do pliku JSON")
    p.add_argument("--max-przyklady", type=int, default=10, metavar="N",
                   help="ile największych rozbieżności pokazać w podsumowaniu (domyślnie 10)")
    p.add_argument("--csv", dest="csv_wyjscie", metavar="WYNIK.csv",
                   help="zapisz dokumenty z problemami jako CSV (separator ';', UTF-8 z BOM - do Excela)")
    p.add_argument("--dopusc-ujemne", dest="dopusc_ujemne", action="store_true", default=True,
                   help="dopuszczaj ujemne ilości i ceny pozycji (domyślnie włączone)")
    p.add_argument("--nie-dopuszczaj-ujemnych", dest="dopusc_ujemne", action="store_false",
                   help="ujemna ilość/cena pozycji to błąd (ILOSC_UJEMNA / CENA_UJEMNA)")
    p.add_argument("--pomin-typy", dest="pomin_typy", default="", metavar="TYP1,TYP2",
                   help="typy dokumentów do pominięcia, np. KOREKTA,ROZ (wielkość liter bez znaczenia)")
    p.add_argument("--mapowanie", metavar="MAPOWANIE.json",
                   help="JSON z mapowaniem nazw pól (patrz amounts_calc.adapter)")
    return p


def main(argv=None):
    for strumien in (sys.stdout, sys.stderr):  # konsole Windows (cp1250/cp852) nie mogą się wywrócić na znakach
        if hasattr(strumien, "reconfigure"):
            strumien.reconfigure(errors="replace")
    args = _parser().parse_args(argv)
    if args.max_przyklady < 0:
        print("Błąd: --max-przyklady nie może być ujemne", file=sys.stderr)
        return 2
    try:
        dokumenty = wczytaj_plik_json(args.plik)
        mapowanie = wczytaj_plik_json(args.mapowanie) if args.mapowanie else None
        if not isinstance(dokumenty, list):
            raise ValueError("oczekiwano listy dokumentów (tablicy JSON), jest %s" % type(dokumenty).__name__)
        wyniki, podsumowanie = sprawdz_partie(dokumenty, args.tryb_vat, mapowanie, args.pomin_typy, args.dopusc_ujemne)
        if args.json_wyjscie:
            zapisz_json(args.json_wyjscie, [wynik_json(w) for w in wyniki if ma_problem(w)])
        if args.csv_wyjscie:
            zapisz_csv(args.csv_wyjscie, wyniki)
    except (OSError, ValueError, BladWalidacji) as e:  # json.JSONDecodeError i UnicodeDecodeError to ValueError
        print("Błąd: %s" % e, file=sys.stderr)
        return 2
    print(tekst_podsumowania(podsumowanie, wyniki, args.max_przyklady))
    return 1 if podsumowanie["wymaga_uwagi"] else 0


if __name__ == "__main__":
    sys.exit(main())
