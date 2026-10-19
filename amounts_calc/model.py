"""Model danych: wejście (Pozycja) i wynik (PozycjaWynik, PodsumowanieStawki, DokumentWynik)."""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .bledy import BRAK_POLA, NIEPOPRAWNA_STRUKTURA, NIEPOPRAWNY_TRYB, BladWalidacji
from .config import TRYB_NETTO, TRYBY
from .hierarchia import liscie_pod, zbuduj_hierarchie
from .stawki import KOLEJNOSC_STAWEK, do_decimal, normalizuj_stawke
from .zestawy import (podsumowanie_stawek, rodzice as rodzice_hierarchii, rozwin, sumy_pozycji, wiersze_z_pozycji, wybierz_alternatywy)

_NIE = frozenset({"nie", "false", "n", "no", "0", "f", "off"})


def _jawnie_nie(x):
    if x is False:
        return True
    if isinstance(x, str):
        return x.strip().lower() in _NIE
    return not isinstance(x, bool) and x == 0


def grupa_alternatywy(alternatywa=None, grupa_opcji=None):
    """Grupa opcji wzajemnie wykluczających się albo None (zwykła pozycja).

    `grupa_opcji` (dowolna wartość) wskazuje grupę; samo `alternatywa` (True / "tak") to domyślna grupa "".
    Jawne `alternatywa=False` ("nie", 0) wyłącza alternatywę nawet przy podanej grupie. Puste wartości
    ("" i None) znaczą "nie podano"."""
    brak = alternatywa is None or (isinstance(alternatywa, str) and not alternatywa.strip())
    if not brak and _jawnie_nie(alternatywa):
        return None
    if grupa_opcji is not None and not (isinstance(grupa_opcji, str) and not grupa_opcji.strip()):
        return grupa_opcji
    return None if brak else ""


TRYBY_OPCJI = ("brak", "opcja", "alternatywa")    # tryb pozycji najwyższego poziomu (pole `tryb_opcji`)
WYBOR_OPCJI = ("auto", "jawny", "awaryjny")        # jak dokument rozstrzyga, co wchodzi do sumy
_TAK = frozenset({"tak", "true", "t", "1", "y", "yes", "on", "prawda"})


def _wartosc(p, pole):
    return p.get(pole) if isinstance(p, Mapping) else getattr(p, pole, None)


def _pusta(x):
    return x is None or (isinstance(x, str) and not x.strip())


def tryb_opcji_pozycji(x, pole="tryb_opcji"):
    """"brak" | "opcja" | "alternatywa" albo None (nie podano: puste pole)."""
    if _pusta(x):
        return None
    if not isinstance(x, str) or x.strip().lower() not in TRYBY_OPCJI:
        raise BladWalidacji(NIEPOPRAWNY_TRYB, pole, "dozwolone: %s, jest %r" % (TRYBY_OPCJI, x))
    return x.strip().lower()


def wybrana_pozycji(x, pole="wybrana"):
    """Pole `wybrana` jako bool; puste (None, "") to nie wybrana."""
    if _pusta(x) or x is False:
        return False
    if x is True or (not isinstance(x, (bool, str)) and x == 1):
        return True
    if isinstance(x, str) and x.strip().lower() in _TAK:
        return True
    if _jawnie_nie(x):
        return False
    raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, pole, "oczekiwano tak/nie (true/false), jest %r" % (x,))


def ustal_opcje(pozycje, rodzic, tryb_opcji=None):
    """Które pozycje najwyższego poziomu są opcjonalne i co wchodzi do sumy.

    `pozycje`: Pozycja albo słowniki; `rodzic`: {indeks: indeks rodzica} (pola opcji mają sens tylko na najwyższym
    poziomie, u dzieci są ignorowane); `tryb_opcji`: "auto" (domyślnie: tryb jawny, gdy któraś pozycja najwyższego
    poziomu ma `tryb_opcji`, inaczej awaryjny), "jawny" (zawsze), "awaryjny" (pola `tryb_opcji` / `wybrana`
    ignorowane, obowiązuje `alternatywa` / `grupa_opcji` i dobór kombinacji do nagłówka).

    Zwraca słownik: jawny (bool), alt {indeks: znacznik opcjonalności albo None} - grupa dla alternatywy, "" dla
    opcji, tryby {indeks: "brak"|"opcja"|"alternatywa"} (tylko tryb jawny), wybrana {indeks: bool} (tylko opcja
    i alternatywa), wlaczone (frozenset wybranych pozycji w trybie jawnym, w awaryjnym None)."""
    wybor = "auto" if _pusta(tryb_opcji) else tryb_opcji
    if wybor not in WYBOR_OPCJI:
        raise BladWalidacji(NIEPOPRAWNY_TRYB, "tryb_opcji", "dozwolone: %s, jest %r" % (WYBOR_OPCJI, tryb_opcji))
    gora = [i for i in range(len(pozycje)) if i not in rodzic]
    surowe = {i: tryb_opcji_pozycji(_wartosc(pozycje[i], "tryb_opcji"), "pozycje[%d].tryb_opcji" % i) for i in gora}
    jawny = wybor == "jawny" or (wybor == "auto" and any(t is not None for t in surowe.values()))
    wynik = {"jawny": jawny, "alt": {i: None for i in range(len(pozycje))}, "tryby": {}, "wybrana": {},
             "wlaczone": None}
    if not jawny:
        for i in gora:
            wynik["alt"][i] = grupa_alternatywy(_wartosc(pozycje[i], "alternatywa"), _wartosc(pozycje[i], "grupa_opcji"))
        return wynik
    for i in gora:
        tryb = surowe[i] or "brak"
        wynik["tryby"][i] = tryb
        if tryb == "brak":
            continue
        g = _wartosc(pozycje[i], "grupa_opcji")
        wynik["alt"][i] = ("" if _pusta(g) else g) if tryb == "alternatywa" else ""
        wynik["wybrana"][i] = wybrana_pozycji(_wartosc(pozycje[i], "wybrana"), "pozycje[%d].wybrana" % i)
    wynik["wlaczone"] = frozenset(i for i, w in wynik["wybrana"].items() if w)
    return wynik


@dataclass(frozen=True)
class Pozycja:
    """Wejściowa pozycja dokumentu.

    W trybie od netto podaj `cena_netto_jedn` (albo `cena_zakupu_jedn` + `narzut_proc`/`marza_proc` pozycji,
    które mają pierwszeństwo, albo `koszt_zakupu_jedn` + narzut/marża dokumentu),
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
    cena_zakupu_jedn: object = None  # oferty/zamówienia: cena zakupu; z narzutem lub marżą daje cenę sprzedaży
    narzut_proc: object = None       # narzut % na cenie zakupu: sprzedaż = zakup * (1 + narzut/100)
    marza_proc: object = None        # alternatywnie marża %: sprzedaż = zakup / (1 - marża/100)
    alternatywa: object = None       # opcja wykluczająca się z innymi opcjami grupy (patrz zestawy.py)
    grupa_opcji: object = None       # nazwa grupy opcji (domyślnie jedna grupa dla wszystkich alternatyw)
    tryb_opcji: object = None        # tryb jawny: "brak" | "opcja" | "alternatywa" (patrz ustal_opcje)
    wybrana: object = None           # tryb jawny: czy opcja / alternatywa wchodzi do sumy


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
        cena_zakupu_jedn=d.get("cena_zakupu_jedn"), narzut_proc=d.get("narzut_proc"), marza_proc=d.get("marza_proc"),
        alternatywa=d.get("alternatywa"), grupa_opcji=d.get("grupa_opcji"),
        tryb_opcji=d.get("tryb_opcji"), wybrana=d.get("wybrana"),
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
    zestaw: bool = False  # wiersz zbiorczy pozycji nadrzędnej: N x suma dzieci, nie wchodzi do sum razem z dziećmi
    alternatywa: object = None  # znacznik opcjonalności: grupa alternatyw ("" dla opcji w trybie jawnym) albo None
    tryb_opcji: object = None   # tryb jawny: "brak" | "opcja" | "alternatywa" (None - dokument w trybie awaryjnym)
    wybrana: object = None      # tryb jawny: czy opcja / alternatywa wchodzi do sumy (None dla "brak")


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
    # Model zestawów: True - ilość zestawu mnoży sumę jego dzieci (dzieci opisują 1 szt.); False - ilość
    # zestawu jest ignorowana (dawne zachowanie). Wybrane opcje: indeksy alternatyw, które weszły do sum.
    ilosc_zestawu: bool = False
    wlaczone_alternatywy: Tuple[int, ...] = ()
    alternatywy: str = ""  # "", "brak" | "zgodne" | "najblizsze" | "wybrane" | "jawne" - jak ustalono opcje
    opcje_jawne: bool = False  # True: opcje i alternatywy wynikają z pól tryb_opcji / wybrana (bez doboru do nagłówka)

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
                             **{k: v for k, v in (("id", p.id), ("parent_id", p.parent_id),
                                                   ("alternatywa", p.alternatywa), ("tryb_opcji", p.tryb_opcji),
                                                   ("wybrana", p.wybrana)) if v is not None})
                        for p in self.pozycje],
            "podsumowanie": [{"stawka_vat": s.stawka_vat, "netto": str(s.netto), "vat": str(s.vat),
                              "brutto": str(s.brutto)} for s in self.podsumowanie],
            "suma_netto": str(self.suma_netto), "suma_vat": str(self.suma_vat),
            "suma_brutto": str(self.suma_brutto), "rozbieznosc_vat": str(self.rozbieznosc_vat),
            "ilosc_zestawu": self.ilosc_zestawu,
        }


def podsumuj_stawki(pozycje):
    """Grupuje pozycje (z polami stawka_vat/netto/vat/brutto) po stawce, w stałej kolejności.
    Prosta suma liści (bez ilości zestawów i alternatyw) - dla dokumentów bez takich pozycji."""
    sumy = {}
    for p in pozycje:
        if p.zestaw:
            continue
        n, v, b = sumy.get(p.stawka_vat, (Decimal(0), Decimal(0), Decimal(0)))
        sumy[p.stawka_vat] = (n + p.netto, v + p.vat, b + p.brutto)
    return tuple(PodsumowanieStawki(s, *sumy[s]) for s in KOLEJNOSC_STAWEK if s in sumy)


def podsumowanie_dokumentu(pozycje, ilosc_zestawu=False, wlaczone=(), konf=None):
    """Podsumowanie stawek dokumentu: zestawy o ilości N wnoszą N x dzieci, opcje spoza `wlaczone` nie wchodzą
    do sum, dzieci nie są liczone drugi raz. Dla zwykłych dokumentów równoważne podsumuj_stawki."""
    kwargs = {} if konf is None else {"konf": konf}
    wiersze = wiersze_z_pozycji(pozycje)
    dzieci = zbuduj_hierarchie([(p.id, p.parent_id) for p in pozycje])
    rozw = rozwin(wiersze, dzieci, ilosc_zestawu, **kwargs)
    sumy = podsumowanie_stawek(wiersze, dzieci, rozw, frozenset(wlaczone), **kwargs)
    return tuple(PodsumowanieStawki(s, v["netto"], v["vat"], v["brutto"]) for s, v in sumy.items())


def dokument_z_dokumentem(dok):
    """Akceptuje DokumentWynik albo słownik (np. zbudowany z wiersza bazy) i zwraca DokumentWynik."""
    if isinstance(dok, DokumentWynik):
        return dok
    return dokument_z_slownika(dok)


def dokument_z_slownika(d, ilosc_zestawu=None, tryb_opcji=None):
    """Buduje DokumentWynik z zewnętrznych danych bez przeliczania - do sprawdz_spojnosc/porownaj.

    Wymagane: pozycje[{stawka_vat, netto, vat, brutto}], suma_netto, suma_vat, suma_brutto.
    Opcjonalne: waluta, tryb ('netto'), tryb_vat, podsumowanie[{stawka_vat, netto, vat, brutto}],
    w pozycjach id i parent_id (zestawy; kwoty pozycji nadrzędnej mogą być pominięte - zostaną uzupełnione
    wartością oczekiwaną), `alternatywa` / `grupa_opcji` (opcje wzajemnie wykluczające się, patrz zestawy.py).

    `ilosc_zestawu` (albo klucz "ilosc_zestawu" w słowniku; domyślnie False): True - ilość pozycji nadrzędnej
    mnoży sumę jej dzieci (dzieci opisują 1 szt. zestawu); False - ilość zestawu jest ignorowana.

    Opcje: pozycje najwyższego poziomu z `tryb_opcji` ("brak" | "opcja" | "alternatywa"), `grupa_opcji`, `wybrana`
    (tryb jawny: do sumy wchodzą pozycje "brak" oraz opcje i alternatywy z wybrana=true) albo - bez tych pól -
    `alternatywa` / `grupa_opcji` z doborem kombinacji do nagłówka (tryb awaryjny). `tryb_opcji` (albo klucz
    "tryb_opcji" w słowniku): "auto" (domyślnie) | "jawny" | "awaryjny", patrz ustal_opcje.
    """
    for pole in ("pozycje", "suma_netto", "suma_vat", "suma_brutto"):
        if pole not in d:
            raise BladWalidacji(BRAK_POLA, pole, "brak pola w dokumencie")
    if ilosc_zestawu is None:
        ilosc_zestawu = bool(d.get("ilosc_zestawu", False))
    surowe = list(d["pozycje"])
    for i, p in enumerate(surowe):
        if not isinstance(p, Mapping):
            raise BladWalidacji(NIEPOPRAWNA_STRUKTURA, "pozycje[%d]" % i, "pozycja musi być słownikiem")
    dzieci = zbuduj_hierarchie([(p.get("id"), p.get("parent_id")) for p in surowe])
    opcje = ustal_opcje(surowe, rodzice_hierarchii(dzieci), d.get("tryb_opcji") if tryb_opcji is None else tryb_opcji)
    pozycje = [None] * len(surowe)

    def pozycja(i, p, netto, vat, brutto, zestaw):
        alt = opcje["alt"][i]
        return PozycjaWynik(
            indeks=i, ilosc=do_decimal(p.get("ilosc", 1), "pozycje[%d].ilosc" % i),
            cena_po_rabacie=Decimal(0), rabat_proc=Decimal(0),
            stawka_vat=normalizuj_stawke(p["stawka_vat"], "pozycje[%d].stawka_vat" % i),
            netto=netto, vat=vat, brutto=brutto, id=p.get("id"), parent_id=p.get("parent_id"), zestaw=zestaw,
            alternatywa=alt, tryb_opcji=opcje["tryby"].get(i), wybrana=opcje["wybrana"].get(i))

    for i, p in enumerate(surowe):
        if i in dzieci:
            continue
        for pole in ("stawka_vat", "netto", "vat", "brutto"):
            if pole not in p:
                raise BladWalidacji(BRAK_POLA, "pozycje[%d].%s" % (i, pole), "brak pola")
        pozycje[i] = pozycja(i, p, *(do_decimal(p[k], "pozycje[%d].%s" % (i, k)) for k in ("netto", "vat", "brutto")),
                             False)
    # pozycje nadrzędne: ilość i stawka z danych, kwoty zapisane albo (gdy brak) oczekiwane = N x suma dzieci
    szkic = []
    for i, p in enumerate(surowe):
        if i in dzieci:
            if "stawka_vat" not in p:
                raise BladWalidacji(BRAK_POLA, "pozycje[%d].stawka_vat" % i, "brak pola")
            szkic.append({"indeks": i, "id": p.get("id"), "ilosc": do_decimal(p.get("ilosc", 1), "pozycje[%d].ilosc" % i),
                          "netto": None, "vat": None, "brutto": None, "stawka": None, "zestaw": True,
                          "alternatywa": None})
        else:
            szkic.append(wiersze_z_pozycji([pozycje[i]])[0])
    oczekiwane = rozwin(szkic, dzieci, ilosc_zestawu)["oczekiwane"]
    for i in sorted(dzieci):
        p = surowe[i]
        kwoty = [do_decimal(p[k], "pozycje[%d].%s" % (i, k)) if p.get(k) is not None else oczekiwane[i][k]
                 for k in ("netto", "vat", "brutto")]
        pozycje[i] = pozycja(i, p, *kwoty, True)
    pozycje = tuple(pozycje)
    naglowek = {"netto": do_decimal(d["suma_netto"], "suma_netto"), "vat": do_decimal(d["suma_vat"], "suma_vat"),
                "brutto": do_decimal(d["suma_brutto"], "suma_brutto")}
    wiersze = wiersze_z_pozycji(pozycje)
    rozw = rozwin(wiersze, dzieci, ilosc_zestawu)
    if opcje["jawny"]:
        wlaczone, alternatywy = opcje["wlaczone"], "jawne"
    else:
        wlaczone, alternatywy = wybierz_alternatywy(wiersze, dzieci, rozw, naglowek)
    if d.get("podsumowanie") is not None:
        podsumowanie = tuple(
            PodsumowanieStawki(normalizuj_stawke(s["stawka_vat"], "podsumowanie.stawka_vat"),
                               do_decimal(s["netto"], "podsumowanie.netto"),
                               do_decimal(s["vat"], "podsumowanie.vat"),
                               do_decimal(s["brutto"], "podsumowanie.brutto"))
            for s in d["podsumowanie"])
    else:
        sumy = podsumowanie_stawek(wiersze, dzieci, rozw, wlaczone)
        podsumowanie = tuple(PodsumowanieStawki(s, v["netto"], v["vat"], v["brutto"]) for s, v in sumy.items())
    tryb = d.get("tryb", TRYB_NETTO)
    if tryb not in TRYBY:
        raise BladWalidacji("NIEPOPRAWNY_TRYB", "tryb", "dozwolone: %s" % (TRYBY,))
    return DokumentWynik(
        waluta=d.get("waluta", "PLN"), tryb=tryb, tryb_vat=d.get("tryb_vat", ""),
        pozycje=pozycje, podsumowanie=podsumowanie,
        suma_netto=naglowek["netto"], suma_vat=naglowek["vat"], suma_brutto=naglowek["brutto"],
        ilosc_zestawu=bool(ilosc_zestawu), wlaczone_alternatywy=tuple(sorted(wlaczone)), alternatywy=alternatywy,
        opcje_jawne=opcje["jawny"])
