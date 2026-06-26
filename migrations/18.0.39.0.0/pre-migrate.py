def migrate(cr, version):
    # res_users.mrp_planner_all_warehouses — added in v39; must exist before ORM
    # fetches res_users on every request (blocks server if missing)
    cr.execute("""
        ALTER TABLE res_users
        ADD COLUMN IF NOT EXISTS mrp_planner_all_warehouses boolean NOT NULL DEFAULT true
    """)

    # M2M rel table for res.users ↔ stock.warehouse
    cr.execute("""
        CREATE TABLE IF NOT EXISTS res_users_mrp_planner_wh_rel (
            user_id      integer NOT NULL REFERENCES res_users(id) ON DELETE CASCADE,
            warehouse_id integer NOT NULL,
            PRIMARY KEY (user_id, warehouse_id)
        )
    """)

    # product_template.x_sale_category — varchar selection field
    cr.execute("""
        ALTER TABLE product_template
        ADD COLUMN IF NOT EXISTS x_sale_category varchar
    """)
