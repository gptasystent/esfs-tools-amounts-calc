# esfs-tools-amounts-calc

Biblioteka czystych funkcji przeliczających kwoty dokumentu handlowego (oferta, zamówienie,
faktura) z jedną, jawną regułą zaokrąglania. Python stdlib (`decimal`), bez zależności,
bez bazy danych.

## Specyfikacja (do zaimplementowania)

Dziś te same sumy liczy kilka miejsc osobno i wychodzą rozbieżności groszowe. Ma powstać
implementacja + testy + dokumentacja.

**Wejście:** lista pozycji `{ilosc, cena_netto_jedn, rabat_proc, stawka_vat}` (stawka: 23, 8, 5, 0,
`'zw'`, `'np'`), tryb liczenia (od netto, od brutto), waluta, opcjonalnie narzut/marża %.

**Wyjście:** dla każdej pozycji netto, vat, brutto; podsumowanie per stawka VAT; sumy dokumentu;
rozbieżność względem sumy z pozycji.

### Wymagania

1. `Decimal` wszędzie, nigdy `float`. Reguła zaokrąglania do grosza `ROUND_HALF_UP`, jawna i
   konfigurowalna w jednym miejscu. Zaokrąglaj w ściśle określonych punktach (po cenie po rabacie,
   po wartości pozycji; VAT liczony ALBO per pozycja ALBO per stawka na sumie); oba tryby jako
   opcja i test pokazujący różnicę w groszach.
2. Rabat: procentowy na pozycji i na dokumencie, kolejność stosowania zdefiniowana i opisana.
3. Odwrotne liczenie: z brutto na netto i vat bez dryfu (`netto + vat == brutto` zawsze, różnicę
   groszy przypisz do pozycji o największej wartości, deterministycznie).
4. Narzut/marża: cena sprzedaży z kosztu zakupu i narzutu %, oraz odwrotnie marża z cen. Opisz
   różnicę narzut vs marża w README.
5. Walidacja: ujemne ilości, rabat > 100%, nieznana stawka -> jasny błąd. Stawki `zw` i `np`
   mają vat = 0.
6. `porownaj(dokument_a, dokument_b)` zwraca listę rozbieżności (pole, a, b, różnica).
   `sprawdz_spojnosc(dokument)` wykrywa: suma pozycji != suma dokumentu, netto+vat != brutto,
   vat per stawka != vat z sumy. Wynik: lista słowników, kody błędów jako stałe.
7. Testy: co najmniej 60, w tym tabele przypadków granicznych (0,005; 0,015; 33,33% x 3 pozycje,
   23% od 0,01, bardzo duże ilości, 1000 pozycji o cenie 0,01), własności
   (`netto+vat==brutto`, suma pozycji == suma dokumentu), regresja "3 x 0,33 = 0,99 vs 1,00".
8. Przykłady w README na fikcyjnych danych (sklep ogrodniczy), opis integracji: jak podmienić
   istniejące obliczenia, jak zrobić testy zgodności na dokumentach z bazy (bez danych w repo).
9. Otwarte decyzje wypisz w README: VAT per pozycja czy per stawka, jak zaokrąglać rabat,
   jak traktować waluty obce.

Uruchamianie testów: `python -m unittest discover -s tests`.

## Implementacja

Pakiet `amounts_calc/` (tylko stdlib, Python 3.8+), testy w `tests/` (733 testów, kilka sekund,
bez bazy danych i bez sieci).

```
amounts_calc/
  config.py       Konfiguracja: JEDNO miejsce reguły zaokrąglania (symetryczne względem zera)
  stawki.py       stawki 23/8/5/0/'zw'/'np', konwersja liczb (float zabroniony)
  model.py        Pozycja (wejście), PozycjaWynik, PodsumowanieStawki, DokumentWynik
  obliczenia.py   oblicz(): od netto / od brutto, rabaty, VAT per pozycja / per stawka
  marza.py        narzut vs marża; cena_sprzedazy() - cena sprzedaży pozycji z zakupu i narzutu do grosza
  spojnosc.py     sprawdz_spojnosc(), porownaj()
  adapter.py      z_wiersza(): dowolne nazwy pól -> słownik dokumentu; wczytanie JSON jako Decimal
  check.py        CLI: python -m amounts_calc.check (wsadowe sprawdzanie dokumentów, JSON/CSV)
  klasyfikacja.py POLGROSZ, NAGLOWEK_*, ILOSC_X_CENA(_NARZUT), VAT_WYLICZONY_* - przyczyny niespójności (czyste funkcje)
  oferty.py       pozycje z ceną zakupu i narzutem, zestawy z własnym narzutem/rabatem (dane dla check.py)
  podpowiedzi.py  ZESTAW_NIEODSWIEZONY / BRUTTO_ROWNE_NETTO / inna - podpowiedź dla każdej niespójności
  hierarchia.py   pozycje nadrzędne/podrzędne (zestawy): walidacja, liście pod pozycją, limit głębokości (10)
  zestawy.py      model zestawu z ilością: mnożniki, N x dzieci, podzestawy, alternatywy (czyste funkcje)
  opcje.py        opcje i alternatywy w trybie jawnym: poza_suma, OPCJA_W_SUMIE / ALTERNATYWA_* (czyste funkcje)
  skan_kodu.py    skaner kodu aplikacji (Python / TS / SQL): miejsca liczące kwoty po swojemu
  zlote.py        generator "złotych przypadków" (deterministyczny JSON do testu kontraktowego w aplikacji)
  formatowanie.py kanoniczne wyświetlanie Decimal (bez ogona zer, bez zaokrąglania)
  bledy.py        BladWalidacji + kody błędów jako stałe
tests/
  referencja.py   niezależna implementacja na fractions.Fraction (bez kodu biblioteki)
```

### Uruchamianie testów

```
python -m unittest discover -s tests
```

Z katalogu głównego repo; działa tak samo na Linuksie i Windowsie (pliki w repo mają
końce linii LF wymuszone przez `.gitattributes`, więc `core.autocrlf=true` niczego nie psuje;
testy nie czytają plików). Nie ma sekretów ani konfiguracji środowiskowej, więc nie ma `.env`.

### Reguła zaokrąglania

Wszystkie zaokrąglenia przechodzą przez `Konfiguracja` (`amounts_calc/config.py`): domyślnie
`ROUND_HALF_UP`, grosz = 2 miejsca, cena po rabacie = 4 miejsca. Zmiana reguły:
`oblicz(..., konfiguracja=Konfiguracja(zaokraglanie=ROUND_HALF_EVEN))`.

Punkty zaokrąglania (i tylko one), w kolejności:

1. cena po rabacie pozycji = `cena * (1 - rabat/100)` -> 4 miejsca,
2. wartość pozycji = `ilość * cena po rabacie` -> grosz,
3. wartość po rabacie dokumentu = `wartość * (1 - rabat_dok/100)` -> grosz (gdy rabat_dok > 0),
4. rozbicie na netto / vat / brutto -> grosz:
   - od netto: `vat = netto * stawka/100`,
   - od brutto: `netto = brutto / (1 + stawka/100)`, `vat = brutto - netto` (bez dryfu).

**Wartości ujemne.** Zaokrąglanie jest symetryczne względem zera: reguła (domyślnie `ROUND_HALF_UP`)
działa na module liczby, a znak jest dopisywany po zaokrągleniu, więc `-12,345 -> -12,35` tak samo jak
`12,345 -> 12,35`, a wynik zerowy nie dostaje znaku. Dokument z odwróconymi znakami ilości daje dokładnie
odwrócone kwoty w każdym trybie (także korekta groszowa: "największa" pozycja to ta o największym
module, a rozkład `proporcjonalnie` jest lustrzany). Domyślnie `oblicz()` odrzuca ujemną ilość i cenę
(`ILOSC_UJEMNA`, `CENA_UJEMNA`); `oblicz(..., dopusc_ujemne=True)` je dopuszcza. Rabat (`rabat_proc`,
`rabat_dokumentu_proc`) zawsze musi mieścić się w 0..100%; rabat jako osobna linia to linia z ujemną ceną.

**Kolejność rabatów:** rabat pozycji (na cenie jednostkowej), potem rabat dokumentu
(procentowo na wartości każdej pozycji), na końcu VAT. Rabaty nie są sumowane do jednego procentu
(200 zł, -10% na pozycji, -10% na dokumencie = 162,00 zł, nie 160,00 zł).

**VAT: dwa tryby** (`Konfiguracja.tryb_vat` albo `oblicz(..., tryb_vat=...)`):

- `per_pozycja` - VAT zaokrąglany na każdej pozycji osobno, suma stawki = suma tych VAT-ów.
- `per_stawka` (domyślny) - VAT liczony raz na sumie stawki. Różnica groszy względem sumy
  VAT-ów z pozycji trafia do pozycji o największej wartości w tej stawce (remis: pierwsza),
  więc suma pozycji == suma dokumentu zawsze, a `netto + vat == brutto` w każdej pozycji.

**Rozkład korekty groszowej** (tylko `per_stawka`; opcja `rozklad_korekty` w `oblicz()` albo w
`Konfiguracja`):

- `"najwieksza"` (domyślnie, jak wyżej) - cała różnica na jednej pozycji. Skrajne przypadki dają
  dziwne pozycje: 1000 x 0,01 zł z VAT 23% daje 2,30 zł VAT na jednej pozycji, a ta sama pozycja
  od brutto potrafi dostać ujemne netto (-1,86 zł).
- `"proporcjonalnie"` - metoda największych reszt: część rozbijana każdej pozycji (vat od netto,
  netto od brutto) liczona dokładnie, obcięta w dół do grosza, a brakujące grosze dostają po 1 gr
  pozycje z największą częścią ułamkową (remis: niższy indeks). Każda pozycja odbiega od wartości
  dokładnej o mniej niż grosz; 1000 x 0,01 zł -> 230 pozycji z VAT 0,01 zł. Przy zerowej korekcie
  oba rozkłady dają identyczny wynik, sumy dokumentu i stawek są zawsze takie same.

W obu: suma pozycji == suma dokumentu i `netto + vat == brutto` w każdej pozycji.

`DokumentWynik.rozbieznosc_vat` = suma VAT liczona per pozycja minus per stawka (ile groszy
kosztuje wybór trybu).

### Przykłady (fikcyjny sklep ogrodniczy)

```python
from amounts_calc import oblicz, porownaj, sprawdz_spojnosc

pozycje = [
    {"ilosc": "3",  "cena_netto_jedn": "12,50", "rabat_proc": "10", "stawka_vat": 23},  # donica
    {"ilosc": "10", "cena_netto_jedn": "4.99",                        "stawka_vat": 8},   # nasiona
    {"ilosc": "2",  "cena_netto_jedn": "39.90", "rabat_proc": "5",  "stawka_vat": 23},  # sekator
    {"ilosc": "1",  "cena_netto_jedn": "0.33",                       "stawka_vat": "zw"},# ulotka
]
dok = oblicz(pozycje, rabat_dokumentu_proc=5)
dok.suma_netto, dok.suma_vat, dok.suma_brutto   # 151.80, 27.73, 179.53
dok.stawka("23")   # netto 104.08, vat 23.94, brutto 128.02
dok.stawka("zw")   # netto 0.31,   vat 0.00,  brutto 0.31

per_poz = oblicz(pozycje, rabat_dokumentu_proc=5, tryb_vat="per_pozycja")
per_poz.suma_vat                                # 27.72  (o grosz mniej)
porownaj(per_poz, dok)[0]                       # {'pole': 'suma_vat', 'a': 27.72, 'b': 27.73, 'roznica': 0.01}
sprawdz_spojnosc(dok)                           # []  - dokument spójny
```

Od brutto (cena na paragonie): `oblicz([{"ilosc": 2, "cena_brutto_jedn": "24.60", "stawka_vat": 23}],
tryb="brutto")` daje netto 40.00, vat 9.20, brutto 49.20; brutto wejściowe jest zawsze równe brutto
wyniku.

Regresja "3 x 0,33": trzy pozycje po 0,33 zł dają sumę 0,99 zł (nie 1,00), a VAT 23% to 0,24 zł
per pozycja albo 0,23 zł per stawka - dokładnie ta groszowa rozbieżność, o którą chodziło.

Wykrywanie niespójności w dokumencie z zewnątrz (słownik, np. zbudowany z wiersza bazy):

```python
sprawdz_spojnosc({"pozycje": [...], "suma_netto": "10.00", "suma_vat": "2.30", "suma_brutto": "12.31"},
                 tryb_vat="per_stawka")
# [{'kod': 'NETTO_PLUS_VAT_ROZNE_OD_BRUTTO', 'zakres': 'dokument', 'pole': 'suma_brutto',
#   'oczekiwano': Decimal('12.30'), 'jest': Decimal('12.31'), 'roznica': Decimal('0.01'), 'opis': ...}, ...]
```

Kody: `SUMA_POZYCJI_ROZNA_OD_DOKUMENTU`, `NETTO_PLUS_VAT_ROZNE_OD_BRUTTO`, `VAT_STAWKI_ROZNY_OD_SUMY`,
`PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI`, `SUMA_STAWEK_ROZNA_OD_DOKUMENTU` (stałe w `amounts_calc.bledy`).
`VAT_STAWKI_ROZNY_OD_SUMY` jest sprawdzany tylko dla `tryb_vat="per_stawka"` (przy `per_pozycja`
różnica jest zamierzona); jeśli dokument nie niesie trybu, podaj go jawnie.

Walidacja rzuca `BladWalidacji` (podklasa `ValueError`) z polami `kod`, `pole`: ujemna ilość lub
cena, rabat poza 0..100%, nieznana stawka, `float` zamiast `Decimal`/`int`/`str`, zły kod waluty
(wymagane np. `PLN`), brak ceny. Stawki `zw` i `np` mają vat = 0.

### Narzut a marża

- **narzut** = (cena - koszt) / **koszt** * 100
- **marża** = (cena - koszt) / **cena** * 100

Koszt 80 zł, cena 100 zł: narzut 25%, marża 20%. Narzut 100% to marża 50%; marża 100% jest
niemożliwa (cena nieskończona), narzut może przekraczać 100%. Funkcje w `amounts_calc.marza`:
`cena_z_narzutu`, `cena_z_marzy`, `narzut_z_cen`, `marza_z_cen`, `marza_z_narzutu`, `narzut_z_marzy`.
W dokumencie: pozycja z `koszt_zakupu_jedn` bez ceny + `oblicz(..., narzut_proc=25)` (albo
`marza_proc=20`) wylicza cenę netto z kosztu; działa tylko w trybie od netto.

### Sprawdzanie dokumentów z bazy

Cel: sprawdzić historyczne dokumenty bez wysyłania danych do repo, a wynik dostać od razu w postaci
nadającej się do decyzji (co jest błędem, co drobiazgiem, co niepełnymi danymi). Eksportujesz dokumenty
u siebie do pliku JSON, uruchamiasz CLI lokalnie i oglądasz tylko raport.

```
python -m amounts_calc.check dokumenty.json [--tryb-vat per_stawka|per_pozycja]
       [--pomin-typy KOREKTA,ROZ] [--json wynik.json] [--csv wynik.csv]
       [--dopusc-ujemne | --nie-dopuszczaj-ujemnych] [--ilosc-zestawu tak|nie]
       [--tryb-opcji auto|jawny|awaryjny] [--max-przyklady N] [--mapowanie mapowanie.json]
```

**Wartości ujemne - `--dopusc-ujemne` (domyślnie włączone).** W zapisanych dokumentach ujemna ilość
lub cena pozycji jest normalna: rabat zapisany jako osobna linia, korekta, zwrot, dokument w całości
ujemny albo o sumie zerowej. Dlatego CLI domyślnie przelicza je jak zwykłe (zaokrąglanie symetryczne,
patrz "Reguła zaokrąglania") i sprawdza spójność sum, a dokument z ujemnymi liniami nie wypada z raportu
z błędem `CENA_UJEMNA`. `--nie-dopuszczaj-ujemnych` przywraca ścisłą walidację (ujemna ilość/cena =
błąd `ILOSC_UJEMNA` / `CENA_UJEMNA`, dokument trafia do raportu jako błędny); ma sens, gdy ujemne wartości
w sprawdzanej próbce mogą być tylko pomyłką wprowadzania (np. nowe zamówienia sprzedaży, w których nie
wolno wystawiać zwrotów). W bibliotece (`oblicz`, `sprawdz_dokument`, `sprawdz_partie`) domyślnie jest
`dopusc_ujemne=False`, żeby nie zmieniać dotychczasowego zachowania; CLI przekazuje `True`.

**Wejście** - JSON: lista dokumentów (UTF-8, BOM dozwolony, końce linii LF lub CRLF). Liczby ułamkowe są
wczytywane jako `Decimal` (`parse_float=Decimal`, bez przechodzenia przez `float`); liczby mogą też być
stringami, również z przecinkiem (`"12,50"`). `NaN`/`Infinity` w pliku to błąd wejścia.

```json
[{"id": "FV/2024/0003", "typ": "FV",
  "suma_netto": "100.00", "suma_vat": "23.00", "suma_brutto": "123.05",
  "pozycje": [{"ilosc": 4, "cena_netto_jedn": "25.00", "rabat_proc": 0, "stawka_vat": 23,
               "netto": "100.00", "vat": "23.00", "brutto": "123.00"}]}]
```

Pola dokumentu: `id` (dowolna wartość JSON, przechodzi do wyniku bez zmian), `pozycje`, `suma_netto`,
`suma_vat`, `suma_brutto`; opcjonalnie `typ` (np. `FV`, `KOREKTA`, `ROZ`, `ZK`; nazwa pola konfigurowalna
przez `--mapowanie`), `tryb` (`netto` domyślnie albo `brutto` - wtedy pozycje niosą `cena_brutto_jedn`),
`waluta`, `rabat_dokumentu_proc`, `podsumowanie` (zapisane sumy per stawka: `[{stawka_vat, netto, vat,
brutto}]`). Pola pozycji: `ilosc`, `cena_netto_jedn` (lub `cena_brutto_jedn`), `rabat_proc`, `stawka_vat`
oraz zapisane `netto`, `vat`, `brutto`; opcjonalnie `id` i `parent_id` (zestawy, patrz niżej).

**Co jest sprawdzane** - dla każdego dokumentu (poza pominiętymi typami):

- (a) `sprawdz_spojnosc` na zapisanych danych (suma pozycji != suma dokumentu, netto+vat != brutto,
  VAT stawki != VAT z sumy - ten ostatni wg `--tryb-vat`, domyślnie `per_stawka`);
- (b) `oblicz()` z pozycji w OBU trybach VAT i `porownaj()` z zapisanymi sumami. Tryb "pasuje", gdy
  zgadzają się sumy dokumentu i podsumowanie stawek; różnice na poziomie pozycji są tylko liczone
  (`liczba_roznic_pozycji`), bo korekta groszowa może legalnie trafić na inną pozycję w systemie
  źródłowym. Wynik: `oba` / `per_stawka` / `per_pozycja` / `zaden`;
- (c) klasyfikacja przyczyn (poniżej). Jeden dokument może mieć kilka przyczyn; każda to osobny kod.

Błędny dokument (ujemna ilość, nieznana stawka, brak pola, śmieci zamiast liczby, zła hierarchia pozycji,
element nie będący obiektem) nie przerywa całości - trafia do raportu z kodem błędu i etapem (`wejscie`
albo `obliczenia`).

#### Kody przyczyn

| Kod | Kiedy |
|---|---|
| `POLGROSZ` | różnica <= 0,01 i któraś z porównywanych wartości jest niezaokrąglona (więcej niż 2 miejsca po przecinku, np. brutto `1845.005`). Ten sam grosz przy wartościach zaokrąglonych **nie** jest półgroszem - to zwykła niespójność. |
| `NAGLOWEK_ZERO` | wszystkie sumy nagłówka równe 0 przy niezerowych pozycjach |
| `NAGLOWEK_NIZSZY` / `NAGLOWEK_WYZSZY` | nagłówek różni się od sumy pozycji o więcej niż 0,01 (porównanie: netto, potem brutto, potem VAT; pokazuje różnicę, różnice na pozostałych polach i `mozliwe_pozycje` - pozycje o wartości równej różnicy, np. pominiętą albo policzoną drugi raz) |
| `ZESTAW_LICZONY_PODWOJNIE` | nagłówek = suma pozycji "liści" + kwoty pozycji nadrzędnych (zestawów) |
| `ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC` | **podpowiedź** do `ZESTAW_ROZNY_OD_DZIECI` dla zestawu o ilości N != 1: zapisane kwoty zestawu (netto, VAT i brutto) równają się 1 x suma dzieci, czyli ilość zestawu została pominięta (oczekiwane jest N x suma dzieci). To osobny, ważny przypadek: dzieci opisują 1 szt. zestawu. Dowód: `suma_dzieci` w przyczynie; `naglowek_liczony_z_zapisanych_zestawow` mówi, że nagłówek też pomija ilość |
| `ALTERNATYWY_W_SUMIE` | **informacja** (`informacja: true`, dokument jest w JSON/CSV niezależnie od statusu): **tylko tryb awaryjny** (dokument bez pola `tryb_opcji`): dokument ma pozycje najwyższego poziomu z `alternatywa` / `grupa_opcji` (opcje wzajemnie się wykluczają). Do sum wchodzi co najwyżej jedna opcja z grupy; przyczyna listuje grupy i opcje (`wliczona`), `dopasowanie` (`zgodne` albo `najblizsze`) i `naglowek_zawiera_wszystkie_opcje` (alternatywy dodane do sumy "po cichu") |
| `OPCJA_W_SUMIE` | **niespójność** (tryb jawny, pola `tryb_opcji` / `wybrana`): suma dokumentu zawiera pozycje trybu `opcja`, które nie mają `wybrana=true`. Przyczyna wskazuje te pozycje (netto/vat/brutto), `roznica_wzgledem_naglowka` (nagłówek - suma wliczona) i `suma_wliczona`. Wykrywana tylko wtedy, gdy nagłówek zgadza się (z tolerancją grosza) z sumą wliczoną + jakimś podzbiorem niewybranych opcji; inaczej zostaje sama `SUMA_POZYCJI_ROZNA_OD_DOKUMENTU` |
| `ALTERNATYWA_BEZ_WYBORU` | **niespójność** (tryb jawny): w grupie `grupa_opcji` żadna alternatywa nie ma `wybrana=true`, a zasada mówi, że do sumy wchodzi dokładnie jedna. Przyczyna listuje grupy i pozycje z kwotami, `roznica_wzgledem_naglowka` oraz `naglowek_pasuje_do` (która alternatywa dałaby sumę równą nagłówkowi) |
| `ALTERNATYWA_WIELE_WYBRANYCH` | **niespójność** (tryb jawny): w grupie więcej niż jedna alternatywa z `wybrana=true` (do sumy wchodzą wtedy wszystkie wybrane). Przyczyna: grupy z kwotami, `wybranych`, `naglowek_pasuje_do_jednej` oraz `naglowek_zawiera_wszystkie_wybrane` |
| `ZESTAW_NIEODSWIEZONY` | **podpowiedź** do `ZESTAW_ROZNY_OD_DZIECI` (bez wyjaśnienia narzutem/rabatem): pozycja nadrzędna nie została przeliczona po zmianie dziecka. Dowody (`dowody` w przyczynie): różnica równa wartości dokładnie jednego dziecka; nagłówek zgadza się z sumą dzieci, a zestaw nie; albo nagłówek zgadza się z zapisanymi kwotami zestawów (`naglowek_liczony_z_zapisanych_zestawow`) |
| `BRUTTO_ROWNE_NETTO` | **podpowiedź**: kwota brutto równa netto mimo stawki VAT > 0 (brak VAT w brutto) - pozycje, wiersz stawki albo sumy dokumentu; pomijane są kwoty, od których VAT zaokrągla się do mniej niż grosza |
| `ZESTAW_Z_NARZUTEM` | **informacja, nie błąd**: pozycja nadrzędna (zestaw) ma własny `narzut_proc` / `marza_proc` / `rabat_proc`, a jej zapisane kwoty różnią się od sumy dzieci dokładnie o ten narzut/rabat (netto w granicach 0,01, VAT i brutto z tolerancją 0,01 na dziecko). Taka różnica nie jest zgłaszana jako `ZESTAW_ROZNY_OD_DZIECI`. Jeśli nagłówek dokumentu = suma liści + różnice takich zestawów, sumy dokumentu też uznawane są za zgodne (`naglowek_uwzglednia_zestawy: true`) |
| `ILOSC_X_CENA` | wartość pozycji (netto w trybie od netto, brutto w trybie od brutto) różni się od `ilość x cena po rabacie` (z rabatem pozycji i dokumentu) o więcej niż 0,01; wskazuje pozycje i różnice |
| `VAT_WYLICZONY_ZGODNY` | pozycje nie mają pola VAT, ale mają `stawka_vat` i `netto`: VAT i brutto zostały wyliczone biblioteką (zapisane netto traktowane jako gotowa wartość pozycji, w obu trybach VAT) i **suma wyliczonego VAT zgadza się z VAT w nagłówku** (w którymkolwiek trybie; `tryby_vat` mówi w którym). Dokument przestaje być "niepełny" |
| `VAT_WYLICZONY_ROZNY` | jw., ale suma wyliczonego VAT różni się od nagłówka: `roznica` = nagłówek - wyliczony (dla bliższego trybu), `wg_stawek` (netto i VAT każdej stawki), `stawki_tlumaczace` (najmniejsze zbiory stawek, których VAT równa się różnicy, np. `[["8"]]` - nagłówek pomija VAT stawki 8%) i `roznica_brutto`. Różnica <= 0,01 przy niezaokrąglonym netto to `POLGROSZ` |
| `BRAK_VAT_W_POZYCJACH` | pozycje nie mają pola VAT **i** brak stawki (w którejś pozycji): **dane niepełne, nie błąd**. Nie da się wyliczyć VAT, więc liczone jest, co się da: netto (i brutto, jeśli jest) pozycji vs nagłówek, `ILOSC_X_CENA`, sumy nagłówka. Brak ilości, ceny lub stawki nie robi z takiego dokumentu błędu |
| `ILOSC_X_CENA_NARZUT` | pozycje z `cena_zakupu_jedn` i `narzut_proc` (albo `marza_proc`): cena sprzedaży = `zakup * (1 + narzut/100)` zaokrąglona do grosza, wartość = ilość x cena sprzedaży po rabacie (z rabatem dokumentu), porównywana z zapisanym `netto` (tolerancja 0,01). Zastępuje `ILOSC_X_CENA` dla takich pozycji. Dwa warianty opisu: **"cena sprzedaży nie zgadza się z zakup+narzut"** (niezgodność; szczegóły: `cena_sprzedazy_oczekiwana`, `cena_sprzedazy_zapisana`, `wyjasnienie` - czy pominięto narzut / rabat, `narzut_wynikowy`) oraz **"narzut/rabat tłumaczy różnicę"** (`informacja: true`: ilość x `cena_netto_jedn` bez narzutu by się nie zgadzała, a z narzutem się zgadza) |
| `NIEZGODNY_Z_BIBLIOTEKA` | żaden tryb VAT nie odtwarza zapisanych sum, a nic innego tego nie tłumaczy |

Kody spójności z `sprawdz_spojnosc` (`SUMA_POZYCJI_ROZNA_OD_DOKUMENTU`, `NETTO_PLUS_VAT_ROZNE_OD_BRUTTO`,
`VAT_STAWKI_ROZNY_OD_SUMY`, `PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI`, `SUMA_STAWEK_ROZNA_OD_DOKUMENTU`,
`ZESTAW_ROZNY_OD_DZIECI`) i kody błędów walidacji (np. `ILOSC_UJEMNA`, `BRAK_POLA`,
`NIEPOPRAWNA_HIERARCHIA`) trafiają do tego samego rozkładu kodów.

**Status dokumentu** (jeden, wg pierwszeństwa): `blad` > `niespojny` (jest niespójność inna niż POLGROSZ
albo przyczyna z tabeli poza POLGROSZ, `BRAK_VAT_W_POZYCJACH`, `VAT_WYLICZONY_ZGODNY`, `ZESTAW_Z_NARZUTEM`
i przyczynami z `informacja: true`, np. `ILOSC_X_CENA_NARZUT` w wariancie "narzut/rabat tłumaczy różnicę") > `niepelny` (tylko
`BRAK_VAT_W_POZYCJACH`) > `drobiazg` (tylko `POLGROSZ`) > `spojny`; `pominiety` dla typów z `--pomin-typy`.
Dokument z `BRAK_VAT_W_POZYCJACH` i prawdziwą niespójnością jest `niespojny`, a kod braku VAT zostaje
na liście przyczyn. Dokument z `VAT_WYLICZONY_ZGODNY` i bez innych przyczyn jest `spojny` (nie trafia do
JSON/CSV), ale jest liczony osobno: w 5. linii podsumowania jako "w tym VAT wyliczony z pozycji i zgodny
z nagłówkiem: N", a kod widać w rozkładzie kodów. `VAT_WYLICZONY_ROZNY` daje `niespojny`.

**Pomijanie typów i grupowanie.** Korekty i faktury rozliczeniowe mają z założenia sumy nagłówka różne od
sumy pozycji. `--pomin-typy KOREKTA,ROZ` (wielkość liter bez znaczenia) wyłącza je ze sprawdzania w całości
(nie są nawet parsowane, więc zepsute dane też nie przeszkadzają), a raport pokazuje je tylko jako liczbę
pominiętych. Raport jest zawsze grupowany po typie: dla każdego typu liczba dokumentów oraz spójne /
drobiazg / niepełne / niespójne / błędne / pominięte. Dokument bez typu trafia do grupy `(brak typu)`.

**Pozycje nadrzędne i podrzędne (zestawy), ZK i oferty.** Pozycja z `parent_id` wskazującym `id` innej
pozycji jest jej dzieckiem; pozycja mająca dzieci to wiersz zbiorczy: jej kwoty to suma dzieci i **nie
wchodzą** do sum dokumentu ani do podsumowania stawek (inaczej zestaw "krzesło + 4 nogi" byłby liczony
podwójnie). Zagnieżdżanie jest dozwolone, dzieci mogą mieć różne stawki VAT, a rabat dokumentu i VAT
dotyczą liści. Zapisane kwoty pozycji nadrzędnej mogą być pominięte (zostaną uzupełnione sumą dzieci);
jeśli są, muszą się zgadzać z sumą dzieci (`ZESTAW_ROZNY_OD_DZIECI`). Zła hierarchia (nieznany
`parent_id`, cykl, zdublowane `id` rodzica) to błąd `NIEPOPRAWNA_HIERARCHIA`. W `oblicz()` te same pola:
`{"id": "Z1", "ilosc": 1, "stawka_vat": 23}` (wiersz nadrzędny; własna cena i rabat są ignorowane) i dzieci
`{"parent_id": "Z1", ...}`.

**Przykład** (dane fikcyjne; plik `dokumenty.json` z 12 dokumentami: spójna faktura, faktura z niezaokrąglonym
brutto `1845.005`, faktura bez pola VAT w pozycjach ze stawkami (VAT wyliczony i zgodny), faktura bez VAT
i bez stawek, faktura z rabatem jako linią ujemną, kilka faktur z różnymi błędami (w tym nagłówek bez VAT
stawki 8%), korekta, faktura rozliczeniowa i ZK z zestawem policzonym drugi raz):

```
$ python -m amounts_calc.check dokumenty.json --pomin-typy KOREKTA,ROZ --json problemy.json --csv problemy.csv --max-przyklady 4
Do sprawdzenia: 5 (niespójne: 5, błędne: 0)
Tylko drobiazgi (POLGROSZ): 1
Niepełne dane (brak VAT w pozycjach): 1
Pominięte typy (KOREKTA, ROZ): 2
Bez uwag: 3 z 12 dokumentów (w tym VAT wyliczony z pozycji i zgodny z nagłówkiem: 1)

Sprawdzono dokumentów: 12 (w tym pominięto: 2)
  spójnych (bez przyczyn):              3
  z niespójnością zapisanych sum:       4
  z błędem (walidacja/struktura):       0
  w raporcie (JSON/CSV): 7

Rozkład kodów (liczba dokumentów):
  SUMA_POZYCJI_ROZNA_OD_DOKUMENTU          4
  SUMA_STAWEK_ROZNA_OD_DOKUMENTU           4
  BRAK_VAT_W_POZYCJACH                     1
  ILOSC_X_CENA                             1
  NAGLOWEK_NIZSZY                          1
  NAGLOWEK_WYZSZY                          1
  NAGLOWEK_ZERO                            1
  NETTO_PLUS_VAT_ROZNE_OD_BRUTTO           1
  POLGROSZ                                 1
  VAT_WYLICZONY_ROZNY                      1
  VAT_WYLICZONY_ZGODNY                     1
  ZESTAW_LICZONY_PODWOJNIE                 1

Zgodność zapisanych sum z biblioteką (dokumenty bez błędu: 8):
  pasuje per_stawka:  3
  pasuje per_pozycja: 3
  rozkład: oba=3, tylko per_stawka=0, tylko per_pozycja=0, żaden=5

Wg typu dokumentu:
  typ      dokumentów  spójne  drobiazg  niepełne  niespójne  błędne  pominięte
  FV                9       3         1         1          4       0          0
  KOREKTA           1       0         0         0          0       0          1
  ROZ               1       0         0         0          0       0          1
  ZK                1       0         0         0          1       0          0

Największe rozbieżności (4 z 5):
  1. id=ZK/1 (indeks 8): 163.89 (16389 gr) - NAGLOWEK_WYZSZY, SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, SUMA_STAWEK_ROZNA_OD_DOKUMENTU, ZESTAW_LICZONY_PODWOJNIE
  2. id=FV/4 (indeks 3): 98.40 (9840 gr) - NAGLOWEK_ZERO, SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, SUMA_STAWEK_ROZNA_OD_DOKUMENTU
  3. id=FV/6 (indeks 5): 36.90 (3690 gr) - ILOSC_X_CENA
  4. id=FV/5 (indeks 4): 12.30 (1230 gr) - NAGLOWEK_NIZSZY, SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, SUMA_STAWEK_ROZNA_OD_DOKUMENTU
```

Dokument `FV/5` ma nagłówek 80,00 netto przy pozycjach 80,00 + 10,00; w `problemy.json` jego przyczyna
wygląda tak (`mozliwe_pozycje` wskazuje pominiętą pozycję o wartości 10,00):

```json
{"kod": "NAGLOWEK_NIZSZY", "roznica": "-10.00", "pole": "suma_netto", "zrodlo_pozycji": "zapisane",
 "roznice_pol": {"suma_netto": "-10.00", "suma_vat": "-2.30", "suma_brutto": "-12.30"},
 "mozliwe_pozycje": [{"indeks": 1, "id": null, "pole": "netto", "wartosc": "10.00", "zestaw": false}],
 "opis": "nagłówek niższy od sumy pozycji o więcej niż 0,01 (netto)"}
```

Dokument `FV/8` nie ma VAT w pozycjach, ale ma stawki i netto; nagłówek (VAT 23,00) pomija VAT stawki 8%.
Biblioteka wylicza z pozycji 25,16 i wskazuje stawkę, która tłumaczy różnicę:

```json
{"kod": "VAT_WYLICZONY_ROZNY", "roznica": "-2.16", "vat_wyliczony": "25.16", "vat_naglowka": "23.00",
 "brutto_wyliczone": "152.16", "brutto_naglowka": "150.00", "roznica_brutto": "-2.16", "tryb_vat": "per_stawka",
 "wg_stawek": [{"stawka": "23", "netto": "100.00", "vat": "23.00"}, {"stawka": "8", "netto": "27.00", "vat": "2.16"}],
 "stawki_tlumaczace": [["8"]], "pole": "suma_vat", "opis": "..."}
```

**Wyjście tekstowe** zaczyna się od dokładnie 5 linii "co jest do zrobienia": ile dokumentów wymaga
uwagi (niespójne + błędne; bez drobiazgów i bez pominiętych typów), ile ma tylko `POLGROSZ`, ile ma
niepełne dane (tylko `BRAK_VAT_W_POZYCJACH`), ile pominięto (z listą typów) i ile jest bez uwag. Statusy
są rozłączne, więc te liczby sumują się do liczby dokumentów. Dalej: rozkład kodów (liczba dokumentów,
w których kod wystąpił), zgodność z trybami VAT, tabela wg typu i największe rozbieżności (bez drobiazgów
i pominiętych; `--max-przyklady` ogranicza długość listy).

**Wyjście JSON** (`--json wynik.json`, UTF-8, LF): lista dokumentów z problemem, czyli o statusie `blad`,
`niespojny`, `niepelny` albo `drobiazg` (spójne i pominięte nie są listowane). Wpis: `indeks` (pozycja
w pliku), `id` (bez zmian), `typ` (zawsze tekst), `status`, `dane` (`pelne` / `brak_kwot` / `brak_vat`),
`blad` (`{kod, pole, etap, wiadomosc}` albo `null`), `niespojnosci` (lista z `sprawdz_spojnosc`: `kod, zakres,
pole, oczekiwano, jest, roznica, opis`; wpisy będące półgroszem mają `drobiazg: true`; każdy ma `podpowiedz`), `przyczyny` (kody
z tabeli wyżej ze szczegółami), `pasuje` (`{per_stawka, per_pozycja}`), `tryb_pasujacy`, `rozbieznosci` (per
tryb VAT lista `{pole, zapisane, biblioteka, roznica}`; `roznica` = biblioteka - zapisane),
`liczba_roznic_pozycji`, `max_roznica`, `pominieto_pozycje`. Kwoty są stringami w postaci kanonicznej.

**Wyświetlanie liczb.** W raporcie tekstowym i JSON kwoty są normalizowane bez zbędnych zer na końcu, ale
z zachowaniem znaczących miejsc i co najmniej dwóch miejsc po przecinku: `140220.000000000000000000000` ->
`140220.00`, `1758.285000000000000000000` -> `1758.285`, `0E-10` -> `0.00`. Nic nie jest zaokrąglane.
Wyjątek: `id` przechodzi bez zmian (liczba z ułamkiem w `id` jest zapisywana tak, jak była w pliku).

**CSV** (`--csv wynik.csv`): jedna linia na dokument z problemem (te same dokumenty co w JSON), kolumny
`indeks;id;typ;status;kody;najwieksza_roznica;tryb_vat_pasuje;podpowiedz`. Separator `;`, kodowanie UTF-8 **z BOM**,
końce linii CRLF i przecinek dziesiętny w kwotach (`98,40`), żeby polski Excel otworzył plik dwuklikiem
bez kreatora importu. `kody` to wszystkie kody dokumentu oddzielone przecinkami, `tryb_vat_pasuje` to
`oba` / `per_stawka` / `per_pozycja` / `zaden` (puste dla dokumentu z błędem), `podpowiedz` to podpowiedź zbiorcza
(patrz "Oferty i zamówienia z narzutem"). Wartości tekstowe
zaczynające się od `=`, `+`, `@` lub `-` (przed nie-cyfrą) dostają apostrof, żeby arkusz nie wykonał ich
jako formuły.

```
indeks;id;typ;status;kody;najwieksza_roznica;tryb_vat_pasuje;podpowiedz
1;FV/2;FV;drobiazg;NETTO_PLUS_VAT_ROZNE_OD_BRUTTO, POLGROSZ, SUMA_POZYCJI_ROZNA_OD_DOKUMENTU, SUMA_STAWEK_ROZNA_OD_DOKUMENTU;0,005;zaden;
9;FV/7;FV;niepelny;BRAK_VAT_W_POZYCJACH;0,00;;
10;FV/8;FV;niespojny;VAT_WYLICZONY_ROZNY;2,16;;inna
```

**Kod wyjścia:** 0 - nic nie wymaga uwagi (drobiazgi, dane niepełne i pominięte typy nie liczą się),
1 - są dokumenty niespójne lub błędne (przy `--nie-dopuszczaj-ujemnych` także z ujemnymi liniami), 2 - błąd wejścia (brak pliku, zły JSON, wejście nie jest listą,
złe mapowanie, `NaN` w pliku, błąd zapisu pliku wyjściowego).

**Dopasowanie do dowolnego schematu - `--mapowanie`.** Plik JSON wskazuje, pod jakimi nazwami szukać
pól kanonicznych (nazwa albo lista nazw; ścieżka z kropką schodzi w zagnieżdżone obiekty). Nazwy z
mapowania mają pierwszeństwo przed domyślnymi (`netto`, `kwota_vat`, `brutto`, `linie`, `qty`,
`typ`/`typ_dokumentu`/`rodzaj`...; pełna lista w `amounts_calc/adapter.py`); nieznany klucz to błąd, żeby
literówka nie zadziałała po cichu. Wartość `null` w danych jest traktowana jak brak pola.

```json
{"id": "nr_dok", "typ": "kod_rodzaju",
 "suma_netto": "kwota_netto", "suma_vat": ["podatek", "kwota_vat"], "suma_brutto": "razem",
 "pozycje": "wiersze",
 "pozycja": {"id": "nr_wiersza", "parent_id": "nr_nadrzednego", "ilosc": "szt", "cena_netto_jedn": "cena",
             "stawka_vat": "stawka_proc", "netto": "wart_n", "vat": "wart_v", "brutto": "wart_b"}}
```

W kodzie ten sam mechanizm to `z_wiersza(wiersz, mapowanie=None, pozycje=None)`, np. gdy pozycje
pobierasz osobnym zapytaniem: `z_wiersza(naglowek, mapowanie, pozycje=lista_wierszy_pozycji)`.
Wynik można podać do `sprawdz_spojnosc`, `porownaj` i `oblicz`.

Zalecany tryb pracy: eksport próbki (np. ostatni miesiąc) do JSON -> CLI lokalnie z `--pomin-typy` ->
z pierwszych 5 linii widać, ile jest do zrobienia, z `--csv` pracujesz w Excelu po `status` i `kody`, a `id`
dokumentów z problemami sprawdzasz już w aplikacji. Raportu z prawdziwymi `id` nie wkładaj do repo.

### Oferty i zamówienia z narzutem

Pozycje ofert i zamówień mają zwykle cenę **zakupu** i narzut (albo marżę), a cena sprzedaży z nich wynika.
W takich danych `cena_netto_jedn` bywa po prostu ceną zakupu, więc zwykłe `ilość x cena_netto_jedn` nie
zgadza się z zapisanym `netto` w prawie każdej pozycji. Dla pozycji z poniższymi polami CLI i `oblicz()`
liczą cenę sprzedaży z zakupu i narzutu.

| Pole pozycji | Znaczenie |
|---|---|
| `cena_zakupu_jedn` | jednostkowa cena zakupu |
| `narzut_proc` | narzut %: `cena sprzedaży = zakup * (1 + narzut/100)` |
| `marza_proc` | alternatywnie marża %: `cena sprzedaży = zakup / (1 - marża/100)` (nie razem z narzutem: `NARZUT_I_MARZA`) |

Reguła (tryb od netto; w trybie od brutto te pola są ignorowane):

1. cena sprzedaży jednostkowa = zakup z narzutem (marżą), **zaokrąglona do grosza** według konfiguracji
   (`Konfiguracja.kwota`; `marza.cena_sprzedazy`) - to jedyne zaokrąglenie ceny sprzedaży,
2. cena po rabacie pozycji = `cena sprzedaży * (1 - rabat/100)` -> 4 miejsca,
3. wartość netto = `ilość * cena po rabacie` -> grosz, potem rabat dokumentu jak zwykle.

Narzut ma pierwszeństwo przed `cena_netto_jedn`. Pola zakupu i narzutu są potrzebne **oba** (sam narzut
bez ceny zakupu jest ignorowany). Różnica względem narzutu dokumentu (`oblicz(..., narzut_proc=...)`
z `koszt_zakupu_jedn`): tam cena jest zaokrąglana do miejsc ceny (4), tu do grosza.

```python
from amounts_calc import oblicz

d = oblicz([
    {"ilosc": 2, "cena_zakupu_jedn": "60.00",  "narzut_proc": 25, "stawka_vat": 23},               # sprzedaż 75,00
    {"ilosc": 1, "cena_zakupu_jedn": "400.00", "narzut_proc": 20, "rabat_proc": 10, "stawka_vat": 23},  # 480,00 -10%
])
d.suma_netto, d.suma_vat, d.suma_brutto      # 582.00, 133.86, 715.86
```

**Sprawdzanie w CLI - `ILOSC_X_CENA_NARZUT`.** Dla pozycji z narzutem zamiast `ILOSC_X_CENA` porównywane jest
`ilość x cena sprzedaży (po rabacie)` z zapisanym `netto` (tolerancja 0,01). Kod ma dwa warianty opisu:

- **"cena sprzedaży nie zgadza się z zakup+narzut"** - niezgodność (dokument `niespojny`). Szczegóły w
  `pozycje[]`: `oczekiwane` i `zapisane` netto, `cena_sprzedazy_oczekiwana`, `cena_sprzedazy_zapisana`,
  `wyjasnienie` (np. "narzut nie został zastosowany", "rabat nie został zastosowany", "nie zastosowano ani
  narzutu, ani rabatu") i `narzut_wynikowy` - jaki narzut wynikałby z zapisanej wartości;
- **"narzut/rabat tłumaczy różnicę"** - informacja (`informacja: true`, w rozkładzie kodów z dopiskiem
  `(informacja)`): zwykłe `ilość x cena_netto_jedn` by się nie zgadzało, a z narzutem zgadza się. To nie błąd.

`cena_netto_jedn` równa cenie zakupu jest traktowana jako cena zakupu; jeśli jest inna, jest traktowana jako
zapisana cena sprzedaży i porównywana z `zakup + narzut` (rozbieżność to ten sam kod).

**Zestawy z własnym narzutem lub rabatem.** Pozycja nadrzędna (zestaw) może mieć własne `narzut_proc` /
`marza_proc` / `rabat_proc`. Jeśli jej zapisane kwoty różnią się od sumy dzieci dokładnie o ten narzut/rabat
(`suma dzieci * (1 + narzut/100) * (1 - rabat/100)`; netto w granicach 0,01, VAT i brutto z tolerancją 0,01 na
dziecko), to jest **informacja** `ZESTAW_Z_NARZUTEM`, a nie `ZESTAW_ROZNY_OD_DZIECI`. Jeśli nagłówek dokumentu
= suma liści + takie różnice zestawów najwyższego poziomu, sumy dokumentu także są uznawane za zgodne
(`naglowek_uwzglednia_zestawy: true`); nagłówek równy samej sumie dzieci jest zgodny jak dotąd. Bez własnego
narzutu (albo gdy kwota do niego nie pasuje) zostaje `ZESTAW_ROZNY_OD_DZIECI`. Zestawy zagnieżdżone są
oceniane względem swoich liści. `oblicz()` nie stosuje narzutu zestawu do sum (sumy liczą się z liści).

**Podpowiedź przyczyny.** Każda niespójność w JSON ma pole `podpowiedz`, a dokument `podpowiedz` zbiorczą
(CSV: ostatnia kolumna, podsumowanie: osobna linia z liczbą dokumentów):

| Podpowiedź | Znaczenie |
|---|---|
| `ZESTAW_NIEODSWIEZONY` | zestaw nie został przeliczony po zmianie dziecka. Dowody (`dowody` w przyczynie): różnica równa wartości dokładnie jednego dziecka; nagłówek zgadza się z sumą dzieci, a zestaw nie; nagłówek zgadza się z zapisanymi kwotami zestawów |
| `BRUTTO_ROWNE_NETTO` | brutto równe netto mimo stawki VAT > 0 (brak VAT w brutto), dla pozycji, wiersza stawki albo sum dokumentu; kwoty, od których VAT zaokrągla się do mniej niż grosza, są pomijane |
| `POLGROSZ` | drobiazg (patrz kody przyczyn) |
| `inna` | nic z powyższego |

Oba pierwsze kody pojawiają się też jako osobne przyczyny (`ZESTAW_NIEODSWIEZONY`, `BRUTTO_ROWNE_NETTO`) w
rozkładzie kodów i w `kody`.

**Mapowanie nazw** (`--mapowanie`) obejmuje nowe pola pozycji bez zmiany kodu:

```json
{"pozycja": {"cena_zakupu_jedn": "kosztzak", "narzut_proc": ["narzut_handl", "narzut"], "marza_proc": "marza_handl"}}
```

Domyślne aliasy: `cena_zakupu_jedn` = `cena_zakupu` / `zakup`, `narzut_proc` = `narzut`, `marza_proc` = `marza`.

**Przykład** (dane fikcyjne, plik `oferty.json`: poprawna oferta z narzutem, oferta bez zastosowanego narzutu, ZK z
zestawem "krzesło + 4 nogi" z narzutem zestawu 10%, ZK z zestawem nieodświeżonym po dodaniu nóg, faktura z brutto
równym netto):

```
$ python -m amounts_calc.check oferty.json --json problemy.json --csv problemy.csv --max-przyklady 3
Do sprawdzenia: 3 (niespójne: 3, błędne: 0)
Tylko drobiazgi (POLGROSZ): 0
Niepełne dane (brak VAT w pozycjach): 0
Pominięte typy: brak (patrz --pomin-typy)
Bez uwag: 2 z 5 dokumentów

Sprawdzono dokumentów: 5 (w tym pominięto: 0)
  spójnych (bez przyczyn):              2
  z niespójnością zapisanych sum:       2
  z błędem (walidacja/struktura):       0
  w raporcie (JSON/CSV): 3

Rozkład kodów (liczba dokumentów):
  BRUTTO_ROWNE_NETTO                       1
  ILOSC_X_CENA_NARZUT                      1
  ILOSC_X_CENA_NARZUT (informacja)         1
  NETTO_PLUS_VAT_ROZNE_OD_BRUTTO           1
  ZESTAW_NIEODSWIEZONY                     1
  ZESTAW_ROZNY_OD_DZIECI                   1
  ZESTAW_Z_NARZUTEM                        1

Podpowiedź przyczyny niespójności (liczba dokumentów): ZESTAW_NIEODSWIEZONY=1, BRUTTO_ROWNE_NETTO=1

Zgodność zapisanych sum z biblioteką (dokumenty bez błędu: 5):
  pasuje per_stawka:  3
  pasuje per_pozycja: 3
  rozkład: oba=3, tylko per_stawka=0, tylko per_pozycja=0, żaden=2

Wg typu dokumentu:
  typ     dokumentów  spójne  drobiazg  niepełne  niespójne  błędne  pominięte
  OFERTA           2       1         0         0          1       0          0
  ZK               2       1         0         0          1       0          0
  FV               1       0         0         0          1       0          0

Największe rozbieżności (3 z 3):
  1. id=OF/2 (indeks 1): 36.90 (3690 gr) - ILOSC_X_CENA_NARZUT
  2. id=ZK/2 (indeks 3): 36.90 (3690 gr) - ZESTAW_NIEODSWIEZONY, ZESTAW_ROZNY_OD_DZIECI
  3. id=FV/9 (indeks 4): 23.00 (2300 gr) - BRUTTO_ROWNE_NETTO, NETTO_PLUS_VAT_ROZNE_OD_BRUTTO
```

CSV (`problemy.csv`):

```
indeks;id;typ;status;kody;najwieksza_roznica;tryb_vat_pasuje;podpowiedz
1;OF/2;OFERTA;niespojny;ILOSC_X_CENA_NARZUT;36,90;zaden;
3;ZK/2;ZK;niespojny;ZESTAW_NIEODSWIEZONY, ZESTAW_ROZNY_OD_DZIECI;36,90;oba;ZESTAW_NIEODSWIEZONY
4;FV/9;FV;niespojny;BRUTTO_ROWNE_NETTO, NETTO_PLUS_VAT_ROZNE_OD_BRUTTO;23,00;zaden;BRUTTO_ROWNE_NETTO
```

Dokument `OF/1` (poprawna oferta) ma w raporcie tylko informację `ILOSC_X_CENA_NARZUT (informacja)`, a `ZK/1` -
`ZESTAW_Z_NARZUTEM`; oba są `spojny` i nie trafiają do JSON ani CSV. Przyczyna z `problemy.json` dla `OF/2`:

```json
{"kod": "ILOSC_X_CENA_NARZUT", "opis": "cena sprzedaży nie zgadza się z zakup+narzut", "pole": "netto",
 "liczba": 1, "roznica": "-30.00",
 "pozycje": [{"indeks": 0, "id": null, "zapisane": "120.00", "oczekiwane": "150.00", "roznica": "-30.00",
              "cena_sprzedazy_oczekiwana": "75.00", "cena_sprzedazy_zapisana": null,
              "wyjasnienie": "narzut nie został zastosowany", "narzut_wynikowy": "0.00"}]}
```

### Ilość pozycji zbiorczej (zestawu)

**Model:** pozycja zbiorcza ma ilość `N`, a jej dzieci opisują **jeden** zestaw (ilości i ceny dzieci
na 1 szt. zestawu). Wartość zestawu = `N x suma dzieci` (netto, VAT i brutto osobno; `kwota()` wg reguły
zaokrąglania, przy `N = 1` bez dodatkowego zaokrąglania). Podzestawy liczone rekurencyjnie (mnożnik liścia
= iloczyn `N` przodków), maksymalna głębokość 10 poziomów (głębiej: `NIEPOPRAWNA_HIERARCHIA`).

* Do sumy dokumentu wchodzi wartość zestawu najwyższego poziomu (`N x dzieci`); dzieci nie są liczone drugi raz.
* Zestaw zapisany inaczej niż `N x dzieci` daje `ZESTAW_ROZNY_OD_DZIECI`; gdy zapisane kwoty równają się
  `1 x dzieci` przy `N != 1`, podpowiedź to `ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC` (ilość pominięta w zestawie).
  Różnice <= 0,01 to zaokrąglenie. Ułamkowe `N` (0,5; 2,5) i `N = 0` są dozwolone; netto, VAT i brutto
  zestawu są zaokrąglane niezależnie, więc `netto + vat` może różnić się od `brutto` o grosz.
* Opcje: CLI `--ilosc-zestawu=tak|nie` (domyślnie `tak`); biblioteka `oblicz(..., ilosc_zestawu=False)`
  domyślnie zachowuje stare zachowanie (ignoruje `ilosc` nadrzędnej), `sprawdz_spojnosc(..., ilosc_zestawu=)`
  dotyczy tylko wejścia słownikowego. Adapter rozpoznaje aliasy `ilosc_zestawu`, `alternatywa`/`opcja`, `grupa_opcji`.
* Podsumowanie stawek: wkład zestawu rozkładany na stawki liści (zaokrąglenie na stawkę, różnica na największą),
  tolerancja VAT na stawkę rośnie z sumą mnożników (0,005 x suma).

**Alternatywy w trybie awaryjnym:** patrz następna sekcja ("Opcje i alternatywy").

### Opcje i alternatywy

Pozycje **najwyższego poziomu** (nie dzieci zestawu) mogą być opcjonalne. Dziś są dwa sposoby, a biblioteka sama wybiera:

* **tryb jawny** - aplikacja zapisuje w pozycjach, co jest opcją i co klient wybrał;
* **tryb awaryjny** - dla dokumentów bez tych pól: stare pola `alternatywa` / `grupa_opcji` i dobór kombinacji
  najlepiej pasującej do nagłówka (z rundy 6).

| Pole pozycji | Znaczenie |
|---|---|
| `tryb_opcji` | `"brak"` (domyślny: zwykła pozycja), `"opcja"` albo `"alternatywa"` (wielkość liter bez znaczenia; puste = nie podano) |
| `grupa_opcji` | nazwa grupy alternatyw; alternatywy bez nazwy tworzą jedną grupę domyślną. Dla `opcja` ignorowane |
| `wybrana` | `true`/`false` (też `"tak"`/`"nie"`, `1`/`0`; puste = nie) - czy pozycja wchodzi do sumy |

**Model (tryb jawny).** Tryb jawny obowiązuje w dokumencie, jeśli **którakolwiek** pozycja najwyższego poziomu ma
niepustą wartość `tryb_opcji`. Wtedy suma dokumentu = pozycje `brak` + pozycje `alternatywa` z `wybrana=true` +
pozycje `opcja` z `wybrana=true`. Nie ma żadnego doboru kombinacji do nagłówka, a pola `alternatywa` ani `grupa_opcji`
jako znacznika alternatywy nie są wtedy brane pod uwagę (`grupa_opcji` tylko nazywa grupę); pozycja bez `tryb_opcji`
w takim dokumencie to `brak`. Pola opcji u dzieci zestawu są ignorowane. Zestaw z `ilosc` i dziećmi (runda 6) może
być opcją albo alternatywą: wnosi wtedy `N x dzieci`, a jego dzieci nie są liczone drugi raz.

**Kody** (kwoty `netto`/`vat`/`brutto` pozycji i `roznica_wzgledem_naglowka` są w przyczynie):

| Kod | Rodzaj | Kiedy |
|---|---|---|
| `OPCJA_W_SUMIE` | niespójność | nagłówek zawiera opcje bez `wybrana=true` |
| `ALTERNATYWA_BEZ_WYBORU` | niespójność | grupa bez żadnej wybranej |
| `ALTERNATYWA_WIELE_WYBRANYCH` | niespójność | grupa z więcej niż jedną wybraną |
| `ALTERNATYWY_W_SUMIE` | informacja | tylko tryb awaryjny |

Trzy pierwsze są niespójnościami (pojawiają się w `sprawdz_spojnosc` jako wpisy `zakres: "grupa:<nazwa>"`, a
`OPCJA_W_SUMIE` jako wpis `dokument` obok `SUMA_POZYCJI_ROZNA_OD_DOKUMENTU`; w CLI dodatkowo jako przyczyny, które
ustawiają status `niespojny`), bo łamią zasadę modelu albo oznaczają, że zapisana suma nie odpowiada wyborowi klienta.
`ALTERNATYWY_W_SUMIE` zostaje informacją, bo w trybie awaryjnym wybór jest tylko zgadywany.

**`poza_suma`.** `sprawdz_spojnosc` zwraca `WynikSpojnosci` - zwykłą listę niespójności (pusta = spójny; wszystko
działa jak dotąd) z polami `poza_suma` i `opcje`. `poza_suma` to suma niewliczonych pozycji trybu `opcja`:
`{"netto", "vat", "brutto", "pozycje": [{indeks, id, netto, vat, brutto}]}` (do pokazania pod sumą w PDF; zera i pusta
lista, gdy takich opcji nie ma). Niewybrane alternatywy nie są "poza sumą" - wykluczają się z wybraną. Zestaw wnosi
`N x dzieci`.

**Raport CLI (`poza_suma`).** Każdy dokument z opcjami `opcja` albo z niewybranymi alternatywami ma w wyniku CLI pole
`poza_suma` (w JSON; `null` dla pozostałych) i trafia do raportu JSON/CSV nawet wtedy, gdy jest spójny:
`{"netto", "vat", "brutto", "pozycje": [...], "alternatywy_niewybrane": [{indeks, id, grupa, netto, vat, brutto}]}`.
Kwoty główne to suma niewybranych opcji (w dokumencie bez VAT w pozycjach `vat` ma wartość `null`), alternatywy są
wymienione osobno. W CSV są kolumny `poza_suma_netto`, `poza_suma_vat`, `poza_suma_brutto` (przed `podpowiedz`).
Dotyczy też trybu awaryjnego: niewybrana kombinacja pozycji z `alternatywa` / `grupa_opcji` trafia do
`alternatywy_niewybrane`.

**Nagłówek z opcją mimo błędu narzutu.** `OPCJA_W_SUMIE` (i `naglowek_zawiera_wszystkie_opcje` w
`ALTERNATYWY_W_SUMIE`) nie wymaga już dokładnej zgodności: dobierany jest podzbiór niewybranych opcji, z którym
suma pozycji jest najbliżej nagłówka, liczona z kwot ZAPISANYCH w pozycjach (`netto`/`vat`/`brutto` pozycji), a nie z
ceny x narzut. Pole `dopasowanie` mówi, jak pewne jest wskazanie: `zgodne` (różnica w granicach grosza) albo `najblizsze`
(nagłówek różni się od tej sumy, np. o błąd narzutu `ILOSC_X_CENA_NARZUT`, ale jest nią wyraźnie bliżej niż samą sumą
wliczoną i reszta nie przekracza 25% kwot dodanych opcji); `reszta` to nagłówek - (suma wliczona + wskazane opcje).
To heurystyka: przy opcji bardzo małej wobec błędu nagłówka może wskazać opcję niesłusznie, a przy większym
rozjeździe niż 25% nie wskaże nic (zostaje `SUMA_POZYCJI_ROZNA_OD_DOKUMENTU`).

**CLI.** Nic nowego nie jest wymagane. `--tryb-opcji auto|jawny|awaryjny` (domyślnie `auto`: jawny, gdy dokument ma
pole `tryb_opcji`, inaczej awaryjny); `jawny` wymusza tryb jawny (bez pól wszystko jest `brak`), `awaryjny` ignoruje
`tryb_opcji` i `wybrana`. Nazwy pól w bazie mapujesz tak jak resztę pól pozycji (`"pozycja": {"tryb_opcji": "rodzaj_linii",
"wybrana": "w_ofercie"}`); wbudowane aliasy: `tryb_pozycji`, `wybrany`, `wliczona`. W bibliotece: `oblicz(..., tryb_opcji=)`,
`sprawdz_spojnosc(..., tryb_opcji=)`, `dokument_z_slownika(..., tryb_opcji=)` (albo klucz `"tryb_opcji"` w dokumencie)
i `sprawdz_dokument(..., tryb_opcji=)`; w trybie jawnym `oblicz()` ignoruje `wlaczone_alternatywy`.

Przykład (fikcyjna oferta: usługa bazowa 100,00, opcja 50,00 niewybrana, alternatywy w grupie `kolor`: 200,00
wybrana i 300,00; suma netto = 100 + 200 = 300,00):

```json
{"id": "OF/10", "typ": "OF", "suma_netto": "300.00", "suma_vat": "69.00", "suma_brutto": "369.00",
 "pozycje": [
   {"id": "P1", "ilosc": 1, "stawka_vat": 23, "netto": "100.00", "vat": "23.00", "brutto": "123.00"},
   {"id": "P2", "ilosc": 1, "stawka_vat": 23, "netto": "50.00", "vat": "11.50", "brutto": "61.50",
    "tryb_opcji": "opcja", "wybrana": false},
   {"id": "P3", "ilosc": 1, "stawka_vat": 23, "netto": "200.00", "vat": "46.00", "brutto": "246.00",
    "tryb_opcji": "alternatywa", "grupa_opcji": "kolor", "wybrana": true},
   {"id": "P4", "ilosc": 1, "stawka_vat": 23, "netto": "300.00", "vat": "69.00", "brutto": "369.00",
    "tryb_opcji": "alternatywa", "grupa_opcji": "kolor", "wybrana": false}]}
```

Ten dokument jest spójny, a `sprawdz_spojnosc(...).poza_suma` to `50.00 / 11.50 / 61.50`. Gdyby nagłówek miał netto
`350.00` (opcja policzona mimo `wybrana=false`), CLI zgłosi `OPCJA_W_SUMIE` (przyczyna z `pozycje` = P2 i
`roznica_wzgledem_naglowka.netto` = `50.00`), a dla grupy `kolor` bez żadnej wybranej - `ALTERNATYWA_BEZ_WYBORU`
z `naglowek_pasuje_do` wskazującym pozycję, której dodanie daje sumę nagłówka.

### Złote przypadki (test kontraktowy dla aplikacji)

```
python -m amounts_calc.zlote --seed 1 --n 500 > zlote.json
```

Deterministyczny generator (to samo `--seed` i `--n` daje ten sam plik bajt w bajt; przy rosnącym `--n` kolejne
przypadki są dopisywane na końcu) zestawu kwot z oczekiwanymi wynikami wg zasady aplikacji: **netto do grosza
(ROUND_HALF_UP, symetrycznie względem zera), VAT = round(netto * stawka / 100, 2) liczony od netto pozycji i zaokrąglany
per pozycja, brutto = netto + VAT**, stawki `zw`/`np` mają VAT 0. Plik jest samodzielny: wystarczy dowolny parser JSON,
nie trzeba tej biblioteki (moduł `zlote.py` liczy oczekiwane wartości własnym kodem, bez `oblicz()`, więc test repo
"generator == `oblicz()`" porównuje dwie niezależne implementacje).

```json
{"format": "zlote-przypadki/1", "seed": 1, "zasada": "...", "stawki": [23, 8, 5, 0, "zw", "np"],
 "przypadki": [
  {"nazwa": "49,50 przy 23% (VAT 11,385 -> 11,39)", "rodzaj": "pozycja", "netto": "49.50", "stawka": 23,
   "oczekiwane": {"netto": "49.50", "vat": "11.39", "brutto": "60.89"}},
  {"nazwa": "3 x 0,33 przy 23% (VAT per pozycja 3 x 0,08)", "rodzaj": "suma",
   "pozycje": [{"netto": "0.33", "stawka": 23}, {"netto": "0.33", "stawka": 23}, {"netto": "0.33", "stawka": 23}],
   "oczekiwane": {"netto": "0.99", "vat": "0.24", "brutto": "1.23"}},
  {"nazwa": "3 x 33,33 z rabatem 10%", "rodzaj": "rabat", "ilosc": "3", "cena_netto_jedn": "33.33",
   "rabat_proc": "10", "stawka": 23, "oczekiwane": {"netto": "89.99", "vat": "20.70", "brutto": "110.69"}}]}
```

Rodzaje: `pozycja` (`netto` jako tekst, może mieć więcej niż 2 miejsca, np. `12.345`), `rabat` (`netto` pozycji = ilość x cena
po rabacie, cena zaokrąglona do 4 miejsc, wartość do grosza) i `suma` (lista pozycji; `oczekiwane` to sumy pozycji,
VAT per pozycja, dlatego w aplikacji porównuj z sumą `kwoty_pozycji`, a nie z VAT liczonym od sumy). Na początku
zawsze są stałe przypadki graniczne (półgrosze, 1 gr, stawki `zw`/`np`/0, kwota 1234567890123,45, ujemne i zwroty, rabat
100%), potem losowe: zwykłe, półgroszowe (VAT dokładnie w pół grosza), małe, duże, ujemne, niezaokrąglone, sumy
(2-30 pozycji, czasem z ujemną) i rabaty. `--n` to liczba przypadków łącznie (przy `--n` mniejszym niż liczba
granicznych zwracane jest pierwsze `n`). W aplikacji (Python): dla `pozycja` porównaj
`kwoty_pozycji(Decimal(p["netto"]), p["stawka"])` z `p["oczekiwane"]` jako `Decimal`.

### Skaner kodu aplikacji

```
python -m amounts_calc.skan_kodu SCIEZKA [SCIEZKA...] [--json w.json] [--csv w.csv]
       [--zrodlo-prawdy funkcje.txt] [--pomin GLOB]... [--tryb pelny|istotne]
       [--waznosc wysoka|srednia|niska]
```

Szuka w kodzie aplikacji (Python / Flask, TypeScript i JavaScript / React oraz SQL, w tym zapytania w tekstach Pythona
i TS) miejsc, które **liczą kwoty po swojemu** zamiast wspólną funkcją `kwoty_pozycji(wartosc_netto, mnoznik_vat) ->
(netto, vat, brutto)`, i mogą dawać niespójności groszowe. Zasada: VAT od netto pozycji, zaokrąglany per pozycja
(ROUND_HALF_UP), brutto = netto + VAT. Tylko stdlib; ~3 s na 535 plików Pythona. Kod wyjścia: 0 = brak znalezisk,
1 = są znaleziska, 2 = błąd wejścia (brak ścieżki, nieczytelny plik `--zrodlo-prawdy`).

| Kod | Ważność | Co wykrywa |
|---|---|---|
| `VAT_MNOZENIE_BEZ_ZAOKRAGLENIA` | wysoka | `* 1.23`, `* 1.08`, `* Decimal("1.23")`, `* (1 + vat/100)`, `* (100 + stawka)/100`, `* stawka / 100`, `* 0.23` (też w SQL i w tekstach), gdy w instrukcji nie ma `round`/`quantize`/`kwoty_pozycji`/`ROUND_HALF_*`/`numeric(.,2)` |
| `JS_ZAOKRAGLENIE_FLOAT` | wysoka / średnia | `Math.round(x * 100) / 100`, `parseFloat(x.toFixed(2))`, `Number(x.toFixed(2))` (wysoka); samo `.toFixed(2)` na kwocie (średnia) |
| `BRUTTO_VAT_BEZ_WSPOLNEJ_FUNKCJI` | wysoka / średnia | zapis `wartosc_brutto`, `suma_brutto`, `kwota_vat`, `wartosc_vat` (także `wartoscBrutto`, klucze słowników, `kwargs`) wyrażeniem: z `*` `/` `round` (wysoka), z samym `+`/`-` (średnia); w SQL: `UPDATE ... SET`, `INSERT`, `GENERATED ALWAYS AS`, trigger (`NEW.x := ...`). Nie zgłasza: przypisania zmiennej, `sum(...)`, `+=`, akumulacji (`suma = suma + x`), konwersji z wiersza, definicji kolumn ORM |
| `NETTO_Z_BRUTTO_DZIELENIE` | średnia | `/ 1.23`, `/ (1 + stawka/100)`, `brutto * 100 / 123` (liczenie netto z brutto bez jawnej decyzji) |
| `ROUND_PYTHON_BANKOWE` | wysoka | `round(kwota, 2)` Pythona na kwocie (zaokrąglenie bankowe, nie ROUND_HALF_UP) |
| `ROUND_NIEPOPRAWNE_MIEJSCA` | wysoka | `round(kwota)`, `round(kwota, 0/1)`, SQL `ROUND(kwota)` / `ROUND(kwota, 0/1)`, `toFixed(0/1)`, `Math.round(kwota)` |
| `FLOAT_W_FUNKCJI_KWOTOWEJ` | średnia | `float(...)` na kwocie, `def ...(x: float) -> float` w funkcji o nazwie kwotowej, SQL `float`/`real`/`double precision` w kolumnie kwotowej |
| `SUMOWANIE_NIESPOJNE` | średnia | w jednym zapytaniu `SUM(...brutto...)` obok `SUM(...netto...)` |
| `STAWKA_VAT_TEKSTOWA` | niska | `'23%'` (obok słowa vat/stawka), `.replace('%', '')` na stawce |
| `STAWKA_ZW_NP_POMINIETA` | średnia | `stawka IN (23, 8, 5)` / lista `(23, 8, 5)` bez `zw`/`np`, `NOT IN ('zw','np')`, `stawka != 'zw'`, `stawka > 0`, `int/float/Decimal/parseInt/Number(stawka)` bez jawnej obsługi `zw`/`np` w pobliżu (8 linii) |
| `FUNKCJA_POZA_ZRODLEM_PRAWDY` | niska | definicja funkcji (Python, TS: `function`, strzałkowa, metoda; SQL `CREATE FUNCTION`) o nazwie z członem brutto/netto/vat/kwota/kwoty/suma/sumy/sumuj, której nie ma w liście źródeł prawdy |

**Tryby: `--tryb istotne` (domyślny) i `pelny`.** Na prawdziwym kodzie większość znalezisk to szum, więc każde znalezisko ma
dwie ważności: jak dotąd (tryb `pelny`, bez zmian) i *po odszumieniu*. Tryb `istotne` pokazuje tylko te, które po
odszumieniu mają ważność wysoką lub średnią (z ważnością po odszumieniu); w bibliotece `skanuj(..., tryb=)` domyślny
jest `pelny`, w CLI `istotne`. Podsumowanie (tekst i JSON: `przed_odszumieniem`, `po_odszumieniu`, `tryb`) podaje liczby
przed i po, w tym wg kodu i ważności, w obu trybach. Odszumianie dotyczy trzech kodów:

* `FLOAT_W_FUNKCJI_KWOTOWEJ` (Python): istotny tylko `float()` użyty w działaniu (`* / + -`) z drugą kwotą lub stawką albo
  zapisywany do pola kwotowego po obliczeniu; domyślnie `niska`, `srednia`, gdy w tym wyrażeniu jest mnożenie lub dzielenie
  ze stawką/VAT. Sam odczyt, konwersja, `abs(float(x))`, JSON, formatowanie, `def ...(x: float) -> float` to szum. SQL
  (w plikach `.sql` i zapytaniach w tekstach Pythona/TS): rzutowanie `::float` / `::double precision` / `CAST(... AS float)` na
  końcu wyrażenia SELECT (`::float AS x`, `::float,`, `::float FROM`, także po `SUM`/`COALESCE`/odejmowaniu w środku) to format
  wyniku zapytania, nie obliczenie, i nie jest zgłaszane. Zgłaszane jest tylko rzutowanie wewnątrz dalszego obliczenia: rzutowany
  operand stoi przy `* / + -` (`a::float * b`, `0.23 * a::float`, `SUM(x)::float * stawka`) albo przy porównaniu (`WHERE
  x::float > 100`, `HAVING`). Typ kolumny `float`/`real`/`double precision` w `CREATE TABLE`/`ALTER TABLE` bez zmian.
* `ROUND_PYTHON_BANKOWE`: zostaje `wysoka` tylko, gdy w tej samej linii lub w sąsiednich 2 liniach (bez komentarzy) jest
  identyfikator z członem netto, brutto, vat, stawka lub wartosc; inaczej `niska` (cena za kg, zł na km, średnie, procenty,
  rozmiary, współrzędne). Dopasowanie po członach identyfikatora, nie po podciągu (`private` nie jest vat).
* `FUNKCJA_POZA_ZRODLEM_PRAWDY`: `srednia` tylko, gdy ciało funkcji ma działanie arytmetyczne na netto/brutto/vat (operatory
  poza tekstami); inaczej szum. Zawsze szum: formatery (`fmt*`, `format*`, `render*`, `display*`, `show*`, `print*`, `to_string`),
  komponenty React (nazwa wielką literą, np. `KwotyCard`), samo `toLocaleString`/`Intl`/JSX.

Wzorce, które muszą zostać znalezione w trybie `istotne` (testy regresji): brutto przez `* (1 + vat/100)` bez zaokrąglenia
(JS i Python), `round(netto * (1 + vat/100.0), 2)` jako brutto, `Math.round(netto * vat) / 100` i `kwota_vat = netto * (vat / 100)`
jako zapis kwoty VAT. Na wymyślonym korpusie szumu (27 fragmentów) tryb `pelny` daje 27 znalezisk, a `istotne` 0; na korpusie
razem z 20 prawdziwymi wzorcami (`tests/skan_szum.py`) przed odszumieniem jest 54 znalezisk (wysoka 22, srednia 17, niska 15),
po odszumieniu 23 (wysoka 14, srednia 9).

**Jak czytać raport.** Linia: `plik:linia  KOD [ważność]  fragment` (fragment to linia kodu bez nadmiaru spacji, do 160 znaków).
Znaleziska są pogrupowane w **moduły** = katalog pliku względem skanowanego katalogu (`routes`, `utils`,
`frontend/pages`, `db/migracje`; pliki w korzeniu to `(korzeń)`), moduły od największej liczby znalezisk, w module od
najwyższej ważności. Na końcu jest podpowiedź poprawki dla każdego kodu (w JSON/CSV przy każdym znalezisku). JSON ma
`podsumowanie` (pliki, znaleziska wg ważności, kodu i modułu) i listę `znaleziska`; CSV ma kolumny
`plik;linia;kod;waznosc;modul;fragment;podpowiedz` (`;`, UTF-8 z BOM, CRLF; fragmenty zaczynające się od `=`, `+`, `@`
dostają apostrof). Zacznij od **wysokiej** ważności; `FUNKCJA_POZA_ZRODLEM_PRAWDY` (po odszumieniu: funkcje z arytmetyką na netto/brutto/vat) to lista do
ręcznego przeglądu (część deleguje do wspólnej funkcji - dopisz je do pliku źródeł prawdy).

**Wyłączenia.** Linię wyłącza komentarz `# kwoty-ok: powód` (Python), `// kwoty-ok: powód` (TS) lub `-- kwoty-ok: powód`
(SQL): w tej samej linii, w osobnej linii bezpośrednio nad nią albo w dowolnej linii wieloliniowej instrukcji (powód jest
dla ludzi, skaner go nie sprawdza). `--pomin GLOB` (powtarzalne, także po przecinku) pomija pliki i katalogi dopasowane do
ścieżki względnej lub nazwy (`'tests/*'`, `test_*.py`, `migracje`). Zawsze pomijane: `.git`, `node_modules`,
`__pycache__`, `venv`/`.venv`, `dist`, `build`, `.next`, `site-packages`, `*.min.js`, `*.d.ts` i pliki większe niż 1,5 MB.
`--zrodlo-prawdy plik.txt` to lista nazw funkcji dozwolonych (jedna w linii, `#` zaczyna komentarz; domyślnie tylko
`kwoty_pozycji`, porównanie bez wielkości liter i podkreślników, więc `kwotyPozycji` to to samo): takie funkcje nie są
zgłaszane jako `FUNKCJA_POZA_ZRODLEM_PRAWDY`, a ich ciała (Python i TS) nie są skanowane, bo to tam wolno liczyć.

**Ograniczenia.** To skaner tekstowy (wyrażenia regularne + prosty lekser komentarzy i tekstów), bez parsowania składni,
typów i przepływu danych: wskazuje miejsca do przejrzenia, nie dowodzi błędu. Nie wie, czy `x` w `x * 1.23` to kwota
(dla stałych 1,05/1,08/0,05/0,08 wymaga w linii słowa kwotowego lub vat/stawka, bo bywają zwykłym współczynnikiem);
nie śledzi, czy wynik mnożenia jest zaokrąglany w innej instrukcji ani czy zmienna `brutto` pochodzi ze wspólnej funkcji.
Zaokrąglenie gdziekolwiek w tej samej instrukcji (do ~25 linii) zdejmuje `VAT_MNOZENIE_BEZ_ZAOKRAGLENIA`. Nazwy kwotowe
rozpoznaje po członach identyfikatora (netto, brutto, vat, kwota, cena, suma, wartosc, podatek, amount, price, gross), więc
kolumny nazwane inaczej (np. `net_amt`) są niewidoczne, a `price` w niekwotowym kontekście daje fałszywy alarm.
SQL w Pythonie/TS jest rozpoznawany po słowach kluczowych w tekście; SQL składany z kawałków (`"SELECT " + kol`) nie.
Nie czyta szablonów (`.html`, `.jinja`), plików konfiguracyjnych ani zapytań w ORM-ach (`func.sum(Model.brutto)`).
Wyrażenia regularne (literały `/.../` w JS) nie są rozpoznawane jako teksty, więc `//` w nich bywa wzięte za komentarz.
**Dokładność na własnych przykładach** (`tests/skan_przyklady.py`: 74 złe i 61 dobrych fragmentów, fikcyjnych i
dostrojonych równolegle ze skanerem, więc to dolna granica trudności, nie niezależna miara): 81 trafień, 0 fałszywych
alarmów, 0 pominięć (precyzja i czułość 100% na tym zbiorze). Dodatkowo 0 znalezisk na ~535 plikach biblioteki standardowej
Pythona i ~160 plikach JS menedżera pakietów. Na prawdziwym kodzie spodziewaj się szumu głównie z
`FUNKCJA_POZA_ZRODLEM_PRAWDY`, `FLOAT_W_FUNKCJI_KWOTOWEJ` i `STAWKA_ZW_NP_POMINIETA`.

### Typowe wyniki i co z nimi zrobić

Jedna linia na kod. Zalecenia: **zignoruj** - nic nie trzeba robić; **sprawdź dokument** - otwórz dokument
(`id` z raportu) i porównaj z podpowiedzią z `przyczyny`; **popraw regułę** - jeśli kod pojawia się masowo
i z różnicami rzędu groszy, to nie błąd dokumentów, tylko inna reguła zaokrąglania / tryb VAT w systemie
źródłowym (spróbuj `--tryb-vat`, `Konfiguracja(zaokraglanie=...)`, `miejsca_ceny`).

| Kod | Co zrobić |
|---|---|
| `POLGROSZ` | **zignoruj** - różnica <= 0,01 z niezaokrąglonej wartości (np. brutto z 3 miejscami); jeśli takich jest bardzo dużo, popraw zaokrąglanie w miejscu, które zapisuje sumy |
| `VAT_WYLICZONY_ZGODNY` | **zignoruj** - pozycje bez VAT, ale VAT wyliczony ze stawki i netto zgadza się z nagłówkiem |
| `VAT_WYLICZONY_ROZNY` | **sprawdź dokument** - zacznij od `stawki_tlumaczace` (nagłówek pomija / dubluje VAT całej stawki); różnica 0,01-0,02 masowo = **popraw regułę** (tryb VAT / zaokrąglanie) |
| `BRAK_VAT_W_POZYCJACH` | **zignoruj albo uzupełnij eksport** - bez stawki w pozycjach nie da się niczego powiedzieć o VAT, sprawdzone zostało tylko netto |
| `NAGLOWEK_ZERO` | **sprawdź dokument** - nagłówek nie został przeliczony (sumy 0 przy niezerowych pozycjach); zwykle błąd zapisu, nie zaokrąglenia |
| `NAGLOWEK_NIZSZY` | **sprawdź dokument** - nagłówek pomija część pozycji; `mozliwe_pozycje` wskazuje pozycję o wartości równej różnicy |
| `NAGLOWEK_WYZSZY` | **sprawdź dokument** - nagłówek zawiera więcej niż pozycje (pozycja usunięta po przeliczeniu albo policzona dwa razy) |
| `ZESTAW_LICZONY_PODWOJNIE` | **sprawdź dokument i poprawę w źródle** - suma nagłówka liczy zestaw (pozycję nadrzędną) obok jego dzieci |
| `ZESTAW_ROZNY_OD_DZIECI` | **sprawdź dokument** - kwota pozycji nadrzędnej nie jest sumą jej dzieci i nie wynika z jej własnego narzutu/rabatu |
| `ZESTAW_BEZ_MNOZENIA_PRZEZ_ILOSC` | **sprawdź dokument** - wartość zestawu nie została pomnożona przez jego ilość (lub dzieci mają ilość zestawu zamiast 1 szt.); jeśli dzieci w Waszych danych opisują całą ilość zestawu, uruchom z `--ilosc-zestawu nie` |
| `ALTERNATYWY_W_SUMIE` | **zignoruj** gdy `dopasowanie: zgodne`; **sprawdź dokument** gdy `najblizsze` (zwłaszcza `naglowek_zawiera_wszystkie_opcje: true` - opcje sumują się mimo, że się wykluczają) |
| `OPCJA_W_SUMIE` | **sprawdź dokument** - nagłówek został policzony razem z opcją, której klient nie wybrał (`wybrana` != true); popraw sumę albo ustaw `wybrana=true` na opcji, jeśli klient ją jednak zamówił |
| `ALTERNATYWA_BEZ_WYBORU` | **sprawdź dokument** - w grupie alternatyw nie zaznaczono żadnej; uzupełnij wybór (`naglowek_pasuje_do` podpowiada, która pasuje do nagłówka) |
| `ALTERNATYWA_WIELE_WYBRANYCH` | **sprawdź dokument** - w grupie zaznaczono kilka alternatyw, a wykluczają się; zostaw jedną (`naglowek_pasuje_do_jednej` podpowiada, która pasuje do nagłówka) |
| `ZESTAW_NIEODSWIEZONY` | **sprawdź dokument** - przelicz zestaw (zapisz dokument ponownie po zmianie dziecka); jeśli to częste, błąd jest w aplikacji, która nie odświeża zestawu |
| `BRUTTO_ROWNE_NETTO` | **sprawdź dokument** - brak VAT w brutto; zwykle błąd zapisu lub import bez przeliczenia, nie zaokrąglenie |
| `ZESTAW_Z_NARZUTEM` | **zignoruj** - różnica zestawu względem sumy dzieci wynika z jego własnego narzutu lub rabatu |
| `ILOSC_X_CENA` | **sprawdź dokument** - wartość pozycji nie wynika z ilości, ceny i rabatów; różnice 0,02-0,05 na wielu pozycjach = **popraw regułę** (np. system zaokrągla cenę po rabacie do 2 miejsc: `miejsca_ceny=2`) |
| `ILOSC_X_CENA_NARZUT` | oferty i zamówienia z `cena_zakupu_jedn` + `narzut_proc`/`marza_proc`: wariant "cena sprzedaży nie zgadza się z zakup+narzut" = **sprawdź dokument** (`wyjasnienie` mówi, czy pominięto narzut albo rabat, a `narzut_wynikowy` jaki narzut wynika z zapisanej wartości); wariant "narzut/rabat tłumaczy różnicę" (w rozkładzie kodów z dopiskiem `(informacja)`) = **zignoruj** |
| `NIEZGODNY_Z_BIBLIOTEKA` | **sprawdź dokument**; masowo przy spójnych dokumentach = **popraw regułę** (inny tryb VAT / sposób zaokrąglania rabatu) |
| `SUMA_POZYCJI_ROZNA_OD_DOKUMENTU` | **sprawdź dokument** - zwykle towarzyszy mu `NAGLOWEK_*` z wyjaśnieniem; sam 1 gr = **popraw regułę** |
| `SUMA_STAWEK_ROZNA_OD_DOKUMENTU` | **sprawdź dokument** - podsumowanie stawek nie sumuje się do nagłówka |
| `PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI` | **sprawdź dokument** - wiersz podsumowania stawki nie jest sumą jej pozycji |
| `NETTO_PLUS_VAT_ROZNE_OD_BRUTTO` | **sprawdź dokument**; 1 gr na wielu dokumentach = **popraw regułę** (brutto zaokrąglane osobno od netto i VAT) |
| `VAT_STAWKI_ROZNY_OD_SUMY` | 1 gr = **popraw regułę**: dokument liczony per pozycja, a sprawdzany `per_stawka` - uruchom z `--tryb-vat per_pozycja`; większa różnica = **sprawdź dokument** |
| `ILOSC_UJEMNA`, `CENA_UJEMNA` | pojawiają się tylko z `--nie-dopuszczaj-ujemnych`: **zignoruj**, jeśli ujemne linie są normalne (zostaw domyślne `--dopusc-ujemne`), albo **sprawdź dokument**, jeśli nie powinny występować |
| `BRAK_POLA`, `BRAK_CENY`, `NIEPOPRAWNA_STRUKTURA` | **popraw eksport lub `--mapowanie`** - brak pola (sumy, pozycji, ceny, ilości, stawki) albo zły kształt danych |
| `NIEZNANA_STAWKA`, `RABAT_POZA_ZAKRESEM`, `NIEPOPRAWNA_LICZBA`, `NIEPOPRAWNY_TRYB`, `NIEPOPRAWNA_WALUTA` | **sprawdź dokument** - dane poza dozwolonymi wartościami (stawka spoza 23/8/5/0/zw/np, rabat poza 0..100%, śmieci zamiast liczby, tryb inny niż netto/brutto, kod waluty nie ISO) |
| `NIEPOPRAWNA_HIERARCHIA` | **sprawdź dokument** - `parent_id` wskazuje nieistniejącą pozycję, cykl albo zdublowane `id` rodzica |
| `NARZUT_I_MARZA`, `MARZA_POZA_ZAKRESEM`, `DZIELENIE_PRZEZ_ZERO` | dotyczą tylko API narzutu i marży (`amounts_calc.marza`), nie pojawiają się w raporcie CLI |

### Integracja z istniejącą aplikacją

1. Skopiuj pakiet `amounts_calc/` (albo dodaj repo do `PYTHONPATH`); zero zależności.
2. W każdym miejscu, które dziś samo sumuje kwoty, zbuduj listę pozycji i wywołaj `oblicz()`;
   z `DokumentWynik` bierz sumy i podsumowanie stawek (`do_slownika()` daje wersję pod JSON ze
   stringami). Nie przeliczaj niczego drugi raz po stronie widoku/raportu.
3. Kwoty trzymaj w `Decimal`/`NUMERIC` do końca; `float` jest odrzucany z błędem.
4. Wybierz tryb VAT zgodny z tym, co dziś wystawia system (patrz otwarte decyzje).

**Testy zgodności na dokumentach z bazy (bez danych w repo):** napisz po stronie aplikacji mały
skrypt, który dla próbki dokumentów (a) mapuje wiersze na słownik `{pozycje, suma_*, ...}`,
(b) woła `sprawdz_spojnosc(dok, tryb_vat=...)` - wynik to lista niespójności istniejących danych,
(c) przelicza te same pozycje przez `oblicz()` i porównuje `porownaj(dok_z_bazy, wynik)` - lista
rozbieżności względem obecnej logiki. Wyniki agreguj po kodach i `pole`; skrypt i próbka zostają
w aplikacji, w repo nie ma żadnych danych.

### Test referencyjny (Fraction)

`tests/referencja.py` to niezależna implementacja na `fractions.Fraction` (nie importuje
biblioteki), a `tests/test_referencja.py` porównuje ją z biblioteką na 2000 losowych dokumentów
(stałe ziarno, tryb VAT `per_pozycja`, od netto i od brutto, rabaty pozycji i dokumentu):

1. **`policz_wg_specyfikacji`** - te same punkty zaokrąglania, ale arytmetyka wymierna. Zgodność
   DOKŁADNA co do grosza (sprawdza poprawność arytmetyki `Decimal`, precyzji kontekstu i kolejności
   operacji). Dodatkowo sumy per stawka dla `per_stawka`.
2. **`policz_dokladnie`** - wszystko dokładnie, zaokrąglenie dopiero na końcu. Tu metody **celowo się
   różnią**, więc test sprawdza granice błędu, nie równość:
   - cena po rabacie zaokrąglana do 4 miejsc (błąd do `ilość x 0,00005`),
   - wartość pozycji zaokrąglana do grosza PRZED liczeniem VAT-u (podwójne zaokrąglenie; np. 1 szt.
     po 0,0218 zł: biblioteka VAT 0,00, referencja dokładna 0,01),
   - rabat dokumentu stosowany do już zaokrąglonej wartości pozycji,
   - od brutto: netto liczone z zaokrąglonego brutto pozycji.
   Bez rabatów kwota pozycji zgadza się dokładnie, a VAT różni się najwyżej o 1 gr (i test wymaga,
   żeby takie różnice faktycznie wystąpiły w próbie). Korekta groszowa `per_stawka` nie ma w
   referencji odpowiednika.

### Otwarte decyzje

1. **VAT per pozycja czy per stawka?** Domyślnie `per_stawka` (jak podsumowanie stawek na
   fakturze). Trzeba potwierdzić, co robi dziś system i księgowość; zmiana to jedna opcja.
   Uwaga: domyślny rozkład korekty (`najwieksza`, wg specyfikacji) bywa skrajny przy tysiącach
   pozycji grosz-po-groszu (1000 x 0,01 zł daje VAT 2,30 zł na jednej pozycji, od brutto nawet
   ujemne netto). Jest alternatywa `rozklad_korekty="proporcjonalnie"`; który rozkład ma być
   domyślny, do decyzji - dotąd zostawiłem zachowanie ze specyfikacji.
2. **Jak zaokrąglać rabat?** Przyjęto: cena po rabacie do 4 miejsc, potem wartość do grosza.
   Alternatywy: cena do grosza (`miejsca_ceny=2`) albo rabat liczony od wartości pozycji.
   Rabat dokumentu jest procentowy na wartości pozycji, a nie kwotowy z rozdziałem.
3. **Waluty obce:** waluta jest tylko etykietą (3 wielkie litery), bez kursów i bez przeliczeń;
   wszystkie waluty zaokrąglane do 2 miejsc (np. JPY bez groszy wymagałoby osobnej konfiguracji).
   Do rozstrzygnięcia: kto i kiedy przelicza kurs, oraz zaokrąglenie kwot w PLN dla VAT.
4. **Ujemne ilości/ceny** (korekty, zwroty, rabat jako linia): specyfikacja każe je odrzucać, więc
   `oblicz()` robi to domyślnie (`dopusc_ujemne=False`), a CLI domyślnie je dopuszcza. Do decyzji:
   czy w aplikacji korekty mają iść tą samą ścieżką `oblicz(..., dopusc_ujemne=True)`; przy mieszanych
   znakach w jednej stawce "największa pozycja" do korekty groszowej wybierana jest po module.
5. **Tryb pasujący w raporcie CLI:** zgodność oceniana po sumach dokumentu i podsumowaniu stawek,
   bez pozycji (korekta groszowa może trafić gdzie indziej). Jeśli system źródłowy ma stałą regułę
   rozdziału groszy, można dodać ją jako kolejny wariant porównania.
6. **Precyzja ceny jednostkowej:** cena po rabacie jest zaokrąglana do 4 miejsc zawsze (też bez
   rabatu), więc cena wejściowa z 5+ miejscami zostanie zaokrąglona - do potwierdzenia.
7. **Model zestawów:** przyjęto, że pozycja nadrzędna jest wierszem zbiorczym (jej kwoty = `N x` suma dzieci,
   własna cena ignorowana; dzieci zawsze opisują 1 szt. zestawu - do potwierdzenia na prawdziwych danych,
   także czy opcje/alternatywy zawsze są oznaczone osobnym polem). Odwrotny model - nadrzędna niesie cenę zestawu, a dzieci są tylko opisowe -
   nie jest obsługiwany; trzeba potwierdzić na prawdziwych ZK/ofertach, który występuje.
8. **Definicja `POLGROSZ`:** różnica <= 0,01 oraz niezaokrąglona (> 2 miejsca) wartość po którejś stronie.
   Progi `0,01` dla `NAGLOWEK_*` i `ILOSC_X_CENA` to stała `PROG` w `klasyfikacja.py`.
   `ILOSC_X_CENA` używa reguł rabatu i zaokrąglenia tej biblioteki (cena po rabacie do 4 miejsc, potem
   wartość do grosza) - system źródłowy zaokrąglający inaczej może dawać fałszywe trafienia.
9. **Dane niepełne:** jako niepełne traktowany jest tylko brak pola VAT we wszystkich pozycjach. Brak
   `brutto` przy obecnych `netto` i `vat` nadal kończy się `BRAK_POLA` (można by wyliczać brutto z
   netto + vat); dokument, w którym tylko część pozycji ma kwoty, jest błędem, nie "niepełnym".
10. **CSV pod polski Excel:** `;`, BOM, CRLF i przecinek dziesiętny. Dla Excela w innej lokalizacji
    (separator `,`, kropka dziesiętna) trzeba to zmienić albo użyć JSON.
11. **Kod wyjścia 1** tylko dla dokumentów niespójnych i błędnych; drobiazgi i dane niepełne dają 0.
    Jeśli CI ma być surowsze, wystarczy sprawdzić statusy w JSON.
12. **Wyliczanie VAT dla pozycji bez VAT:** zapisane `netto` pozycji jest traktowane jako gotowa wartość
    (bez ponownego rabatu dokumentu), a porównanie dotyczy sumy VAT dokumentu w obu trybach VAT. Brutto
    wyliczone jest podawane w szczegółach przyczyny, ale nie generuje osobnych kodów. Dokument z
    `VAT_WYLICZONY_ZGODNY` ma status `spojny` i nie trafia do JSON/CSV; jeśli ma trafiać (żeby widzieć,
    które dokumenty polegały na wyliczeniu), wystarczy zmienić status na osobny.
13. **Pozycje z narzutem - heurystyka `cena_netto_jedn`:** gdy pozycja ma zakup i narzut, `cena_netto_jedn` równa
    cenie zakupu (z tolerancją 0,01) jest traktowana jako cena zakupu, a każda inna jako zapisana cena
    sprzedaży porównywana z `zakup + narzut`. Jeśli w danych `cena_netto_jedn` to np. cena katalogowa niezwiązana
    z narzutem, da to fałszywe `ILOSC_X_CENA_NARZUT`; wtedy wystarczy nie mapować tego pola na `cena_netto_jedn`.
    Narzut bez ceny zakupu jest cicho ignorowany.
14. **Zaokrąglenie ceny sprzedaży:** do grosza, jednym zaokrągleniem przed rabatem (inaczej niż narzut dokumentu,
    który zaokrągla do miejsc ceny). Jeśli system źródłowy zaokrągla np. dopiero wartość pozycji, trzeba
    ustawić `Konfiguracja(miejsca_kwot=...)` albo zmienić regułę.
15. **Narzut zestawu a sumy dokumentu:** przyjęto, że nagłówek może być sumą liści albo sumą liści z narzutem/rabatem
    zestawów najwyższego poziomu; zestawy zagnieżdżone z własnym narzutem są oceniane względem swoich liści, a
    `oblicz()` zawsze liczy sumy z liści. Do potwierdzenia na prawdziwych ZK.
16. **Dowody `ZESTAW_NIEODSWIEZONY`:** to heurystyka z jednego zrzutu danych (nie widać historii zmian), więc
    podpowiedź może być fałszywa przy zestawie, który po prostu ma błędną kwotę; `inna` oznacza brak dowodów.
17. **`BRUTTO_ROWNE_NETTO`:** pomija kwoty, od których VAT zaokrągla się do mniej niż grosza, oraz stawki `zw`/`np`/0;
    nie rozpoznaje odwróconego obciążenia, w którym brutto równe netto jest zamierzone.
18. **Ilość zero w opcji:** czy opcja może mieć `ilosc = 0`? Biblioteka ją dopuszcza (opcja wnosi wtedy 0 i niczego
    nie zmienia w sumie), ale w ofercie dla klienta taka pozycja raczej nie ma sensu - do ustalenia, czy aplikacja ma
    ją blokować, czy traktować `0` jak "opcja wyłączona".
19. **Opcja wybrana po wysłaniu oferty:** pole `wybrana` opisuje stan *teraz*. Jeśli klient zmieni wybór po wysłaniu
    oferty, zapisany nagłówek (i PDF) mogą się rozjechać z polami; biblioteka zgłosi to jako `OPCJA_W_SUMIE`,
    `ALTERNATYWA_BEZ_WYBORU` albo zwykłą różnicę sum. Do decyzji: czy zmiana wyboru zawsze przelicza nagłówek,
    czy tworzy nową wersję oferty, i czy wysłana oferta ma zamrażać `wybrana`.
20. **Tryb jawny od pierwszego pola:** wystarczy jedna pozycja z niepustym `tryb_opcji`, żeby cały dokument przeszedł
    na tryb jawny (stare `alternatywa` / `grupa_opcji` w tym samym dokumencie przestają działać jako znacznik
    alternatywy). Dokumenty przejściowe, w których aplikacja zapisuje `tryb_opcji` tylko w części pozycji, trzeba
    uzupełnić; `--tryb-opcji awaryjny` pozwala porównać oba odczyty.
21. **Co to jest "poza sumą":** tylko niewybrane *opcje*. Niewybrane alternatywy nie są pokazywane pod sumą; jeśli
    PDF ma pokazywać także je, wystarczy dołożyć drugą sumę (dane są w `wiersze`/`opcje`).
22. **Skaner kodu: lista źródeł prawdy.** Domyślnie tylko `kwoty_pozycji`. Trzeba dopisać do pliku `--zrodlo-prawdy` nazwy
    pozostałych funkcji aplikacji, które wolno liczyć kwoty (np. wariant odwrotnego liczenia z brutto), i zdecydować, czy
    ich ciała mają być wyłączone ze skanowania (tak jest teraz).
23. **Złote przypadki: odwrotne liczenie i rabaty dokumentu.** Plik zawiera tylko liczenie od netto, rabat pozycji i sumy
    per pozycja; nie ma przypadków liczenia netto z brutto ani rabatu dokumentu, bo aplikacja nie podała dla nich reguły.
24. **Opcje: próg 25% dopasowania `najblizsze`** jest wartością dobraną na oko (stała `PROGLICZNY` w `opcje.py`); do
    potwierdzenia, jak duży błąd narzutu realnie występuje.
25. **Odszumianie skanera: progi.** Okno 2 linii dla `round()`, zestaw słów kontekstu (netto, brutto, vat, stawka, wartosc) i lista
    formaterów (`fmt*`, `format*`, `render*`...) to wartości dobrane na wymyślonym korpusie; do sprawdzenia na prawdziwym kodzie
    (`--tryb pelny` pozwala porównać). `float` w sumie netto + VAT ma po odszumieniu ważność `niska`, więc tryb `istotne` go
    ukrywa; jeśli taki zapis ma być widoczny, trzeba podnieść go do `srednia`.
26. **SQL: rzut w argumencie funkcji.** `COALESCE(kwota::float, 0) * stawka` nie jest zgłaszane (rzutowanie stoi przy przecinku, a
    mnożenie dotyczy całego wyniku funkcji); skaner patrzy tylko na bezpośredniego sąsiada rzutowanego operandu. Podobnie przypisanie
    `SET kwota = x::float` nie jest uznawane za porównanie.
