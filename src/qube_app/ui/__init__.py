"""Interfaz Qt de la app. Importar esto exige ``uv sync --extra app``.

El núcleo (``qube_app.link``, ``.stream``, ``.analysis``) no depende de Qt a propósito:
la autoprueba de banco corre sin GUI y los tests no necesitan un servidor gráfico.
"""
