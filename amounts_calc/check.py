"""Wsadowe sprawdzanie dokumentów (np. wyeksportowanych z bazy do JSON) - bez wysyłania danych do repo.

    python -m amounts_calc.check dokumenty.json [--tryb-vat per_stawka|per_pozycja]
        [--json wynik.json] [--max-przyklady N] [--mapowanie mapowanie.json]

Dla każdego dokumentu:
  a) sprawdz_spojnosc na zapisanych danych (niespójność zapisanych sum),
  b) oblicz() z pozycji w OBU trybach VAT i porownaj() z zapisanymi sumami; zapisuje, który tryb
     pasuje (żaden / oba / jeden). Zgodność oceniana jest po sumach dokumentu i po podsumowaniu
     stawek; różnice na poziomie pozycji są tylko liczone (korekta groszowa per stawka może
     legalnie trafić na inną pozycję niż w systemie źródłowym).
Błędny dokument nie przerywa całości - trafia do raportu z kodem błędu.

Kod wyjścia: 0 = wszystko w porządku, 1 = znaleziono problemy, 2 = błąd wejścia (plik/JSON/mapowanie).
"""
import argparse
import json
import sys
import uuid
from collections import Counter
from decimal import Decimal, DecimalException

from .adapter import id_dokumentu, scal_mapowanie, wczytaj_plik_json, z_wiersza
from .bledy import NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, NIEPOPRAWNA_LICZBA, BladWalidacji
from .config import TRYBY_VAT, VAT_PER_POZYCJA, VAT_PER_STAWKA
from .formatowanie import format_bez_zer, format_kwoty
from .model import dokument_z_slownika
from .obliczenia import oblicz
from .spojnosc import porownaj, sprawdz_spojnosc

DOPASOWANIA = ("oba", "per_stawka", "per_pozycja", "zaden")
_POZYCJA_KLUCZE = ("netto", "vat", "brutto")


def _dopasowanie(ps, pp):
    return "oba" if ps and pp else "per_stawka" if ps else "per_pozycja" if pp else "zaden"


def _blad(kod, pole, wiadomosc, etap):
    return {"kod": kod, "pole": pole, "etap": etap, "wiadomosc": wiadomosc}


def _kryterium(roznice, z_stawkami):
    """Różnice istotne dla oceny trybu: sumy dokumentu (+ podsumowanie stawek)."""
    return [r for r in roznice
            if r["pole"].startswith("suma_") or (z_stawkami and r["pole"].startswith("stawka:"))]


def _opisz_roznice(roznice):
    return [{"pole": r["pole"], "zapisane": r["a"], "biblioteka": r["b"], "roznica": r["roznica"]}
            for r in roznice]


def sprawdz_dokument(surowy, indeks=0, tryb_vat=VAT_PER_STAWKA, mapowanie=None):
    """Sprawdza jeden dokument (słownik o dowolnych nazwach pól + mapowanie). Nie rzuca z powodu danych."""
    wynik = {"indeks": indeks, "id": id_dokumentu(surowy, mapowanie), "blad": None, "niespojnosci": [],
             "pasuje": None, "tryb_pasujacy": None, "rozbieznosci": None, "liczba_roznic_pozycji": None,
             "pominieto_pozycje": False, "max_roznica": Decimal(0)}
    etap = "wejscie"
    try:
        kan = z_wiersza(surowy, mapowanie)
        pozycje = kan["pozycje"]
        pominiete = bool(pozycje) and not any(k in p for p in pozycje for k in _POZYCJA_KLUCZE)
        wynik["pominieto_pozycje"] = pominiete
        zapisany = dokument_z_slownika(dict(kan, pozycje=[] if pominiete else pozycje))
        niespojnosci = sprawdz_spojnosc(zapisany, tryb_vat=tryb_vat)
        if pominiete:   # bez kwot pozycji zostaje tylko sprawdzenie sum dokumentu
            niespojnosci = [n for n in niespojnosci
                            if n["kod"] == NETTO_PLUS_VAT_ROZNE_OD_BRUTTO and n["zakres"] == "dokument"]
        wynik["niespojnosci"] = niespojnosci

        etap = "obliczenia"
        z_stawkami = (not pominiete) or ("podsumowanie" in kan)
        rozbieznosci, pozycyjne, pasuje = {}, {}, {}
        for tv in (VAT_PER_STAWKA, VAT_PER_POZYCJA):
            obliczony = oblicz(pozycje, tryb=kan.get("tryb", "netto"), waluta=kan.get("waluta", "PLN"),
                               rabat_dokumentu_proc=kan.get("rabat_dokumentu_proc", 0), tryb_vat=tv)
            wszystkie = porownaj(zapisany, obliczony)
            istotne = _kryterium(wszystkie, z_stawkami)
            rozbieznosci[tv] = _opisz_roznice(istotne)
            pozycyjne[tv] = sum(1 for r in wszystkie if r["pole"].startswith("pozycje["))
            pasuje[tv] = not istotne
        wynik.update(pasuje=pasuje, rozbieznosci=rozbieznosci, liczba_roznic_pozycji=pozycyjne,
                     tryb_pasujacy=_dopasowanie(pasuje[VAT_PER_STAWKA], pasuje[VAT_PER_POZYCJA]))
    except BladWalidacji as e:
        wynik["blad"] = _blad(e.kod, e.pole, e.wiadomosc, etap)
    except DecimalException as e:
        wynik["blad"] = _blad(NIEPOPRAWNA_LICZBA, None, "wartość liczbowa poza zakresem (%s)" % type(e).__name__, etap)

    kandydaci = [abs(n["roznica"]) for n in wynik["niespojnosci"]]
    if wynik["rozbieznosci"] is not None:
        # do "największej rozbieżności" liczy się lepszy z trybów (mniejsza suma różnic)
        najlepszy = min((VAT_PER_STAWKA, VAT_PER_POZYCJA),
                        key=lambda t: sum(abs(r["roznica"]) for r in wynik["rozbieznosci"][t]))
        kandydaci += [abs(r["roznica"]) for r in wynik["rozbieznosci"][najlepszy]]
    wynik["max_roznica"] = max(kandydaci, default=Decimal(0))
    return wynik


def ma_problem(wynik):
    return bool(wynik["blad"] or wynik["niespojnosci"] or wynik["tryb_pasujacy"] == "zaden")


def sprawdz_partie(dokumenty, tryb_vat=VAT_PER_STAWKA, mapowanie=None):
    """Zwraca (lista wyników per dokument, podsumowanie). Błędny dokument nie przerywa partii."""
    scal_mapowanie(mapowanie)  # wczesny błąd przy złym mapowaniu
    wyniki = [sprawdz_dokument(d, i, tryb_vat, mapowanie) for i, d in enumerate(dokumenty)]
    kody = Counter()
    for w in wyniki:
        kody.update({n["kod"] for n in w["niespojnosci"]})
        if w["blad"]:
            kody[w["blad"]["kod"]] += 1
    porownane = [w for w in wyniki if w["tryb_pasujacy"] is not None]
    rozklad = Counter(w["tryb_pasujacy"] for w in porownane)
    najwieksze = sorted((w for w in wyniki if w["max_roznica"] > 0), key=lambda w: (-w["max_roznica"], w["indeks"]))
    podsumowanie = {
        "liczba_dokumentow": len(wyniki),
        "spojne": sum(1 for w in wyniki if not w["blad"] and not w["niespojnosci"]),
        "z_niespojnosciami": sum(1 for w in wyniki if w["niespojnosci"]),
        "z_bledem": sum(1 for w in wyniki if w["blad"]),
        "z_problemem": sum(1 for w in wyniki if ma_problem(w)),
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


def tekst_podsumowania(podsumowanie, wyniki, max_przyklady=10):
    p = podsumowanie
    linie = [
        "Sprawdzono dokumentów: %d" % p["liczba_dokumentow"],
        "  spójnych (bez niespójności i błędów): %d" % p["spojne"],
        "  z niespójnością zapisanych sum:       %d" % p["z_niespojnosciami"],
        "  z błędem (walidacja/struktura):       %d" % p["z_bledem"],
        "  z problemem (w tym brak zgodności z biblioteką): %d" % p["z_problemem"],
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
    ostatnie = [wyniki[i] for i in p["najwieksze_indeksy"][:max_przyklady]]
    linie.append("Największe rozbieżności (%d z %d):" % (len(ostatnie), len(p["najwieksze_indeksy"])))
    for n, w in enumerate(ostatnie, 1):
        kody = sorted({x["kod"] for x in w["niespojnosci"]})
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
        wyniki, podsumowanie = sprawdz_partie(dokumenty, args.tryb_vat, mapowanie)
        if args.json_wyjscie:
            zapisz_json(args.json_wyjscie, [wynik_json(w) for w in wyniki if ma_problem(w)])
    except (OSError, ValueError, BladWalidacji) as e:  # json.JSONDecodeError i UnicodeDecodeError to ValueError
        print("Błąd: %s" % e, file=sys.stderr)
        return 2
    print(tekst_podsumowania(podsumowanie, wyniki, args.max_przyklady))
    return 1 if podsumowanie["z_problemem"] else 0


if __name__ == "__main__":
    sys.exit(main())
