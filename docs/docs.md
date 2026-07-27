# Documentación de fórmulas de cálculo

---

## Guía rápida: configuraciones que cambian metodología

Las configuraciones de esta tabla seleccionan entre **fórmulas o algoritmos distintos** — no solo cambian un umbral numérico. Para cada opción se indica qué método aplica y en qué sección se detalla.

### Reprogramación en cascada — criterio de prioridad

| Valor en Ajustes | Algoritmo |
|---|---|
| Orden cronológico (fecha actual) | Las OFs se ordenan por su fecha de inicio actual, de la más próxima a la más lejana |
| Más cortas primero (SPT) | Las OFs se ordenan por duración calculada, de menor a mayor (*Shortest Processing Time*) |
| Secuencia manual en el wizard | El operador define el orden arrastrando las OFs antes de ejecutar |

→ Ver *Criterio de prioridad al reprogramar*

### Comparativa y Forecast — criterio de OFs por período

| Valor en Ajustes | Qué OFs entran en el período | Cómo se calcula la cantidad |
|---|---|---|
| Por fecha de cierre (default) | Solo OFs cuya `date_finished` cae dentro del período | Se usa `product_qty` completa |
| Por solapamiento completo | Toda OF activa durante el período (inicio ≤ fin período y fin ≥ inicio período) | Se usan `product_qty` y `qty_produced` completos; una OF puede aparecer en varios períodos (doble conteo): no sumar períodos entre sí |
| Proporcional por duración | Toda OF activa durante el período | `product_qty × (segundos solapados ÷ duración total)`; el producido usa `move_finished_ids` con fecha en el período. Sin fecha de inicio válida: fallback a la fecha de cierre (cantidad completa si el cierre cae en el período), igual en comparativa y forecast |

Se configura en Ajustes → Producción → "Comparativa Producido vs. Programado" (`mrp.reschedule.config.comparison_date_mode`). Aplica tanto en el widget de comparativa como en la columna OFs del forecast.

→ Ver *Tabla Producido vs Programado — columnas calculadas* y *Tabla forecast — columnas calculadas*

### Quiebres de stock — método de rotación

| Valor en Ajustes | Fórmula |
|---|---|
| Por unidades | stock promedio (unidades) ÷ promedio mensual de salidas × 30 |
| Por COGS (a costo) | días del período × inventario promedio valorizado ÷ costo de lo vendido |
| Por ventas (a precio) | días del período × inventario promedio valorizado ÷ ventas netas (precio de lista) |

> El *stock promedio* (unidades) se calcula por **roll-back**: ancla en el stock actual y rueda hacia atrás con los flujos del período (ver detalle).

→ Ver *Rotación en quiebres de stock*

### Forecast — método de rotación de inventario

Mismas tres fórmulas que en Quiebres de stock; el período es el rango del forecast seleccionado.

→ Ver *Rotación de inventario (columna por producto)*

### Forecast — fuente de demanda para cobertura de inventario

| Valor en Ajustes | Denominador |
|---|---|
| Forecast planificado | total de forecast del período |
| Demanda real (pedidos SO) | total de unidades en OVs confirmadas del período |
| Entregado histórico | total de unidades entregadas (salidas completadas) del período |

→ Ver *Cobertura de inventario (columna por producto)*

### Forecast — divisor del % de cobertura de OFs

| Valor en Ajustes | Fórmula |
|---|---|
| Forecast planificado | OFs ÷ forecast × 100 |
| Demanda real (pedidos SO) | OFs ÷ unidades en OVs confirmadas × 100 |

→ Ver *Tabla forecast — columnas calculadas* (columna % Cobertura)

### Forecast — fórmula de precisión

| Valor en Ajustes | Método |
|---|---|
| Simple | real ÷ forecast × 100 |
| MAPE | promedio de (100 − \|error\|/real × 100) por período |
| WAPE | 100 − Σ\|error\| / Σreal × 100 (global, pondera por volumen real) |
| WMAPE | 100 − Σ\|error\| / Σforecast × 100 (global, pondera por volumen planificado) |
| Sesgo | (real − forecast) / forecast × 100 |

→ Ver *Fórmulas de precisión de forecast*

### Forecast — fuente del «real» para precisión

| Valor en Ajustes | Qué se usa como volumen real en las 5 fórmulas anteriores |
|---|---|
| Demanda confirmada (órdenes de venta) | unidades en OVs confirmadas o cerradas del período |
| Entregas completadas | unidades entregadas (salidas de stock completadas) del período |

→ Ver *Fórmulas de precisión de forecast — fuente del «real»*

### Categorías de venta — modo de asignación

| Valor en Ajustes | Método |
|---|---|
| Manual | El usuario asigna desde la ficha del artículo |
| Automática por rotación de inventario | Días de cobertura calculados a partir de stock ÷ (salidas o demanda ÷ meses); compara contra umbrales en días |
| Automática por demanda | Promedio mensual de unidades demandadas; compara contra umbrales en u./mes |
| Automática por participación acumulada (Pareto) | Pareto acumulado por unidades o por importe; compara contra umbrales en % acumulado |

→ Ver *Categorías de venta (A / B / C / D / E)*

### Categorías de venta — fuente del denominador de rotación

*(aplica solo cuando el modo es «Automática por rotación de inventario»)*

| Valor en Ajustes | Denominador |
|---|---|
| Entregas completadas | movimientos de salida completados en el período |
| Demanda confirmada (OVs) | unidades en OVs confirmadas del período |

→ Ver *Modo Rotación de inventario — fuente del denominador*

### Categorías de venta — métrica de participación acumulada

*(aplica solo cuando el modo es «Automática por participación acumulada (Pareto)»)*

| Valor en Ajustes | Ponderación |
|---|---|
| Unidades entregadas | ordena por unidades vendidas en el período |
| Importe (precio de lista × cantidad) | ordena por precio de lista × unidades vendidas |

→ Ver *Modo Participación acumulada — Pareto*

### Análisis de proveedores — referencia para variación de precio

| Valor en Ajustes | Precio de referencia |
|---|---|
| Costo estándar del producto | costo estándar del catálogo del producto |
| Lista de precio del proveedor | precio configurado en la lista de precios del proveedor para ese artículo; si no está, la variación queda sin valor |

→ Ver *Tabla de métricas — columna Variación de precio*

### Categorías de proveedor — método

| Valor en Ajustes | Algoritmo |
|---|---|
| Manual | Asignación directa desde la ficha del proveedor |
| ABC por volumen (importe OCs) | Pareto por importe total de OCs del último año |
| ABC por frecuencia (cantidad de OCs) | Pareto por cantidad de OCs del último año |
| ABC por RFM | Scoring R + F + M (1–3 pts c/u); cortes configurables en "Parámetros RFM" (def: A ≥ 8, B ≥ 6, C ≥ 4, D ≥ 3, E = sin datos) |
| ABC por % de entrega a tiempo | Pareto descendente por % de recepciones llegadas en fecha (excluye recepciones sin fecha) |
| ABC por variación de precio | Ranking por percentil de posición por \|var precio\| respecto al precio de referencia; menor = A |
| ABC por calidad — diferencia de cantidad | Pareto descendente por % de movimientos recibidos con cantidad exacta |
| ABC por calidad — devoluciones | Ranking por percentil de posición por cantidad de devoluciones; 0 devoluciones con actividad = A, sin actividad = E |
| ABC por calidad — combinado | Pareto descendente por promedio de % a tiempo y % sin diferencia de cantidad |

→ Ver *Categorías de proveedor — métodos automáticos*

### Categorías de cliente — método

| Valor en Ajustes | Algoritmo |
|---|---|
| Manual | Asignación directa desde la ficha del cliente |
| ABC por volumen (importe SOs) | Pareto por importe total de SOs confirmadas del último año |
| ABC por frecuencia (cantidad de SOs) | Pareto por cantidad de SOs del último año |
| ABC por RFM | Scoring R + F + M (1–3 pts c/u); mismos umbrales que categorías de proveedor |

→ Ver *Categorías de cliente — métodos automáticos*

### Análisis de clientes — método «entrega a tiempo»

| Valor en Ajustes | Definición de «a tiempo» |
|---|---|
| Fecha compromiso del pedido | Entrega a tiempo si fecha_entrega ≤ fecha_compromiso de la OV |
| Fecha programada del envío | Entrega a tiempo si fecha_entrega ≤ fecha_programada del envío saliente |
| Días desde confirmación del pedido | Entrega a tiempo si fecha_entrega ≤ fecha_confirmación + N días (SLA configurable) |

→ Ver *Análisis de clientes — % a tiempo*

---

## Panel de Producción

### Alertas de producción

#### OFs atrasadas

| Concepto                | Detalle                                                             |
| ----------------------- | ------------------------------------------------------------------- |
| **¿Cuándo se genera?**  | Cuando una OF activa tiene la fecha de fin planificada en el pasado |
| **Estados que aplican** | Confirmada, En progreso, Por cerrar                                 |
| **Excluye**             | OFs cuya lista de materiales es de tipo Subcontratación             |

**Días de atraso**

| Concepto       | Detalle                                                                           |
| -------------- | --------------------------------------------------------------------------------- |
| **Fórmula**    | máximo entre 0 y (fecha actual − fecha fin planificada de la OF), en días enteros |
| **Campo Odoo** | `mrp.production.date_finished`                                                    |
| **Nota**       | El resultado nunca es negativo                                                    |

**Severidad**

| Condición                       | Color    |
| ------------------------------- | -------- |
| Días de atraso ≥ umbral crítico | Roja     |
| Días de atraso < umbral crítico | Amarilla |

| Parámetro                | Campo                                          | Valor por defecto |
| ------------------------ | ---------------------------------------------- | ----------------- |
| Umbral días críticos OFs | `mrp.reschedule.config.alert_mo_critical_days` | 3 días            |

---

#### OFs por vencer

| Concepto               | Detalle                                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| **¿Cuándo se genera?** | Cuando una OF activa tiene la fecha de fin dentro de la ventana de aviso, pero aún no venció |
| **Condición**          | fecha actual < fecha fin planificada ≤ fecha actual + ventana de aviso                       |
| **Severidad**          | Siempre amarilla                                                                             |
| **Excluye**            | OFs de subcontratación                                                                       |

| Parámetro                | Campo                                         | Valor por defecto |
| ------------------------ | --------------------------------------------- | ----------------- |
| Ventana de aviso en días | `mrp.reschedule.config.alert_mo_warning_days` | 7 días            |

---

#### Cantidad diferente

| Concepto               | Detalle                                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------------------- |
| **¿Cuándo se genera?** | Cuando una OF recién cerrada produjo una cantidad que difiere de la planificada más allá de la tolerancia |
| **Estado que dispara** | OF pasa a Terminada                                                                                       |

**Cálculo del desvío**

| Concepto                       | Detalle                                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------------------------- |
| **Cantidad real**              | Suma de las cantidades de los movimientos de producto terminado con estado Hecho                  |
| **Desvío**                     | valor absoluto de (cantidad real − cantidad planificada) dividido por cantidad planificada        |
| **Condición de alerta**        | desvío > tolerancia configurada                                                                   |
| **Campo cantidad real**        | `stock.move.quantity` donde `move.state = 'done'` y `move.product_id = mrp.production.product_id` |
| **Campo cantidad planificada** | `mrp.production.product_qty`                                                                      |

**Severidad**

| Condición                                                      | Color    |
| -------------------------------------------------------------- | -------- |
| Cantidad real < cantidad planificada (producción insuficiente) | Roja     |
| Cantidad real > cantidad planificada (excedente)               | Amarilla |

| Parámetro            | Campo                                     | Valor por defecto |
| -------------------- | ----------------------------------------- | ----------------- |
| Tolerancia de desvío | `mrp.reschedule.config.qty_tolerance_pct` | 5 %               |

---

#### OFs canceladas

| Concepto               | Detalle                                     |
| ---------------------- | ------------------------------------------- |
| **¿Cuándo se genera?** | Cuando una OF pasa al estado Cancelada      |
| **Resolución**         | No se auto-resuelve, requiere acción manual |
| **Severidad**          | Siempre amarilla                            |
| **Excluye**            | OFs de subcontratación                      |

---

#### Tarjetas KPI de alertas de producción

Cada tarjeta cuenta alertas no resueltas (`resolved = False`), excluyendo las de OFs con LdM de subcontratación.

| Tarjeta          | Qué cuenta                                                         | Campo tipo alerta             |
| ---------------- | ------------------------------------------------------------------ | ----------------------------- |
| OFs atrasadas    | Alertas abiertas de OFs con fecha de fin vencida                   | `alert_type = 'mo_delayed'`   |
| OFs por vencer   | Alertas abiertas de OFs próximas a vencer                          | `alert_type = 'mo_upcoming'`  |
| Cant. diferentes | Alertas abiertas de OFs con cantidad producida fuera de tolerancia | `alert_type = 'qty_mismatch'` |
| OFs canceladas   | Alertas abiertas de OFs canceladas                                 | `alert_type = 'mo_cancelled'` |
| Badge críticas   | Total de alertas abiertas con severidad roja, de cualquier tipo    | `severity = 'critical'`       |

---

#### Tabla de alertas activas — columnas calculadas

| Columna             | Cómo se calcula                                        | Campo Odoo                                     |
| ------------------- | ------------------------------------------------------ | ---------------------------------------------- |
| Tipo                | Etiqueta traducida del tipo de alerta                  | `mrp.reschedule.alert.alert_type`              |
| Severidad           | Nivel de urgencia: roja o amarilla                     | `mrp.reschedule.alert.severity`                |
| OF / OC / Recepción | Registro origen de la alerta                           | Relación al documento según tipo               |
| Producto            | Nombre del producto involucrado                        | `mrp.reschedule.alert.product_id.display_name` |
| Días de atraso      | máximo(0, fecha actual − fecha de referencia), en días | Calculado en tiempo real                       |

**Fecha de referencia según tipo de alerta**

| Tipo de alerta                                             | Fecha de referencia                | Campo Odoo                     |
| ---------------------------------------------------------- | ---------------------------------- | ------------------------------ |
| OFs atrasadas / por vencer / cant. diferentes / canceladas | Fecha fin planificada de la OF     | `mrp.production.date_finished` |
| OCs vencidas / por vencer / canceladas                     | Fecha de entrega estimada de la OC | `purchase.order.date_planned`  |
| Recepciones atrasadas                                      | Fecha programada de la recepción   | `stock.picking.scheduled_date` |

---

### Órdenes de fabricación

#### Tarjetas KPI del widget OFs

| KPI              | Qué cuenta                                           | Condición                           |
| ---------------- | ---------------------------------------------------- | ----------------------------------- |
| Activas          | OFs que no están terminadas ni canceladas            | `state not in ('done', 'cancel')`   |
| En progreso      | OFs activas en fabricación o listas para cerrar      | `state in ('progress', 'to_close')` |
| Atrasadas        | OFs activas con fecha fin en el pasado               | `date_finished < fecha actual`      |
| Para reprogramar | OFs activas marcadas por el sistema para reprogramar | `x_reschedule_needed = True`        |
| Finalizadas      | OFs terminadas                                       | `state = 'done'`                    |
| Por cerrar       | OFs activas pendientes de cierre                     | `state = 'to_close'`                |

---

#### Tabla de OFs — columnas calculadas

Las OFs mostradas son las que solapan con el rango de fechas seleccionado y no están terminadas ni canceladas.

| Columna             | Cómo se calcula                                                          | Campo Odoo                                                                                             |
| ------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Referencia          | Nombre de la OF                                                          | `mrp.production.name`                                                                                  |
| Producto            | Nombre del producto a fabricar                                           | `mrp.production.product_id.display_name`                                                               |
| Cantidad            | Cantidad planificada a producir                                          | `mrp.production.product_qty`                                                                           |
| Fin planificado     | Fecha y hora de fin prevista                                             | `mrp.production.date_finished`                                                                         |
| Estado              | Estado actual de la OF                                                   | `mrp.production.state`                                                                                 |
| Atrasada            | Sí cuando la fecha fin ya pasó                                           | `date_finished < fecha actual`                                                                         |
| Reprogramar         | Sí cuando el sistema marcó la OF para reprogramar                        | `mrp.production.x_reschedule_needed`                                                                   |
| Entregas pendientes | Suma de cantidades de movimientos de salida pendientes para ese producto | `stock.move.product_uom_qty` donde `state not in ('done','cancel')` y `picking_type_code = 'outgoing'` |

---

#### Tabla de Solicitudes de Producción — columnas calculadas

| Columna          | Cómo se calcula                                        | Campo Odoo                                                        |
| ---------------- | ------------------------------------------------------ | ----------------------------------------------------------------- |
| Referencia       | Nombre de la solicitud                                 | `mrp.production.request.name`                                     |
| Disponible desde | Fecha mínima de inicio para las OFs de esta solicitud  | `mrp.production.request.start_from`                               |
| Estado           | Estado actual de la solicitud                          | `mrp.production.request.state`                                    |
| OFs totales      | Cantidad de OFs vinculadas a la solicitud              | Conteo de `item_ids.production_id`                                |
| OFs terminadas   | OFs de la solicitud con estado Terminada               | `production_id.state = 'done'`                                    |
| OFs retrasadas   | OFs de la solicitud activas con fecha fin en el pasado | `state not in ('done','cancel')` y `date_finished < fecha actual` |

**KPIs del widget de solicitudes**

| KPI              | Cómo se calcula                                                                       |
| ---------------- | ------------------------------------------------------------------------------------- |
| Total            | Solicitudes en estado Confirmada + Calculada                                          |
| Activas          | Solicitudes en estado Confirmada                                                      |
| Calculadas       | Solicitudes en estado Calculada                                                       |
| Para reprogramar | Solicitudes activas donde alguna OF tiene `x_reschedule_needed = True`                |
| OFs retrasadas   | Total de OFs en estado activo con fecha fin vencida, de todas las solicitudes activas |

---

#### Tabla Producido vs Programado — columnas calculadas

Agrupa las OFs del período por producto. El criterio que determina qué OFs entran en el período se configura en `mrp.reschedule.config.comparison_date_mode` (ver *Comparativa y Forecast — criterio de OFs por período* en la Guía rápida).

| Columna        | Fórmula en español                                                                     | Campo Odoo                               |
| -------------- | -------------------------------------------------------------------------------------- | ---------------------------------------- |
| Producto       | Nombre del producto                                                                    | `mrp.production.product_id.display_name` |
| Programado     | Suma de cantidades planificadas de las OFs del período para ese producto (puede ser fracción en modo proporcional) | `mrp.production.product_qty` (o fracción proporcional) |
| Producido      | Suma de cantidades producidas de las OFs del período. En modo proporcional, solo los movimientos reales con fecha en el período | `mrp.production.qty_produced` o `move_finished_ids` filtrados por fecha |
| % Cumplimiento | (producido ÷ programado) × 100, redondeado a 1 decimal. "s/plan" si se produjo sin cantidad programada (sin plan / sobreproducción); 0 % si no hubo ni producido ni programado | Calculado |

**Colores del % de cumplimiento**

| Color    | Condición                        |
| -------- | -------------------------------- |
| Verde    | % cumplimiento ≥ 90 %            |
| Amarillo | % cumplimiento entre 50 % y 89 % |
| Rojo     | % cumplimiento < 50 %            |

**KPIs globales del comparativo**

| KPI              | Fórmula en español                                                 |
| ---------------- | ------------------------------------------------------------------ |
| Total programado | Suma de cantidades programadas de todos los productos              |
| Total producido  | Suma de cantidades producidas de todos los productos               |
| % Global         | (total producido ÷ total programado) × 100, redondeado a 1 decimal; "s/plan" si hubo producido sin programado |
| OFs terminadas   | Cantidad de OFs con estado Terminada cuya `date_finished` cae en el período. Se cuenta siempre por fecha de fin, sin importar el criterio de fechas, por lo que puede no coincidir con las OFs del comparativo de cantidades |

---

### Carga de centros de trabajo

#### Horas disponibles

| Concepto             | Detalle                                                                                           |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| **Fórmula**          | Horas hábiles del calendario laboral del CT en el período × (eficiencia del CT ÷ 100)             |
| **Fallback**         | Si el calendario no puede calcularse, se estima en proporción a las horas semanales de asistencia |
| **Campo calendario** | `mrp.workcenter.resource_calendar_id`                                                             |
| **Campo eficiencia** | `mrp.workcenter.time_efficiency` (en %, por ejemplo 85 significa 85 %)                            |

---

#### Horas ejecutadas

| Concepto           | Detalle                                                                                            |
| ------------------ | -------------------------------------------------------------------------------------------------- |
| **Fórmula**        | Suma de la duración **real** de las operaciones **terminadas dentro del período** (por fecha de fin) |
| **Estado / fecha** | `state = 'done'` y `date_finished` dentro de `[inicio, fin]` del período                            |
| **Campo duración** | `mrp.workorder.duration` (duración real, en minutos → horas dividiendo por 60)                      |

> No se prorratea por solapamiento: se suma la duración real completa de cada operación terminada en el período. Si las operaciones no registran tiempo real (`duration = 0`), las horas ejecutadas serán 0 aunque la operación esté terminada.

---

#### Horas pendientes

| Concepto           | Detalle                                                                                         |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| **Fórmula**        | Suma de la duración **planificada** de las operaciones **no terminadas** que solapan el período |
| **Estado**         | Cualquier estado excepto Terminada y Cancelada                                                   |
| **Campo duración** | `mrp.workorder.duration_expected` (tiempo estándar, en minutos → horas)                         |

---

#### Horas planificadas

| Concepto    | Detalle                                                                                             |
| ----------- | --------------------------------------------------------------------------------------------------- |
| **Fórmula** | `duration_expected` de las operaciones terminadas del período + horas pendientes (todo lo planificado) |

---

#### Tiempo muerto, tiempo no planificado y carga del CT

| Indicador             | Fórmula en español                                                          | Nota                          |
| --------------------- | --------------------------------------------------------------------------- | ----------------------------- |
| Tiempo muerto         | máximo(0, horas disponibles − horas ejecutadas − horas pendientes)          | Capacidad disponible ociosa   |
| Tiempo no planificado | máximo(0, horas ejecutadas − duración planificada de las operaciones terminadas) | Ejecución que superó el plan (o sin plan) |
| Carga %               | horas planificadas ÷ horas disponibles × 100                                | Cero si no hay disponibles    |

**Colores de carga**

| Color    | Condición               |
| -------- | ----------------------- |
| Verde    | Carga < 70 %            |
| Amarillo | Carga entre 70 % y 89 % |
| Rojo     | Carga ≥ 90 %            |

---

#### Series del gráfico de carga (barras apiladas)

El gráfico muestra dos stacks por cada centro de trabajo:

| Serie          | Stack | Valor                                            |
| -------------- | ----- | ------------------------------------------------ |
| Planificado    | Plan  | horas planificadas (`duration_expected`)         |
| Sin planificar | Plan  | máximo(0, disponible − planificado)              |
| Ejecutado      | Real  | horas ejecutadas (duración real de terminadas)   |
| Pendiente      | Real  | horas pendientes                                 |
| Tiempo muerto  | Real  | capacidad ociosa                                 |
| No planificado | Real  | ejecución fuera del plan (puede exceder el total) |

---

#### Tabla de centros de trabajo — columnas calculadas

| Columna           | Fórmula en español                                             | Campo / Fuente                                              |
| ----------------- | -------------------------------------------------------------- | ----------------------------------------------------------- |
| Centro de trabajo | Nombre del CT                                                  | `mrp.workcenter.name`                                       |
| Disponible (h)    | Horas hábiles del calendario × eficiencia                      | `resource_calendar_id`, `time_efficiency`                   |
| Ejecutado (h)     | Suma de horas de operaciones terminadas que solapan el período | `mrp.workorder.duration_expected`, `state = 'done'`         |
| Pendiente (h)     | Suma de horas de operaciones activas que solapan el período    | `mrp.workorder.duration_expected`, `state != 'done/cancel'` |
| Tiempo libre (h)  | disponible − ejecutado − pendiente (mínimo 0)                  | Calculado                                                   |
| Carga %           | (ejecutado + pendiente) ÷ disponible × 100                     | Calculado                                                   |

---

### Quiebres de stock

#### Fórmula de quiebre

| Concepto                  | Detalle                                                                                                                               |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Stock actual**          | Suma de cantidades en las ubicaciones internas de la ubicación configurada                                                            |
| **Mínimo**                | Cantidad mínima configurada en el punto de reorden del producto (ruta Fabricación). Si hay varios puntos de reorden, se toma el mayor |
| **Condición de quiebre**  | stock actual < mínimo (con tolerancia de 0.001 unidades)                                                                              |
| **Campo stock**           | `stock.quant.quantity` en ubicaciones con `usage = 'internal'`                                                                        |
| **Campo mínimo**          | `stock.warehouse.orderpoint.product_min_qty` donde `route_id = ruta Fabricación`                                                      |
| **Ubicación configurada** | `mrp.reschedule.config.stock_location_id` (si no está configurada, se usan todas las internas)                                        |

---

#### KPIs del widget de quiebres

| KPI         | Qué cuenta                                                         |
| ----------- | ------------------------------------------------------------------ |
| Total       | Productos con línea de forecast O con punto de reorden configurado |
| Con quiebre | Productos con punto de reorden donde stock actual < mínimo         |
| OK          | Productos con punto de reorden donde stock actual ≥ mínimo         |
| Sin mínimo  | Productos sin punto de reorden configurado (ruta Fabricación)      |

---

#### Agrupamiento por tabs en quiebres

El widget permite agrupar la tabla mediante nav-tabs (pestañas encima de la tabla), igual que el widget de Forecast. Los criterios de agrupamiento disponibles son:

| Criterio | Campo de agrupamiento | Condición de disponibilidad |
|---|---|---|
| Categoría | `product.template.categ_id.name` | Siempre disponible |
| Cat. venta | `product.template.x_sale_category` | Solo cuando las categorías de venta están habilitadas en configuración |

Al activar un agrupamiento, los tabs muestran cada grupo con su conteo de productos. El tab activo filtra la tabla al grupo seleccionado; el paginado se reinicia al cambiar de tab.

El nombre de la categoría mostrado en los tabs y en el dropdown de ubicaciones corresponde al nodo hoja (`name`), no al nombre completo de la jerarquía (`complete_name`). Lo mismo aplica para la columna Familia en el forecast y el dropdown de familias en ventas.

---

#### Tabla de quiebres — columnas calculadas

| Columna      | Fórmula en español                                     | Campo Odoo                                   |
| ------------ | ------------------------------------------------------ | -------------------------------------------- |
| Artículo     | Nombre del producto                                    | `product.template.display_name`              |
| Tipo         | Tipos de producto asignados al artículo (concatenados) | `product.template.x_product_type_ids`        |
| Stock actual | Suma de cantidades en ubicaciones internas             | `stock.quant.quantity`                       |
| Mínimo       | Cantidad mínima del punto de reorden                   | `stock.warehouse.orderpoint.product_min_qty` |
| Diferencia   | stock actual − mínimo (negativo indica quiebre)        | Calculado                                    |
| Estado       | `Quiebre` / `OK` / `Sin mínimo` según condición        | Calculado                                    |

---

#### OFs activas por producto (acordeón)

Al expandir un producto, se muestran sus OFs activas:

| Concepto   | Detalle                                                                                     |
| ---------- | ------------------------------------------------------------------------------------------- |
| **Filtro** | OFs del producto en estado Confirmada, En progreso o Por cerrar, excluyendo subcontratación |
| **Orden**  | Por fecha fin ascendente                                                                    |
| **Límite** | 50 OFs como máximo                                                                          |

---

#### Rotación en quiebres de stock

El widget calcula los días de inventario (DIO) usando el mismo método configurado en `mrp.reschedule.config.stock_break_rotation_method`. El período es `rotation_months_cfg × 30` días.

**Por unidades (`stock_break_rotation_method = 'units'`)**

```
S_avg = (stock_inicio + stock_fin) / 2           [unidades]
DIO   = S_avg / (salidas_periodo / n_meses) × 30
```

| Variable | Detalle |
|---|---|
| `stock_fin` | Stock **actual** (el período de rotación termina hoy) — snapshot de `stock.quant`, warehouse-scoped |
| `stock_inicio` | `stock_fin − entradas_periodo + salidas_periodo` (roll-back desde el stock actual) |
| `salidas_periodo` | Suma de salidas que cruzan la frontera de las ubicaciones seleccionadas en el período |
| `n_meses` | Número de meses del período configurado |

> **Roll-back:** se ancla en el stock actual (exacto) y se rueda hacia atrás con los flujos del período, en vez de reconstruir sumando todo el historial. Consistente con la columna de stock actual (mismas ubicaciones).

**Por COGS — a costo (`stock_break_rotation_method = 'cogs'`)**

```
S_avg_val = (inv_inicio_costo + inv_fin_costo) / 2    [valor monetario]
DIO       = D × S_avg_val / COGS
```

| Variable | Detalle |
|---|---|
| `inv_inicio_costo` | Stock inicial × costo estándar del producto |
| `inv_fin_costo` | Stock final × costo estándar del producto |
| `COGS` | Suma de `price_unit × quantity` de los movimientos de salida completados |
| `D` | Días del período (`rotation_months_cfg × 30`) |

**Por ventas — a precio de venta (`stock_break_rotation_method = 'sales'`)**

```
S_avg_val = (inv_inicio_precio + inv_fin_precio) / 2  [valor monetario]
DIO       = D × S_avg_val / V_net
```

| Variable | Detalle |
|---|---|
| `inv_inicio_precio` | Stock inicial × precio de lista del producto |
| `inv_fin_precio` | Stock final × precio de lista del producto |
| `V_net` | Suma de `price_unit × quantity` de los movimientos de salida (valorados a precio de lista) |
| `D` | Días del período |

---

### Reprogramación en cascada

#### Duración de una OF

El sistema intenta calcular la duración en este orden:

| Prioridad           | Fórmula en español                                                                    | Campos Odoo                                                  |
| ------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| 1 — Con operaciones | Suma de duraciones esperadas de todas las operaciones, convertidas de minutos a horas | `mrp.workorder.duration_expected` ÷ 60                       |
| 2 — Con fechas      | Diferencia entre fecha fin y fecha inicio de la OF, en horas                          | `mrp.production.date_finished` − `mrp.production.date_start` |
| 3 — Fallback        | Se asumen 8 horas                                                                     | Valor fijo                                                   |

---

#### Delta de reprogramación

| Concepto             | Fórmula en español                              | Formato       |
| -------------------- | ----------------------------------------------- | ------------- |
| Diferencia de fechas | nueva fecha fin − fecha fin actual, en segundos | Interno       |
| Días                 | parte entera de (diferencia en horas ÷ 24)      | Número entero |
| Horas restantes      | resto de (diferencia en horas ÷ 24)             | Número entero |
| Visualización        | `+2d 3h` si se adelanta, `-1d 0h` si se atrasa  | Texto         |

---

#### Secuenciación de operaciones por CT

Cada operación se programa desde el momento en que el CT queda libre. Ninguna operación puede empezar antes de que el CT esté disponible.

Si se ajusta la duración total de la OF, cada operación se escala proporcionalmente:

| Concepto                         | Fórmula en español                                                | Campo Odoo                        |
| -------------------------------- | ----------------------------------------------------------------- | --------------------------------- |
| Factor de escala                 | duración total ajustada ÷ suma de duraciones esperadas originales | `mrp.workorder.duration_expected` |
| Nueva duración de cada operación | duración esperada original × factor de escala                     | Calculado                         |

---

#### Criterio de prioridad al reprogramar

Configurable en `mrp.reschedule.config.priority`. Determina en qué orden se colocan las OFs en el plan antes de ejecutar la reprogramación en cascada.

| Valor (`priority`) | Algoritmo | Criterio de ordenación |
|---|---|---|
| `chronological` | Orden cronológico | `date_start` ascendente — primero las OFs con inicio más próximo |
| `shortest_first` | Más cortas primero (SPT) | `duration_hours` ascendente — minimiza el tiempo promedio de espera (Shortest Processing Time) |
| `manual` | Secuencia manual | El operador reordena las OFs en el wizard de reprogramación antes de ejecutar; el sistema respeta ese orden |

> **Nota SPT:** La duración se calcula según la prioridad descripta en *Duración de una OF* (operaciones → fechas → fallback 8 h).

---

## Panel de Compras

### Alertas de compras

#### OCs vencidas

| Concepto                | Detalle                                                                |
| ----------------------- | ---------------------------------------------------------------------- |
| **¿Cuándo se genera?**  | Cuando una OC aprobada tiene la fecha de entrega estimada en el pasado |
| **Campo de referencia** | `purchase.order.date_planned` (entrega estimada, no fecha de emisión)  |

**Días de atraso y severidad**

| Concepto           | Fórmula en español                                                   | Campo                                                        |
| ------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------ |
| Días de atraso     | máximo(0, fecha actual − fecha de entrega estimada), en días enteros | `purchase.order.date_planned`                                |
| Severidad roja     | días de atraso ≥ umbral crítico OCs                                  | `mrp.reschedule.config.alert_po_critical_days` (def: 5 días) |
| Severidad amarilla | días de atraso < umbral crítico OCs                                  | —                                                            |

---

#### OCs por vencer

| Concepto               | Detalle                                                                                                                     |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **¿Cuándo se genera?** | Cuando una OC aprobada y no totalmente recibida tiene la fecha de entrega dentro de la ventana de aviso, pero aún no venció |
| **Condición**          | fecha actual < fecha entrega estimada ≤ fecha actual + ventana de aviso                                                     |
| **Severidad**          | Siempre amarilla                                                                                                            |

| Parámetro                | Campo                                         | Valor por defecto |
| ------------------------ | --------------------------------------------- | ----------------- |
| Ventana de aviso en días | `mrp.reschedule.config.alert_po_warning_days` | 10 días           |

---

#### Recepciones atrasadas

| Concepto               | Detalle                                                               |
| ---------------------- | --------------------------------------------------------------------- |
| **¿Cuándo se genera?** | Cuando una recepción pendiente tiene la fecha programada en el pasado |

**Días de atraso y severidad**

| Concepto           | Fórmula en español                                                          | Campo                                                             |
| ------------------ | --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Días de atraso     | máximo(0, fecha actual − fecha programada de la recepción), en días enteros | `stock.picking.scheduled_date`                                    |
| Severidad roja     | días de atraso ≥ umbral crítico recepciones                                 | `mrp.reschedule.config.alert_receipt_critical_days` (def: 3 días) |
| Severidad amarilla | días de atraso < umbral crítico recepciones                                 | —                                                                 |

---

#### Tarjetas KPI de alertas de compras

| Tarjeta        | Qué cuenta                                  | Campo tipo alerta                |
| -------------- | ------------------------------------------- | -------------------------------- |
| OCs vencidas   | Alertas abiertas de OCs con entrega vencida | `alert_type = 'po_delayed'`      |
| OCs por vencer | Alertas abiertas de OCs próximas a vencer   | `alert_type = 'po_upcoming'`     |
| OCs canceladas | Alertas abiertas de OCs canceladas          | `alert_type = 'po_cancelled'`    |
| Recepciones    | Alertas abiertas de recepciones atrasadas   | `alert_type = 'receipt_delayed'` |

---

### Órdenes de compra

#### Tarjetas KPI del widget OCs

| KPI             | Fórmula en español                                           | Condición Odoo                                                |
| --------------- | ------------------------------------------------------------ | ------------------------------------------------------------- |
| Cotizaciones    | OCs en borrador o enviadas al proveedor                      | `state in ('draft', 'sent')`                                  |
| Por aprobar     | OCs pendientes de aprobación interna                         | `state = 'to approve'`                                        |
| Total aprobadas | OCs confirmadas con entrega pendiente                        | `state = 'purchase'`                                          |
| A tiempo        | Del total aprobadas: con fecha de entrega futura o sin fecha | `date_planned > fecha actual`                                 |
| Vencidas        | Del total aprobadas: con fecha de entrega en el pasado       | `date_planned ≤ fecha actual`                                 |
| Críticas        | De las vencidas: con atraso mayor al umbral crítico          | `(fecha actual − date_planned).días ≥ alert_po_critical_days` |

> **Alcance (multiempresa).** Todos los KPIs y listas del panel de OCs se acotan a la **empresa activa** (`company_id`), igual que el resto del módulo. Cada KPI filtra el rango de fechas por su propio campo (Cotizaciones/Por aprobar por `date_order`, Total aprobadas por `date_approve`, A tiempo/Vencidas/Críticas por `date_planned`), por eso Aprobadas ≠ A tiempo + Vencidas.
>
> **OCs de servicio.** Si `exclude_service_pos` está activo, las OCs cuyas líneas son **todas** de tipo servicio se excluyen de los contadores (aparecen en la pestaña «Servicios» si está habilitada). Este flag se lee de la configuración de **cada empresa**: cada compañía tiene su propio registro de configuración, creado automáticamente si no existía.

---

#### Tabla de OCs — columnas calculadas

| Columna          | Fórmula en español                                                           | Campo Odoo                               |
| ---------------- | ---------------------------------------------------------------------------- | ---------------------------------------- |
| Referencia       | Número de la OC                                                              | `purchase.order.name`                    |
| Proveedor        | Nombre del proveedor                                                         | `purchase.order.partner_id.display_name` |
| Entrega estimada | Fecha de entrega comprometida                                                | `purchase.order.date_planned`            |
| Monto total      | Importe total de la OC en su moneda                                          | `purchase.order.amount_total`            |
| Vencida          | Sí cuando la fecha de entrega ya pasó                                        | `date_planned < fecha actual`            |
| Días vencida     | máximo(0, fecha actual − fecha de entrega), en días. Cero si no está vencida | Calculado                                |

---

#### Disponibilidad de recepciones — columnas calculadas

El estado de disponibilidad combina el estado del picking con las cantidades reservadas en sus movimientos:

| Estado mostrado         | Condición                                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------ |
| Disponible              | El picking está asignado y todas las líneas tienen cantidad reservada ≥ cantidad demandada |
| Parcialmente disponible | El picking está asignado con alguna línea incompleta, o confirmado con algo reservado      |
| No disponible           | El picking está confirmado sin reservas, o en estado En espera                             |

| Columna                       | Fórmula en español                                                            | Campo Odoo                                                   |
| ----------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Cantidad disponible por línea | el mayor entre cantidad reservada y cantidad ya procesada                     | `max(stock.move.reserved_availability, stock.move.quantity)` |
| Días de retraso               | máximo(0, fecha actual − fecha programada), en días. Cero si no está atrasada | `stock.picking.scheduled_date`                               |

---

#### Entregas a subcontratistas — trazado de OF origen

Para cada entrega, el sistema busca la OF de fabricación origen en este orden:

| Prioridad | Estrategia                                                                   |
| --------- | ---------------------------------------------------------------------------- |
| 1         | Campo directo `raw_material_production_id` en los movimientos del picking    |
| 2         | Seguir los destinos de los movimientos iterativamente hasta encontrar una OF |
| 3         | Buscar en las líneas de la OC asociada al picking                            |
| 4         | Buscar por grupo de abastecimiento compartido entre el picking y alguna OF   |

| Columna            | Fuente                                                                |
| ------------------ | --------------------------------------------------------------------- |
| N° OC              | `mrp.production.purchase_line_id.order_id.name` (de la OF encontrada) |
| Producto terminado | `mrp.production.product_id.display_name` (de la OF encontrada)        |
| Proveedor          | `stock.picking.partner_id.display_name`                               |

---

### Análisis de proveedores

#### Tabla de métricas — columnas calculadas

La fuente son las recepciones (`stock.picking`) con estado Hecho y tipo Entrante del período seleccionado.

| Métrica                   | Fórmula en español                                                                | Campos Odoo                                                                       |
| ------------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| OCs                       | Cantidad de OCs aprobadas o cerradas del proveedor en el período                  | `count(purchase.order)` donde `state in ('purchase','done')`                      |
| Artículos distintos       | Cantidad de productos distintos comprados al proveedor en el período              | `len(set(purchase.order.line.product_id))`                                        |
| Monto                     | Suma de importes de todas las OCs del proveedor en el período                     | `Σ purchase.order.amount_total`                                                   |
| % A tiempo                | Recepciones llegadas en fecha ÷ total de recepciones × 100                        | `on_time_count / pick_count × 100` donde `date_done ≤ scheduled_date`             |
| Retraso promedio (días)   | Promedio de días de atraso, solo sobre las recepciones que llegaron tarde         | `Σ(date_done − scheduled_date).días / count` donde `date_done > scheduled_date`   |
| % Completas               | Recepciones sin backorder ÷ total de recepciones × 100                            | `complete_count / pick_count × 100` donde el picking no generó backorder          |
| Lead time promedio (días) | Promedio de días desde la aprobación de la OC hasta el cierre de la recepción     | `Σ(stock.picking.date_done − purchase.order.date_approve).días / count`           |
| Variación de precio (%)   | Promedio firmado de la diferencia entre precio pagado y precio de referencia, por línea | Fórmula dependiente de `supplier_price_var_method` (ver abajo) |
| Facturas pendientes       | Suma de saldos pendientes de pago de facturas del proveedor                       | `Σ account.move.amount_residual` donde `payment_state not in ('paid','reversed')` |

**Variación de precio — precio de referencia (`supplier_price_var_method`)**

| Valor | Precio de referencia | Fórmula de la columna |
|---|---|---|
| `standard` (por defecto) | Costo estándar del producto (`product.template.standard_price`) | `Σ((price_unit − standard_price) / standard_price × 100) / count` |
| `pricelist` | Precio configurado para ese proveedor en `product.supplierinfo` | `Σ((price_unit − pricelist_price) / pricelist_price × 100) / count` |

> Si para un artículo no hay precio de proveedor configurado (`product.supplierinfo` vacío) y el método es `pricelist`, esa línea no aporta al promedio (se ignora).

> La variación de precio puede ser negativa si el precio pagado fue menor al de referencia. La clasificación ABC usa el valor absoluto.

**KPI global de % a tiempo (ponderado, no promedio de promedios)**

| Concepto          | Fórmula en español                                                                      |
| ----------------- | --------------------------------------------------------------------------------------- |
| % a tiempo global | suma de recepciones a tiempo de todos los proveedores ÷ suma total de recepciones × 100 |

**Colores por umbral (configurables)**

| Métrica          | Verde                                          | Amarillo                                         | Rojo           |
| ---------------- | ---------------------------------------------- | ------------------------------------------------ | -------------- |
| % A tiempo       | ≥ `sup_on_time_green_pct` (def: 90 %)          | ≥ `sup_on_time_yellow_pct` (def: 70 %)           | < 70 %         |
| Retraso promedio | ≤ `sup_delay_green_days` (def: 1 día)          | ≤ `sup_delay_yellow_days` (def: 3 días)          | > 3 días       |
| % Completas      | ≥ `sup_complete_green_pct` (def: 95 %)         | ≥ `sup_complete_yellow_pct` (def: 80 %)          | < 80 %         |
| Variación precio | \|var\| ≤ `sup_price_var_green_pct` (def: 3 %) | \|var\| ≤ `sup_price_var_yellow_pct` (def: 10 %) | \|var\| > 10 % |

---

#### Categorías de proveedor — métodos automáticos

El resultado se guarda en `mrp.partner.company.category` (campo computed `res.partner.x_supplier_category`, por empresa). El período de análisis es configurable: `supplier_cat_lookback_months` en `mrp.reschedule.config` (def: 12 meses).

**Umbrales Pareto comunes** (aplican a todos los métodos excepto RFM y Manual):

| Categoría | Condición            | Parámetro               |
| --------- | -------------------- | ----------------------- |
| A         | acumulado ≤ umbral A | `abc_pct_a` (def: 20 %) |
| B         | acumulado ≤ umbral B | `abc_pct_b` (def: 50 %) |
| C         | acumulado ≤ umbral C | `abc_pct_c` (def: 80 %) |
| D         | acumulado ≤ umbral D | `abc_pct_d` (def: 95 %) |
| E         | resto                | —                       |

> Cada registro se clasifica por el acumulado **antes** de sumar su propia participación (acumulado exclusivo): así el registro más grande siempre cae en A, aunque por sí solo supere el umbral A.

---

**ABC por volumen** (`supplier_cat_method = 'abc_volume'`)

| Concepto                | Detalle                                                                |
| ----------------------- | ---------------------------------------------------------------------- |
| **Valor por proveedor** | Suma de importes de OCs confirmadas o cerradas en el período configurado |
| **Clasificación**       | Pareto acumulado descendente: mayor importe = A                        |
| **Campo**               | `Σ purchase.order.amount_total` donde `state in ('purchase','done')`   |

---

**ABC por frecuencia** (`supplier_cat_method = 'abc_frequency'`)

| Concepto                | Detalle                                                        |
| ----------------------- | -------------------------------------------------------------- |
| **Valor por proveedor** | Cantidad de OCs confirmadas o cerradas en el período configurado |
| **Clasificación**       | Pareto acumulado descendente: mayor frecuencia = A             |
| **Campo**               | `count(purchase.order)` donde `state in ('purchase','done')`   |

---

**ABC por RFM** (`supplier_cat_method = 'abc_rfm'`)

| Componente     | Fórmula en español                    | Puntuación                                                               |
| -------------- | ------------------------------------- | ------------------------------------------------------------------------ |
| Recencia (R)   | Días desde la última OC hasta hoy     | < `rfm_recency_recent_days` (30) = 3 pts / < `rfm_recency_medium_days` (90) = 2 pts / resto = 1 pt |
| Frecuencia (F) | Cantidad de OCs en el último año      | > `rfm_freq_high` (10) = 3 pts / ≥ `rfm_freq_medium` (3) = 2 pts / resto = 1 pt |
| Monetario (M)  | Importe total de OCs en el último año | ≥ percentil 66 del grupo = 3 pts / ≥ percentil 33 = 2 pts / resto = 1 pt |

Cortes del puntaje configurables en Ajustes → "Parámetros RFM" (entre paréntesis los defaults):

| Puntaje total (R+F+M)             | Categoría |
| --------------------------------- | --------- |
| ≥ `rfm_score_a` (8)               | A         |
| ≥ `rfm_score_b` (6)               | B         |
| ≥ `rfm_score_c` (4)               | C         |
| ≥ `rfm_score_d` (3)               | D         |
| Sin datos (sin OCs en el período) | E         |

---

**ABC por % entrega a tiempo** (`supplier_cat_method = 'abc_delivery_pct'`)

| Concepto                | Detalle                                                    |
| ----------------------- | ---------------------------------------------------------- |
| **Valor por proveedor** | Recepciones llegadas en fecha ÷ recepciones con fecha × 100 (las recepciones sin fecha planificada o de recepción se excluyen del denominador) |
| **Clasificación**       | Pareto acumulado descendente: mayor % a tiempo = A         |

---

**ABC por variación de precio** (`supplier_cat_method = 'abc_price_var'`)

| Concepto                | Detalle                                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| **Valor por proveedor** | Promedio de \|precio − referencia\| ÷ referencia × 100. Referencia configurable en `supplier_price_var_method`: costo estándar (`standard`), lista de proveedor (`pricelist`) o precio anterior pagado (`previous`, default). Misma referencia que la columna del análisis de proveedores |
| **Clasificación**       | Ranking por percentil de posición (ascendente): menor variación = A. Reparte por cuotas fijas de proveedores, no por participación acumulada |
| **Campos**              | `purchase.order.line.price_unit` vs. `product.product.standard_price` / `product.supplierinfo.price` / precio de la compra previa (según config) |

---

**ABC por calidad — exactitud de cantidad** (`supplier_cat_method = 'abc_quality_qty'`)

| Concepto                | Detalle                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------- |
| **Valor por proveedor** | Movimientos recibidos con cantidad exacta ÷ total de movimientos × 100              |
| **Exactitud**           | Se considera exacta cuando \|cantidad recibida − cantidad pedida\| < 0,001 unidades |
| **Clasificación**       | Pareto acumulado descendente: mayor % exactitud = A                                 |

---

**ABC por calidad — devoluciones** (`supplier_cat_method = 'abc_quality_returns'`)

| Concepto                | Detalle                                                             |
| ----------------------- | ------------------------------------------------------------------- |
| **Valor por proveedor** | Cantidad de recepciones revertidas al proveedor en el período (0 si tuvo compras y ninguna devolución)    |
| **Clasificación**       | Ranking por percentil de posición: menos devoluciones = A. Proveedores con compras y 0 devoluciones = A; sin actividad de compra en el período = E (sin datos) |

---

**ABC por calidad — combinado** (`supplier_cat_method = 'abc_quality_combo'`)

| Concepto                | Detalle                                                                                |
| ----------------------- | -------------------------------------------------------------------------------------- |
| **Valor por proveedor** | Promedio simple entre % de recepciones a tiempo y % de recepciones con cantidad exacta |
| **Clasificación**       | Pareto acumulado descendente: mayor promedio = A                                       |

---

## Panel de Ventas

### Productos más vendidos

#### Cantidad vendida y monto

| Concepto         | Fórmula en español                                                                                      | Campo Odoo                                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Cantidad vendida | Suma de unidades de las salidas completadas del período, agrupado por producto base (suma de variantes) | `Σ stock.move.line.quantity` donde `picking_type_code = 'outgoing'` y `state = 'done'` y `product_id.sale_ok = True` |
| Importe          | cantidad vendida × precio de lista vigente del producto                                                 | `product.template.list_price`                                                                                        |
| Período          | Ventana deslizante configurable: 1, 3, 6 o 12 meses hacia atrás desde hoy                               | —                                                                                                                    |

> El importe es una **aproximación**: usa el precio de lista actual, no el precio real de cada venta.

---

#### Tabla de productos más vendidos — columnas calculadas

| Columna       | Fórmula en español                                                         | Campo Odoo                         |
| ------------- | -------------------------------------------------------------------------- | ---------------------------------- |
| Artículo      | Nombre del producto                                                        | `product.template.name`            |
| Código        | Referencia interna                                                         | `product.template.default_code`    |
| Categoría ABC | Categoría de venta asignada (si está habilitada)                           | `product.template.x_sale_category` |
| Cantidad      | Suma de unidades vendidas en el período (todas las variantes del producto) | `Σ stock.move.line.quantity`       |
| Importe       | Cantidad × precio de lista actual                                          | Calculado                          |

---

#### Gráfico de dona por categoría ABC

| Dato del segmento | Fórmula en español                                                         |
| ----------------- | -------------------------------------------------------------------------- |
| SKUs              | Cantidad de productos distintos en esa categoría                           |
| Cantidad total    | Suma de unidades vendidas de todos los productos de esa categoría          |
| Importe total     | Suma de importes de todos los productos de esa categoría                   |
| % del segmento    | SKUs de la categoría ÷ total de SKUs mostrados × 100 (se muestra si ≥ 5 %) |

---

### Categorías de venta (A / B / C / D / E)

El resultado se guarda en `product.template.x_sale_category`. La fuente son salidas completadas del período de análisis configurado.

| Parámetro           | Campo                                            | Valor por defecto |
| ------------------- | ------------------------------------------------ | ----------------- |
| Período de análisis | `mrp.reschedule.config.sale_cat_lookback_months` | 3 meses           |

---

#### Modo Rotación de inventario (`sale_cat_mode = 'automatic'`)

| Concepto            | Fórmula en español                                                        | Campo Odoo                                       |
| ------------------- | ------------------------------------------------------------------------- | ------------------------------------------------ |
| Denominador período | Volumen del período (según `sale_cat_rotation_source`, ver abajo)         | Ver tabla inferior                               |
| Promedio mensual    | Denominador período ÷ cantidad de meses del período                       | —                                                |
| Stock actual        | Suma de cantidades en ubicaciones internas, por producto base             | `Σ stock.quant.quantity`                         |
| Días de rotación    | (stock actual ÷ promedio mensual) × 30, redondeado. Si no hay ventas: 999 | Calculado                                        |

**Fuente del denominador de rotación (`sale_cat_rotation_source`)**

| Valor | Denominador |
|---|---|
| `delivery` (por defecto) | Suma de unidades entregadas (salidas completadas) del período: `Σ stock.move.line.quantity` |
| `demand` | Suma de unidades en OVs confirmadas del período: `Σ sale.order.line.product_uom_qty` |

| Categoría | Condición                                            |
| --------- | ---------------------------------------------------- |
| A         | días de rotación ≤ `sale_cat_a_days` (def: 30 días)  |
| B         | días de rotación ≤ `sale_cat_b_days` (def: 60 días)  |
| C         | días de rotación ≤ `sale_cat_c_days` (def: 90 días)  |
| D         | días de rotación ≤ `sale_cat_d_days` (def: 180 días) |
| E         | sin ventas en el período o rotación > umbral D       |

---

#### Modo Demanda (`sale_cat_mode = 'demand'`)

| Concepto         | Fórmula en español                                  | Campo Odoo                   |
| ---------------- | --------------------------------------------------- | ---------------------------- |
| Promedio mensual | Salidas del período ÷ cantidad de meses del período | `Σ stock.move.line.quantity` |

| Categoría | Condición                                                   |
| --------- | ----------------------------------------------------------- |
| A         | promedio mensual ≥ `sale_cat_demand_a_qty` (def: 100 u/mes) |
| B         | promedio mensual ≥ `sale_cat_demand_b_qty` (def: 50 u/mes)  |
| C         | promedio mensual ≥ `sale_cat_demand_c_qty` (def: 20 u/mes)  |
| D         | promedio mensual ≥ `sale_cat_demand_d_qty` (def: 5 u/mes)   |
| E         | promedio mensual < umbral D                                 |

---

#### Modo Participación acumulada — Pareto (`sale_cat_mode = 'share'`)

| Concepto           | Fórmula en español                                      | Campo Odoo                      |
| ------------------ | ------------------------------------------------------- | ------------------------------- |
| Valor por unidades | Suma de unidades vendidas del producto en el período    | `Σ stock.move.line.quantity`    |
| Valor por importe  | Suma de unidades vendidas × precio de lista actual      | `× product.template.list_price` |
| Participación      | Valor del producto ÷ valor total de todos los productos | Calculado                       |
| Acumulado          | Suma de participaciones, ordenando de mayor a menor     | Calculado                       |

| Categoría | Condición                                      |
| --------- | ---------------------------------------------- |
| A         | acumulado ≤ `sale_cat_share_a_pct` (def: 50 %) |
| B         | acumulado ≤ `sale_cat_share_b_pct` (def: 80 %) |
| C         | acumulado ≤ `sale_cat_share_c_pct` (def: 95 %) |
| D         | acumulado ≤ `sale_cat_share_d_pct` (def: 99 %) |
| E         | resto                                          |

---

### Forecast

#### KPIs globales del panel

| KPI                 | Fórmula en español                                                                           | Campos Odoo                                                                       |
| ------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Forecast total      | Suma de todas las cantidades de forecast del período                                         | `Σ mrp.forecast.line.forecast_qty`                                                |
| OFs planificadas    | Suma de cantidades de OFs en estados habilitados asignadas al período. El criterio de asignación depende de `comparison_date_mode` | `Σ mrp.production.product_qty` (o fracción proporcional)                          |
| Gap OFs             | OFs planificadas − forecast total (negativo = déficit de cobertura)                          | Calculado                                                                         |
| Cobertura %         | OFs planificadas ÷ forecast total × 100, redondeado a 1 decimal                              | Calculado                                                                         |
| Productos en riesgo | Cantidad de productos con cobertura por debajo del umbral de aviso                           | `cobertura_% < forecast_warning_pct` (def: 70 %)                                  |
| Entregado total     | Suma de unidades de salidas completadas del período, para productos con forecast             | `Σ stock.move.quantity` donde `picking_type_code = 'outgoing'` y `state = 'done'` |
| Demanda OV          | Suma de cantidades pedidas en órdenes de venta confirmadas o cerradas del período            | `Σ sale.order.line.product_uom_qty` donde `order.state in ('sale','done')`        |
| Tasa de servicio    | entregado total ÷ demanda OV × 100, redondeado a 1 decimal                                   | Calculado                                                                         |
| Gap de demanda      | (demanda OV − forecast total) ÷ forecast total × 100 (positivo = demanda superó el forecast) | Calculado                                                                         |

**Colores de Tasa de servicio**

| Color    | Condición         |
| -------- | ----------------- |
| Verde    | ≥ 95 %            |
| Amarillo | entre 80 % y 94 % |
| Rojo     | < 80 %            |

**Colores de Gap de demanda** (sobre el valor absoluto)

| Color    | Condición                                      |
| -------- | ---------------------------------------------- |
| Verde    | \|gap\| ≤ 10 % (demanda alineada con forecast) |
| Amarillo | \|gap\| ≤ 25 % (desvío moderado)               |
| Rojo     | \|gap\| > 25 % (desvío significativo)          |

**Colores de Gap de OFs**

| Color    | Condición                                    |
| -------- | -------------------------------------------- |
| Verde    | gap ≥ 0 % (OFs cubren o superan el forecast) |
| Amarillo | gap entre −10 % y 0 %                        |
| Rojo     | gap < −10 %                                  |

---

#### Tabla forecast — columnas calculadas (matriz producto × mes)

Para cada celda (un producto en un mes específico):

| Columna          | Fórmula en español                                                                    | Campos Odoo                         |
| ---------------- | ------------------------------------------------------------------------------------- | ----------------------------------- |
| Forecast         | Suma de líneas de forecast del producto para ese mes                                  | `Σ mrp.forecast.line.forecast_qty`  |
| OFs              | Suma de cantidades de OFs del producto asignadas al mes. El criterio de asignación depende de `comparison_date_mode` (ver Guía rápida): por fecha de fin, por solapamiento completo, o proporcional por duración | `Σ mrp.production.product_qty` (o fracción proporcional) |
| % Cobertura      | OFs del mes ÷ denominador del mes × 100, redondeado a 1 decimal. Cero si el denominador es cero. Denominador según `forecast_mo_coverage_denominator` (ver abajo) | Calculado |
| Entregado        | Suma de unidades de salidas completadas del producto en ese mes                       | `Σ stock.move.line.quantity`        |
| Demanda real     | Suma de cantidades pedidas en OVs confirmadas del producto en ese mes                 | `Σ sale.order.line.product_uom_qty` |
| Tasa de servicio | entregado ÷ demanda real × 100, redondeado a 1 decimal                                | Calculado                           |
| Gap de demanda   | (demanda real − forecast) ÷ forecast × 100, redondeado a 1 decimal                    | Calculado                           |

**% Cobertura OFs — denominador configurable (`forecast_mo_coverage_denominator`)**

| Valor | Denominador de la columna % Cobertura |
|---|---|
| `forecast` (por defecto) | Forecast planificado del mes (`Σ mrp.forecast.line.forecast_qty`) |
| `so_demand` | Unidades en OVs confirmadas del mes (`Σ sale.order.line.product_uom_qty`) |

**Colores de cobertura por celda**

| Color    | Condición                                      |
| -------- | ---------------------------------------------- |
| Verde    | cobertura ≥ 100 %                              |
| Amarillo | cobertura ≥ `forecast_warning_pct` (def: 70 %) |
| Rojo     | cobertura < `forecast_warning_pct`             |

**Totales por producto (columna de totales al final de cada fila)**

| Total                  | Fórmula en español                               |
| ---------------------- | ------------------------------------------------ |
| Total forecast         | Suma de forecast de todos los meses del producto |
| Total OFs              | Suma de OFs de todos los meses del producto      |
| % Total                | Total OFs ÷ Total forecast × 100                 |
| Total entregado        | Suma de entregado de todos los meses             |
| Total demanda real     | Suma de demanda real de todos los meses          |
| Tasa de servicio total | Total entregado ÷ total demanda real × 100       |

---

#### Rotación de inventario (columna por producto)

El método se configura en `mrp.reschedule.config.forecast_rotation_method`. El período es el rango del forecast seleccionado.

**Por unidades (`forecast_rotation_method = 'units'`)**

| Concepto                   | Fórmula en español                                             | Campo Odoo                                       |
| -------------------------- | -------------------------------------------------------------- | ------------------------------------------------ |
| Promedio mensual entregado | Total de unidades entregadas en el período ÷ cantidad de meses | `Σ stock.move.line.quantity` salidas completadas |
| Stock al fin del período   | stock actual − entradas(fin→hoy) + salidas(fin→hoy)            | Ancla en `stock.quant` (roll-back)               |
| Stock al inicio del período | stock al fin − entradas del período + salidas del período     | Roll-back sobre `stock.move`                     |
| Stock promedio del período | (stock al inicio + stock al fin) ÷ 2                           | Calculado                                        |
| Rotación en meses          | stock promedio ÷ promedio mensual, redondeado a 1 decimal      | Calculado                                        |
| Rotación en días           | stock promedio ÷ promedio mensual × 30, redondeado a entero    | Calculado                                        |
| Unidad de visualización    | Configurable: días o meses                                     | `mrp.reschedule.config.forecast_rotation_unit`   |

> **Stock promedio (roll-back).** No se reconstruye sumando todo el historial: se ancla en el stock **actual** (exacto, de `stock.quant`, respetando el filtro de depósito) y se rueda hacia atrás con los flujos que cruzan la frontera de las ubicaciones. Si el período termina hoy o en el futuro, el stock al fin = stock actual. Solo se miran los movimientos del período (y una cola si el período es pasado), no toda la historia.

**Por COGS — a costo (`forecast_rotation_method = 'cogs'`)**

```
S_avg_val = (inv_inicio_costo + inv_fin_costo) / 2    [valor monetario]
DIO       = D × S_avg_val / COGS
```

| Variable | Detalle |
|---|---|
| `inv_inicio_costo` | Stock al inicio del período × costo estándar (`product.template.standard_price`) |
| `inv_fin_costo` | Stock al final del período × costo estándar |
| `COGS` | Suma de `price_unit × quantity` de los movimientos de salida completados en el período |
| `D` | Días del período (rango del forecast) |
| `DIO` | Días de inventario (equivale a la columna "Rotación en días") |

**Por ventas — a precio de venta (`forecast_rotation_method = 'sales'`)**

```
S_avg_val = (inv_inicio_precio + inv_fin_precio) / 2  [valor monetario]
DIO       = D × S_avg_val / V_net
```

| Variable | Detalle |
|---|---|
| `inv_inicio_precio` | Stock al inicio del período × precio de lista (`product.template.list_price`) |
| `inv_fin_precio` | Stock al final del período × precio de lista |
| `V_net` | Suma de ventas netas en el período (movimientos de salida valorados a precio de lista) |
| `D` | Días del período |

**Colores de rotación** (comunes a los tres métodos)

| Unidad | Verde     | Amarillo            | Gris (sin color) |
| ------ | --------- | ------------------- | ---------------- |
| Meses  | ≤ 3 meses | entre 4 y 6 meses   | > 6 meses        |
| Días   | ≤ 90 días | entre 91 y 180 días | > 180 días       |

---

#### Cobertura de inventario (columna por producto)

Calcula los **días de stock disponible** a partir del inventario actual y una demanda de referencia configurable. El resultado es distinto de la columna "% Cobertura OFs" (que mide cuánto de la demanda planificada ya tiene una OF asignada).

```
cobertura_dias = stock_actual × D / demand_fuente
```

La fuente de demanda se configura en `mrp.reschedule.config.forecast_coverage_demand_source`:

| Valor | `demand_fuente` |
|---|---|
| `forecast` (por defecto) | Total de forecast planificado del período (`Σ mrp.forecast.line.forecast_qty`) |
| `so_demand` | Total de unidades en OVs confirmadas del período (`Σ sale.order.line.product_uom_qty`) |
| `delivered` | Total de unidades entregadas (salidas completadas) del período (`Σ stock.move.line.quantity`) |

> Si la fuente de demanda es cero para un producto, la cobertura se reporta como indefinida (no se muestra).

---

#### Fórmulas de precisión de forecast

Las 5 fórmulas usan el mismo concepto de **«real»**, cuya fuente es configurable mediante `mrp.reschedule.config.forecast_precision_source`:

#### Fórmulas de precisión de forecast — fuente del «real»

| Valor | `real` en las 5 fórmulas | Campo Odoo |
|---|---|---|
| `demand` (por defecto) | Unidades en OVs confirmadas o cerradas del período | `Σ sale.order.line.product_uom_qty` donde `order.state in ('sale','done')` |
| `delivery` | Unidades entregadas (salidas de stock completadas) del período | `Σ stock.move.line.quantity` donde `state = 'done'` y `picking_type_code = 'outgoing'` |

> Elegir `delivery` hace que la precisión mida qué tan bien el forecast anticipó los despachos reales en lugar de los pedidos colocados. Útil cuando la demanda confirmada y la entregada difieren significativamente.

> **Dónde se muestra cada valor (agregación).** El módulo distingue dos niveles, y **no deben compararse entre sí** (agregar datos ≠ agregar métricas):
> - **Columna por artículo**: la métrica calculada sobre los períodos de *ese* producto.
> - **Card superior y fila Total**: la métrica **agregada** (ratio de sumas) sobre **todos los productos visibles**, respetando el filtro/búsqueda de la tabla. Es el mismo número en el card y en la fila Total.
>
> El indicador **titular** (el número grande del card y la columna) es la fórmula elegida en Ajustes (`forecast_acc_formula`); las demás aparecen como pills, todas con el mismo método de agregación. El promedio simple de la columna **no** es el valor del card: el card pondera por volumen.

Valores de base para cada período y producto:

| Variable         | Descripción                                   | Campo Odoo                          |
| ---------------- | --------------------------------------------- | ----------------------------------- |
| `forecast_qty`   | Cantidad planificada en el forecast del mes   | `mrp.forecast.line.forecast_qty`    |
| `real`           | Volumen real del período (según `precision_source` arriba) | Ver tabla superior |
| `error_absoluto` | Valor absoluto de (real − forecast)           | Calculado                           |

---

**Simple**

| Concepto            | Fórmula en español                                                                        |
| ------------------- | ----------------------------------------------------------------------------------------- |
| Precisión por celda | demanda real ÷ forecast × 100, redondeado a 1 decimal (si hay forecast)                   |
| Precisión total     | suma de demanda real de todos los períodos ÷ suma de forecast de todos los períodos × 100 |
| Interpretación      | 100 % = coincidencia exacta. Más de 100 % = la demanda superó el forecast                 |

**MAPE — Error porcentual absoluto medio**

| Concepto            | Fórmula en español                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------------- |
| Precisión por celda | máximo(0, 100 − error absoluto ÷ demanda real × 100), redondeado a 1 decimal (solo si hay demanda real) |
| Precisión total     | promedio de precisiones de todos los períodos con demanda real > 0                                      |
| Característica      | Muy sensible a períodos con demanda baja o cero                                                         |

**WAPE — Error porcentual absoluto ponderado por demanda real**

| Concepto        | Fórmula en español                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------- |
| Precisión total | máximo(0, 100 − suma de errores absolutos ÷ suma de demanda real × 100), redondeado a 1 decimal |
| Característica  | Pondera más los períodos de mayor volumen real. Robusto cuando el forecast tiene ceros          |

**WMAPE — Error porcentual absoluto ponderado por forecast**

| Concepto        | Fórmula en español                                                                          |
| --------------- | ------------------------------------------------------------------------------------------- |
| Precisión total | máximo(0, 100 − suma de errores absolutos ÷ suma de forecast × 100), redondeado a 1 decimal |
| Característica  | Pondera más los períodos de mayor volumen planificado. Estándar en supply chain             |

**Sesgo (Bias)**

| Concepto        | Fórmula en español                                                                                              |
| --------------- | --------------------------------------------------------------------------------------------------------------- |
| Sesgo por celda | (demanda real − forecast) ÷ forecast × 100, redondeado a 1 decimal (si hay forecast)                            |
| Sesgo total     | (suma de demanda real − suma de forecast) ÷ suma de forecast × 100                                              |
| Interpretación  | Positivo = la demanda superó sistemáticamente el forecast (forecast conservador). Negativo = forecast optimista |

**Colores de precisión**

| Fórmula                   | Verde            | Amarillo                    | Rojo             |
| ------------------------- | ---------------- | --------------------------- | ---------------- |
| Simple, MAPE, WAPE, WMAPE | ≥ 90 %           | entre 70 % y 89 %           | < 70 %           |
| Sesgo                     | \|sesgo\| ≤ 10 % | \|sesgo\| entre 11 % y 20 % | \|sesgo\| > 20 % |

---

#### Categorías de cliente — métodos automáticos

El resultado se guarda en `mrp.partner.company.category` (campo computed `res.partner.x_customer_category`, por empresa). El período de análisis es configurable: `customer_cat_lookback_months` en `mrp.reschedule.config` (def: 12 meses). Los umbrales Pareto son los mismos que para proveedores (`abc_pct_a/b/c/d`).

**ABC por volumen** (`customer_cat_method = 'abc_volume'`)

| Concepto              | Detalle                                                                |
| --------------------- | ---------------------------------------------------------------------- |
| **Valor por cliente** | Suma de importes de OVs confirmadas o cerradas en el período configurado |
| **Clasificación**     | Pareto acumulado descendente: mayor volumen = A                        |
| **Campo**             | `Σ sale.order.amount_total` donde `state in ('sale','done')`           |

**ABC por frecuencia** (`customer_cat_method = 'abc_frequency'`)

| Concepto              | Detalle                                                        |
| --------------------- | -------------------------------------------------------------- |
| **Valor por cliente** | Cantidad de OVs confirmadas o cerradas en el período configurado |
| **Clasificación**     | Pareto acumulado descendente: mayor frecuencia = A             |
| **Campo**             | `count(sale.order)` donde `state in ('sale','done')`           |

**ABC por RFM** (`customer_cat_method = 'abc_rfm'`)

| Componente     | Fórmula en español                    | Puntuación                                                               |
| -------------- | ------------------------------------- | ------------------------------------------------------------------------ |
| Recencia (R)   | Días desde la última OV hasta hoy     | < `rfm_recency_recent_days` (30) = 3 pts / < `rfm_recency_medium_days` (90) = 2 pts / resto = 1 pt |
| Frecuencia (F) | Cantidad de OVs en el último año      | > `rfm_freq_high` (10) = 3 pts / ≥ `rfm_freq_medium` (3) = 2 pts / resto = 1 pt |
| Monetario (M)  | Importe total de OVs en el último año | ≥ percentil 66 del grupo = 3 pts / ≥ percentil 33 = 2 pts / resto = 1 pt |

Cortes configurables en Ajustes → "Parámetros RFM" (compartidos con proveedores):

| Puntaje total (R+F+M)             | Categoría |
| --------------------------------- | --------- |
| ≥ `rfm_score_a` (8)               | A         |
| ≥ `rfm_score_b` (6)               | B         |
| ≥ `rfm_score_c` (4)               | C         |
| ≥ `rfm_score_d` (3)               | D         |
| Sin datos (sin OVs en el período) | E         |

---

## Panel de Ventas — Análisis de clientes

El widget de análisis de clientes calcula métricas por cliente a partir de órdenes de venta y sus entregas. El período de análisis es el rango seleccionado en el panel.

---

### % de cumplimiento y % físico (tasas de entrega por cliente)

Cada cliente muestra dos tasas de entrega, espejando la "Tasa de cumplimiento" y la "Tasa física" del panel de ventas. Ambas se aplican también en el detalle del cliente (por mes, por producto) y en los KPIs superiores del panel (promedios).

**% de cumplimiento** — "de lo que pidió en el período, ¿cuánto ya le entregué?"

| Concepto | Fórmula | Campo Odoo |
|---|---|---|
| Cantidad pedida | Suma de unidades en líneas de OVs confirmadas del período | `Σ sale.order.line.product_uom_qty` donde `order.state in ('sale','done')` |
| Cantidad entregada | Entregado acumulado a la fecha de esas mismas líneas (cualquier fecha de entrega) | `Σ sale.order.line.qty_delivered` |
| % de cumplimiento | cantidad_entregada ÷ cantidad_pedida × 100 | Calculado |

**% físico** — "¿cuánto le despaché este período?"

| Concepto | Fórmula | Campo Odoo |
|---|---|---|
| Cantidad pedida | Igual que arriba (pedido en el período) | `Σ sale.order.line.product_uom_qty` |
| Cantidad despachada | Salidas completadas con fecha de efectivización dentro del período, de cualquier pedido del cliente (vinculadas vía el pedido del remito) | `Σ stock.move.line.quantity` donde `state='done'`, picking `outgoing` con `date_done` en el período |
| % físico | cantidad_despachada ÷ cantidad_pedida × 100 | Calculado |

> El % físico puede superar 100 % si se despachan pedidos de períodos anteriores. El tooltip desglosa las entregas por mes de confirmación del pedido de origen. Ambas tasas usan el mismo semáforo configurable en Ajustes.

---

### Análisis de clientes — % a tiempo

Mide el porcentaje de envíos (pickings) que llegaron antes de la fecha límite definida por la configuración `customer_analysis_ontime_method`.

```
ontime_pct = pickings_a_tiempo / total_pickings × 100
```

**Definición de "a tiempo" según `customer_analysis_ontime_method`**

| Valor | Condición para considerar un envío "a tiempo" | Campo Odoo |
|---|---|---|
| `commitment_date` (por defecto) | `date_done ≤ commitment_date` de la orden de venta asociada | `sale.order.commitment_date` |
| `scheduled_date` | `date_done ≤ scheduled_date` del envío saliente | `stock.picking.scheduled_date` |
| `sla_days` | `date_done ≤ date_order + N días` (N = `customer_sla_days` configurable) | `sale.order.date_order + timedelta(days=sla_days)` |

> Si un picking no tiene la fecha de referencia configurada (por ejemplo, `commitment_date` vacío), ese picking no se incluye en el cómputo de `ot_total`.

---

### Intervalos entre pedidos

Mide la regularidad de compra de un cliente.

| Concepto | Fórmula | Campo Odoo |
|---|---|---|
| Lista de fechas | Fechas de confirmación de todas las OVs del cliente en el período, ordenadas | `sale.order.date_order` |
| Gaps | Diferencia en días entre cada par de pedidos consecutivos | `date_i+1 − date_i` |
| Promedio de intervalos | Suma de gaps ÷ (cantidad de gaps) | `Σ gaps / len(gaps)` |

> Si el cliente tiene solo 1 pedido en el período, el promedio de intervalos es indefinido (no se muestra).

---

### Ticket promedio

```
ticket_promedio = importe_total_periodo / cantidad_de_pedidos
```

| Variable | Campo Odoo |
|---|---|
| `importe_total_periodo` | `Σ sale.order.amount_total` del período |
| `cantidad_de_pedidos` | `count(sale.order)` del período |

---

### Tendencia de ventas

Compara el importe del período actual con el mismo período del año anterior.

```
trend_pct = (total_actual − total_anterior) / total_anterior × 100
```

| Variable | Detalle |
|---|---|
| `total_actual` | Importe total de OVs del período seleccionado |
| `total_anterior` | Importe total de OVs del mismo rango de fechas, desplazado 1 año hacia atrás |

> Si el período anterior tiene importe cero (cliente sin histórico), la tendencia no se muestra.

---

### ABC del período

Clasifica los clientes activos en el período según su participación acumulada en el importe total de ventas. Usa los mismos umbrales Pareto que el resto del módulo (`abc_pct_a`, `abc_pct_b`).

```
participacion_i   = importe_cliente_i / importe_total_todos × 100
acumulado_i       = Σ participacion (ordenado de mayor a menor)
```

| Condición | Categoría del período |
|---|---|
| `acumulado ≤ abc_a_pct` (def: 20 %) | A |
| `acumulado ≤ abc_a_pct + abc_b_pct` (def: 20 % + 30 % = 50 %) | B |
| resto | C |

> Esta clasificación ABC del período es calculada sobre la marcha para el widget; es independiente de la categoría permanente `x_customer_category` asignada por el cron.

---

### Segmento de frecuencia

Clasifica cada cliente según la regularidad y recencia de sus pedidos.

| Condición (evaluada en orden) | Segmento |
|---|---|
| Días desde último pedido > `customer_risk_days` (def: 90 días) | En riesgo |
| Promedio de intervalos ≤ 30 días | Frecuente |
| Promedio de intervalos ≤ 90 días | Ocasional |
| Promedio de intervalos > 90 días | Inactivo |

> La condición "En riesgo" tiene precedencia sobre las demás: un cliente con intervalos frecuentes pero que no compra desde hace más de `customer_risk_days` días se clasifica como "En riesgo".

---

## Período de análisis — categorías de proveedor y cliente

### `supplier_cat_lookback_months` (mrp.reschedule.config)

Cantidad de meses de historial que se consideran al ejecutar `action_compute_supplier_categories`. Equivale a `sale_cat_lookback_months` para productos. Default: 12.

El cálculo usa `date.today() - timedelta(days=months * 30)` como fecha de inicio.

### `customer_cat_lookback_months` (mrp.reschedule.config)

Ídem para `action_compute_customer_categories`. Default: 12.

---

## Precisión horaria en "entrega a tiempo" — proveedores

La comparación de si una recepción llegó a tiempo usa `picking.date_done <= picking.scheduled_date` en todos los contextos:

- `get_supplier_analysis_data()` en `mrp_planner_dashboard_supplier.py`
- `abc_delivery_pct` y `abc_quality_combo` en `mrp_partner_category.py`

Una entrega que llega el mismo día que la fecha programada pero una hora después se clasifica como **tarde**. Esto garantiza que el % de entregas a tiempo del dashboard y el de la categorización son comparables.

---

## Independencia entre rotación de quiebres y categorización de productos

**Decisión de diseño intencional, no un bug.**

La tabla de quiebres de stock y la categoría ABC de producto (columna "Cat. venta") usan configuraciones independientes:

| Dimensión | Quiebres de stock | Categoría de producto |
|---|---|---|
| Método | `stock_break_rotation_method` (units/cogs/sales) | `sale_cat_mode` (automatic/demand/share/manual) |
| Período | `stock_break_rotation_months` | `sale_cat_lookback_months` |
| Base demanda | siempre entregas reales | configurable (`sale_cat_rotation_source`) |
| Cuándo se calcula | en vivo, cada vez que se abre el panel | bajo demanda (botón "Calcular ahora" o cron) |

**Por qué no se unifican:** quiebres de stock es una herramienta de exploración operativa — el usuario cambia el filtro para investigar distintos escenarios. La categorización de productos es una política estable que no debe cambiar porque alguien tenga otro filtro abierto.

**Cómo se documenta en pantalla:** el header de la columna "Rot." muestra el método y período activos. El badge de "Cat. venta" tiene un tooltip que indica con qué método/período/base fue calculada y que no se recalcula con los filtros del panel.
