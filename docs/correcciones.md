# Correcciones pendientes

## Panel de Compras

### C5 — Días de retraso/vencimiento no aparecen en los KPI
**Archivos:** `views/mrp_planner_dashboard_views.xml`, `models/mrp_planner_dashboard.py`, `static/src/js/alert_kpi_widget.js`  
**Problema:** Los KPI de alertas (tanto producción como compras) solo muestran conteos, sin indicar cuántos días lleva el retraso o cuántos días faltan para vencer.  
**Pendiente:** Definir qué dato mostrar (máximo de días, promedio, u otro).
