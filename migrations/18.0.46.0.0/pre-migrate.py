import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Pre-migración 18.0.46.0.0 — DDL extraído de _auto_init().

    Mueve a esta migración versionada todo el DDL pesado (ALTER TABLE, INSERT
    de migración de datos) que antes se ejecutaba en cada upgrade desde los
    métodos _auto_init() de los modelos.  Los índices idempotentes manejados
    con tools.create_index (mrp_reschedule_alert) se mantienen en sus modelos.

    Bloques incluidos:
      1. mrp_reschedule_config  — DROP CONSTRAINT del singleton antiguo
      2. mrp_reschedule_plan    — ALTER COLUMN production_id DROP NOT NULL
      3. mrp_reschedule_config  — relleno de company_id en filas históricas
      4. mrp_reschedule_plan    — relleno de company_id en filas históricas
      5. mrp_reschedule_alert   — relleno de company_id en filas históricas
      6. mrp_partner_company_category — migración de columnas globales de res_partner
      7. mrp_product_company_category — migración de columna global de product_template
    """
    if not version:
        return

    # ── 1. mrp_reschedule_config: eliminar constraint singleton de columna única ──
    _logger.info("MRP Planner [1/7]: eliminando constraint singleton antiguo en mrp_reschedule_config")
    cr.execute("""
        ALTER TABLE mrp_reschedule_config
        DROP CONSTRAINT IF EXISTS mrp_reschedule_config_singleton
    """)

    # ── 2. mrp_reschedule_plan: production_id pasa a ser opcional ─────────────
    _logger.info("MRP Planner [2/7]: eliminando NOT NULL de mrp_reschedule_plan.production_id")
    cr.execute("""
        ALTER TABLE mrp_reschedule_plan
        ALTER COLUMN production_id DROP NOT NULL
    """)

    # ── 3. mrp_reschedule_config: rellenar company_id en registros históricos ──
    _logger.info("MRP Planner [3/7]: rellenando company_id en mrp_reschedule_config")
    cr.execute("""
        UPDATE mrp_reschedule_config
        SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
        WHERE company_id IS NULL
    """)

    # ── 4. mrp_reschedule_plan: rellenar company_id en planes históricos ───────
    _logger.info("MRP Planner [4/7]: rellenando company_id en mrp_reschedule_plan")
    cr.execute("""
        UPDATE mrp_reschedule_plan
        SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
        WHERE company_id IS NULL
    """)

    # ── 5. mrp_reschedule_alert: rellenar company_id en alertas históricas ─────
    _logger.info("MRP Planner [5/7]: rellenando company_id en mrp_reschedule_alert")
    cr.execute("""
        UPDATE mrp_reschedule_alert
        SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
        WHERE company_id IS NULL
    """)

    # ── 6. mrp_partner_company_category: migrar columnas globales de res_partner ─
    _logger.info("MRP Planner [6/7]: migrando categorías de proveedor/cliente por empresa")
    cr.execute("""
        INSERT INTO mrp_partner_company_category
            (partner_id, company_id, supplier_category, customer_category,
             create_uid, create_date, write_uid, write_date)
        SELECT
            rp.id,
            (SELECT id FROM res_company ORDER BY id LIMIT 1),
            rp.x_supplier_category,
            rp.x_customer_category,
            1, NOW() AT TIME ZONE 'UTC',
            1, NOW() AT TIME ZONE 'UTC'
        FROM res_partner rp
        WHERE (rp.x_supplier_category IS NOT NULL OR rp.x_customer_category IS NOT NULL)
          AND NOT EXISTS (
              SELECT 1 FROM mrp_partner_company_category mpc
               WHERE mpc.partner_id = rp.id
                 AND mpc.company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
          )
    """)

    # ── 7. mrp_product_company_category: migrar columna global de product_template ─
    _logger.info("MRP Planner [7/7]: migrando categorías de venta por empresa")
    cr.execute("""
        INSERT INTO mrp_product_company_category
            (product_tmpl_id, company_id, sale_category,
             create_uid, create_date, write_uid, write_date)
        SELECT
            pt.id,
            (SELECT id FROM res_company ORDER BY id LIMIT 1),
            pt.x_sale_category,
            1, NOW() AT TIME ZONE 'UTC',
            1, NOW() AT TIME ZONE 'UTC'
        FROM product_template pt
        WHERE pt.x_sale_category IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM mrp_product_company_category mpc
               WHERE mpc.product_tmpl_id = pt.id
                 AND mpc.company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
          )
    """)

    _logger.info("MRP Planner: pre-migración 18.0.46.0.0 completada correctamente")
