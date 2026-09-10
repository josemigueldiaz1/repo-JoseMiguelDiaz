### Reporte de calidad — `oferta_renipress (RENIPRESS_31-08-2026.csv)`

- Registros evaluados: **36,004**
- Reglas aplicadas: **6**
- Reglas con hallazgos: **4**
- Total de marcas: **14,904** (un registro puede activar mas de una regla)
- Recuperados: **354** · Descartados: **13,181**

| Regla | Descripcion | Marcados | % | Recup. | Descart. | Accion |
|---|---|---:|---:|---:|---:|---|
| R6 | Problemas de codificacion en campos de texto | 4 | 0.011% | 4 | 0 | CORREGIDO |
| R5 | Codigos duplicados en `COD_IPRESS` | 0 | 0.0% | 0 | 0 | SIN_HALLAZGOS |
| R1 | Coordenadas ausentes, nulas o cero | 13,176 | 36.596% | 0 | 13,176 | RETENIDO_CON_ADVERTENCIA |
| R3 | Latitud y longitud intercambiadas | 0 | 0.0% | 0 | 0 | SIN_HALLAZGOS |
| R2 | Coordenadas fuera del bounding box del Peru | 5 | 0.014% | 0 | 5 | RETENIDO_CON_ADVERTENCIA |
| R4 | Punto fuera del distrito que el registro declara | 1,719 | 7.532% | 350 | 0 | RETENIDO_CON_ADVERTENCIA |

**Justificacion de cada accion**

- **R6 — Problemas de codificacion en campos de texto.** El archivo se lee con `utf-8-sig`, que es su codificacion real (UTF-8 con BOM). Leerlo como latin-1 renombra la primera columna a `ï»¿INSTITUCION` y mete mojibake en los campos acentuados; por eso el encoding es un parametro de `config.md` y no un valor incrustado. Los residuos que sobreviven se reparan re-codificando a latin-1 y decodificando como UTF-8, y la reparacion solo se acepta si elimina la firma de mojibake. Columnas afectadas: {'NOMBRE': 4}.
- **R5 — Codigos duplicados en `COD_IPRESS`.** No se hallaron codigos repetidos: el identificador es unico en este corte.
- **R1 — Coordenadas ausentes, nulas o cero.** 13,174 filas sin coordenada y 2 con (0,0). No son recuperables sin geocodificar la direccion, lo que introduciria un error de posicion mayor que el que se quiere medir. Se conservan en el dataset con `coord_valida=False` (siguen contando para estadisticas de cobertura del registro) pero se excluyen del calculo de establecimiento mas cercano. Excluirlas del ruteo sesga la oferta a la baja: es una limitacion que el informe declara explicitamente.
- **R3 — Latitud y longitud intercambiadas.** Los rangos validos de latitud y longitud del Peru no se solapan, de modo que un par intercambiado solo es interpretable de una forma. La correccion es deterministica y se aplica con tasa de recuperacion del 100%; no se descarta ningun registro por esta causa. En este corte del registro no se hallo ningun caso: la regla queda implementada y ejercitada, y su conteo cero es en si un resultado.
- **R2 — Coordenadas fuera del bounding box del Peru.** Evaluado contra lon [-81.4, -68.6] y lat [-18.4, -0.04]. Se aplica despues de R3 para no contar como fuera de rango un punto que solo estaba invertido. Lo que queda marcado no tiene una lectura alternativa plausible (signo perdido, unidades UTM sin convertir), asi que se retiene con `coord_valida=False` en vez de inventarle una posicion.
- **R4 — Punto fuera del distrito que el registro declara.** Se cruzo cada punto con los limites distritales del IGN. 350 caen a menos de 0.002deg del borde del distrito declarado y se aceptan como error de digitalizacion del limite (~222 m a esta latitud). 1,369 presentan un conflicto real entre coordenada y UBIGEO. Esos no se corrigen automaticamente: no hay informacion para decidir si el erroneo es el punto o el codigo, y sobrescribir uno con el otro fabricaria una precision inexistente. Se retienen con `distrito_estado` explicito para que el analisis de sensibilidad del informe pueda excluirlos y medir el efecto.