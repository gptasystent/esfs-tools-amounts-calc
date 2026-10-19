"""Generator "złotych przypadków": deterministyczny zestaw kwot z oczekiwanymi wynikami do testu kontraktowego.

    python -m amounts_calc.zlote --seed 1 --n 500 > zlote.json

Zasada (taka jak we wspólnej funkcji aplikacji `kwoty_pozycji`): netto pozycji zaokrąglone do grosza,
VAT = round(netto * stawka / 100, 2), brutto = netto + VAT; zaokrąglenie ROUND_HALF_UP symetryczne względem zera
(-0,125 -> -0,13); stawki `zw` i `np` mają VAT 0. VAT jest liczony od netto POZYCJI i zaokrąglany PER POZYCJA,
a suma dokumentu to suma pozycji.

Wynik to samodzielny JSON (do odczytu wystarczy dowolny parser JSON, bez tej biblioteki):

    {"format": "zlote-przypadki/1", "seed": 1, "zasada": "...", "przypadki": [ ... ]}

Przypadek ma zawsze `nazwa`, `rodzaj` i `oczekiwane`; reszta zależy od rodzaju:
  pozycja  netto (tekst, może mieć więcej niż 2 miejsca), stawka (23, 8, 5, 0, "zw", "np")
           oczekiwane {netto, vat, brutto}
  rabat    ilosc, cena_netto_jedn, rabat_proc, stawka; netto pozycji = ilosc x cena po rabacie, gdzie cena po rabacie
           jest zaokrąglona do 4 miejsc, a wartość do grosza; oczekiwane {netto, vat, brutto}
  suma     pozycje [{netto, stawka}]; oczekiwane {netto, vat, brutto} = sumy pozycji (VAT per pozycja)
Kwoty są tekstami z kropką dziesiętną; przypadki graniczne (zawsze na początku) są stałe, reszta jest losowana
z `--seed`. Przy `--n` mniejszym niż liczba przypadków granicznych zwracane jest pierwsze `n`.

Moduł jest niezależny od reszty biblioteki (tylko stdlib): oczekiwane wartości liczy własnym kodem, więc test
"generator == oblicz()" naprawdę porównuje dwie implementacje.
"""
import argparse
import json
import random
import sys
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

FORMAT = "zlote-przypadki/1"
STAWKI = (23, 8, 5, 0, "zw", "np")
ZASADA = ("netto do grosza (ROUND_HALF_UP, symetrycznie względem zera); VAT = round(netto * stawka / 100, 2) liczony "
          "od netto pozycji i zaokrąglony per pozycja; brutto = netto + VAT; stawki zw i np mają VAT 0; "
          "suma dokumentu = suma pozycji")
_KONTEKST = Context(prec=60, rounding=ROUND_HALF_UP)
_GROSZ = Decimal("0.01")


def zaokraglij(x, miejsca=2):
    """ROUND_HALF_UP na module liczby, znak dopisany po zaokrągleniu (-0,125 -> -0,13); zero bez znaku."""
    with localcontext(_KONTEKST):
        q = x.copy_abs().quantize(Decimal(1).scaleb(-miejsca), rounding=ROUND_HALF_UP)
        return q.copy_negate() if x < 0 and q != 0 else q


def tekst(x):
    return format(x, "f")


def kwoty_pozycji(wartosc_netto, stawka):
    """(netto, vat, brutto) wg zasady powyżej; `stawka` to 23, 8, 5, 0, "zw" albo "np"."""
    netto = zaokraglij(Decimal(wartosc_netto))
    procent = Decimal(0) if stawka in ("zw", "np") else Decimal(stawka)
    with localcontext(_KONTEKST):
        vat = zaokraglij(netto * procent / 100)
        return netto, vat, netto + vat


def _oczekiwane(netto, vat, brutto):
    return {"netto": tekst(netto), "vat": tekst(vat), "brutto": tekst(brutto)}


def przypadek_pozycji(nazwa, netto, stawka):
    n, v, b = kwoty_pozycji(netto, stawka)
    return {"nazwa": nazwa, "rodzaj": "pozycja", "netto": tekst(Decimal(netto)), "stawka": stawka,
            "oczekiwane": _oczekiwane(n, v, b)}


def przypadek_rabatu(nazwa, ilosc, cena, rabat, stawka):
    with localcontext(_KONTEKST):
        cena_po = zaokraglij(Decimal(cena) * (1 - Decimal(rabat) / 100), 4)
        wartosc = Decimal(ilosc) * cena_po
    n, v, b = kwoty_pozycji(wartosc, stawka)
    return {"nazwa": nazwa, "rodzaj": "rabat", "ilosc": tekst(Decimal(ilosc)), "cena_netto_jedn": tekst(Decimal(cena)),
            "rabat_proc": tekst(Decimal(rabat)), "stawka": stawka, "oczekiwane": _oczekiwane(n, v, b)}


def przypadek_sumy(nazwa, pozycje):
    razem = [Decimal(0)] * 3
    for netto, stawka in pozycje:
        razem = [r + k for r, k in zip(razem, kwoty_pozycji(netto, stawka))]
    return {"nazwa": nazwa, "rodzaj": "suma",
            "pozycje": [{"netto": tekst(Decimal(n)), "stawka": s} for n, s in pozycje],
            "oczekiwane": _oczekiwane(*razem)}


def _graniczne():
    """Stałe przypadki, które najłatwiej zepsuć: półgrosze, 1 gr, ogromne kwoty, ujemne, stawki zw/np, sumy."""
    p = []
    for netto, stawka, nazwa in [
            ("49.50", 23, "49,50 przy 23% (VAT 11,385 -> 11,39)"),
            ("0.01", 23, "1 gr przy 23% (VAT 0,0023 -> 0)"), ("0.02", 23, "2 gr przy 23%"),
            ("0.03", 23, "3 gr przy 23% (VAT 0,0069 -> 0,01)"), ("0.00", 23, "zero"),
            ("0.50", 23, "50 gr przy 23% (VAT 0,115 -> 0,12)"), ("0.10", 5, "10 gr przy 5% (VAT 0,005 -> 0,01)"),
            ("0.09", 5, "9 gr przy 5% (VAT 0,0045 -> 0)"), ("0.30", 5, "30 gr przy 5% (VAT 0,015 -> 0,02)"),
            ("10.00", 8, "10,00 przy 8%"), ("12.50", 8, "12,50 przy 8% (VAT 1,00)"), ("6.25", 8, "6,25 przy 8% (VAT 0,5)"),
            ("1.05", 5, "1,05 przy 5% (VAT 0,0525 -> 0,05)"), ("0.65", 23, "0,65 przy 23% (VAT 0,1495 -> 0,15)"),
            ("100.00", 0, "stawka 0%"), ("100.00", "zw", "stawka zw"), ("100.00", "np", "stawka np"),
            ("12.345", 23, "netto z 3 miejscami (12,345 -> 12,35)"), ("12.344", 23, "netto z 3 miejscami (12,344 -> 12,34)"),
            ("0.005", 23, "pół grosza netto (0,005 -> 0,01)"), ("0.004", 23, "mniej niż pół grosza netto"),
            ("999999999.99", 23, "bardzo duża kwota"), ("1234567890123.45", 8, "kwota na 13 cyfr"),
            ("0.01", 8, "1 gr przy 8%"), ("0.01", 5, "1 gr przy 5%"),
            ("-49.50", 23, "ujemna 49,50 przy 23% (symetryczne zaokrąglenie)"), ("-0.125", 23, "ujemne pół grosza"),
            ("-0.03", 23, "ujemne 3 gr"), ("-100.00", "zw", "ujemna stawka zw"), ("-12.345", 8, "ujemne 3 miejsca")]:
        p.append(przypadek_pozycji(nazwa, netto, stawka))
    p.append(przypadek_sumy("3 x 0,33 przy 23% (VAT per pozycja 3 x 0,08)", [("0.33", 23)] * 3))
    p.append(przypadek_sumy("10 x 0,01 przy 23% (VAT 0 na każdej pozycji)", [("0.01", 23)] * 10))
    p.append(przypadek_sumy("100 x 0,10 przy 5% (każdy VAT 0,005 -> 0,01)", [("0.10", 5)] * 100))
    p.append(przypadek_sumy("dwie stawki", [("49.50", 23), ("12.50", 8), ("30.00", "zw"), ("7.77", 5)]))
    p.append(przypadek_sumy("pozycja i korekta ujemna", [("49.50", 23), ("-49.50", 23)]))
    p.append(przypadek_sumy("rabat jako linia ujemna", [("200.00", 23), ("-20.00", 23)]))
    p.append(przypadek_rabatu("3 x 33,33 z rabatem 10%", "3", "33.33", "10", 23))
    p.append(przypadek_rabatu("cena po rabacie z 4 miejscami", "7", "19.99", "12.5", 8))
    p.append(przypadek_rabatu("rabat 100%", "5", "10.00", "100", 23))
    p.append(przypadek_rabatu("ilość ułamkowa z rabatem", "2.5", "9.99", "15", 23))
    p.append(przypadek_rabatu("ilość ujemna (zwrot)", "-2", "49.50", "0", 23))
    return p


def _kwota(rng, maks_cyfr):
    """Losowa kwota o losowym rzędzie wielkości (log-jednostajnie), w groszach lub z dodatkowymi miejscami."""
    cyfry = rng.randrange(1, maks_cyfr + 1)
    grosze = rng.randrange(0, 10 ** cyfry)
    dodatkowe = rng.choice((0, 0, 0, 0, 1, 2))
    wartosc = Decimal(grosze) / 100
    if dodatkowe:
        wartosc += Decimal(rng.randrange(0, 10 ** dodatkowe)) / (100 * 10 ** dodatkowe)
    return wartosc


def _polgrosz(rng):
    """Netto w groszach i stawka tak, że VAT wypada dokładnie w pół grosza (round half up jest rozstrzygający)."""
    while True:
        stawka = rng.choice((23, 8, 5))
        grosze = rng.randrange(1, 10 ** rng.randrange(2, 8))
        if (grosze * stawka) % 100 == 50:
            return Decimal(grosze) / 100, stawka


def generuj(seed=1, n=500):
    """Lista przypadków: stałe graniczne, potem losowe z `seed` (deterministycznie), razem `n`."""
    przypadki = _graniczne()
    if n <= len(przypadki):
        return przypadki[:max(n, 0)]
    rng = random.Random(seed)
    rodzaje = ("losowa", "losowa", "polgrosze", "mala", "duza", "ujemna", "niezaokraglona", "suma", "rabat")
    for numer in range(len(przypadki), n):
        rodzaj = rng.choice(rodzaje)
        stawka = rng.choice(STAWKI)
        if rodzaj == "polgrosze":
            netto, stawka = _polgrosz(rng)
            przypadki.append(przypadek_pozycji("polgrosze-%d" % numer, netto, stawka))
        elif rodzaj == "suma":
            pozycje = [(_kwota(rng, 5), rng.choice(STAWKI)) for _ in range(rng.randrange(2, 31))]
            if rng.randrange(4) == 0:
                pozycje.append((-_kwota(rng, 4), rng.choice(STAWKI)))
            przypadki.append(przypadek_sumy("suma-%d" % numer, pozycje))
        elif rodzaj == "rabat":
            przypadki.append(przypadek_rabatu(
                "rabat-%d" % numer, Decimal(rng.randrange(1, 2000)) / rng.choice((1, 10, 100)),
                _kwota(rng, 6), Decimal(rng.randrange(0, 5001)) / 100, stawka))
        else:
            netto = {"losowa": lambda: _kwota(rng, 7), "mala": lambda: Decimal(rng.randrange(0, 100)) / 100,
                     "duza": lambda: _kwota(rng, 13) + 10 ** 6, "ujemna": lambda: -_kwota(rng, 7),
                     "niezaokraglona": lambda: Decimal(rng.randrange(0, 10 ** 8)) / 10000}[rodzaj]()
            przypadki.append(przypadek_pozycji("%s-%d" % (rodzaj, numer), netto, stawka))
    return przypadki


def dokument(seed=1, n=500):
    return {"format": FORMAT, "seed": seed, "zasada": ZASADA, "stawki": list(STAWKI), "przypadki": generuj(seed, n)}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m amounts_calc.zlote", description=__doc__.split("\n\n")[0])
    p.add_argument("--seed", type=int, default=1, help="ziarno losowania (domyślnie 1)")
    p.add_argument("--n", type=int, default=500, help="liczba przypadków łącznie, w tym graniczne (domyślnie 500)")
    args = p.parse_args(argv)
    if args.n < 0:
        print("Błąd: --n nie może być ujemne", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    json.dump(dokument(args.seed, args.n), sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
