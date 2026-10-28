"""Creación de la sesión de Spark en modo local."""
import os
from pathlib import Path

from pyspark.sql import SparkSession


def _ensure_hadoop_home() -> None:
    # En Windows Spark necesita winutils.exe y hadoop.dll para escribir a
    # disco. Si HADOOP_HOME no está definido se usa ~/hadoop (ver README).
    if os.name != "nt" or os.environ.get("HADOOP_HOME"):
        return
    home = Path.home() / "hadoop"
    if (home / "bin" / "winutils.exe").exists():
        os.environ["HADOOP_HOME"] = str(home)
        os.environ["PATH"] = str(home / "bin") + os.pathsep + os.environ["PATH"]


def get_spark(app_name: str = "bd2-p2", driver_memory: str = "6g",
              shuffle_partitions: int = 32) -> SparkSession:
    _ensure_hadoop_home()
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
