"""
inspect_real_formats.py

Run inside HUS Acamedic in the folder with the real CSV files.
Prints each file name, its separator, its columns, and the FORMAT of the first
value in each column: digits become 9, letters become a (or A if upper case),
everything is cut to 40 characters. No real values are printed.

Usage:
  python inspect_real_formats.py
  python inspect_real_formats.py /path/to/csv/folder
"""

import glob
import os
import re
import sys

import pandas as pd

folder = sys.argv[1] if len(sys.argv) > 1 else "."  # Folder with the real CSV files


def shape(value):
    """2024-10-10T21:00:00.000Z -> 9999-99-99A99:99:99.999A (format only)."""
    value = re.sub(r"\d", "9", str(value))
    value = re.sub(r"[^\W\d_]", lambda match: "A" if match.group().isupper() else "a", value)
    return value[:40]


for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
    # Separator = the one that splits the header into the most columns
    with open(path, encoding="utf-8", errors="replace") as file:
        header = file.readline()
    separator = max([",", ";", "\t"], key=lambda candidate: len(header.split(candidate)))

    table = pd.read_csv(path, sep=separator, dtype=str, nrows=200,
                        encoding="utf-8", encoding_errors="replace")
    print("\n=== %s   separator %r" % (os.path.basename(path), separator))
    for column in table.columns:
        values = table[column].dropna()
        example = shape(values.iloc[0]) if len(values) else "(empty in first 200 rows)"
        print("  %-45s %s" % (column, example))
