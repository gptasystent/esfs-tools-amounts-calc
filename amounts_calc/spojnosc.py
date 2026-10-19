"""sprawdz_spojnosc(dokument) i porownaj(a, b).

Oba przyjmują DokumentWynik albo słownik (patrz model.dokument_z_slownika), więc działają
też na dokumentach wczytanych z bazy i na wynikach `oblicz`.
"""
from decimal import Decimal, localcontext

from .bledy import (NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI,
                    SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, SUMA_STAWEK_ROZNA_OD_DOKUMENTU,
                    VAT_STAWKI_ROZNY_OD_SUMY)
from .config import DOMYSLNA, KONTEKST, TRYB_BRUTTO, VAT_PER_STAWKA
from .model import dokument_z_dokumentem, podsumuj_stawki
from .stawki import wartosc_stawki

_100 = Decimal(100)
_POLA_KWOT = ("netto", "vat", "brutto")


def _wpis(kod, zakres, pole, oczekiwano, jest, opis):
    return {"kod": kod, "zakres": zakres, "pole": pole, "oczekiwano": oczekiwano, "jest": jest,
            "roznica": jest - oczekiwano, "opis": opis}


def _vat_z_sumy(sumy, tryb, konf):
    """VAT, jaki wynika z sumy stawki (netto lub brutto zależnie od trybu dokumentu)."""
    r = wartosc_stawki(sumy.stawka_vat)
    if tryb == TRYB_BRUTTO:
        return sumy.brutto - konf.kwota(sumy.brutto / (1 + r / _100))
    return konf.kwota(sumy.netto * r / _100)


def sprawdz_spojnosc(dokument, tryb_vat=None, konfiguracja=DOMYSLNA):
    """Zwraca listę niespójności (pusta = dokument spójny). Każdy wpis to słownik:
    kod, zakres, pole, oczekiwano, jest, roznica (jest - oczekiwano), opis.

    Sprawdzane:
      SUMA_POZYCJI_ROZNA_OD_DOKUMENTU       suma pozycji != suma dokumentu
      NETTO_PLUS_VAT_ROZNE_OD_BRUTTO        netto + vat != brutto (pozycja, stawka, dokument)
      PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI  wiersz podsumowania stawki != suma jej pozycji
      SUMA_STAWEK_ROZNA_OD_DOKUMENTU        suma wierszy podsumowania != suma dokumentu
      VAT_STAWKI_ROZNY_OD_SUMY              VAT stawki != VAT policzony z sumy stawki
                                            (tylko dla tryb_vat == per_stawka; domyślnie
                                            bierze tryb_vat dokumentu, a gdy nieznany - pomija)
    """
    dok = dokument_z_dokumentem(dokument)
    konf = konfiguracja
    tryb_vat = tryb_vat if tryb_vat is not None else dok.tryb_vat
    wyniki = []

    with localcontext(KONTEKST):
        # netto + vat == brutto: pozycje, stawki, dokument
        for p in dok.pozycje:
            if p.netto + p.vat != p.brutto:
                wyniki.append(_wpis(NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "pozycja:%d" % p.indeks, "brutto",
                                    p.netto + p.vat, p.brutto, "netto + vat != brutto w pozycji"))
        for s in dok.podsumowanie:
            if s.netto + s.vat != s.brutto:
                wyniki.append(_wpis(NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "stawka:%s" % s.stawka_vat, "brutto",
                                    s.netto + s.vat, s.brutto, "netto + vat != brutto w stawce"))
        if dok.suma_netto + dok.suma_vat != dok.suma_brutto:
            wyniki.append(_wpis(NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, "dokument", "suma_brutto",
                                dok.suma_netto + dok.suma_vat, dok.suma_brutto,
                                "suma_netto + suma_vat != suma_brutto"))

        # suma pozycji == suma dokumentu
        z_pozycji = podsumuj_stawki(dok.pozycje)
        for pole in _POLA_KWOT:
            suma = sum((getattr(p, pole) for p in dok.pozycje), Decimal(0))
            jest = getattr(dok, "suma_" + pole)
            if suma != jest:
                wyniki.append(_wpis(SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, "dokument", "suma_" + pole, suma, jest,
                                    "suma pozycji != suma dokumentu"))

        # podsumowanie stawek vs pozycje i vs dokument
        wiersze = {s.stawka_vat: s for s in dok.podsumowanie}
        oczekiwane = {s.stawka_vat: s for s in z_pozycji}
        for stawka in sorted(set(wiersze) | set(oczekiwane)):
            for pole in _POLA_KWOT:
                oczek = getattr(oczekiwane[stawka], pole) if stawka in oczekiwane else Decimal(0)
                jest = getattr(wiersze[stawka], pole) if stawka in wiersze else Decimal(0)
                if oczek != jest:
                    wyniki.append(_wpis(PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI, "stawka:%s" % stawka, pole,
                                        oczek, jest, "podsumowanie stawki != suma jej pozycji"))
        for pole in _POLA_KWOT:
            suma = sum((getattr(s, pole) for s in dok.podsumowanie), Decimal(0))
            jest = getattr(dok, "suma_" + pole)
            if suma != jest:
                wyniki.append(_wpis(SUMA_STAWEK_ROZNA_OD_DOKUMENTU, "dokument", "suma_" + pole, suma, jest,
                                    "suma podsumowania stawek != suma dokumentu"))

        # VAT stawki vs VAT z sumy (tylko gdy dokument liczono per stawka)
        if tryb_vat == VAT_PER_STAWKA:
            for s in dok.podsumowanie:
                oczek = _vat_z_sumy(s, dok.tryb, konf)
                if oczek != s.vat:
                    wyniki.append(_wpis(VAT_STAWKI_ROZNY_OD_SUMY, "stawka:%s" % s.stawka_vat, "vat",
                                        oczek, s.vat, "VAT stawki != VAT policzony z sumy stawki"))
    return wyniki


def _roznica(a, b):
    if any(isinstance(x, (Decimal, int)) for x in (a, b)):
        return (b if b is not None else 0) - (a if a is not None else 0)
    return None


def porownaj(dokument_a, dokument_b):
    """Lista rozbieżności {pole, a, b, roznica} (roznica = b - a; None dla pól nienumerycznych).
    Pusta lista = dokumenty zgodne co do kwot, walut, liczby pozycji i podsumowania stawek.
    """
    a, b = dokument_z_dokumentem(dokument_a), dokument_z_dokumentem(dokument_b)
    wyniki = []

    def dodaj(pole, va, vb):
        if va != vb:
            wyniki.append({"pole": pole, "a": va, "b": vb, "roznica": _roznica(va, vb)})

    dodaj("waluta", a.waluta, b.waluta)
    for pole in _POLA_KWOT:
        dodaj("suma_" + pole, getattr(a, "suma_" + pole), getattr(b, "suma_" + pole))
    sa = {s.stawka_vat: s for s in a.podsumowanie}
    sb = {s.stawka_vat: s for s in b.podsumowanie}
    for stawka in sorted(set(sa) | set(sb), key=lambda x: (len(x), x)):
        for pole in _POLA_KWOT:
            dodaj("stawka:%s.%s" % (stawka, pole),
                  getattr(sa[stawka], pole) if stawka in sa else None,
                  getattr(sb[stawka], pole) if stawka in sb else None)
    dodaj("liczba_pozycji", len(a.pozycje), len(b.pozycje))
    for pa, pb in zip(a.pozycje, b.pozycje):
        dodaj("pozycje[%d].stawka_vat" % pa.indeks, pa.stawka_vat, pb.stawka_vat)
        for pole in _POLA_KWOT:
            dodaj("pozycje[%d].%s" % (pa.indeks, pole), getattr(pa, pole), getattr(pb, pole))
    return wyniki
