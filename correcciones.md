# Correcciones pendientes

## Panel de Compras

### C1 — Filtro de fecha usa campo incorrecto en OCs y Servicios
**Archivos:** `models/mrp_planner_dashboard.py` → `get_po_dashboard_data`  
**Problema:** El filtro de fecha filtra por `date_planned` (fecha de entrega estimada). Debería filtrar por `date_order` (fecha de emisión de la OC).  
**Aplica a:** pestañas OCs y Servicios. Recepciones y Entregas usan `scheduled_date`, que es correcto.

---

### C2 — KPI de alertas de compras sin tooltips
**Archivos:** `views/mrp_planner_dashboard_views.xml` (panel Compras, sección "Alertas de compras")  
**Problema:** Las 4 tarjetas (OCs vencidas, OCs por vencer, OCs canceladas, Recepciones) no tienen atributo `title` con descripción.

---

### C3 — KPI "OCs canceladas" siempre muestra 0
**Archivos:** `models/mrp_reschedule_alert.py`  
**Problema:** No existe ningún método `_check_cancelled_pos`. La alerta de tipo `po_cancelled` nunca se genera, por lo que el contador siempre es 0.  
**Solución propuesta:** Reemplazar este KPI por "Por aprobar" (`state = 'to approve'`), dato ya calculado en `_compute_po_stats` como `po_to_approve`.

---

### C4 — KPI "Recepciones" incluye recepciones internas
**Archivos:** `models/mrp_reschedule_alert.py` → `_check_delayed_receipts`  
**Problema:** La búsqueda filtra solo por `picking_type_code = 'incoming'`, lo que incluye traslados internos entrantes además de recepciones de OCs.  
**Solución propuesta:** Agregar filtro `('origin', '=like', 'P%')` para incluir solo pickings cuyo documento de origen sea una OC (comienza con 'P'). Alternativa más robusta: `('purchase_id', '!=', False)`. Usar la alternativa robusta (purchase_id)

---

### C5 — Días de retraso/vencimiento no aparecen en los KPI
**Archivos:** `views/mrp_planner_dashboard_views.xml`, `models/mrp_planner_dashboard.py`, `static/src/js/alert_kpi_widget.js`  
**Problema:** Los KPI de alertas (tanto producción como compras) solo muestran conteos, sin indicar cuántos días lleva el retraso o cuántos días faltan para vencer.  
**Pendiente:** Definir qué dato mostrar (máximo de días, promedio, u otro).

---

## Panel de Producción

### P1 — Widget OFs no excluye subcontratación
**Archivos:** `models/mrp_planner_dashboard.py` → `get_mo_widget_data`  
**Problema:** El método no aplica filtro de subcontratación. Las OFs con LdM de tipo `subcontract` aparecen en:
- KPIs: Activas, En progreso, Atrasadas, Para reprogramar, Finalizadas, Por cerrar
- Tabs: OFs, Programaciones, Producido vs programado  
**Nota:** Las alertas de producción (alert_kpi_widget) ya excluyen subcontratadas correctamente desde la sesión anterior.  
**Solución:** Agregar dominio `['|', ('bom_id', '=', False), ('bom_id.type', '!=', 'subcontract')]` en `get_mo_widget_data` y en los campos computados de KPI de OFs.

---

## Panel de Ventas

### V1 — Etiquetas "Arriba 10/20/50" deben ser "Top 10/20/50"
**Archivos:** `static/src/xml/sales_chart_widget.xml`  
**Problema:** Los botones del selector de cantidad de productos muestran "Arriba 10", "Arriba 20", "Arriba 50". Deben decir "Top 10", "Top 20", "Top 50".

---

### V2 — Gráfico de productos más vendidos: fuente de datos solo entrega física
**Archivos:** `models/mrp_planner_dashboard.py` → `get_sales_chart_data`  
**Problema:** La cantidad vendida se calcula sumando `stock.move.line.quantity` con `state='done'` y `picking_type_code='outgoing'` (entregas físicas completadas). El importe se calcula como `qty × list_price`, no el precio real de venta.  
**Solución propuesta:** Agregar un filtro para elegir la fuente: órdenes de venta confirmadas (`sale.order.line`), solicitudes de cotización, o entregas (comportamiento actual). Implica cambiar el modelo fuente según la selección.
La demanda se debe calcular sumando las cantidades pedidas (en las ordenes de venta y cotizaciones). La cantidad pedida deberia verse en sale.order.line, el campo product_uom_qty. y luego yo poder filtrar en las ordenes de venta y cotizaciones o bien ambas.

---

### V3 — KPI de forecast sin tooltips con fórmula de cálculo
**Archivos:** `static/src/xml/forecast_widget.xml` (o el template del widget de forecast)  
**Problema:** Las tarjetas KPI del widget de forecast (Cobertura %, Productos en riesgo, Tasa de servicio, Precisión forecast, etc.) no tienen tooltip explicando cómo se calcula cada uno.  
**Fórmulas para documentar en tooltip:**
- Cobertura %: OFs planificadas ÷ Forecast × 100
- Gap: OFs planificadas − Forecast
- Productos en riesgo: productos con cobertura < umbral de aviso (configurable)
- Tasa de servicio: Entregado ÷ Demanda OV × 100
- Precisión forecast: según fórmula configurada (Simple / MAPE / WAPE / WMAPE / Sesgo)

---

## Ajustes

### A1 — Estados de OF en "Quiebres de stock y Forecast" sin tooltips
**Archivos:** `views/res_config_settings_views.xml`, `models/mrp_reschedule_config.py`  
**Problema:** Los toggles Borrador / Confirmada / En progreso / Por cerrar / Terminada no tienen `help`. El usuario no sabe qué afecta activar/desactivar cada uno.  
**Qué hace:** Controla qué estados de OF se consideran como "producción planificada" al calcular la cobertura en el widget de Forecast (OFs ÷ Forecast). No afecta el widget de quiebres de stock.  
**Solución:** Agregar `help` a cada campo `forecast_mo_state_*` y al grupo en la vista.

---

### A2 — Criterio de prioridad sin descripción por opción
**Archivos:** `views/res_config_settings_views.xml`  
**Problema:** Las tres opciones del radio (Orden cronológico, Más cortas primero SPT, Secuencia manual) no tienen descripción individual explicando el comportamiento.  
**Significado de cada opción:**
- *Orden cronológico*: las OFs con fecha de inicio más próxima tienen prioridad en el WC
- *Más cortas primero (SPT)*: minimiza el tiempo de espera promedio; favorece OFs de menor duración
- *Secuencia manual en el wizard*: el usuario arrastra y ordena las OFs manualmente en el wizard de reprogramación  
**Solución:** Agregar tooltips individuales a cada opción del radio field, o agregar texto descriptivo en la vista.

---

### A3 — Fórmulas de precisión forecast: labels demasiado largos, sin tooltips
**Archivos:** `models/mrp_reschedule_config.py` → campo `forecast_acc_formula`, `views/res_config_settings_views.xml`  
**Problema:** Los labels de las opciones del radio incluyen la fórmula como texto (ej. "MAPE — promedio de errores porcentuales por período"), lo que resulta en texto largo en la UI. Deberían ser labels cortos con la fórmula explicada en un tooltip.  
**Solución:** Acortar labels a solo el nombre (MAPE, WAPE, WMAPE, Sesgo, Simple) y mover la descripción a un atributo `help` o tooltip por opción.
