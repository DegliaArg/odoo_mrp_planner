# Arquitectura — odoo_mrp_planner

> **Para quién:** desarrollador que va a modificar el módulo.
> **No repite** features (→ `README.md`) ni fórmulas (→ `docs.md`) — los referencia cuando hace falta.

---

## Mapa de carpetas

| Carpeta | Qué vive ahí |
|---------|-------------|
| `models/` | Modelos persistentes, mixins de cálculo y TransientModels del dashboard |
| `wizard/` | Wizards de programación desde demanda e importación de forecast |
| `views/` | XML de vistas form/list/tree y definición de menús |
| `static/src/js/` | Widgets OWL del dashboard (un archivo por widget + helpers separados) |
| `static/src/xml/` | Templates QWeb de cada widget OWL (ver sub-templates más abajo) |
| `static/src/css/` | Estilos específicos del módulo (Gantt, tooltips KPI) |
| `security/` | Grupos (`groups.xml`), reglas de acceso (`ir_rules.xml`, `ir.model.access.csv`) |

### Sub-templates XML por widget

Los widgets más complejos dividen su template principal en sub-templates (`t-call`) registrados en archivos separados. El split refleja responsabilidades distintas, no líneas:

| Widget | Archivo principal | Sub-templates |
|--------|------------------|---------------|
| Forecast | `forecast_widget.xml` | `forecast_kpis.xml` — dos filas de 5 KPI cards; `forecast_controls.xml` — barra de filtros (período, depósito, columnas, exportar) |
| Análisis de clientes | `customer_analysis_widget.xml` | `customer_analysis_row.xml` — fila de tabla con datos de columnas y lista de pedidos; `customer_analysis_detail_panel.xml` — panel de análisis individual (KPIs, gráficos, top artículos) |

---

## Modelos por área

### Configuración y permisos

| Modelo | Archivo | Responsabilidad | Se relaciona con |
|--------|---------|-----------------|-----------------|
| `mrp.reschedule.config` | `mrp_reschedule_config.py` | Singleton de configuración global: umbrales de alerta, opciones de scheduling, categorías, forecast. Sincroniza `wc_fallback`/`priority` en `ir.config_parameter`. | `ir.cron`, `res.users` |
| `mrp.reschedule.user.permission` | `mrp_reschedule_user_permission.py` | Depósitos visibles por usuario en el planificador | `res.users`, `stock.warehouse` |
| `res.users` _(inherit)_ | `res_users.py` | Agrega `mrp_planner_all_warehouses` / `mrp_planner_warehouse_ids`, 10 campos `mrp_planner_show_*` de visibilidad de secciones por panel, y constraint de grupo scheduling | `mrp.reschedule.config` |

### Alertas

| Modelo | Archivo | Responsabilidad | Se relaciona con |
|--------|---------|-----------------|-----------------|
| `mrp.reschedule.alert` | `mrp_reschedule_alert.py` | Alerta activa (OF atrasada, OC vencida, recepción demorada, desvío de cantidad, etc.). Lógica de detección periódica y resolución reactiva. | `mrp.production`, `purchase.order`, `stock.picking` |

### Reprogramación en cascada

| Modelo | Archivo | Responsabilidad | Se relaciona con |
|--------|---------|-----------------|-----------------|
| `mrp.reschedule.cascade.mixin` | `mrp_reschedule_cascade_mixin.py` | AbstractModel: motor de cálculo de cascada (_build_lines, _schedule_mo_block, _sort_mos_by_priority, etc.) | `mrp.schedule.mixin` |
| `mrp.reschedule.plan` | `mrp_reschedule_plan.py` | Plan de reprogramación: CRUD, actions (calculate/apply/cancel), Gantt. Hereda el mixin de cascada. | `mrp.reschedule.cascade.mixin`, `mrp.reschedule.plan.line` |
| `mrp.reschedule.plan.line` | `mrp_reschedule_plan_line.py` | Línea propuesta del plan (una OF o PO por fila, con fechas nuevas y delta) | `mrp.reschedule.plan`, `mrp.production` |
| `mrp.reschedule.plan.wc.line` | `mrp_reschedule_plan_wc_line.py` | Carga detallada por centro de trabajo dentro de un plan | `mrp.reschedule.plan` |

### Programación desde demanda (wizards)

| Modelo | Archivo | Responsabilidad | Se relaciona con |
|--------|---------|-----------------|-----------------|
| `mrp.demand.expansion.mixin` | `wizard/mrp_demand_expansion_mixin.py` | AbstractModel: expansión de BOM multinivel (_find_bom, _build_demand_tree, evaluación de ruta/WC por componente) | `mrp.bom`, `product.template` |
| `mrp.demand.scheduling.mixin` | `wizard/mrp_demand_scheduling_mixin.py` | AbstractModel: scheduling de fechas contra calendario (_schedule_tree, _get_wc_anchors_multi, _forward/_backward_schedule_days) | `resource.calendar`, `mrp.workcenter` |
| `mrp.production.request` | `wizard/mrp_production_request.py` | Solicitud de programación: CRUD, actions, creación de OFs. Hereda ambos mixins. | Ambos mixins, `mrp.production.request.item`, `mrp.production` |
| `mrp.production.request.item` | `wizard/mrp_production_request_item.py` | Artículo dentro de una solicitud (producto + cantidad + fecha límite) | `mrp.production.request` |
| `mrp.production.request.line` / `.wc` | `wizard/mrp_production_request_line.py` | Líneas del plan calculado (OF/OC/Stock) y carga por WC | `mrp.production.request` |
| `mrp.forecast.import.wizard` | `wizard/mrp_forecast_import_wizard.py` | Importación de forecast desde Excel/CSV | `mrp.forecast.line` |

### Forecast

| Modelo | Archivo | Responsabilidad | Se relaciona con |
|--------|---------|-----------------|-----------------|
| `mrp.forecast.line` | `mrp_forecast_line.py` | Línea de forecast mensual por producto: cantidad planificada, cobertura calculada | `product.template`, `mrp.production` |

### Dashboard (TransientModels de lectura)

Todos heredan de `mrp.planner.dashboard` y exponen métodos RPC llamados por widgets OWL. Usan `sudo()` extensivamente para leer modelos de ventas/stock/compras sin requerir acceso directo del usuario (ver comentarios en cada método).

**Mixin del dashboard**

| Mixin | Archivo | Responsabilidad |
|-------|---------|-----------------|
| `mrp.planner.dashboard.actions.mixin` | `mrp_planner_dashboard_actions_mixin.py` | AbstractModel con los métodos de drill-down (`action_view_*` + helpers `_open_alerts` / `_open_mos`). Importado por `mrp.planner.dashboard` via `_inherit`. Los `_wh_domain_*` y `_get_allowed_wh_ids` quedan en el coordinador porque los usan también los `_compute_*`. |

**Convención de filtrado por depósito**

Todo método `get_*` del dashboard que filtre por depósito usa `_get_wh_domains()` como único punto de entrada:

```python
wh = self._get_wh_domains()   # calcula una vez
wh.mo       # dominio para mrp.production
wh.po       # dominio para purchase.order / stock.picking
wh.alert    # dominio para mrp.reschedule.alert
wh.allowed_ids  # list[int] | None — para filtros que usan IDs directamente
```

`_get_wh_domains()` respeta `mrp_planner_all_warehouses=True` (retorna dominios vacíos = sin filtro). Métodos nuevos que consulten MO/PO/alertas deben pasar por este método. `_get_allowed_wh_ids()` es implementación interna; no llamarla directamente desde métodos nuevos.|

**Coordinador y extensiones por área de datos**

| Modelo / archivo | Dominio de datos |
|-----------------|-----------------|
| `mrp_planner_dashboard.py` | Coordinador base: campos, `_compute_*`, helpers de depósito (`_wh_domain_*`, `_get_allowed_wh_ids`), navegación inter-panel (`action_open_*`, `action_refresh_*`, `action_new_*`), `get_internal_locations()`. Hereda `mrp.planner.dashboard.actions.mixin`. |
| `mrp_planner_dashboard_mo.py` | Órdenes de fabricación |
| `mrp_planner_dashboard_po.py` | Órdenes de compra |
| `mrp_planner_dashboard_wc.py` | Carga de centros de trabajo (gráfico) |
| `mrp_planner_dashboard_stock.py` | Quiebres de stock |
| `mrp_planner_dashboard_forecast.py` | Datos de forecast para el widget |
| `mrp_forecast_calc_mixin.py` | Helpers de cálculo pesado del forecast, separados del archivo principal: rotación de inventario (`_fc_rotation_data`), construcción de filas con cobertura y precisión (`_fc_build_rows`), stats de productos sin forecast (`_fc_no_fc_stats`) |
| `mrp_planner_dashboard_forecast_export.py` | Generación del archivo Excel de exportación del forecast (`get_forecast_export`) |
| `mrp_planner_dashboard_sales.py` | Panel de ventas: gráfico de ventas por producto, categorías disponibles. Expone `_parse_date` como helper compartido. |
| `mrp_planner_dashboard_supplier.py` | Análisis de proveedores: KPIs de cumplimiento, lead time, variación de precio. Importa `_parse_date` de sales. |
| `mrp_planner_dashboard_customer.py` | Análisis de clientes |
| `mrp_planner_detail_dashboard.py` | Dashboard detalle por OF/producto (drill-down) |

### Clasificación ABC (extensión de mrp.reschedule.config)

| Modelo | Archivo | Responsabilidad | Se relaciona con |
|--------|---------|-----------------|-----------------|
| `mrp.reschedule.config` _(extend)_ | `mrp_partner_category.py` | Clasificación A–E automática de `product.template` (venta) y `res.partner` (proveedores y clientes) por múltiples métodos: volumen, frecuencia, RFM, % entrega a tiempo, varianza de precio, calidad de cantidad, rotación de inventario. Expone métodos de cron y acciones manuales. Usa helpers de `mrp_abc_helpers.py`. | `product.template`, `res.partner`, `stock.move.line`, `purchase.order`, `sale.order` |
| `mrp.partner.company.category` | `mrp_partner_company_category.py` | Almacén por empresa de las categorías A–E de proveedor y cliente. `res.partner.x_supplier_category` / `x_customer_category` son campos computed que leen/escriben en esta tabla. | `res.partner`, `res.company` |
| `mrp.product.company.category` | `mrp_product_company_category.py` | Almacén por empresa de la categoría A–E de venta. `product.template.x_sale_category` es campo computed que lee/escribe en esta tabla. | `product.template`, `res.company` |

### Modelos extendidos (inherit)

| Modelo base | Archivo | Qué agrega |
|------------|---------|-----------|
| `mrp.production` | `mrp_production.py` | Botones de reprogramación, campo de tipo de OF |
| `product.template` | `product_template.py` | Campo computed `x_sale_category` (A–E) — lee/escribe en `mrp.product.company.category`; centros de trabajo compatibles |
| `res.partner` | `res_partner.py` | Campos computed `x_supplier_category` / `x_customer_category` (A–E) — leen/escriben en `mrp.partner.company.category`; flags `mrp_enable_*_cat` de visibilidad |
| `purchase.order` | `purchase_order.py` | Hooks para generación reactiva de alertas al cancelar/confirmar |
| `stock.picking` | `stock_picking.py` | Hook para resolución de alertas de recepción al validar |

### Helpers compartidos

| Archivo | Qué provee |
|---------|-----------|
| `models/mrp_schedule_mixin.py` | `MrpScheduleMixin` (AbstractModel): `_schedule_duration`, `INDENT_MAP` — compartido por wizards y planes |
| `models/mrp_abc_helpers.py` | Funciones ABC/Pareto reutilizadas por categorías de proveedor, cliente y venta |
| `models/const.py` | Constantes del módulo: `SALE_CAT_SELECTION`, `DEFAULT_PO_CRITICAL_DAYS`, umbrales de semáforo (`DEFAULT_ON_TIME_*`, `DEFAULT_RISK_DAYS`, `FORECAST_*`, `RFM_*`) |
| `models/mrp_product_type.py` | Catálogo de tipos de OF |
| `models/mrp_product_workcenter.py` | Relación producto → centros de trabajo compatibles |

---

## Los 3 flujos principales

### 1. Programación desde demanda

```
Usuario abre wizard → mrp.production.request (request.py)
  │
  ├── action_calculate()
  │     ├── MrpDemandExpansionMixin._build_demand_tree()   [expansion_mixin.py]
  │     │     ├── _find_bom()  →  mrp.bom
  │     │     ├── _get_supply_method()  →  decide OF / OC / subcontrato / stock
  │     │     └── recursión por cada componente hasta MAX_DEPTH
  │     │
  │     └── MrpDemandSchedulingMixin._schedule_tree()      [scheduling_mixin.py]
  │           ├── _get_wc_anchors_multi()  →  resource.calendar
  │           ├── _forward_schedule_days() / _backward_schedule_days()
  │           └── produce árbol de nodos con fechas calculadas
  │
  ├── _collect_lines()  →  escribe mrp.production.request.line / .wc
  │
  └── action_confirm()
        ├── Crea mrp.production (OFs madre)
        └── _plan_child_mos()  →  planifica OFs hijas recursivamente
```

### 2. Reprogramación en cascada

```
Usuario abre plan → mrp.reschedule.plan (plan.py + cascade_mixin.py)
  │
  ├── action_calculate()
  │     └── MrpRescheduleCascadeMixin._build_lines()       [cascade_mixin.py]
  │           ├── _get_subsequent_mos()  →  BFS desde OF pivot
  │           ├── _get_pos_for_mo()      →  OCs vinculadas
  │           ├── _schedule_mo_block()   →  calcula bloque en calendario del WC
  │           │     └── MrpScheduleMixin._schedule_duration() [schedule_mixin.py]
  │           └── escribe mrp.reschedule.plan.line / .wc.line
  │
  └── action_apply()
        ├── Actualiza fechas en mrp.production
        ├── Actualiza fechas en purchase.order
        └── Genera mrp.reschedule.alert si hay solapamientos
```

### 3. Dashboard / Forecast

```
Browser OWL widget                          Python TransientModel
──────────────────                          ─────────────────────
onMounted → orm.call(                  →    mrp.planner.dashboard.*
  "mrp.planner.dashboard",                    método RPC
  "get_*_data", [filtros]              ←    devuelve dict con datos
)                                           (lee via sudo() sin acceso directo)
  │
  ├── state.data = resultado
  ├── re-render → template QWeb
  └── Chart.js para gráficos
        ├── forecast_widget.js  →  forecast_formatters.js, forecast_drilldown.js,
        │                          forecast_filters.js, forecast_export.js (funciones puras / delegación)
        └── customer_analysis_widget.js  →  customer_analysis_charts.js

Configuración activa:
  mrp.reschedule.config (singleton)
    └── leída en cada RPC para umbrales, métodos de cálculo, etc.
```

---

## Convenciones del proyecto

### Mixins

El módulo usa mixins `AbstractModel` para separar el motor de cálculo de los modelos que lo exponen:

| Mixin | Hereda en | Para qué |
|-------|-----------|---------|
| `mrp.schedule.mixin` | plan + wizard | `_schedule_duration`, `INDENT_MAP` |
| `mrp.reschedule.cascade.mixin` | `mrp.reschedule.plan` | motor BFS + scheduling de cascada |
| `mrp.demand.expansion.mixin` | `mrp.production.request` | expansión de BOM |
| `mrp.demand.scheduling.mixin` | `mrp.production.request` | scheduling contra calendario |

**Regla:** si un método de cálculo no necesita persistencia ni fields propios, va al mixin. Si depende de `self._fields`, va al modelo.

### Grupos de seguridad

Definidos en `security/groups.xml`. La visibilidad de menús, botones y pestañas de configuración se controla exclusivamente con estos grupos:

| Grupo | Qué ve / puede hacer |
|-------|---------------------|
| `group_prod_read` | Dashboard de producción (solo lectura) |
| `group_prod` | Dashboard de producción + config de pestaña Producción (implica `group_prod_read`) |
| `group_purchase` | Panel de Compras (solo lectura) |
| `group_purchase_admin` | Panel de Compras + config de proveedores (implica `group_purchase`) |
| `group_sales_read` | Panel de Ventas, forecast y análisis de clientes (solo lectura) |
| `group_sales` | Panel de Ventas + edición/importación de forecast y config (implica `group_sales_read`) |
| `group_scheduling` | Menús Programaciones y Reprogramaciones + su configuración |
| `group_admin` | Todo lo anterior + Configuración completa (implica todos los demás) |

Cada vista XML declara `groups=` en sus `<page>`, `<menuitem>` y `<button>`. Además, los métodos RPC del dashboard verifican grupos en el servidor vía `_ensure_planner_group()` (lectura o admin del área correspondiente).

### Patrón de widgets OWL

Todos los widgets siguen la misma estructura:

```js
// 1. Estado local
this.state = useState({ loading: true, data: null, ... });

// 2. Carga de datos en onMounted (con guard de "Component is destroyed")
onMounted(async () => {
    try {
        await this._load();
    } catch (e) {
        if (e.message !== "Component is destroyed") throw e;
    }
});

// 3. Datos vía RPC
async _load() {
    const result = await this.orm.call("mrp.planner.dashboard", "get_X_data", [filtros]);
    this.state.data = result;
    this.state.loading = false;
}

// 4. Columnas configurables via useColManager (si aplica)
const cols = useColManager(widgetKey, defaultCols);
```

Los widgets que usan Chart.js llaman `await loadBundle("web.chartjs_lib")` antes del primer render. Las funciones de formato puras viven en archivos separados (`forecast_formatters.js`, `customer_analysis_charts.js`).

---

## Diagrama de dependencias (datos)

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (OWL widgets)                                       │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ forecast_    │  │ sales_chart_   │  │ customer_       │  │
│  │ widget.js    │  │ widget.js      │  │ analysis_widget │  │
│  │ + formatters │  │                │  │ + charts        │  │
│  └──────┬───────┘  └───────┬────────┘  └────────┬────────┘  │
│         │ orm.call          │ orm.call            │ orm.call  │
└─────────┼───────────────────┼─────────────────────┼──────────┘
          │ RPC               │ RPC                 │ RPC
┌─────────▼───────────────────▼─────────────────────▼──────────┐
│  mrp.planner.dashboard.*  (TransientModel, sudo reads)        │
│  ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │ dashboard_   │  │ dashboard_ │  │ dashboard_customer   │  │
│  │ forecast.py  │  │ sales.py   │  │ + dashboard_stock    │  │
│  └──────┬───────┘  └─────┬──────┘  └──────────────────────┘  │
└─────────┼────────────────┼──────────────────────────────────┘
          │ sudo reads      │ sudo reads
    ┌─────▼──────┐    ┌─────▼──────┐
    │ mrp.       │    │ sale.order │
    │ forecast.  │    │ stock.move │
    │ line       │    │ ...        │
    └─────┬──────┘    └─────┬──────┘
          │                  │
    ┌─────▼──────────────────▼───────────────┐
    │  mrp.reschedule.config  (singleton)    │
    │  umbrales · métodos · toggles          │
    └────────────────────────────────────────┘
```
