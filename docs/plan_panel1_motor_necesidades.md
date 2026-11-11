# Plan — Panel 1: Motor de necesidades de producción

> Estado: **propuesta funcional acordada, pendiente de construir**. Rama de trabajo: `18.0-dev`.
> Fuentes: `Especificacion_Paneles_Supply_Chain.docx` (spec de 3 paneles) y
> `Motor_Planificacion_Integrado_con_Dashboard_Impacto22.xlsx` (motor Excel en uso hoy).
> El Excel extraído quedó en `scripts_tmp/_spec/` para consulta.

## 1. Objetivo

Reformulación fuerte del módulo `odoo_mrp_planner_scheduling`. **Primer paso: Panel 1**,
que no es sólo un panel de visualización sino el **punto de partida desde donde se disparan
las OF**. Replica dentro de Odoo el "motor" que hoy se hace a mano en el Excel: calcula la
**necesidad de producción por SKU** con datos que ya existen en el sistema.

El spec define 3 paneles (planificación, forecast/demanda, inmovilizados). **Arrancamos sólo
por el Panel 1.** En su v1 **replicamos el Excel tal cual** (sin fechas de quiebre/lanzamiento,
que son del spec más rico y quedan para una iteración posterior).

## 2. El motor Excel (lo que hay que replicar)

El Excel recorre el maestro de SKU (hasta ~2.600) y por cada uno calcula con `INDEX/MATCH`
+ `SUMIFS`. Tiene **dos hojas motor**:

### 2.1 Hoja PLANIFICACION — "¿cuánto fabricar este mes?" (necesidad neta) — **ESTO es v1**

Criterio declarado: **Stock objetivo = (promedio forecast × factor seguridad) + forecast del mes**.

| Col | Concepto | Cálculo |
|-----|----------|---------|
| K | Posición de stock | `virtual_available` = a la mano + entrante − saliente (col H de BD_STOCK = "Cantidad pronosticada Odoo") |
| L | Promedio forecast | `SUM(forecast en ventana, estado OK) / Nº FIJO de meses de la ventana` |
| M | Forecast del mes | forecast del único "mes a programar" |
| N | Stock de seguridad | `ROUNDUP(L × factor)` — factor en PARAMETROS = **1.4** |
| O | Stock objetivo | `N + M` |
| P | Necesidad neta | `MAX(0, ROUNDUP(O − K))` |
| Q | Cantidad sugerida a fabricar | si origen ≠ "Producción Interna" → 0; si P>0 → `MAX(mínimo_por_turno, P)`; si no → 0 |
| R / S | Cobertura actual / con programa (meses) | `K/L` y `(K+Q)/L` |
| T | Estado | cascada de validaciones (ver abajo) |

**Estado (col T), en cascada:**
`REVISAR ORIGEN` (sin origen válido) → `REVISAR STOCK` (sin registro de stock) →
`SIN FORECAST` → `NO FABRICAR` (origen no es Producción Interna) → `STOCK SUFICIENTE` (P≤0) →
combinación de: `REVISAR CANTIDAD` (P>0 y Q<promedio), `REVISAR MAQUINA` (sin máquina),
`REVISAR MINIMO` (sin mínimo por turno), `APLICA MINIMO` (Q>P), **`PROGRAMAR`** (Q≥promedio,
con máquina y mínimo definidos). `PROGRAMAR` = la línea verde desde la que se dispara la OF.

### 2.2 Hoja PUNTO_PEDIDO — "¿cuándo disparar?" (reorder point) — **queda para después**

Criterio: **Punto de pedido = demanda durante lead time + stock de seguridad**.
- Demanda diaria = promedio mensual / 30.4375
- Demanda en LT = `ROUNDUP(diaria × lead_time)`
- Stock seguridad = `ROUNDUP(promedio × factor)`
- Punto de pedido = suma de ambos
- Estado = `PEDIR / REVISAR` si posición ≤ punto de pedido, si no `OK`
- Lead time por categoría de origen (PARAMETROS): Producción Interna 50, CV Nacional 30,
  CV importado 120 días…

El "Panel 1" rico del spec (fecha de quiebre, fecha límite de lanzamiento) es la **fusión** de
estos dos motores. Hoy ninguno calcula fechas; el disparo es por umbral.

### 2.3 Parámetros del Excel (hoja PARAMETROS)

Factor de seguridad (1.4), inicio/fin del promedio forecast, Nº de meses del período,
días promedio por mes (30.4375), lead times por origen, capacidad inicial (2.600 SKU).

## 3. Mapeo de datos: Excel → Odoo (casi todo ya existe)

| BD del Excel | Dato | En Odoo | Estado |
|--------------|------|---------|--------|
| BD_MAESTRO_SKU | código, código viejo, descripción, familia, ABC | `product.template/product`, `default_code`, `x_studio_cdigo_viejo` | ✅ existe |
| BD_STOCK col H | posición de stock | `product.virtual_available` (patrón `stock.quant` read_group) | ✅ existe |
| BD_STOCK | categ. venta / producto / precio | `mrp.product.company.category` (`x_sale_category`), `categ_id`, `list_price` | ✅ existe |
| **BD_FORECAST** | forecast mensual por SKU | **`mrp.forecast.line`** (product_id, period, forecast_qty) | ✅ existe |
| BD_ORIGEN | origen / tipo de abastecimiento | `x_product_type_ids` (M2M → `mrp.product.type`) — a cargar | ⚠️ campo existe, sin datos |
| BD_MAQUINAS_MINIMOS | máquina asignada | `mrp.product.workcenter` con `is_preferred` | ✅ existe |
| BD_MAQUINAS_MINIMOS | **mínimo por turno** | **nuevo campo `min_per_shift`** en `mrp.product.workcenter` | 🆕 crear |
| BD_VULCANIZADO | PT ↔ semiterminado, secuencia, ABC VL | derivable de `mrp.bom` | ⏸️ pendiente |
| PARAMETROS | factor, lead times, ventana | tabla/config propia | 🆕 crear |

Patrones de lectura ya probados en el repo (reusar): `virtual_available` vía `stock.quant`
read_group; `mrp.forecast.line`; lead times `mrp.bom.produce_delay` / `seller_ids.delay`;
`read_group` + dict mapping para KPIs a escala; todo filtrado por `company_id`.

## 4. Decisiones acordadas

1. **Origen de abastecimiento** = `x_product_type_ids` (M2M a `mrp.product.type`, etiqueta
   "Tipo de producto", ya usado como columna "Tipo" en el panel de quiebres).
   **Cada SKU lleva UN solo tipo de origen** (convención simple, sin flag extra en el catálogo).
2. **Máquina asignada** = centro `is_preferred` en `mrp.product.workcenter` (ya existe).
   **Mínimo por turno** = campo nuevo `min_per_shift` en `mrp.product.workcenter`
   (depende del par producto+máquina, como en el Excel).
3. **Forecast** = todo `mrp.forecast.line` de Odoo, **sin filtro de estado**. El usuario vela
   por que el dato esté correcto y actualizado. (Pendiente: cargar histórico hacia atrás.)
4. **Factor de seguridad configurable** (v1 global; override por categoría/SKU, más adelante).
5. **Promedio forecast** = suma / **Nº fijo de meses de la ventana** (no por meses-con-dato).
6. **Posición de stock** = pronóstico (`virtual_available`); **almacén configurable**.
7. **Disparo**: crea **1 OF del producto final en el último almacén**; las OF/OC hacia atrás
   se generan por el circuito existente (explosión BOM del scheduling). OF para aprobación
   humana (el spec insiste: el panel recomienda, el usuario aprueba).
8. **v1 = replicar el Excel tal cual** (sin fechas de quiebre/lanzamiento).
9. **Vulcanizado/secuencia** = pendiente (se ve al llegar a semiterminados).

## 5. Triage del módulo actual (criterio: menos es más)

| Pieza actual | Qué es | Decisión |
|--------------|--------|----------|
| `mrp.product.workcenter` | Dato maestro producto↔máquina (+ preferido) | **Conservar y extender** (+ `min_per_shift`) |
| `mrp.schedule.mixin` | Utilidad de fechas hábiles / calendario | **Conservar** (reusable) |
| Config/grupos/seguridad/menú | Plomería del módulo | **Conservar** (colgar Panel 1) |
| `mrp.demand.expansion.mixin` + `mrp.demand.scheduling.mixin` | Explosión BOM + scheduling contra capacidad | **Reusar como backend del disparo** |
| `mrp.production.request` (wizard manual) | Puerta de entrada manual | **Reemplazar** por Panel 1 |
| `mrp.reschedule.plan` + `cascade.mixin` (746 líneas) + plan.line + wc.line + Gantts + alertas | Reprogramador en cascada de fechas | **Aparcar** (ver §5.1) |

### 5.1 Qué hacer con la cascada

**Aparcar, no borrar (todavía).** Ocultar su UI ahora (sacar menú/acción) para que no moleste,
dejando el código quieto. **Git es la red de seguridad.** Cuando se diseñe el motor de
**capacidad finita** (OT×CT, "pin & re-solve" — ver nota de rumbo del proyecto), se decide de
una: canibalizar lo que sirva (agenda por calendario laboral, anclas de carga por CT, preload
batch) y borrar el resto en una sola pasada informada. Así no queda "código al pedo" a la vista,
no se gasta esfuerzo en demolición prematura y no se pierde lógica reusable.

## 6. Orden de construcción

1. **Parámetros configurables** (factor de seguridad, días/mes = 30.4375, almacén por defecto,
   lead times por origen, ventana de promedio). Con vigencia/auditoría (spec §7).
2. **Campo `min_per_shift`** en `mrp.product.workcenter`.
3. **Motor de necesidades**: método Python que, dado *mes a programar* + *ventana* + *almacén*,
   recorre productos y calcula por SKU (K,L,M,N,O,P,Q, cobertura, estado) replicando
   PLANIFICACION. Reusa los patrones de lectura existentes.
4. **Panel 1** (client action OWL, consistente con los dashboards KPI actuales): KPIs superiores
   (quiebres, riesgos, necesidad fab/compra, SKU a intervenir), tabla operativa, filtros
   (origen, categorías, almacén, estado) y acción **"Generar OF"** → backend de disparo.
5. **Aparcar la cascada** (ocultar UI).

## 7. Dudas / pendientes

- Cargar el histórico de forecast hacia atrás para tener buen promedio.
- Factor por categoría/SKU (post-v1).
- Vulcanizado: ¿sólo informativo o interviene en el encadenado de OF de semiterminados?
- Factor 1.4 (PARAMETROS) vs 1.3 (texto PUNTO_PEDIDO) vs 2.3 (spec): se parametriza; confirmar
  el valor vigente al cargar.
