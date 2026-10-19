"""Biblioteka czystych funkcji do przeliczania kwot dokumentu handlowego."""
from .config import (DOMYSLNA, Konfiguracja, TRYB_BRUTTO, TRYB_NETTO, VAT_PER_POZYCJA,
                     VAT_PER_STAWKA)
from .model import DokumentWynik, Pozycja, PozycjaWynik, PodsumowanieStawki
from .obliczenia import oblicz
