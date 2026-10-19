"""Dodaje katalog główny repo do sys.path (unittest discover -s tests nie robi tego sam)."""
import os
import sys

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if KORZEN not in sys.path:
    sys.path.insert(0, KORZEN)
