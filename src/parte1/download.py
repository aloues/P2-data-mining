"""Descarga los archivos anuales del registro OCDS Perú (OECE/OSCE).

Uso:
    python -m src.parte1.download --years 2023 2024
"""
import argparse
import urllib.request

from src.common.config import DEFAULT_YEARS, OCDS_URL, RAW_DIR


def download_year(year: int, force: bool = False) -> None:
    dest = RAW_DIR / f"{year}.jsonl.gz"
    if dest.exists() and not force:
        print(f"[{year}] ya existe, se omite ({dest.stat().st_size / 1e6:.0f} MB)")
        return
    url = OCDS_URL.format(year=year)
    print(f"[{year}] descargando {url}")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    print(f"[{year}] listo ({dest.stat().st_size / 1e6:.0f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for year in args.years:
        download_year(year, args.force)


if __name__ == "__main__":
    main()
