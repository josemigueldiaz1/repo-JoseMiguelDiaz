"""
HW2 — Analisis geoespacial de accesibilidad a establecimientos de salud resolutivos.

Paquete de modulos reutilizables del pipeline. Cada fase del enunciado vive en su
propio modulo y es importable y ejecutable de forma independiente:

    config       lectura de config.md (unica fuente de verdad de los parametros)
    acquisition  Fase 1 — descarga reproducible de las fuentes
    validation   Fase 1 — las seis reglas de calidad y el reporte
    supply       Fase 1 — dataset de oferta (RENIPRESS)
    demand       Fase 1 — dataset de demanda (centros poblados + poblacion WorldPop)
    io_utils     escritura de resultados en el formato declarado en config.md
    export       figuras y mapas para el informe
"""

__version__ = "0.1.0"
__author__ = "Jose Miguel Diaz"
