"""Parte I — Aplanado de OCDS al grano entidad–proveedor–ítem (Spark).

Ejecución: Spark (obligatorio en la Parte I). El JSON anidado se lee una sola
vez y se generan tres tablas en data/processed/:

  items      una fila por ítem adjudicado: entidad compradora, proveedor,
             clasificación del ítem y monto en soles. Es la base para los
             vectores de características y la matriz de interacción.
  tenderers  una fila por (proceso, postor). Sirve para el grafo de
             co-participación: dos proveedores se conectan si compiten en
             el mismo proceso.
  parties    catálogo de actores (entidades y proveedores) con su región.

Decisión sobre enlaces incompletos: la arista entidad–proveedor se toma de
la adjudicación (awards) y no del contrato, porque ~17% de las adjudicaciones
no tienen contrato vinculado. Se conserva la marca `has_contract` para poder
filtrarlas después si se requiere.

Uso:
    python -m src.parte1.flatten --years 2024
"""
import argparse

from pyspark.sql import DataFrame, functions as F

from src.common.config import DEFAULT_YEARS, PROCESSED_DIR, RAW_DIR
from src.common.spark import get_spark


def ruc_from_id(col):
    """'PE-RUC-20543312232' -> '20543312232'; otros esquemas se dejan igual."""
    return F.regexp_replace(col, r"^PE-RUC-", "")


def to_pen(value_col):
    """Convierte un Value OCDS a soles usando su tipo de cambio a PEN."""
    rate = F.filter(value_col.exchangeRates, lambda x: x.currency == "PEN")[0].rate
    return F.when(value_col.currency == "PEN", value_col.amount) \
            .otherwise(value_col.amount * rate)


def build_parties(rec: DataFrame) -> DataFrame:
    p = rec.select(F.explode("parties").alias("p")).select("p.*")
    return (
        p.select(
            F.col("id").alias("party_id"),
            F.upper(F.trim("name")).alias("name"),
            F.col("address.department").alias("department"),
            F.col("roles"),
        )
        .groupBy("party_id")
        .agg(
            F.first("name", ignorenulls=True).alias("name"),
            F.first("department", ignorenulls=True).alias("department"),
            F.array_distinct(F.flatten(F.collect_list("roles"))).alias("roles"),
        )
    )


def build_items(rec: DataFrame, parties: DataFrame) -> DataFrame:
    contracted = rec.select(
        "ocid", F.explode("contracts.awardID").alias("award_id")
    ).distinct().withColumn("has_contract", F.lit(True))

    awards = rec.select(
        "ocid",
        F.col("buyer.id").alias("buyer_id"),
        F.col("tender.id").alias("tender_id"),
        F.col("tender.procurementMethodDetails").alias("method"),
        F.col("tender.mainProcurementCategory").alias("category"),
        F.col("tender.numberOfTenderers").alias("n_tenderers"),
        F.explode("awards").alias("a"),
    )

    items = (
        awards
        .select(
            "*",
            F.col("a.id").alias("award_id"),
            F.to_date("a.date").alias("award_date"),
            F.explode("a.suppliers").alias("s"),
        )
        .select(
            "*",
            F.explode("a.items").alias("it"),
        )
        .select(
            "ocid", "tender_id", "buyer_id", "method", "category", "n_tenderers",
            "award_id", "award_date",
            F.col("s.id").alias("supplier_id"),
            ruc_from_id(F.col("s.id")).alias("supplier_ruc"),
            F.col("it.id").alias("item_id"),
            F.col("it.description").alias("item_desc"),
            F.col("it.classification.id").alias("cubso_id"),
            F.col("it.classification.description").alias("cubso_desc"),
            F.col("it.additionalClassifications")[0].id.alias("unspsc_id"),
            F.col("it.quantity").alias("quantity"),
            F.col("it.totalValue.currency").alias("currency"),
            to_pen(F.col("it.totalValue")).alias("amount_pen"),
        )
        # Familia UNSPSC (4 primeros dígitos) como categoría agregada del ítem
        .withColumn("unspsc_family", F.substring("unspsc_id", 1, 4))
    )

    buyer_info = parties.select(
        F.col("party_id").alias("buyer_id"),
        F.col("name").alias("buyer_name"),
        F.col("department").alias("buyer_department"),
    )
    supplier_name = parties.select(
        F.col("party_id").alias("supplier_id"),
        F.col("name").alias("supplier_name"),
    )

    return (
        items
        .join(contracted, ["ocid", "award_id"], "left")
        .fillna({"has_contract": False})
        .join(buyer_info, "buyer_id", "left")
        .join(supplier_name, "supplier_id", "left")
    )


def build_tenderers(rec: DataFrame) -> DataFrame:
    return (
        rec.select(
            "ocid",
            F.col("buyer.id").alias("buyer_id"),
            F.explode("tender.tenderers").alias("t"),
        )
        .select(
            "ocid", "buyer_id",
            F.col("t.id").alias("supplier_id"),
            ruc_from_id(F.col("t.id")).alias("supplier_ruc"),
        )
        .dropDuplicates(["ocid", "supplier_id"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    args = parser.parse_args()

    spark = get_spark("parte1-flatten")
    paths = [str(RAW_DIR / f"{y}.jsonl.gz") for y in args.years]

    # Un .gz no es divisible: Spark lo lee en una sola partición. Se
    # reparticiona apenas se carga para paralelizar los explode posteriores.
    rec = spark.read.json(paths).repartition(spark.sparkContext.defaultParallelism * 2)
    rec.cache()

    parties = build_parties(rec)
    items = build_items(rec, parties)
    tenderers = build_tenderers(rec)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    parties.write.mode("overwrite").parquet(str(PROCESSED_DIR / "parties"))
    # Particionado físico por departamento de la entidad: los análisis
    # regionales leen solo las carpetas necesarias (partition pruning).
    # El repartition previo por la misma columna deja un archivo por
    # departamento; sin él cada tarea escribe en cada carpeta (25 × 22 = 550
    # archivos pequeños, ver diagnostics.py).
    items.repartition("buyer_department").write.mode("overwrite") \
         .partitionBy("buyer_department").parquet(str(PROCESSED_DIR / "items"))
    tenderers.write.mode("overwrite").parquet(str(PROCESSED_DIR / "tenderers"))

    items = spark.read.parquet(str(PROCESSED_DIR / "items"))
    print("items:", items.count(),
          "| entidades:", items.select("buyer_id").distinct().count(),
          "| proveedores:", items.select("supplier_id").distinct().count())
    print("tenderers:", spark.read.parquet(str(PROCESSED_DIR / "tenderers")).count())
    print("parties:", spark.read.parquet(str(PROCESSED_DIR / "parties")).count())
    spark.stop()


if __name__ == "__main__":
    main()
