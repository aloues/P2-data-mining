# Proyecto Integrador 2 — Contrataciones Públicas del Perú

Grafos, clustering y aprendizaje de representación sobre los datos abiertos de
contrataciones públicas del Perú (estándar OCDS).

**Fuente de datos:** Registro OCDS – Perú (OECE/OSCE), publicado en
[data.open-contracting.org](https://data.open-contracting.org/es/publication/135).
Licencia CC BY 4.0.

## Preguntas de interés (borrador)

1. **Concentración de mercado:** ¿en qué categorías de bienes/servicios pocas
   empresas concentran la mayor parte del monto adjudicado, y varía por región?
2. **Segmentos de proveedores:** ¿qué tipologías de proveedores existen según su
   comportamiento (diversificación de entidades, tamaño de contratos, alcance
   regional) y cuáles se salen del patrón?
3. **Actores centrales y mercados:** ¿qué entidades y proveedores articulan la
   red de contrataciones y qué comunidades (mercados) emergen de ella?

## Estructura

```
src/
  common/        utilidades compartidas (sesión Spark, rutas)
  parte1/        Parte I  – aplanado OCDS, resolución de entidades, artefactos base (Spark)
  parte2/        Parte II – clustering y anomalías (local)
  parte3/        Parte III – sistemas de recomendación
  parte4/        Parte IV – PageRank y HITS
  parte5/        Parte V  – detección de comunidades
  parte6/        Parte VI – embeddings de nodos
notebooks/       exploración e interpretación
web/             reporte interactivo
artifacts/       salidas ligeras para la web (CSV/JSON)
data/            datos crudos y procesados (no versionado)
```

## Instalación

Requiere Python 3.10+ y Java 17 (para Spark).

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

**Windows:** Spark necesita `winutils.exe` y `hadoop.dll` (Hadoop 3.3) para
escribir Parquet. Colocarlos en `%USERPROFILE%\hadoop\bin`; `get_spark()` define
`HADOOP_HOME` automáticamente si encuentra esa carpeta.

## Ejecución

```bash
# 1. Descargar datos (por defecto 2024)
python -m src.parte1.download --years 2024

# 2. Aplanar OCDS al grano entidad–proveedor–ítem (Spark)
python -m src.parte1.flatten
```

Salidas en `data/processed/`: `items` (particionado por departamento de la
entidad), `tenderers` (postores por proceso, para el grafo de co-participación)
y `parties` (catálogo de actores).

```bash
# 3. Resolución de entidades de proveedores (reglas + MinHash/LSH en Spark)
python -m src.parte1.entity_resolution
```

Genera `data/processed/supplier_map` (`supplier_id → canonical_id`). Hallazgos
del diagnóstico: los consorcios usan códigos internos de 4–7 dígitos bajo el
esquema PE-RUC y sus nombres son genéricos ("CONSORCIO SANTA ROSA" aparece con
92 códigos distintos), por lo que nunca se fusionan por nombre. Solo se unen
IDs sin RUC válido a un RUC válido cuando el nombre coincide (63 casos en 2024).

```bash
# 4. Artefactos base: features, matrices de interacción y grafos
python -m src.parte1.build_artifacts
```

Salidas en `artifacts/parte1/` (Parquet, no versionado; `summary.json` sí):

| Artefacto | Filas (2024) | Uso |
|-----------|-------------:|-----|
| `supplier_features` | 49 569 | clustering de proveedores (Parte II) |
| `buyer_features` | 2 917 | clustering de entidades (Parte II) |
| `inter_buyer_supplier` | 73 778 | recomendación (Parte III) |
| `inter_buyer_family` | 30 218 | recomendación por contenido / SVD (Partes III y VI) |
| `edges_bipartite` | 73 778 | PageRank y HITS (Parte IV) |
| `edges_coparticipation` | 1 760 602 | comunidades y embeddings (Partes V y VI) |

Criterio de aristas de co-participación: dos proveedores se conectan si
postularon al mismo proceso; cada proceso con *n* postores aporta 1/(n−1) al
par y se exigen ≥ 2 procesos en común.

Datos 2024 (primera corrida): 98 292 ítems adjudicados, 2 917 entidades,
49 582 proveedores, ~S/ 73.8 mil millones; 85 % de los ítems tienen contrato
vinculado.

```bash
# 5. Diagnósticos y particionamiento (Spark): explain(), tiempos y export a la web
python -m src.parte1.diagnostics
```

Genera `artifacts/parte1/diagnostics.json` y `web/data/parte1.js`. Mide:

- **Compradores:** los 2 917 `buyer_id` son únicos; los 2 nombres repetidos son
  distritos homónimos de departamentos distintos, no duplicados.
- **Enlaces incompletos:** 15 % de los ítems no tiene contrato vinculado pero
  suman el 28 % del monto (29 % de las obras). La arista se toma de la
  adjudicación y se conserva `has_contract`.
- **Particionamiento:** el `.gz` se lee en 1 partición; `repartition(32)` baja
  el aplanado de 6.2 s a 4.1 s. `partitionBy(buyer_department)` convierte el
  filtro en `PartitionFilters` (1 de 25 archivos, ~3.5× más rápido que sin
  particionar). Sin `repartition` previo se generaban 550 archivos pequeños.
  En el self-join de co-participación, 32 particiones de shuffle tardan 3.8 s
  frente a 6.0 s con las 200 por defecto.

### Parte II — Clustering y anomalías (local)

```bash
python -m src.parte2.clustering
```

Corre en local (scikit-learn/SciPy): los vectores agregados caben en memoria y
DBSCAN/HDBSCAN/jerárquico no existen en Spark MLlib. Para proveedores (k = 6) y
entidades (k = 5): log1p + estandarización, PCA al 90 % de varianza, KMeans++
(codo, silueta, Davies-Bouldin), HDBSCAN, DBSCAN (eps por codo de
k-distancias) y Ward sobre muestra (dendrograma, ARI frente a KMeans). Exporta
`artifacts/parte2/clustering.json` y `web/data/parte2.js`.

## Reporte web

`web/` es una página estática (HTML + JS + Plotly) que lee los `.js` de
`web/data/`. Para verla en local basta con abrir `web/index.html`. Se publica en
GitHub Pages con `.github/workflows/pages.yml` (Settings → Pages → Source =
GitHub Actions). KMeans++, DBSCAN y el corte del dendrograma se recalculan en
vivo en el navegador.

## Avance

| Parte | Estado |
|-------|--------|
| I. Transformación y base relacional (Spark) | listo (2024) |
| II. Clustering y anomalías | listo |
| III. Recomendación | pendiente |
| IV. PageRank / HITS | pendiente |
| V. Comunidades | pendiente |
| VI. Embeddings | pendiente |
| VII. Discusión y reporte web | reporte web con Partes I–II |
