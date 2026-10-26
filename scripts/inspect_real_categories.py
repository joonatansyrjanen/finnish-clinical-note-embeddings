"""
inspect_real_categories.py

Run inside HUS Acamedic. Answers the open questions about the mock data by printing
counts of category labels only (note tabs, contact types and the like), plus the
length of the hashed IDs. Prints no free text, names, dates or IDs.

Usage:
  python inspect_real_categories.py "/path/to/export"
"""

import os
import sys

import pandas as pd

folder = sys.argv[1] if len(sys.argv) > 1 else "."  # Folder with the real CSV files


def show(file_name, column, top=15):
    """Top category counts for one column."""
    table = pd.read_csv(os.path.join(folder, file_name), sep=";", dtype=str, usecols=[column])
    print("\n=== %s . %s" % (file_name, column))
    print(table[column].value_counts(dropna=False).head(top).to_string())


# Note structure
show("Apotti_potilaskertomus.csv", "merkinta_valilehti_selite", 25)
show("Apotti_potilaskertomus.csv", "kontaktityyppi_selite")
show("Apotti_potilaskertomus.csv", "kayntityyppi_selite")
show("Apotti_potilaskertomus.csv", "toimipiste_eala_selite")

# First word of each note (the author's role in the header line)
notes = pd.read_csv(os.path.join(folder, "Apotti_potilaskertomus.csv"), sep=";", dtype=str, usecols=["merkinta_teksti"], nrows=20000)
print("\n=== First word of merkinta_teksti")
print(notes["merkinta_teksti"].str.split().str[0].value_counts().head(10).to_string())

# Diagnosis flags
show("Apotti_diagnoosi.csv", "syy_tai_oire")
show("Apotti_diagnoosi.csv", "kontakti_kayntityyppi_selite")

# Hash length of the IDs
kaynti = pd.read_csv(os.path.join(folder, "Apotti_kaynti.csv"), sep=";", dtype=str, usecols=["shjakso_id"], nrows=100)
print("\n=== Length of shjakso_id:", kaynti["shjakso_id"].str.len().value_counts().to_dict())
