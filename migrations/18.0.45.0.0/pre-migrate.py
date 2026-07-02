def migrate(cr, version):
    cr.execute("""
        ALTER TABLE mrp_reschedule_config
        ADD COLUMN IF NOT EXISTS enable_sale_categories boolean NOT NULL DEFAULT false
    """)
