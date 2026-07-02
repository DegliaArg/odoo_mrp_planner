# Documentación de fórmulas de cálculo

## 1. Alertas — generación y severidad

### 1.1 OFs atrasadas
Se genera una alerta cuando una OF activa (Confirmada, En progreso o Por cerrar) tiene su fecha de fin planificada en el pasado. El sistema corre este chequeo periódicamente según el intervalo configurado en ajustes.

**Días de atraso:**
```
días_atraso = max(0, (hoy - mrp.production.date_finished).days)
```
Diferencia en días entre hoy y la fecha de fin planificada de la OF. Si el resultado es negativo se muestra como cero.

**Severidad:**
```
severity = 'critical' si días_atraso >= mrp.reschedule.config.alert_mo_critical_days (def: 3)
severity = 'warning'  si días_atraso <  mrp.reschedule.config.alert_mo_critical_days
```

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.2 OFs por vencer
Se genera una alerta cuando una OF activa tiene su fecha de fin planificada dentro del horizonte de aviso configurado en ajustes (default: próximos 7 días), pero aún no está vencida.

**Días hasta el vencimiento:**
```
días_hasta_vence = max(0, (mrp.production.date_finished - hoy).days)
ventana          = hoy + timedelta(days=mrp.reschedule.config.alert_mo_warning_days)  (def: 7)
```
Condición: `hoy < date_finished <= ventana`.

**Severidad:** siempre amarilla.

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.3 Cantidad diferente
Se genera una alerta cuando una OF recién cerrada (estado Terminada) produjo una cantidad que difiere de la planificada más allá de la tolerancia configurada.

**Cálculo:**
```
actual_qty  = Σ stock.move.quantity  donde move.state='done'
                                          y move.product_id = mrp.production.product_id
                                          (move in mrp.production.move_finished_ids)
delta       = |actual_qty - mrp.production.product_qty| / mrp.production.product_qty
tolerancia  = mrp.reschedule.config.qty_tolerance_pct / 100  (def: 0.05)
```
Si `delta > tolerancia` se genera la alerta.  
**Severidad:** roja si `actual_qty < product_qty` (producción insuficiente), amarilla si se excedió.

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.4 OFs canceladas
Se genera automáticamente cuando una OF pasa al estado Cancelada. No se resuelve sola — requiere acción manual del usuario.

**Severidad:** siempre amarilla.

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.5 OCs vencidas
Se genera cuando una OC aprobada tiene su fecha de entrega estimada en el pasado.

**Fórmula:**
```
días_atraso = max(0, (hoy - purchase.order.date_planned).days)
severity    = 'critical' si días_atraso >= mrp.reschedule.config.alert_po_critical_days (def: 5)
severity    = 'warning'  si días_atraso <  mrp.reschedule.config.alert_po_critical_days
```
La fecha de referencia es `date_planned` (entrega estimada), no la fecha de emisión de la OC.

---

### 1.6 OCs por vencer
Se genera cuando una OC aprobada y no totalmente recibida tiene su fecha de entrega estimada dentro del horizonte de aviso configurado (default: próximos 10 días), pero aún no está vencida.

**Ventana:**
```
future_limit = hoy + timedelta(days=mrp.reschedule.config.alert_po_warning_days)  (def: 10)
Condición: hoy < purchase.order.date_planned <= future_limit
```

**Severidad:** siempre amarilla.

---

### 1.7 Recepciones atrasadas
Se genera cuando una recepción pendiente tiene su fecha programada en el pasado.

**Fórmula:**
```
días_atraso = max(0, (hoy - stock.picking.scheduled_date).days)
severity    = 'critical' si días_atraso >= mrp.reschedule.config.alert_receipt_critical_days (def: 3)
severity    = 'warning'  si días_atraso <  mrp.reschedule.config.alert_receipt_critical_days
```

**Problema conocido (C4):** actualmente incluye movimientos internos además de recepciones de OCs.

---

### 1.8 Días de atraso por tipo de alerta (campo calculado)
El campo "días de atraso" se recalcula en tiempo real contra la fecha de referencia de cada tipo de alerta:

| Tipo de alerta                                            | Fecha de referencia                |
|-----------------------------------------------------------|------------------------------------|
| OFs atrasadas / por vencer / cant. diferente / canceladas | Fecha de fin planificada de la OF  |
| OCs vencidas / por vencer / canceladas                    | Fecha de entrega estimada de la OC |
| Recepciones atrasadas                                     | Fecha programada de la recepción   |

El valor siempre es cero o positivo — nunca negativo.

---

## 2. Panel de Producción — KPIs del widget OFs

| KPI              | Qué cuenta                                             |
|------------------|--------------------------------------------------------|
| Activas          | OFs que no están en estado Terminada ni Cancelada      |
| En progreso      | OFs activas en estado En progreso o Por cerrar         |
| Atrasadas        | OFs activas cuya fecha de fin planificada ya pasó      |
| Para reprogramar | OFs activas marcadas como "necesita reprogramación"    |
| Finalizadas      | OFs en estado Terminada                                |
| Por cerrar       | OFs activas en estado Por cerrar                       |

**Problema conocido (P1):** ninguno de estos conteos excluye OFs de subcontratación.

---

## 3. Panel de Producción — KPIs de alertas (tarjetas)

Cada tarjeta cuenta las alertas no resueltas de ese tipo, excluyendo las que corresponden a OFs con LdM de tipo Subcontratación. Si se aplica el filtro de estados, solo se cuentan alertas cuya OF esté en los estados seleccionados.

| Tarjeta          | Qué cuenta                                          |
|------------------|-----------------------------------------------------|
| OFs atrasadas    | Alertas activas de tipo "OF atrasada"               |
| OFs por vencer   | Alertas activas de tipo "OF por vencer"             |
| Cant. diferentes | Alertas activas de tipo "Cantidad diferente"        |
| OFs canceladas   | Alertas activas de tipo "OF cancelada"              |
| Badge críticas   | Alertas activas con severidad roja (cualquier tipo) |

---

## 4. Panel de Producción — Carga de centros de trabajo

### Horas disponibles
```
horas_disponibles = resource.calendar.get_work_hours_count(inicio, fin)
                  × (mrp.workcenter.time_efficiency / 100)
```
Se obtienen del calendario laboral (`resource_calendar_id`) del centro de trabajo para el período seleccionado, multiplicadas por su eficiencia. Si el calendario no puede calcularse, se estima proporcionalmente a partir de las horas semanales de asistencia.

### Horas ejecutadas
```
horas_ejecutadas = Σ _overlap_hours(wo, rango)
                     donde mrp.workorder.state = 'done'
```
Suma de las horas de las operaciones (work orders) ya terminadas que se solapan con el período. El solapamiento parcial se pondera por proporción:
```
proporción = (min(wo.date_finished, rango_fin) - max(wo.date_start, rango_inicio)).total_seconds()
           / (wo.date_finished - wo.date_start).total_seconds()
horas_wo   = (mrp.workorder.duration_expected / 60) × proporción
```

### Horas pendientes
```
horas_pendientes = Σ _overlap_hours(wo, rango)
                     donde mrp.workorder.state not in ('done', 'cancel')
```
Mismo cálculo de solapamiento que las ejecutadas.

### Tiempo libre
```
tiempo_libre = max(0, horas_disponibles - horas_ejecutadas - horas_pendientes)
```

### Carga del centro (%)
```
carga_pct = (horas_ejecutadas + horas_pendientes) / horas_disponibles × 100
```

**Colores:**
```
verde    si carga_pct < 70%
amarillo si 70% ≤ carga_pct < 90%
rojo     si carga_pct ≥ 90%
```

---

## 5. Panel de Producción — Producido vs programado

Para cada producto, se compara la cantidad total de OFs planificadas contra la cantidad realmente producida en el período:

```
planificado    = Σ mrp.production.product_qty           (OFs del período)
producido      = Σ mrp.production.qty_produced          (ídem)
cumplimiento % = round(producido / planificado × 100, 1)  si planificado > 0
```

**Colores del % de cumplimiento:**
```
verde    si cumplimiento % ≥ 90%
amarillo si 50% ≤ cumplimiento % < 90%
rojo     si cumplimiento % < 50%
```

---

## 6. Panel de Compras — KPIs del widget OCs

| KPI                | Fórmula                                                                                                                   |
|--------------------|---------------------------------------------------------------------------------------------------------------------------|
| Cotizaciones (RFQ) | `count(purchase.order)` donde `state in ('draft','sent')`                                                                 |
| Por aprobar        | `count(purchase.order)` donde `state = 'to_approve'`                                                                     |
| Total aprobadas    | `count(purchase.order)` donde `state in ('purchase','done')` y `receipt_status != 'full'`                                |
| A tiempo           | Del total aprobadas: `date_planned > hoy`                                                                                 |
| Vencidas           | Del total aprobadas: `date_planned ≤ hoy`                                                                                 |
| Críticas           | De las vencidas: `(hoy - date_planned).days >= mrp.reschedule.config.alert_po_critical_days` (def: 5 días)               |

**Problema conocido (C1):** el filtro de fecha filtra por `date_planned` (entrega estimada), no por fecha de emisión de la OC.

---

## 7. Panel de Compras — KPIs de alertas

Cada tarjeta cuenta las alertas no resueltas del tipo correspondiente:

| Tarjeta        | Qué cuenta                                                               |
|----------------|--------------------------------------------------------------------------|
| OCs vencidas   | Alertas activas de tipo "OC vencida"                                     |
| OCs por vencer | Alertas activas de tipo "OC por vencer"                                  |
| OCs canceladas | Siempre 0 — el tipo de alerta nunca se genera (ver C3)                   |
| Recepciones    | Alertas activas de tipo "Recepción atrasada" — incluye internas (ver C4) |

---

## 8. Panel de Compras — Disponibilidad de recepciones y entregas

Cada recepción o entrega muestra su estado de disponibilidad de materiales:

| Estado        | Criterio (campo `stock.picking.state`)                                                                        |
|---------------|---------------------------------------------------------------------------------------------------------------|
| Disponible    | `state = 'assigned'` y todas las líneas tienen `qty_disponible ≥ product_uom_qty - 0.001`                    |
| Parcialmente  | `state = 'assigned'` con alguna línea con `qty_disponible < product_uom_qty - 0.001`; o `state='confirmed'` con alguna línea reservada |
| No disponible | `state = 'confirmed'` sin ninguna línea reservada, o `state = 'waiting'`                                      |

```
qty_disponible = max(stock.move.reserved_availability, stock.move.quantity_done)
días_retraso   = max(0, (hoy - stock.picking.scheduled_date).days)
```

---

## 9. Panel de Ventas — Gráfico de productos más vendidos

### Cantidad vendida
```
cantidad_vendida = Σ stock.move.line.quantity
                   donde picking_type_code = 'outgoing'
                         y state = 'done'
                         y product_id.sale_ok = True
                         y date ∈ [hoy - N meses, hoy]
# Agrupado por product_id.product_tmpl_id (suma variantes del mismo producto base)
```
El período N es una ventana deslizante: 1, 3, 6 o 12 meses.

### Importe (aproximado)
```
importe = cantidad_vendida × product.template.list_price
```
**No refleja el precio real de la venta** — es una aproximación basada en el precio de lista vigente.

**Problema conocido (V2):** no existe opción para cambiar la fuente de datos a líneas de órdenes de venta. Actualmente solo usa entregas físicas completadas.

---

## 10. Forecast — KPIs globales

| KPI                 | Fórmula                                                                                                      |
|---------------------|--------------------------------------------------------------------------------------------------------------|
| Forecast total      | `Σ mrp.forecast.line.forecast_qty` del período                                                               |
| OFs planificadas    | `Σ mrp.production.product_qty` donde `state` ∈ estados habilitados y `date_finished` en el período          |
| Gap OFs             | `OFs_planificadas - forecast_total` (negativo = déficit de producción)                                       |
| Cobertura %         | `OFs_planificadas / forecast_total × 100`                                                                    |
| Productos en riesgo | `count(productos)` donde `cobertura_% < mrp.reschedule.config.forecast_warning_pct` (def: 70%)              |
| Entregado total     | `Σ stock.move.quantity` donde `picking_type_code='outgoing'` y `state='done'`, para productos con forecast   |
| Demanda OV          | `Σ sale.order.line.product_uom_qty` donde `order.state in ('sale','done')` y fecha en el período             |
| Tasa de servicio    | `entregado_total / demanda_OV × 100`                                                                         |
| Gap de demanda      | `(demanda_OV - forecast_total) / forecast_total × 100` (positivo = demanda superó el forecast)              |
| Precisión forecast  | Según la fórmula configurada en `mrp.reschedule.config.forecast_acc_formula` (ver sección 11)                |

**Colores de Tasa de servicio:**
```
verde    si tasa_servicio ≥ 95%
amarillo si 80% ≤ tasa_servicio < 95%
rojo     si tasa_servicio < 80%
```

**Colores de Gap de demanda** (`|demand_gap_pct|`):
```
verde    si |gap| ≤ 10%   (demanda alineada con forecast)
amarillo si |gap| ≤ 25%   (desvío moderado)
rojo     si |gap| > 25%   (desvío significativo)
```

**Colores de Gap de OFs** (brecha entre cobertura y forecast):
```
verde    si gap_ofs ≥ 0%    (OFs cubren o superan el forecast)
amarillo si -10% ≤ gap_ofs < 0%  (leve déficit de cobertura)
rojo     si gap_ofs < -10%  (déficit significativo)
```

---

## 11. Forecast — Fórmulas de precisión

> **Nota importante:** todas las fórmulas usan **demanda SO** (`so_demand`) como referencia real, no las unidades entregadas físicamente. La demanda SO es la suma de `sale.order.line.product_uom_qty` de OVs confirmadas o cerradas en el período.

En todas las fórmulas se trabaja con estos valores por período y producto:
- **Forecast** (`forecast_qty`): `mrp.forecast.line.forecast_qty` del mes
- **Demanda SO** (`so_demand`): `Σ sale.order.line.product_uom_qty` del período
- **Error** (`abs_err`): `|so_demand - forecast_qty|`

### Simple
```
precisión_celda = so_demand / forecast_qty × 100    (si forecast_qty > 0)
precisión_total = Σso_demand / Σforecast_qty × 100
```
Un valor de 100 % significa que la demanda real coincidió exactamente con el forecast. Por encima de 100 % indica que la demanda superó el forecast.

### MAPE — Error porcentual absoluto medio
```
precisión_período = max(0, 100 - |abs_err / so_demand| × 100)   (solo si so_demand > 0)
precisión_total   = Σprecisión_período / count(períodos con so_demand > 0)
```
Sensible a períodos de bajo volumen. Solo se incluyen períodos donde `so_demand > 0`.

### WAPE — Error porcentual absoluto ponderado por demanda real
```
precisión_total = max(0, 100 - Σabs_err / Σso_demand × 100)
```
Pondera más los períodos de mayor volumen real de demanda SO. Robusto ante períodos con forecast en cero.

### WMAPE — Error porcentual absoluto ponderado por forecast
```
precisión_total = max(0, 100 - Σabs_err / Σforecast_qty × 100)
```
Pondera más los períodos de mayor volumen planificado. Estándar en supply chain.

### Sesgo (Bias)
```
sesgo_celda  = (so_demand - forecast_qty) / forecast_qty × 100   (si forecast_qty > 0)
sesgo_total  = (Σso_demand - Σforecast_qty) / Σforecast_qty × 100
```
Positivo significa que la demanda sistemáticamente superó el forecast (forecast conservador); negativo indica que el forecast fue optimista.

### Colores de precisión
```
# Simple, MAPE, WAPE, WMAPE:
verde    si precisión ≥ 90%
amarillo si 70% ≤ precisión < 90%
rojo     si precisión < 70%

# Sesgo (Bias):
verde    si |sesgo| ≤ 10%
amarillo si 10% < |sesgo| ≤ 20%
rojo     si |sesgo| > 20%
```

---

## 12. Forecast — Rotación de inventario

```
entregado_total    = Σ stock.move.quantity  (salidas completadas del período)
promedio_mensual   = entregado_total / n_meses

stock_actual       = Σ stock.quant.quantity  (ubicaciones internas, filtrado por almacén si se configuró)

rotación_días      = round(stock_actual / promedio_mensual × 30)   si promedio_mensual > 0
rotación_meses     = round(stock_actual / promedio_mensual, 1)     si promedio_mensual > 0
```

La unidad de visualización se configura en `mrp.reschedule.config.forecast_rotation_unit` ('days' o 'months').

**Colores:**

| Unidad | Verde      | Amarillo         | Sin color (gris) |
|--------|------------|------------------|------------------|
| Días   | ≤ 90 días  | 91–180 días      | > 180 días       |
| Meses  | ≤ 3 meses  | 4–6 meses        | > 6 meses        |

El umbral amarillo es exactamente el doble del umbral verde (umbral verde × 2). Por encima del doble se muestra en gris (sin color destacado).

---

## 13. Forecast — Cobertura por celda (mes × producto)

```
cobertura_pct = round(mo_qty / forecast_qty × 100, 1)   si forecast_qty > 0

donde:
  mo_qty       = Σ mrp.production.product_qty  (OFs del mes con estados habilitados)
  forecast_qty = mrp.forecast.line.forecast_qty  (línea del mes para ese producto)
```

**Colores de celda:**
```
verde    si cobertura_pct ≥ 100%
amarillo si cobertura_pct ≥ mrp.reschedule.config.forecast_warning_pct  (def: 70%)
rojo     si cobertura_pct <  mrp.reschedule.config.forecast_warning_pct
```
Solo el umbral de aviso (`forecast_warning_pct`) determina el color. El campo `forecast_critical_pct` existe en la configuración pero no se usa en el coloreado de celdas.

---

## 14. Análisis de proveedores

| Métrica                   | Fórmula                                                                                                                             |
|---------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| % A tiempo                | `on_time_count / pick_count × 100` donde `on_time` = pickings con `date_done ≤ scheduled_date`                                    |
| Retraso promedio (días)   | `Σ(date_done - scheduled_date).days / delay_count` solo pickings donde `date_done > scheduled_date`                               |
| % Recepciones completas   | `complete_count / pick_count × 100` donde `complete` = recepciones que NO generaron backorder                                      |
| Lead time promedio (días) | `Σ(stock.picking.date_done - purchase.order.date_approve).days / count` — desde la **aprobación** de la OC hasta el cierre de la recepción |
| Variación de precio (%)   | `Σ((price_unit - standard_price) / standard_price × 100) / count` — promedio **firmado** por línea de OC vs costo estándar del producto |

> **Nota variación de precio:** el dashboard muestra el promedio firmado (puede ser negativo si el precio pagado es inferior al costo estándar). La clasificación ABC de proveedores usa el valor absoluto de esta variación.

### Campos Odoo involucrados
- `stock.picking`: `date_done`, `scheduled_date`, `backorder_id`
- `purchase.order`: `date_approve`, `partner_id`
- `purchase.order.line`: `price_unit`
- `product.product`: `standard_price`

### Colores (umbrales configurables en `mrp.reschedule.config`)

| Métrica          | Verde                                                                             | Amarillo                                                                         | Rojo                           |
|------------------|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------|--------------------------------|
| % A tiempo       | `≥ sup_on_time_green_pct` (def: 90%)                                              | `≥ sup_on_time_yellow_pct` (def: 70%)                                            | `< sup_on_time_yellow_pct`     |
| Retraso promedio | `≤ sup_delay_green_days` (def: 1 día)                                             | `≤ sup_delay_yellow_days` (def: 3 días)                                          | `> sup_delay_yellow_days`      |
| % Completas      | `≥ sup_complete_green_pct` (def: 95%)                                             | `≥ sup_complete_yellow_pct` (def: 80%)                                           | `< sup_complete_yellow_pct`    |
| Var. precio      | `|var| ≤ sup_price_var_green_pct` (def: 3%)                                       | `|var| ≤ sup_price_var_yellow_pct` (def: 10%)                                    | `|var| > sup_price_var_yellow_pct` |

---

## 15. Categorías de venta (A / B / C / D / E)

La asignación usa como fuente `stock.move.line` de tipo `outgoing` y `state='done'` del período configurado (`mrp.reschedule.config.sale_cat_lookback_months`, def: 3 meses). El resultado se guarda en `product.template.x_sale_category`.

### Modo Rotación de inventario (`sale_cat_mode = 'automatic'`)
```
del_by_tmpl     = Σ stock.move.line.quantity  (salidas completadas del período, por product_template)
avg_monthly     = del_by_tmpl / sale_cat_lookback_months
stock_actual    = Σ stock.quant.quantity  (ubicaciones internas, por product_template)

rotación_días   = round(stock_actual / avg_monthly × 30)   si avg_monthly > 0, sino 999

A  si rotación_días ≤ sale_cat_a_days  (def: 30)
B  si rotación_días ≤ sale_cat_b_days  (def: 60)
C  si rotación_días ≤ sale_cat_c_days  (def: 90)
D  si rotación_días ≤ sale_cat_d_days  (def: 180)
E  si avg_monthly <= 0 o rotación_días > sale_cat_d_days
```

### Modo Demanda (`sale_cat_mode = 'demand'`)
```
avg_monthly = del_by_tmpl / sale_cat_lookback_months

A  si avg_monthly ≥ sale_cat_demand_a_qty  (def: 100 u/mes)
B  si avg_monthly ≥ sale_cat_demand_b_qty  (def: 50 u/mes)
C  si avg_monthly ≥ sale_cat_demand_c_qty  (def: 20 u/mes)
D  si avg_monthly ≥ sale_cat_demand_d_qty  (def: 5 u/mes)
E  en otro caso
```

### Modo Participación acumulada — Pareto (`sale_cat_mode = 'share'`)
```
# Métrica por producto (sale_cat_share_metric):
valor = del_by_tmpl × product.template.list_price   si métrica = 'pxq'
valor = del_by_tmpl                                  si métrica = 'units'

total       = Σvalor (todos los productos)
acumulado   = 0

# Ordenados de mayor a menor valor:
acumulado  += valor / total
A  si acumulado ≤ sale_cat_share_a_pct / 100  (def: 50%)
B  si acumulado ≤ sale_cat_share_b_pct / 100  (def: 80%)
C  si acumulado ≤ sale_cat_share_c_pct / 100  (def: 95%)
D  si acumulado ≤ sale_cat_share_d_pct / 100  (def: 99%)
E  en otro caso
```

---

## 16. Reprogramación en cascada

### Duración de una OF
```
# 1. Si hay work orders con tiempo esperado cargado:
duración_horas = Σ mrp.workorder.duration_expected / 60

# 2. Si no, pero hay fechas de inicio y fin:
duración_horas = (mrp.production.date_finished - mrp.production.date_start).total_seconds() / 3600

# 3. Fallback:
duración_horas = 8.0
```

### Delta de reprogramación
```
delta_secs = (mrp.reschedule.plan.line.new_date_finish
            - mrp.reschedule.plan.line.current_date_finish).total_seconds()

signo = '+' si delta_secs >= 0 (se adelanta), '-' si negativo (se atrasa)
días  = int(|delta_secs| / 3600 // 24)
horas = int(|delta_secs| / 3600 % 24)
# Formato: "+2d 3h" o "-1d 0h"
```

### Secuenciación de operaciones por centro de trabajo
Cada operación se programa a partir del momento en que el centro de trabajo queda libre (último fin registrado para ese CT, o la fecha base de la reprogramación si el CT aún no tiene asignaciones). La siguiente operación no puede empezar antes de que el CT esté disponible.

Si se especifica un ajuste de duración total para la OF, cada operación se escala proporcionalmente:
```
escala = duración_total_ajustada / Σ(mrp.workorder.duration_expected)
duración_wo_ajustada = mrp.workorder.duration_expected × escala
```

---

## 17. Quiebres de stock

```
stock_actual  = Σ stock.quant.quantity  en ubicación configurada
                (mrp.reschedule.config.stock_location_id → o todas las internas si no se configuró)

quiebre       = stock_actual < stock.warehouse.orderpoint.product_min_qty
```

| KPI         | Qué cuenta                                                                                       |
|-------------|--------------------------------------------------------------------------------------------------|
| Total       | Todos los productos relevantes (con `mrp.forecast.line` o con punto de reorden configurado)     |
| Con quiebre | Productos con `stock.warehouse.orderpoint` donde `stock_actual < product_min_qty`               |
| OK          | Productos con `stock.warehouse.orderpoint` donde `stock_actual ≥ product_min_qty`               |
| Sin mínimo  | Productos sin `stock.warehouse.orderpoint` configurado                                           |

---

## 18. Categorías de proveedor — Métodos automáticos

El campo `res.partner.x_supplier_category` se calcula con el método elegido en `mrp.reschedule.config.supplier_cat_method`. El período de análisis es siempre los últimos 12 meses (`date.today() - 365 días`).

Los umbrales Pareto aplican a todos los métodos excepto RFM y Manual:

```
A  si acumulado ≤ abc_pct_a / 100  (def: 20%)
B  si acumulado ≤ abc_pct_b / 100  (def: 50%)
C  si acumulado ≤ abc_pct_c / 100  (def: 80%)
D  si acumulado ≤ abc_pct_d / 100  (def: 95%)
E  en otro caso
```

### Método ABC por volumen (`abc_volume`)
```
valor_proveedor = Σ purchase.order.amount_total
                  donde state in ('purchase','done') y date_order >= hace 12 meses
# Luego Pareto acumulado (mayor volumen = A)
```

### Método ABC por frecuencia (`abc_frequency`)
```
valor_proveedor = count(purchase.order)
                  donde state in ('purchase','done') y date_order >= hace 12 meses
# Luego Pareto acumulado (mayor frecuencia = A)
```

### Método ABC por RFM (`abc_rfm`)
```
R = (hoy - max(purchase.order.date_order)).days   (recencia: días desde última OC)
F = count(purchase.order)                          (frecuencia: OCs en el año)
M = Σ purchase.order.amount_total                  (monetario: importe total)

# Scoring R (1–3):
r_score = 3 si R < 30 días
r_score = 2 si 30 ≤ R < 90 días
r_score = 1 si R ≥ 90 días

# Scoring F (1–3):
f_score = 3 si F > 10
f_score = 2 si 3 ≤ F ≤ 10
f_score = 1 si F < 3

# Scoring M (1–3, relativo al grupo):
m_score = 3 si M ≥ percentil_66(M del grupo)
m_score = 2 si M ≥ percentil_33(M del grupo)
m_score = 1 en otro caso

# Suma y clasificación:
total_score = r_score + f_score + m_score  (rango: 3–9)
A  si total_score ≥ 8
B  si total_score ≥ 6
C  si total_score ≥ 4
D  si total_score = 3
E  si no hay datos (sin OCs en el período)
```

### Método ABC por % entrega a tiempo (`abc_delivery_pct`)
```
on_time_pct = on_time_count / pick_count × 100
  donde on_time = stock.picking  con state='done', picking_type_code='incoming'
                  y date_done ≤ scheduled_date
# Luego Pareto acumulado (mayor % a tiempo = A)
```

### Método ABC por variación de precio (`abc_price_var`)
```
var_por_línea = |purchase.order.line.price_unit - product.product.standard_price|
                / product.product.standard_price × 100
avg_var = Σvar_por_línea / count(líneas con standard_price > 0 y price_unit > 0)
# Luego Pareto INVERTIDO (menor variación = A)
```
El Pareto invertido ordena de menor a mayor y asigna A a los que están en el percentil más bajo (mejor desempeño).

### Método ABC por calidad — diferencia de cantidad (`abc_quality_qty`)
```
qty_exact_pct = exact_count / total_count × 100
  donde exact = stock.move con |quantity - product_uom_qty| < 0.001
# Luego Pareto acumulado (mayor % exactitud = A)
```

### Método ABC por calidad — devoluciones (`abc_quality_returns`)
```
returns_count = count(stock.picking) donde return_id != False
                y return_id.purchase_id.partner_id = proveedor
# Luego Pareto INVERTIDO (menos devoluciones = A)
```

### Método ABC por calidad — combinado (`abc_quality_combo`)
```
on_time_pct = on_time_count / total_count × 100   (recepciones a tiempo)
qty_pct     = exact_count   / total_count × 100   (cantidad exacta)
avg_score   = mean([on_time_pct, qty_pct])         (promedio simple de los que tienen datos)
# Luego Pareto acumulado (mayor promedio = A)
```

---

## 19. Categorías de cliente — Métodos automáticos

El campo `res.partner.x_customer_category` se calcula con el método elegido en `mrp.reschedule.config.customer_cat_method`. El período de análisis es los últimos 12 meses. Los umbrales Pareto son los mismos que para proveedores (`abc_pct_a/b/c/d`).

### Método ABC por volumen (`abc_volume`)
```
valor_cliente = Σ sale.order.amount_total
                donde state in ('sale','done') y date_order >= hace 12 meses
# Luego Pareto acumulado (mayor volumen = A)
```

### Método ABC por frecuencia (`abc_frequency`)
```
valor_cliente = count(sale.order)
                donde state in ('sale','done') y date_order >= hace 12 meses
# Luego Pareto acumulado (mayor frecuencia = A)
```

### Método ABC por RFM (`abc_rfm`)
Misma lógica que para proveedores, pero usando `sale.order` en lugar de `purchase.order`:
```
R = (hoy - max(sale.order.date_order)).days
F = count(sale.order)
M = Σ sale.order.amount_total

# Scoring idéntico al de proveedores
# Resultado: A (8–9 pts), B (6–7), C (4–5), D (3), E (sin datos)
```
