"""
Modulos de la Tarea 1 — RAG Normativo.

El reparto de responsabilidades responde a la arquitectura que exige el enunciado:

    config       lee config.yaml; unica fuente de parametros
    fuentes      descarga los PDF y ejecuta la comprobacion de fuentes (Fase 1)
    extraccion   PDF -> paginas, conservando el numero de pagina desde el primer paso
    limpieza     quita cabeceras de El Peruano y normaliza el texto
    chunking     paginas -> fragmentos con metadatos e ID estable
    embeddings   UNA interfaz, DOS implementaciones (local y API)
    indice       persistencia vectorial en ChromaDB
    costos       registro de cada llamada con el precio de la franja horaria
    motor        la funcion unica que responde una pregunta

`motor` es el nucleo y NO importa ninguna libreria de interfaz. Se verifica con:

    python -c "import ast,sys; ..."    (ver README, seccion 'Verificacion de arquitectura')
"""
