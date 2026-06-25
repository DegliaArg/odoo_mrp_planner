# Review — odoo_mrp_planner

## Resumen ejecutivo

Revisión completa del módulo en 7 fases. Se encontraron **2 vulnerabilidades de seguridad críticas** (acceso ORM bypasseable al sistema de permisos y a la configuración global), **1 bug crítico de instalación** (ID de base de datos hardcodeado), **1 bug de lógica** en el mixin de scheduling y múltiples issues de performance y estructura. Se corrigieron directamente 15 problemas de severidad media-alta. Quedan 8 decisiones pendientes de equipo documentadas al final.

---

## 🔴 Crítico (seguridad / bugs bloqueantes)

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| 1 | `security/ir.model.access.csv` | 12 | `mrp.reschedule.config` editable por cualquier usuario (CRUD): un usuario básico podía borrar la configuración global, cambiar umbrales de alertas o el intervalo del cron | **Corregido** — separado en read para `group_user` + CRUD para `group_mrp_manager` |
| 2 | `security/ir.model.access.csv` | 15 | `mrp.reschedule.user.permission` creatable por cualquier usuario: un usuario podía crearse su propio registro de permisos y otorgarse `can_schedule=True`, `can_reschedule=True`, etc., bypasseando completamente el sistema de permisos del módulo | **Corregido** — separado en read para `group_user` + CRUD para `group_mrp_manager` |
| 3 | `wizard/mrp_production_request.py` | 179 | `picking_type_id` default `browse(518)`: ID de base de datos específico de la instancia de desarrollo. En cualquier otra instalación apunta a otro registro o inexistente | **Corregido** — reemplazado por `search([('code', '=', 'mrp_operation'), ('company_id', ...)], limit=1)` |
| 4 | `models/mrp_reschedule_config.py` | 113 | Sin protección contra creación de múltiples singletons: dos configs coexistentes producen comportamiento no determinista (el cron puede usar umbrales distintos a los que muestra la UI) | **Corregido** — `create()` lanza `UserError` si ya existe un registro |
| 5 | `models/mrp_reschedule_alert.py` | 152 | `action_run_cron_manual()` sin guard de grupo: cualquier usuario con acceso al modelo podía ejecutar búsquedas masivas sobre toda la instancia repetidamente | **Corregido** — requiere `mrp.group_mrp_manager` |

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
| 20 | Todos los widgets JS | Sin JSDoc, sin `static props`, sin documentación del contrato de RPCs ni de la estructura de datos esperada | Pendiente (ver decisiones) |
| 21 | `mrp_reschedule_alert.py` | `days_late` es campo estático: entre corridas del cron el valor mostrado al usuario puede estar desactualizado | Requiere decisión (ver abajo) |
| 22 | `mrp_reschedule_alert.py` | `_check_qty_mismatches()` ventana temporal de 1 hora hardcodeada; si el cron corre cada 2h, pierde OFs terminadas entre ciclos | Requiere decisión (ver abajo) |
| 23 | `mrp_reschedule_plan.py` | `_get_subsequent_mos()` heurística por WC compartido incluye OFs no relacionadas con la cadena del pivot | Requiere decisión (ver abajo) |
| 24 | `mrp_reschedule_plan.py` | `add_mo()` sin límite de profundidad recursiva: árboles de más de ~100 niveles de sub-ÓFs pueden provocar `RecursionError` | Requiere decisión (ver abajo) |
| 25 | `mrp_planner_detail_dashboard_views.xml` | Dos botones con `name="action_view_overdue_pos"`: la tarjeta "Críticas" debería llamar a una acción con filtro diferente al de "Vencidas" | Requiere decisión (ver abajo) |
| 26 | `mrp_reschedule_plan_views.xml` | `domain` en `production_id` solo muestra `state='confirmed'`, excluyendo OFs `in_progress` candidatas válidas | Requiere decisión (ver abajo) |
| 27 | `mrp_production.py` | `_compute_reschedule_plan_count()` hace 2 búsquedas por OF (N+1 en lista), optimizable con 2 `read_group` | Requiere decisión (ver abajo) |

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

---

## Decisiones pendientes para el equipo

1. **`days_late` como campo computado vs estático** (`mrp_reschedule_alert.py:54`): el campo `days_late` no se recalcula entre corridas del cron; el dashboard puede mostrar "3 días de atraso" cuando ya pasaron 10. Convertirlo a compute tiene costo de performance (recalculo al leer la lista de alertas). ¿Vale la precisión?

2. **Ventana temporal en `_check_qty_mismatches()`** (`mrp_reschedule_alert.py:434`): la ventana de 1 hora es fija e independiente del `cron_interval_number` configurado. Si el cron corre cada 2h, OFs terminadas entre ciclos no generan alerta de cantidad. Solución: leer `cron_interval_number + cron_interval_type` del config para calcular la ventana dinámicamente.

3. **Heurística de "dependientes" en `_get_subsequent_mos()`** (`mrp_reschedule_plan.py:295`): la búsqueda incluye toda OF que comparte WC con el pivot y empieza después, independientemente de si hay relación real. Esto puede generar reprogramaciones masivas no deseadas en producción con alta carga. Requiere definir qué constituye una "dependencia real" (¿solo `x_parent_mo_id`? ¿por componentes compartidos?).

4. **Límite de profundidad en `add_mo()`** (`mrp_reschedule_plan.py:508`): árboles de sub-ÓFs de 100+ niveles pueden provocar `RecursionError`. Solución: convertir la recursión a iterativo con una pila explícita o añadir un `MAX_DEPTH = 50` con warning al usuario si se corta.

5. **Dos botones `action_view_overdue_pos` en detail dashboard** (`mrp_planner_detail_dashboard_views.xml:207`): las tarjetas "Vencidas" y "Críticas (+N días)" abren la misma acción. ¿Se quiere una acción específica para "críticas" con filtro de días, o es intencional?

6. **`domain` en `production_id` solo muestra `confirmed`** (`mrp_reschedule_plan_views.xml:128`): el selector de ÓF pivot en el wizard de reprogramación excluye OFs en estado `progress` y `to_close`. ¿Es intencional? Generalmente las OFs en progreso también pueden necesitar reprogramación.

7. **`_compute_reschedule_plan_count()` N+1** (`mrp_production.py:188`): hace 2 búsquedas SQL por OF en lista. La optimización requiere 2 `read_group` + lógica de unión de sets, es un cambio de mayor complejidad. Anotar como deuda técnica.

8. **Documentación de contratos de widgets OWL**: ningún widget tiene JSDoc, `static props`, ni documentación de la estructura JSON que devuelven los métodos Python. No es bloqueante pero dificulta el mantenimiento. Se recomienda añadir en el próximo ciclo de desarrollo.
