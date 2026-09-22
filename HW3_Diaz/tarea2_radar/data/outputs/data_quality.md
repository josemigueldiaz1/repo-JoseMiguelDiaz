# Reporte de calidad de datos — Tarea 2

Ninguna regla elimina registros. Cada una marca una columna `flag_*`,
cuenta los afectados y declara que se hizo con ellos.

| Código | Qué detecta | Registros | % | Acción |
|---|---|---:|---:|---|
| `duplicados` | Mismo ocid en mas de una fila | 0 | 0.00% | ya deduplicado en la adquisicion; se conserva la aparicion mas reciente |
| `sin_monto` | Monto ausente, cero o negativo | 2,476 | 12.12% | se conserva; queda excluido de las sumas y del mapa por monto |
| `sin_descripcion` | Descripcion vacia o demasiado corta | 0 | 0.00% | se conserva; NO entra al indice semantico porque no hay que vectorizar |
| `localidad_no_dep` | El campo Localidad no es un departamento (mezcla provincias y distritos) | 16,281 | 79.72% | no se usa Localidad como departamento salvo como ultimo recurso difuso |
| `codificacion` | Tildes o mayusculas distintas del canonico (por ejemplo JUNIN frente a JUNIN con tilde) | 0 | 0.00% | corregido con normalizacion Unicode NFD |
| `sin_departamento` | No se pudo asignar departamento tras la cascada | 0 | 0.00% | se conserva etiquetado NO_LOCALIZADO; excluido solo del mapa |
| `sin_fecha` | Fecha de publicacion ausente o ilegible | 0 | 0.00% | se conserva; excluido de los filtros y graficos por fecha |