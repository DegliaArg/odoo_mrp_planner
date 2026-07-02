def migrate(cr, version):
    cr.execute("""
        ALTER TABLE mrp_reschedule_config
        ADD COLUMN IF NOT EXISTS supplier_analysis_date_field varchar NOT NULL DEFAULT 'date_approve'
    """)
