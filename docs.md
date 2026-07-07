# Documentación de fórmulas de cálculo

---

## Panel de Producción

### Alertas de producción

#### OFs atrasadas

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una OF activa tiene la fecha de fin planificada en el pasado |
| **Estados que aplican** | Confirmada, En progreso, Por cerrar |
| **Excluye** | OFs cuya lista de materiales es de tipo Subcontratación |

**Días de atraso**

| Concepto | Detalle |
|---|---|
| **Fórmula** | máximo entre 0 y (fecha actual − fecha fin planificada de la OF), en días enteros |
| **Campo Odoo** | `mrp.production.date_finished` |
| **Nota** | El resultado nunca es negativo |

**Severidad**

| Condición | Color |
|---|---|
| Días de atraso ≥ umbral crítico | Roja |
| Días de atraso < umbral crítico | Amarilla |

| Parámetro | Campo | Valor por defecto |
|---|---|---|
| Umbral días críticos OFs | `mrp.reschedule.config.alert_mo_critical_days` | 3 días |

---

#### OFs por vencer

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una OF activa tiene la fecha de fin dentro de la ventana de aviso, pero aún no venció |
| **Condición** | fecha actual < fecha fin planificada ≤ fecha actual + ventana de aviso |
| **Severidad** | Siempre amarilla |
| **Excluye** | OFs de subcontratación |

| Parámetro | Campo | Valor por defecto |
|---|---|---|
| Ventana de aviso en días | `mrp.reschedule.config.alert_mo_warning_days` | 7 días |

---

#### Cantidad diferente

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una OF recién cerrada produjo una cantidad que difiere de la planificada más allá de la tolerancia |
| **Estado que dispara** | OF pasa a Terminada |

**Cálculo del desvío**

| Concepto | Detalle |
|---|---|
| **Cantidad real** | Suma de las cantidades de los movimientos de producto terminado con estado Hecho |
| **Desvío** | valor absoluto de (cantidad real − cantidad planificada) dividido por cantidad planificada |
| **Condición de alerta** | desvío > tolerancia configurada |
| **Campo cantidad real** | `stock.move.quantity` donde `move.state = 'done'` y `move.product_id = mrp.production.product_id` |
| **Campo cantidad planificada** | `mrp.production.product_qty` |

**Severidad**

| Condición | Color |
|---|---|
| Cantidad real < cantidad planificada (producción insuficiente) | Roja |
| Cantidad real > cantidad planificada (excedente) | Amarilla |

| Parámetro | Campo | Valor por defecto |
|---|---|---|
| Tolerancia de desvío | `mrp.reschedule.config.qty_tolerance_pct` | 5 % |

---

#### OFs canceladas

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una OF pasa al estado Cancelada |
| **Resolución** | No se auto-resuelve, requiere acción manual |
| **Severidad** | Siempre amarilla |
| **Excluye** | OFs de subcontratación |

---

#### Tarjetas KPI de alertas de producción

Cada tarjeta cuenta alertas no resueltas (`resolved = False`), excluyendo las de OFs con LdM de subcontratación.

| Tarjeta | Qué cuenta | Campo tipo alerta |
|---|---|---|
| OFs atrasadas | Alertas abiertas de OFs con fecha de fin vencida | `alert_type = 'mo_delayed'` |
| OFs por vencer | Alertas abiertas de OFs próximas a vencer | `alert_type = 'mo_upcoming'` |
| Cant. diferentes | Alertas abiertas de OFs con cantidad producida fuera de tolerancia | `alert_type = 'qty_mismatch'` |
| OFs canceladas | Alertas abiertas de OFs canceladas | `alert_type = 'mo_cancelled'` |
| Badge críticas | Total de alertas abiertas con severidad roja, de cualquier tipo | `severity = 'critical'` |

---

#### Tabla de alertas activas — columnas calculadas

| Columna | Cómo se calcula | Campo Odoo |
|---|---|---|
| Tipo | Etiqueta traducida del tipo de alerta | `mrp.reschedule.alert.alert_type` |
| Severidad | Nivel de urgencia: roja o amarilla | `mrp.reschedule.alert.severity` |
| OF / OC / Recepción | Registro origen de la alerta | Relación al documento según tipo |
| Producto | Nombre del producto involucrado | `mrp.reschedule.alert.product_id.display_name` |
| Días de atraso | máximo(0, fecha actual − fecha de referencia), en días | Calculado en tiempo real |

**Fecha de referencia según tipo de alerta**

| Tipo de alerta | Fecha de referencia | Campo Odoo |
|---|---|---|
| OFs atrasadas / por vencer / cant. diferentes / canceladas | Fecha fin planificada de la OF | `mrp.production.date_finished` |
| OCs vencidas / por vencer / canceladas | Fecha de entrega estimada de la OC | `purchase.order.date_planned` |
| Recepciones atrasadas | Fecha programada de la recepción | `stock.picking.scheduled_date` |

---

### Órdenes de fabricación

#### Tarjetas KPI del widget OFs

| KPI | Qué cuenta | Condición |
|---|---|---|
| Activas | OFs que no están terminadas ni canceladas | `state not in ('done', 'cancel')` |
| En progreso | OFs activas en fabricación o listas para cerrar | `state in ('progress', 'to_close')` |
| Atrasadas | OFs activas con fecha fin en el pasado | `date_finished < fecha actual` |
| Para reprogramar | OFs activas marcadas por el sistema para reprogramar | `x_reschedule_needed = True` |
| Finalizadas | OFs terminadas | `state = 'done'` |
| Por cerrar | OFs activas pendientes de cierre | `state = 'to_close'` |

---

#### Tabla de OFs — columnas calculadas

Las OFs mostradas son las que solapan con el rango de fechas seleccionado y no están terminadas ni canceladas.

| Columna | Cómo se calcula | Campo Odoo |
|---|---|---|
| Referencia | Nombre de la OF | `mrp.production.name` |
| Producto | Nombre del producto a fabricar | `mrp.production.product_id.display_name` |
| Cantidad | Cantidad planificada a producir | `mrp.production.product_qty` |
| Fin planificado | Fecha y hora de fin prevista | `mrp.production.date_finished` |
| Estado | Estado actual de la OF | `mrp.production.state` |
| Atrasada | Sí cuando la fecha fin ya pasó | `date_finished < fecha actual` |
| Reprogramar | Sí cuando el sistema marcó la OF para reprogramar | `mrp.production.x_reschedule_needed` |
| Entregas pendientes | Suma de cantidades de movimientos de salida pendientes para ese producto | `stock.move.product_uom_qty` donde `state not in ('done','cancel')` y `picking_type_code = 'outgoing'` |

---

#### Tabla de Solicitudes de Producción — columnas calculadas

| Columna | Cómo se calcula | Campo Odoo |
|---|---|---|
| Referencia | Nombre de la solicitud | `mrp.production.request.name` |
| Disponible desde | Fecha mínima de inicio para las OFs de esta solicitud | `mrp.production.request.start_from` |
| Estado | Estado actual de la solicitud | `mrp.production.request.state` |
| OFs totales | Cantidad de OFs vinculadas a la solicitud | Conteo de `item_ids.production_id` |
| OFs terminadas | OFs de la solicitud con estado Terminada | `production_id.state = 'done'` |
| OFs retrasadas | OFs de la solicitud activas con fecha fin en el pasado | `state not in ('done','cancel')` y `date_finished < fecha actual` |

**KPIs del widget de solicitudes**

| KPI | Cómo se calcula |
|---|---|
| Total | Solicitudes en estado Confirmada + Calculada |
| Activas | Solicitudes en estado Confirmada |
| Calculadas | Solicitudes en estado Calculada |
| Para reprogramar | Solicitudes activas donde alguna OF tiene `x_reschedule_needed = True` |
| OFs retrasadas | Total de OFs en estado activo con fecha fin vencida, de todas las solicitudes activas |

---

#### Tabla Producido vs Programado — columnas calculadas

Agrupa todas las OFs del período (activas y terminadas) por producto.

| Columna | Fórmula en español | Campo Odoo |
|---|---|---|
| Producto | Nombre del producto | `mrp.production.product_id.display_name` |
| Programado | Suma de cantidades planificadas de todas las OFs del período para ese producto | `mrp.production.product_qty` |
| Producido | Suma de cantidades ya producidas de todas las OFs del período para ese producto | `mrp.production.qty_produced` |
| % Cumplimiento | (producido ÷ programado) × 100, redondeado a 1 decimal. Cero si no hay nada programado | Calculado |

**Colores del % de cumplimiento**

| Color | Condición |
|---|---|
| Verde | % cumplimiento ≥ 90 % |
| Amarillo | % cumplimiento entre 50 % y 89 % |
| Rojo | % cumplimiento < 50 % |

**KPIs globales del comparativo**

| KPI | Fórmula en español |
|---|---|
| Total programado | Suma de cantidades programadas de todos los productos |
| Total producido | Suma de cantidades producidas de todos los productos |
| % Global | (total producido ÷ total programado) × 100, redondeado a 1 decimal |
| OFs terminadas | Cantidad de OFs con estado Terminada en el período |

---

### Carga de centros de trabajo

#### Horas disponibles

| Concepto | Detalle |
|---|---|
| **Fórmula** | Horas hábiles del calendario laboral del CT en el período × (eficiencia del CT ÷ 100) |
| **Fallback** | Si el calendario no puede calcularse, se estima en proporción a las horas semanales de asistencia |
| **Campo calendario** | `mrp.workcenter.resource_calendar_id` |
| **Campo eficiencia** | `mrp.workcenter.time_efficiency` (en %, por ejemplo 85 significa 85 %) |

---

#### Horas ejecutadas

| Concepto | Detalle |
|---|---|
| **Fórmula** | Suma de horas de operaciones ya terminadas que se solapan con el período seleccionado |
| **Estado** | Solo operaciones con estado Terminada |
| **Campo duración** | `mrp.workorder.duration_expected` (en minutos, se convierte a horas dividiendo por 60) |
| **Campo estado** | `mrp.workorder.state = 'done'` |

**Solapamiento parcial de una operación con el período**

| Concepto | Fórmula en español |
|---|---|
| Inicio del solapamiento | el mayor entre fecha inicio de la operación y fecha inicio del período |
| Fin del solapamiento | el menor entre fecha fin de la operación y fecha fin del período |
| Proporción del solapamiento | (duración del solapamiento en segundos) ÷ (duración total de la operación en segundos) |
| Horas aportadas | duración esperada de la operación (en horas) × proporción del solapamiento |

---

#### Horas pendientes

| Concepto | Detalle |
|---|---|
| **Fórmula** | Mismo cálculo de solapamiento que horas ejecutadas, pero para operaciones que aún no terminaron ni se cancelaron |
| **Estado** | Operaciones con cualquier estado excepto Terminada y Cancelada |

---

#### Tiempo libre y carga del CT

| Indicador | Fórmula en español | Nota |
|---|---|---|
| Tiempo libre | máximo(0, horas disponibles − horas ejecutadas − horas pendientes) | Nunca negativo |
| Carga % | (horas ejecutadas + horas pendientes) ÷ horas disponibles × 100 | Cero si no hay horas disponibles |

**Colores de carga**

| Color | Condición |
|---|---|
| Verde | Carga < 70 % |
| Amarillo | Carga entre 70 % y 89 % |
| Rojo | Carga ≥ 90 % |

---

#### Series del gráfico de carga (barras apiladas)

El gráfico muestra dos stacks por cada centro de trabajo:

| Serie | Stack | Valor |
|---|---|---|
| Planificado | Plan | horas ejecutadas + horas pendientes |
| No planificado | Plan | tiempo libre |
| Ejecutado | Real | horas ejecutadas |
| Pendiente | Real | horas pendientes |
| Tiempo libre | Real | tiempo libre |

**Tooltip de ocupación real**

| Concepto | Fórmula en español |
|---|---|
| % ocupación | (horas ejecutadas + horas pendientes) ÷ horas disponibles × 100, redondeado |

---

#### Tabla de centros de trabajo — columnas calculadas

| Columna | Fórmula en español | Campo / Fuente |
|---|---|---|
| Centro de trabajo | Nombre del CT | `mrp.workcenter.name` |
| Disponible (h) | Horas hábiles del calendario × eficiencia | `resource_calendar_id`, `time_efficiency` |
| Ejecutado (h) | Suma de horas de operaciones terminadas que solapan el período | `mrp.workorder.duration_expected`, `state = 'done'` |
| Pendiente (h) | Suma de horas de operaciones activas que solapan el período | `mrp.workorder.duration_expected`, `state != 'done/cancel'` |
| Tiempo libre (h) | disponible − ejecutado − pendiente (mínimo 0) | Calculado |
| Carga % | (ejecutado + pendiente) ÷ disponible × 100 | Calculado |

---

### Quiebres de stock

#### Fórmula de quiebre

| Concepto | Detalle |
|---|---|
| **Stock actual** | Suma de cantidades en las ubicaciones internas de la ubicación configurada |
| **Mínimo** | Cantidad mínima configurada en el punto de reorden del producto (ruta Fabricación). Si hay varios puntos de reorden, se toma el mayor |
| **Condición de quiebre** | stock actual < mínimo (con tolerancia de 0.001 unidades) |
| **Campo stock** | `stock.quant.quantity` en ubicaciones con `usage = 'internal'` |
| **Campo mínimo** | `stock.warehouse.orderpoint.product_min_qty` donde `route_id = ruta Fabricación` |
| **Ubicación configurada** | `mrp.reschedule.config.stock_location_id` (si no está configurada, se usan todas las internas) |

---

#### KPIs del widget de quiebres

| KPI | Qué cuenta |
|---|---|
| Total | Productos con línea de forecast O con punto de reorden configurado |
| Con quiebre | Productos con punto de reorden donde stock actual < mínimo |
| OK | Productos con punto de reorden donde stock actual ≥ mínimo |
| Sin mínimo | Productos sin punto de reorden configurado (ruta Fabricación) |

---

#### Tabla de quiebres — columnas calculadas

| Columna | Fórmula en español | Campo Odoo |
|---|---|---|
| Artículo | Nombre del producto | `product.template.display_name` |
| Tipo | Tipos de producto asignados al artículo (concatenados) | `product.template.x_product_type_ids` |
| Stock actual | Suma de cantidades en ubicaciones internas | `stock.quant.quantity` |
| Mínimo | Cantidad mínima del punto de reorden | `stock.warehouse.orderpoint.product_min_qty` |
| Diferencia | stock actual − mínimo (negativo indica quiebre) | Calculado |
| Estado | `Quiebre` / `OK` / `Sin mínimo` según condición | Calculado |

---

#### OFs activas por producto (acordeón)

Al expandir un producto, se muestran sus OFs activas:

| Concepto | Detalle |
|---|---|
| **Filtro** | OFs del producto en estado Confirmada, En progreso o Por cerrar, excluyendo subcontratación |
| **Orden** | Por fecha fin ascendente |
| **Límite** | 50 OFs como máximo |

---

### Reprogramación en cascada

#### Duración de una OF

El sistema intenta calcular la duración en este orden:

| Prioridad | Fórmula en español | Campos Odoo |
|---|---|---|
| 1 — Con operaciones | Suma de duraciones esperadas de todas las operaciones, convertidas de minutos a horas | `mrp.workorder.duration_expected` ÷ 60 |
| 2 — Con fechas | Diferencia entre fecha fin y fecha inicio de la OF, en horas | `mrp.production.date_finished` − `mrp.production.date_start` |
| 3 — Fallback | Se asumen 8 horas | Valor fijo |

---

#### Delta de reprogramación

| Concepto | Fórmula en español | Formato |
|---|---|---|
| Diferencia de fechas | nueva fecha fin − fecha fin actual, en segundos | Interno |
| Días | parte entera de (diferencia en horas ÷ 24) | Número entero |
| Horas restantes | resto de (diferencia en horas ÷ 24) | Número entero |
| Visualización | `+2d 3h` si se adelanta, `-1d 0h` si se atrasa | Texto |

---

#### Secuenciación de operaciones por CT

Cada operación se programa desde el momento en que el CT queda libre. Ninguna operación puede empezar antes de que el CT esté disponible.

Si se ajusta la duración total de la OF, cada operación se escala proporcionalmente:

| Concepto | Fórmula en español | Campo Odoo |
|---|---|---|
| Factor de escala | duración total ajustada ÷ suma de duraciones esperadas originales | `mrp.workorder.duration_expected` |
| Nueva duración de cada operación | duración esperada original × factor de escala | Calculado |

---

## Panel de Compras

### Alertas de compras

#### OCs vencidas

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una OC aprobada tiene la fecha de entrega estimada en el pasado |
| **Campo de referencia** | `purchase.order.date_planned` (entrega estimada, no fecha de emisión) |

**Días de atraso y severidad**

| Concepto | Fórmula en español | Campo |
|---|---|---|
| Días de atraso | máximo(0, fecha actual − fecha de entrega estimada), en días enteros | `purchase.order.date_planned` |
| Severidad roja | días de atraso ≥ umbral crítico OCs | `mrp.reschedule.config.alert_po_critical_days` (def: 5 días) |
| Severidad amarilla | días de atraso < umbral crítico OCs | — |

---

#### OCs por vencer

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una OC aprobada y no totalmente recibida tiene la fecha de entrega dentro de la ventana de aviso, pero aún no venció |
| **Condición** | fecha actual < fecha entrega estimada ≤ fecha actual + ventana de aviso |
| **Severidad** | Siempre amarilla |

| Parámetro | Campo | Valor por defecto |
|---|---|---|
| Ventana de aviso en días | `mrp.reschedule.config.alert_po_warning_days` | 10 días |

---

#### Recepciones atrasadas

| Concepto | Detalle |
|---|---|
| **¿Cuándo se genera?** | Cuando una recepción pendiente tiene la fecha programada en el pasado |

**Días de atraso y severidad**

| Concepto | Fórmula en español | Campo |
|---|---|---|
| Días de atraso | máximo(0, fecha actual − fecha programada de la recepción), en días enteros | `stock.picking.scheduled_date` |
| Severidad roja | días de atraso ≥ umbral crítico recepciones | `mrp.reschedule.config.alert_receipt_critical_days` (def: 3 días) |
| Severidad amarilla | días de atraso < umbral crítico recepciones | — |

---

#### Tarjetas KPI de alertas de compras

| Tarjeta | Qué cuenta | Campo tipo alerta |
|---|---|---|
| OCs vencidas | Alertas abiertas de OCs con entrega vencida | `alert_type = 'po_delayed'` |
| OCs por vencer | Alertas abiertas de OCs próximas a vencer | `alert_type = 'po_upcoming'` |
| OCs canceladas | Alertas abiertas de OCs canceladas | `alert_type = 'po_cancelled'` |
| Recepciones | Alertas abiertas de recepciones atrasadas | `alert_type = 'receipt_delayed'` |

---

### Órdenes de compra

#### Tarjetas KPI del widget OCs

| KPI | Fórmula en español | Condición Odoo |
|---|---|---|
| Cotizaciones | OCs en borrador o enviadas al proveedor | `state in ('draft', 'sent')` |
| Por aprobar | OCs pendientes de aprobación interna | `state = 'to approve'` |
| Total aprobadas | OCs confirmadas con entrega pendiente | `state = 'purchase'` |
| A tiempo | Del total aprobadas: con fecha de entrega futura o sin fecha | `date_planned > fecha actual` |
| Vencidas | Del total aprobadas: con fecha de entrega en el pasado | `date_planned ≤ fecha actual` |
| Críticas | De las vencidas: con atraso mayor al umbral crítico | `(fecha actual − date_planned).días ≥ alert_po_critical_days` |

---

#### Tabla de OCs — columnas calculadas

| Columna | Fórmula en español | Campo Odoo |
|---|---|---|
| Referencia | Número de la OC | `purchase.order.name` |
| Proveedor | Nombre del proveedor | `purchase.order.partner_id.display_name` |
| Entrega estimada | Fecha de entrega comprometida | `purchase.order.date_planned` |
| Monto total | Importe total de la OC en su moneda | `purchase.order.amount_total` |
| Vencida | Sí cuando la fecha de entrega ya pasó | `date_planned < fecha actual` |
| Días vencida | máximo(0, fecha actual − fecha de entrega), en días. Cero si no está vencida | Calculado |

---

#### Disponibilidad de recepciones — columnas calculadas

El estado de disponibilidad combina el estado del picking con las cantidades reservadas en sus movimientos:

| Estado mostrado | Condición |
|---|---|
| Disponible | El picking está asignado y todas las líneas tienen cantidad reservada ≥ cantidad demandada |
| Parcialmente disponible | El picking está asignado con alguna línea incompleta, o confirmado con algo reservado |
| No disponible | El picking está confirmado sin reservas, o en estado En espera |

| Columna | Fórmula en español | Campo Odoo |
|---|---|---|
| Cantidad disponible por línea | el mayor entre cantidad reservada y cantidad ya procesada | `max(stock.move.reserved_availability, stock.move.quantity)` |
| Días de retraso | máximo(0, fecha actual − fecha programada), en días. Cero si no está atrasada | `stock.picking.scheduled_date` |

---

#### Entregas a subcontratistas — trazado de OF origen

Para cada entrega, el sistema busca la OF de fabricación origen en este orden:

| Prioridad | Estrategia |
|---|---|
| 1 | Campo directo `raw_material_production_id` en los movimientos del picking |
| 2 | Seguir los destinos de los movimientos iterativamente hasta encontrar una OF |
| 3 | Buscar en las líneas de la OC asociada al picking |
| 4 | Buscar por grupo de abastecimiento compartido entre el picking y alguna OF |

| Columna | Fuente |
|---|---|
| N° OC | `mrp.production.purchase_line_id.order_id.name` (de la OF encontrada) |
| Producto terminado | `mrp.production.product_id.display_name` (de la OF encontrada) |
| Proveedor | `stock.picking.partner_id.display_name` |

---

### Análisis de proveedores

#### Tabla de métricas — columnas calculadas

La fuente son las recepciones (`stock.picking`) con estado Hecho y tipo Entrante del período seleccionado.

| Métrica | Fórmula en español | Campos Odoo |
|---|---|---|
| OCs | Cantidad de OCs aprobadas o cerradas del proveedor en el período | `count(purchase.order)` donde `state in ('purchase','done')` |
| Artículos distintos | Cantidad de productos distintos comprados al proveedor en el período | `len(set(purchase.order.line.product_id))` |
| Monto | Suma de importes de todas las OCs del proveedor en el período | `Σ purchase.order.amount_total` |
| % A tiempo | Recepciones llegadas en fecha ÷ total de recepciones × 100 | `on_time_count / pick_count × 100` donde `date_done ≤ scheduled_date` |
| Retraso promedio (días) | Promedio de días de atraso, solo sobre las recepciones que llegaron tarde | `Σ(date_done − scheduled_date).días / count` donde `date_done > scheduled_date` |
| % Completas | Recepciones sin backorder ÷ total de recepciones × 100 | `complete_count / pick_count × 100` donde el picking no generó backorder |
| Lead time promedio (días) | Promedio de días desde la aprobación de la OC hasta el cierre de la recepción | `Σ(stock.picking.date_done − purchase.order.date_approve).días / count` |
| Variación de precio (%) | Promedio firmado de la diferencia entre precio pagado y costo estándar, por línea | `Σ((price_unit − standard_price) / standard_price × 100) / count` |
| Facturas pendientes | Suma de saldos pendientes de pago de facturas del proveedor | `Σ account.move.amount_residual` donde `payment_state not in ('paid','reversed')` |

> La variación de precio puede ser negativa si el precio pagado fue menor al costo estándar. La clasificación ABC usa el valor absoluto.

**KPI global de % a tiempo (ponderado, no promedio de promedios)**

| Concepto | Fórmula en español |
|---|---|
| % a tiempo global | suma de recepciones a tiempo de todos los proveedores ÷ suma total de recepciones × 100 |

**Colores por umbral (configurables)**

| Métrica | Verde | Amarillo | Rojo |
|---|---|---|---|
| % A tiempo | ≥ `sup_on_time_green_pct` (def: 90 %) | ≥ `sup_on_time_yellow_pct` (def: 70 %) | < 70 % |
| Retraso promedio | ≤ `sup_delay_green_days` (def: 1 día) | ≤ `sup_delay_yellow_days` (def: 3 días) | > 3 días |
| % Completas | ≥ `sup_complete_green_pct` (def: 95 %) | ≥ `sup_complete_yellow_pct` (def: 80 %) | < 80 % |
| Variación precio | \|var\| ≤ `sup_price_var_green_pct` (def: 3 %) | \|var\| ≤ `sup_price_var_yellow_pct` (def: 10 %) | \|var\| > 10 % |

---

#### Categorías de proveedor — métodos automáticos

El resultado se guarda en `res.partner.x_supplier_category`. El período de análisis son los últimos 12 meses.

**Umbrales Pareto comunes** (aplican a todos los métodos excepto RFM y Manual):

| Categoría | Condición | Parámetro |
|---|---|---|
| A | acumulado ≤ umbral A | `abc_pct_a` (def: 20 %) |
| B | acumulado ≤ umbral B | `abc_pct_b` (def: 50 %) |
| C | acumulado ≤ umbral C | `abc_pct_c` (def: 80 %) |
| D | acumulado ≤ umbral D | `abc_pct_d` (def: 95 %) |
| E | resto | — |

---

**ABC por volumen** (`supplier_cat_method = 'abc_volume'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Suma de importes de OCs confirmadas o cerradas en los últimos 12 meses |
| **Clasificación** | Pareto acumulado descendente: mayor importe = A |
| **Campo** | `Σ purchase.order.amount_total` donde `state in ('purchase','done')` |

---

**ABC por frecuencia** (`supplier_cat_method = 'abc_frequency'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Cantidad de OCs confirmadas o cerradas en los últimos 12 meses |
| **Clasificación** | Pareto acumulado descendente: mayor frecuencia = A |
| **Campo** | `count(purchase.order)` donde `state in ('purchase','done')` |

---

**ABC por RFM** (`supplier_cat_method = 'abc_rfm'`)

| Componente | Fórmula en español | Puntuación |
|---|---|---|
| Recencia (R) | Días desde la última OC hasta hoy | < 30 días = 3 pts / < 90 días = 2 pts / resto = 1 pt |
| Frecuencia (F) | Cantidad de OCs en el último año | > 10 OCs = 3 pts / ≥ 3 = 2 pts / resto = 1 pt |
| Monetario (M) | Importe total de OCs en el último año | ≥ percentil 66 del grupo = 3 pts / ≥ percentil 33 = 2 pts / resto = 1 pt |

| Puntaje total (R+F+M) | Categoría |
|---|---|
| 8 o 9 | A |
| 6 o 7 | B |
| 4 o 5 | C |
| 3 | D |
| Sin datos (sin OCs en el período) | E |

---

**ABC por % entrega a tiempo** (`supplier_cat_method = 'abc_delivery_pct'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Recepciones llegadas en fecha ÷ total de recepciones × 100 |
| **Clasificación** | Pareto acumulado descendente: mayor % a tiempo = A |

---

**ABC por variación de precio** (`supplier_cat_method = 'abc_price_var'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Promedio de \|precio de la línea − costo estándar del producto\| ÷ costo estándar × 100, por línea de OC |
| **Clasificación** | Pareto acumulado **ascendente** (invertido): menor variación = A |
| **Campos** | `purchase.order.line.price_unit`, `product.product.standard_price` |

---

**ABC por calidad — exactitud de cantidad** (`supplier_cat_method = 'abc_quality_qty'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Movimientos recibidos con cantidad exacta ÷ total de movimientos × 100 |
| **Exactitud** | Se considera exacta cuando \|cantidad recibida − cantidad pedida\| < 0,001 unidades |
| **Clasificación** | Pareto acumulado descendente: mayor % exactitud = A |

---

**ABC por calidad — devoluciones** (`supplier_cat_method = 'abc_quality_returns'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Cantidad de recepciones revertidas al proveedor en el último año |
| **Clasificación** | Pareto acumulado **ascendente** (invertido): menos devoluciones = A |

---

**ABC por calidad — combinado** (`supplier_cat_method = 'abc_quality_combo'`)

| Concepto | Detalle |
|---|---|
| **Valor por proveedor** | Promedio simple entre % de recepciones a tiempo y % de recepciones con cantidad exacta |
| **Clasificación** | Pareto acumulado descendente: mayor promedio = A |

---

## Panel de Ventas

### Productos más vendidos

#### Cantidad vendida y monto

| Concepto | Fórmula en español | Campo Odoo |
|---|---|---|
| Cantidad vendida | Suma de unidades de las salidas completadas del período, agrupado por producto base (suma de variantes) | `Σ stock.move.line.quantity` donde `picking_type_code = 'outgoing'` y `state = 'done'` y `product_id.sale_ok = True` |
| Importe | cantidad vendida × precio de lista vigente del producto | `product.template.list_price` |
| Período | Ventana deslizante configurable: 1, 3, 6 o 12 meses hacia atrás desde hoy | — |

> El importe es una **aproximación**: usa el precio de lista actual, no el precio real de cada venta.

---

#### Tabla de productos más vendidos — columnas calculadas

| Columna | Fórmula en español | Campo Odoo |
|---|---|---|
| Artículo | Nombre del producto | `product.template.name` |
| Código | Referencia interna | `product.template.default_code` |
| Categoría ABC | Categoría de venta asignada (si está habilitada) | `product.template.x_sale_category` |
| Cantidad | Suma de unidades vendidas en el período (todas las variantes del producto) | `Σ stock.move.line.quantity` |
| Importe | Cantidad × precio de lista actual | Calculado |

---

#### Gráfico de dona por categoría ABC

| Dato del segmento | Fórmula en español |
|---|---|
| SKUs | Cantidad de productos distintos en esa categoría |
| Cantidad total | Suma de unidades vendidas de todos los productos de esa categoría |
| Importe total | Suma de importes de todos los productos de esa categoría |
| % del segmento | SKUs de la categoría ÷ total de SKUs mostrados × 100 (se muestra si ≥ 5 %) |

---

### Categorías de venta (A / B / C / D / E)

El resultado se guarda en `product.template.x_sale_category`. La fuente son salidas completadas del período de análisis configurado.

| Parámetro | Campo | Valor por defecto |
|---|---|---|
| Período de análisis | `mrp.reschedule.config.sale_cat_lookback_months` | 3 meses |

---

#### Modo Rotación de inventario (`sale_cat_mode = 'automatic'`)

| Concepto | Fórmula en español | Campo Odoo |
|---|---|---|
| Salidas del período | Suma de unidades entregadas en el período, por producto base | `Σ stock.move.line.quantity` salidas completadas |
| Promedio mensual | Salidas del período ÷ cantidad de meses del período | — |
| Stock actual | Suma de cantidades en ubicaciones internas, por producto base | `Σ stock.quant.quantity` |
| Días de rotación | (stock actual ÷ promedio mensual) × 30, redondeado. Si no hay ventas: 999 | Calculado |

| Categoría | Condición |
|---|---|
| A | días de rotación ≤ `sale_cat_a_days` (def: 30 días) |
| B | días de rotación ≤ `sale_cat_b_days` (def: 60 días) |
| C | días de rotación ≤ `sale_cat_c_days` (def: 90 días) |
| D | días de rotación ≤ `sale_cat_d_days` (def: 180 días) |
| E | sin ventas en el período o rotación > umbral D |

---

#### Modo Demanda (`sale_cat_mode = 'demand'`)

| Concepto | Fórmula en español | Campo Odoo |
|---|---|---|
| Promedio mensual | Salidas del período ÷ cantidad de meses del período | `Σ stock.move.line.quantity` |

| Categoría | Condición |
|---|---|
| A | promedio mensual ≥ `sale_cat_demand_a_qty` (def: 100 u/mes) |
| B | promedio mensual ≥ `sale_cat_demand_b_qty` (def: 50 u/mes) |
| C | promedio mensual ≥ `sale_cat_demand_c_qty` (def: 20 u/mes) |
| D | promedio mensual ≥ `sale_cat_demand_d_qty` (def: 5 u/mes) |
| E | promedio mensual < umbral D |

---

#### Modo Participación acumulada — Pareto (`sale_cat_mode = 'share'`)

| Concepto | Fórmula en español | Campo Odoo |
|---|---|---|
| Valor por unidades | Suma de unidades vendidas del producto en el período | `Σ stock.move.line.quantity` |
| Valor por importe | Suma de unidades vendidas × precio de lista actual | `× product.template.list_price` |
| Participación | Valor del producto ÷ valor total de todos los productos | Calculado |
| Acumulado | Suma de participaciones, ordenando de mayor a menor | Calculado |

| Categoría | Condición |
|---|---|
| A | acumulado ≤ `sale_cat_share_a_pct` (def: 50 %) |
| B | acumulado ≤ `sale_cat_share_b_pct` (def: 80 %) |
| C | acumulado ≤ `sale_cat_share_c_pct` (def: 95 %) |
| D | acumulado ≤ `sale_cat_share_d_pct` (def: 99 %) |
| E | resto |

---

### Forecast

#### KPIs globales del panel

| KPI | Fórmula en español | Campos Odoo |
|---|---|---|
| Forecast total | Suma de todas las cantidades de forecast del período | `Σ mrp.forecast.line.forecast_qty` |
| OFs planificadas | Suma de cantidades planificadas de OFs en estados habilitados con fecha fin en el período | `Σ mrp.production.product_qty` |
| Gap OFs | OFs planificadas − forecast total (negativo = déficit de cobertura) | Calculado |
| Cobertura % | OFs planificadas ÷ forecast total × 100, redondeado a 1 decimal | Calculado |
| Productos en riesgo | Cantidad de productos con cobertura por debajo del umbral de aviso | `cobertura_% < forecast_warning_pct` (def: 70 %) |
| Entregado total | Suma de unidades de salidas completadas del período, para productos con forecast | `Σ stock.move.quantity` donde `picking_type_code = 'outgoing'` y `state = 'done'` |
| Demanda OV | Suma de cantidades pedidas en órdenes de venta confirmadas o cerradas del período | `Σ sale.order.line.product_uom_qty` donde `order.state in ('sale','done')` |
| Tasa de servicio | entregado total ÷ demanda OV × 100, redondeado a 1 decimal | Calculado |
| Gap de demanda | (demanda OV − forecast total) ÷ forecast total × 100 (positivo = demanda superó el forecast) | Calculado |

**Colores de Tasa de servicio**

| Color | Condición |
|---|---|
| Verde | ≥ 95 % |
| Amarillo | entre 80 % y 94 % |
| Rojo | < 80 % |

**Colores de Gap de demanda** (sobre el valor absoluto)

| Color | Condición |
|---|---|
| Verde | \|gap\| ≤ 10 % (demanda alineada con forecast) |
| Amarillo | \|gap\| ≤ 25 % (desvío moderado) |
| Rojo | \|gap\| > 25 % (desvío significativo) |

**Colores de Gap de OFs**

| Color | Condición |
|---|---|
| Verde | gap ≥ 0 % (OFs cubren o superan el forecast) |
| Amarillo | gap entre −10 % y 0 % |
| Rojo | gap < −10 % |

---

#### Tabla forecast — columnas calculadas (matriz producto × mes)

Para cada celda (un producto en un mes específico):

| Columna | Fórmula en español | Campos Odoo |
|---|---|---|
| Forecast | Suma de líneas de forecast del producto para ese mes | `Σ mrp.forecast.line.forecast_qty` |
| OFs | Suma de cantidades planificadas de OFs del producto en ese mes (estados habilitados) | `Σ mrp.production.product_qty` |
| % Cobertura | OFs del mes ÷ forecast del mes × 100, redondeado a 1 decimal. Cero si no hay forecast | Calculado |
| Entregado | Suma de unidades de salidas completadas del producto en ese mes | `Σ stock.move.line.quantity` |
| Demanda real | Suma de cantidades pedidas en OVs confirmadas del producto en ese mes | `Σ sale.order.line.product_uom_qty` |
| Tasa de servicio | entregado ÷ demanda real × 100, redondeado a 1 decimal | Calculado |
| Gap de demanda | (demanda real − forecast) ÷ forecast × 100, redondeado a 1 decimal | Calculado |

**Colores de cobertura por celda**

| Color | Condición |
|---|---|
| Verde | cobertura ≥ 100 % |
| Amarillo | cobertura ≥ `forecast_warning_pct` (def: 70 %) |
| Rojo | cobertura < `forecast_warning_pct` |

**Totales por producto (columna de totales al final de cada fila)**

| Total | Fórmula en español |
|---|---|
| Total forecast | Suma de forecast de todos los meses del producto |
| Total OFs | Suma de OFs de todos los meses del producto |
| % Total | Total OFs ÷ Total forecast × 100 |
| Total entregado | Suma de entregado de todos los meses |
| Total demanda real | Suma de demanda real de todos los meses |
| Tasa de servicio total | Total entregado ÷ total demanda real × 100 |

---

#### Rotación de inventario (columna por producto)

| Concepto | Fórmula en español | Campo Odoo |
|---|---|---|
| Promedio mensual entregado | Total de unidades entregadas en el período ÷ cantidad de meses | `Σ stock.move.line.quantity` salidas completadas |
| Stock actual | Suma de cantidades en ubicaciones internas | `Σ stock.quant.quantity` |
| Rotación en meses | stock actual ÷ promedio mensual, redondeado a 1 decimal | Calculado |
| Rotación en días | stock actual ÷ promedio mensual × 30, redondeado a entero | Calculado |
| Unidad de visualización | Configurable: días o meses | `mrp.reschedule.config.forecast_rotation_unit` |

**Colores de rotación**

| Unidad | Verde | Amarillo | Gris (sin color) |
|---|---|---|---|
| Meses | ≤ 3 meses | entre 4 y 6 meses | > 6 meses |
| Días | ≤ 90 días | entre 91 y 180 días | > 180 días |

---

#### Fórmulas de precisión de forecast

> Todas las fórmulas usan **demanda OV** (`so_demand`) como referencia real: suma de `sale.order.line.product_uom_qty` de OVs confirmadas o cerradas del período. No son unidades entregadas físicamente.

Valores de base para cada período y producto:

| Variable | Descripción | Campo Odoo |
|---|---|---|
| `forecast_qty` | Cantidad planificada en el forecast del mes | `mrp.forecast.line.forecast_qty` |
| `so_demand` | Demanda real de OVs confirmadas en el período | `Σ sale.order.line.product_uom_qty` |
| `error_absoluto` | Valor absoluto de (demanda real − forecast) | Calculado |

---

**Simple**

| Concepto | Fórmula en español |
|---|---|
| Precisión por celda | demanda real ÷ forecast × 100, redondeado a 1 decimal (si hay forecast) |
| Precisión total | suma de demanda real de todos los períodos ÷ suma de forecast de todos los períodos × 100 |
| Interpretación | 100 % = coincidencia exacta. Más de 100 % = la demanda superó el forecast |

**MAPE — Error porcentual absoluto medio**

| Concepto | Fórmula en español |
|---|---|
| Precisión por celda | máximo(0, 100 − error absoluto ÷ demanda real × 100), redondeado a 1 decimal (solo si hay demanda real) |
| Precisión total | promedio de precisiones de todos los períodos con demanda real > 0 |
| Característica | Muy sensible a períodos con demanda baja o cero |

**WAPE — Error porcentual absoluto ponderado por demanda real**

| Concepto | Fórmula en español |
|---|---|
| Precisión total | máximo(0, 100 − suma de errores absolutos ÷ suma de demanda real × 100), redondeado a 1 decimal |
| Característica | Pondera más los períodos de mayor volumen real. Robusto cuando el forecast tiene ceros |

**WMAPE — Error porcentual absoluto ponderado por forecast**

| Concepto | Fórmula en español |
|---|---|
| Precisión total | máximo(0, 100 − suma de errores absolutos ÷ suma de forecast × 100), redondeado a 1 decimal |
| Característica | Pondera más los períodos de mayor volumen planificado. Estándar en supply chain |

**Sesgo (Bias)**

| Concepto | Fórmula en español |
|---|---|
| Sesgo por celda | (demanda real − forecast) ÷ forecast × 100, redondeado a 1 decimal (si hay forecast) |
| Sesgo total | (suma de demanda real − suma de forecast) ÷ suma de forecast × 100 |
| Interpretación | Positivo = la demanda superó sistemáticamente el forecast (forecast conservador). Negativo = forecast optimista |

**Colores de precisión**

| Fórmula | Verde | Amarillo | Rojo |
|---|---|---|---|
| Simple, MAPE, WAPE, WMAPE | ≥ 90 % | entre 70 % y 89 % | < 70 % |
| Sesgo | \|sesgo\| ≤ 10 % | \|sesgo\| entre 11 % y 20 % | \|sesgo\| > 20 % |

---

#### Categorías de cliente — métodos automáticos

El resultado se guarda en `res.partner.x_customer_category`. El período de análisis son los últimos 12 meses. Los umbrales Pareto son los mismos que para proveedores (`abc_pct_a/b/c/d`).

**ABC por volumen** (`customer_cat_method = 'abc_volume'`)

| Concepto | Detalle |
|---|---|
| **Valor por cliente** | Suma de importes de OVs confirmadas o cerradas en los últimos 12 meses |
| **Clasificación** | Pareto acumulado descendente: mayor volumen = A |
| **Campo** | `Σ sale.order.amount_total` donde `state in ('sale','done')` |

**ABC por frecuencia** (`customer_cat_method = 'abc_frequency'`)

| Concepto | Detalle |
|---|---|
| **Valor por cliente** | Cantidad de OVs confirmadas o cerradas en los últimos 12 meses |
| **Clasificación** | Pareto acumulado descendente: mayor frecuencia = A |
| **Campo** | `count(sale.order)` donde `state in ('sale','done')` |

**ABC por RFM** (`customer_cat_method = 'abc_rfm'`)

| Componente | Fórmula en español | Puntuación |
|---|---|---|
| Recencia (R) | Días desde la última OV hasta hoy | < 30 días = 3 pts / < 90 días = 2 pts / resto = 1 pt |
| Frecuencia (F) | Cantidad de OVs en el último año | > 10 OVs = 3 pts / ≥ 3 = 2 pts / resto = 1 pt |
| Monetario (M) | Importe total de OVs en el último año | ≥ percentil 66 del grupo = 3 pts / ≥ percentil 33 = 2 pts / resto = 1 pt |

| Puntaje total (R+F+M) | Categoría |
|---|---|
| 8 o 9 | A |
| 6 o 7 | B |
| 4 o 5 | C |
| 3 | D |
| Sin datos (sin OVs en el período) | E |
