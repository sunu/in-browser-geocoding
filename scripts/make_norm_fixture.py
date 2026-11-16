"""Write web/test/fixtures/norm_names.json: names and their keys from geoparse.execute.data.norm_name.

Usage: uv run python scripts/make_norm_fixture.py [--divisions data/build-world/divisions.parquet]

The Python test (tests/test_norm_name.py) and the TS test (web/test/core.test.ts) both check this file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from geoparse.config import REPO_ROOT
from geoparse.execute.data import norm_name

OUT = REPO_ROOT / "web" / "test" / "fixtures" / "norm_names.json"

CASES = [
    "Tamil-Nadu ", "  São Paulo", "Łódź", "Zürich", "Ærøskøbing", "Straße", "Þingvellir", "İstanbul", "Đà Nẵng",
    "Malmö", "Ñuñoa", "Œuvre", "Ħamrun", "Москва", "Йошкар-Ола", "Αθήνα", "ΟΔΟΣ", "東京都", "北京市", "서울특별시",
    "मुंबई", "தமிழ்நாடு", "กรุงเทพมหานคร", "القاهرة", "תל אביב-יפו", "ﬁnland", "Ｔｏｋｙｏ", "St. John's", "Saint-Étienne",
    "N'Djamena", "Côte d'Ivoire", "100 Mile House", "Ⅻ district", "a b", "x_y", "",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--divisions", type=Path, default=REPO_ROOT / "data" / "build-world" / "divisions.parquet")
    args = ap.parse_args()
    names = list(CASES)
    if args.divisions.exists():
        # Up to 5 names for each country, so that all scripts in the data are in the sample.
        rows = duckdb.sql(f"""
            SELECT n FROM (
                SELECT unnest(list_concat([name, name_en], alt_names)) AS n, country,
                       row_number() OVER (PARTITION BY country ORDER BY hash(id)) AS r
                FROM read_parquet('{args.divisions}'))
            WHERE r <= 5 AND n IS NOT NULL ORDER BY country, n""").fetchall()
        names += sorted({r[0] for r in rows} - set(CASES))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([[n, norm_name(n)] for n in names], ensure_ascii=False, indent=0) + "\n")
    print(f"{OUT}: {len(names)} names")


if __name__ == "__main__":
    main()
