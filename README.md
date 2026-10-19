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

Pakiet `amounts_calc/` (tylko stdlib, Python 3.8+), testy w `tests/` (128 testów, ~1 s,
bez bazy danych i bez sieci).

```
amounts_calc/
  config.py       Konfiguracja: JEDNO miejsce reguły zaokrąglania (tryb, miejsca, tryb VAT)
  stawki.py       stawki 23/8/5/0/'zw'/'np', konwersja liczb (float zabroniony)
  model.py        Pozycja (wejście), PozycjaWynik, PodsumowanieStawki, DokumentWynik
  obliczenia.py   oblicz(): od netto / od brutto, rabaty, VAT per pozycja / per stawka
  marza.py        narzut vs marża
  spojnosc.py     sprawdz_spojnosc(), porownaj()
  bledy.py        BladWalidacji + kody błędów jako stałe
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

**Kolejność rabatów:** rabat pozycji (na cenie jednostkowej), potem rabat dokumentu
(procentowo na wartości każdej pozycji), na końcu VAT. Rabaty nie są sumowane do jednego procentu
(200 zł, -10% na pozycji, -10% na dokumencie = 162,00 zł, nie 160,00 zł).

**VAT: dwa tryby** (`Konfiguracja.tryb_vat` albo `oblicz(..., tryb_vat=...)`):

- `per_pozycja` - VAT zaokrąglany na każdej pozycji osobno, suma stawki = suma tych VAT-ów.
- `per_stawka` (domyślny) - VAT liczony raz na sumie stawki. Różnica groszy względem sumy
  VAT-ów z pozycji trafia do pozycji o największej wartości w tej stawce (remis: pierwsza),
  więc suma pozycji == suma dokumentu zawsze, a `netto + vat == brutto` w każdej pozycji.

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

### Otwarte decyzje

1. **VAT per pozycja czy per stawka?** Domyślnie `per_stawka` (jak podsumowanie stawek na
   fakturze). Trzeba potwierdzić, co robi dziś system i księgowość; zmiana to jedna opcja.
   Uwaga: `per_stawka` z korektą na jednej pozycji bywa skrajny przy tysiącach pozycji
   grosz-po-groszu (1000 x 0,01 zł daje VAT 2,30 zł na jednej pozycji) - ewentualny rozkład
   korekty po 1 gr na wiele pozycji to osobna decyzja, bo spec każe wskazać największą pozycję.
2. **Jak zaokrąglać rabat?** Przyjęto: cena po rabacie do 4 miejsc, potem wartość do grosza.
   Alternatywy: cena do grosza (`miejsca_ceny=2`) albo rabat liczony od wartości pozycji.
   Rabat dokumentu jest procentowy na wartości pozycji, a nie kwotowy z rozdziałem.
3. **Waluty obce:** waluta jest tylko etykietą (3 wielkie litery), bez kursów i bez przeliczeń;
   wszystkie waluty zaokrąglane do 2 miejsc (np. JPY bez groszy wymagałoby osobnej konfiguracji).
   Do rozstrzygnięcia: kto i kiedy przelicza kurs, oraz zaokrąglenie kwot w PLN dla VAT.
4. **Ujemne ilości/ceny** (korekty, zwroty) są błędem walidacji zgodnie ze specyfikacją;
   jeśli korekty mają iść tą samą ścieżką, trzeba zmienić regułę.
5. **Precyzja ceny jednostkowej:** cena po rabacie jest zaokrąglana do 4 miejsc zawsze (też bez
   rabatu), więc cena wejściowa z 5+ miejscami zostanie zaokrąglona - do potwierdzenia.
