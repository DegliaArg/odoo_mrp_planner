# -*- coding: utf-8 -*-
"""Renombra el campo de planificación vulcanizado_id -> manufactured_product_id.

Antes el componente del que se lee la máquina y el mínimo por turno se llamaba
"Vulcanizado" (hardcodeo de un sector concreto). Se generaliza a "Componente
fabricado" (manufactured_product_id). Se renombra la columna para conservar los
valores ya precalculados/cargados a mano, en vez de dejar que el recálculo los
vuelva a detectar (y se perderían los overrides manuales).
"""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'product_template'
          AND column_name = 'vulcanizado_id'
    """)
    if not cr.fetchone():
        return
    # Si por algún motivo ya existiera la columna nueva, no pisarla.
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'product_template'
          AND column_name = 'manufactured_product_id'
    """)
    if cr.fetchone():
        return
    cr.execute("""
        ALTER TABLE product_template
        RENAME COLUMN vulcanizado_id TO manufactured_product_id
    """)
