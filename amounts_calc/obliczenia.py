"""Liczenie kwot dokumentu: od netto albo od brutto.

PUNKTY ZAOKRĄGLANIA (kolejność, jedyne miejsca w których cokolwiek jest zaokrąglane):
  1. cena po rabacie pozycji = cena * (1 - rabat/100)        -> miejsca_ceny (domyślnie 4)
  2. wartość pozycji         = ilość * cena po rabacie       -> grosz
  3. wartość po rabacie dokumentu = wartość * (1 - rabat_dok/100)  -> grosz (tylko gdy rabat_dok > 0)
  4. rozbicie na netto/vat/brutto:
       od netto:  vat = netto * stawka/100        -> grosz
       od brutto: netto = brutto / (1+stawka/100) -> grosz, vat = brutto - netto (bez dryfu)
     robione per pozycja ALBO per stawka na sumie (Konfiguracja.tryb_vat).

WARTOŚCI UJEMNE: reguła zaokrąglania działa na module liczby, a znak jest dopisywany po zaokrągleniu,
więc dokument ze wszystkimi znakami odwróconymi daje dokładnie odwrócone wyniki (także korekta
groszowa: "największa" pozycja to ta o największym module, a rozkład "proporcjonalnie" jest lustrzany).

CENA Z ZAKUPU I NARZUTU: pozycja z `cena_zakupu_jedn` i `narzut_proc` (albo `marza_proc`) ma cenę sprzedaży
`zakup * (1 + narzut/100)` (`zakup / (1 - marża/100)`) zaokrągloną do grosza (konf.kwota); dalej jak zwykła
cena: rabat pozycji -> cena po rabacie -> wartość. Ma pierwszeństwo przed `cena_netto_jedn` (w ofertach to
często cena zakupu). Działa w trybie od netto; w trybie od brutto pola zakupu i narzutu są ignorowane.

POZYCJE NADRZĘDNE (ZESTAWY): pozycja z `parent_id` jest dzieckiem pozycji o danym `id`. Pozycja,
która ma dzieci, to wiersz zbiorczy: jej kwoty to suma dzieci, a sama NIE wchodzi do sum dokumentu
ani do podsumowania stawek (brak podwójnego liczenia). Jej własne ilość/cena/rabat są ignorowane
(wymagane są tylko `ilosc` i `stawka_vat`, żeby wiersz był poprawną pozycją). Rabat dokumentu i
tryb VAT dotyczą liści.

KOLEJNOŚĆ RABATÓW: najpierw rabat pozycji (na cenie jednostkowej), potem rabat dokumentu
(procentowo na wartości każdej pozycji), na końcu VAT. Rabat dokumentu nie jest łączony z
rabatem pozycji w jeden procent.

W trybie per stawka VAT liczony jest raz na sumie stawki, a różnica groszy względem sumy
VAT liczonych per pozycja trafia do pozycji o największej wartości w tej stawce (remis:
pierwsza z brzegu). Dzięki temu suma pozycji == suma dokumentu zawsze.
Opcja rozklad_korekty="proporcjonalnie" zamiast tego liczy część rozbijaną (vat od netto, netto
od brutto) każdej pozycji dokładnie, obcina ją w dół do grosza i dodaje po 1 gr kolejnym
pozycjom wg malejącej części ułamkowej (remis: niższy indeks), aż suma stawki się zgodzi.
"""
from decimal import Decimal, localcontext

from . import marza
from .hierarchia import liscie_pod, zbuduj_hierarchie
from .bledy import (BRAK_CENY, CENA_UJEMNA, ILOSC_UJEMNA, NARZUT_I_MARZA, NIEPOPRAWNA_WALUTA,
                    NIEPOPRAWNY_TRYB, RABAT_POZA_ZAKRESEM, BladWalidacji)
from .config import (DOMYSLNA, KONTEKST, ROZKLADY, ROZKLAD_NAJWIEKSZA, TRYB_BRUTTO, TRYB_NETTO,
                     TRYBY, TRYBY_VAT, VAT_PER_POZYCJA)
from .model import (DokumentWynik, PozycjaWynik, pozycja_z_slownika, podsumuj_stawki)
from .stawki import do_decimal, normalizuj_stawke, wartosc_stawki

_100 = Decimal(100)


def _rabat(wartosc, pole):
    d = do_decimal(wartosc if wartosc is not None else 0, pole)
    if d < 0 or d > 100:
        raise BladWalidacji(RABAT_POZA_ZAKRESEM, pole, "rabat musi być w zakresie 0..100%%, jest %s" % d)
    return d


def _waluta(waluta):
    if not (isinstance(waluta, str) and len(waluta) == 3 and waluta.isascii()
            and waluta.isalpha() and waluta.isupper()):
        raise BladWalidacji(NIEPOPRAWNA_WALUTA, "waluta", "oczekiwano kodu ISO 4217 (np. PLN), jest %r" % (waluta,))
    return waluta


def _rozbij(kwota, stawka, tryb, konf):
    """kwota (netto lub brutto zależnie od trybu) -> (netto, vat, brutto) z jednym zaokrągleniem."""
    r = wartosc_stawki(stawka)
    if tryb == TRYB_NETTO:
        vat = konf.kwota(kwota * r / _100)
        return kwota, vat, kwota + vat
    netto = konf.kwota(kwota / (1 + r / _100))
    return netto, kwota - netto, kwota


def _dokladna_czesc(kwota, stawka, tryb):
    """Niezaokrąglona część rozbijana: vat (od netto) albo netto (od brutto)."""
    r = wartosc_stawki(stawka)
    return kwota * r / _100 if tryb == TRYB_NETTO else kwota / (1 + r / _100)


def _rozdziel_reszty(dokladne, docelowa, konf):
    """Metoda największych reszt, symetryczna względem zera.

    Każda część jest obcinana w stronę zera do grosza; brakujące (lub nadmiarowe) grosze dostają
    pozycje o największej (najmniejszej) reszcie ze znakiem, remis: niższy indeks. Dla samych liczb
    dodatnich to klasyczna metoda największych reszt, a lustrzana grupa ujemna daje lustrzany wynik."""
    obciete = [konf.obetnij(x) for x in dokladne]
    reszty = [x - o for x, o in zip(dokladne, obciete)]
    brak = int(((docelowa - sum(obciete, Decimal(0))) / konf.grosz).to_integral_value())
    if brak >= 0:
        kolejnosc = sorted(range(len(dokladne)), key=lambda j: (-reszty[j], j))
        krok = konf.grosz
    else:
        kolejnosc = sorted(range(len(dokladne)), key=lambda j: (reszty[j], j))
        krok = -konf.grosz
    wynik = list(obciete)
    for k in range(abs(brak)):
        wynik[kolejnosc[k % len(kolejnosc)]] += krok
    return wynik


def _wejscie_pozycji(i, p, tryb, narzut, marza_proc, konf, dopusc_ujemne=False):
    """Waliduje pozycję i zwraca (ilosc, cena, rabat, stawka)."""
    pre = "pozycje[%d]." % i
    ilosc = do_decimal(p.ilosc, pre + "ilosc")
    if ilosc < 0 and not dopusc_ujemne:
        raise BladWalidacji(ILOSC_UJEMNA, pre + "ilosc", "ilość nie może być ujemna: %s" % ilosc)
    rabat = _rabat(p.rabat_proc, pre + "rabat_proc")
    stawka = normalizuj_stawke(p.stawka_vat, pre + "stawka_vat")
    if tryb == TRYB_NETTO:
        if p.cena_zakupu_jedn is not None and (p.narzut_proc is not None or p.marza_proc is not None):
            # oferta/zamówienie: cena sprzedaży z zakupu i narzutu (marży) pozycji, zaokrąglona do grosza;
            # ma pierwszeństwo przed cena_netto_jedn, która w takich danych bywa tylko ceną zakupu
            cena = marza.cena_sprzedazy(p.cena_zakupu_jedn, p.narzut_proc, p.marza_proc, konf, dopusc_ujemne,
                                        pre.rstrip("."))
        elif p.cena_netto_jedn is not None:
            cena = do_decimal(p.cena_netto_jedn, pre + "cena_netto_jedn")
        elif p.koszt_zakupu_jedn is not None and (narzut is not None or marza_proc is not None):
            if narzut is not None:
                cena = marza.cena_z_narzutu(p.koszt_zakupu_jedn, narzut, konf)
            else:
                cena = marza.cena_z_marzy(p.koszt_zakupu_jedn, marza_proc, konf)
        else:
            raise BladWalidacji(BRAK_CENY, pre + "cena_netto_jedn",
                                "brak ceny netto (ani kosztu z narzutem/marżą)")
        pole_ceny = pre + "cena_netto_jedn"
    else:
        if p.cena_brutto_jedn is None:
            raise BladWalidacji(BRAK_CENY, pre + "cena_brutto_jedn", "tryb od brutto wymaga ceny brutto")
        cena = do_decimal(p.cena_brutto_jedn, pre + "cena_brutto_jedn")
        pole_ceny = pre + "cena_brutto_jedn"
    if cena < 0 and not dopusc_ujemne:
        raise BladWalidacji(CENA_UJEMNA, pole_ceny, "cena nie może być ujemna: %s" % cena)
    return ilosc, cena, rabat, stawka


def oblicz(pozycje, tryb=TRYB_NETTO, waluta="PLN", rabat_dokumentu_proc=0,
           narzut_proc=None, marza_proc=None, tryb_vat=None, rozklad_korekty=None,
           dopusc_ujemne=False, konfiguracja=DOMYSLNA):
    """Przelicza dokument. `pozycje`: lista Pozycja lub słowników. Zwraca DokumentWynik.

    `dopusc_ujemne=True` dopuszcza ujemne ilości i ceny (rabat jako osobna linia, korekta, zwrot);
    domyślnie są błędem walidacji. Zaokrąglanie i rozbicie VAT są symetryczne względem zera.

    Waluta jest tylko etykietą (bez przeliczeń kursowych); zaokrąglanie jak dla PLN.
    """
    konf = konfiguracja
    if tryb not in TRYBY:
        raise BladWalidacji(NIEPOPRAWNY_TRYB, "tryb", "dozwolone: %s, jest %r" % (TRYBY, tryb))
    tryb_vat = tryb_vat or konf.tryb_vat
    if tryb_vat not in TRYBY_VAT:
        raise BladWalidacji(NIEPOPRAWNY_TRYB, "tryb_vat", "dozwolone: %s, jest %r" % (TRYBY_VAT, tryb_vat))
    rozklad = rozklad_korekty or konf.rozklad_korekty
    if rozklad not in ROZKLADY:
        raise BladWalidacji(NIEPOPRAWNY_TRYB, "rozklad_korekty", "dozwolone: %s, jest %r" % (ROZKLADY, rozklad))
    waluta = _waluta(waluta)
    if narzut_proc is not None and marza_proc is not None:
        raise BladWalidacji(NARZUT_I_MARZA, "narzut_proc", "podaj narzut albo marżę, nie oba")
    if (narzut_proc is not None or marza_proc is not None) and tryb != TRYB_NETTO:
        raise BladWalidacji(NIEPOPRAWNY_TRYB, "tryb", "narzut/marża działa tylko w trybie od netto")

    with localcontext(KONTEKST):
        rabat_dok = _rabat(rabat_dokumentu_proc, "rabat_dokumentu_proc")
        wejscia = [pozycja_z_slownika(p) for p in pozycje]
        dzieci = zbuduj_hierarchie([(w.id, w.parent_id) for w in wejscia])
        liscie = [i for i in range(len(wejscia)) if i not in dzieci]  # tylko liście wchodzą do sum

        ilosci, ceny_po, rabaty, stawki, kwoty = [], [], [], [], []
        for i in liscie:
            p = wejscia[i]
            ilosc, cena, rabat, stawka = _wejscie_pozycji(i, p, tryb, narzut_proc, marza_proc, konf, dopusc_ujemne)
            cena_po = konf.cena(cena * (1 - rabat / _100))                 # punkt 1
            wartosc = konf.kwota(ilosc * cena_po)                           # punkt 2
            if rabat_dok > 0:
                wartosc = konf.kwota(wartosc * (1 - rabat_dok / _100))      # punkt 3
            ilosci.append(ilosc)
            ceny_po.append(cena_po)
            rabaty.append(rabat)
            stawki.append(stawka)
            kwoty.append(wartosc)

        # punkt 4: rozbicie per pozycja (zawsze liczone - baza dla obu trybów i dla rozbieznosc_vat)
        rozbite = [_rozbij(k, s, tryb, konf) for k, s in zip(kwoty, stawki)]
        netto = [r[0] for r in rozbite]
        vat = [r[1] for r in rozbite]
        brutto = [r[2] for r in rozbite]

        rozbieznosc = Decimal(0)
        for s in sorted(set(stawki)):
            idx = [i for i, x in enumerate(stawki) if x == s]
            _, vat_grupy, _ = _rozbij(sum(kwoty[i] for i in idx), s, tryb, konf)
            roznica = vat_grupy - sum(vat[i] for i in idx)
            rozbieznosc -= roznica
            if tryb_vat == VAT_PER_POZYCJA or roznica == 0:
                continue
            if rozklad == ROZKLAD_NAJWIEKSZA:
                # największa wartość w stawce, remis -> najniższy indeks (deterministycznie)
                najw = max(idx, key=lambda i: (abs(kwoty[i]), -i))
                nowe = {najw: vat[najw] + roznica if tryb == TRYB_NETTO else netto[najw] - roznica}
            else:
                docelowa = _rozbij(sum(kwoty[i] for i in idx), s, tryb, konf)[1 if tryb == TRYB_NETTO else 0]
                nowe_kol = _rozdziel_reszty([_dokladna_czesc(kwoty[i], s, tryb) for i in idx], docelowa, konf)
                nowe = dict(zip(idx, nowe_kol))
            for i, wartosc in nowe.items():
                if tryb == TRYB_NETTO:      # poprawiamy vat, brutto = netto + vat
                    vat[i], brutto[i] = wartosc, netto[i] + wartosc
                else:                       # poprawiamy netto, vat = brutto - netto
                    netto[i], vat[i] = wartosc, brutto[i] - wartosc

        wyniki_lisci = {}
        for j, i in enumerate(liscie):
            w = wejscia[i]
            wyniki_lisci[i] = PozycjaWynik(
                indeks=i, ilosc=ilosci[j], cena_po_rabacie=ceny_po[j], rabat_proc=rabaty[j],
                stawka_vat=stawki[j], netto=netto[j], vat=vat[j], brutto=brutto[j], id=w.id, parent_id=w.parent_id)
        wyniki = []
        for i, w in enumerate(wejscia):
            if i in wyniki_lisci:
                wyniki.append(wyniki_lisci[i])
                continue
            # pozycja nadrzędna (zestaw): suma liści pod nią; nie wchodzi do sum dokumentu
            potomne = [wyniki_lisci[j] for j in liscie_pod(i, dzieci)]
            wyniki.append(PozycjaWynik(
                indeks=i, ilosc=do_decimal(w.ilosc, "pozycje[%d].ilosc" % i), cena_po_rabacie=Decimal(0),
                rabat_proc=Decimal(0), stawka_vat=normalizuj_stawke(w.stawka_vat, "pozycje[%d].stawka_vat" % i),
                netto=sum((x.netto for x in potomne), Decimal(0)), vat=sum((x.vat for x in potomne), Decimal(0)),
                brutto=sum((x.brutto for x in potomne), Decimal(0)), id=w.id, parent_id=w.parent_id, zestaw=True))
        wyniki = tuple(wyniki)
        podsumowanie = podsumuj_stawki(wyniki)
        return DokumentWynik(
            waluta=waluta, tryb=tryb, tryb_vat=tryb_vat, pozycje=wyniki, podsumowanie=podsumowanie,
            suma_netto=sum((p.netto for p in podsumowanie), Decimal(0)),
            suma_vat=sum((p.vat for p in podsumowanie), Decimal(0)),
            suma_brutto=sum((p.brutto for p in podsumowanie), Decimal(0)),
            rozbieznosc_vat=rozbieznosc)
