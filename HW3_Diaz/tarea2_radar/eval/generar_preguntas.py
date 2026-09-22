"""
Genera el conjunto de evaluacion de la Tarea 2 con procesos relevantes REALES.

El enunciado pide "at least 10 questions with known relevant processes". El problema
practico es de donde sale ese "known": anotar a mano cuales de 20,422 procesos son
relevantes para una pregunta es inviable, y elegirlos a ojo sesgaria la evaluacion hacia
los que uno ya sabe que el buscador encuentra.

La solucion que se usa aqui es explicita y reproducible: para cada tema se define una
**regla lexica** sobre el texto del proceso (una expresion regular con los terminos que
un experto usaria) y se toman como relevantes TODOS los procesos que la cumplen. Esa
regla es el patron de oro; la busqueda semantica se evalua contra el.

La ventaja metodologica es que el patron de oro se construye con un mecanismo
DISTINTO del que se evalua: la verdad se fija por coincidencia de palabras y se mide si
los embeddings, que no ven palabras sino significado, la recuperan. Si se hubiera fijado
con los propios embeddings, la evaluacion seria circular.

Su limitacion, que conviene declarar: la regla lexica no captura procesos que describan
lo mismo con otras palabras, asi que el patron de oro puede quedarse corto. Eso hace la
metrica CONSERVADORA (el sistema puede recuperar procesos correctos que la regla no
marco y se le contarian como fallo), nunca optimista.

Uso:
    python eval/generar_preguntas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
HW3 = RAIZ.parent
for p in (str(RAIZ), str(HW3)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.config import load_config  # noqa: E402

# (id, pregunta en lenguaje natural, regex del patron de oro, filtros declarados)
TEMAS = [
    ("R01", "obras de agua potable y saneamiento",
     r"(agua potable|saneamiento|alcantarillado|aguas residuales|desag[uü]e)", {}),
    ("R02", "compra de computadoras y equipos informaticos",
     r"(computador|laptop|inform[aá]tic|servidor|impresora|licencia de software)", {}),
    ("R03", "servicios de consultoria para proyectos de inversion",
     r"(consultor[ií]a|expediente t[eé]cnico|estudio de preinversi[oó]n|supervisi[oó]n de obra)", {}),
    ("R04", "medicamentos e insumos para establecimientos de salud",
     r"(medicament|f[aá]rmac|insumo m[eé]dic|material m[eé]dic|hospital)", {}),
    ("R05", "mejoramiento y rehabilitacion de carreteras y caminos",
     r"(carretera|camino vecinal|v[ií]a|pavimen|trocha|puente)", {}),
    ("R06", "alimentos para programas sociales",
     r"(alimento|raci[oó]n|desayuno escolar|v[ií]veres|canasta)", {}),
    ("R07", "construccion y mejoramiento de instituciones educativas",
     r"(instituci[oó]n educativa|colegio|aula|escolar|educativ)", {}),
    ("R08", "servicios de seguridad y vigilancia",
     r"(vigilancia|seguridad privada|resguardo|cust[o]dia)", {}),
    ("R09", "adquisicion de combustible y carburantes",
     r"(combustible|di[eé]sel|gasolina|petr[oó]leo|gas licuado|glp)", {}),
    ("R10", "equipamiento y mobiliario para oficinas",
     r"(mobiliario|escritorio|silla|estante|mueble)", {}),
    ("R11", "mantenimiento de redes electricas y alumbrado",
     r"(el[eé]ctric|alumbrado|energ[ií]a|subestaci[oó]n|luminaria)", {}),
    ("R12", "servicios de limpieza publica y manejo de residuos solidos",
     r"(limpieza p[uú]blica|residuos s[oó]lidos|recolecci[oó]n de basura|relleno sanitario)", {}),
]


def main() -> int:
    cfg = load_config()
    p = cfg.processed_dir / "procesos.parquet"
    if not p.exists():
        print(f"Falta {p}. Corre antes: python build_data.py")
        return 1

    df = pd.read_parquet(p)
    texto = (df["titulo"].fillna("") + " " + df["descripcion"].fillna("")).str.lower()

    filas = []
    for id_, pregunta, patron, _filtros in TEMAS:
        m = texto.str.contains(patron, regex=True, na=False)
        ocids = df.loc[m, "ocid"].tolist()
        if len(ocids) < 3:
            print(f"  {id_}: solo {len(ocids)} procesos relevantes; se omite")
            continue
        # Se guardan hasta 60 ocids relevantes. Mas no aporta: Recall@k con k<=5 solo
        # necesita saber si el recuperado pertenece al conjunto.
        filas.append({
            "id": id_,
            "pregunta": pregunta,
            "tipo": "in_domain",
            "patron_oro": patron,
            "n_relevantes": len(ocids),
            "ocids_relevantes": ";".join(ocids[:60]),
        })
        print(f"  {id_}: {len(ocids):5d} procesos relevantes · {pregunta}")

    # Preguntas fuera de dominio: ningun proceso puede responderlas.
    for id_, pregunta in [
        ("R90", "cual es la receta del ceviche peruano"),
        ("R91", "quien gano el mundial de futbol de 2022"),
        ("R92", "cuantos habitantes tiene la ciudad de Tokio"),
    ]:
        filas.append({"id": id_, "pregunta": pregunta, "tipo": "out_domain",
                      "patron_oro": "", "n_relevantes": 0, "ocids_relevantes": ""})

    out = pd.DataFrame(filas)
    destino = cfg.eval_dir / "preguntas.csv"
    out.to_csv(destino, index=False, encoding="utf-8")
    print(f"\n{len(out)} preguntas -> {destino}")
    print(f"  in_domain : {(out['tipo'] == 'in_domain').sum()}")
    print(f"  out_domain: {(out['tipo'] == 'out_domain').sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
