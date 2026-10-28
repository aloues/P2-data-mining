"""Parte II — Clustering y detección de anomalías.

Ejecución: local (scikit-learn / SciPy). Los vectores de la Parte I ya están
agregados por actor: 49 569 proveedores × 12 variables y 2 917 entidades × 9
caben de sobra en memoria, y DBSCAN/HDBSCAN y el jerárquico no tienen versión
en Spark MLlib. Spark solo aportaría coste de arranque y serialización.

Para cada tipo de actor (proveedores y entidades):
  1. Selección de variables y transformación log1p de las de cola pesada
     (montos, conteos), luego StandardScaler.
  2. PCA reteniendo VAR_TARGET de la varianza: decorrelaciona (monto total y
     n.º de procesos van juntos) y reduce el ruido para los métodos de densidad.
  3. KMeans++ para k = 2..K_MAX con inercia (codo), silueta y Davies-Bouldin.
  4. HDBSCAN sobre todo el conjunto: clústeres densos + ruido (outliers).
  5. DBSCAN con eps elegido por el codo de la curva de k-distancias.
  6. Jerárquico Ward sobre una muestra -> dendrograma y ARI frente a KMeans.

Exporta artifacts/parte2/clustering.json (resumen) y web/data/parte2.js
(muestra de puntos en el espacio PCA para recomputar KMeans y DBSCAN en vivo).

Uso:
    python -m src.parte2.clustering
"""
import json

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from sklearn.cluster import DBSCAN, HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from src.common.config import ARTIFACTS_DIR, PROCESSED_DIR, ROOT

SEED = 42
K_MAX = 12
VAR_TARGET = 0.90
SIL_SAMPLE = 10_000     # silueta es O(n²): se estima sobre una muestra
WARD_SAMPLE = 2_000
WEB_SAMPLE = 2_500      # puntos que la web recalcula en vivo
OUT = ARTIFACTS_DIR / "parte2"

# k elegido con silueta + interpretabilidad (ver web, módulo "Elección de k"):
# la silueta máxima siempre es k=2 (un proceso vs. varios), que no separa
# tipologías. Proveedores: k=6 (silueta 0.30 vs 0.33 en k=4) separa los
# consorcios de obra y los proveedores multicliente. Entidades: k=5 aísla un
# grupo de alta contratación directa y postor único.
# HDBSCAN en proveedores: con min_cluster_size pequeño las variables casi
# discretas (% bienes ∈ {0, 1}) generan decenas de micro-clústeres; se exige
# ~2% del total para obtener tipologías densas.
CONFIG = {
    "proveedores": {"k": 6, "hdb_min_cluster": 1000, "hdb_min_samples": 25},
    "entidades": {"k": 5, "hdb_min_cluster": 15, "hdb_min_samples": 10},
}
WEB_DATA = ROOT / "web" / "data"

# (columna, transformación, etiqueta para la web)
SUPPLIER_VARS = [
    ("total_amount", "log", "Monto total adjudicado (log)"),
    ("median_item_amount", "log", "Monto mediano por ítem (log)"),
    ("n_processes_won", "log", "Procesos ganados (log)"),
    ("n_buyers", "log", "Entidades clientes (log)"),
    ("n_departments", "log", "Departamentos atendidos (log)"),
    ("n_families", "log", "Familias UNSPSC (log)"),
    ("pct_direct", None, "% contratación directa"),
    ("pct_goods", None, "% bienes"),
    ("pct_works", None, "% obras"),
    ("avg_competitors", "log", "Postores promedio (log)"),
    ("top_buyer_share", None, "Dependencia del principal cliente"),
    ("win_rate", None, "Tasa de éxito (ganados/postulados)"),
]
BUYER_VARS = [
    ("total_amount", "log", "Monto total contratado (log)"),
    ("n_processes", "log", "Procesos (log)"),
    ("n_suppliers", "log", "Proveedores distintos (log)"),
    ("n_families", "log", "Familias UNSPSC (log)"),
    ("pct_direct", None, "% contratación directa"),
    ("avg_competitors", "log", "Postores promedio (log)"),
    ("pct_single_bidder", None, "% ítems con un solo postor"),
    ("top_supplier_share", None, "Concentración en el principal proveedor"),
    ("suppliers_per_process", "log", "Proveedores por proceso (log)"),
]


def load_suppliers() -> pd.DataFrame:
    df = pd.read_parquet(ARTIFACTS_DIR / "parte1" / "supplier_features")
    names = pd.read_parquet(PROCESSED_DIR / "parties", columns=["party_id", "name"]) \
        .rename(columns={"party_id": "supplier_id"})
    df = df.merge(names, on="supplier_id", how="left")
    # Personas naturales: se enmascara el nombre (encuadre ético, ver web)
    natural = df["supplier_type"] == "persona_natural"
    df.loc[natural, "name"] = "PERSONA NATURAL ···" + df.loc[natural, "supplier_id"].str[-4:]
    df["label"] = df["name"].fillna(df["supplier_id"])
    df["group"] = df["supplier_type"]
    return df


def load_buyers() -> pd.DataFrame:
    df = pd.read_parquet(ARTIFACTS_DIR / "parte1" / "buyer_features")
    df["suppliers_per_process"] = df["n_suppliers"] / df["n_processes"]
    df["label"] = df["buyer_name"]
    df["group"] = df["department"]
    return df


def design_matrix(df: pd.DataFrame, spec) -> np.ndarray:
    cols = []
    for col, tr, _ in spec:
        x = df[col].astype(float)
        x = x.fillna(x.median())
        cols.append(np.log1p(x) if tr == "log" else x)
    return np.column_stack(cols)


def k_distance_eps(Z: np.ndarray, min_samples: int, rng) -> tuple[float, list]:
    """Curva de k-distancias ordenada; eps = punto de máxima curvatura
    (distancia máxima a la recta entre extremos)."""
    idx = rng.choice(len(Z), min(len(Z), 20_000), replace=False)
    d, _ = NearestNeighbors(n_neighbors=min_samples).fit(Z).kneighbors(Z[idx])
    curve = np.sort(d[:, -1])
    x = np.linspace(0, 1, len(curve))
    y = (curve - curve[0]) / (curve[-1] - curve[0])
    knee = int(np.argmax(x - y))
    step = max(1, len(curve) // 400)
    return float(curve[knee]), curve[::step].round(4).tolist()


def profiles(df, labels, spec, X_raw) -> list:
    """Media de cada variable original (sin log) por clúster, más su z-score
    respecto de la población, para interpretar qué distingue a cada grupo."""
    raw = pd.DataFrame({c: df[c].astype(float) for c, _, _ in spec})
    z = (X_raw - X_raw.mean(0)) / X_raw.std(0)
    out = []
    for lab in sorted(set(labels)):
        m = labels == lab
        top_groups = df.loc[m, "group"].value_counts(normalize=True).head(4)
        out.append({
            "cluster": int(lab),
            "size": int(m.sum()),
            "share": round(float(m.mean()), 4),
            "amount_share": round(float(df.loc[m, "total_amount"].sum() / df["total_amount"].sum()), 4),
            "mean": {c: round(float(raw.loc[m, c].mean()), 4) for c, _, _ in spec},
            "median": {c: round(float(raw.loc[m, c].median()), 4) for c, _, _ in spec},
            "z": {c: round(float(z[m, i].mean()), 3) for i, (c, _, _) in enumerate(spec)},
            "groups": {k: round(float(v), 3) for k, v in top_groups.items()},
            "examples": df.loc[m].nlargest(5, "total_amount")["label"].tolist(),
        })
    return out


def outliers(df, Zs, km, hdb_labels, spec, X_raw, n=25) -> list:
    """Ruido de HDBSCAN ordenado por distancia al centroide KMeans más
    cercano; se reportan las 3 variables con mayor |z| como explicación."""
    dist = km.transform(Zs).min(1)
    z = (X_raw - X_raw.mean(0)) / X_raw.std(0)
    idx = np.where(hdb_labels == -1)[0]
    idx = idx[np.argsort(-dist[idx])][:n]
    rows = []
    for i in idx:
        top = np.argsort(-np.abs(z[i]))[:3]
        rows.append({
            "label": df["label"].iloc[i],
            "group": df["group"].iloc[i],
            "total_amount": round(float(df["total_amount"].iloc[i]), 2),
            "kmeans_cluster": int(km.labels_[i]),
            "distance": round(float(dist[i]), 3),
            "drivers": [{"var": spec[j][2], "z": round(float(z[i, j]), 2)} for j in top],
        })
    return rows


def analyze(name: str, df: pd.DataFrame, spec, k: int, hdb_min_cluster: int,
            hdb_min_samples: int) -> tuple[dict, dict]:
    rng = np.random.default_rng(SEED)
    X_raw = design_matrix(df, spec)
    X = StandardScaler().fit_transform(X_raw)

    pca = PCA(random_state=SEED).fit(X)
    n_comp = int(np.searchsorted(np.cumsum(pca.explained_variance_ratio_), VAR_TARGET) + 1)
    Z = PCA(n_components=n_comp, random_state=SEED).fit_transform(X)

    sil_idx = rng.choice(len(Z), min(len(Z), SIL_SAMPLE), replace=False)
    ksel, models = [], {}
    for kk in range(2, K_MAX + 1):
        km = KMeans(n_clusters=kk, init="k-means++", n_init=10, random_state=SEED).fit(Z)
        models[kk] = km
        ksel.append({
            "k": kk,
            "inertia": round(float(km.inertia_), 2),
            "silhouette": round(float(silhouette_score(Z[sil_idx], km.labels_[sil_idx])), 4),
            "davies_bouldin": round(float(davies_bouldin_score(Z, km.labels_)), 4),
        })
    k_best = k
    km = models[k_best]

    hdb = HDBSCAN(min_cluster_size=hdb_min_cluster, min_samples=hdb_min_samples, copy=True).fit(Z)
    min_samples = 2 * n_comp
    eps, kdist = k_distance_eps(Z, min_samples, rng)
    db = DBSCAN(eps=eps, min_samples=min_samples).fit(Z)

    w_idx = rng.choice(len(Z), min(len(Z), WARD_SAMPLE), replace=False)
    L = linkage(Z[w_idx], method="ward")
    ward_labels = fcluster(L, k_best, criterion="maxclust") - 1
    dn = dendrogram(L, truncate_mode="lastp", p=40, no_plot=True)

    loadings = PCA(n_components=2, random_state=SEED).fit(X).components_
    summary = {
        "entity": name,
        "n": len(df),
        "variables": [{"col": c, "transform": t or "ninguna", "label": l} for c, t, l in spec],
        "pca": {
            "explained": pca.explained_variance_ratio_.round(4).tolist(),
            "n_components": n_comp,
            "loadings_pc1": dict(zip([l for _, _, l in spec], loadings[0].round(3).tolist())),
            "loadings_pc2": dict(zip([l for _, _, l in spec], loadings[1].round(3).tolist())),
        },
        "k_selection": ksel,
        "k_best": k_best,
        "k_silhouette_max": max(ksel, key=lambda r: r["silhouette"])["k"],
        "kmeans_profiles": profiles(df, km.labels_, spec, X_raw),
        "hdbscan": {
            "min_cluster_size": hdb_min_cluster,
            "min_samples": hdb_min_samples,
            "n_clusters": int(hdb.labels_.max() + 1),
            "noise_share": round(float((hdb.labels_ == -1).mean()), 4),
            "noise_amount_share": round(float(
                df.loc[hdb.labels_ == -1, "total_amount"].sum() / df["total_amount"].sum()), 4),
            "profiles": profiles(df, hdb.labels_, spec, X_raw),
            "ari_vs_kmeans": round(float(adjusted_rand_score(km.labels_, hdb.labels_)), 4),
        },
        "dbscan": {
            "eps": round(eps, 4), "min_samples": min_samples,
            "n_clusters": int(db.labels_.max() + 1),
            "noise_share": round(float((db.labels_ == -1).mean()), 4),
            "k_distance": kdist,
        },
        "ward": {
            "sample": len(w_idx),
            "ari_vs_kmeans": round(float(adjusted_rand_score(km.labels_[w_idx], ward_labels)), 4),
            "dendrogram": {"icoord": dn["icoord"], "dcoord": dn["dcoord"], "ivl": dn["ivl"]},
        },
        "outliers": outliers(df, Z, km, hdb.labels_, spec, X_raw),
    }

    # Muestra para la web: estratificada para que los outliers aparezcan
    noise = np.where(hdb.labels_ == -1)[0]
    keep = np.concatenate([
        rng.choice(noise, min(len(noise), WEB_SAMPLE // 5), replace=False),
        rng.choice(np.setdiff1d(np.arange(len(Z)), noise),
                   min(len(Z) - len(noise), WEB_SAMPLE - min(len(noise), WEB_SAMPLE // 5)),
                   replace=False),
    ])
    web = {
        "entity": name,
        "n_components": n_comp,
        "z": Z[keep].round(3).tolist(),
        "label": df["label"].iloc[keep].tolist(),
        "group": df["group"].iloc[keep].fillna("—").tolist(),
        "amount": df["total_amount"].iloc[keep].round(0).tolist(),
        "kmeans": km.labels_[keep].tolist(),
        "hdbscan": hdb.labels_[keep].tolist(),
        "eps_default": round(eps, 3),
        "min_samples_default": min_samples,
        "k_best": k_best,
    }
    print(f"[{name}] n={len(df)} PCs={n_comp} k={k_best} "
          f"sil={next(r['silhouette'] for r in ksel if r['k'] == k_best)} | "
          f"HDBSCAN {summary['hdbscan']['n_clusters']} cl, ruido {summary['hdbscan']['noise_share']:.1%} | "
          f"DBSCAN eps={eps:.2f} {summary['dbscan']['n_clusters']} cl, ruido {summary['dbscan']['noise_share']:.1%} | "
          f"ARI ward={summary['ward']['ari_vs_kmeans']}")
    return summary, web


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    results, web = {}, {}
    for name, loader, spec in (("proveedores", load_suppliers, SUPPLIER_VARS),
                               ("entidades", load_buyers, BUYER_VARS)):
        results[name], web[name] = analyze(name, loader(), spec, **CONFIG[name])

    (OUT / "clustering.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    payload = {"summary": results, "points": web}
    (WEB_DATA / "parte2.js").write_text(
        "window.P2 = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";",
        encoding="utf-8")


if __name__ == "__main__":
    main()
