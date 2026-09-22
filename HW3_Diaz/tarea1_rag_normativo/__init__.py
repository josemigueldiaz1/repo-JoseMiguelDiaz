"""
Tarea 1 — RAG Normativo.

Este archivo convierte la carpeta en un paquete importable, y existe por un motivo
concreto: la Tarea 2 debe **reutilizar el motor de la Tarea 1**, no reimplementarlo.
Gracias a esto, `tarea2_radar` puede escribir

    from tarea1_rag_normativo.src.embeddings import crear
    from tarea1_rag_normativo.src.indice import IndiceVectorial
    from tarea1_rag_normativo.src.costos import RegistroCostos
    from tarea1_rag_normativo.src.config import Config

y compartir literalmente el mismo codigo: el mismo modelo de embeddings, el mismo
almacen vectorial, el mismo registro de costos y la misma logica de abstencion. Si se
corrige un fallo en el motor, se corrige para las dos tareas a la vez.
"""
