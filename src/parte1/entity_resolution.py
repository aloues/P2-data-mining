"""Parte I — Resolución de entidades de proveedores (Spark).

Ejecución: Spark. El join aproximado de MinHash/LSH es la parte costosa y
escala con Spark MLlib.

Diagnóstico sobre los datos 2024 (ver README):
  * Todos los proveedores vienen con esquema PE-RUC, pero ~19% de los IDs no
    tienen 11 dígitos. La mayoría son códigos internos de consorcio
    (4–7 dígitos), aunque el nombre no siempre diga "CONSORCIO".
  * Los IDs que empiezan con "L" son proveedores extranjeros.
  * Hay nombres genéricos de consorcio ("CONSORCIO SANTA ROSA") compartidos
    por decenas de códigos distintos: son consorcios diferentes y NO se
    fusionan por nombre.
  * El duplicado real es un código corto asignado a una sola firma que
    también aparece con su RUC ("BIOMEDICAL LINE S.A.C" vs RUC 2051934...).

Regla de fusión: solo un ID sin RUC válido puede mapearse a un RUC válido, y
solo si su nombre normalizado coincide exactamente o es casi idéntico
(distancia de Jaccard sobre trigramas <= JACCARD_MAX). Dos RUC válidos nunca se
fusionan: legalmente son contribuyentes distintos.

Salida: data/processed/supplier_map
  supplier_id | canonical_id | supplier_type | name_norm | match_rule

Uso:
    python -m src.parte1.entity_resolution
"""
from pyspark.ml import Pipeline
from pyspark.ml.feature import HashingTF, MinHashLSH, NGram, RegexTokenizer
from pyspark.sql import DataFrame, Window, functions as F

from src.common.config import PROCESSED_DIR
from src.common.spark import get_spark

JACCARD_MAX = 0.1
MIN_LEN_RATIO = 0.85

ACCENTS_FROM = "ÁÉÍÓÚÜÑ"
ACCENTS_TO = "AEIOUUN"


def normalize_name(col):
    """Mayúsculas, sin tildes ni puntuación. Se conservan las formas
    societarias (SAC, SRL...) pero sin puntos, para que "S.A.C." == "SAC"
    y a la vez "GARRITA" (consorcio) != "GARRITA SAC" (empresa)."""
    c = F.translate(F.upper(F.trim(col)), ACCENTS_FROM, ACCENTS_TO)
    c = F.regexp_replace(c, r"[.,]", "")
    c = F.regexp_replace(c, r"[^A-Z0-9&]+", " ")
    return F.trim(F.regexp_replace(c, r"\s+", " "))


def supplier_type(raw_id, name):
    code = F.regexp_replace(raw_id, r"^PE-RUC-", "")
    return (
        F.when(code.rlike(r"^L"), "extranjero")
        .when(code.rlike(r"^20\d{9}$"), "persona_juridica")
        .when(code.rlike(r"^10\d{9}$"), "persona_natural")
        .when(code.rlike(r"^\d{11}$"), "otro_ruc")
        .when(code.rlike(r"^\d{4,7}$"), "consorcio")
        .when(name.contains("CONSORCIO"), "consorcio")
        .otherwise("otro")
    )


def load_suppliers(spark) -> DataFrame:
    """Universo de proveedores: adjudicados y postores."""
    items = spark.read.parquet(str(PROCESSED_DIR / "items")).select("supplier_id")
    tend = spark.read.parquet(str(PROCESSED_DIR / "tenderers")).select("supplier_id")
    parties = spark.read.parquet(str(PROCESSED_DIR / "parties")) \
        .select(F.col("party_id").alias("supplier_id"), "name")
    return (
        items.union(tend).distinct()
        .join(parties, "supplier_id", "left")
        .withColumn("name_norm", normalize_name(F.col("name")))
        .withColumn("supplier_type", supplier_type(F.col("supplier_id"), F.col("name_norm")))
        .withColumn("valid_ruc", F.col("supplier_type").isin(
            "persona_juridica", "persona_natural", "otro_ruc"))
    )


def exact_matches(sup: DataFrame) -> DataFrame:
    valid = sup.filter("valid_ruc").groupBy("name_norm") \
        .agg(F.collect_set("supplier_id").alias("rucs"))
    # Solo se acepta si el nombre corresponde a un único RUC válido
    valid = valid.filter(F.size("rucs") == 1) \
        .select("name_norm", F.col("rucs")[0].alias("canonical_id"))
    # Nombres de consorcio excluidos: "CONSORCIO SAN MARTIN" con RUC no es el
    # mismo que las decenas de códigos con ese nombre.
    return (
        sup.filter(~F.col("valid_ruc") & (F.col("supplier_type") != "extranjero")
                   & ~F.col("name_norm").contains("CONSORCIO"))
        .join(valid, "name_norm")
        .select("supplier_id", "canonical_id", F.lit("exacto").alias("match_rule"))
    )


def fuzzy_matches(sup: DataFrame, already: DataFrame) -> DataFrame:
    """MinHash/LSH sobre trigramas de caracteres del nombre normalizado."""
    pipeline = Pipeline(stages=[
        RegexTokenizer(inputCol="name_norm", outputCol="chars", pattern="", minTokenLength=1),
        NGram(n=3, inputCol="chars", outputCol="trigrams"),
        HashingTF(inputCol="trigrams", outputCol="tf", numFeatures=1 << 18, binary=True),
        MinHashLSH(inputCol="tf", outputCol="hashes", numHashTables=5, seed=42),
    ])
    # Los nombres de consorcio comparten el prefijo "CONSORCIO " y son
    # genéricos: saturan los buckets de LSH y su fusión difusa no es
    # confiable. Se excluyen de ambos lados.
    named = sup.filter((F.length("name_norm") >= 6) & ~F.col("name_norm").contains("CONSORCIO"))
    model = pipeline.fit(named)

    left = model.transform(
        named.filter(~F.col("valid_ruc") & (F.col("supplier_type") != "extranjero"))
        .join(already.select("supplier_id"), "supplier_id", "left_anti")
    )
    right = model.transform(named.filter("valid_ruc"))

    lsh = model.stages[-1]
    pairs = lsh.approxSimilarityJoin(left, right, JACCARD_MAX, distCol="dist").select(
        F.col("datasetA.supplier_id").alias("supplier_id"),
        F.col("datasetB.supplier_id").alias("canonical_id"),
        "dist",
        F.length("datasetA.name_norm").alias("len_a"),
        F.length("datasetB.name_norm").alias("len_b"),
    )
    # Los trigramas son un conjunto: "A Y B" puede quedar a distancia ~0 de
    # "A". Exigir longitudes parecidas evita fusionar asociaciones con uno
    # de sus miembros.
    pairs = pairs.filter(
        F.least("len_a", "len_b") / F.greatest("len_a", "len_b") >= MIN_LEN_RATIO
    )
    # Se acepta solo el mejor candidato y si no hay empate
    w = Window.partitionBy("supplier_id").orderBy("dist")
    return (
        pairs.withColumn("rk", F.rank().over(w))
        .filter("rk = 1")
        .withColumn("n_best", F.count("*").over(Window.partitionBy("supplier_id")))
        .filter("n_best = 1")
        .select("supplier_id", "canonical_id", F.lit("minhash").alias("match_rule"))
    )


def main() -> None:
    spark = get_spark("parte1-entity-resolution")
    sup = load_suppliers(spark).cache()

    exact = exact_matches(sup).cache()
    fuzzy = fuzzy_matches(sup, exact)
    matches = exact.unionByName(fuzzy)

    smap = (
        sup.join(matches, "supplier_id", "left")
        .withColumn("canonical_id", F.coalesce("canonical_id", "supplier_id"))
        .fillna({"match_rule": "propio"})
        .select("supplier_id", "canonical_id", "supplier_type", "name_norm", "match_rule")
    )
    smap.write.mode("overwrite").parquet(str(PROCESSED_DIR / "supplier_map"))

    smap = spark.read.parquet(str(PROCESSED_DIR / "supplier_map"))
    print("IDs de proveedor:", smap.count(),
          "| canónicos:", smap.select("canonical_id").distinct().count())
    smap.groupBy("supplier_type").count().orderBy(F.desc("count")).show()
    smap.groupBy("match_rule").count().show()
    smap.filter("match_rule = 'minhash'").join(
        smap.select(F.col("supplier_id").alias("canonical_id"),
                    F.col("name_norm").alias("canonical_name")), "canonical_id"
    ).select("name_norm", "canonical_name").show(10, truncate=45)
    spark.stop()


if __name__ == "__main__":
    main()
