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
  parte2/        Parte II – clustering y anomalías
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

## Ejecución

```bash
# 1. Descargar datos (por defecto 2024)
python -m src.parte1.download --years 2024

# 2. Aplanar OCDS al grano entidad–proveedor–ítem (Spark)
python -m src.parte1.flatten
```

## Avance

| Parte | Estado |
|-------|--------|
| I. Transformación y base relacional (Spark) | en progreso |
| II. Clustering y anomalías | pendiente |
| III. Recomendación | pendiente |
| IV. PageRank / HITS | pendiente |
| V. Comunidades | pendiente |
| VI. Embeddings | pendiente |
| VII. Discusión y reporte web | pendiente |
