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

_(uzupełnia wykonawca po zakończeniu zadania)_
