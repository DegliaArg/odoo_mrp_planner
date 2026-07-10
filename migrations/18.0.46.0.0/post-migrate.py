import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Seed group_scheduling with all internal active users if enable_scheduling is True.

    This runs after every upgrade so that existing config singletons (which were
    created before this group existed) get their users populated correctly.
    """
    cr.execute("SELECT enable_scheduling FROM mrp_reschedule_config LIMIT 1")
    row = cr.fetchone()
    if not row or not row[0]:
        _logger.info("post-migrate 46: enable_scheduling is False or no config; skipping group seed")
        return

    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'odoo_mrp_planner' AND name = 'group_scheduling'
        LIMIT 1
    """)
    gmd = cr.fetchone()
    if not gmd:
        _logger.warning("post-migrate 46: group_scheduling not found in ir.model.data; skipping")
        return
    gid = gmd[0]

    cr.execute("""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT %s, id FROM res_users
        WHERE share = false AND active = true
        ON CONFLICT DO NOTHING
    """, (gid,))

    cr.execute("SELECT COUNT(*) FROM res_groups_users_rel WHERE gid = %s", (gid,))
    count = cr.fetchone()[0]
    _logger.info("post-migrate 46: group_scheduling now has %d users", count)
