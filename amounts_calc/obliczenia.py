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
from .hierarchia import zbuduj_hierarchie
from .zestawy import podsumowanie_stawek, rodzice, rozwin
from .bledy import (BRAK_CENY, CENA_UJEMNA, ILOSC_UJEMNA, NARZUT_I_MARZA, NIEPOPRAWNA_WALUTA,
                    NIEPOPRAWNY_TRYB, RABAT_POZA_ZAKRESEM, BladWalidacji)
from .config import (DOMYSLNA, KONTEKST, ROZKLADY, ROZKLAD_NAJWIEKSZA, TRYB_BRUTTO, TRYB_NETTO,
                     TRYBY, TRYBY_VAT, VAT_PER_POZYCJA)
from .model import (DokumentWynik, PodsumowanieStawki, PozycjaWynik, pozycja_z_slownika, ustal_opcje)
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
           dopusc_ujemne=False, ilosc_zestawu=False, wlaczone_alternatywy=None, konfiguracja=DOMYSLNA,
           tryb_opcji=None):
    """Przelicza dokument. `pozycje`: lista Pozycja lub słowników. Zwraca DokumentWynik.

    `dopusc_ujemne=True` dopuszcza ujemne ilości i ceny (rabat jako osobna linia, korekta, zwrot);
    domyślnie są błędem walidacji. Zaokrąglanie i rozbicie VAT są symetryczne względem zera.

    `ilosc_zestawu=True`: ilość pozycji nadrzędnej (zestawu) mnoży sumę jej dzieci - dzieci opisują 1 szt.
    zestawu (ich wiersze w wyniku są na 1 szt.), zestaw ma wartość N x dzieci, a do sum dokumentu wchodzi
    N x dzieci (dzieci nie są liczone drugi raz). Domyślnie False: ilość zestawu jest ignorowana.
    `wlaczone_alternatywy`: które pozycje z `alternatywa` / `grupa_opcji` wchodzą do sum - None (żadna),
    "wszystkie" albo kolekcja indeksów pozycji; bez takich pól nic się nie zmienia.
    Tryb jawny opcji: gdy którakolwiek pozycja najwyższego poziomu ma `tryb_opcji` ("brak" | "opcja" |
    "alternatywa"), do sum wchodzą pozycje "brak" oraz opcje i alternatywy z `wybrana`=true, a
    `wlaczone_alternatywy` jest ignorowane. `tryb_opcji` (parametr): "auto" (domyślnie) | "jawny" | "awaryjny".

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
        liscie = [i for i in range(len(wejscia)) if i not in dzieci]  # liście liczone są na 1 szt. zestawu
        rodzic = rodzice(dzieci)
        opcje = ustal_opcje(wejscia, rodzic, tryb_opcji)
        alt = opcje["alt"]
        if opcje["jawny"]:
            wlaczone = opcje["wlaczone"]
        elif wlaczone_alternatywy is None:
            wlaczone = frozenset()
        elif wlaczone_alternatywy == "wszystkie":
            wlaczone = frozenset(i for i, g in alt.items() if g is not None)
        else:
            wlaczone = frozenset(int(i) for i in wlaczone_alternatywy)
        ilosci_zestawow = {i: do_decimal(wejscia[i].ilosc, "pozycje[%d].ilosc" % i) for i in dzieci}

        def waga(i):
            """Ile razy liść wchodzi do sum dokumentu: iloczyn ilości zestawów nad nim, 0 dla opcji spoza wyboru."""
            m, a, gora = Decimal(1), rodzic.get(i), i
            while a is not None:
                m *= ilosci_zestawow[a] if ilosc_zestawu else 1
                gora, a = a, rodzic.get(a)
            return Decimal(0) if alt[gora] is not None and gora not in wlaczone else m

        wagi = [waga(i) for i in liscie]

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
            # liczą się tylko liście wchodzące do sum; sumy grupy ważone ilością zestawów nad liściem
            idx = [i for i, x in enumerate(stawki) if x == s and wagi[i] != 0]
            if not idx:
                continue
            suma_kwot = sum((wagi[i] * kwoty[i] for i in idx), Decimal(0))
            cel_vat = _rozbij(suma_kwot, s, tryb, konf)
            roznica = cel_vat[1] - sum((wagi[i] * vat[i] for i in idx), Decimal(0))
            rozbieznosc -= roznica
            if tryb_vat == VAT_PER_POZYCJA or roznica == 0:
                continue
            # korektę groszową przyjmuje tylko liść o wadze 1 (korekty nie da się rozdzielić na N sztuk zestawu)
            kandydaci = [i for i in idx if wagi[i] == 1]
            if not kandydaci:
                continue
            if rozklad == ROZKLAD_NAJWIEKSZA:
                # największa wartość w stawce, remis -> najniższy indeks (deterministycznie)
                najw = max(kandydaci, key=lambda i: (abs(kwoty[i]), -i))
                nowe = {najw: vat[najw] + roznica if tryb == TRYB_NETTO else netto[najw] - roznica}
            else:
                docelowa = cel_vat[1 if tryb == TRYB_NETTO else 0]
                stala = sum((wagi[i] * (vat[i] if tryb == TRYB_NETTO else netto[i]) for i in idx if wagi[i] != 1),
                            Decimal(0))
                nowe_kol = _rozdziel_reszty([_dokladna_czesc(kwoty[i], s, tryb) for i in kandydaci],
                                            docelowa - stala, konf)
                nowe = dict(zip(kandydaci, nowe_kol))
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
                stawka_vat=stawki[j], netto=netto[j], vat=vat[j], brutto=brutto[j], id=w.id, parent_id=w.parent_id,
                alternatywa=alt[i], tryb_opcji=opcje["tryby"].get(i), wybrana=opcje["wybrana"].get(i))
        # pozycje nadrzędne (zestawy): N x suma dzieci (dzieci na 1 szt.), rekurencyjnie; dla N = 1 zwykła suma
        wiersze = []
        for i, w in enumerate(wejscia):
            if i in wyniki_lisci:
                r = wyniki_lisci[i]
                wiersze.append({"indeks": i, "id": r.id, "ilosc": r.ilosc, "netto": r.netto, "vat": r.vat,
                                "brutto": r.brutto, "stawka": r.stawka_vat, "zestaw": False, "alternatywa": alt[i]})
            else:
                wiersze.append({"indeks": i, "id": w.id, "ilosc": ilosci_zestawow[i], "netto": None, "vat": None,
                                "brutto": None, "stawka": None, "zestaw": True, "alternatywa": alt[i]})
        rozw = rozwin(wiersze, dzieci, ilosc_zestawu, konf)
        wyniki = []
        for i, w in enumerate(wejscia):
            if i in wyniki_lisci:
                wyniki.append(wyniki_lisci[i])
                continue
            o = rozw["oczekiwane"][i]
            wyniki.append(PozycjaWynik(
                indeks=i, ilosc=ilosci_zestawow[i], cena_po_rabacie=Decimal(0),
                rabat_proc=Decimal(0), stawka_vat=normalizuj_stawke(w.stawka_vat, "pozycje[%d].stawka_vat" % i),
                netto=o["netto"], vat=o["vat"], brutto=o["brutto"], id=w.id, parent_id=w.parent_id, zestaw=True,
                alternatywa=alt[i], tryb_opcji=opcje["tryby"].get(i), wybrana=opcje["wybrana"].get(i)))
        wyniki = tuple(wyniki)
        sumy_stawek = podsumowanie_stawek(wiersze, dzieci, rozw, wlaczone, konf)
        podsumowanie = tuple(PodsumowanieStawki(s, v["netto"], v["vat"], v["brutto"]) for s, v in sumy_stawek.items())
        return DokumentWynik(
            waluta=waluta, tryb=tryb, tryb_vat=tryb_vat, pozycje=wyniki, podsumowanie=podsumowanie,
            suma_netto=sum((p.netto for p in podsumowanie), Decimal(0)),
            suma_vat=sum((p.vat for p in podsumowanie), Decimal(0)),
            suma_brutto=sum((p.brutto for p in podsumowanie), Decimal(0)),
            rozbieznosc_vat=rozbieznosc, ilosc_zestawu=bool(ilosc_zestawu),
            wlaczone_alternatywy=tuple(sorted(wlaczone)),
            alternatywy=("jawne" if opcje["jawny"]
                         else "wybrane" if any(g is not None for g in alt.values()) else "brak"),
            opcje_jawne=opcje["jawny"])
