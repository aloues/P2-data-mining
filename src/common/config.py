"""Rutas y parámetros compartidos por todas las partes del proyecto."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # jsonl.gz descargados del registro OCDS
PROCESSED_DIR = DATA_DIR / "processed"  # parquet intermedios (Spark)
ARTIFACTS_DIR = ROOT / "artifacts"    # salidas ligeras para el reporte web

OCDS_URL = "https://data.open-contracting.org/en/publication/135/download?name={year}.jsonl.gz"

DEFAULT_YEARS = [2024]
