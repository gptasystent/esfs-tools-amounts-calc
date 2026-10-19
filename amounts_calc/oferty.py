"""Oferty i zamówienia: pozycje z ceną zakupu i narzutem, zestawy z własnym narzutem/rabatem.

Funkcje budujące dane dla klasyfikacja.py na podstawie kanonicznych pozycji (słowniki z adaptera) i
wyniku oblicz(). Nie rzucają z powodu danych: pozycję, której nie da się ocenić, pomijają.
"""
from decimal import DecimalException

from . import marza
from .bledy import BladWalidacji
from .config import DOMYSLNA, KONTEKST
from .klasyfikacja import PROG
from .obliczenia import oblicz
from .stawki import do_decimal

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
