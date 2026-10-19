"""Błędy walidacji i kody błędów jako stałe."""

# Kody błędów walidacji wejścia
NIEPOPRAWNA_LICZBA = "NIEPOPRAWNA_LICZBA"
ILOSC_UJEMNA = "ILOSC_UJEMNA"
CENA_UJEMNA = "CENA_UJEMNA"
RABAT_POZA_ZAKRESEM = "RABAT_POZA_ZAKRESEM"
NIEZNANA_STAWKA = "NIEZNANA_STAWKA"
NIEPOPRAWNY_TRYB = "NIEPOPRAWNY_TRYB"
NIEPOPRAWNA_WALUTA = "NIEPOPRAWNA_WALUTA"
BRAK_CENY = "BRAK_CENY"
NARZUT_I_MARZA = "NARZUT_I_MARZA"
MARZA_POZA_ZAKRESEM = "MARZA_POZA_ZAKRESEM"
DZIELENIE_PRZEZ_ZERO = "DZIELENIE_PRZEZ_ZERO"
BRAK_POLA = "BRAK_POLA"
NIEPOPRAWNA_STRUKTURA = "NIEPOPRAWNA_STRUKTURA"

# Kody niespójności wykrywanych przez sprawdz_spojnosc
SUMA_POZYCJI_ROZNA_OD_DOKUMENTU = "SUMA_POZYCJI_ROZNA_OD_DOKUMENTU"
NETTO_PLUS_VAT_ROZNE_OD_BRUTTO = "NETTO_PLUS_VAT_ROZNE_OD_BRUTTO"
VAT_STAWKI_ROZNY_OD_SUMY = "VAT_STAWKI_ROZNY_OD_SUMY"
PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI = "PODSUMOWANIE_STAWKI_ROZNE_OD_POZYCJI"
SUMA_STAWEK_ROZNA_OD_DOKUMENTU = "SUMA_STAWEK_ROZNA_OD_DOKUMENTU"


class BladWalidacji(ValueError):
    """Niepoprawne dane wejściowe. `kod` to jedna ze stałych powyżej, `pole` wskazuje miejsce."""

    def __init__(self, kod, pole, wiadomosc):
        super().__init__("[%s] %s: %s" % (kod, pole, wiadomosc))
        self.kod = kod
        self.pole = pole
        self.wiadomosc = wiadomosc
