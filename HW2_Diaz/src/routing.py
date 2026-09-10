"""
Fase 2 — Motor de ruteo, snapping, cache y matriz origen x establecimiento.

Cliente de **OSRM** (Open Source Routing Machine) corriendo en local sobre el extracto
OpenStreetMap del Peru. El enunciado exige una red vial real: la distancia en linea recta no
es un proxy valido de tiempo de viaje, y en los Andes y la Amazonia la diferencia no es un
detalle sino el hallazgo.

Por que OSRM y no las alternativas (esto va al video):

* **OSMnx + NetworkX** construye el grafo en Python. Va bien en areas urbanas, pero Loreto
  tiene 368 000 km2: el grafo es enorme, lento de construir y pesado en memoria. El propio
  enunciado lo describe como "pesado y lento a escala departamental".
* **OpenRouteService** es una API remota con cuota. Obliga a throttlear, y sobre todo
  **no funciona sin internet**, asi que la demostracion en vivo dependeria de la conexion.
* **OSRM en local** no tiene limite de consultas, responde matrices completas en
  milisegundos y funciona offline. Es la opcion que el enunciado marca como recomendada.

Este modulo es importable y ejecutable de forma independiente del pipeline, como pide el
enunciado:

    python -m src.routing --check          # verifica que OSRM responde
    python -m src.routing --demo           # ruta de prueba entre dos puntos conocidos
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .config import Config

log = logging.getLogger(__name__)

# OSRM devuelve null cuando un par es inalcanzable (isla, componente desconectado).
INALCANZABLE = np.nan


class OSRMNoDisponible(RuntimeError):
    """OSRM no responde en la URL configurada."""


# ============================================================================== cliente
@dataclass
class OSRMClient:
    """
    Cliente minimo de la API HTTP de OSRM v5.

    Solo se usan tres servicios:
      /nearest  diagnostico de snapping (a que distancia de la red cae cada punto)
      /table    matrices de duracion y distancia (el caballo de batalla)
      /route    una ruta concreta, para inspeccion y para el video

    Nota sobre el `perfil` en la URL: `osrm-routed` sirve el perfil con el que fue
    construido el grafo, e ignora el que va en la ruta. Se mantiene por correccion
    sintactica, pero para cambiar de perfil hay que levantar OTRO servidor con otro grafo:
    de ahi que cada perfil tenga su propio puerto en config.md.
    """

    base_url: str
    perfil: str = "driving"
    timeout: int = 120
    # Tope de coordenadas por peticion /table. osrm-routed arranca con --max-table-size;
    # la suma (chunk_origenes + chunk_destinos) debe quedar holgadamente por debajo, y ademas
    # mantener la URL corta: la API de OSRM es solo GET, cada coordenada ocupa ~22 caracteres,
    # y una URL gigante falla antes de llegar al servidor.
    chunk_origenes: int = 200
    chunk_destinos: int = 300
    reintentos: int = 3
    espera_reintento: float = 2.0

    n_peticiones: int = field(default=0, init=False)
    segundos_red: float = field(default=0.0, init=False)

    # ------------------------------------------------------------------ infraestructura
    def _get(self, ruta: str, params: dict | None = None) -> dict:
        url = f"{self.base_url.rstrip('/')}/{ruta}"
        ultimo: Exception | None = None
        for intento in range(1, self.reintentos + 1):
            try:
                t0 = time.perf_counter()
                r = requests.get(url, params=params, timeout=self.timeout)
                self.segundos_red += time.perf_counter() - t0
                self.n_peticiones += 1
                r.raise_for_status()
                datos = r.json()
                if datos.get("code") != "Ok":
                    raise RuntimeError(f"OSRM respondio code={datos.get('code')}: "
                                       f"{datos.get('message', '')}")
                return datos
            except requests.RequestException as e:
                ultimo = e
                if intento < self.reintentos:
                    log.warning("    OSRM fallo (intento %d/%d): %s; reintento en %.0fs",
                                intento, self.reintentos, e, self.espera_reintento)
                    time.sleep(self.espera_reintento)
        raise OSRMNoDisponible(
            f"OSRM no respondio en {url} tras {self.reintentos} intentos. "
            f"Ultimo error: {ultimo}. Verifica que el contenedor este levantado "
            f"(docker ps) y escuchando en {self.base_url}."
        ) from ultimo

    @staticmethod
    def _coords(lon: np.ndarray, lat: np.ndarray) -> str:
        return ";".join(f"{x:.6f},{y:.6f}" for x, y in zip(lon, lat))

    # -------------------------------------------------------------------------- salud
    def disponible(self) -> bool:
        """True si OSRM responde. No lanza: sirve para decidir si seguir o abortar limpio."""
        try:
            # Punto arbitrario dentro del Peru (plaza de armas de Lima).
            self._get(f"nearest/v1/{self.perfil}/-77.0300,-12.0464", {"number": 1})
            return True
        except Exception as e:  # noqa: BLE001
            log.error("OSRM no disponible en %s: %s", self.base_url, e)
            return False

    # ------------------------------------------------------------------------ nearest
    def nearest(self, lon: np.ndarray, lat: np.ndarray) -> pd.DataFrame:
        """
        Distancia de cada punto al nodo mas cercano de la red vial (snapping).

        El enunciado exige reportar cuantos puntos no lograron engancharse y la distancia
        media de enganche. Un punto que engancha a 8 km de la red no esta "en la red": su
        tiempo de viaje calculado ignora esos 8 km, y eso hay que declararlo.
        """
        filas = []
        for i, (x, y) in enumerate(zip(lon, lat)):
            try:
                d = self._get(f"nearest/v1/{self.perfil}/{x:.6f},{y:.6f}", {"number": 1})
                w = d["waypoints"][0]
                filas.append({"idx": i, "snap_m": float(w["distance"]),
                              "snap_lon": w["location"][0], "snap_lat": w["location"][1],
                              "snap_ok": True, "via": w.get("name", "")})
            except Exception:  # noqa: BLE001 — un punto sin enganche no debe abortar el lote
                filas.append({"idx": i, "snap_m": np.nan, "snap_lon": np.nan,
                              "snap_lat": np.nan, "snap_ok": False, "via": ""})
            if (i + 1) % 500 == 0:
                log.info("    snapping %d/%d", i + 1, len(lon))
        return pd.DataFrame(filas)

    # -------------------------------------------------------------------------- table
    def table(
        self,
        origenes: pd.DataFrame,
        destinos: pd.DataFrame,
        col_lon: str = "lon",
        col_lat: str = "lat",
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Matriz completa origen x destino de duracion (seg) y distancia (m).

        Se trocea por bloques de origenes porque OSRM limita el numero de coordenadas por
        peticion (`--max-table-size`) y porque su API es solo GET: una URL con miles de
        coordenadas falla por longitud antes de llegar al servidor.

        Devuelve dos matrices (n_origenes x n_destinos). Los pares inalcanzables vienen
        como NaN, no como cero: un cero silencioso se leeria como "esta al lado".
        """
        n_o, n_d = len(origenes), len(destinos)
        dur = np.full((n_o, n_d), np.nan)
        dist = np.full((n_o, n_d), np.nan)

        # Se trocean AMBAS dimensiones. Trocear solo los origenes basta mientras los destinos
        # sean pocos (44 resolutivas), pero el analisis a pie compara contra las ~2 100 IPRESS
        # de cualquier categoria, y entonces los destinos por si solos ya superarian el
        # --max-table-size del servidor y la longitud maxima de URL.
        n_bo = int(np.ceil(n_o / self.chunk_origenes))
        n_bd = int(np.ceil(n_d / self.chunk_destinos))
        total_bloques = n_bo * n_bd
        t0 = time.perf_counter()
        hecho = 0

        for bd in range(n_bd):
            d_ini = bd * self.chunk_destinos
            d_fin = min(d_ini + self.chunk_destinos, n_d)
            sub_d = destinos.iloc[d_ini:d_fin]
            coords_dest = self._coords(sub_d[col_lon].to_numpy(dtype=float),
                                       sub_d[col_lat].to_numpy(dtype=float))
            n_dd = d_fin - d_ini

            for bo in range(n_bo):
                o_ini = bo * self.chunk_origenes
                o_fin = min(o_ini + self.chunk_origenes, n_o)
                sub_o = origenes.iloc[o_ini:o_fin]
                n_oo = o_fin - o_ini

                coords = (self._coords(sub_o[col_lon].to_numpy(dtype=float),
                                       sub_o[col_lat].to_numpy(dtype=float))
                          + ";" + coords_dest)
                datos = self._get(
                    f"table/v1/{self.perfil}/{coords}",
                    {"sources": ";".join(str(i) for i in range(n_oo)),
                     "destinations": ";".join(str(i + n_oo) for i in range(n_dd)),
                     "annotations": "duration,distance"},
                )
                dur[o_ini:o_fin, d_ini:d_fin] = np.array(
                    [[np.nan if v is None else v for v in fila] for fila in datos["durations"]])
                if "distances" in datos:
                    dist[o_ini:o_fin, d_ini:d_fin] = np.array(
                        [[np.nan if v is None else v for v in fila]
                         for fila in datos["distances"]])

                hecho += 1
                if hecho % 10 == 0 or hecho == total_bloques:
                    log.info("    matriz bloque %d/%d · %.1fs · %d peticiones",
                             hecho, total_bloques, time.perf_counter() - t0, self.n_peticiones)
        return dur, dist

    # -------------------------------------------------------------------------- route
    def route(self, o_lon: float, o_lat: float, d_lon: float, d_lat: float) -> dict:
        """Una ruta concreta, con geometria. Util para el video y para inspeccionar casos."""
        d = self._get(
            f"route/v1/{self.perfil}/{o_lon:.6f},{o_lat:.6f};{d_lon:.6f},{d_lat:.6f}",
            {"overview": "simplified", "geometries": "geojson"},
        )
        r = d["routes"][0]
        return {"duracion_seg": r["duration"], "distancia_m": r["distance"],
                "geometry": r.get("geometry")}


# ============================================================================= muestreo
def muestrear_demanda(demanda: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    Reduce la demanda al tope de puntos que fija el enunciado (5 000), con muestreo
    **estratificado por distrito y ponderado por poblacion**.

    Por que asi y no una muestra aleatoria simple: una aleatoria simple sobre 15 418 puntos
    dejaria distritos enteros sin representar, y como las metricas se agregan a nivel
    distrital, esos distritos quedarian sin valor. Estratificando por distrito se garantiza
    que **todos** aparezcan.

    Cada punto seleccionado carga un `peso_muestral` que expande la poblacion del estrato:
    dentro de cada distrito, los pesos de los puntos muestreados suman la poblacion total del
    distrito. Asi las metricas ponderadas por poblacion siguen siendo insesgadas respecto del
    universo completo, aunque se calculen sobre una muestra.

    Implicacion de error muestral que el informe debe declarar: la varianza dentro del
    distrito no se captura. Si en un distrito hay dos centros poblados con accesos muy
    distintos y solo se muestrea uno, el promedio distrital hereda su valor.
    """
    tope = int(cfg.ruteo.get("max_puntos_demanda", 5000))
    semilla = int(cfg.ruteo.get("semilla", 42))

    d = demanda.copy()
    d["peso_muestral"] = d["poblacion"].astype(float)

    if len(d) <= tope:
        d["en_muestra"] = True
        log.info("  muestreo innecesario: %d puntos <= tope de %d", len(d), tope)
        return d

    rng = np.random.default_rng(semilla)
    pob_distrito = d.groupby("ubigeo")["poblacion"].sum()
    pob_total = float(pob_distrito.sum())
    distritos = list(pob_distrito.index)
    disponibles = d.groupby("ubigeo").size()

    # ---- reparto de la cuota por distrito, en tres pasos ----
    # 1) Un punto garantizado por distrito, para que ninguno quede sin representar: las
    #    metricas se agregan a nivel distrital y un distrito sin muestra no tendria valor.
    base = {u: min(1, int(disponibles[u])) for u in distritos}
    presupuesto = tope - sum(base.values())
    if presupuesto < 0:
        raise ValueError(
            f"El tope de {tope} puntos no alcanza para dar al menos uno a cada uno de los "
            f"{len(distritos)} distritos. Sube [ruteo].max_puntos_demanda en config.md.")

    # 2) El resto se reparte proporcional a poblacion por el metodo de **restos mayores**
    #    (Hamilton). Truncar sin mas desperdiciaba ~1 700 puntos del presupuesto, y con OSRM
    #    local rutear mas origenes no cuesta nada: mas puntos = mas resolucion espacial gratis.
    cupo = {u: int(disponibles[u]) - base[u] for u in distritos}   # cuantos mas caben
    exacto = ({u: presupuesto * (pob_distrito[u] / pob_total) for u in distritos}
              if pob_total > 0 else {u: 0.0 for u in distritos})
    extra = {u: min(int(np.floor(exacto[u])), cupo[u]) for u in distritos}

    # 3) Los puntos que sobran —por el truncamiento y por los distritos con menos puntos que
    #    su cuota— se reasignan por resto decreciente entre los que todavia tienen cupo.
    sobrante = presupuesto - sum(extra.values())
    orden_resto = sorted(distritos, key=lambda u: exacto[u] - np.floor(exacto[u]), reverse=True)
    while sobrante > 0:
        repartido = 0
        for u in orden_resto:
            if sobrante == 0:
                break
            if extra[u] < cupo[u]:
                extra[u] += 1
                sobrante -= 1
                repartido += 1
        if repartido == 0:
            break  # ya no queda cupo en ningun distrito

    cuota = {u: base[u] + extra[u] for u in distritos}

    elegidos: list = []
    for u in distritos:
        sub = d[d["ubigeo"] == u]
        k = min(cuota[u], len(sub))
        if k <= 0:
            continue
        # Se muestrea con probabilidad proporcional a la poblacion, pero se garantiza que
        # el punto mas poblado del distrito siempre entre: es el que mas pesa en la metrica.
        orden = sub.sort_values("poblacion", ascending=False)
        forzados = orden.index[:1].tolist()
        resto = orden.index[1:]
        faltan = k - len(forzados)
        if faltan > 0 and len(resto) > 0:
            w = d.loc[resto, "poblacion"].to_numpy(dtype=float)
            w = np.where(w > 0, w, 1e-9)  # los de peso 0 pueden salir, pero casi nunca
            p = w / w.sum()
            extra = rng.choice(resto, size=min(faltan, len(resto)), replace=False, p=p)
            elegidos.extend(list(extra))
        elegidos.extend(forzados)

    d["en_muestra"] = d.index.isin(elegidos)
    muestra = d[d["en_muestra"]].copy()

    # Expansion: dentro de cada distrito los pesos suman la poblacion total del distrito.
    suma_muestra = muestra.groupby("ubigeo")["poblacion"].transform("sum")
    factor = muestra["ubigeo"].map(pob_distrito) / suma_muestra.replace(0, np.nan)
    muestra["peso_muestral"] = (muestra["poblacion"] * factor).fillna(0.0)
    # Distritos donde toda la muestra tiene poblacion 0: se reparte en partes iguales.
    sin_peso = muestra.groupby("ubigeo")["peso_muestral"].transform("sum").eq(0)
    if sin_peso.any():
        n_por_dist = muestra.groupby("ubigeo")["ccpp_id"].transform("size")
        muestra.loc[sin_peso, "peso_muestral"] = (
            muestra.loc[sin_peso, "ubigeo"].map(pob_distrito) / n_por_dist[sin_peso])

    log.info("  muestreo estratificado: %d -> %d puntos en %d distritos (semilla=%d)",
             len(d), len(muestra), muestra["ubigeo"].nunique(), semilla)
    log.info("  poblacion representada: %.0f de %.0f (%.4f%%)",
             muestra["peso_muestral"].sum(), pob_total,
             100 * muestra["peso_muestral"].sum() / pob_total if pob_total else 0)
    return muestra


# =============================================================================== cache
def _clave_cache(perfil: str, origenes: pd.Series, destinos: pd.Series) -> str:
    """Huella estable del par (conjunto de origenes, conjunto de destinos, perfil)."""
    h = hashlib.sha256()
    h.update(perfil.encode())
    h.update("|".join(map(str, origenes)).encode())
    h.update("#".encode())
    h.update("|".join(map(str, destinos)).encode())
    return h.hexdigest()[:16]


def matriz_con_cache(
    client: OSRMClient,
    origenes: pd.DataFrame,
    destinos: pd.DataFrame,
    perfil: str,
    cache_dir: Path,
    col_id_origen: str = "ccpp_id",
    col_id_destino: str = "cod_ipress",
    forzar: bool = False,
) -> pd.DataFrame:
    """
    Matriz completa origen x destino, cacheada en Parquet.

    El enunciado es explicito: "todo resultado de ruteo se escribe a disco; una segunda
    corrida no debe recalcular lo cacheado". La clave del cache incluye el perfil y las
    listas de identificadores, de modo que cambiar el ambito o la muestra invalida el cache
    automaticamente en vez de devolver resultados de otro conjunto.

    Devuelve formato largo: una fila por par, con `duracion_seg` y `distancia_m`.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    clave = _clave_cache(perfil, origenes[col_id_origen], destinos[col_id_destino])
    destino_pq = cache_dir / f"matriz_{perfil}_{clave}.parquet"
    meta = cache_dir / f"matriz_{perfil}_{clave}.json"

    if destino_pq.exists() and not forzar:
        df = pd.read_parquet(destino_pq)
        log.info("  [cache] matriz %-5s %d pares reutilizados de %s",
                 perfil, len(df), destino_pq.name)
        return df

    log.info("  calculando matriz %s: %d origenes x %d destinos = %d pares",
             perfil, len(origenes), len(destinos), len(origenes) * len(destinos))
    t0 = time.perf_counter()
    dur, dist = client.table(origenes, destinos)
    transcurrido = time.perf_counter() - t0

    df = pd.DataFrame({
        col_id_origen: np.repeat(origenes[col_id_origen].to_numpy(), len(destinos)),
        col_id_destino: np.tile(destinos[col_id_destino].to_numpy(), len(origenes)),
        "duracion_seg": dur.ravel(),
        "distancia_m": dist.ravel(),
    })
    df["perfil"] = perfil
    df.to_parquet(destino_pq, index=False)

    n_nan = int(df["duracion_seg"].isna().sum())
    meta.write_text(json.dumps({
        "perfil": perfil,
        "n_origenes": len(origenes),
        "n_destinos": len(destinos),
        "n_pares": len(df),
        "pares_inalcanzables": n_nan,
        "pct_inalcanzables": round(100 * n_nan / len(df), 3) if len(df) else 0,
        "segundos_calculo": round(transcurrido, 1),
        "peticiones_osrm": client.n_peticiones,
    }, indent=2), encoding="utf-8")

    log.info("  matriz %s lista en %.1fs · %d pares · %d inalcanzables (%.2f%%)",
             perfil, transcurrido, len(df), n_nan, 100 * n_nan / len(df) if len(df) else 0)
    return df


# ====================================================================== mas cercano
def mas_cercano(
    matriz: pd.DataFrame,
    col_id_origen: str = "ccpp_id",
    col_id_destino: str = "cod_ipress",
) -> pd.DataFrame:
    """
    Para cada origen, el destino de menor tiempo de viaje.

    Los origenes cuyos pares son todos NaN quedan con `alcanzable=False`. **No se les
    imputa una distancia en linea recta**: el enunciado prohibe expresamente rellenar en
    silencio con euclidiana y un factor de rodeo sin justificarlo empiricamente. Un punto
    inalcanzable por carretera es un resultado, y en Loreto es *el* resultado.
    """
    m = matriz.dropna(subset=["duracion_seg"])
    if m.empty:
        out = matriz[[col_id_origen]].drop_duplicates().copy()
        out["alcanzable"] = False
        return out

    idx = m.groupby(col_id_origen)["duracion_seg"].idxmin()
    mejor = m.loc[idx, [col_id_origen, col_id_destino, "duracion_seg", "distancia_m"]].copy()
    mejor = mejor.rename(columns={col_id_destino: "id_mas_cercano",
                                  "duracion_seg": "t_min_seg",
                                  "distancia_m": "dist_min_m"})
    mejor["t_min_min"] = mejor["t_min_seg"] / 60.0
    mejor["alcanzable"] = True

    # Un trayecto de EXACTAMENTE 0 segundos y 0 metros entre dos ubicaciones distintas no es
    # un establecimiento "en la puerta": es que OSRM engancho el origen y el destino al mismo
    # nodo de la red y no puede distinguirlos. Ocurre donde la red es dispersa, que es
    # justamente donde el resultado importa, asi que se marca en vez de tomarse por bueno.
    mejor["snap_colapsado"] = (mejor["dist_min_m"].fillna(-1) == 0)
    n_col = int(mejor["snap_colapsado"].sum())
    if n_col:
        log.warning("  %d de %d origenes (%.1f%%) tienen trayecto degenerado de 0 m: el "
                    "origen y el establecimiento enganchan al mismo nodo de la red. Se "
                    "marcan `snap_colapsado` y se excluyen de los estadisticos de tiempo.",
                    n_col, len(mejor), 100 * n_col / len(mejor))

    todos = matriz[[col_id_origen]].drop_duplicates()
    out = todos.merge(mejor, on=col_id_origen, how="left")
    out["alcanzable"] = out["alcanzable"].fillna(False).astype(bool)
    n_inalc = int((~out["alcanzable"]).sum())
    if n_inalc:
        log.warning("  %d de %d origenes no alcanzan NINGUN establecimiento resolutivo "
                    "por carretera (%.1f%%)", n_inalc, len(out), 100 * n_inalc / len(out))
    return out


def snap_con_cache(
    client: OSRMClient,
    puntos: pd.DataFrame,
    perfil: str,
    etiqueta: str,
    cache_dir: Path,
    col_id: str = "ccpp_id",
    forzar: bool = False,
) -> pd.DataFrame:
    """
    Snapping cacheado en Parquet. El enganche es una peticion HTTP por punto, asi que sobre
    5 000 puntos cuesta cerca de un minuto: no tiene sentido repetirlo en cada corrida.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    clave = _clave_cache(perfil, puntos[col_id], pd.Series([etiqueta]))
    destino = cache_dir / f"snap_{perfil}_{etiqueta}_{clave}.parquet"
    if destino.exists() and not forzar:
        snap = pd.read_parquet(destino)
        log.info("  [cache] snapping %-6s %-8s %d puntos reutilizados",
                 perfil, etiqueta, len(snap))
        return snap
    t0 = time.perf_counter()
    snap = client.nearest(puntos["lon"].to_numpy(), puntos["lat"].to_numpy())
    snap.to_parquet(destino, index=False)
    log.info("  snapping %s/%s calculado en %.0fs", perfil, etiqueta, time.perf_counter() - t0)
    return snap


def diagnostico_snapping(snap: pd.DataFrame, etiqueta: str) -> dict:
    """Resumen del enganche a la red, tal como lo exige el enunciado."""
    ok = snap["snap_ok"]
    d = snap.loc[ok, "snap_m"]
    res = {
        "conjunto": etiqueta,
        "n_puntos": len(snap),
        "n_enganchados": int(ok.sum()),
        "n_fallidos": int((~ok).sum()),
        "snap_medio_m": round(float(d.mean()), 1) if len(d) else None,
        "snap_mediana_m": round(float(d.median()), 1) if len(d) else None,
        "snap_p95_m": round(float(d.quantile(0.95)), 1) if len(d) else None,
        "snap_max_m": round(float(d.max()), 1) if len(d) else None,
        "n_snap_mayor_1km": int((d > 1000).sum()) if len(d) else 0,
        "n_snap_mayor_5km": int((d > 5000).sum()) if len(d) else 0,
    }
    log.info("  snapping %-10s: %d/%d enganchados · medio=%.0fm mediana=%.0fm p95=%.0fm "
             "max=%.0fm · >1km: %d · >5km: %d",
             etiqueta, res["n_enganchados"], res["n_puntos"],
             res["snap_medio_m"] or 0, res["snap_mediana_m"] or 0,
             res["snap_p95_m"] or 0, res["snap_max_m"] or 0,
             res["n_snap_mayor_1km"], res["n_snap_mayor_5km"])
    return res


# ======================================================= cobertura real de la red vial
def clasificar_cobertura_red(
    demanda: pd.DataFrame, snap: pd.DataFrame, cfg: Config
) -> pd.DataFrame:
    """
    Marca los puntos que la red vial no sirve realmente.

    OSRM engancha cada punto a la via mas cercana y rutea **desde ahi**, ignorando el tramo
    entre el punto real y esa via. Mientras ese tramo son decenas de metros el efecto es
    despreciable; cuando son kilometros, el tiempo calculado deja de medir lo que se
    pretende medir y lo subestima sistematicamente.

    En Loreto el centro poblado mediano engancha a 10.4 km de la carretera mas proxima
    (p90: 60 km; maximo: 113 km), porque la conectividad amazonica es fluvial. Sin esta
    clasificacion, esos puntos recibirian un tiempo de viaje artificialmente bajo.

    Los puntos por encima del umbral **no se borran ni se rellenan** con distancia
    euclidiana: se marcan `fuera_de_red` y se reportan por separado. La diferencia entre la
    metrica con y sin ellos es, en si misma, la medida de cuanta poblacion queda fuera del
    alcance de la red vial.
    """
    umbral = float(cfg.ruteo.get("snap_umbral_m", 2000))
    out = demanda.copy()
    out["snap_m"] = snap["snap_m"].to_numpy()
    out["snap_ok"] = snap["snap_ok"].to_numpy()
    out["fuera_de_red"] = (~out["snap_ok"]) | (out["snap_m"] > umbral)

    n = int(out["fuera_de_red"].sum())
    pob_fuera = float(out.loc[out["fuera_de_red"], "peso_muestral"].sum())
    pob_total = float(out["peso_muestral"].sum())
    log.info("  fuera de red (snap > %.0f m): %d/%d puntos (%.1f%%) · "
             "%.0f habitantes (%.1f%% de la poblacion)",
             umbral, n, len(out), 100 * n / len(out),
             pob_fuera, 100 * pob_fuera / pob_total if pob_total else 0)
    for dep, g in out.groupby("departamento"):
        pf = float(g.loc[g["fuera_de_red"], "peso_muestral"].sum())
        pt = float(g["peso_muestral"].sum())
        log.info("    %-12s %4d/%4d puntos · %5.1f%% de su poblacion",
                 dep, int(g["fuera_de_red"].sum()), len(g), 100 * pf / pt if pt else 0)
    return out


def sensibilidad_umbral(demanda: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    Cuanta poblacion queda clasificada como fuera de red segun donde se ponga el umbral.

    Sirve para demostrar que la conclusion no depende de haber elegido 2 000 m a dedo: si el
    resultado es cualitativamente el mismo con 500 m y con 10 000 m, el umbral no manda.
    Requiere que `demanda` traiga ya las columnas `snap_m` y `peso_muestral`.
    """
    umbrales = cfg.ruteo.get("snap_umbrales_sensibilidad", [500, 1000, 2000, 5000, 10000])
    filas = []
    pob_total = float(demanda["peso_muestral"].sum())
    for u in umbrales:
        fuera = (~demanda["snap_ok"]) | (demanda["snap_m"] > u)
        fila = {"umbral_m": u,
                "puntos_fuera": int(fuera.sum()),
                "pct_puntos": round(100 * fuera.mean(), 1),
                "poblacion_fuera": round(float(demanda.loc[fuera, "peso_muestral"].sum())),
                "pct_poblacion": round(
                    100 * demanda.loc[fuera, "peso_muestral"].sum() / pob_total, 1)
                if pob_total else 0.0}
        for dep, g in demanda.groupby("departamento"):
            f = (~g["snap_ok"]) | (g["snap_m"] > u)
            pt = float(g["peso_muestral"].sum())
            fila[f"pct_pob_{dep[:4].lower()}"] = round(
                100 * float(g.loc[f, "peso_muestral"].sum()) / pt, 1) if pt else 0.0
        filas.append(fila)
    out = pd.DataFrame(filas)
    log.info("  sensibilidad al umbral de enganche:\n%s", out.to_string(index=False))
    return out


# ======================================================== comparacion entre modos
def comparar_modos(
    mejores: dict[str, pd.DataFrame], demanda: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compara el acceso al establecimiento resolutivo mas cercano entre perfiles.

    El enunciado pide dos cosas y advierte que las discrepancias **son hallazgos, no bugs**:

      1. Con que frecuencia el establecimiento mas cercano CAMBIA segun el modo. Cambia
         porque las redes no son la misma: una autopista acorta mucho en auto y nada a pie,
         mientras que un camino peatonal puede unir en linea lo que en auto exige un rodeo.
      2. Como se compara el tiempo entre modos. La razon caminar/conducir **no es constante**:
         depende del terreno, del tipo de via y de la conectividad de la red.

    Devuelve (tabla_larga_por_punto, resumen_por_departamento).
    """
    if "car" not in mejores:
        raise ValueError("La comparacion entre modos necesita al menos el perfil 'car'")

    base = demanda[["ccpp_id", "departamento", "poblacion", "peso_muestral",
                    "urbano_rural"]].copy()
    for perfil, df in mejores.items():
        cols = df[["ccpp_id", "id_mas_cercano", "t_min_min", "dist_min_m", "alcanzable"]].copy()
        cols.columns = ["ccpp_id", f"id_{perfil}", f"t_{perfil}", f"dist_{perfil}",
                        f"alc_{perfil}"]
        base = base.merge(cols, on="ccpp_id", how="left")

    perfiles = [p for p in mejores if p != "car"]
    for p in perfiles:
        # Cambia el establecimiento mas cercano al cambiar de modo? Solo tiene sentido
        # preguntarlo donde AMBOS modos alcanzan algo; donde no, la respuesta es "no se sabe".
        # Se usa el dtype nullable "boolean" (no el bool de numpy) porque necesita admitir
        # pd.NA: en pandas 3.x asignar NA a una columna bool corriente lanza TypeError.
        amb = base[f"alc_{p}"].fillna(False) & base["alc_car"].fillna(False)
        cambia = (amb & (base[f"id_{p}"] != base["id_car"])).astype("boolean")
        cambia[~amb] = pd.NA
        base[f"cambia_vs_car_{p}"] = cambia
        # Razon de tiempos.
        base[f"razon_{p}_car"] = base[f"t_{p}"] / base["t_car"].replace(0, np.nan)

    filas = []
    for dep, g in base.groupby("departamento"):
        f = {"departamento": dep, "n_puntos": len(g)}
        for perfil in mejores:
            alc = g[f"alc_{perfil}"].fillna(False)
            f[f"alcanzables_{perfil}"] = int(alc.sum())
            f[f"t_mediana_{perfil}_min"] = round(float(g.loc[alc, f"t_{perfil}"].median()), 1) \
                if alc.any() else None
        for p in perfiles:
            camb = g[f"cambia_vs_car_{p}"].dropna()
            f[f"pct_cambia_{p}"] = round(100 * camb.mean(), 1) if len(camb) else None
            r = g[f"razon_{p}_car"].replace([np.inf, -np.inf], np.nan).dropna()
            f[f"razon_{p}_car_mediana"] = round(float(r.median()), 2) if len(r) else None
            f[f"razon_{p}_car_p90"] = round(float(r.quantile(0.9)), 2) if len(r) else None
        filas.append(f)
    resumen = pd.DataFrame(filas)

    log.info("  comparacion entre modos:")
    for _, f in resumen.iterrows():
        log.info("    %-12s mediana car=%s min", f["departamento"], f.get("t_mediana_car_min"))
        for p in perfiles:
            log.info("                  %-4s mediana=%s min · razon vs car: %s (p90 %s) · "
                     "cambia el mas cercano en %s%% de los puntos",
                     p, f.get(f"t_mediana_{p}_min"), f.get(f"razon_{p}_car_mediana"),
                     f.get(f"razon_{p}_car_p90"), f.get(f"pct_cambia_{p}"))
    return base, resumen


def acceso_urbano_a_pie(
    client: OSRMClient,
    demanda: pd.DataFrame,
    oferta_toda: pd.DataFrame,
    cfg: Config,
    forzar: bool = False,
) -> pd.DataFrame | None:
    """
    Tiempo caminando de los puntos de demanda urbanos al establecimiento mas cercano
    **de cualquier categoria**, no solo resolutivo.

    Lo pide explicitamente el enunciado, y mide algo distinto del resto del estudio: no la
    capacidad de resolver una emergencia quirurgica, sino la accesibilidad cotidiana a una
    posta o centro de salud, que es como la mayoria de la poblacion urbana usa el sistema.

    Se restringe a los puntos urbanos porque caminar como modo de acceso solo tiene sentido
    a esa escala; en el ambito rural disperso la distancia lo vuelve irrelevante.
    """
    urbanos = demanda[demanda["es_urbano"]].copy()
    if urbanos.empty:
        log.warning("  no hay puntos de demanda urbanos en la muestra")
        return None
    log.info("  acceso urbano a pie: %d puntos urbanos x %d establecimientos de cualquier "
             "categoria", len(urbanos), len(oferta_toda))

    m = matriz_con_cache(client, urbanos, oferta_toda, "foot_urbano", cfg.cache_dir,
                         forzar=forzar)
    mc = mas_cercano(m)
    out = urbanos[["ccpp_id", "departamento", "distrito", "poblacion", "peso_muestral"]].merge(
        mc, on="ccpp_id", how="left")
    out = out.rename(columns={"id_mas_cercano": "ipress_mas_cercana_pie",
                              "t_min_min": "t_pie_min", "dist_min_m": "dist_pie_m",
                              "t_min_seg": "t_pie_seg", "alcanzable": "alcanzable_pie",
                              "snap_colapsado": "snap_colapsado_pie"})
    alc = out["alcanzable_pie"].fillna(False)
    col = out["snap_colapsado_pie"].fillna(False)
    valido = alc & ~col

    log.info("  tiempo caminando al establecimiento mas cercano (cualquier categoria):")
    log.info("    %-12s %5s %7s %8s %8s %s", "depto", "n", "mediana", "p90", "colapsad", "")
    for dep, g in out.groupby("departamento"):
        gv = g[valido.reindex(g.index, fill_value=False)]
        gc = int(col.reindex(g.index, fill_value=False).sum())
        if len(gv):
            log.info("    %-12s %5d %6.1f' %7.1f' %8d  (%.0f%% de sus puntos)",
                     dep, len(gv), gv["t_pie_min"].median(), gv["t_pie_min"].quantile(0.9),
                     gc, 100 * gc / len(g))
        else:
            log.warning("    %-12s sin puntos validos: los %d urbanos tienen el trayecto "
                        "colapsado por red dispersa", dep, gc)
    return out


# ================================================================== ejecucion directa
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="Pruebas del modulo de ruteo, sin el pipeline")
    p.add_argument("--check", action="store_true", help="Verifica que OSRM responde")
    p.add_argument("--demo", action="store_true",
                   help="Ruta de prueba Chiclayo -> Hospital Regional Lambayeque")
    p.add_argument("--perfil", default="car", help="Perfil declarado en config.md")
    args = p.parse_args()

    from .config import load_config
    cfg = load_config()
    url = cfg.ruteo.get("osrm_url", "http://localhost:5000")
    cli = OSRMClient(base_url=url)

    if args.check or not (args.check or args.demo):
        print(f"Probando OSRM en {url} ...")
        print("OSRM DISPONIBLE" if cli.disponible() else "OSRM NO DISPONIBLE")
    if args.demo:
        r = cli.route(-79.8409, -6.7714, -79.8730, -6.7620)
        print(f"duracion: {r['duracion_seg'] / 60:.1f} min · "
              f"distancia: {r['distancia_m'] / 1000:.2f} km")
