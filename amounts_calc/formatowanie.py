"""Wyświetlanie Decimal bez ogona zer (bez zaokrąglania i bez udziału kontekstu Decimal)."""


def format_bez_zer(d):
    """Postać dziesiętna bez zbędnych zer na końcu części ułamkowej: 1758.285000 -> 1758.285, 100.0 -> 100."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def format_kwoty(d):
    """Postać kanoniczna kwoty: bez zbędnych zer, ale co najmniej 2 miejsca po przecinku.

    140220.0000 -> 140220.00, 1758.285000 -> 1758.285, 0E-10 -> 0.00. Nic nie jest zaokrąglane.
    """
    calk, _, ulam = format_bez_zer(d).partition(".")
    return "%s.%s" % (calk, ulam.ljust(2, "0"))


def miejsca_znaczace(d):
    """Liczba znaczących miejsc po przecinku (bez końcowych zer); 0 dla liczb całkowitych."""
    _, _, ulam = format_bez_zer(d).partition(".")
    return len(ulam)
