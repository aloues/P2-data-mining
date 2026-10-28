"""Parte I — Construcción de los artefactos base (Spark).

Ejecución: Spark. Lee las tablas aplanadas, aplica el mapa de resolución de
entidades y exporta a artifacts/parte1/:

  supplier_features   vector de características por proveedor canónico
  buyer_features      vector de características por entidad compradora
  inter_buyer_supplier   matriz de interacción implícita entidad × proveedor
  inter_buyer_family     matriz entidad × familia UNSPSC (para SVD/contenido)
  edges_bipartite     grafo entidad → proveedor (PageRank/HITS)
  edges_coparticipation  grafo proveedor — proveedor por co-participación

Criterio de aristas de co-participación: dos proveedores se conectan si se
presentaron como postores al mismo proceso. Cada proceso con n postores aporta
1/(n-1) a cada par, para que una subasta con 200 postores no pese lo mismo
que un concurso con 3. Se conservan pares con al menos MIN_SHARED procesos en
común para filtrar coincidencias aisladas.

Uso:
    python -m src.parte1.build_artifacts
"""
import json

from pyspark.sql import DataFrame, functions as F

from src.common.config import ARTIFACTS_DIR, PROCESSED_DIR
from src.common.spark import get_spark

MIN_SHARED = 2
OUT = ARTIFACTS_DIR / "parte1"


def canonical(df: DataFrame, smap: DataFrame) -> DataFrame:
    return (
        df.join(smap.select("supplier_id", "canonical_id", "supplier_type"), "supplier_id", "left")
        .withColumn("supplier_id", F.coalesce("canonical_id", "supplier_id"))
        .drop("canonical_id")
    )


def top_share(df: DataFrame, key: str, other: str) -> DataFrame:
    """Participación del principal contraparte en el monto de `key`."""
    by_pair = df.groupBy(key, other).agg(F.sum("amount_pen").alias("amt"))
    return by_pair.groupBy(key).agg(
        (F.max("amt") / F.sum("amt")).alias(f"top_{other.split('_')[0]}_share")
    )


def supplier_features(items: DataFrame, tend: DataFrame) -> DataFrame:
    base = items.groupBy("supplier_id").agg(
        F.first("supplier_type", ignorenulls=True).alias("supplier_type"),
        F.countDistinct("ocid").alias("n_processes_won"),
        F.count("*").alias("n_items"),
        F.sum("amount_pen").alias("total_amount"),
        F.expr("percentile_approx(amount_pen, 0.5)").alias("median_item_amount"),
        F.countDistinct("buyer_id").alias("n_buyers"),
        F.countDistinct("buyer_department").alias("n_departments"),
        F.countDistinct("unspsc_family").alias("n_families"),
        F.avg(F.col("method").contains("Directa").cast("double")).alias("pct_direct"),
        F.avg((F.col("category") == "goods").cast("double")).alias("pct_goods"),
        F.avg((F.col("category") == "services").cast("double")).alias("pct_services"),
        F.avg((F.col("category") == "works").cast("double")).alias("pct_works"),
        F.avg("n_tenderers").alias("avg_competitors"),
    )
    bids = tend.groupBy("supplier_id").agg(F.countDistinct("ocid").alias("n_processes_bid"))
    return (
        base.join(top_share(items, "supplier_id", "buyer_id"), "supplier_id", "left")
        .join(bids, "supplier_id", "left")
        .withColumn("win_rate", F.col("n_processes_won") / F.greatest("n_processes_bid", "n_processes_won"))
        .withColumn("log_total_amount", F.log1p("total_amount"))
    )


def buyer_features(items: DataFrame) -> DataFrame:
    base = items.groupBy("buyer_id").agg(
        F.first("buyer_name").alias("buyer_name"),
        F.first("buyer_department").alias("department"),
        F.countDistinct("ocid").alias("n_processes"),
        F.sum("amount_pen").alias("total_amount"),
        F.countDistinct("supplier_id").alias("n_suppliers"),
        F.countDistinct("unspsc_family").alias("n_families"),
        F.avg(F.col("method").contains("Directa").cast("double")).alias("pct_direct"),
        F.avg("n_tenderers").alias("avg_competitors"),
        F.avg((F.col("n_tenderers") <= 1).cast("double")).alias("pct_single_bidder"),
    )
    return (
        base.join(top_share(items, "buyer_id", "supplier_id"), "buyer_id", "left")
        .withColumn("log_total_amount", F.log1p("total_amount"))
    )


def coparticipation(tend: DataFrame) -> DataFrame:
    t = tend.select("ocid", "supplier_id").distinct()
    n = t.groupBy("ocid").agg(F.count("*").alias("n"))
    t = t.join(n.filter("n >= 2"), "ocid")
    pairs = (
        t.alias("a").join(t.alias("b"), "ocid")
        .filter(F.col("a.supplier_id") < F.col("b.supplier_id"))
        .select(
            F.col("a.supplier_id").alias("src"),
            F.col("b.supplier_id").alias("dst"),
            (1.0 / (F.col("a.n") - 1)).alias("w"),
        )
    )
    return (
        pairs.groupBy("src", "dst")
        .agg(F.count("*").alias("n_shared"), F.sum("w").alias("weight"))
        .filter(F.col("n_shared") >= MIN_SHARED)
    )


def main() -> None:
    spark = get_spark("parte1-artifacts")
    smap = spark.read.parquet(str(PROCESSED_DIR / "supplier_map"))
    items = canonical(spark.read.parquet(str(PROCESSED_DIR / "items")), smap) \
        .filter(F.col("amount_pen").isNotNull()).cache()
    tend = canonical(spark.read.parquet(str(PROCESSED_DIR / "tenderers")), smap)

    inter = items.groupBy("buyer_id", "supplier_id").agg(
        F.count("*").alias("n_items"),
        F.countDistinct("ocid").alias("n_processes"),
        F.sum("amount_pen").alias("amount_pen"),
    )
    outputs = {
        "supplier_features": supplier_features(items, tend),
        "buyer_features": buyer_features(items),
        "inter_buyer_supplier": inter,
        "inter_buyer_family": items.filter(F.col("unspsc_family").isNotNull())
            .groupBy("buyer_id", "unspsc_family")
            .agg(F.count("*").alias("n_items"), F.sum("amount_pen").alias("amount_pen")),
        "edges_bipartite": inter.select(
            F.col("buyer_id").alias("src"), F.col("supplier_id").alias("dst"),
            "n_processes", F.col("amount_pen").alias("weight")),
        "edges_coparticipation": coparticipation(tend),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, df in outputs.items():
        df.write.mode("overwrite").parquet(str(OUT / name))
        summary[name] = spark.read.parquet(str(OUT / name)).count()
        print(f"{name:24s} {summary[name]:>10,d} filas")

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    spark.stop()


if __name__ == "__main__":
    main()
