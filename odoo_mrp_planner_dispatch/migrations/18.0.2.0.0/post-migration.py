"""
Migración a 18.0.2.0.0 — Panel de Inventario estándar.

La "Tasa física s/ disponible" pasó a "Tasa de entrega s/ disponible": el
numerador cambió de "despachado" (x_dispatch_date, circuito opcional) a
"entregado" (salida a cliente validada, date_done), y el universo pendiente
dejó de incluir las validadas sin despachar y las transferencias entre
depósitos con tipo de salida. La serie acumulada mezcla ambos criterios, así
que se reinicia: se purgan los snapshots crudos y el consolidado mensual del
KPI. El cron los vuelve a generar desde cero con el criterio nuevo.
"""


def migrate(cr, version):
    cr.execute("DELETE FROM mrp_dispatch_stock_log")
    cr.execute("DELETE FROM mrp_planner_kpi_monthly WHERE kpi = 'dispatch_available'")
