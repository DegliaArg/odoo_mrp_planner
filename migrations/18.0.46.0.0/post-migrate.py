import logging

_logger = logging.getLogger(__name__)

_MENU_XMLIDS = [
    ('odoo_mrp_planner', 'mrp_reschedule_menu_plans'),
    ('odoo_mrp_planner', 'mrp_reschedule_menu_request'),
]
_GROUP_XMLID = ('odoo_mrp_planner', 'group_scheduling')


def migrate(cr, version):
    """Sincroniza menús y grupo de scheduling con el valor de enable_scheduling.

    Corre en cada upgrade para que el estado de los menús y el grupo queden
    alineados con la configuración actual, independientemente de si se creó
    un registro nuevo o ya existía el singleton antes de este código.
    """
    cr.execute("SELECT enable_scheduling FROM mrp_reschedule_config LIMIT 1")
    row = cr.fetchone()
    enabled = bool(row[0]) if row else True
    _logger.info("post-migrate 46: enable_scheduling=%s — sincronizando menús y grupo", enabled)

    # ── Menús: active=enabled ──────────────────────────────────────────────
    for module, name in _MENU_XMLIDS:
        cr.execute(
            "SELECT res_id FROM ir_model_data WHERE module=%s AND name=%s LIMIT 1",
            (module, name),
        )
        md = cr.fetchone()
        if not md:
            _logger.warning("post-migrate 46: no se encontró %s.%s en ir_model_data", module, name)
            continue
        cr.execute("UPDATE ir_ui_menu SET active=%s WHERE id=%s", (enabled, md[0]))

    # ── Grupo: poblar o vaciar ─────────────────────────────────────────────
    cr.execute(
        "SELECT res_id FROM ir_model_data WHERE module=%s AND name=%s LIMIT 1",
        _GROUP_XMLID,
    )
    gmd = cr.fetchone()
    if not gmd:
        _logger.warning("post-migrate 46: group_scheduling no encontrado en ir_model_data")
        return
    gid = gmd[0]

    if enabled:
        cr.execute("""
            INSERT INTO res_groups_users_rel (gid, uid)
            SELECT %s, id FROM res_users WHERE share = false AND active = true
            ON CONFLICT DO NOTHING
        """, (gid,))
        cr.execute("SELECT COUNT(*) FROM res_groups_users_rel WHERE gid=%s", (gid,))
        count = cr.fetchone()[0]
        _logger.info("post-migrate 46: group_scheduling poblado con %d usuarios", count)
    else:
        cr.execute("DELETE FROM res_groups_users_rel WHERE gid=%s", (gid,))
        _logger.info("post-migrate 46: group_scheduling vaciado")
