"""Oferty i zamówienia: pozycje z ceną zakupu i narzutem, zestawy z własnym narzutem/rabatem.

Funkcje budujące dane dla klasyfikacja.py na podstawie kanonicznych pozycji (słowniki z adaptera) i
wyniku oblicz(). Nie rzucają z powodu danych: pozycję, której nie da się ocenić, pomijają.
"""
from decimal import Decimal, DecimalException, localcontext

from . import marza
from .bledy import ALTERNATYWY_W_SUMIE, ZESTAW_Z_NARZUTEM, BladWalidacji
from .config import DOMYSLNA, KONTEKST
from .hierarchia import liscie_pod
from .klasyfikacja import PROG
from .obliczenia import oblicz
from .stawki import do_decimal
from .zestawy import grupy_alternatyw, rozwin, sumy_pozycji, wiersze_z_pozycji, wklad, wybierz_alternatywy

_100 = 100


def ma_narzut(p):
    """Pozycja ma cenę zakupu i narzut albo marżę => cena sprzedaży wynika z nich (jak w oblicz())."""
    return p.get("cena_zakupu_jedn") is not None and (p.get("narzut_proc") is not None
                                                      or p.get("marza_proc") is not None)


def _wartosc(p, cena, rabat, rabat_dok, dopusc_ujemne):
    """Wartość netto pozycji dla danej ceny jednostkowej i rabatu pozycji (rabat dokumentu jak w dokumencie)."""
    try:
        d = oblicz([{"ilosc": p.get("ilosc"), "cena_netto_jedn": cena, "rabat_proc": rabat,
                     "stawka_vat": p.get("stawka_vat")}], rabat_dokumentu_proc=rabat_dok, dopusc_ujemne=dopusc_ujemne)
    except (BladWalidacji, DecimalException):
        return None
    return d.pozycje[0].netto


def _wyjasnienie(p, zakup, cena_sp, rabat, zapisane, rabat_dok, dopusc_ujemne):
    """Który z pominiętych czynników (narzut, rabat) tłumaczy zapisaną wartość."""
    kandydaci = (("narzut nie został zastosowany", zakup, rabat),
                 ("rabat nie został zastosowany", cena_sp, 0),
                 ("nie zastosowano ani narzutu, ani rabatu", zakup, 0))
    for opis, cena, r in kandydaci:
        w = _wartosc(p, cena, r, rabat_dok, dopusc_ujemne)
        if w is not None and abs(w - zapisane) <= PROG:
            return opis
    return None


def _narzut_wynikowy(p, zakup, rabat, rabat_dok, zapisane, konf):
    """Narzut %, jaki wynikałby z zapisanej wartości (przy zadanej ilości, rabatach i cenie zakupu)."""
    try:
        ilosc = do_decimal(p["ilosc"], "ilosc")
        czynnik = ilosc * (1 - do_decimal(rabat, "rabat") / _100) * (1 - do_decimal(rabat_dok, "rabat") / _100)
        if czynnik == 0 or zakup == 0:
            return None
        return konf.procent((zapisane / czynnik / zakup - 1) * _100)
    except (BladWalidacji, DecimalException, KeyError):
        return None


def rekordy_narzutu(pozycje, wiersze, obliczony, rabat_dok=0, dopusc_ujemne=False, konf=DOMYSLNA):
    """Rekordy dla przyczyny_ilosc_x_cena_narzut: jeden na pozycję (liść) z ceną zakupu i narzutem.

    pozycje: kanoniczne pozycje dokumentu; wiersze: zapisane kwoty (indeks, id, zestaw, netto);
    obliczony: DokumentWynik z oblicz() (cena sprzedaży z zakupu i narzutu)."""
    rekordy = []
    for w in wiersze:
        i = w["indeks"]
        if w["zestaw"] or w["netto"] is None or not ma_narzut(pozycje[i]):
            continue
        p = pozycje[i]
        try:
            zakup = do_decimal(p["cena_zakupu_jedn"], "cena_zakupu_jedn")
            cena_sp = marza.cena_sprzedazy(zakup, p.get("narzut_proc"), p.get("marza_proc"), konf, dopusc_ujemne)
            cena_netto = p.get("cena_netto_jedn")
            cena_netto_d = do_decimal(cena_netto, "cena_netto_jedn") if cena_netto is not None else None
        except (BladWalidacji, DecimalException):
            continue
        rabat = p.get("rabat_proc", 0)
        oczekiwane = obliczony.pozycje[i].netto
        zapisane = w["netto"]
        # cena_netto_jedn równa cenie zakupu to w takich danych po prostu cena zakupu, nie zapisana cena sprzedaży
        cena_zapisana = cena_netto_d if cena_netto_d is not None and abs(cena_netto_d - zakup) > PROG else None
        naiwne = _wartosc(p, cena_netto, rabat, rabat_dok, dopusc_ujemne) if cena_netto is not None else None
        r = {"indeks": i, "id": w["id"], "zapisane": zapisane, "oczekiwane": oczekiwane, "cena_oczekiwana": cena_sp,
             "cena_zapisana": cena_zapisana, "naiwne": naiwne, "wyjasnienie": None, "narzut_wynikowy": None}
        if abs(zapisane - oczekiwane) > PROG:
            r["wyjasnienie"] = _wyjasnienie(p, zakup, cena_sp, rabat, zapisane, rabat_dok, dopusc_ujemne)
            r["narzut_wynikowy"] = _narzut_wynikowy(p, zakup, rabat, rabat_dok, zapisane, konf)
        rekordy.append(r)
    return rekordy


# ---- zestawy (pozycje nadrzędne) z własnym narzutem lub rabatem ----

POLA_KWOT = ("netto", "vat", "brutto")


def czynnik_zestawu(p):
    """Mnożnik z własnego narzutu/marży i rabatu zestawu: (1 + narzut/100) albo 1/(1 - marża/100), razy
    (1 - rabat/100). None, gdy zestaw nie ma żadnego z nich (albo dane są niepoprawne)."""
    n, m, r = p.get("narzut_proc"), p.get("marza_proc"), p.get("rabat_proc")
    if n is None and m is None and r is None:
        return None
    if n is not None and m is not None:
        return None
    try:
        with localcontext(KONTEKST):
            czynnik = Decimal(1)
            if n is not None:
                czynnik *= 1 + do_decimal(n, "narzut_proc") / 100
            if m is not None:
                czynnik /= 1 - do_decimal(m, "marza_proc") / 100
            if r is not None:
                czynnik *= 1 - do_decimal(r, "rabat_proc") / 100
            return czynnik
    except (BladWalidacji, DecimalException, ZeroDivisionError):
        return None


def zestawy_z_narzutem(pozycje, zapisany, dzieci, konf=DOMYSLNA):
    """Zestawy, których zapisane kwoty różnią się od N x sumy dzieci dokładnie o własny narzut/rabat.

    pozycje: kanoniczne pozycje; zapisany: DokumentWynik z zapisanymi kwotami (zestawy mają kwoty);
    dzieci: wynik zbuduj_hierarchie. Zwraca listę {indeks, id, narzut_proc, marza_proc, rabat_proc, czynnik,
    suma_dzieci, zapisane, oczekiwane, roznica} (kwoty netto) tylko dla zestawów z różnicą, którą narzut/rabat
    tłumaczy: netto w granicach 0,01, a VAT i brutto w granicach 0,01 na każdy liść (zaokrąglenia dzieci)."""
    wynik = []
    oczekiwane = rozwin(wiersze_z_pozycji(zapisany.pozycje), dzieci, zapisany.ilosc_zestawu, konf)["oczekiwane"]
    for i in sorted(dzieci):
        p = pozycje[i]
        czynnik = czynnik_zestawu(p)
        if czynnik is None:
            continue
        liscie = [zapisany.pozycje[j] for j in liscie_pod(i, dzieci)]
        wiersz = zapisany.pozycje[i]
        suma = oczekiwane[i]       # N x suma dzieci (dla N = 1 zwykła suma dzieci)
        zapis = {k: getattr(wiersz, k) for k in POLA_KWOT}
        if all(zapis[k] == suma[k] for k in POLA_KWOT):
            continue          # brak różnicy do wytłumaczenia
        oczek = {k: konf.kwota(suma[k] * czynnik) for k in POLA_KWOT}
        tol = {"netto": PROG, "vat": PROG * (len(liscie) + 1), "brutto": PROG * (len(liscie) + 1)}
        if all(abs(zapis[k] - oczek[k]) <= tol[k] for k in POLA_KWOT):
            wynik.append({"indeks": i, "id": p.get("id"), "narzut_proc": p.get("narzut_proc"),
                          "marza_proc": p.get("marza_proc"), "rabat_proc": p.get("rabat_proc"),
                          "czynnik": czynnik.quantize(Decimal("0.000001")), "suma_dzieci": suma["netto"],
                          "zapisane": zapis["netto"], "oczekiwane": oczek["netto"],
                          "roznica": zapis["netto"] - suma["netto"], "_delta": {k: zapis[k] - suma[k] for k in POLA_KWOT}})
    return wynik


def delta_zestawow_najwyzszego_poziomu(zestawy, pozycje):
    """Suma różnic (zapisane - suma liści) wyjaśnionych zestawów najwyższego poziomu (bez rodzica)."""
    delta = {k: Decimal(0) for k in POLA_KWOT}
    for z in zestawy:
        if pozycje[z["indeks"]].get("parent_id") is None:
            for k in POLA_KWOT:
                delta[k] += z["_delta"][k]
    return delta


def przyczyna_zestaw_z_narzutem(zestawy, naglowek_uwzglednia):
    """Przyczyna informacyjna: różnica zestawu względem sumy dzieci wynika z jego własnego narzutu/rabatu."""
    return {"kod": ZESTAW_Z_NARZUTEM, "pole": "netto", "roznica": None, "informacja": True, "liczba": len(zestawy),
            "opis": "kwoty pozycji nadrzędnej różnią się od sumy dzieci zgodnie z jej własnym narzutem/rabatem",
            "naglowek_uwzglednia_zestawy": naglowek_uwzglednia,
            "zestawy": [{k: v for k, v in z.items() if not k.startswith("_")} for z in zestawy]}


# ---- alternatywy (opcje wzajemnie wykluczające się) ----

def _blizej_wszystkich(naglowek, wszystkie, wlaczone, wiersze, dzieci, rozw, pola):
    """Nagłówek różni się od baza + WSZYSTKIE opcje (np. o błąd narzutu), ale jest tą sumą wyraźnie bliżej niż
    wybraną kombinacją: odległość od sumy ze wszystkimi < od sumy z wybraną i nie więcej niż 25% dodanych kwot.
    Porównanie po kwotach zapisanych w pozycjach."""
    wybrana = sumy_pozycji(wiersze, dzieci, rozw, frozenset(wlaczone))
    baza = sumy_pozycji(wiersze, dzieci, rozw, frozenset())
    d_wszystkie = sum((abs(naglowek[f] - wszystkie[f]) for f in pola), Decimal(0))
    d_wybrana = sum((abs(naglowek[f] - wybrana[f]) for f in pola), Decimal(0))
    dodane = sum((abs(wszystkie[f] - baza[f]) for f in pola), Decimal(0))
    return d_wszystkie < d_wybrana and d_wszystkie <= Decimal("0.25") * dodane


def przyczyna_alternatyw(wiersze, dzieci, naglowek, wlaczone, uwzglednij_ilosc=True, konf=DOMYSLNA):
    """Informacja ALTERNATYWY_W_SUMIE: lista opcji (pozycje najwyższego poziomu z `alternatywa`) per grupa,
    które z nich weszły do sum i czy nagłówek jest z tym zgodny.

    naglowek: {pole: Decimal|None}. `dopasowanie`: "zgodne" - baza + wybrane opcje = nagłówek; "najblizsze" -
    żadna kombinacja (po jednej lub żadnej opcji z grupy) nie pasuje. `naglowek_zawiera_wszystkie_opcje`: nagłówek
    = baza + WSZYSTKIE opcje, czyli alternatywy zostały po cichu dodane do sumy mimo, że wykluczają się."""
    rozw = rozwin(wiersze, dzieci, uwzglednij_ilosc, konf)
    grupy = grupy_alternatyw(wiersze, rozw["rodzic"])
    if not grupy:
        return None
    _, dopasowanie = wybierz_alternatywy(wiersze, dzieci, rozw, naglowek)
    wszystkie = sumy_pozycji(wiersze, dzieci, rozw, frozenset(i for idx in grupy.values() for i in idx))
    pola = [f for f in POLA_KWOT if naglowek.get(f) is not None and wszystkie[f] is not None]
    zawiera_wszystkie = (dopasowanie != "zgodne" and any(len(idx) > 1 for idx in grupy.values()) and bool(pola)
                         and (all(abs(naglowek[f] - wszystkie[f]) <= PROG for f in pola)
                              or _blizej_wszystkich(naglowek, wszystkie, wlaczone, wiersze, dzieci, rozw, pola)))
    return {"kod": ALTERNATYWY_W_SUMIE, "pole": None, "roznica": None, "informacja": True, "raportuj": True,
            "opis": "pozycje typu opcja wykluczają się wzajemnie: do sumy wchodzi co najwyżej jedna z grupy",
            "dopasowanie": dopasowanie, "naglowek_zawiera_wszystkie_opcje": zawiera_wszystkie,
            "grupy": [{"grupa": g, "pozycje": [dict({"indeks": i, "id": wiersze[i].get("id"), "wliczona": i in wlaczone,
                                                      "zestaw": i in dzieci}, **wklad(i, wiersze, dzieci, rozw))
                                                for i in idx]} for g, idx in grupy.items()]}
