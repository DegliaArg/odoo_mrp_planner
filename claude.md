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

## Restricciones conocidas
- WC capacity siempre = 1 (sin paralelismo)
- Sin leaves en los calendarios (solo horario estándar)
- PostgreSQL: nombres de tabla máx 63 caracteres

## Arquitectura del módulo

### Algoritmo principal (`wizard/mrp_reschedule_wizard.py`)
`wc_anchors = {wc_id: datetime}` — un anchor por WC, avanza independientemente.

Para cada MO subsecuente:
- `_schedule_mo_block()`: itera WOs en secuencia,
  `earliest = max(prev_wo_end, wc_anchors[wc_id], base_dt)`
- `is_anchor=True` → MO fija, solo ancla sus WCs sin reprogramar
- `_schedule_duration()` → respeta attendance del calendario, sin leaves
- Cascada: OCs vinculadas + MOs hijas (via `x_parent_mo_id` → fallback `origin`)
- Advertencias: OC confirmada (`purchase`/`done`), hija ajustada al calendario

### Prioridad (`_sort_mos_by_priority`)
Config en `ir.config_parameter` clave `mrp_reschedule.priority`:
- `chronological` (default): orden por `date_start`
- `shortest_first`: duración calculada desde WOs
- `manual`: respeta `reschedule_sequence` editable en el wizard

### Trigger semi-automático (`models/mrp_production.py`)
`write()` override: cuando una MO pasa a `done`/`cancel`,
activa `x_reschedule_needed=True` en MOs subsecuentes de los mismos WCs.
Botón inteligente en el form de MO cuando `x_reschedule_needed=True`.

### Gantt OWL (`static/src/js/mrp_reschedule_gantt.js`)
Widget `reschedule_gantt` registrado en `view_widgets`.
Lee `line_ids.records` via `props.record.data`.
Barras dimmed cuando `apply=False` (`is_anchor=True`).
Toggle "Mostrar posición original".

## Modelos transitorios
- `mrp.reschedule.wizard`
- `mrp.reschedule.wizard.line`
  Campos clave: `apply`, `is_anchor`, `reschedule_sequence`, `duration_hours`,
  `warning_type`, `warning_message`, `record_type`, `level`,
  `production_id`, `purchase_id`, `current/new_date_start/finish`

## Estructura de archivos
odoo_mrp_reschedule/
├── init.py
├── manifest.py          (version 18.0.2.0.0, depends: mrp, purchase)
├── models/
│   ├── init.py
│   ├── mrp_production.py    (x_parent_mo_id, x_reschedule_needed, write override)
│   └── res_config_settings.py  (mrp_reschedule_priority)
├── security/
│   └── ir.model.access.csv
├── static/src/js/
│   └── mrp_reschedule_gantt.js
├── views/
│   ├── mrp_production_views.xml
│   └── res_config_settings_views.xml
└── wizard/
├── init.py
├── mrp_reschedule_wizard.py
└── mrp_reschedule_wizard_views.xml

## Notas de debugging
- Errores de instalación: revisar primero `ir.model.access.csv` y el orden
  de archivos en `data` del manifest
- Assets JS: hacer upgrade del módulo tras cambios en JS para limpiar caché
- Campos `store=False` en One2many: deben estar en la vista list para
  que el widget OWL los pueda leer desde `props.record.data`
- `_schedule_duration` asume datetimes UTC naive; verificar si hay tzinfo
  antes de pasar