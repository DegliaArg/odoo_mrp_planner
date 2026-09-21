from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Convierte los centros alternativos del viejo Many2many a la tabla propia
    mrp.routing.workcenter.alt, precargando el time_cycle_manual de cada operación.

    El campo `alternative_workcenter_ids` pasó de Many2many (solo la lista de CTs)
    a One2many con duración por centro. La tabla de relación anterior
    (`mrp_routing_wc_scheduling_alt_rel`) queda huérfana tras el cambio de tipo;
    acá se leen sus filas, se crean las líneas nuevas y se elimina la tabla.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute("SELECT to_regclass('mrp_routing_wc_scheduling_alt_rel')")
    if not cr.fetchone()[0]:
        return  # nada que migrar (instalación limpia o ya migrada)

    cr.execute(
        "SELECT routing_wc_id, workcenter_id FROM mrp_routing_wc_scheduling_alt_rel"
    )
    rows = cr.fetchall()

    Alt = env['mrp.routing.workcenter.alt']
    Op = env['mrp.routing.workcenter']
    Wc = env['mrp.workcenter']
    for routing_wc_id, workcenter_id in rows:
        op = Op.browse(routing_wc_id).exists()
        wc = Wc.browse(workcenter_id).exists()
        if not op or not wc:
            continue
        # Idempotente: si ya existe la línea (re-corrida), no duplicar.
        if Alt.search_count([
            ('routing_workcenter_id', '=', op.id),
            ('workcenter_id', '=', wc.id),
        ]):
            continue
        Alt.create({
            'routing_workcenter_id': op.id,
            'workcenter_id': wc.id,
            'time_cycle_manual': op.time_cycle_manual or op.time_cycle or 0.0,
        })

    cr.execute("DROP TABLE IF EXISTS mrp_routing_wc_scheduling_alt_rel")
