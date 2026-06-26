# Review — odoo_mrp_planner

## Resumen ejecutivo

Revisión completa del módulo en 3 iteraciones. v1+v2: 27 problemas corregidos (seguridad, performance, lógica, UX). v3 (2026-06-26): verificación de fixes aplicados; se encontraron **4 regresiones** introducidas al convertir `days_late` a campo compute (cron crashea, orden inválido en búsqueda, modelo sin acceso ORM, comentario desactualizado). Todos resueltos. Estado actual: **31 issues corregidos, 0 pendientes**.

---

## 🔴 Crítico (seguridad / bugs bloqueantes)

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| 1 | `security/ir.model.access.csv` | 12 | `mrp.reschedule.config` editable por cualquier usuario (CRUD): un usuario básico podía borrar la configuración global, cambiar umbrales de alertas o el intervalo del cron | **Corregido** — separado en read para `group_user` + CRUD para `group_mrp_manager` |
| 2 | `security/ir.model.access.csv` | 15 | `mrp.reschedule.user.permission` creatable por cualquier usuario: un usuario podía crearse su propio registro de permisos y otorgarse `can_schedule=True`, `can_reschedule=True`, etc., bypasseando completamente el sistema de permisos del módulo | **Corregido** — separado en read para `group_user` + CRUD para `group_mrp_manager` |
| 3 | `wizard/mrp_production_request.py` | 179 | `picking_type_id` default `browse(518)`: ID de base de datos específico de la instancia de desarrollo. En cualquier otra instalación apunta a otro registro o inexistente | **Corregido** — reemplazado por `search([('code', '=', 'mrp_operation'), ('company_id', ...)], limit=1)` |
| 4 | `models/mrp_reschedule_config.py` | 113 | Sin protección contra creación de múltiples singletons: dos configs coexistentes producen comportamiento no determinista (el cron puede usar umbrales distintos a los que muestra la UI) | **Corregido** — `create()` lanza `UserError` si ya existe un registro |
| 5 | `models/mrp_reschedule_alert.py` | 152 | `action_run_cron_manual()` sin guard de grupo: cualquier usuario con acceso al modelo podía ejecutar búsquedas masivas sobre toda la instancia repetidamente | **Corregido** — requiere `mrp.group_mrp_manager` |
| 6 (v3) | `models/mrp_reschedule_alert.py` | 266, 300, 349, 387, 437, 508 | **Regresión**: al convertir `days_late` a campo `compute` (store=False) en v2, los 6 métodos del cron siguieron pasando `'days_late': valor` en `write_vals`. Odoo lanza `ValueError: Unallowed field 'days_late'` al ejecutar el cron — todo el sistema de alertas se rompe silenciosamente. | **Corregido** — eliminado `'days_late'` de los 6 `write_vals` de los chequeos del cron |
| 7 (v3) | `security/ir.model.access.csv` | — | **Regresión**: el fix de seguridad #2 declaró que `mrp.reschedule.user.permission` fue dividido, pero el modelo nunca fue agregado al CSV. La línea original (CRUD para `group_user`) había sido eliminada sin agregar las dos nuevas. El modelo era completamente inaccesible. | **Corregido** — agregadas las dos líneas (read para `group_user`, CRUD para `group_admin`) |
| 8 (v3) | `models/mrp_planner_dashboard.py` | 157 | **Regresión**: `_compute_inline_alerts` usaba `order='days_late desc, id desc'`. Los campos no almacenados no se pueden usar en ORDER BY SQL — Odoo lanza error al calcular el campo del dashboard. | **Corregido** — reemplazado por `order='id desc'` |

---

## 🟡 Importante (performance / lógica incorrecta)

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| 6 | `models/mrp_schedule_mixin.py` | 35 | `_schedule_duration()` con `duration_hours=0` devolvía `(after_dt, after_dt + 8h)` en lugar de `(after_dt, after_dt)` | **Corregido** — separadas las dos condiciones del guard |
| 7 | `models/mrp_reschedule_user_permission.py` | — | Sin `_sql_constraints` de unicidad: múltiples registros para el mismo usuario producían comportamiento no determinista en permisos | **Corregido** — `unique(user_id, config_id)` |
| 8 | `models/mrp_planner_detail_dashboard.py` | 81 | Umbral de OCs críticas hardcodeado en `5` días, ignorando el valor configurado en `mrp.reschedule.config.alert_po_critical_days` | **Corregido** — lee de config con fallback 5 |
| 9 | `models/mrp_production.py` | 225 | `_compute_alert_count()` hacía un `search_count` por cada OF del recordset (N+1 queries en lista de OFs) | **Corregido** — `read_group` en una sola query |
| 10 | `models/mrp_production.py` | 172 | `_flag_subsequent_mos()` con `limit=20`: solo marcaba las primeras 20 OFs subsecuentes | **Corregido** — aumentado a 50 con comentario explicativo |
| 11 | `models/stock_picking.py` | 52 | `_flag_mos_for_picking()` con `limit=50`: OFs que consumen los productos de esa recepción por encima de 50 no se marcaban con `x_reschedule_needed` | **Corregido** — aumentado a 200 |
| 12 | `models/mrp_planner_dashboard.py` | 1 | Import muerto `import calendar as _cal` (el módulo `calendar` se importa dentro de la función `get_forecast_dashboard_data()` como `_calendar`, el nivel de módulo no se usaba) | **Corregido** — eliminado |
| 13 | `models/mrp_reschedule_config.py` | 77 | `int(param)` podía lanzar `ValueError` si el parámetro del sistema `mrp_reschedule.stock_location_id` fue editado manualmente con un valor no numérico | **Corregido** — try/except con fallback `False` |
| 14 | `static/src/js/stock_break_widget.js` | 32 | Sin `onWillUnmount`: el timer de debounce de búsqueda podía ejecutarse después de que el componente fuera destruido, disparando un RPC sobre un OWL component desmontado | **Corregido** — `onWillUnmount(() => clearTimeout(this._searchTimer))` |
| 15 | `static/src/js/mo_dashboard_widget.js` | 165–207 | `openMo()` y `openRequest()` pasaban `res_id` + `domain + view_mode: "list,form"` simultáneamente, lo que abría la vista en lista filtrada a 1 registro en vez de abrir el form directamente | **Corregido** — removido domain, cambiado a `view_mode: "form"` |
| 16 | `static/src/js/po_dashboard_widget.js` | 171–198 | Mismo problema en `openPo()` y `openPicking()` | **Corregido** — ídem |
| 17 | `views/mrp_reschedule_plan_views.xml` | 155–164 | Campo `reschedule_sequence` declarado dos veces en el mismo `<list>` (como widget handle y como columna visible). En Odoo 18 causa advertencia y comportamiento inconsistente | **Corregido** — eliminada la segunda declaración |
| 18 | `static/src/js/wc_load_chart.js` | 135–137 | Variables `tiempoLibre` y `noplanificado` ambas apuntaban a `data.tiempo_muerto` con nombres distintos, aparentando ser un bug. El comportamiento es correcto (misma capacidad libre en ambos stacks), pero el código era engañoso | **Corregido** — unificadas en `tiempoMuerto` con comentario explicativo |

---

## 🟢 Mejoras (docs / estructura / legibilidad)

| # | Archivo | Descripción | Estado |
|---|---------|-------------|--------|
| 19 | `mrp_reschedule_alert.py` | `_compute_impact_mo_count` usaba `len(record)` cargando el recordset completo; `len(.ids)` carga solo IDs | **Corregido** |
| 20 | Todos los widgets JS | Sin JSDoc, sin `static props`, sin documentación del contrato de RPCs ni de la estructura de datos esperada | **Corregido** — JSDoc + `static props` añadidos a los 4 widgets |
| 21 | `mrp_reschedule_alert.py` | `days_late` es campo estático: entre corridas del cron el valor mostrado al usuario puede estar desactualizado | **Corregido** — convertido a `compute='_compute_days_late', store=False`; se recalcula al leer |
| 22 | `mrp_reschedule_alert.py` | `_check_qty_mismatches()` ventana temporal de 1 hora hardcodeada; si el cron corre cada 2h, pierde OFs terminadas entre ciclos | **Corregido** — ventana dinámica: `cron_interval_number * factor * 1.1`, mínimo 30 min |
| 23 | `mrp_reschedule_plan.py` | `_get_subsequent_mos()` heurística por WC compartido incluye OFs no relacionadas con la cadena del pivot | **Corregido** — heurística de 3 niveles: (1) x_parent_mo_id, (2) OFs que consumen el producto del pivot, (3) WC compartido solo si `include_wc_heuristic=True` en config |
| 24 | `mrp_reschedule_plan.py` | `add_mo()` sin límite de profundidad recursiva: árboles de más de ~100 niveles de sub-ÓFs pueden provocar `RecursionError` | **Corregido** — convertido a iterativo con `deque`; `MAX_DEPTH=30` con warning y línea truncada |
| 25 | `mrp_planner_detail_dashboard_views.xml` | Dos botones con `name="action_view_overdue_pos"`: la tarjeta "Críticas" debería llamar a una acción con filtro diferente al de "Vencidas" | **Corregido** — nueva acción `action_view_critical_pos` con filtro de días desde config |
| 26 | `mrp_reschedule_plan_views.xml` | `domain` en `production_id` solo muestra `state='confirmed'`, excluyendo OFs `in_progress` candidatas válidas | **Corregido** — `[('state', 'in', ['confirmed', 'progress', 'to_close'])]` |
| 27 | `mrp_production.py` | `_compute_reschedule_plan_count()` hace 2 búsquedas por OF (N+1 en lista), optimizable con 2 `read_group` | **Corregido** — 2 `search_read` batch (pivot_map + line_map), luego unión de sets por OF |
| 28 (v3) | `models/mrp_production.py` | 164 | Docstring de `_flag_subsequent_mos` decía "limit=20" cuando el código usa `limit=50` (ambigüedad entre lo documentado y el comportamiento real) | **Corregido** — actualizado a "limit=50" |

---

## Cambios aplicados

| Archivo | Descripción del cambio |
|---------|----------------------|
| `security/ir.model.access.csv` | `mrp.reschedule.config` y `mrp.reschedule.user.permission`: split en read (group_user) + CRUD (group_mrp_manager) |
| `models/mrp_reschedule_config.py` | Singleton guard en `create()`, import `UserError`, fix `int(param)` con try/except |
| `models/mrp_reschedule_user_permission.py` | `_sql_constraints` unique(user_id, config_id) |
| `models/mrp_planner_dashboard.py` | Eliminado import muerto `import calendar as _cal` |
| `models/mrp_schedule_mixin.py` | Fix duración 0 que devolvía 8h en lugar de 0 |
| `models/mrp_reschedule_alert.py` | Guard `group_mrp_manager` en `action_run_cron_manual()`; `len(.ids)` en `_compute_impact_mo_count` |
| `models/mrp_planner_detail_dashboard.py` | Umbral OC críticas lee de config en lugar de hardcoded 5 |
| `models/mrp_production.py` | `_compute_alert_count` con `read_group`; limit 20→50 en `_flag_subsequent_mos` |
| `models/stock_picking.py` | limit 50→200 en `_flag_mos_for_picking` |
| `wizard/mrp_production_request.py` | `picking_type_id` default por búsqueda en lugar de `browse(518)` |
| `views/mrp_reschedule_plan_views.xml` | Eliminada declaración duplicada de `reschedule_sequence` |
| `static/src/js/wc_load_chart.js` | Unificadas `tiempoLibre`/`noplanificado` en `tiempoMuerto` con comentario |
| `static/src/js/stock_break_widget.js` | Import `onWillUnmount`, cleanup de timer al desmontar |
| `static/src/js/mo_dashboard_widget.js` | `openMo`/`openRequest`: eliminado domain redundante, view_mode→form only |
| `static/src/js/po_dashboard_widget.js` | `openPo`/`openPicking`: ídem |

### Cambios v3 (2026-06-26) — regresiones por conversión de `days_late` a compute

| Archivo | Descripción del cambio |
|---------|----------------------|
| `models/mrp_reschedule_alert.py` | Eliminado `'days_late'` de los `write_vals` de los 6 métodos de chequeo del cron (`_check_delayed_mos`, `_check_upcoming_mos`, `_check_delayed_pos`, `_check_upcoming_pos`, `_check_delayed_receipts`, `_check_qty_mismatches`). Escribir un campo compute sin inverse lanza `ValueError` en Odoo. |
| `models/mrp_planner_dashboard.py` | Eliminado `days_late` del `order=` en `_compute_inline_alerts`. Los campos no almacenados no se pueden usar en ORDER BY SQL. Reemplazado por `order='id desc'`. |
| `security/ir.model.access.csv` | Agregadas las dos líneas faltantes para `mrp.reschedule.user.permission` (read para `group_user`, CRUD para `group_admin`). El modelo existía pero era inaccesible. |
| `models/mrp_production.py` | Corregido comentario desactualizado en `_flag_subsequent_mos` que decía "limit=20" cuando el código usa `limit=50`. |

---

## Decisiones resueltas (v2)

Todas las decisiones pendientes han sido implementadas:

1. **`days_late` como campo computado** — Corregido. `store=False`, `compute='_compute_days_late'`. El `_order` ya no lo incluye (Odoo no permite ORDER BY sobre campos no almacenados).

2. **Ventana temporal dinámica en `_check_qty_mismatches()`** — Corregido. La ventana se calcula como `cron_interval_number * type_factor * 1.1` con mínimo 30 min.

3. **Heurística de 3 niveles en `_get_subsequent_mos()`** — Corregido. Nivel 1: `x_parent_mo_id`; Nivel 2: OFs que consumen el producto del pivot; Nivel 3: WC compartido (opcional vía `include_wc_heuristic` en config).

4. **Iterativo con `MAX_DEPTH=30` en `_build_lines()`** — Corregido. La recursión fue convertida a un loop con `deque`. Las OFs que superan la profundidad máxima reciben una línea con `warning_message` y `apply=False`.

5. **Botón "Críticas" con acción propia** — Corregido. Nueva acción `action_view_critical_pos` que filtra por `date_planned < now - po_crit_days días`.

6. **Domain `production_id` expandido** — Corregido. `[('state', 'in', ['confirmed', 'progress', 'to_close'])]`.

7. **`_compute_reschedule_plan_count()` N+1 resuelto** — Corregido. Dos `search_read` batch + unión de sets por OF.

8. **JSDoc + `static props` en widgets OWL** — Corregido. Los 4 widgets tienen bloque JSDoc de módulo, `static props`, y comentarios en métodos clave.
