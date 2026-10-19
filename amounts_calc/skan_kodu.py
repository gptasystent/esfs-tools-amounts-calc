"""Skaner kodu aplikacji: miejsca, które liczą kwoty po swojemu zamiast wspólną funkcją.

    python -m amounts_calc.skan_kodu SCIEZKA [SCIEZKA...] [--json w.json] [--csv w.csv]
        [--zrodlo-prawdy funkcje.txt] [--pomin GLOB] [--waznosc wysoka|srednia|niska]

Zasada, której pilnuje skaner: kwoty pozycji liczy JEDNA wspólna funkcja (domyślnie `kwoty_pozycji(wartosc_netto,
mnoznik_vat) -> (netto, vat, brutto)`): netto do grosza, VAT = round(netto * stawka / 100, 2) w ROUND_HALF_UP, brutto =
netto + VAT, czyli VAT liczony od netto pozycji i zaokrąglany PER POZYCJA. Każde inne miejsce, które mnoży przez
stawkę, zaokrągla kwotę albo zapisuje brutto/VAT po swojemu, może dawać różnice groszowe.

Skanowane pliki: Python (.py), TypeScript/JavaScript (.ts .tsx .js .jsx .mjs) i SQL (.sql oraz zapytania w tekstach
Pythona i TS). To skaner tekstowy (wyrażenia regularne + prosty lekser komentarzy i tekstów), bez parsowania
składni: wskazuje miejsca do przejrzenia, nie dowodzi błędu. Linię można wyłączyć komentarzem
`# kwoty-ok: powód` (Python), `// kwoty-ok: powód` (TS) albo `-- kwoty-ok: powód` (SQL) w tej samej linii,
w linii nad nią albo gdziekolwiek w wieloliniowej instrukcji.

Tylko stdlib. Kod wyjścia: 0 = brak znalezisk, 1 = są znaleziska, 2 = błąd wejścia.
"""
import argparse
import csv
import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict, namedtuple
from functools import lru_cache

WYSOKA, SREDNIA, NISKA = "wysoka", "srednia", "niska"
WAZNOSCI = (WYSOKA, SREDNIA, NISKA)
_RANGA = {w: i for i, w in enumerate(WAZNOSCI)}

# kod -> (domyślna ważność, krótki opis, podpowiedź poprawki)
VAT_MNOZENIE_BEZ_ZAOKRAGLENIA = "VAT_MNOZENIE_BEZ_ZAOKRAGLENIA"
JS_ZAOKRAGLENIE_FLOAT = "JS_ZAOKRAGLENIE_FLOAT"
BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI = "BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI"
NETTO_Z_BRUTTO_DZIELENIE = "NETTO_Z_BRUTTO_DZIELENIE"
ROUND_PYTHON_BANKOWE = "ROUND_PYTHON_BANKOWE"
ROUND_NIEPOPRAWNE_MIEJSCA = "ROUND_NIEPOPRAWNE_MIEJSCA"
FLOAT_W_FUNKCJI_KWOTOWEJ = "FLOAT_W_FUNKCJI_KWOTOWEJ"
SUMOWANIE_NIESPOJNE = "SUMOWANIE_NIESPOJNE"
STAWKA_VAT_TEKSTOWA = "STAWKA_VAT_TEKSTOWA"
STAWKA_ZW_NP_POMINIETA = "STAWKA_ZW_NP_POMINIETA"
FUNKCJA_POZA_ZRODLEM_PRAWDY = "FUNKCJA_POZA_ZRODLEM_PRAWDY"

KODY = {
    VAT_MNOZENIE_BEZ_ZAOKRAGLENIA: (
        WYSOKA, "mnożenie przez stawkę VAT (* 1.23, * (1 + vat/100), * stawka / 100) bez zaokrąglenia kwoty",
        "wywołaj kwoty_pozycji(wartosc_netto, mnoznik_vat) zamiast mnożyć samemu; VAT = round(netto * stawka / 100, 2), "
        "brutto = netto + VAT"),
    JS_ZAOKRAGLENIE_FLOAT: (
        WYSOKA, "zaokrąglanie kwoty na binarnych floatach (toFixed, Math.round(x * 100) / 100, parseFloat(x.toFixed(2)))",
        "nie zaokrąglaj w przeglądarce: weź netto/VAT/brutto z backendu (kwoty_pozycji); toFixed służy tylko do "
        "wyświetlania gotowej kwoty (np. Intl.NumberFormat)"),
    BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI: (
        WYSOKA, "zapis wartosc_brutto / suma_brutto / kwota_vat / wartosc_vat wyliczony poza wspólną funkcją",
        "przypisz wynik kwoty_pozycji(...) (netto, vat, brutto) zamiast liczyć pole własnym wyrażeniem; w SQL użyj "
        "wartości policzonych przez aplikację albo jednej funkcji bazy"),
    NETTO_Z_BRUTTO_DZIELENIE: (
        SREDNIA, "dzielenie przez 1.23 / (1 + stawka/100): liczenie netto z brutto bez jawnej decyzji",
        "ustal jedną regułę odwrotnego liczenia (netto = round(brutto / (1 + stawka/100), 2), VAT = brutto - netto) "
        "w jednej funkcji i ją wywołuj; sprawdź, czy brutto to na pewno wartość źródłowa"),
    ROUND_PYTHON_BANKOWE: (
        WYSOKA, "round() Pythona na kwocie: zaokrąglenie bankowe (half-even), nie ROUND_HALF_UP",
        "użyj Decimal i .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) albo kwoty_pozycji(...)"),
    ROUND_NIEPOPRAWNE_MIEJSCA: (
        WYSOKA, "zaokrąglenie kwoty do 0 lub 1 miejsca po przecinku (albo bez liczby miejsc)",
        "kwoty zaokrąglamy do grosza (2 miejsca); ceny jednostkowe do 4; wywołaj kwoty_pozycji(...)"),
    FLOAT_W_FUNKCJI_KWOTOWEJ: (
        SREDNIA, "float / double / real zamiast Decimal / numeric w obliczeniach kwot",
        "używaj Decimal (Python) i numeric(12,2) (SQL); float() tylko do wyświetlania, nigdy w obliczeniach"),
    SUMOWANIE_NIESPOJNE: (
        SREDNIA, "SUM(brutto) obok SUM(netto) (i SUM(vat)) w jednym zapytaniu: dwa różne sposoby sumowania",
        "sumuj jedną rzecz: SUM(wartosc_netto) i SUM(kwota_vat) (brutto = ich suma) albo SUM(wartosc_brutto), "
        "ale nie porównuj jednego z drugim; pozycje powinny mieć netto + VAT = brutto z kwoty_pozycji"),
    STAWKA_VAT_TEKSTOWA: (
        NISKA, "stawka VAT jako tekst z procentem ('23%') zamiast jednej reprezentacji",
        "trzymaj stawkę w jednej postaci (23, 8, 5, 0, 'zw', 'np') i parsuj ją w jednym miejscu"),
    STAWKA_ZW_NP_POMINIETA: (
        SREDNIA, "kod obsługuje tylko numeryczne stawki: pomija 'zw' i 'np' (lista liczb, > 0, rzutowanie na liczbę)",
        "obsłuż zw/np jawnie (VAT 0): stawka_na_liczbe('zw') -> 0; nie rzutuj stawki bez sprawdzenia"),
    FUNKCJA_POZA_ZRODLEM_PRAWDY: (
        NISKA, "funkcja o nazwie z brutto/netto/vat/kwoty/suma spoza listy źródeł prawdy",
        "sprawdź, czy liczy kwoty po swojemu; jeśli deleguje do kwoty_pozycji, dopisz ją do --zrodlo-prawdy, "
        "jeśli nie - zastąp wywołaniem kwoty_pozycji albo oznacz '# kwoty-ok: powód'"),
}

DOMYSLNE_ZRODLO_PRAWDY = ("kwoty_pozycji",)
ROZSZERZENIA = {".py": "py", ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts", ".sql": "sql"}
POMIJANE_KATALOGI = frozenset({".git", ".hg", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next",
                               ".tox", ".mypy_cache", ".pytest_cache", "coverage", "site-packages"})
MAKS_ROZMIAR_PLIKU = 1_500_000
MAKS_FRAGMENT = 160
_MARKER = re.compile(r"kwoty-ok\s*:", re.I)

Znalezisko = namedtuple("Znalezisko", "plik linia kod waznosc fragment podpowiedz")


# ---------------------------------------------------------------- leksyka: komentarze i teksty

_PY = re.compile(
    r"""(?P<tri>(?<!\w)(?:[rRbBuUfF]{1,2})?(?P<q>\"\"\"|''')(?:\\.|.)*?(?P=q))"""
    r"""|(?P<str>(?<!\w)(?:[rRbBuUfF]{1,2})?(?:'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"))"""
    r"""|(?P<kom>\#[^\n]*)""", re.S)
_TS = re.compile(
    r"""(?P<kom>//[^\n]*|/\*.*?\*/)"""
    r"""|(?P<str>'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`)""", re.S)
_SQL = re.compile(r"""(?P<kom>--[^\n]*|/\*.*?\*/)|(?P<str>'(?:''|[^'])*'|"(?:""|[^"])*")""", re.S)
_LEKSERY = {"py": _PY, "ts": _TS, "sql": _SQL}
_NIE_NOWA_LINIA = re.compile(r"[^\n]")
_JAK_SQL = re.compile(r"\b(?:SELECT|UPDATE|INSERT|DELETE|CREATE|ALTER)\b", re.I)
_JAK_SQL2 = re.compile(r"\b(?:FROM|SET|INTO|TABLE|TRIGGER|FUNCTION|VALUES|VIEW)\b", re.I)


def przygotuj(tekst, jezyk):
    """(kod, komentarze, literaly_sql): `kod` to tekst z zamalowanymi spacjami komentarzami i docstringami (te same
    numery linii), `komentarze` {nr linii: tekst komentarza}, `literaly_sql` [(nr pierwszej linii, treść)] - teksty
    w Pythonie/TS wyglądające na SQL."""
    wynik, komentarze, literaly = [], {}, []
    poz = 0
    linia = 0                     # numer linii (od 0) w miejscu `poz`
    for m in _LEKSERY[jezyk].finditer(tekst):
        wynik.append(tekst[poz:m.start()])
        linia += tekst.count("\n", poz, m.start())
        poz = m.start()
        zamaluj = m.group("kom") is not None
        if jezyk == "py" and m.group("tri") is not None:
            przed = "".join(wynik).rstrip()
            poczatek_linii = not tekst[tekst.rfind("\n", 0, m.start()) + 1:m.start()].strip()
            if poczatek_linii and (not przed or przed.endswith(":")):
                zamaluj = True            # docstring: traktowany jak komentarz
            elif _jak_sql(m.group()):
                literaly.append((linia, m.group()))
        elif jezyk != "sql" and m.group("str") is not None and _jak_sql(m.group()):
            literaly.append((linia, m.group()))
        if zamaluj:
            komentarze[linia] = komentarze.get(linia, "") + " " + m.group()
            if "\n" in m.group():                # wieloliniowy: marker w dowolnej jego linii
                for i, kawalek in enumerate(m.group().split("\n")):
                    komentarze[linia + i] = komentarze.get(linia + i, "") + " " + kawalek
            wynik.append(_NIE_NOWA_LINIA.sub(" ", m.group()))
        else:
            wynik.append(m.group())
        linia += m.group().count("\n")
        poz = m.end()
    wynik.append(tekst[poz:])
    return "".join(wynik), komentarze, literaly


def _jak_sql(tresc):
    return bool(_JAK_SQL.search(tresc) and _JAK_SQL2.search(tresc))


# ---------------------------------------------------------------- słownik kwot

_POLSKIE = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
_IDENT = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż_]\w*")
_TOKENY = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_TOKENY_KWOT = frozenset({"netto", "brutto", "vat", "kwota", "kwoty", "kwot", "cena", "ceny", "suma", "sumy",
                          "wartosc", "podatek", "podatku", "amount", "price", "gross"})
_TOKENY_FUNKCJI = frozenset({"brutto", "netto", "vat", "kwota", "kwoty", "suma", "sumy", "sumuj"})


@lru_cache(maxsize=None)
def tokeny(identyfikator):
    return frozenset(t.lower() for t in _TOKENY.findall(identyfikator.translate(_POLSKIE)))


def ma_kwote(tekst):
    """Czy w tekście jest identyfikator (lub klucz tekstowy) z członem netto/brutto/vat/kwota/cena/suma/wartosc..."""
    return any(tokeny(i) & _TOKENY_KWOT for i in _IDENT.findall(tekst))


def _norm(nazwa):
    return re.sub(r"[^a-z]", "", nazwa.translate(_POLSKIE).lower())


_CELE_ZAPISU = frozenset(_norm(n) for n in ("wartosc_brutto", "suma_brutto", "kwota_vat", "wartosc_vat", "suma_vat",
                                           "kwota_brutto"))

# ---------------------------------------------------------------- wzorce

_STAWKA_ID = r"""[\w.\[\]'"]*(?:[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax)[\w.\[\]'"]*"""
_W_NAWIASACH = r"(?:[^()]|\([^()]*\))*?"     # treść nawiasu z jednym poziomem zagnieżdżenia
_LUZNO = r"[^\n]{0,60}?"                         # kilka znaków w obrębie linii (także domykające nawiasy)
_LICZBA_VAT = r"(?<![\w.])1[.,](?:23|08|05)(?![\d])"
_MNOZENIE = r"(?<!\*)\*(?!\*)"

_R1 = [re.compile(p, re.I) for p in (
    _MNOZENIE + r"\s*(?:Decimal\(\s*['\"])?" + _LICZBA_VAT,                       # * 1.23, * Decimal("1.23")
    _LICZBA_VAT + r"(?:['\"]\s*\))?\s*" + _MNOZENIE,                              # 1.23 *
    _MNOZENIE + r"\s*0[.,](?:23|08|05)(?!\d)",                                    # * 0.23
    _MNOZENIE + r"\s*\(\s*1\s*\+\s*0[.,](?:23|08|05)\s*\)",                       # * (1 + 0.23)
)] + [re.compile(p) for p in (
    _MNOZENIE + r"\s*\(\s*1\s*\+\s*" + _LUZNO + r"(?:[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax)"
    + _LUZNO + r"/\s*100(?:\.0*)?\s*\)",                                          # * (1 + vat/100)
    _MNOZENIE + r"\s*\(\s*100\s*\+\s*" + _LUZNO + r"(?:[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax)"
    + _LUZNO + r"\)\s*/\s*100",                                                   # * (100 + stawka) / 100
    _MNOZENIE + r"\s*" + _STAWKA_ID + r"\s*/\s*100(?:\.0*)?(?![\d])",             # * stawka / 100
    _STAWKA_ID + r"\s*/\s*100(?:\.0*)?\s*" + _MNOZENIE,                           # stawka / 100 *
)]
_SLABA_STALA = re.compile(r"(?<![\d.])(?:1[.,]0[58]|0[.,]0[58])(?!\d)")
_STAWKA_W_LINII = re.compile(r"[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax")
_ZAOKRAGLENIE = re.compile(
    r"\bround\s*\(|\.quantize\s*\(|\bquantize\s*\(|\bkwoty_pozycji\s*\(|\.kwota\s*\(|ROUND_HALF_|Math\.round|"
    r"\.toFixed\s*\(|numeric\s*\(\s*\d+\s*,\s*2\s*\)|\bzaokragl\w*\s*\(|\bzaokrągl\w*\s*\(", re.I)

_R3 = [re.compile(p, re.I) for p in (
    r"(?<!/)/(?!/)\s*(?:Decimal\(\s*['\"])?" + _LICZBA_VAT,                       # / 1.23
    r"\b100\s*/\s*(?:123|108|105)\b",                                             # brutto * 100 / 123
    r"\b(?:23|8|5)\s*/\s*(?:123|108|105)\b",                                      # brutto * 23 / 123
)] + [re.compile(p) for p in (
    r"(?<!/)/(?!/)\s*\(\s*1\s*\+\s*" + _LUZNO + r"(?:[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax)"
    + _LUZNO + r"/\s*100(?:\.0*)?\s*\)",                                          # / (1 + vat/100)
    r"(?<!/)/(?!/)\s*\(\s*100\s*\+\s*" + _LUZNO + r"(?:[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax)"
    + _LUZNO + r"\)",                                                             # / (100 + stawka)
)]

_PY_ROUND = re.compile(r"(?<![\w.])round\s*\(")
_PY_BEZ_BANKOWEGO = re.compile(r"\bquantize\s*\(|ROUND_HALF_UP|\bkwoty_pozycji\s*\(|\.kwota\s*\(")
_PY_FLOAT = re.compile(r"(?<![\w.])float\s*\(")
_PY_DEF_FLOAT = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+(\w+)[ \t]*\(.*(?::[ \t]*float\b|->[ \t]*float\b)", re.M)
_SQL_FLOAT = re.compile(r"\b(?:float|float4|float8|real|double\s+precision)\b", re.I)
_SQL_ROUND = re.compile(r"\bROUND\s*\(", re.I)
_JS_PARSE_TOFIXED = re.compile(r"\b(?:parseFloat|Number)\s*\([^;\n]*?\.toFixed\s*\(|\+\s*[\w.\[\]()]+\.toFixed\s*\(")
_JS_MATH_ROUND_100 = re.compile(r"Math\.round\s*\(\s*" + _W_NAWIASACH + r"\*\s*100\s*\)\s*/\s*100")
_JS_TOFIXED = re.compile(r"\.toFixed\s*\(\s*(\d*)\s*\)")
_JS_MATH_ROUND = re.compile(r"Math\.round\s*\(")

_R6_TEKST = re.compile(r"""(['"])\s*(?:23|8|5|0)\s*%\s*\1""")
_R6_PROCENT_PARSE = re.compile(r"""(?:\.replace\(\s*['"]%['"]|\.rstrip\(\s*['"]%['"]|\.strip\(\s*['"]%['"])""")
_R6_IN = re.compile(r"""(?:[Ss]tawk\w*|[Vv]at_?[Rr]ate|\bvat\b|tax_rate)\s+(NOT\s+)?IN\s*[\(\[\{]([^)\]}]*)[\)\]\}]""", re.I)
_R6_LISTA = re.compile(r"""[\(\[\{]\s*23\s*,\s*8\s*,\s*5\s*(?:,\s*0\s*)?[\)\]\}]""")
_R6_NIEROWNE = re.compile(r"""[Ss]tawk\w*\s*(?:!==?|<>)\s*['"](?:zw|np)['"]""")
_R6_WIEKSZE = re.compile(r"""\b[\w.]*[Ss]tawk\w*\s*(?:>\s*0\b|>=\s*1\b)""")
_R6_RZUTOWANIE = re.compile(
    r"""\b(?:parseInt|parseFloat|Number|int|float|Decimal)\s*\(\s*[\w.\[\]'"]*(?:[Ss]tawk|vat_?rate|vatRate)[\w.\[\]'"]*\s*[,)]""")
_ZW_NP = re.compile(r"""['"](?:zw|np)['"]""", re.I)

_DEF_PY = re.compile(r"^[ \t]*(?:async\s+)?def\s+(\w+)", re.M)
_DEF_TS = [re.compile(p, re.M) for p in (
    r"\bfunction\s*\*?\s*(\w+)",
    r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=\n]+)?=\s*(?:async\s*)?(?:function\b|\([^)\n]*\)\s*(?::[^=\n]+)?=>|\w+\s*=>)",
    r"^[ \t]*(?:(?:public|private|protected|static|async|readonly)\s+)*(\w+)\s*\([^)\n]*\)\s*(?::\s*[\w<>\[\]|]+\s*)?\{",
)]
_DEF_SQL = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([\w.\"]+)", re.I)

_SQL_SUM_BRUTTO = re.compile(r"\bSUM\s*\(" + _W_NAWIASACH + r"brutto" + _W_NAWIASACH + r"\)", re.I)
_SQL_SUM_NETTO = re.compile(r"\bSUM\s*\(" + _W_NAWIASACH + r"netto" + _W_NAWIASACH + r"\)", re.I)
_SQL_UPDATE_SET = re.compile(r"\bUPDATE\b.*?\bSET\b(.*?)(?=\bWHERE\b|\bFROM\b|;|$)", re.I | re.S)
_SQL_INSERT = re.compile(r"\bINSERT\s+INTO\s+[\w.\"]+\s*\(([^)]*)\)\s*(VALUES|SELECT)\b(.*)", re.I | re.S)
_SQL_GENERATED = re.compile(r"([\w\"]+)\s+[\w\"]+(?:\s*\([^)]*\))?\s+GENERATED\s+ALWAYS\s+AS\s*\(", re.I)
_SQL_NEW = re.compile(r"\bNEW\s*\.\s*([\w\"]+)\s*:?=\s*([^;]*)", re.I)

_PRZYPISANIE = re.compile(
    r"""(?P<cel>(?:[\w.]*\.)?\[?['"]?(?P<nazwa>[A-Za-z_]\w*)['"]?\]?)\s*(?P<op>[+\-*/]?=|:)(?![=>])""")
_ARYTMETYKA = re.compile(r"[\w)\]]\s*[+\-*/]\s*[\w(\[]")
_MNOZENIE_DZIELENIE = re.compile(r"[\w)\]]\s*[*/]\s*[\w(\[]|\bround\s*\(|\bquantize\s*\(|\.toFixed\s*\(|Math\.round|\bROUND\s*\(",
                                 re.I)


class _Plik:
    """Wspólny kontekst reguł dla jednego pliku."""

    def __init__(self, tekst, jezyk, zrodlo):
        self.jezyk = jezyk
        self.oryginal = tekst.split("\n")
        kod, self.komentarze, self.literaly = przygotuj(tekst, jezyk)
        self.linie = kod.split("\n")
        self.zrodlo = zrodlo                      # znormalizowane nazwy funkcji dozwolonych
        self.zaokraglenie = _zaokraglenie_z(zrodlo)
        self.znaleziska = {}
        self.linie_zw_np = [bool(_ZW_NP.search(l)) for l in self.linie]

    def dodaj(self, linia, kod, waznosc=None):
        """Zapisuje znalezisko (linia od 0, kod); przy powtórzeniu zostaje wyższa ważność."""
        waznosc = waznosc or KODY[kod][0]
        stara = self.znaleziska.get((linia, kod))
        if stara is None or _RANGA[waznosc] < _RANGA[stara]:
            self.znaleziska[(linia, kod)] = waznosc


def _zaokraglenie_z(zrodlo):
    if not zrodlo:
        return _ZAOKRAGLENIE
    nazwy = "|".join(re.escape(n) for n in sorted(zrodlo))
    return re.compile(_ZAOKRAGLENIE.pattern + r"|\b(?:%s)\s*\(" % nazwy, re.I)


# ---------------------------------------------------------------- instrukcje

_NAWIASY = re.compile(r"[()\[\]{}]")
_TEKST_JEDNOLINIOWY = re.compile(r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*\"""")
_KONCZY_OPERATOREM = ("\\", "+", "-", "*", "/", "=", "&&", "||", "?", ":", ",")
_ZACZYNA_KONTYNUACJE = (".", "?", ":", "&&", "||", "*", "+", "/")
MAKS_LINII_INSTRUKCJI = 25


def instrukcje(linie, jezyk):
    """[(pierwsza, ostatnia)] numery linii instrukcji. Python/TS: do domknięcia nawiasów i kontynuacji operatorem;
    SQL: do linii kończącej się średnikiem."""
    wynik, n, i = [], len(linie), 0
    while i < n:
        if not linie[i].strip():
            i += 1
            continue
        start, glebokosc = i, 0
        while True:
            czysta = _TEKST_JEDNOLINIOWY.sub("", linie[i])
            if jezyk != "sql":
                glebokosc += len(re.findall(r"[(\[{]", czysta)) - len(re.findall(r"[)\]}]", czysta))
            koniec = i + 1 >= n or i - start >= MAKS_LINII_INSTRUKCJI * (2 if jezyk == "sql" else 1)
            if not koniec:
                aktualna, nastepna = czysta.strip(), linie[i + 1].strip()
                if jezyk == "sql":
                    koniec = aktualna.endswith(";")
                else:
                    koniec = (glebokosc <= 0 and not aktualna.endswith(_KONCZY_OPERATOREM)
                              and not (nastepna and nastepna.startswith(_ZACZYNA_KONTYNUACJE)))
            if koniec:
                break
            i += 1
        wynik.append((start, i))
        i += 1
    return wynik


# ---------------------------------------------------------------- reguły

def _linia_w(tekst_instrukcji, start, offset):
    return start + tekst_instrukcji.count("\n", 0, offset)


def _linia_tekstu(tekst, offset):
    s = tekst.rfind("\n", 0, offset) + 1
    k = tekst.find("\n", offset)
    return tekst[s:k if k >= 0 else len(tekst)]


def _argumenty(tekst, nawias_otwierajacy):
    """Argumenty wywołania na najwyższym poziomie; `nawias_otwierajacy` to indeks '('. Zwraca (lista, indeks ')')."""
    glebokosc, biezacy, wynik = 0, [], []
    for i in range(nawias_otwierajacy, len(tekst)):
        c = tekst[i]
        if c in "([{":
            glebokosc += 1
            if glebokosc == 1:
                continue
        elif c in ")]}":
            glebokosc -= 1
            if glebokosc == 0:
                wynik.append("".join(biezacy).strip())
                return wynik, i
        elif c == "," and glebokosc == 1:
            wynik.append("".join(biezacy).strip())
            biezacy = []
            continue
        biezacy.append(c)
    return wynik + ["".join(biezacy).strip()], len(tekst)


def w_zwyklym_tekscie(tekst, offset):
    """Czy `offset` leży w tekście ("..." / '...' / `...`), który nie jest SQL-em ani wyrażeniem w ${...} / {...}:
    ścieżki URL, komunikaty itp. nie są obliczeniami."""
    poczatek = tekst.rfind("\n", 0, offset) + 1
    for m in re.finditer(r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`""", tekst[poczatek:]):
        a, b = poczatek + m.start(), poczatek + m.end()
        if a < offset < b:
            tresc = m.group()
            if _jak_sql(tresc):
                return False
            przed = tekst[a:offset]
            return przed.count("{") <= przed.count("}")
    return False


def _regula_mnozenie(p, tekst, start):
    """1. mnożenie przez stawkę bez zaokrąglenia (wszystkie języki)."""
    if p.zaokraglenie.search(tekst):
        return
    for wz in _R1:
        for m in wz.finditer(tekst):
            if _SLABA_STALA.search(m.group()) and not (ma_kwote(_linia_tekstu(tekst, m.start()))
                                                       or _STAWKA_W_LINII.search(_linia_tekstu(tekst, m.start()))):
                continue            # 1.05 / 1.08 / 0.05 / 0.08 bywają zwykłym współczynnikiem: potrzebny kontekst kwot
            if not w_zwyklym_tekscie(tekst, m.start()):
                p.dodaj(_linia_w(tekst, start, m.start()), VAT_MNOZENIE_BEZ_ZAOKRAGLENIA)


def _regula_js(p, tekst, start):
    """1. JS/TS: toFixed, Math.round(x * 100) / 100, parseFloat(x.toFixed(2)) na kwotach."""
    sparowane = set()
    for m in _JS_PARSE_TOFIXED.finditer(tekst):
        l = _linia_w(tekst, start, m.start())
        if ma_kwote(_linia_tekstu(tekst, m.start())):
            p.dodaj(l, JS_ZAOKRAGLENIE_FLOAT, WYSOKA)
            sparowane.add(l)
    for m in _JS_MATH_ROUND_100.finditer(tekst):
        if ma_kwote(_linia_tekstu(tekst, m.start())) or ma_kwote(m.group()):
            p.dodaj(_linia_w(tekst, start, m.start()), JS_ZAOKRAGLENIE_FLOAT, WYSOKA)
    for m in _JS_TOFIXED.finditer(tekst):
        l = _linia_w(tekst, start, m.start())
        if l in sparowane or not ma_kwote(_linia_tekstu(tekst, m.start())):
            continue
        if m.group(1) in ("0", "1"):
            p.dodaj(l, ROUND_NIEPOPRAWNE_MIEJSCA, WYSOKA)
        else:
            p.dodaj(l, JS_ZAOKRAGLENIE_FLOAT, SREDNIA)
    for m in _JS_MATH_ROUND.finditer(tekst):
        argumenty, _ = _argumenty(tekst, m.end() - 1)
        wiersz = _linia_tekstu(tekst, m.start())
        if ma_kwote(wiersz) and not re.search(r"\*\s*100\b|\b100\s*\*", argumenty[0] if argumenty else ""):
            if not re.search(r"\)\s*/\s*100", tekst[m.start():m.start() + len(wiersz) + 80]):
                p.dodaj(_linia_w(tekst, start, m.start()), ROUND_NIEPOPRAWNE_MIEJSCA, WYSOKA)


def _regula_dzielenie(p, tekst, start):
    """3. dzielenie przez 1.23 / (1 + stawka/100)."""
    for wz in _R3:
        for m in wz.finditer(tekst):
            if not w_zwyklym_tekscie(tekst, m.start()):
                p.dodaj(_linia_w(tekst, start, m.start()), NETTO_Z_BRUTTO_DZIELENIE)


def _regula_round_py(p, tekst, start):
    """4. round() Pythona na kwocie."""
    if _PY_BEZ_BANKOWEGO.search(tekst):
        return
    for m in _PY_ROUND.finditer(tekst):
        argumenty, _ = _argumenty(tekst, m.end() - 1)
        if not ma_kwote(" ".join(argumenty)) and not ma_kwote(_linia_tekstu(tekst, m.start())):
            continue
        miejsca = argumenty[1].replace("ndigits=", "").strip() if len(argumenty) > 1 else None
        kod = ROUND_NIEPOPRAWNE_MIEJSCA if miejsca in (None, "", "0", "1") else ROUND_PYTHON_BANKOWE
        p.dodaj(_linia_w(tekst, start, m.start()), kod)


def _regula_float_py(p, tekst, start):
    """4. float() na kwocie."""
    for m in _PY_FLOAT.finditer(tekst):
        if ma_kwote(_linia_tekstu(tekst, m.start())):
            p.dodaj(_linia_w(tekst, start, m.start()), FLOAT_W_FUNKCJI_KWOTOWEJ)
    for m in _PY_DEF_FLOAT.finditer(tekst):
        if tokeny(m.group(1)) & _TOKENY_KWOT:
            p.dodaj(_linia_w(tekst, start, m.start()), FLOAT_W_FUNKCJI_KWOTOWEJ)


def _regula_sql_float_round(p, tekst, start):
    """4. SQL: float/real zamiast numeric; ROUND(x), ROUND(x, 0|1) na kwotach."""
    for m in _SQL_FLOAT.finditer(tekst):
        if ma_kwote(_linia_tekstu(tekst, m.start())):
            p.dodaj(_linia_w(tekst, start, m.start()), FLOAT_W_FUNKCJI_KWOTOWEJ)
    for m in _SQL_ROUND.finditer(tekst):
        argumenty, _ = _argumenty(tekst, m.end() - 1)
        if not ma_kwote(" ".join(argumenty)):
            continue
        if len(argumenty) < 2 or argumenty[1].strip() in ("0", "1"):
            p.dodaj(_linia_w(tekst, start, m.start()), ROUND_NIEPOPRAWNE_MIEJSCA)


def _regula_sumowanie(p, tekst, start):
    """5. SUM(brutto) obok SUM(netto) w jednym zapytaniu."""
    brutto, netto = list(_SQL_SUM_BRUTTO.finditer(tekst)), _SQL_SUM_NETTO.search(tekst)
    if brutto and netto:
        p.dodaj(_linia_w(tekst, start, brutto[0].start()), SUMOWANIE_NIESPOJNE)


def _rhs(tekst, od):
    """Prawa strona przypisania: do przecinka/średnika/końca linii na poziomie 0 albo zamykającego nawiasu."""
    glebokosc = 0
    for i in range(od, len(tekst)):
        c = tekst[i]
        if c in "([{":
            glebokosc += 1
        elif c in ")]}":
            glebokosc -= 1
            if glebokosc < 0:
                return tekst[od:i]
        elif glebokosc == 0 and c in ",;\n":
            return tekst[od:i]
    return tekst[od:]


def _ocena_zapisu(rhs, op, cel, p):
    """None (zapis dopuszczalny) albo ważność: wyrażenie liczące kwotę poza wspólną funkcją."""
    if p.zrodlo and any(re.search(r"\b%s\s*\(" % re.escape(n), rhs, re.I) for n in p.zrodlo):
        return None
    if op in ("*=", "/="):
        return WYSOKA
    if op in ("+=", "-="):
        return None                           # kumulowanie już policzonych kwot
    if _MNOZENIE_DZIELENIE.search(rhs):
        return WYSOKA
    if _ARYTMETYKA.search(rhs) and _norm(cel) not in re.sub(r"[^a-z]", "", rhs.translate(_POLSKIE).lower()):
        return SREDNIA
    return None


def _regula_zapis(p, tekst, start):
    """2. Python/TS: przypisanie/klucz wartosc_brutto, suma_brutto, kwota_vat, wartosc_vat wyrażeniem."""
    for m in _PRZYPISANIE.finditer(tekst):
        if _norm(m.group("nazwa")) not in _CELE_ZAPISU:
            continue
        rhs = _rhs(tekst, m.end())
        if m.group("op") == ":" and not re.search(r"[\w)\]]\s*[+\-*/]\s*[\w(\[]", rhs):
            continue
        waznosc = _ocena_zapisu(rhs, m.group("op"), m.group("nazwa"), p)
        if waznosc:
            p.dodaj(_linia_w(tekst, start, m.start("nazwa")), BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI, waznosc)


def _regula_zapis_sql(p, tekst, start):
    """2. SQL: UPDATE ... SET brutto = ..., INSERT, GENERATED ALWAYS AS, trigger (NEW.brutto := ...)."""
    for m in _SQL_UPDATE_SET.finditer(tekst):
        zestaw, od = m.group(1), m.start(1)
        for przypisanie in re.finditer(r"([\w.\"]+)\s*=\s*", zestaw):
            kolumna = przypisanie.group(1).split(".")[-1].strip('"')
            if _norm(kolumna) not in _CELE_ZAPISU:
                continue
            rhs = _rhs(zestaw, przypisanie.end())
            if re.match(r"\s*[\w.\"]+\s*$", rhs) or re.search(r"\bSUM\s*\(", rhs, re.I) and not _MNOZENIE_DZIELENIE.search(rhs):
                continue
            waznosc = _ocena_zapisu(rhs, "=", kolumna, p)
            if waznosc:
                p.dodaj(_linia_w(tekst, start, od + przypisanie.start(1)), BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI, waznosc)
    for m in _SQL_INSERT.finditer(tekst):
        kolumny = [c.strip().split(".")[-1].strip('"') for c in m.group(1).split(",")]
        if any(_norm(c) in _CELE_ZAPISU for c in kolumny) and (_MNOZENIE_DZIELENIE.search(m.group(3))
                                                              or re.search(r"[\w)]\s*\+\s*[\w(]", m.group(3))):
            p.dodaj(_linia_w(tekst, start, m.start()), BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI, WYSOKA)
    for m in _SQL_GENERATED.finditer(tekst):
        if _norm(m.group(1)) in _CELE_ZAPISU:
            p.dodaj(_linia_w(tekst, start, m.start()), BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI, WYSOKA)
    for m in _SQL_NEW.finditer(tekst):
        if _norm(m.group(1)) in _CELE_ZAPISU and not re.fullmatch(r"\s*[\w.]+\s*", m.group(2)):
            p.dodaj(_linia_w(tekst, start, m.start()), BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI, WYSOKA)


def _regula_stawki(p, tekst, start):
    """6. stawka jako tekst '23%' i kod pomijający zw/np."""
    for m in _R6_TEKST.finditer(tekst):
        if re.search(r"[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT|[Tt]ax", _linia_tekstu(tekst, m.start())):
            p.dodaj(_linia_w(tekst, start, m.start()), STAWKA_VAT_TEKSTOWA)
    for m in _R6_PROCENT_PARSE.finditer(tekst):
        if re.search(r"[Ss]tawk|(?<![A-Za-z])vat|Vat|VAT", _linia_tekstu(tekst, m.start())):
            p.dodaj(_linia_w(tekst, start, m.start()), STAWKA_VAT_TEKSTOWA)
    koniec = start + tekst.count("\n")
    for m in _R6_NIEROWNE.finditer(tekst):
        p.dodaj(_linia_w(tekst, start, m.start()), STAWKA_ZW_NP_POMINIETA)
    # jawna obsługa zw/np w pobliżu (okno 8 linii) oznacza świadomą decyzję
    jawne = any(p.linie_zw_np[max(0, start - 8):koniec + 9])
    for m in _R6_IN.finditer(tekst):
        pozycje = [x.strip().strip("'\"").lower() for x in m.group(2).split(",") if x.strip()]
        liczbowe = [x for x in pozycje if re.fullmatch(r"\d+", x)]
        ma_zw_np = any(x in ("zw", "np") for x in pozycje)
        if (m.group(1) and ma_zw_np) or (not m.group(1) and liczbowe and not ma_zw_np):
            p.dodaj(_linia_w(tekst, start, m.start()), STAWKA_ZW_NP_POMINIETA)
    if jawne:
        return
    for wz in (_R6_LISTA, _R6_WIEKSZE, _R6_RZUTOWANIE):
        for m in wz.finditer(tekst):
            p.dodaj(_linia_w(tekst, start, m.start()), STAWKA_ZW_NP_POMINIETA)


# (reguła, fragmenty tekstu, z których co najmniej jeden musi wystąpić w instrukcji - tani filtr przed wyrażeniami regularnymi)
_REGULY = {
    "py": ((_regula_mnozenie, ("*",)), (_regula_dzielenie, ("/",)), (_regula_round_py, ("round",)),
           (_regula_float_py, ("float",)), (_regula_zapis, ("brutto", "vat")),
           (_regula_stawki, ("stawk", "vat", "tax"))),
    "ts": ((_regula_mnozenie, ("*",)), (_regula_dzielenie, ("/",)), (_regula_js, ("tofixed", "math.round")),
           (_regula_zapis, ("brutto", "vat")), (_regula_stawki, ("stawk", "vat", "tax"))),
    "sql": ((_regula_mnozenie, ("*",)), (_regula_dzielenie, ("/",)),
            (_regula_sql_float_round, ("float", "real", "double", "round")), (_regula_sumowanie, ("sum",)),
            (_regula_zapis_sql, ("brutto", "vat")), (_regula_stawki, ("stawk", "vat", "tax"))),
}
_REGULY_SQL_W_TEKSCIE = _REGULY["sql"][2:5]


# ---------------------------------------------------------------- definicje funkcji i zakresy

def _nazwa_funkcji_sql(nazwa):
    return nazwa.strip('"').split(".")[-1].strip('"')


def definicje(p):
    """[(nr linii od 0, nazwa funkcji)] definicji w pliku."""
    kod = "\n".join(p.linie)
    wynik = []
    if p.jezyk == "py":
        wzorce = [_DEF_PY]
    elif p.jezyk == "ts":
        wzorce = _DEF_TS
    else:
        wzorce = [_DEF_SQL]
    for wz in wzorce:
        for m in wz.finditer(kod):
            nazwa = _nazwa_funkcji_sql(m.group(1)) if p.jezyk == "sql" else m.group(1)
            wynik.append((kod.count("\n", 0, m.start(1)), nazwa))
    return sorted(set(wynik))


def _zakres_ciala(p, linia):
    """Ostatnia linia ciała funkcji zaczynającej się w `linia` (Python: wcięcia; TS: nawiasy klamrowe)."""
    n = len(p.linie)
    if p.jezyk == "py":
        wciecie = len(p.linie[linia]) - len(p.linie[linia].lstrip())
        koniec = linia
        for i in range(linia + 1, n):
            if not p.linie[i].strip():
                continue
            if len(p.linie[i]) - len(p.linie[i].lstrip()) <= wciecie:
                break
            koniec = i
        return koniec
    if p.jezyk == "ts":
        glebokosc, widziano = 0, False
        for i in range(linia, min(n, linia + 400)):
            czysta = _TEKST_JEDNOLINIOWY.sub("", p.linie[i])
            for c in czysta:
                if c == "{":
                    glebokosc += 1
                    widziano = True
                elif c == "}":
                    glebokosc -= 1
            if widziano and glebokosc <= 0:
                return i
            if not widziano and czysta.rstrip().endswith(";"):
                return i
        return linia
    return linia


def skanuj_tekst(tekst, sciezka, jezyk, zrodlo_prawdy=DOMYSLNE_ZRODLO_PRAWDY):
    """Znaleziska w jednym pliku (tekst już wczytany). `zrodlo_prawdy`: nazwy funkcji uznanych za wspólne."""
    zrodlo = frozenset(_norm(n) for n in zrodlo_prawdy)
    p = _Plik(tekst, jezyk, zrodlo_prawdy)
    instr = instrukcje(p.linie, jezyk)
    for start, koniec in instr:
        tekst_instr = "\n".join(p.linie[start:koniec + 1])
        niskie = tekst_instr.lower()
        for regula, wyzwalacze in _REGULY[jezyk]:
            if any(w in niskie for w in wyzwalacze):
                regula(p, tekst_instr, start)
    for nr_linii, tresc in p.literaly:                     # SQL w tekstach Pythona / TS
        linie_sql = przygotuj(tresc, "sql")[0].split("\n")
        for s, k in instrukcje(linie_sql, "sql"):
            tekst_sql = "\n".join(linie_sql[s:k + 1])
            niskie = tekst_sql.lower()
            for regula, wyzwalacze in _REGULY_SQL_W_TEKSCIE:
                if any(w in niskie for w in wyzwalacze):
                    regula(p, tekst_sql, nr_linii + s)
    # definicje funkcji (7.) i ciała źródeł prawdy
    wylaczone_ciala = set()
    for nr, nazwa in definicje(p):
        norm = _norm(nazwa)
        if norm in zrodlo:
            if jezyk != "sql":
                wylaczone_ciala.update(range(nr, _zakres_ciala(p, nr) + 1))
            continue
        if (tokeny(nazwa) & _TOKENY_FUNKCJI) and not nazwa.lower().startswith("test") and not nazwa.startswith("__"):
            p.dodaj(nr, FUNKCJA_POZA_ZRODLEM_PRAWDY)
    z_markerem = {l for l, t in p.komentarze.items() if _MARKER.search(t)}    # linie z komentarzem kwoty-ok
    instr_linii = {}
    for start, koniec in instr:
        for l in range(start, koniec + 1):
            instr_linii[l] = (start, koniec)
    wynik = []
    for (linia, kod), waznosc in sorted(p.znaleziska.items()):
        start, koniec = instr_linii.get(linia, (linia, linia))
        if linia in wylaczone_ciala:
            continue
        w_instrukcji = any(l in z_markerem for l in range(start, koniec + 1))
        nad_instrukcja = (start - 1) in z_markerem and not p.linie[start - 1].strip()
        if w_instrukcji or nad_instrukcja:
            continue
        fragment = " ".join(p.oryginal[linia].split())
        if len(fragment) > MAKS_FRAGMENT:
            fragment = fragment[:MAKS_FRAGMENT - 1] + "…"
        wynik.append(Znalezisko(sciezka, linia + 1, kod, waznosc, fragment, KODY[kod][2]))
    return wynik


# ---------------------------------------------------------------- pliki

def wczytaj_zrodlo_prawdy(sciezka):
    """Nazwy funkcji z pliku tekstowego (jedna w linii; '#' zaczyna komentarz, puste linie są pomijane)."""
    with open(sciezka, encoding="utf-8-sig") as f:
        nazwy = [w.split("#", 1)[0].strip() for w in f]
    return tuple(n for n in nazwy if n)


def _pasuje_do_wzorca(rel, nazwa, wzorce):
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(nazwa, g) or fnmatch.fnmatch("/" + rel, g) for g in wzorce)


def zbierz_pliki(sciezki, pomin=()):
    """[(ścieżka pliku, ścieżka względna do skanowanego katalogu)] oraz liczba pominiętych (za duże / wykluczone)."""
    pliki, pominiete = [], 0
    for glowna in sciezki:
        if os.path.isfile(glowna):
            if ROZSZERZENIA.get(os.path.splitext(glowna)[1].lower()):
                pliki.append((glowna, os.path.basename(glowna)))
            continue
        for katalog, podkatalogi, nazwy in os.walk(glowna):
            rel_kat = os.path.relpath(katalog, glowna).replace(os.sep, "/")
            rel_kat = "" if rel_kat == "." else rel_kat
            podkatalogi[:] = sorted(
                d for d in podkatalogi if d not in POMIJANE_KATALOGI
                and not _pasuje_do_wzorca((rel_kat + "/" + d).lstrip("/"), d, pomin))
            for nazwa in sorted(nazwy):
                if not ROZSZERZENIA.get(os.path.splitext(nazwa)[1].lower()):
                    continue
                rel = (rel_kat + "/" + nazwa).lstrip("/")
                pelna = os.path.join(katalog, nazwa)
                if nazwa.endswith((".min.js", ".d.ts")) or _pasuje_do_wzorca(rel, nazwa, pomin) \
                        or os.path.getsize(pelna) > MAKS_ROZMIAR_PLIKU:
                    pominiete += 1
                    continue
                pliki.append((pelna, rel))
    return pliki, pominiete


def modul(rel):
    """Moduł pliku: jego katalog względem skanowanego katalogu ("routes", "utils", "frontend/pages"); pliki w korzeniu
    trafiają do "(korzeń)"."""
    kat = os.path.dirname(rel)
    return kat or "(korzeń)"


def skanuj(sciezki, pomin=(), zrodlo_prawdy=DOMYSLNE_ZRODLO_PRAWDY):
    """Skanuje pliki i katalogi. Zwraca (znaleziska, statystyki); znaleziska mają ścieżkę względną w polu `plik`."""
    pliki, pominiete = zbierz_pliki(sciezki, pomin)
    znaleziska, bledy_odczytu = [], 0
    for pelna, rel in pliki:
        try:
            with open(pelna, encoding="utf-8", errors="replace") as f:
                tekst = f.read()
        except OSError:
            bledy_odczytu += 1
            continue
        jezyk = ROZSZERZENIA[os.path.splitext(pelna)[1].lower()]
        znaleziska += skanuj_tekst(tekst.replace("\r\n", "\n").replace("\r", "\n"), rel, jezyk, zrodlo_prawdy)
    return znaleziska, {"plikow": len(pliki), "pominietych": pominiete, "bledow_odczytu": bledy_odczytu}


# ---------------------------------------------------------------- raport

def podsumowanie(znaleziska, statystyki):
    moduly = Counter(modul(z.plik) for z in znaleziska)
    return dict(statystyki, znalezisk=len(znaleziska),
                wg_waznosci={w: sum(1 for z in znaleziska if z.waznosc == w) for w in WAZNOSCI},
                wg_kodu=dict(sorted(Counter(z.kod for z in znaleziska).items(), key=lambda kv: (-kv[1], kv[0]))),
                wg_modulu=dict(sorted(moduly.items(), key=lambda kv: (-kv[1], kv[0]))))


def _slownik(z):
    return {"plik": z.plik, "linia": z.linia, "kod": z.kod, "waznosc": z.waznosc, "modul": modul(z.plik),
            "fragment": z.fragment, "podpowiedz": z.podpowiedz}


def zgrupowane(znaleziska):
    """{moduł: [znaleziska]} - moduły od największej liczby znalezisk, w module od najwyższej ważności."""
    grupy = defaultdict(list)
    for z in znaleziska:
        grupy[modul(z.plik)].append(z)
    for lista in grupy.values():
        lista.sort(key=lambda z: (_RANGA[z.waznosc], z.plik, z.linia, z.kod))
    return dict(sorted(grupy.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def tekst_raportu(znaleziska, statystyki):
    p = podsumowanie(znaleziska, statystyki)
    linie = ["Przeskanowano plików: %d (pominięto: %d), znalezisk: %d" % (p["plikow"], p["pominietych"], p["znalezisk"]),
             "Ważność: " + ", ".join("%s=%d" % (w, n) for w, n in p["wg_waznosci"].items()), ""]
    if not znaleziska:
        return "\n".join(linie + ["Brak znalezisk."])
    linie.append("Kody (liczba znalezisk):")
    linie += ["  %-34s %d" % (k, n) for k, n in p["wg_kodu"].items()]
    for mod, lista in zgrupowane(znaleziska).items():
        linie += ["", "== %s (%d) ==" % (mod, len(lista))]
        linie += ["  %s:%d  %s [%s]  %s" % (z.plik, z.linia, z.kod, z.waznosc, z.fragment) for z in lista]
    linie += ["", "Jak poprawić (wg kodu):"]
    for kod in p["wg_kodu"]:
        linie += ["  %s [%s]: %s" % (kod, KODY[kod][0], KODY[kod][2])]
    return "\n".join(linie)


def zapisz_json(sciezka, znaleziska, statystyki):
    dane = {"podsumowanie": podsumowanie(znaleziska, statystyki), "znaleziska": [_slownik(z) for z in znaleziska]}
    with open(sciezka, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dane, f, ensure_ascii=False, indent=2)
        f.write("\n")


KOLUMNY_CSV = ("plik", "linia", "kod", "waznosc", "modul", "fragment", "podpowiedz")


def zapisz_csv(sciezka, znaleziska):
    """Separator ';', UTF-8 z BOM, CRLF (otwiera się w polskim Excelu); fragmenty zaczynające się od =, +, @, -
    dostają apostrof (ochrona przed formułami)."""
    from .check import _komorka_tekstowa
    with open(sciezka, "w", encoding="utf-8-sig", newline="") as f:
        zapis = csv.writer(f, delimiter=";", lineterminator="\r\n")
        zapis.writerow(KOLUMNY_CSV)
        for z in sorted(znaleziska, key=lambda z: (_RANGA[z.waznosc], z.plik, z.linia, z.kod)):
            zapis.writerow([_komorka_tekstowa(x) for x in (z.plik, z.linia, z.kod, z.waznosc, modul(z.plik),
                                                          z.fragment, z.podpowiedz)])


def _parser():
    p = argparse.ArgumentParser(prog="python -m amounts_calc.skan_kodu", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sciezki", nargs="+", metavar="SCIEZKA", help="pliki i katalogi do przeskanowania")
    p.add_argument("--json", dest="json_wyjscie", metavar="W.json", help="zapisz znaleziska i podsumowanie jako JSON")
    p.add_argument("--csv", dest="csv_wyjscie", metavar="W.csv", help="zapisz znaleziska jako CSV (';', UTF-8 z BOM)")
    p.add_argument("--zrodlo-prawdy", dest="zrodlo_prawdy", metavar="PLIK.txt",
                   help="plik z nazwami funkcji uznanych za wspólne (jedna w linii); domyślnie tylko kwoty_pozycji")
    p.add_argument("--pomin", action="append", default=[], metavar="GLOB",
                   help="wzorzec ścieżki (względnej) lub nazwy do pominięcia, np. 'tests/*' albo 'test_*.py'; "
                        "można powtarzać i łączyć przecinkami")
    p.add_argument("--waznosc", choices=WAZNOSCI, default=NISKA,
                   help="najniższa ważność w raporcie (domyślnie niska = wszystko)")
    return p


def main(argv=None):
    for strumien in (sys.stdout, sys.stderr):
        if hasattr(strumien, "reconfigure"):
            strumien.reconfigure(errors="replace")
    args = _parser().parse_args(argv)
    try:
        for s in args.sciezki:
            if not os.path.exists(s):
                raise OSError("brak ścieżki: %s" % s)
        zrodlo = DOMYSLNE_ZRODLO_PRAWDY
        if args.zrodlo_prawdy:
            zrodlo = tuple(dict.fromkeys(DOMYSLNE_ZRODLO_PRAWDY + wczytaj_zrodlo_prawdy(args.zrodlo_prawdy)))
        pomin = [g.strip() for porcja in args.pomin for g in porcja.split(",") if g.strip()]
        znaleziska, statystyki = skanuj(args.sciezki, pomin, zrodlo)
        znaleziska = [z for z in znaleziska if _RANGA[z.waznosc] <= _RANGA[args.waznosc]]
        if args.json_wyjscie:
            zapisz_json(args.json_wyjscie, znaleziska, statystyki)
        if args.csv_wyjscie:
            zapisz_csv(args.csv_wyjscie, znaleziska)
    except OSError as e:
        print("Błąd: %s" % e, file=sys.stderr)
        return 2
    print(tekst_raportu(znaleziska, statystyki))
    return 1 if znaleziska else 0


if __name__ == "__main__":
    sys.exit(main())
