# Revisión completa del módulo odoo_mrp_planner

**Fecha:** 2026-07-02
**Revisor:** Claude Code (claude-sonnet-4-6)
**Rama:** 18.0
**Alcance:** Fases 2–13 (seguridad, estructura, código muerto, optimización Python, OWL/JS, vistas XML, UX/UI, documentación, calidad) — revisión completa multi-agente

---

## Resumen ejecutivo

El módulo está funcionalmente maduro: la lógica de cascada, alertas, forecast y dashboard están implementadas y operativas. La revisión de 10 agentes de análisis encontró findings en seguridad, optimización Python, OWL/JS y calidad. Al verificar el código real contra cada finding, se confirmó que varios ya habían sido corregidos en commits recientes: `_upsert_alert` implementado, `@api.depends` correcto en alertas, try/except en `int(loc_param)`, `noupdate="1"` en crons de categoría, grupos correctos en `action_run_cron_manual`, `statusbar_visible` con "cancelled", `static props` en widgets, logging en crons, confirm mejorado en botón cancelar.

Los issues reales aplicados en esta sesión cubrieron: guards de grupo faltantes en acciones destructivas, N+1 queries en métodos RPC del dashboard, inconsistencia UTC en drill-down de forecast, RPCs paralelas en widgets JS, y ajustes de accesibilidad/búsqueda en vistas XML.

El riesgo principal sin resolver está en **seguridad a nivel de CSV**: los modelos de planes, alertas y forecast tienen CRUD completo para `base.group_user`, lo que requiere decisión de diseño del equipo antes de ajustar.

---

## 🔴 Issues Críticos

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| C-01 | `security/ir.model.access.csv` | 2–8, 18 | Modelos de planes, alertas y forecast tienen CRUD completo (1,1,1,1) para `base.group_user`. Cualquier usuario interno puede borrar planes y alertas de otros usuarios. | **Requiere decisión** |
| C-02 | `security/ir.model.access.csv` | 19 | El wizard `mrp.forecast.import.wizard` tiene CRUD para `base.group_user`. `action_import()` hace `unlink` masivo de todas las líneas de forecast de la empresa sin check de grupo. | **Requiere decisión** |
| C-03 | `models/mrp_reschedule_plan.py` | 176–187 | `action_reset_draft()` y `action_cancel()` no tenían guard de grupo: cualquier usuario podía resetear/cancelar planes ajenos. | **Corregido** |
| C-04 | `models/mrp_reschedule_config.py` | 829–836 | Guard de singleton en `create()` vulnerable a race condition con `vals_list` multi-elemento. No hay `_sql_constraints` de unicidad a nivel de BD. | **Requiere decisión** |
| C-05 | `models/mrp_planner_dashboard.py` | 558–561 | N+1 queries en `get_wc_tags()`: un `search_count` por tag para verificar si tiene WCs activos. | **Corregido** |
| C-06 | `models/mrp_planner_dashboard.py` | 2252–2262 | N+1 queries en `get_product_categories_for_chart()`: un `search_count` por categoría para verificar si tiene productos vendibles. | **Corregido** |
| C-07 | `models/mrp_planner_dashboard.py` | 2173–2200 | N+1 browse en `get_sales_chart_data()`: `browse(product_id[0])` individual por cada fila de `read_group`. | **Requiere decisión** |
| C-08 | `models/mrp_reschedule_plan.py` | 362–392 | N+1 queries en `_build_lines()`: `_get_pos_for_mo()` y `_get_child_mos()` emiten hasta 4 búsquedas por OF en el BFS. Con cascadas de N órdenes: hasta 4N queries. | **Requiere decisión** |
| C-09 | `wizard/mrp_production_request_views.xml` | 51–62 | Botones `action_confirm` (Crear OFs) y `action_plan_all_mos` (Planificar OFs) sin atributo `groups`. Cualquier usuario interno podía crear OFs. | **Corregido** |
| C-10 | `models/mrp_planner_dashboard.py` | 1741 | `so_demand_no_fc` faltaba filtro `sale_ok=True`, inflando el contador con productos internos. | **Verificado — ya corregido** |
| C-11 | `models/mrp_reschedule_alert.py` | N/A | `_upsert_alert()` faltaba — callers en `mrp_production.py` y `purchase_order.py` silenciaban el `AttributeError`. | **Verificado — ya implementado** |

---

## 🟡 Issues Importantes

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| I-01 | `models/mrp_planner_dashboard.py` | 1973 | `int(loc_param)` sin try/except en `get_stock_breaks_kpis()`. | **Verificado — ya tiene try/except** |
| I-02 | `models/mrp_reschedule_alert.py` | 107–108 | `action_resolve()` sin guard de grupo: cualquier usuario podía marcar alertas ajenas como resueltas. | **Corregido** |
| I-03 | `models/mrp_reschedule_config.py` | 348, 463, 676 | `action_auto_assign_sale_categories()`, `action_compute_supplier_categories()`, `action_compute_customer_categories()` sin verificación de grupo. Hacen write masivo en `product.template` y `res.partner`. | **Corregido** |
| I-04 | `models/mrp_reschedule_config.py` | 771–826 | `cron.sudo().write()` sin comentario justificando el escalado. | **Verificado — ya tiene comentarios** |
| I-05 | `security/` | N/A | `mrp.forecast.line` tiene `company_id` pero no hay record rules de multi-empresa. Un usuario de empresa A puede leer/escribir forecast de empresa B. | **Requiere decisión** |
| I-06 | `models/mrp_reschedule_alert.py` | 78–79 | `_compute_days_late()` necesita `@api.depends` con campos relacionales. | **Verificado — ya correcto** |
| I-07 | `models/mrp_reschedule_alert.py` | 99–103 | `_compute_impact_mo_count()` necesita `@api.depends('impact_mo_ids')`. | **Verificado — ya correcto** |
| I-08 | `models/mrp_reschedule_alert.py` | 174 | `action_run_cron_manual` verificaba `mrp.group_mrp_manager` (grupo nativo Odoo) en lugar de `odoo_mrp_planner.group_admin`. | **Verificado — ya corregido** |
| I-09 | `views/mrp_reschedule_alert_views.xml` | 18–51 | Crons de categorías tenían `noupdate="0"`, el upgrade reseteaba el estado activo/inactivo configurado por el usuario. | **Verificado — ya corregido (noupdate="1")** |
| I-10 | `__manifest__.py` | 59 | Entrada `mo_list_widget.js` sin indentación (columna 0 en lugar de 12 espacios). | **Corregido** |
| I-11 | `models/mrp_planner_dashboard.py` | 179–262 | `_compute_mo_stats()` y `_compute_po_stats()` ejecutan `search()` y config lookup dentro del bucle `for rec in self`. | **Requiere decisión** |
| I-12 | `models/mrp_reschedule_alert.py` | 12–15 | `mrp.reschedule.alert` no hereda `mail.thread`. No hay historial de quién resolvió cada alerta con comentario. | **Requiere decisión** |
| I-13 | `views/mrp_reschedule_plan_views.xml` | 76 | Botón "Aplicar cambios" usaba `groups='mrp.group_mrp_manager'` pero Python verificaba `group_prod`/`group_admin`. | **Verificado — ya alineado** |
| I-14 | `views/mrp_reschedule_alert_views.xml` | 89–92 | Vista búsqueda de alertas sin group_by por `product_id`. | **Corregido** |
| I-15 | `views/mrp_reschedule_plan_views.xml` | 27–29 | Vista búsqueda de planes sin group_by por `production_id` ni `applied_by`. | **Corregido** |
| I-16 | `models/mrp_planner_dashboard.py` | 1821–1836 | `get_product_mos_for_forecast()` usaba tiempo local en lugar de UTC para el dominio, desincronizando el acordeón con la tabla principal para usuarios en zonas UTC-. | **Corregido** |
| I-17 | `models/mrp_reschedule_config.py` | 451–755 | Métodos de cron sin logging de inicio/fin. | **Verificado — ya tienen logging** |
| I-18 | `static/src/js/mo_list_widget.js` | 32–35 | `_loadTags()` y `_loadMos()` en serie en `onMounted`. | **Corregido** |
| I-19 | `static/src/js/wc_load_chart.js` | 35–39 | `_loadTags()` y `_loadChart()` en serie en `onMounted`. | **Corregido** |
| I-20 | `static/src/js/mo_dashboard_widget.js` | 89–93 | `_loadTags()` y `_loadData()` en serie en `onMounted`. | **Corregido** |
| I-21 | `static/src/js/sales_chart_widget.js` | 46–52 | `get_product_categories_for_chart` y `_load()` en serie en `onMounted`. | **Corregido** |
| I-22 | `static/src/js/forecast_widget.js` | 622–624 | `_periodDateRange()` construye strings de datetime en hora local para dominios RPC que Odoo interpreta como UTC. Discrepancia entre tabla principal y drill-down para usuarios en zonas UTC-. | **Requiere decisión** |
| I-23 | `models/mrp_product_type.py` | 9 | `mrp.product.type` sin `_sql_constraints` de unicidad de nombre. | **Verificado — ya tiene constraint** |
| I-24 | `views/purchase_order_views.xml` | 1–3 | Archivo vacío declarado en manifest sin comentario explicativo. | **Corregido** |

---

## 🟢 Mejoras (improvements)

| # | Área | Descripción | Estado |
|---|------|-------------|--------|
| G-01 | Python | `_parse_date` duplicada en dos métodos del dashboard. Extraer a función de módulo. | **Requiere decisión** |
| G-02 | Python | Patrón `env['mrp.reschedule.config'].search([], limit=1)` repetido 8 veces en 4 archivos. Mover `_get_config` al mixin. | **Requiere decisión** |
| G-03 | Python | Constante `8.0` (horas jornada) en dos archivos sin nombre. Definir `DEFAULT_SHIFT_HOURS = 8.0`. | **Requiere decisión** |
| G-04 | Python | Factor `/ 60.0` (minutos→horas) repetido 7 veces en 2 archivos. Definir `MINS_PER_HOUR = 60.0`. | **Requiere decisión** |
| G-05 | Python | `_fmt_delta_secs` duplicada entre `_compute_delta_display` y `_compute_delta_display_line`. | **Requiere decisión** |
| G-06 | Python | `DEFAULT_PO_CRITICAL_DAYS = 5` hardcodeado en 5 sitios. | **Requiere decisión** |
| G-07 | Python | `get_wc_load_data` método muerto (no referenciado en ningún widget JS). | **Requiere decisión** |
| G-08 | Python | `_period_from_str` en `mrp.forecast.line` nunca invocado. | **Requiere decisión** |
| G-09 | Python | `action_view_warning`, `action_view_in_progress_mos`, `action_view_reschedule_needed`, `action_view_done_mos` sin callers. | **Requiere decisión** |
| G-10 | Python | `import calendar`, `import io`, `import base64` dentro de métodos (solo `openpyxl` justifica import tardío). | **Requiere decisión** |
| G-11 | Python | `no_subcontract_domain()` llamado 16 veces por request sin cache. | **Requiere decisión** |
| G-12 | Python | `len(rec.line_ids)` carga registros completos; preferir `.ids`. | **Requiere decisión** |
| G-13 | JS | `pieLabelPlugin` redefinido como nuevo objeto en cada `_drawPie()`. Extraer a constante de módulo. | **Requiere decisión** |
| G-14 | JS | Falta debounce en `onPeriodFromChange`/`onPeriodToChange` en `forecast_widget.js`. | **Requiere decisión** |
| G-15 | JS | `pageSize: 50` hardcodeado en 3 widgets JS independientes. Extraer constante compartida. | **Requiere decisión** |
| G-16 | JS | Umbrales `90`/`70` de carga de CTs hardcodeados en JS; deberían venir del backend. | **Requiere decisión** |
| G-17 | JS | `column_manager.js` registra listeners en `document` en `onResizeStart` sin limpieza si el componente se desmonta durante un resize. | **Requiere decisión** |
| G-18 | XML | `feasibility_summary` declarado dos veces en el mismo form (patrón `invisible` mutuamente exclusivo). Puede generar binding conflicts en OWL. | **Requiere decisión** |
| G-19 | XML | `result_message` declarado dos veces en el wizard de importación. Mismo patrón que G-18. | **Requiere decisión** |
| G-20 | XML | `stock_location_id` en config sin `domain` explícito en el XML del campo (solo en el modelo). | **Requiere decisión** |
| G-21 | Estructura | `__manifest__.py` versión `18.0.43.0.0` — el major `43` sugiere uso como contador de iteraciones, no versión semántica. | **Requiere decisión** |
| G-22 | Estructura | `mrp_reschedule_plan.py` (900+ líneas, 3 clases) y `mrp_production_request.py` (1100+ líneas, 4 clases). Separar en archivos. | **Requiere decisión** |
| G-23 | Estructura | Funciones ABC helper en `mrp_reschedule_config.py` usadas también desde `res_partner.py` y `product_template.py`. Mover a `mrp_abc_helpers.py`. | **Requiere decisión** |
| G-24 | Docs | Métodos públicos del TransientModel dashboard sin docstrings (15+ métodos). | **Requiere decisión** |
| G-25 | Docs | Núcleo del algoritmo de cascada (`_get_delta`, `_schedule_mo_block`, `_get_subsequent_mos`) sin docstrings. | **Requiere decisión** |
| G-26 | Docs | `MAX_DEPTH = 30` sin comentario explicando que previene RecursionError en cascadas profundas. | **Requiere decisión** |
| G-27 | Docs | Comentario UTC en `get_forecast_dashboard_data` no explica el caso de borde del cambio de mes. | **Requiere decisión** |
| G-28 | UX | Columnas `purchase_id` y `picking_id` en vista lista de alertas con `optional='show'` activo; para la mayoría siempre están vacías. | **Requiere decisión** |
| G-29 | UX | Botón "Cancelar plan" con confirm incompleto. | **Verificado — ya mejorado** |
| G-30 | UX | Formulario de alerta sin banner visual cuando `severity='critical'` y no resuelta. | **Requiere decisión** |

---

## Cambios aplicados en esta revisión

| Archivo | Cambio |
|---------|--------|
| `models/mrp_reschedule_plan.py` | Guard de grupo (`group_prod`/`group_admin`/`group_system`) en `action_reset_draft()` y `action_cancel()` |
| `models/mrp_reschedule_alert.py` | `UserError` importado a nivel de módulo; removido import inline en `action_run_cron_manual` |
| `models/mrp_reschedule_alert.py` | Guard de grupo en `action_resolve()` |
| `models/mrp_reschedule_config.py` | Guard de grupo + docstring en `action_auto_assign_sale_categories()` |
| `models/mrp_reschedule_config.py` | Guard de grupo + docstring en `action_compute_supplier_categories()` |
| `models/mrp_reschedule_config.py` | Guard de grupo + docstring en `action_compute_customer_categories()` |
| `models/mrp_planner_dashboard.py` | Eliminado N+1 en `get_wc_tags()`: un único `mapped('tag_ids')` reemplaza `search_count` por loop |
| `models/mrp_planner_dashboard.py` | Eliminado N+1 en `get_product_categories_for_chart()`: `read_group` + búsqueda única reemplaza `search_count` por loop |
| `models/mrp_planner_dashboard.py` | Corregida inconsistencia UTC en `get_product_mos_for_forecast()`: aplica la misma conversión de zona horaria que `get_forecast_dashboard_data()` |
| `views/mrp_reschedule_alert_views.xml` | Agregado group_by `product_id` en vista búsqueda de alertas |
| `views/mrp_reschedule_plan_views.xml` | Agregados group_by `production_id` y `applied_by` en vista búsqueda de planes |
| `wizard/mrp_production_request_views.xml` | `groups="odoo_mrp_planner.group_prod,odoo_mrp_planner.group_admin,base.group_system"` en botones `action_confirm` y `action_plan_all_mos` |
| `views/mrp_forecast_line_views.xml` | Comentario explicativo al filtro "Próximos 3 meses" |
| `views/purchase_order_views.xml` | Comentario indicando que es un placeholder para extensiones futuras |
| `__manifest__.py` | Corregida indentación de la entrada `mo_list_widget.js` |
| `static/src/js/mo_list_widget.js` | Paralelizado `_loadTags()` y `_loadMos()` con `Promise.all` en `onMounted` |
| `static/src/js/wc_load_chart.js` | Paralelizado `_loadTags()` y `_loadChart()` con `Promise.all` en `onMounted` |
| `static/src/js/mo_dashboard_widget.js` | Paralelizado `_loadTags()` y `_loadData()` con `Promise.all` en `onMounted` |
| `static/src/js/sales_chart_widget.js` | Paralelizado `get_product_categories_for_chart` y `_load()` con `Promise.all` en `onMounted` |

---

## Decisiones pendientes para el equipo

### Alta prioridad

**C-01/C-02 — Permisos CSV:** Los modelos de planes, alertas y forecast tienen CRUD completo para `base.group_user`. Propuesta: dividir cada fila en una de lectura para `base.group_user` (1,0,0,0) y otra con CRUD para los grupos del módulo (`group_prod`, `group_sales`, `group_admin`). Verificar que los formularios de usuario estén asignados al grupo correcto antes de aplicar.

**C-04 — Singleton config sin constraint DB:** El `search_count` en `create()` no protege contra concurrencia. Agregar `_sql_constraints = [('singleton', 'CHECK(id = 1)', 'Solo puede existir una configuración.')]` o equivalente.

**I-05 — Multi-empresa forecast:** Agregar record rule estándar de Odoo para `mrp.forecast.line` con `domain_force="[('company_id', 'in', [company_id, False])]"` si la instancia es multi-empresa.

**I-12 — mail.thread en alertas:** Agregar `_inherit = ['mail.thread', 'mail.activity.mixin']` y `<chatter/>` al form. Impacto: tabla de mensajes adicional. Campo `resolved` con `tracking=True` para auditoría automática.

**I-22 — UTC en drill-down JS:** `_periodDateRange()` en `forecast_widget.js` usa hora local. Opciones: (a) exponer bounds UTC desde el backend en el payload de `get_forecast_dashboard_data`, (b) calcular offset en JS con `luxon` (ya disponible en Odoo 18) usando `DateTime.fromISO(...).toUTC()`.

### Media prioridad

**C-07 — N+1 browse en get_sales_chart_data:** Pre-cargar con `search_read(['id','product_tmpl_id'])` y construir dict antes del loop.

**C-08 — N+1 en _build_lines (BFS):** Pre-cargar todas las OCs y OFs hijo con dominios IN antes del bucle BFS para cascadas >10 OFs.

**G-18/G-19 — Campos duplicados en vistas:** Refactorizar `feasibility_summary` y `result_message` a un único `<field>` con clase dinámica via `t-attf-class`.

### Baja prioridad

**G-22 — Archivos monolíticos:** Separar `mrp_reschedule_plan.py` y `mrp_production_request.py` en archivos por clase.

**G-07/G-08/G-09 — Métodos muertos:** Verificar con `grep -r` que no hayan callers en módulos externos antes de eliminar `get_wc_load_data`, `_period_from_str`, `action_view_warning`, `action_view_in_progress_mos`, `action_view_reschedule_needed`, `action_view_done_mos`.

**G-21 — Versión del módulo:** Normalizar `18.0.43.0.0` a `18.0.1.0.0` y documentar política de versioning.

---

## Notas de migración

- Los guards de grupo nuevos en `action_reset_draft()`, `action_cancel()`, `action_resolve()` y los tres métodos de categorías pueden rechazar con `UserError` a usuarios que hoy los usan sin el grupo correcto. Verificar asignaciones de grupo antes de desplegar en producción.

- La corrección UTC en `get_product_mos_for_forecast()` cambia qué OFs aparecen en el acordeón del forecast para usuarios en zonas horarias distintas de UTC. El comportamiento nuevo es el correcto (consistente con la tabla principal).

- Los cambios de `Promise.all` en los cuatro widgets JS reducen la latencia de carga inicial sin cambiar la interfaz ni el comportamiento funcional.
