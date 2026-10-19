"""Model danych: wejście (Pozycja) i wynik (PozycjaWynik, PodsumowanieStawki, DokumentWynik)."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .bledy import BRAK_POLA, BladWalidacji
from .config import TRYB_NETTO, TRYBY
from .stawki import KOLEJNOSC_STAWEK, do_decimal, normalizuj_stawke


@dataclass(frozen=True)
class Pozycja:
    """Wejściowa pozycja dokumentu.

    W trybie od netto podaj `cena_netto_jedn` (albo `koszt_zakupu_jedn` + narzut/marża dokumentu),
    w trybie od brutto - `cena_brutto_jedn`. Liczby: Decimal/int/str, nigdy float.
    """
    ilosc: object
    cena_netto_jedn: object = None
    rabat_proc: object = 0
    stawka_vat: object = 23
    cena_brutto_jedn: object = None
    koszt_zakupu_jedn: object = None


def pozycja_z_slownika(d):
    if isinstance(d, Pozycja):
        return d
    for pole in ("ilosc", "stawka_vat"):
        if pole not in d:
            raise BladWalidacji(BRAK_POLA, pole, "brak pola w pozycji")
    return Pozycja(
        ilosc=d["ilosc"], cena_netto_jedn=d.get("cena_netto_jedn"), rabat_proc=d.get("rabat_proc", 0),
        stawka_vat=d["stawka_vat"], cena_brutto_jedn=d.get("cena_brutto_jedn"),
        koszt_zakupu_jedn=d.get("koszt_zakupu_jedn"),
    )


@dataclass(frozen=True)
class PozycjaWynik:
    indeks: int
    ilosc: Decimal
    cena_po_rabacie: Decimal  # netto w trybie od netto, brutto w trybie od brutto
    rabat_proc: Decimal
    stawka_vat: str
    netto: Decimal
    vat: Decimal
    brutto: Decimal


@dataclass(frozen=True)
class PodsumowanieStawki:
    stawka_vat: str
    netto: Decimal
    vat: Decimal
    brutto: Decimal


@dataclass(frozen=True)
class DokumentWynik:
    waluta: str
    tryb: str
    tryb_vat: str
    pozycje: Tuple[PozycjaWynik, ...]
    podsumowanie: Tuple[PodsumowanieStawki, ...]
    suma_netto: Decimal
    suma_vat: Decimal
    suma_brutto: Decimal
    # Różnica: suma VAT liczona niezależnie per pozycja minus suma VAT liczona per stawka na sumie.
    # Pokazuje, ile groszy "kosztuje" wybór trybu VAT; niezależna od wybranego trybu.
    rozbieznosc_vat: Decimal = Decimal(0)

    def stawka(self, etykieta) -> Optional[PodsumowanieStawki]:
        for p in self.podsumowanie:
            if p.stawka_vat == etykieta:
                return p
        return None

    def do_slownika(self):
        """Słownik z kwotami jako str (gotowy pod JSON); odwracalny przez dokument_z_slownika."""
        return {
            "waluta": self.waluta, "tryb": self.tryb, "tryb_vat": self.tryb_vat,
            "pozycje": [{"stawka_vat": p.stawka_vat, "ilosc": str(p.ilosc), "netto": str(p.netto),
                         "vat": str(p.vat), "brutto": str(p.brutto)} for p in self.pozycje],
            "podsumowanie": [{"stawka_vat": s.stawka_vat, "netto": str(s.netto), "vat": str(s.vat),
                              "brutto": str(s.brutto)} for s in self.podsumowanie],
            "suma_netto": str(self.suma_netto), "suma_vat": str(self.suma_vat),
            "suma_brutto": str(self.suma_brutto), "rozbieznosc_vat": str(self.rozbieznosc_vat),
        }


def podsumuj_stawki(pozycje):
    """Grupuje pozycje (z polami stawka_vat/netto/vat/brutto) po stawce, w stałej kolejności."""
    sumy = {}
    for p in pozycje:
        n, v, b = sumy.get(p.stawka_vat, (Decimal(0), Decimal(0), Decimal(0)))
        sumy[p.stawka_vat] = (n + p.netto, v + p.vat, b + p.brutto)
    return tuple(PodsumowanieStawki(s, *sumy[s]) for s in KOLEJNOSC_STAWEK if s in sumy)


def dokument_z_dokumentem(dok):
    """Akceptuje DokumentWynik albo słownik (np. zbudowany z wiersza bazy) i zwraca DokumentWynik."""
    if isinstance(dok, DokumentWynik):
        return dok
    return dokument_z_slownika(dok)


def dokument_z_slownika(d):
    """Buduje DokumentWynik z zewnętrznych danych bez przeliczania - do sprawdz_spojnosc/porownaj.

    Wymagane: pozycje[{stawka_vat, netto, vat, brutto}], suma_netto, suma_vat, suma_brutto.
    Opcjonalne: waluta, tryb ('netto'), tryb_vat, podsumowanie[{stawka_vat, netto, vat, brutto}].
    """
    for pole in ("pozycje", "suma_netto", "suma_vat", "suma_brutto"):
        if pole not in d:
            raise BladWalidacji(BRAK_POLA, pole, "brak pola w dokumencie")
    pozycje = []
    for i, p in enumerate(d["pozycje"]):
        for pole in ("stawka_vat", "netto", "vat", "brutto"):
            if pole not in p:
                raise BladWalidacji(BRAK_POLA, "pozycje[%d].%s" % (i, pole), "brak pola")
        pozycje.append(PozycjaWynik(
            indeks=i, ilosc=do_decimal(p.get("ilosc", 1), "pozycje[%d].ilosc" % i),
            cena_po_rabacie=Decimal(0), rabat_proc=Decimal(0),
            stawka_vat=normalizuj_stawke(p["stawka_vat"], "pozycje[%d].stawka_vat" % i),
            netto=do_decimal(p["netto"], "pozycje[%d].netto" % i),
            vat=do_decimal(p["vat"], "pozycje[%d].vat" % i),
            brutto=do_decimal(p["brutto"], "pozycje[%d].brutto" % i)))
    pozycje = tuple(pozycje)
    if d.get("podsumowanie") is not None:
        podsumowanie = tuple(
            PodsumowanieStawki(normalizuj_stawke(s["stawka_vat"], "podsumowanie.stawka_vat"),
                               do_decimal(s["netto"], "podsumowanie.netto"),
                               do_decimal(s["vat"], "podsumowanie.vat"),
                               do_decimal(s["brutto"], "podsumowanie.brutto"))
            for s in d["podsumowanie"])
    else:
        podsumowanie = podsumuj_stawki(pozycje)
    tryb = d.get("tryb", TRYB_NETTO)
    if tryb not in TRYBY:
        raise BladWalidacji("NIEPOPRAWNY_TRYB", "tryb", "dozwolone: %s" % (TRYBY,))
    return DokumentWynik(
        waluta=d.get("waluta", "PLN"), tryb=tryb, tryb_vat=d.get("tryb_vat", ""),
        pozycje=pozycje, podsumowanie=podsumowanie,
        suma_netto=do_decimal(d["suma_netto"], "suma_netto"),
        suma_vat=do_decimal(d["suma_vat"], "suma_vat"),
        suma_brutto=do_decimal(d["suma_brutto"], "suma_brutto"))
