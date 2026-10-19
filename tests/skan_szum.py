"""Wymyślone fragmenty do testów odszumiania skanera (runda 9): SZUM (po odszumieniu nie jest istotne) i ISTOTNE
(zostaje). Format: (nazwa, jezyk, kod, kod znaleziska, oczekiwana ważność po odszumieniu; None = szum)."""

FLOAT = "FLOAT_W_FUNKCJI_KWOTOWEJ"
ROUND = "ROUND_PYTHON_BANKOWE"
FUNKCJA = "FUNKCJA_POZA_ZRODLEM_PRAWDY"

SZUM = [
    # 1. float() przy odczycie / konwersji / formatowaniu
    ("float odczyt", "py", "kwota = float(row['kwota'])\n", FLOAT, None),
    ("float abs", "py", "x = abs(float(wiersz['kwota']))\n", FLOAT, None),
    ("float json", "py", "return jsonify({'kwota': float(k.kwota)})\n", FLOAT, None),
    ("float format", "py", "etykieta = '%.2f' % float(kwota)\n", FLOAT, None),
    ("float argument", "py", "limit = float(request.args.get('kwota_max'))\n", FLOAT, None),
    ("float print", "py", "print(float(wartosc_netto))\n", FLOAT, None),
    ("float podstawienie", "py", "dane['kwota'] = float(dane['kwota'])\n", FLOAT, None),
    ("float dzielenie przez stala", "py", "srednia = float(kwota) / 3\n", FLOAT, None),
    ("float def", "py", "def pobierz_kwota(kwota: float) -> float:\n    return kwota\n", FLOAT, None),
    ("float cena", "py", "cena_za_kg = float(cena)\n", FLOAT, None),
    # 2. round() poza pieniędzmi (cena za kg, zł na km, średnie, procenty, rozmiary, współrzędne)
    ("round cena za kg", "py", "cena_kg = round(cena / waga, 2)\n", ROUND, "niska"),
    ("round zl na km", "py", "zl_km = round(koszt_kwota / km, 2)\n", ROUND, "niska"),
    ("round srednia l4", "py", "srednia = round(suma_dni_l4 / liczba, 2)\n", ROUND, "niska"),
    ("round procent", "py", "procent = round(kwota_czesc * 100 / kwota_razem, 2)\n", ROUND, "niska"),
    ("round rozmiar", "py", "rozmiar_mb = round(suma_bajtow / 1048576, 2)\n", ROUND, "niska"),
    ("round litry", "py", "spalanie = round(suma_litrow / km * 100, 2)\n", ROUND, "niska"),
    ("round wspolrzedne", "py", "lat = round(punkt.cena_lat, 5)\n", ROUND, "niska"),
    ("round kwota daleko od vat", "py",
     "netto = p.netto\n\n\n\nsrednia = round(kwota / n, 2)\n", ROUND, "niska"),
    # 3. funkcje wyświetlające kwoty, formatery i komponenty
    ("komponent react", "ts",
     "export const KwotyCard = ({ brutto }: P) => <div>{brutto.toLocaleString('pl-PL')}</div>;\n", FUNKCJA, None),
    ("fmt Intl", "ts",
     "export const fmtKwota = (kwota: number) => new Intl.NumberFormat('pl-PL').format(kwota);\n", FUNKCJA, None),
    ("format toFixed", "ts", "function formatBrutto(b: number) {\n  return b.toFixed(2) + ' zł';\n}\n", FUNKCJA, None),
    ("format py", "py", 'def format_kwoty(netto):\n    return f"{netto:.2f}"\n', FUNKCJA, None),
    ("render vat", "py", "def render_vat(vat):\n    return str(vat)\n", FUNKCJA, None),
    ("suma bez arytmetyki", "ts", "function sumaWiersza(w: Wiersz) {\n  return w.id;\n}\n", FUNKCJA, None),
    ("getter netto", "py", "def pobierz_netto(dok):\n    return dok.netto\n", FUNKCJA, None),
    ("komponent z JSX", "ts",
     "function SumaBrutto({ brutto }: P) {\n  return <span className=\"suma-brutto\">{brutto}</span>;\n}\n", FUNKCJA, None),
    ("nazwa z lancuchem", "ts",
     "const kwotaLabel = (netto: number) => 'Netto: ' + netto + ' zł';\n", FUNKCJA, None),
]

ISTOTNE = [
    # 1. float w działaniu z drugą kwotą / stawką
    ("float brutto z vat", "py", "brutto = float(netto) * (1 + float(vat) / 100)\n", FLOAT, "srednia"),
    ("float vat ze stawki", "py", "kwota_vat = float(netto) * stawka / 100\n", FLOAT, "srednia"),
    ("float netto plus vat", "py", "suma = float(row['netto']) + float(row['vat'])\n", FLOAT, "niska"),
    ("float odejmowanie", "py", "roznica = float(brutto) - float(netto)\n", FLOAT, "niska"),
    ("float zapis do pola kwotowego", "py", "wartosc_brutto = float(netto_a) + netto_b\n", FLOAT, "niska"),
    # 2. round na netto/brutto/vat/stawka
    ("round vat", "py", "vat = round(netto * stawka / 100, 2)\n", ROUND, "wysoka"),
    ("round brutto z 1+vat/100", "py", "brutto = round(netto * (1 + vat/100.0), 2)\n", ROUND, "wysoka"),
    ("round wartosc_brutto", "py", "x = round(wartosc_brutto, 2)\n", ROUND, "wysoka"),
    ("round z sasiednia linia", "py", "netto = pozycja.netto\nsuma = round(cena * ilosc, 2)\n", ROUND, "wysoka"),
    ("round z linia ponizej", "py", "razem = round(cena * ilosc, 2)\nvat = razem * stawka\n", ROUND, "wysoka"),
    # 3. funkcje z działaniami na netto/brutto/vat
    ("def brutto", "py", "def policz_brutto(netto, vat):\n    return netto + vat\n", FUNKCJA, "srednia"),
    ("function vat", "ts",
     "export function liczVat(netto: number, stawka: number) {\n  return netto * stawka / 100;\n}\n", FUNKCJA, "srednia"),
    ("reduce brutto", "ts",
     "const sumaBrutto = (poz: P[]) => poz.reduce((a, p) => a + p.brutto, 0);\n", FUNKCJA, "srednia"),
    ("sql funkcja", "sql",
     "CREATE FUNCTION oblicz_brutto(netto numeric, vat numeric) RETURNS numeric AS $$ SELECT netto + vat $$ LANGUAGE sql;\n",
     FUNKCJA, "srednia"),
    ("metoda klasy", "py", "class D:\n    def suma_netto(self):\n        return self.a_netto - self.b_netto\n", FUNKCJA, "srednia"),
]

# Wzorce, które NADAL muszą być znajdowane w trybie "istotne": (nazwa, jezyk, kod, {kod: ważność})
NADAL_ZNAJDOWANE = [
    ("js brutto (1 + vat/100)", "ts", "const brutto = netto * (1 + vat / 100);\n", {"VAT_MNOZENIE_BEZ_ZAOKRAGLENIA": "wysoka"}),
    ("py brutto (1 + vat/100)", "py", "brutto = netto * (1 + vat / 100)\n", {"VAT_MNOZENIE_BEZ_ZAOKRAGLENIA": "wysoka"}),
    ("py round(netto * (1 + vat/100.0), 2)", "py", "brutto = round(netto * (1 + vat/100.0), 2)\n", {ROUND: "wysoka"}),
    ("js Math.round(netto * vat) / 100", "ts", "const kwotaVat = Math.round(netto * vat) / 100;\n",
     {"BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI": "wysoka"}),
    ("py kwota_vat = netto * (vat / 100)", "py", "kwota_vat = netto * (vat / 100)\n",
     {"BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI": "wysoka"}),
]
