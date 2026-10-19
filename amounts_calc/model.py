"""Model danych: wejście (Pozycja) i wynik (PozycjaWynik, PodsumowanieStawki, DokumentWynik)."""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .bledy import BRAK_POLA, NIEPOPRAWNA_STRUKTURA, BladWalidacji
from .config import TRYB_NETTO, TRYBY
from .hierarchia import liscie_pod, zbuduj_hierarchie
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
    id: object = None         # identyfikator pozycji - potrzebny tylko, gdy inne pozycje mają ją za rodzica
    parent_id: object = None  # id pozycji nadrzędnej (zestawu); patrz hierarchia.py


def pozycja_z_slownika(d):
    if isinstance(d, Pozycja):
        return d
    for pole in ("ilosc", "stawka_vat"):
        if pole not in d:
            raise BladWalidacji(BRAK_POLA, pole, "brak pola w pozycji")
    return Pozycja(
        ilosc=d["ilosc"], cena_netto_jedn=d.get("cena_netto_jedn"), rabat_proc=d.get("rabat_proc", 0),
        stawka_vat=d["stawka_vat"], cena_brutto_jedn=d.get("cena_brutto_jedn"),
        koszt_zakupu_jedn=d.get("koszt_zakupu_jedn"), id=d.get("id"), parent_id=d.get("parent_id"),
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
    id: object = None
    parent_id: object = None
    zestaw: bool = False  # wiersz zbiorczy pozycji nadrzędnej: suma dzieci, nie wchodzi do sum dokumentu


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
            "pozycje": [dict({"stawka_vat": p.stawka_vat, "ilosc": str(p.ilosc), "netto": str(p.netto),
                              "vat": str(p.vat), "brutto": str(p.brutto)},
                             **{k: v for k, v in (("id", p.id), ("parent_id", p.parent_id)) if v is not None})
                        for p in self.pozycje],
            "podsumowanie": [{"stawka_vat": s.stawka_vat, "netto": str(s.netto), "vat": str(s.vat),
                              "brutto": str(s.brutto)} for s in self.podsumowanie],
            "suma_netto": str(self.suma_netto), "suma_vat": str(self.suma_vat),
            "suma_brutto": str(self.suma_brutto), "rozbieznosc_vat": str(self.rozbieznosc_vat),
        }


def podsumuj_stawki(pozycje):
    """Grupuje pozycje (z polami stawka_vat/netto/vat/brutto) po stawce, w stałej kolejności."""
    sumy = {}
    for p in pozycje:
        if p.zestaw:
            continue
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
    Opcjonalne: waluta, tryb ('netto'), tryb_vat, podsumowanie[{stawka_vat, netto, vat, brutto}],
    w pozycjach id i parent_id (zestawy; kwoty pozycji nadrzędnej mogą być pominięte).
    """
    for pole in ("pozycje", "suma_netto", "suma_vat", "suma_brutto"):
        if pole not in d:
            raise BladWalidacji(BRAK_POLA, pole, "brak pola w dokumencie")
    surowe = list(d["pozycje"])
    for i, p in enumerate(surowe):
        if not isinstance(p, Mapping):
            raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "pozycje[%d]" % i, "pozycja musi być słownikiem")
    dzieci = zbuduj_hierarchie([(p.get("id"), p.get("parent_id")) for p in surowe])
    pozycje = [None] * len(surowe)

    def pozycja(i, p, netto, vat, brutto, zestaw):
        return PozycjaWynik(
            indeks=i, ilosc=do_decimal(p.get("ilosc", 1), "pozycje[%d].ilosc" % i),
            cena_po_rabacie=Decimal(0), rabat_proc=Decimal(0),
            stawka_vat=normalizuj_stawke(p["stawka_vat"], "pozycje[%d].stawka_vat" % i),
            netto=netto, vat=vat, brutto=brutto, id=p.get("id"), parent_id=p.get("parent_id"), zestaw=zestaw)

    for i, p in enumerate(surowe):
        if i in dzieci:
            continue
        for pole in ("stawka_vat", "netto", "vat", "brutto"):
            if pole not in p:
                raise BladWalidacji(BRAK_POLA, "pozycje[%d].%s" % (i, pole), "brak pola")
        pozycje[i] = pozycja(i, p, *(do_decimal(p[k], "pozycje[%d].%s" % (i, k)) for k in ("netto", "vat", "brutto")),
                             False)
    for i in sorted(dzieci):   # pozycje nadrzędne: brakujące kwoty = suma liści pod nimi
        p = surowe[i]
        if "stawka_vat" not in p:
            raise BladWalidacji(BRAK_POLA, "pozycje[%d].stawka_vat" % i, "brak pola")
        liscie = [pozycje[j] for j in liscie_pod(i, dzieci)]
        kwoty = [do_decimal(p[k], "pozycje[%d].%s" % (i, k)) if p.get(k) is not None
                 else sum((getattr(l, k) for l in liscie), Decimal(0)) for k in ("netto", "vat", "brutto")]
        pozycje[i] = pozycja(i, p, *kwoty, True)
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
