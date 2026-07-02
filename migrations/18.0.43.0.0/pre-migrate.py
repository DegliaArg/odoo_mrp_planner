def migrate(cr, version):
    # Umbrales Pareto configurables para clasificación ABC de proveedores y clientes
    cr.execute("""
        ALTER TABLE mrp_reschedule_config
        ADD COLUMN IF NOT EXISTS abc_pct_a integer NOT NULL DEFAULT 20,
        ADD COLUMN IF NOT EXISTS abc_pct_b integer NOT NULL DEFAULT 50,
        ADD COLUMN IF NOT EXISTS abc_pct_c integer NOT NULL DEFAULT 80,
        ADD COLUMN IF NOT EXISTS abc_pct_d integer NOT NULL DEFAULT 95
    """)
