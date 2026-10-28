"""Creación de la sesión de Spark en modo local."""
from pyspark.sql import SparkSession


def get_spark(app_name: str = "bd2-p2", driver_memory: str = "6g",
              shuffle_partitions: int = 32) -> SparkSession:
    # En local el valor por defecto de 200 particiones de shuffle genera
    # demasiadas tareas pequeñas; 32 se ajusta mejor a un portátil.
    return (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", driver_memory)
        .config("spark.sql.shuffle.partitions", shuffle_partitions)
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )
