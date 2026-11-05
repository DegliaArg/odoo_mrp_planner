# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Post-migración 18.0.13.8.0: pasa el cron del Resumen diario de Gerencia de
'cada 1 hora' a 'cada 15 minutos'.

El registro del cron es noupdate="1" (su estado activo lo administra el usuario),
así que el nuevo intervalo del XML no se aplica a las instalaciones existentes:
hay que actualizarlo acá. La granularidad de 15 min es la que permite respetar
los minutos de la hora de envío (p. ej. 15:30 y no solo la hora redonda).

Se adelanta además el próximo disparo a 'ahora' para que la nueva cadencia de
15 min arranque en la próxima pasada del planificador, sin esperar al viejo
nextcall (que podía estar hasta una hora en el futuro).
"""
from odoo import api, fields, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('odoo_mrp_planner.ir_cron_management_daily_report',
                   raise_if_not_found=False)
    if not cron:
        return
    cron.write({
        'interval_number': 15,
        'interval_type': 'minutes',
        'nextcall': fields.Datetime.now(),
    })
