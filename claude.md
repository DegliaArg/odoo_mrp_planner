# odoo_mrp_reschedule — contexto para Claude Code

## Stack
- Odoo 18 SH Enterprise, licencia Enterprise
- Python + OWL (Odoo Web Library)
- Submodule de Deglia-Capemi, rama activa: `18.0-dev`
- Merge a `18.0` tras validar en SH → actualizar pointer en Deglia-Capemi

## Convenciones
- Commits: `[ADD]`, `[FIX]`, `[IMP]`, `[REF]`
- Licencia OPL-1, copyright 2026 Deglia, administracion@deglia.xyz
- Nombres de módulo: `odoo_*`
- Sin `attrs` (Odoo 18 usa expresiones directas en `invisible`, `readonly`)
- `column_invisible="True"` para campos ocultos en listas
- Datetimes: siempre UTC naive en Python; Luxon DateTime en OWL

## Campos confirmados en la instancia
- `mrp.production`: `date_start`, `date_finished`, `origin`,
  `purchase_order_id`, `purchase_line_id`,
  `x_parent_mo_id` (Many2one → mrp.production),
  `x_reschedule_needed` (Boolean)
- `mrp.workorder`: `duration_expected` (float, minutos), `date_finished`
- `mrp.workcenter`: `resource_calendar_id` (Many2one → resource.calendar)
- `resource.calendar.attendance`: `dayofweek`, `hour_from`, `hour_to`,
  `date_from`, `date_to`
- `purchase.order`: `date_order`, `date_planned`
- Campo Studio en `product.template`: `x_studio_cdigo_viejo`
  (no se propaga a `product.product`; acceder via `product_id.product_tmpl_id`)

## Restricciones conocidas
- WC capacity siempre = 1 (sin paralelismo)
- Sin leaves en los calendarios (solo horario estándar)
- PostgreSQL: nombres de tabla máx 63 caracteres

## Arquitectura del módulo

### Motor principal (`models/mrp_reschedule_plan.py`)

Modelo **persistente** `mrp.reschedule.plan` (hereda `mail.thread`, `mail.activity.mixin`).
No es un wizard transitorio — tiene historial, chatter y auditoría completa.

**Secuencia de referencia:** `RESCH/YYYY/XXXX`
**Estados:** `draft` → `calculated` → `applied` | `cancelled`
**Soft delete:** campo `active` (Boolean).

`wc_anchors = {wc_id: datetime}` — un anchor por WC, avanza independientemente.

Métodos clave:
- `action_calculate()` → llama a `_build_lines()`, punto de entrada del cálculo
- `_build_lines()` — constructor del árbol en dos modos:
  - **Modo pivot**: `production_id` definida; reprograma MOs subsecuentes de sus WCs
  - **Modo global**: `production_id` vacía; usa `replan_from` como base para todas las MOs activas
- `_schedule_mo_block()` — itera WOs en secuencia:
  `earliest = max(prev_wo_end, wc_anchors[wc_id], base_dt)`
- `is_anchor=True` → MO fija, solo ancla sus WCs sin reprogramar
- `_schedule_duration()` → respeta attendance del calendario con pytz; límite 365 días
- `action_apply()` → escribe fechas en MOs/POs reales, llama `mo.button_plan()`, registra `applied_date`/`applied_by`
- `_sort_mos_by_priority()` → lee `ir.config_parameter` clave `mrp_reschedule.priority`

Cascada al calcular:
- OCs vinculadas a la MO
- MOs hijas (via `x_parent_mo_id` → fallback `origin`)
- Advertencias: OC confirmada (`purchase`/`done`), hija ajustada al calendario

### Prioridad (`_sort_mos_by_priority`)
Config en `ir.config_parameter` clave `mrp_reschedule.priority`:
- `chronological` (default): orden por `date_start`
- `shortest_first`: duración calculada desde WOs (regla SPT)
- `manual`: respeta `reschedule_sequence` editable en el plan

### Trigger semi-automático (`models/mrp_production.py`)
`write()` override: cuando una MO pasa a `done`/`cancel`,
activa `x_reschedule_needed=True` en MOs subsecuentes de los mismos WCs (limit=20).
Botón inteligente en el form de MO cuando `x_reschedule_needed=True`.
Al abrir el plan de reprogramación, el flag se limpia automáticamente.

### Gantt (vistas XML nativas — sin JS custom)
No hay widget OWL propio. El Gantt usa el componente nativo de Odoo vía XML.
Solo existe CSS custom (`static/src/css/reschedule_gantt.css`).

Cuatro vistas Gantt definidas en `mrp_reschedule_plan_views.xml`:
1. `gantt_current` — fechas actuales (`current_date_start/finish`) antes del replan
2. `gantt` — fechas propuestas (`new_date_start/finish`) tras el cálculo
3. `wc_line_gantt` — carga por WC (`MrpReschedulePlanWcLine`)
4. `gantt_global` — todas las líneas de todos los planes

### Wizard de nueva programación (`wizard/mrp_production_request.py`)
Flujo alternativo para crear MOs nuevas desde demanda.
Modelos **transitorios**:
- `mrp.production.request` — cabecera del wizard; campo `start_from`
- `mrp.production.request.item` — fila de entrada (producto, cantidad, fecha límite);
  computed: `projected_end`, `feasible`, `feasibility_msg`
- `mrp.production.request.line` — líneas de resultado (solo lectura)

Métodos clave:
- `_build_demand_tree()` — expansión recursiva de BOM; detecta rutas: `manufacture` / `buy` / `stock`
- `_schedule_tree()` — scheduler bottom-up con `wc_anchors` compartidos entre ítems
- `action_calculate()` — valida BOMs, construye árboles, acumula líneas con viabilidad
- `action_confirm()` — crea solo MOs de nivel 0; las hijas las genera Odoo vía reglas de aprovisionamiento

## Modelos persistentes
- `mrp.reschedule.plan`
- `mrp.reschedule.plan.line`
  Campos clave: `apply`, `is_anchor`, `forced_start_date`, `reschedule_sequence`,
  `duration_hours`, `warning_type`, `warning_message`, `record_type`, `level`,
  `production_id`, `purchase_id`, `current/new_date_start/finish`, `delta_display`
- `mrp.reschedule.plan.wc.line`
  Campos clave: `production_id`, `workorder_id`, `workcenter_id`,
  `new_date_start`, `new_date_finish`

## Estructura de archivos
```
odoo_mrp_reschedule/
├── __init__.py
├── __manifest__.py          (version 18.0.8.0.0, depends: mrp, purchase, mail)
├── models/
│   ├── __init__.py
│   ├── mrp_production.py        (x_parent_mo_id, x_reschedule_needed, write override)
│   ├── mrp_reschedule_plan.py   (motor principal — plan persistente + algoritmo)
│   └── res_config_settings.py  (mrp_reschedule_priority)
├── security/
│   └── ir.model.access.csv
├── static/src/css/
│   └── reschedule_gantt.css
├── views/
│   ├── mrp_production_views.xml         (extensión form MO, acción lista)
│   ├── mrp_reschedule_plan_views.xml    (plan form/list, 4 Gantt, menús)
│   └── res_config_settings_views.xml
└── wizard/
    ├── __init__.py
    ├── mrp_production_request.py        (wizard nueva programación — transitorio)
    └── mrp_production_request_views.xml
```

## Menús (bajo MRP → Reprogramación)
- **Nueva programación** → wizard `mrp.production.request`
- **Planes** → lista/form de `mrp.reschedule.plan`
- **Carga de WC (propuesto)** → Gantt `wc_line_gantt`
- **Árbol de órdenes** → lista global de todas las líneas
- **Estado real de WC** → Gantt de workorders reales

## Notas de debugging
- Errores de instalación: revisar primero `ir.model.access.csv` y el orden
  de archivos en `data` del manifest
- Assets CSS: hacer upgrade del módulo tras cambios para limpiar caché
- Campos `store=False` en One2many: deben estar en la vista list para
  que el widget OWL los pueda leer desde `props.record.data`
- `_schedule_duration` asume datetimes UTC naive; verificar si hay tzinfo
  antes de pasar
- `production_id` en `mrp.reschedule.plan` es nullable (modo global);
  la migración en `_auto_init` elimina el NOT NULL de la columna si existe
- `x_studio_cdigo_viejo` vive en `product.template`, no en `product.product`;
  acceder siempre via `mo.product_id.product_tmpl_id`
