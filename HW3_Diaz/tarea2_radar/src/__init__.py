"""
Modulos de la Tarea 2 — Radar de compras publicas.

    config        subclase del Config de la Tarea 1; anade lo propio de esta tarea
    adquisicion   descarga los bulk mensuales de OECE por su API, con cache y sha
    validacion    reglas de calidad y reporte de lo que se encontro
    territorio    normaliza la ubicacion del comprador a los 25 departamentos
    motor         RAG HIBRIDO: filtros estructurados + busqueda semantica
    metricas      indicador de postor unico y demas senales de alerta

Lo que NO esta aqui, a proposito: el modelo de embeddings, el almacen vectorial y el
registro de costos. Esos se importan de `tarea1_rag_normativo.src`, porque el enunciado
pide reutilizar el motor de la Tarea 1 y porque mantener dos copias del mismo codigo es
la forma mas segura de que acaben divergiendo.
"""
