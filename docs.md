# Documentación de fórmulas de cálculo

---

## Panel de Producción

### Alertas de producción

#### Generación de alertas de OFs

**OFs atrasadas** — se genera cuando una OF activa (Confirmada, En progreso o Por cerrar) tiene su fecha de fin planificada en el pasado.

```
días_atraso = max(0, (hoy - mrp.production.date_finished).days)

severity = 'critical'  si días_atraso >= mrp.reschedule.config.alert_mo_critical_days  (def: 3)
severity = 'warning'   si días_atraso <  mrp.reschedule.config.alert_mo_critical_days
```

**OFs por vencer** — se genera cuando una OF activa tiene su fecha de fin dentro del horizonte de aviso, pero aún no está vencida.

```
ventana = hoy + timedelta(days=mrp.reschedule.config.alert_mo_warning_days)  (def: 7)
Condición: hoy < date_finished <= ventana

días_hasta_vence = max(0, (mrp.production.date_finished - hoy).days)
severity = 'warning'  (siempre amarilla)
```

**Cantidad diferente** — se genera cuando una OF recién cerrada produjo una cantidad que difiere de la planificada más allá de la tolerancia.

```
actual_qty = Σ stock.move.quantity  donde move.state='done'
                                         y move.product_id = mrp.production.product_id
                                         (move in mrp.production.move_finished_ids)

delta      = |actual_qty - mrp.production.product_qty| / mrp.production.product_qty
tolerancia = mrp.reschedule.config.qty_tolerance_pct / 100  (def: 0.05)
```

Si `delta > tolerancia` se genera la alerta.
Severidad: roja si `actual_qty < product_qty` (insuficiente), amarilla si se excedió.

**OFs canceladas** — se genera automáticamente cuando una OF pasa a estado Cancelada. No se auto-resuelve, requiere acción manual.

```
severity = 'warning'  (siempre amarilla)
```

> Ninguna alerta de OF se genera para OFs cuya LdM sea de tipo Subcontratación.

---

#### Tarjetas KPI de alertas de producción

Cada tarjeta cuenta alertas no resueltas (`resolved = False`), excluyendo OFs con LdM de subcontratación. Si se aplica filtro de estados, solo se cuentan alertas cuya OF esté en los estados seleccionados.

| Tarjeta          | Qué cuenta                                              |
|------------------|---------------------------------------------------------|
| OFs atrasadas    | `alert_type = 'mo_delayed'`                             |
| OFs por vencer   | `alert_type = 'mo_upcoming'`                            |
| Cant. diferentes | `alert_type = 'qty_mismatch'`                           |
| OFs canceladas   | `alert_type = 'mo_cancelled'`                           |
| Badge críticas   | `severity = 'critical'` (cualquier tipo de alerta)      |

---

#### Tabla de alertas activas — columnas calculadas

| Columna           | Fórmula / Fuente                                                                                 |
|-------------------|--------------------------------------------------------------------------------------------------|
| Tipo              | `mrp.reschedule.alert.alert_type` (etiqueta traducida)                                           |
| Severidad         | `mrp.reschedule.alert.severity`                                                                  |
| OF / OC / Recep.  | Relación Many2one al registro origen según tipo                                                  |
| Producto          | `mrp.reschedule.alert.product_id.display_name`                                                   |
| Días de atraso    | Calculado en tiempo real según la tabla de fechas de referencia (ver abajo)                      |

**Fecha de referencia por tipo de alerta:**

| Tipo de alerta                                                  | Fecha de referencia                  |
|-----------------------------------------------------------------|--------------------------------------|
| OFs atrasadas / por vencer / cant. diferentes / canceladas      | `mrp.production.date_finished`       |
| OCs vencidas / por vencer / canceladas                          | `purchase.order.date_planned`        |
| Recepciones atrasadas                                           | `stock.picking.scheduled_date`       |

El campo `días_atraso` siempre es `max(0, (hoy - fecha_referencia).days)`.

---

### Órdenes de fabricación

#### Tarjetas KPI del widget OFs

| KPI              | Qué cuenta                                                    |
|------------------|---------------------------------------------------------------|
| Activas          | OFs `state not in ('done', 'cancel')`                         |
| En progreso      | OFs activas con `state in ('progress', 'to_close')`           |
| Atrasadas        | OFs activas con `date_finished < hoy`                         |
| Para reprogramar | OFs activas con `x_reschedule_needed = True`                  |
| Finalizadas      | OFs con `state = 'done'`                                      |
| Por cerrar       | OFs activas con `state = 'to_close'`                          |

---

#### Tabla de OFs — columnas calculadas

Las OFs se filtran por las que solapan el rango seleccionado:

```
domain = [
    ('state', 'not in', ('done', 'cancel')),
    ('date_start', '<=', último_día_rango),
    '|',
        ('date_finished', '>=', primer_día_rango),
        '&',
            ('date_finished', '=', False),
            ('date_start', '>=', primer_día_rango),
]
```

| Columna           | Fórmula                                                                                                  |
|-------------------|----------------------------------------------------------------------------------------------------------|
| Referencia        | `mrp.production.name`                                                                                    |
| Producto          | `mrp.production.product_id.display_name`                                                                 |
| Cantidad          | `mrp.production.product_qty`                                                                             |
| Fin planificado   | `mrp.production.date_finished`                                                                           |
| Estado            | `mrp.production.state` (etiqueta traducida)                                                              |
| Atrasada          | `bool(date_finished and date_finished < hoy)`                                                            |
| Reprogramar       | `bool(mrp.production.x_reschedule_needed)`                                                               |
| Entregas pend.    | `Σ stock.move.product_uom_qty` donde `move.state not in ('done','cancel')` y `picking_type_code='outgoing'` para ese `product_id` |

Si se aplica filtro por sector (tag de CT), solo se muestran OFs que tengan al menos una operación cuyo `workcenter_id` pertenezca al sector seleccionado.

---

#### Tabla de Solicitudes de Producción — columnas calculadas

| Columna           | Fórmula                                                                                                              |
|-------------------|----------------------------------------------------------------------------------------------------------------------|
| Referencia        | `mrp.production.request.name`                                                                                        |
| Disponible desde  | `mrp.production.request.start_from`                                                                                  |
| Estado            | `mrp.production.request.state`                                                                                       |
| OFs totales       | `len(request.item_ids.mapped('production_id').filtered(lambda m: m.id))`                                            |
| OFs terminadas    | OFs de la solicitud con `state = 'done'`                                                                             |
| OFs retrasadas    | OFs de la solicitud con `state not in ('done','cancel')` y `date_finished < hoy`                                    |

**KPIs del widget de solicitudes:**

```
total           = len(solicitudes confirmadas + calculadas)
activas         = len(solicitudes con state='confirmed')
calculadas      = len(solicitudes con state='calculated')
para_reprog     = len(solicitudes activas donde alguna OF tenga x_reschedule_needed=True)
ofs_retrasadas  = len(OFs de todas las solicitudes activas con date_finished < hoy)
```

---

#### Tabla Producido vs Programado — columnas calculadas

Agrupa todas las OFs (activas + terminadas) del período por `product_id`:

```
planificado    = Σ mrp.production.product_qty          (OFs del período)
producido      = Σ mrp.production.qty_produced         (ídem)
cumplimiento % = round(producido / planificado × 100, 1)  si planificado > 0, sino 0.0
```

**Colores del % de cumplimiento:**

```
verde    si cumplimiento % ≥ 90 %
amarillo si 50 % ≤ cumplimiento % < 90 %
rojo     si cumplimiento % < 50 %
```

**KPIs globales del comparativo:**

```
planificado_total = Σ planificado (todos los productos)
producido_total   = Σ producido
pct_global        = round(producido_total / planificado_total × 100, 1) si planificado_total > 0
ofs_terminadas    = count(OFs con state='done' en el período)
```

---

### Carga de centros de trabajo

#### Horas disponibles

```
horas_disponibles = resource.calendar.get_work_hours_count(inicio, fin, compute_leaves=False)
                  × (mrp.workcenter.time_efficiency / 100)
```

Se obtienen del calendario laboral del centro de trabajo para el período. Si el calendario no puede calcularse, se estima proporcionalmente desde las horas semanales de asistencia (fallback lineal).

#### Horas ejecutadas

```
horas_ejecutadas = Σ _overlap_hours(wo, rango)
                   donde mrp.workorder.state = 'done'
```

Solapamiento parcial ponderado por proporción:

```
ov_start    = max(wo.date_start, rango_inicio)
ov_end      = min(wo.date_finished, rango_fin)
proporción  = (ov_end - ov_start).total_seconds()
            / (wo.date_finished - wo.date_start).total_seconds()
horas_wo    = (mrp.workorder.duration_expected / 60) × proporción
```

Si la WO no tiene `date_finished`, se usa `duration_expected / 60` sin ponderar.

#### Horas pendientes

```
horas_pendientes = Σ _overlap_hours(wo, rango)
                   donde mrp.workorder.state not in ('done', 'cancel')
```

Mismo cálculo de solapamiento.

#### Tiempo libre y carga

```
tiempo_libre = max(0, horas_disponibles - horas_ejecutadas - horas_pendientes)
carga_pct    = (horas_ejecutadas + horas_pendientes) / horas_disponibles × 100
```

**Colores de carga:**

```
verde    si carga_pct < 70 %
amarillo si 70 % ≤ carga_pct < 90 %
rojo     si carga_pct ≥ 90 %
```

#### Series del gráfico (Chart.js stacked bar)

El gráfico muestra dos stacks por centro de trabajo:

| Serie         | Stack  | Valor                                   |
|---------------|--------|-----------------------------------------|
| Planificado   | plan   | `ejecutado + pendiente`                 |
| No planificado| plan   | `tiempo_libre`                          |
| Ejecutado     | real   | `horas_ejecutadas`                      |
| Pendiente     | real   | `horas_pendientes`                      |
| Tiempo libre  | real   | `tiempo_libre`                          |

Tooltip de ocupación real:

```
pct_ocupacion = round((ejecutado + pendiente) / disponible × 100)  si disponible > 0
```

#### Tabla de centros de trabajo — columnas calculadas

| Columna           | Fórmula                                            |
|-------------------|----------------------------------------------------|
| Centro de trabajo | `mrp.workcenter.name`                              |
| Disponible (h)    | `horas_disponibles` (calendario × eficiencia)      |
| Ejecutado (h)     | `horas_ejecutadas` (solapamiento WOs done)         |
| Pendiente (h)     | `horas_pendientes` (solapamiento WOs activas)      |
| Tiempo libre (h)  | `max(0, disponible - ejecutado - pendiente)`       |
| Carga %           | `(ejecutado + pendiente) / disponible × 100`       |
| Color             | Verde < 70 % / Amarillo < 90 % / Rojo ≥ 90 %      |

---

### Quiebres de stock

```
stock_actual = Σ stock.quant.quantity
               en stock.quant.location_id hijo de mrp.reschedule.config.stock_location_id
               con location_id.usage = 'internal'
               (si no hay ubicación configurada: todas las internas de la empresa)

mínimo       = stock.warehouse.orderpoint.product_min_qty
               donde route_id = ruta "Fabricación"
               (si hay varios orderpoints por producto, se toma el mayor)

quiebre      = stock_actual < (mínimo - 0.001)
```

**KPIs del widget:**

| KPI         | Qué cuenta                                                                                              |
|-------------|---------------------------------------------------------------------------------------------------------|
| Total       | Productos con `mrp.forecast.line` o con punto de reorden configurado                                   |
| Con quiebre | Productos con orderpoint donde `stock_actual < product_min_qty`                                         |
| OK          | Productos con orderpoint donde `stock_actual ≥ product_min_qty`                                         |
| Sin mínimo  | Productos sin `stock.warehouse.orderpoint` configurado (ruta Fabricación)                               |

**Tabla de quiebres — columnas calculadas:**

| Columna          | Fórmula / Fuente                                                                                      |
|------------------|-------------------------------------------------------------------------------------------------------|
| Artículo         | `product.template.display_name`                                                                       |
| Tipo             | `product.template.x_product_type_ids.mapped('name')` (concatenados)                                  |
| Stock actual     | `Σ stock.quant.quantity` en ubicaciones internas (batch read_group)                                   |
| Mínimo           | `stock.warehouse.orderpoint.product_min_qty` (mayor si hay varios)                                    |
| Diferencia       | `stock_actual - mínimo` (negativo indica quiebre)                                                     |
| Estado           | `'broken'` si `stock_actual < mínimo - 0.001`, `'ok'` si ≥ mínimo, `'no_min'` si sin orderpoint      |

**OFs activas por producto (acordeón al expandir):**

```
OFs mostradas = mrp.production donde product_id = producto
                y state in ('confirmed', 'progress', 'to_close')
                y no subcontratación
                ordenadas por date_finished asc, límite 50
```

---

### Reprogramación en cascada

#### Duración de una OF

```
# 1. Si hay work orders con tiempo esperado cargado:
duración_horas = Σ mrp.workorder.duration_expected / 60

# 2. Si no, pero hay fechas de inicio y fin:
duración_horas = (mrp.production.date_finished - mrp.production.date_start).total_seconds() / 3600

# 3. Fallback:
duración_horas = 8.0
```

#### Delta de reprogramación

```
delta_secs = (nueva_fecha_fin - fecha_fin_actual).total_seconds()

signo = '+' si delta_secs >= 0, '-' si negativo
días  = int(|delta_secs| / 3600 // 24)
horas = int(|delta_secs| / 3600 % 24)
# Formato mostrado: "+2d 3h" o "-1d 0h"
```

#### Secuenciación de operaciones por centro de trabajo

Cada operación se programa desde el momento en que el CT queda libre (último fin registrado para ese CT, o la fecha base si el CT aún no tiene asignaciones en el plan). Ninguna operación puede empezar antes de que el CT esté disponible.

Si se ajusta la duración total de la OF, cada operación se escala proporcionalmente:

```
escala               = duración_total_ajustada / Σ(mrp.workorder.duration_expected)
duración_wo_ajustada = mrp.workorder.duration_expected × escala
```

---

## Panel de Compras

### Alertas de compras

#### Generación de alertas de OCs y recepciones

**OCs vencidas** — se genera cuando una OC aprobada tiene su `date_planned` en el pasado.

```
días_atraso = max(0, (hoy - purchase.order.date_planned).days)

severity = 'critical'  si días_atraso >= mrp.reschedule.config.alert_po_critical_days  (def: 5)
severity = 'warning'   si días_atraso <  mrp.reschedule.config.alert_po_critical_days
```

**OCs por vencer** — se genera cuando una OC aprobada y no totalmente recibida tiene su `date_planned` dentro del horizonte de aviso.

```
future_limit = hoy + timedelta(days=mrp.reschedule.config.alert_po_warning_days)  (def: 10)
Condición: hoy < purchase.order.date_planned <= future_limit

severity = 'warning'  (siempre amarilla)
```

**Recepciones atrasadas** — se genera cuando una recepción pendiente tiene su `scheduled_date` en el pasado.

```
días_atraso = max(0, (hoy - stock.picking.scheduled_date).days)

severity = 'critical'  si días_atraso >= mrp.reschedule.config.alert_receipt_critical_days  (def: 3)
severity = 'warning'   si días_atraso <  mrp.reschedule.config.alert_receipt_critical_days
```

---

#### Tarjetas KPI de alertas de compras

Cada tarjeta cuenta alertas no resueltas (`resolved = False`) del tipo correspondiente:

| Tarjeta        | Qué cuenta                                        |
|----------------|---------------------------------------------------|
| OCs vencidas   | `alert_type = 'po_delayed'`                       |
| OCs por vencer | `alert_type = 'po_upcoming'`                      |
| OCs canceladas | `alert_type = 'po_cancelled'`                     |
| Recepciones    | `alert_type = 'receipt_delayed'`                  |

---

### Órdenes de compra

#### Tarjetas KPI del widget OCs

| KPI                | Fórmula                                                                                               |
|--------------------|-------------------------------------------------------------------------------------------------------|
| Cotizaciones (RFQ) | `count(purchase.order)` donde `state in ('draft', 'sent')`                                           |
| Por aprobar        | `count(purchase.order)` donde `state = 'to approve'`                                                 |
| Total aprobadas    | `count(purchase.order)` donde `state = 'purchase'`                                                   |
| A tiempo           | Del total aprobadas: `date_planned > hoy` o sin fecha                                                 |
| Vencidas           | Del total aprobadas: `date_planned <= hoy`                                                            |
| Críticas           | De las vencidas: `(hoy - date_planned).days >= alert_po_critical_days`  (def: 5)                     |

---

#### Tabla de OCs — columnas calculadas

| Columna           | Fórmula / Fuente                                                                        |
|-------------------|-----------------------------------------------------------------------------------------|
| Referencia        | `purchase.order.name`                                                                   |
| Proveedor         | `purchase.order.partner_id.display_name`                                                |
| Entrega estimada  | `purchase.order.date_planned`                                                           |
| Monto total       | `purchase.order.amount_total` (en moneda de la OC)                                      |
| Vencida           | `bool(date_planned and date_planned < hoy)`                                             |
| Días vencida      | `max(0, (hoy - date_planned).days)` si vencida, 0 en otro caso                         |

---

#### Disponibilidad de recepciones — columnas calculadas

La disponibilidad de cada recepción se determina combinando `stock.picking.state` con las cantidades reservadas de sus movimientos:

```python
# Estado de disponibilidad (función _pick_avail):
if picking.state == 'assigned':
    is_partial = any(
        max(move.quantity, move.reserved_availability) < move.product_uom_qty - 0.001
        for move in picking.move_ids if move.state not in ('done', 'cancel')
    )
    → 'partially_available' si is_partial, 'assigned' (completo) si no

if picking.state == 'confirmed':
    has_any = any(
        max(move.quantity, move.reserved_availability) > 0.001
        for move in picking.move_ids if move.state not in ('done', 'cancel')
    )
    → 'partially_available' si has_any, 'confirmed' (sin reserva) si no

si picking.state = 'waiting' → 'waiting'
```

| Estado mostrado   | Condición                                                                          |
|-------------------|------------------------------------------------------------------------------------|
| Disponible        | `state='assigned'` y todas las líneas con qty reservada ≥ qty demandada            |
| Parcialmente      | `state='assigned'` con alguna línea incompleta, o `state='confirmed'` con algo res.|
| No disponible     | `state='confirmed'` sin reservas, o `state='waiting'`                              |

```
días_retraso = max(0, (hoy - stock.picking.scheduled_date).days)
               si scheduled_date < hoy, sino 0
```

---

#### Entregas a subcontratistas — trazado de OF origen

Para cada entrega a subcontratista, el sistema traza la OF de fabricación origen mediante 4 estrategias de fallback en orden:

```
# Estrategia 1: campo directo
for move in picking.move_ids:
    if move.raw_material_production_id → mo encontrada

# Estrategia 2: seguir move_dest_ids iterativamente (BFS)
for move in trazar_destinos(picking.move_ids):
    if move.raw_material_production_id → mo encontrada
    if move.production_id → mo encontrada

# Estrategia 3: desde líneas de la OC asociada
for line in picking.purchase_id.order_line:
    for move in line.move_ids:
        if move.raw_material_production_id → mo encontrada

# Estrategia 4: grupo de abastecimiento
mo = mrp.production donde procurement_group_id = picking.group_id  (limit=1)
```

| Columna           | Fuente                                                    |
|-------------------|-----------------------------------------------------------|
| N° OC             | `mo.purchase_line_id.order_id.name` o '—'                |
| Producto terminado| `mo.product_id.display_name` o '—'                       |
| Proveedor         | `picking.partner_id.display_name`                         |
| Disponibilidad    | Misma función `_pick_avail` que recepciones               |

---

### Análisis de proveedores

#### Tabla de métricas por proveedor — columnas calculadas

El período de análisis se filtra por la fecha configurada en `mrp.reschedule.config.supplier_analysis_date_field` (`date_approve`, `date_order` o `date_planned`). La fuente son `stock.picking` con `state='done'` y `picking_type_code='incoming'` del período.

| Métrica                    | Fórmula                                                                                                                             |
|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| OCs                        | `count(purchase.order)` donde `state in ('purchase','done')` en el período                                                         |
| Artículos distintos        | `len(set(purchase.order.line.product_id))` en el período                                                                           |
| Monto                      | `Σ purchase.order.amount_total` en el período                                                                                       |
| % A tiempo                 | `on_time_count / pick_count × 100` — `on_time` = recepciones con `date_done ≤ scheduled_date`                                      |
| Retraso promedio (días)    | `Σ(date_done - scheduled_date).days / delay_count` — solo recepciones donde `date_done > scheduled_date`                           |
| % Recepciones completas    | `complete_count / pick_count × 100` — `complete` = recepciones que NO generaron backorder (`backorder_id` vacío)                    |
| Lead time promedio (días)  | `Σ(stock.picking.date_done - purchase.order.date_approve).days / count` — desde aprobación hasta cierre de recepción                |
| Variación de precio (%)    | `Σ((price_unit - standard_price) / standard_price × 100) / count` — promedio firmado por línea vs costo estándar del producto       |
| Facturas pendientes        | `Σ account.move.amount_residual` donde `move_type='in_invoice'` y `payment_state not in ('paid','reversed')` y `state='posted'`     |

> La variación de precio es el promedio firmado (puede ser negativo si el precio pagado es inferior al estándar). La clasificación ABC usa el valor absoluto.

**KPIs globales del análisis (ponderados, no promedio de promedios):**

```
on_time_pct_global = Σ on_time_count (todos proveedores) / Σ pick_count (todos) × 100
```

**Colores por umbral (configurables en `mrp.reschedule.config`):**

| Métrica          | Verde                                     | Amarillo                                  | Rojo                              |
|------------------|-------------------------------------------|-------------------------------------------|-----------------------------------|
| % A tiempo       | `≥ sup_on_time_green_pct`  (def: 90 %)   | `≥ sup_on_time_yellow_pct`  (def: 70 %)  | `< sup_on_time_yellow_pct`        |
| Retraso promedio | `≤ sup_delay_green_days`   (def: 1 día)  | `≤ sup_delay_yellow_days`   (def: 3 días)| `> sup_delay_yellow_days`         |
| % Completas      | `≥ sup_complete_green_pct` (def: 95 %)   | `≥ sup_complete_yellow_pct` (def: 80 %)  | `< sup_complete_yellow_pct`       |
| Var. precio      | `\|var\| ≤ sup_price_var_green_pct` (def: 3 %) | `\|var\| ≤ sup_price_var_yellow_pct` (def: 10 %) | `\|var\| > sup_price_var_yellow_pct` |

---

#### Categorías de proveedor — métodos automáticos

El campo `res.partner.x_supplier_category` se calcula con el método elegido en `mrp.reschedule.config.supplier_cat_method`. El período de análisis es los últimos 12 meses (`hoy - 365 días`).

**Umbrales Pareto comunes (aplican a todos los métodos excepto RFM y Manual):**

```
A  si acumulado ≤ abc_pct_a / 100  (def: 20 %)
B  si acumulado ≤ abc_pct_b / 100  (def: 50 %)
C  si acumulado ≤ abc_pct_c / 100  (def: 80 %)
D  si acumulado ≤ abc_pct_d / 100  (def: 95 %)
E  en otro caso
```

**ABC por volumen (`abc_volume`):**
```
valor = Σ purchase.order.amount_total  donde state in ('purchase','done')
# Pareto acumulado descendente (mayor volumen = A)
```

**ABC por frecuencia (`abc_frequency`):**
```
valor = count(purchase.order)  donde state in ('purchase','done')
# Pareto acumulado descendente (mayor frecuencia = A)
```

**ABC por RFM (`abc_rfm`):**
```
R = (hoy - max(purchase.order.date_order)).days   (recencia)
F = count(purchase.order)                          (frecuencia)
M = Σ purchase.order.amount_total                  (monetario)

r_score = 3 si R < 30 días  |  2 si 30 ≤ R < 90  |  1 si R ≥ 90
f_score = 3 si F > 10       |  2 si 3 ≤ F ≤ 10   |  1 si F < 3
m_score = 3 si M ≥ percentil_66(grupo)  |  2 si M ≥ percentil_33  |  1 en otro caso

total_score = r_score + f_score + m_score  (rango 3–9)
A si total_score ≥ 8  |  B si ≥ 6  |  C si ≥ 4  |  D si = 3  |  E si sin datos
```

**ABC por % entrega a tiempo (`abc_delivery_pct`):**
```
on_time_pct = on_time_count / pick_count × 100
# Pareto acumulado descendente (mayor % a tiempo = A)
```

**ABC por variación de precio (`abc_price_var`):**
```
var_por_línea = |purchase.order.line.price_unit - product.product.standard_price|
                / product.product.standard_price × 100
avg_var = Σvar_por_línea / count(líneas con standard_price > 0 y price_unit > 0)
# Pareto INVERTIDO — ordenado de menor a mayor (menor variación = A)
```

**ABC por calidad — diferencia de cantidad (`abc_quality_qty`):**
```
qty_exact_pct = exact_count / total_count × 100
# exact: stock.move donde |quantity - product_uom_qty| < 0.001
# Pareto acumulado descendente (mayor % exactitud = A)
```

**ABC por calidad — devoluciones (`abc_quality_returns`):**
```
returns_count = count(stock.picking) donde return_id != False
                y return_id.purchase_id.partner_id = proveedor
# Pareto INVERTIDO (menos devoluciones = A)
```

**ABC por calidad — combinado (`abc_quality_combo`):**
```
on_time_pct = on_time_count / total_count × 100
qty_pct     = exact_count   / total_count × 100
avg_score   = mean([on_time_pct, qty_pct])   (promedio simple de los disponibles)
# Pareto acumulado descendente (mayor promedio = A)
```

---

## Panel de Ventas

### Productos más vendidos

#### Cantidad vendida y monto

```
cantidad_vendida = Σ stock.move.line.quantity
                   donde picking_type_code = 'outgoing'
                         y state = 'done'
                         y product_id.sale_ok = True
                         y date ∈ [hoy - N meses, hoy]
# Agrupado por product_id.product_tmpl_id (suma variantes del mismo producto base)

importe = cantidad_vendida × product.template.list_price
```

> El importe es una **aproximación** — usa el precio de lista vigente, no el precio real de cada venta.

El período N es una ventana deslizante: 1, 3, 6 o 12 meses.

---

#### Tabla de productos más vendidos — columnas calculadas

| Columna        | Fórmula / Fuente                                                      |
|----------------|-----------------------------------------------------------------------|
| Artículo       | `product.template.name`                                               |
| Código         | `product.template.default_code`                                       |
| Categoría ABC  | `product.template.x_sale_category` (si está habilitado)               |
| Cantidad       | `Σ stock.move.line.quantity` (variantes del mismo template)           |
| Importe        | `cantidad × product.template.list_price`                              |

**Gráfico de dona por categoría ABC:**

```javascript
por_categoría[cat].skus   = count(productos de esa categoría)
por_categoría[cat].qty    = Σ cantidad_vendida
por_categoría[cat].amount = Σ importe

// Porcentaje en segmento (se muestra si segmento ≥ 5%):
pct = skus_cat / total_skus × 100
```

---

#### Categorías de venta (A / B / C / D / E)

La asignación usa `stock.move.line` de tipo `outgoing` y `state='done'` del período `mrp.reschedule.config.sale_cat_lookback_months` (def: 3 meses). El resultado se guarda en `product.template.x_sale_category`.

**Modo Rotación de inventario (`sale_cat_mode = 'automatic'`):**

```
del_by_tmpl   = Σ stock.move.line.quantity  (salidas del período, por product_template)
avg_monthly   = del_by_tmpl / sale_cat_lookback_months
stock_actual  = Σ stock.quant.quantity  (ubicaciones internas, por product_template)

rotación_días = round(stock_actual / avg_monthly × 30)  si avg_monthly > 0, sino 999

A  si rotación_días ≤ sale_cat_a_days  (def: 30)
B  si rotación_días ≤ sale_cat_b_days  (def: 60)
C  si rotación_días ≤ sale_cat_c_days  (def: 90)
D  si rotación_días ≤ sale_cat_d_days  (def: 180)
E  si avg_monthly ≤ 0 o rotación_días > sale_cat_d_days
```

**Modo Demanda (`sale_cat_mode = 'demand'`):**

```
avg_monthly = del_by_tmpl / sale_cat_lookback_months

A  si avg_monthly ≥ sale_cat_demand_a_qty  (def: 100 u/mes)
B  si avg_monthly ≥ sale_cat_demand_b_qty  (def: 50 u/mes)
C  si avg_monthly ≥ sale_cat_demand_c_qty  (def: 20 u/mes)
D  si avg_monthly ≥ sale_cat_demand_d_qty  (def: 5 u/mes)
E  en otro caso
```

**Modo Participación acumulada — Pareto (`sale_cat_mode = 'share'`):**

```
valor = del_by_tmpl × product.template.list_price  si métrica = 'pxq'
valor = del_by_tmpl                                si métrica = 'units'

total     = Σ valor (todos los productos)
acumulado = 0

# Ordenados de mayor a menor valor:
acumulado += valor / total
A  si acumulado ≤ sale_cat_share_a_pct / 100  (def: 50 %)
B  si acumulado ≤ sale_cat_share_b_pct / 100  (def: 80 %)
C  si acumulado ≤ sale_cat_share_c_pct / 100  (def: 95 %)
D  si acumulado ≤ sale_cat_share_d_pct / 100  (def: 99 %)
E  en otro caso
```

---

### Forecast

#### KPIs globales del panel

| KPI                 | Fórmula                                                                                                             |
|---------------------|---------------------------------------------------------------------------------------------------------------------|
| Forecast total      | `Σ mrp.forecast.line.forecast_qty` del período                                                                      |
| OFs planificadas    | `Σ mrp.production.product_qty` donde `state` ∈ estados habilitados y `date_finished` en el período                 |
| Gap OFs             | `OFs_planificadas - forecast_total` (negativo = déficit de cobertura)                                               |
| Cobertura %         | `round(OFs_planificadas / forecast_total × 100, 1)`                                                                 |
| Productos en riesgo | `count(productos)` donde `cobertura_% < forecast_warning_pct`  (def: 70 %)                                         |
| Entregado total     | `Σ stock.move.quantity` donde `picking_type_code='outgoing'` y `state='done'`, para productos con forecast          |
| Demanda OV          | `Σ sale.order.line.product_uom_qty` donde `order.state in ('sale','done')` y fecha en el período                   |
| Tasa de servicio    | `round(entregado_total / demanda_OV × 100, 1)`                                                                      |
| Gap de demanda      | `round((demanda_OV - forecast_total) / forecast_total × 100, 1)` (positivo = demanda superó el forecast)           |
| Precisión forecast  | Según `mrp.reschedule.config.forecast_acc_formula` (ver sección Fórmulas de precisión)                             |

**Colores de Tasa de servicio:**
```
verde    si tasa_servicio ≥ 95 %
amarillo si 80 % ≤ tasa_servicio < 95 %
rojo     si tasa_servicio < 80 %
```

**Colores de Gap de demanda (`|demand_gap_pct|`):**
```
verde    si |gap| ≤ 10 %   (demanda alineada con forecast)
amarillo si |gap| ≤ 25 %   (desvío moderado)
rojo     si |gap| > 25 %   (desvío significativo)
```

**Colores de Gap de OFs:**
```
verde    si gap_ofs ≥ 0 %       (OFs cubren o superan el forecast)
amarillo si -10 % ≤ gap_ofs < 0 %
rojo     si gap_ofs < -10 %
```

---

#### Tabla forecast — columnas calculadas (matriz producto × mes)

Para cada celda (producto, mes):

```
fc_qty  = Σ mrp.forecast.line.forecast_qty  del mes
mo_qty  = Σ mrp.production.product_qty       de OFs en ese mes (estados habilitados)
del_qty = Σ stock.move.line.quantity          de salidas done en ese mes
so_qty  = Σ sale.order.line.product_uom_qty  de OVs sale/done en ese mes

cobertura_pct  = round(mo_qty / fc_qty × 100, 1)  si fc_qty > 0, sino 0.0
service_rate   = round(del_qty / so_qty × 100, 1)  si so_qty > 0, sino null
demand_gap_pct = round((so_qty - fc_qty) / fc_qty × 100, 1)  si fc_qty > 0, sino null
```

**Colores de cobertura por celda:**
```
verde    si cobertura_pct ≥ 100 %
amarillo si cobertura_pct ≥ forecast_warning_pct  (def: 70 %)
rojo     si cobertura_pct <  forecast_warning_pct
```

**Totales por producto (columna de totales):**
```
total_forecast    = Σ fc_qty  (todos los meses)
total_mos         = Σ mo_qty
total_pct         = round(total_mos / total_forecast × 100, 1)  si total_forecast > 0
total_delivered   = Σ del_qty
total_so_demand   = Σ so_qty
total_service_rate= round(total_delivered / total_so_demand × 100, 1)  si total_so_demand > 0
```

---

#### Rotación de inventario (columna de la tabla)

```
avg_monthly_del = Σ del_qty (todos los meses del período) / n_meses
stock_actual    = Σ stock.quant.quantity  (ubicaciones internas)

rotación_meses  = round(stock_actual / avg_monthly_del, 1)     si avg_monthly_del > 0
rotación_días   = round(stock_actual / avg_monthly_del × 30)   si avg_monthly_del > 0
```

La unidad de visualización se configura en `mrp.reschedule.config.forecast_rotation_unit` (`'days'` o `'months'`).

**Colores:**

| Unidad | Verde      | Amarillo         | Gris (sin color) |
|--------|------------|------------------|------------------|
| Días   | ≤ 90 días  | 91–180 días      | > 180 días       |
| Meses  | ≤ 3 meses  | 4–6 meses        | > 6 meses        |

El umbral amarillo es exactamente el doble del umbral verde.

---

#### Fórmulas de precisión de forecast

> Todas las fórmulas usan **demanda SO** (`so_demand`) como referencia real: `Σ sale.order.line.product_uom_qty` de OVs confirmadas/cerradas del período. No son unidades entregadas físicamente.

En todas las fórmulas, por período y producto:
- `forecast_qty` = `mrp.forecast.line.forecast_qty`
- `so_demand` = demanda SO del período
- `abs_err` = `|so_demand - forecast_qty|`

**Simple:**
```
precisión_celda = round(so_demand / forecast_qty × 100, 1)    si forecast_qty > 0
precisión_total = round(Σso_demand / Σforecast_qty × 100, 1)
```
100 % = coincidencia exacta. Por encima de 100 % = demanda superó el forecast.

**MAPE — Error porcentual absoluto medio:**
```
precisión_celda = round(max(0, 100 - abs_err / so_demand × 100), 1)  si so_demand > 0
precisión_total = Σprecisión_celda / count(celdas con so_demand > 0)
```
Solo se incluyen períodos donde `so_demand > 0`. Sensible a períodos de bajo volumen.

**WAPE — Ponderado por demanda real:**
```
precisión_total = round(max(0, 100 - Σabs_err / Σso_demand × 100), 1)
```
Pondera más los períodos de mayor demanda real. Robusto ante períodos con forecast en cero.

**WMAPE — Ponderado por forecast:**
```
precisión_total = round(max(0, 100 - Σabs_err / Σforecast_qty × 100), 1)
```
Pondera más los períodos de mayor volumen planificado. Estándar en supply chain.

**Sesgo (Bias):**
```
sesgo_celda = round((so_demand - forecast_qty) / forecast_qty × 100, 1)  si forecast_qty > 0
sesgo_total = round((Σso_demand - Σforecast_qty) / Σforecast_qty × 100, 1)
```
Positivo = demanda superó sistemáticamente el forecast (forecast conservador). Negativo = forecast optimista.

**Colores de precisión:**
```
# Simple, MAPE, WAPE, WMAPE:
verde    si precisión ≥ 90 %
amarillo si 70 % ≤ precisión < 90 %
rojo     si precisión < 70 %

# Sesgo:
verde    si |sesgo| ≤ 10 %
amarillo si 10 % < |sesgo| ≤ 20 %
rojo     si |sesgo| > 20 %
```

---

#### Categorías de cliente — métodos automáticos

El campo `res.partner.x_customer_category` se calcula con el método elegido en `mrp.reschedule.config.customer_cat_method`. El período de análisis es los últimos 12 meses. Los umbrales Pareto son los mismos que para proveedores (`abc_pct_a/b/c/d`).

**ABC por volumen (`abc_volume`):**
```
valor = Σ sale.order.amount_total  donde state in ('sale','done')
# Pareto acumulado descendente (mayor volumen = A)
```

**ABC por frecuencia (`abc_frequency`):**
```
valor = count(sale.order)  donde state in ('sale','done')
# Pareto acumulado descendente (mayor frecuencia = A)
```

**ABC por RFM (`abc_rfm`):**
```
R = (hoy - max(sale.order.date_order)).days
F = count(sale.order)
M = Σ sale.order.amount_total

# Scoring idéntico al de proveedores (r/f/m_score 1–3)
total_score = r_score + f_score + m_score  (rango 3–9)
A si ≥ 8  |  B si ≥ 6  |  C si ≥ 4  |  D si = 3  |  E si sin datos
```
