"""Parte I — Diagnósticos: compradores, enlaces incompletos y particionamiento (Spark).

Ejecución: Spark. Mide sobre los datos reales las decisiones de la Parte I y
exporta artifacts/parte1/diagnostics.json y web/data/parte1.js (reporte web):

  entity_resolution  resumen del mapa de proveedores (supplier_map).
  buyers       ¿hay compradores duplicados? Se buscan nombres normalizados
                iguales con distinto buyer_id.
  contracts     cobertura de contratos por adjudicación (enlaces incompletos).
  partitioning  efecto del particionamiento sobre el plan de ejecución:
                  1. el .gz no es divisible -> 1 partición; repartition.
                  2. partitionBy(buyer_department) -> partition pruning.
                  3. shuffle del self-join de co-participación y número de
                     particiones de shuffle (con AQE).

Uso:
    python -m src.parte1.diagnostics
"""
import contextlib
import io
import json
import statistics
import time

from pyspark.sql import functions as F

from src.common.config import ARTIFACTS_DIR, PROCESSED_DIR, RAW_DIR, ROOT
from src.common.spark import get_spark
from src.parte1.build_artifacts import canonical, coparticipation
from src.parte1.entity_resolution import normalize_name
from src.parte1.flatten import build_items, build_parties, build_tenderers

OUT = ARTIFACTS_DIR / "parte1"
WEB_DATA = ROOT / "web" / "data"
REPEATS = 5


def plan(df, mode: str = "formatted") -> str:
    """Texto de df.explain(); PySpark lo imprime en stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        df.explain(mode=mode)
    return buf.getvalue().strip()


def physical_only(text: str) -> str:
    """De un plan 'extended' se queda solo con el plan físico."""
    return text.split("== Physical Plan ==")[-1].strip()


def timed(action, repeats: int = REPEATS) -> float:
    """Mediana en segundos; la primera corrida se descarta (calentamiento)."""
    action()
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        action()
        runs.append(time.perf_counter() - t0)
    return round(statistics.median(runs), 3)


def n_files(path) -> int:
    return sum(1 for p in path.rglob("*.parquet"))


def entity_resolution(spark) -> dict:
    smap = spark.read.parquet(str(PROCESSED_DIR / "supplier_map"))
    merged = smap.filter("match_rule != 'propio'").join(
        smap.select(F.col("supplier_id").alias("canonical_id"),
                    F.col("name_norm").alias("canonical_name")), "canonical_id")
    count_by = lambda c: {r[c]: r["count"] for r in smap.groupBy(c).count().collect()}
    return {
        "n_ids": smap.count(),
        "n_canonical": smap.select("canonical_id").distinct().count(),
        "by_type": count_by("supplier_type"),
        "by_rule": count_by("match_rule"),
        "examples": [r.asDict() for r in merged.select(
            "supplier_id", "name_norm", "canonical_id", "canonical_name", "match_rule")
            .orderBy(F.desc("match_rule")).limit(12).collect()],
    }


def buyers(items) -> dict:
    b = items.select("buyer_id", "buyer_name", "buyer_department").distinct()
    dup = (
        b.withColumn("name_norm", normalize_name(F.col("buyer_name")))
        .groupBy("name_norm")
        .agg(F.countDistinct("buyer_id").alias("n_ids"),
             F.collect_set("buyer_id").alias("ids"),
             F.collect_set("buyer_department").alias("departments"))
        .filter("n_ids > 1")
    )
    return {
        "n_buyer_ids": b.select("buyer_id").distinct().count(),
        "id_schemes": [r.asDict() for r in b.groupBy(
            F.regexp_extract("buyer_id", r"^([A-Z]+-[A-Z]+)", 1).alias("scheme")).count().collect()],
        "same_name_groups": [r.asDict() for r in dup.collect()],
    }


def contracts(items) -> dict:
    total = items.agg(F.count("*").alias("n"), F.sum("amount_pen").alias("amt")).first()
    rows = items.groupBy("has_contract").agg(
        F.count("*").alias("n_items"), F.sum("amount_pen").alias("amount_pen"),
        F.expr("percentile_approx(amount_pen, 0.5)").alias("median_item")).collect()
    by_cat = items.groupBy("category").agg(
        F.avg((~F.col("has_contract")).cast("double")).alias("pct_without_contract"),
        F.count("*").alias("n_items")).collect()
    return {
        "n_items": total["n"],
        "amount_pen": total["amt"],
        "by_flag": [r.asDict() for r in rows],
        "by_category": [r.asDict() for r in by_cat],
    }


def gz_partitions(spark) -> dict:
    raw = spark.read.json(str(RAW_DIR / "2024.jsonl.gz"))
    n_raw = raw.rdd.getNumPartitions()
    target = spark.sparkContext.defaultParallelism * 2
    rep = raw.repartition(target)

    # Como en flatten.py: el JSON se cachea una vez y se recorre varias
    # veces (parties, items, tenderers). Se mide lo que cuesta construir
    # las tres tablas sobre la caché con 1 partición vs reparticionada.
    def build_all(df):
        parties = build_parties(df)
        for out in (parties, build_items(df, parties), build_tenderers(df)):
            out.write.format("noop").mode("overwrite").save()

    t0 = time.perf_counter()
    raw.cache().count()
    t_read = time.perf_counter() - t0
    rep.cache().count()
    t_raw = timed(lambda: build_all(raw), repeats=2)
    t_rep = timed(lambda: build_all(rep), repeats=2)
    raw.unpersist()
    rep.unpersist()
    return {
        "default_parallelism": spark.sparkContext.defaultParallelism,
        "partitions_after_read": n_raw,
        "partitions_after_repartition": target,
        "seconds_read_gz": round(t_read, 3),
        "seconds_flatten_1_partition": t_raw,
        "seconds_flatten_repartitioned": t_rep,
        "plan_repartitioned": physical_only(plan(
            rep.select(F.explode("awards").alias("a")), "extended")),
    }


def pruning(spark) -> dict:
    """Compara tres layouts de la misma tabla items:
    flat         sin particionar (18 archivos, uno por tarea)
    smallfiles   partitionBy sin repartition previo (como estaba antes)
    partitioned  repartition + partitionBy (layout actual de flatten.py)
    """
    paths = {
        "partitioned": PROCESSED_DIR / "items",
        "flat": PROCESSED_DIR / "items_flat",
        "smallfiles": PROCESSED_DIR / "items_smallfiles",
    }
    base = spark.read.parquet(str(paths["partitioned"]))
    base.repartition(18).write.mode("overwrite").parquet(str(paths["flat"]))
    base.repartition(22).write.mode("overwrite").partitionBy("buyer_department") \
        .parquet(str(paths["smallfiles"]))
    dfs = {k: spark.read.parquet(str(p)) for k, p in paths.items()}

    cusco = lambda df: df.filter(F.col("buyer_department") == "CUSCO") \
        .groupBy("supplier_id").agg(F.sum("amount_pen").alias("amt"))
    full = lambda df: df.groupBy("buyer_department").agg(F.sum("amount_pen").alias("amt"))
    run = lambda df: df.write.format("noop").mode("overwrite").save()

    layouts = {}
    for k, df in dfs.items():
        cusco_dir = paths[k] / "buyer_department=CUSCO"
        layouts[k] = {
            "files_total": n_files(paths[k]),
            "files_read_cusco": n_files(cusco_dir) if cusco_dir.exists() else n_files(paths[k]),
            "seconds_cusco": timed(lambda: run(cusco(df))),
            "seconds_full_scan": timed(lambda: run(full(df))),
        }
    return {
        "query_cusco": "items.filter(buyer_department = 'CUSCO').groupBy(supplier_id).sum(amount_pen)",
        "query_full": "items.groupBy(buyer_department).sum(amount_pen)",
        "n_departments": dfs["partitioned"].select("buyer_department").distinct().count(),
        "layouts": layouts,
        "plan_partitioned": plan(cusco(dfs["partitioned"])),
        "plan_flat": plan(cusco(dfs["flat"])),
    }


def shuffle(spark) -> dict:
    smap = spark.read.parquet(str(PROCESSED_DIR / "supplier_map"))
    tend = canonical(spark.read.parquet(str(PROCESSED_DIR / "tenderers")), smap)
    edges = coparticipation(tend)

    timings = {}
    for n in (8, 32, 200):
        spark.conf.set("spark.sql.shuffle.partitions", n)
        timings[n] = timed(lambda: edges.write.format("noop").mode("overwrite").save(), repeats=2)
    spark.conf.set("spark.sql.shuffle.partitions", 32)

    text = plan(edges)
    return {
        "seconds_by_shuffle_partitions": timings,
        "plan_coparticipation": text,
        "n_exchanges": text.split("\n\n")[0].count("Exchange"),
    }


def main() -> None:
    spark = get_spark("parte1-diagnostics")
    spark.sparkContext.setLogLevel("ERROR")
    items = spark.read.parquet(str(PROCESSED_DIR / "items")).cache()

    out = {
        "entity_resolution": entity_resolution(spark),
        "buyers": buyers(items),
        "contracts": contracts(items),
    }
    # Sin esto las lecturas siguientes de items saldrían de la caché y el
    # plan no mostraría el partition pruning.
    items.unpersist()
    out |= {
        "partitioning": {
            "gz": gz_partitions(spark),
            "pruning": pruning(spark),
            "shuffle": shuffle(spark),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "diagnostics.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Para la web: diagnósticos + conteos de los artefactos de build_artifacts
    out["artifacts"] = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    (WEB_DATA / "parte1.js").write_text(
        "window.P1 = " + json.dumps(out, ensure_ascii=False, default=str) + ";", encoding="utf-8")

    p = out["partitioning"]
    print("compradores con nombre repetido:", len(out["buyers"]["same_name_groups"]))
    print("gz:", p["gz"]["partitions_after_read"], "->", p["gz"]["partitions_after_repartition"],
          "particiones | lectura", p["gz"]["seconds_read_gz"], "s | aplanado",
          p["gz"]["seconds_flatten_1_partition"], "s vs",
          p["gz"]["seconds_flatten_repartitioned"], "s")
    for k, v in p["pruning"]["layouts"].items():
        print("layout", k, v)
    print("shuffle:", p["shuffle"]["seconds_by_shuffle_partitions"])
    spark.stop()


if __name__ == "__main__":
    main()
