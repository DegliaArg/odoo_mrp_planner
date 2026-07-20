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

## Revisión v45 — Refactor: separación de archivos y documentación

**Fecha:** 2026-07-03  
**Alcance:** Separación de archivos monolíticos en módulos focalizados; incorporación de docstrings completos en todos los archivos Python y JS del módulo.

---

### Archivos creados (separación de módulos)

| Archivo nuevo | Líneas | Origen | Métodos migrados |
|---------------|--------|--------|-----------------|
| `models/mrp_partner_category.py` | 616 | `mrp_reschedule_config.py` | Funciones ABC helper + `MrpPartnerCategory` (clase separada con métodos de clasificación) |
| `models/mrp_planner_dashboard_wc.py` | 256 | `mrp_planner_dashboard.py` | `get_wc_tags`, `get_wc_chart_data`, `get_wc_load_data` |
| `models/mrp_planner_dashboard_po.py` | 431 | `mrp_planner_dashboard.py` | `get_po_dashboard_data` |
| `models/mrp_planner_dashboard_mo.py` | 477 | `mrp_planner_dashboard.py` | `get_filtered_mos`, `get_alert_stats`, `get_mo_widget_data`, `get_mo_kpi_counts`, `get_request_widget_data`, `get_comparison_data` |
| `models/mrp_planner_dashboard_forecast.py` | 741 | `mrp_planner_dashboard.py` | `get_warehouses_for_forecast`, `get_forecast_dashboard_data`, `get_product_mos_for_forecast`, `get_forecast_export` |
| `models/mrp_planner_dashboard_stock.py` | 295 | `mrp_planner_dashboard.py` | `get_stock_break_data`, `get_product_mos_for_stock_break` |
| `models/mrp_planner_dashboard_sales.py` | 570 | `mrp_planner_dashboard.py` | `get_sales_chart_data`, `get_product_categories_for_chart`, `get_supplier_analysis_data`, `get_supplier_pos_for_analysis` |
| `wizard/mrp_production_request_item.py` | 205 | `mrp_production_request.py` | `MrpProductionRequestItem` clase completa |
| `wizard/mrp_production_request_line.py` | 182 | `mrp_production_request.py` | `MrpProductionRequestLine` + `MrpProductionRequestWc` |

### Archivos reducidos

| Archivo | Líneas antes | Líneas después |
|---------|-------------|---------------|
| `models/mrp_planner_dashboard.py` | ~2681 | ~744 |
| `models/mrp_reschedule_config.py` | ~900+ | reducido (ABC movido) |
| `wizard/mrp_production_request.py` | ~1100+ | reducido (clases movidas) |

### Documentación incorporada

Todos los archivos Python y JS del módulo recibieron docstrings siguiendo el formato:
- **Módulo**: encabezado con responsabilidades y relaciones.
- **Clase**: descripción del modelo y su rol.
- **Método**: fórmula/lógica, campos que modifica, dependencias.

Archivos documentados (38 de 41 — 3 fallaron por rate limit y se retomaron manualmente):
- `models/`: todos los archivos Python incluyendo los 7 nuevos de dashboard
- `wizard/`: `mrp_production_request.py`, `mrp_production_request_item.py`, `mrp_production_request_line.py`, `mrp_forecast_import_wizard.py`
- `static/src/js/`: todos los widgets OWL

### Fix adicional — orden en `models/__init__.py`

`mrp_partner_category` (usa `_inherit = 'mrp.reschedule.config'`) movido después de `mrp_reschedule_config` para garantizar que el modelo base esté registrado antes de la extensión.

---

## Notas de migración

- Los guards de grupo nuevos en `action_reset_draft()`, `action_cancel()`, `action_resolve()` y los tres métodos de categorías pueden rechazar con `UserError` a usuarios que hoy los usan sin el grupo correcto. Verificar asignaciones de grupo antes de desplegar en producción.

- La corrección UTC en `get_product_mos_for_forecast()` cambia qué OFs aparecen en el acordeón del forecast para usuarios en zonas horarias distintas de UTC. El comportamiento nuevo es el correcto (consistente con la tabla principal).

- Los cambios de `Promise.all` en los cuatro widgets JS reducen la latencia de carga inicial sin cambiar la interfaz ni el comportamiento funcional.

---

## Revisión v45.0.0

**Fecha:** 2026-07-03
**Alcance:** Revisión incremental v45.0.0 — optimización de queries N+1, seguridad de permisos CSV, correctness de campos computed, calidad de modelos y widgets OWL/JS

---

### Issues Críticos

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| C-01 | `models/mrp_planner_dashboard.py` | 2038 | `product.product.search()` sin `limit=` carga todos los productos vendibles (3.000–10.000) a memoria; `rows[]` construido en O(N) antes de paginar. Cuello de botella dominante del widget. | **Corregido** |
| C-02 | `models/mrp_planner_dashboard.py` | 2070 | Loop O(N) sobre todos los productos para construir `rows[]`; `display_name` se carga para la página completa en lugar de solo los registros de la página activa. | **Corregido** |
| C-03 | `models/mrp_planner_dashboard.py` | 1484 | Accesos relacionales en cadena `line.product_id.display_name` y `line.product_id.product_tmpl_id.id` dentro del loop `fc_lines` sin precarga: N+1 implícito en `mrp.forecast.line`. | **Corregido** |
| C-04 | `models/mrp_planner_dashboard.py` | 1552 | Acceso a `line.order_id.date_order` dentro del loop `sale.order.line` sin prefetch: N+1 en `sale.order`. | **Corregido** |
| C-05 | `models/mrp_planner_dashboard.py` | 2344 | `pos.filtered(_all_svc)` itera cada OC accediendo a `p.order_line` y `l.product_id.type` sin prefetch; filtro `goods/services` aplicado en Python tras traer todas las OCs del período. | **Corregido** |
| C-06 | `models/mrp_planner_dashboard.py` | 626 | `mrp.workorder.search()` dentro del loop `for wc in workcenters`: una query SQL independiente por cada centro de trabajo (hasta 20 queries para N=20 WCs). | **Corregido** |
| C-07 | `security/ir_rules.xml` | — | `mrp.forecast.line` tiene `company_id` y constraint SQL correcto, pero no existe ninguna `ir.rule` que restrinja la visibilidad por empresa. En instalación multi-empresa cualquier usuario ve forecasts de todas las empresas. | **Corregido** |
| C-08 | `models/res_partner.py` | 22 | `@api.depends()` vacío en `_compute_mrp_cat_flags`: el compute solo corre al crear el registro; cambios posteriores en `mrp.reschedule.config` no invalidan el cache, generando inconsistencias en visibilidad de campos. | **Corregido** |
| C-09 | `models/product_template.py` | 35 | `@api.depends()` vacío en `_compute_mrp_sale_cat_flag`: mismo problema que C-08 para `mrp_enable_sale_cat`. | **Corregido** |
| C-10 | `security/ir.model.access.csv` | — | `mrp.reschedule.plan`: `base.group_user` tenía `perm_unlink=1`; cualquier usuario interno podía borrar planes calculados/aplicados sin pasar por `action_cancel`. | **Corregido** |
| C-11 | `security/ir.model.access.csv` | — | `mrp.reschedule.alert`: `base.group_user` tenía CRUD completo; cualquier usuario podía crear alertas falsas o borrar alertas críticas sin pasar por `action_resolve`. | **Corregido** |

---

### Issues Importantes

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| I-01 | `models/mrp_planner_dashboard.py` | 1531 | `stock.move.line.search()` + suma Python agrupando por `product_id` y mes: tabla puede tener millones de registros. Reemplazable por `.search().read()` con campos limitados. | **Corregido** |
| I-02 | `models/mrp_planner_dashboard.py` | 1577 | `stock.quant.search()` + suma Python por `product_id`: exactamente la semántica de `read_group(..., ['quantity:sum'], ['product_id'])`. | **Corregido** |
| I-03 | `models/mrp_planner_dashboard.py` | 1588 | Acceso a `t.categ_id.display_name` dentro del loop `product.template` sin precarga: N+1 en categorías (hasta una query por categoría distinta; `display_name` toca la cadena `parent_id`). | **Corregido** |
| I-04 | `models/mrp_planner_dashboard.py` | 2049 | `stock.warehouse.orderpoint.search()` sin `limit=`: hasta 5.000 IDs en cláusula `IN`, genera query lenta en PostgreSQL con listas >1.000. | **Corregido** |
| I-05 | `models/mrp_planner_dashboard.py` | 2143 | `t.x_product_type_ids.mapped('name')` dentro de dict comprehension sin prefetch previo de la M2M: hasta 20 queries adicionales (una por template de la página). | **Corregido** |
| I-06 | `models/mrp_planner_dashboard.py` | 2342 | `po_type` filter se aplica en Python después de traer todas las OCs del período: se cargan y descartan registros innecesarios. Fix traslada la clasificación goods/services a SQL con `read_group`. | **Corregido** |
| I-07 | `models/mrp_planner_dashboard.py` | 2510 | Segunda búsqueda de `mrp.reschedule.config` duplicada (ya cargada como `cfg_sa` en L2330): query completamente redundante sobre la misma tabla, mismo dominio, misma compañía. | **Corregido** |
| I-08 | `models/mrp_planner_dashboard.py` | 585 | `_avail_hours()` recalcula `get_work_hours_count` para cada WC aunque compartan el mismo calendario: si 10 WCs usan el mismo turno, el cómputo de intervalos se ejecuta 10 veces con argumentos idénticos. | **Corregido** |
| I-09 | `models/mrp_planner_dashboard.py` | 783 | `_trace_mo` usa recursión con guard `depth > 10` frágil (permite 11 niveles): puede generar stack overflow en cadenas largas. Reemplazado por versión iterativa con `collections.deque` y `MAX_DEPTH=20`. Adaptar call site en `_delivery_info`. | **Corregido** |
| I-10 | `models/mrp_forecast_line.py` | 38 | `period_display` sin `help=`; `company_id` sin `index=True`; `uom_id` related sin `store=False` explícito. | **Corregido** |
| I-11 | `models/mrp_forecast_line.py` | 28 | `forecast_qty` sin `help=`, sin `default=0.0` y sin restricción de valor positivo (un forecast negativo no está bloqueado). | **Corregido** |
| I-12 | `models/mrp_product_type.py` | 10 | `_sql_constraints` con `UNIQUE(name)` global: en multi-empresa dos empresas no pueden tener un tipo de producto con el mismo nombre. | **Corregido** |
| I-13 | `models/res_users.py` | 7 | `mrp_planner_all_warehouses` y `mrp_planner_warehouse_ids` sin record rule ni override `_search`: el filtrado por depósito depende de que cada método lo aplique manualmente; riesgo de fuga de datos por omisión. | **Requiere decisión** |
| I-14 | `models/res_partner.py` | 8 | `x_supplier_category` y `x_customer_category` sin `index=True`: búsquedas ABC en `res.partner` (decenas de miles de registros) hacen full-table-scan. | **Corregido** |
| I-15 | `models/mrp_planner_dashboard.py` | 2385 | Dict comprehension `po_map` accede a `po.partner_id.id` sin prefetch explícito garantizado (puede haber lazy-load residual si `pos` fue fragmentado por `filtered()`). | **Corregido** |
| I-16 | `models/mrp_planner_dashboard.py` | 2426 | Loop sobre `pickings` accede a `picking.purchase_id.id` sin prefetch explícito. | **Corregido** |
| I-17 | `security/ir.model.access.csv` | — | `mrp.reschedule.plan.line` y `mrp.reschedule.plan.wc.line`: `base.group_user` tenía CRUD completo; líneas de plan solo deben ser creadas/borradas por el servidor. | **Corregido** |
| I-18 | `security/ir.model.access.csv` | — | `mrp.product.workcenter`: tabla de configuración WC-producto editable por cualquier usuario operativo; debería ser solo lectura para `base.group_user`. | **Corregido** |
| I-19 | `security/ir.model.access.csv` | — | `mrp.product.type`: catálogo maestro de etiquetas editable por cualquier usuario; debería restringirse a `group_admin`. | **Corregido** |
| I-20 | `security/ir.model.access.csv` | — | `mrp.forecast.line`: CRUD para `base.group_user` desacopla el control ORM del control Python (`can_edit_forecast`); un operario de producción puede modificar forecasts. | **Corregido** |

---

### Mejoras

| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| M-01 | `models/mrp_planner_dashboard.py` | 1504 | Loop `for mo in mos` carga el ORM completo de `mrp.production` (decenas de campos); usar `.read(['product_id','date_finished','product_qty'])` reduce huella de memoria. | **Corregido** |
| M-02 | `models/mrp_planner_dashboard.py` | 2062 | Domain de `stock.quant` usa `child_of` sin filtrar `location_id.usage='internal'`; sub-ubicaciones virtuales/tránsito pueden contaminar totales de stock. | **Corregido** |
| M-03 | `models/mrp_planner_dashboard.py` | 2129 | `no_subcontract_domain()` ejecuta una query SQL extra por invocación; debe calcularse una vez al inicio del método. | **Corregido** |
| M-04 | `models/mrp_planner_dashboard.py` | 637 | `wos` iterado dos veces en generator expressions separadas para calcular `ejecutado` y `pendiente`; una sola pasada con acumuladores es suficiente. | **Corregido** |
| M-05 | `models/mrp_forecast_line.py` | 63 | `from datetime import date` dentro del cuerpo de `_period_from_str` en lugar del top del archivo: no idiomático, overhead de import lookup en cada llamada. | **Corregido** |
| M-06 | `models/product_template.py` | 15 | `x_sale_category` sin `index=True`; `SALE_CAT_SELECTION` importada desde `product_template.py` en lugar de un archivo compartido: dependencia frágil entre módulos. | **Corregido** |
| M-07 | `static/src/js/forecast_widget.js` | 37 | `ForecastWidget` sin `static props`: OWL lanza advertencia en modo estricto y descarta props desconocidos. | **Corregido** |
| M-08 | `static/src/js/forecast_widget.js` | 90 | `onPeriodFromChange` y `onPeriodToChange` llaman `_load()` sincrónicamente en cada evento `input`: cada keystroke válido dispara un RPC. Falta debounce de 400 ms. | **Corregido** |
| M-09 | `static/src/js/column_manager.js` | 68 | Listeners `mousemove`/`mouseup` sobre `document` no se limpian si el componente se desmonta durante un drag-resize: memory/event leak acumulativo por sesión. | **Corregido** |
| M-10 | `static/src/js/supplier_analysis_widget.js` | 57 | `SupplierAnalysisWidget` sin `onWillUnmount` que cancele el resize activo de `useColManager`. Consumer-side del leak en M-09. | **Corregido** |
| M-11 | `static/src/js/supplier_analysis_widget.js` | 86 | `onPeriodFromChange` y `onPeriodToChange` en `SupplierAnalysisWidget` sin debounce: mismo patrón que M-08 sobre un RPC más pesado (`get_supplier_analysis_data`). | **Corregido** |
| M-12 | `security/ir.model.access.csv` | — | `mrp.planner.dashboard` y `mrp.planner.detail.dashboard` son TransientModels con CRUD a `group_user`: técnicamente válido (Odoo gestiona el ciclo de vida de transient), pero debería documentarse. | **Requiere decisión** |
| M-13 | `security/ir.model.access.csv` | — | `mrp.production.request` y líneas asociadas: CRUD completo para `group_user` —  `perm_unlink` restringido a `group_admin`. El flujo del wizard permite que cualquier usuario cree borradores (intencional); solo admins pueden borrar registros. | **Corregido** |
| M-14 | `wizard/mrp_forecast_import_wizard.py` | 57 | `action_import()` sin verificación de grupo Python; acceso directo por API bypasseaba el control UI. Guard agregado: requiere `group_sales` o `group_admin`. | **Corregido** |

---

### Cambios aplicados en esta revisión

| Archivo | Cambio |
|---------|--------|
| `models/mrp_planner_dashboard.py` | `_trace_mo` recursivo reemplazado por `_trace_mo_iter` iterativo con `collections.deque` y `MAX_DEPTH=20`; call site en `_delivery_info` adaptado |
| `models/mrp_planner_dashboard.py` | `fc_lines` loop: precarga de `product_id.display_name` y `product_tmpl_id` con `read()` en batch antes del loop (fix F1) |
| `models/mrp_planner_dashboard.py` | `sale.order.line` loop: reemplazado por `search().read()` + precarga de `date_order` en batch (fix F2) |
| `models/mrp_planner_dashboard.py` | `stock.move.line` loop: reemplazado por `.search().read(['product_id','date','quantity'])` (fix F3) |
| `models/mrp_planner_dashboard.py` | `stock.quant` loop: reemplazado por `read_group(..., ['quantity:sum'], ['product_id'])` (fix F4) |
| `models/mrp_planner_dashboard.py` | `product.template` loop: `browse()` reemplazado por `read()` + precarga de categorías y tipos en selects independientes (fix F5) |
| `models/mrp_planner_dashboard.py` | Loop `for mo in mos`: reemplazado por `mos.read(['product_id','date_finished','product_qty'])` (fix F6) |
| `models/mrp_planner_dashboard.py` | Clasificación `goods/services` trasladada a SQL con `purchase.order.line.read_group()` antes del `search()` (fix SA-001/SA-002 combinados) |
| `models/mrp_planner_dashboard.py` | Eliminada segunda búsqueda duplicada de `mrp.reschedule.config`; `cfg_sa` renombrado a `cfg` (fix SA-003) |
| `models/mrp_planner_dashboard.py` | `pos.mapped('partner_id')` agregado antes del dict comprehension `po_map` (fix SA-004) |
| `models/mrp_planner_dashboard.py` | `pickings.mapped('purchase_id')` agregado antes del loop de pickings (fix SA-005) |
| `models/mrp_planner_dashboard.py` | `product.product.search()` cambiado a `.search().ids`; loop O(N) sobre products refactorizado a loop sobre IDs; `display_name` cargado solo para la página (fix SB-01/SB-02) |
| `models/mrp_planner_dashboard.py` | `stock.warehouse.orderpoint.search()` reemplazado por `read_group` con `product_min_qty:max` y `qty_forecast:max` (fix SB-03) |
| `models/mrp_planner_dashboard.py` | `page_tmpls.mapped('x_product_type_ids')` agregado para forzar prefetch M2M antes del dict comprehension `tmpl_type_map` (fix SB-04) |
| `models/mrp_planner_dashboard.py` | `('location_id.usage', '=', 'internal')` agregado al domain de `stock.quant.read_group` (fix SB-05) |
| `models/mrp_planner_dashboard.py` | `no_sc_domain = no_subcontract_domain(self.env)` calculado una vez al inicio del método (fix SB-06) |
| `models/mrp_planner_dashboard.py` | `mrp.workorder.search()` sacado del loop de WCs; batch único agrupado por WC con `defaultdict` (fix N1-workorder-search-in-loop) |
| `models/mrp_planner_dashboard.py` | `_avail_hours()` memoiza resultado de `get_work_hours_count` en `_cal_hours_cache` por `(calendar_id, dt_start, dt_end)` (fix repeated-get_work_hours_count) |
| `models/mrp_planner_dashboard.py` | Dos generator expressions sobre `wos` reemplazadas por una sola pasada con acumuladores `ejecutado`/`pendiente` (fix wos-iterated-twice) |
| `models/mrp_forecast_line.py` | `help=` en `period_display`; `index=True` en `company_id`; `store=False` explícito en `uom_id` (fix F02) |
| `models/mrp_forecast_line.py` | `default=0.0` y `help=` en `forecast_qty` (fix F03) |
| `models/mrp_forecast_line.py` | `from datetime import date` movido al top del archivo; eliminado import inline en `_period_from_str` (fix F10) |
| `models/res_partner.py` | `@api.depends()` reemplazado por `@api.depends_context('company')` en `_compute_mrp_cat_flags` (fix F04) |
| `models/res_partner.py` | `index=True` en `x_supplier_category` y `x_customer_category` (fix F08) |
| `models/product_template.py` | `@api.depends()` reemplazado por `@api.depends_context('company')` en `_compute_mrp_sale_cat_flag` (fix F05) |
| `models/product_template.py` | Import de `SALE_CAT_SELECTION` actualizado para usar `models/const.py` (fix F09) |
| `models/const.py` | Creado archivo nuevo con `SALE_CAT_SELECTION` como constante compartida (fix F09) |
| `models/res_partner.py` | Import de `SALE_CAT_SELECTION` actualizado para usar `models/const.py` (fix F09) |
| `models/mrp_product_type.py` | Constraint `name_unique` reemplazado por `name_company_unique` `UNIQUE(name, company_id)`; `help=` en `color`; campo `company_id` agregado con `index=True` (fix F06) |
| `static/src/js/forecast_widget.js` | `static props` agregado a `ForecastWidget` (fix F1) |
| `static/src/js/forecast_widget.js` | Debounce de 400 ms en `_loadDebounced`; `clearTimeout` en `onWillUnmount`; period handlers actualizados a `_loadDebounced()` (fix F4/F4b) |
| `static/src/js/column_manager.js` | `_resizeCleanup` tracker agregado en `onResizeStart`; función `cancelResize()` expuesta en el objeto retornado (fix F2/F3c) |
| `static/src/js/supplier_analysis_widget.js` | `onWillUnmount` importado y agregado con `cancelResize()` y `clearTimeout` del timer de debounce (fix F3/F3b/F5c) |
| `static/src/js/supplier_analysis_widget.js` | Debounce de 400 ms en `_loadDebounced`; period handlers actualizados a `_loadDebounced()` (fix F5/F5b) |
| `security/ir.model.access.csv` | `mrp.reschedule.plan`: `group_user` a `1,1,1,0`; filas `group_prod` y `group_admin` con unlink (fix SEC-01) |
| `security/ir.model.access.csv` | `mrp.reschedule.plan.line`: `group_user` a `1,1,0,0`; `mrp.reschedule.plan.wc.line`: `group_user` a `1,0,0,0`; filas `group_prod` con CRUD (fix SEC-02) |
| `security/ir.model.access.csv` | `mrp.reschedule.alert`: `group_user` a `1,1,0,0`; fila `group_admin` con CRUD (fix SEC-03) |
| `security/ir.model.access.csv` | `mrp.product.workcenter`: `group_user` a `1,0,0,0`; filas `group_prod` y `group_admin` con CRUD (fix SEC-06) |
| `security/ir.model.access.csv` | `mrp.product.type`: `group_user` a `1,0,0,0`; fila `group_admin` con CRUD (fix SEC-07) |
| `security/ir.model.access.csv` | `mrp.forecast.line`: `group_user` a `1,0,0,0`; filas `group_sales` y `group_admin` con CRUD (fix SEC-08) |
| `security/ir_rules.xml` | Creado: `rule_forecast_line_company` restringe `mrp.forecast.line` a `company_ids` para `base.group_user` (fix C-07) |
| `__manifest__.py` | Agregado `security/ir_rules.xml` al listado `data` después de `groups.xml` (fix C-07) |
| `security/ir.model.access.csv` | `mrp.production.request` y 3 modelos relacionados (item, line, wc): `group_user` pasa a `unlink=0`; nuevas filas `group_admin` con CRUD completo (fix M-13) |
| `wizard/mrp_forecast_import_wizard.py` | Guard de grupo en `action_import()`: requiere `group_sales` o `group_admin`; lanza `UserError` si no cumple (fix M-14) |

---

### Decisiones pendientes para el equipo

**Alta prioridad**

**I-13 — Enforcement de depósitos por usuario (`res.users`):** Los campos `mrp_planner_all_warehouses` y `mrp_planner_warehouse_ids` existen pero no hay record rule ni override de `_search` que los aplique automáticamente. Cada método RPC del dashboard debe filtrar manualmente; cualquier omisión expone datos de otros depósitos. Decidir: (a) agregar record rules por modelo, o (b) documentar explícitamente que el filtrado es responsabilidad del desarrollador en cada punto de acceso.

**I-09 — `_trace_mo_iter` call site adaptado (TRACE_MO_RECURSION):** La versión iterativa devuelve una lista de moves visitados en lugar del primer recordset encontrado. El call site en `_delivery_info` fue adaptado, pero se debe revisar que la lógica de extracción de la OF (`raw_material_production_id` o `production_id`) sea correcta para todos los casos de subcontratación.

**Media prioridad**

**M-12 — TransientModels con CRUD a `group_user` (`mrp.planner.dashboard`, `mrp.planner.detail.dashboard`):** Aceptable por diseño de Odoo para TransientModels. Documentar en comentario del CSV que el CRUD es gestionado por Odoo y no expone acciones UI.

**Baja prioridad**

**F07 — `mrp.reschedule.user.permission`:** Modelo de permisos por usuario sin enforcement automático (mismo patrón que I-13). Revisar si tiene record rules o si la lógica de filtrado está dispersa en los métodos RPC.

---

## Revisión de cierre v46 — auditoría final + split de archivos

**Fecha:** 2026-07-07
**Alcance:** Resolución de ítems pendientes de la auditoría anterior, split de archivos monolíticos, extracción de helpers JS, creación de ARQUITECTURA.md.

---

### Issues resueltos en esta ronda

| # | Área | Descripción | Commit |
|---|------|-------------|--------|
| R-01 | Python | Constraint SQL singleton en `mrp.reschedule.config`: `UNIQUE(singleton_check)` + campo `singleton_check = fields.Boolean(default=True)` — protege contra concurrencia en `create()` | `51762ad` |
| R-02 | Python | Comentarios de justificación en todos los `sudo()` de los TransientModels de dashboard (lectura cross-empresa de stock/ventas/compras sin acceso directo del usuario) | `51762ad` |
| R-03 | JS | Fix UTC en `_periodDateRange()` de `forecast_widget.js`: construía strings de datetime en hora local; el ORM Odoo los interpreta como UTC, causando corrimiento de mes para usuarios UTC-3. Corregido con conversión explícita a UTC | `51762ad` |
| R-04 | Python | Constante `DEFAULT_PO_CRITICAL_DAYS = 5` extraída a `models/const.py`; reemplaza magic number en 5 archivos | `51762ad` |
| R-05 | Python | `_parse_date` deduplicada: era función anidada repetida en dos métodos de `mrp_planner_dashboard_sales.py`; extraída a nivel de módulo | `51762ad` |
| R-06 | Python | Eliminados 6 métodos muertos: `get_wc_load_data`, `_period_from_str`, `action_view_warning`, `action_view_in_progress_mos`, `action_view_reschedule_needed`, `action_view_done_mos` — confirmado con grep que no tenían callers | `51762ad` |
| R-07 | XML | `purchase_order_views.xml` eliminado del manifest (archivo vacío) | `51762ad` |
| R-08 | XML | Columnas `purchase_id` y `picking_id` en lista de alertas pasadas a `optional="hide"` (estaban en `optional="show"`; para la mayoría de alertas siempre están vacías) | `51762ad` |
| R-09 | Estructura | `mrp_reschedule_plan.py` (1246 líneas, 3 clases) dividido en 4 archivos: `mrp_reschedule_cascade_mixin.py` (590 líneas), `mrp_reschedule_plan.py` reducido (409 líneas), `mrp_reschedule_plan_line.py` (210 líneas), `mrp_reschedule_plan_wc_line.py` (92 líneas) | `87f983e` |
| R-10 | Estructura | `mrp_production_request.py` (1147 líneas, 4 clases) dividido en 3 archivos: `mrp_demand_expansion_mixin.py` (343 líneas), `mrp_demand_scheduling_mixin.py` (358 líneas), `mrp_production_request.py` reducido (509 líneas) | `813abd5` |
| R-11 | JS | `forecast_widget.js` (1388 líneas): funciones de formato puras extraídas a `forecast_formatters.js`; funciones de gráficos a `customer_analysis_charts.js` | `84107cc`, `8213802` |
| R-12 | Docs | `ARQUITECTURA.md` creado: mapa de carpetas, tablas de modelos por área, 3 flujos principales con rutas de archivos, diagrama ASCII de dependencias | `5f13b5e` |

---

### Decisiones pendientes (aún abiertas)

| # | Área | Descripción |
|---|------|-------------|
| D-02 | Performance | **N+1 en `get_sales_chart_data`** (`mrp_planner_dashboard_sales.py`): `browse(g['product_id'][0])` individual dentro del loop de `read_group` — un `browse` por fila de resultado. Pre-cargar con `browse(list_of_ids)` antes del loop. |
| D-03 | Performance | **N+1 en `_build_lines` (BFS de cascada)** (`mrp_reschedule_cascade_mixin.py`): `_get_pos_for_mo(mo)` y `_get_child_mos(mo)` emiten búsquedas individuales por OF dentro del BFS. Con cascadas de N órdenes genera hasta 4N queries. Pre-cargar en batch antes del bucle. |
| D-04 | UX | **Banner crítico en formulario de alerta** (`mrp_reschedule_alert_views.xml`): el form muestra colores de fila en lista pero no tiene banner `alert-danger` cuando `severity='critical'` y `resolved=False`. Hay `decoration-danger` en listas pero no panel de advertencia en el form. |
| D-05 | XML | **`feasibility_summary` declarado dos veces** en el mismo form de solicitud de programación (`mrp_production_request_views.xml`, líneas 111 y 116). Patrón `invisible` mutuamente exclusivo; puede generar binding conflicts en OWL. Refactorizar a un único `<field>` con clase dinámica. |
| D-06 | XML | **`result_message` declarado dos veces** en el wizard de importación de forecast (líneas 33–39): dos `<div>` con `invisible` excluyentes (uno para éxito, otro para error). Mismo patrón que D-05. |

---

## Revisión v47 — Filtrado por depósito y visibilidad de secciones

**Fecha:** 2026-07-14
**Alcance:** Fix bug `_wh_domain_alert` (rama `purchase_id` faltante), filtrado warehouse completo en todos los RPCs, feature de secciones visibles por usuario.

---

### Issues resueltos en esta ronda

| # | Área | Descripción | Commits |
|---|------|-------------|---------|
| R-01 | Seguridad/Datos | **D-01 cerrado** — Implementada opción (b): helpers `_wh_domain_mo`, `_wh_domain_po`, `_wh_domain_alert` en `mrp.planner.dashboard` (TransientModel base); aplicados en los 7 archivos de dashboard. Cada RPC filtra por `allowed_ids = _get_allowed_wh_ids()` antes de cualquier búsqueda. El filtrado es responsabilidad explícita del desarrollador en cada punto de acceso — no hay `ir.rule`, por diseño. | `30b6fc1` |
| R-02 | Bug | **`_wh_domain_alert` rama `purchase_id` faltante** — Alertas `po_delayed`/`po_upcoming`/`po_cancelled` tienen `production_id=False` y `picking_id=False`; el dominio original las hacía caer en la rama "ninguno → siempre incluir", mostrando alertas de todos los depósitos sin filtrar (manifestado: 911 OCs vencidas en header vs 2 en widget). Fix: dominio de 4 ramas con `production_id`, `purchase_id`, `picking_id`, y vacío. | `30b6fc1` |
| R-03 | Bug | **`get_stock_break_data` — `allowed_ids` fuera de scope** — `allowed_ids` se calculaba dentro del branch `else` de resolución de ubicaciones, quedando fuera de alcance para orderpoints y `mo_groups`. Izando el cómputo al tope del método. | `30b6fc1` |
| R-04 | Feature | **Visibilidad de secciones por usuario** — 10 campos `mrp_planner_show_*` en `res.users` (default `True`); campos computed `show_*_sec` en TransientModel; `invisible` combinado `"not can_see_* or not show_*_sec"` en los 4 paneles; vista unificada `view_users_mrp_warehouse_list` con toggle columns para depósitos y secciones; botón único en configuración. | `30b6fc1`, `32990d0` |

---

## Revisión v48 — Auditoría de configuraciones y completitud de docs.md

**Fecha:** 2026-07-14
**Alcance:** Relevamiento exhaustivo de todos los campos `Selection` que cambian metodología de cálculo; adición de 9 gaps identificados a `docs.md`.

---

### Issues resueltos en esta ronda

| # | Área | Descripción |
|---|------|-------------|
| D-01 docs | Documentación | **Tabla de configuraciones** — agregada sección "Guía rápida: configuraciones que cambian metodología" al inicio de `docs.md` con 14 subtablas (una por campo `Selection` relevado). |
| D-02 docs | Documentación | **Rotación COGS/ventas** — solo existía la variante "por unidades"; agregadas variantes `cogs` y `sales` en el widget de Forecast y en el widget de Quiebres de stock. |
| D-03 docs | Documentación | **Rotación en quiebres de stock** — sección nueva con las 3 fórmulas (units/cogs/sales) y variable `D = rotation_months_cfg × 30`. |
| D-04 docs | Documentación | **Cobertura de inventario — fuente de demanda** — sección nueva "Cobertura de inventario (columna por producto)" con las 3 variantes de `forecast_coverage_demand_source`. |
| D-05 docs | Documentación | **% Cobertura OFs — denominador so_demand** — columna "% Cobertura" actualizada con la tabla de `forecast_mo_coverage_denominator`. |
| D-06 docs | Documentación | **Precisión de forecast — fuente delivery** — reemplazado blockquote "todas usan demanda OV" por sección "fuente del «real»" con variantes `demand`/`delivery`. |
| D-07 docs | Documentación | **Rotación de venta — denominador demand** — tabla de `sale_cat_rotation_source` añadida en el Modo Rotación de categorías de venta. |
| D-08 docs | Documentación | **Variación de precio — referencia pricelist** — columna actualizada con tabla de variantes `standard`/`pricelist` y nota sobre líneas sin `product.supplierinfo`. |
| D-09 docs | Documentación | **Análisis de clientes — sección completa nueva** — el panel no tenía ninguna fórmula documentada. Agregadas: % entrega, % a tiempo (3 variantes de `customer_analysis_ontime_method`), intervalos entre pedidos, ticket promedio, tendencia de ventas, ABC del período, segmento de frecuencia. |
| D-10 docs | Documentación | **Criterio de prioridad al reprogramar** — sección nueva en "Reprogramación en cascada" documentando `chronological`/`shortest_first`/`manual`. |

---

## Revisión v49 — Agrupamiento de quiebres, filtros de almacén, nombres hoja y criterio OFs por período

**Fecha:** 2026-07-14
**Alcance:** Cuatro cambios de código documentados: nuevo criterio de OFs por período (`comparison_date_mode`), agrupamiento por tabs en quiebres de stock, filtros de almacén en 4 endpoints, y cambio de `complete_name`/`display_name` a `name` en categorías y ubicaciones.

---

### Cambios aplicados en esta ronda

| # | Área | Archivos afectados | Descripción |
|---|------|--------------------|-------------|
| C-01 | Feature | `models/mrp_reschedule_config.py`, `models/mrp_planner_dashboard_mo.py`, `models/mrp_planner_dashboard_forecast.py` | **Nuevo campo `comparison_date_mode`** en `mrp.reschedule.config` con 3 opciones: `finish_date` (por fecha de cierre), `overlap` (solapamiento completo), `proportional` (proporcional por duración). Aplica en `get_comparison_data` y `get_forecast_dashboard_data`. Default `finish_date` para no romper comportamiento existente. |
| C-02 | UI | `static/src/js/stock_break_widget.js`, `static/src/xml/stock_break_widget.xml` | **Agrupamiento por nav-tabs en quiebres de stock** — reescrito para usar nav-tabs encima de la tabla (igual que el widget de Forecast), en lugar de filas de encabezado de grupo dentro del `tbody`. Criterios disponibles: Categoría y Cat. venta (si habilitada). |
| C-03 | Seguridad/Datos | `models/mrp_planner_dashboard_forecast.py`, `models/mrp_planner_dashboard_sales.py`, `models/mrp_planner_dashboard_wc.py`, `models/mrp_planner_dashboard_customer.py` | **Filtros de almacén faltantes** — aplicado `_get_allowed_wh_ids()` en 4 endpoints que no lo tenían: `get_forecast_dashboard_data` (filtro `picking_type_id.warehouse_id` en OFs), `get_sales_chart_data` (sale.order y stock.move.line), `get_wc_chart_data` (mrp.workorder), `get_customer_analysis_data` / `get_customer_detail` (validación server-side de warehouse_ids). |
| C-04 | UI | `models/mrp_planner_dashboard_forecast.py`, `models/mrp_planner_dashboard_sales.py`, `models/mrp_planner_dashboard.py`, `models/mrp_planner_dashboard_stock.py` | **`name` en lugar de `complete_name`/`display_name`** — columna Familia y tabs del forecast, dropdown de familias en ventas, dropdown de ubicaciones en quiebres, y título del panel de quiebres ahora muestran solo el nodo hoja de la jerarquía. |

---

## Revisión v50 — Seguridad, performance, split de archivos grandes

**Fecha:** 2026-07-17
**Alcance:** Auditoría completa de producción: comentarios de sudo(), corrección de N+1, cierre de D-02/D-04/D-05, división de los 3 archivos más grandes.

---

### Issues cerrados en esta ronda

| # | Área | Descripción |
|---|------|-------------|
| D-02 ✓ | Performance | **N+1 en `get_sales_chart_data`** — `browse(g['product_id'][0])` individual reemplazado por batch `browse(list_of_ids).read(['id','product_tmpl_id'])` + dict lookup, en dos lugares: loop de `sale.order.line` y loop de `stock.move.line`. |
| D-04 ✓ | UX | **Banner de alerta crítica** — añadido `<div class="alert alert-danger">` en el form de `mrp.reschedule.alert` (`mrp_reschedule_alert_views.xml`), visible cuando `severity == 'critical' and not resolved`. |
| D-05 ✓ | XML | **`feasibility_summary` binding conflict OWL** — `mrp_production_request_views.xml`: el segundo `<field name="feasibility_summary">` reemplazado por `<span t-esc="record.feasibility_summary.value"/>`. Un único binding OWL, sin colisión. |

### Seguridad — comentarios sudo()

Añadidos comentarios `# sudo():` explicando la justificación en todos los usos de `sudo()` que los requerían:

| Archivo | Contexto |
|---------|----------|
| `models/mrp_partner_category.py` | `sale.order.line`, `product.product`, `product.supplierinfo` — no accesibles para usuarios de producción/logística |
| `models/mrp_planner_dashboard_sales.py` | Batch pre-load para N+1 fix (D-02) |
| `models/mrp_planner_dashboard_stock.py` | `stock.move` requiere permisos de inventario |
| `models/mrp_reschedule_config.py` | Búsqueda de singletons, escritura en `ir.groups`, creación de config inicial |
| `models/mrp_reschedule_cascade_mixin.py` | `ir.config_parameter` solo legible con permisos de admin |
| `wizard/mrp_production_request_line.py` | `ir.config_parameter` desde contexto de wizard sin permisos de admin |
| `wizard/mrp_demand_expansion_mixin.py` | `ir.config_parameter` desde mixin de expansión de demanda |

### Split de archivos grandes

| Archivo original | Líneas antes | Líneas después | Extraído a |
|-----------------|-------------|----------------|-----------|
| `static/src/js/customer_analysis_widget.js` | 1 119 | 881 | `customer_analysis_charts.js` (+229 líneas): `drawPanelCharts(widget)`, `CHART_COLORS`, `monthLabel()` |
| `static/src/js/forecast_widget.js` | 1 625 | 1 347 | `forecast_tooltips.js` (nuevo, 175 líneas): 12 funciones de tooltip/KPI. `forecast_export.js` (nuevo, 65 líneas): `downloadForecastExcel()`. Se eliminó `const MONTHS_ES` duplicada que vivía dentro de `downloadExport()`. |
| `models/mrp_planner_dashboard_forecast.py` | 1 165 | 1 047 | `mrp_planner_dashboard_forecast_export.py` (nuevo): mixin `MrpPlannerDashboardForecastExport` con `get_forecast_export()`. Imports `io` y `base64` movidos al nuevo archivo. |

### Pending (aún abiertos)

| # | Área | Descripción |
|---|------|-------------|
| D-03 | Performance | N+1 en `_build_lines` BFS (`mrp_reschedule_cascade_mixin.py`): requiere decisión arquitectónica antes de intervenir. |
| D-06 | XML | `result_message` declarado dos veces en el wizard de importación de forecast — mismo patrón que D-05, pendiente de resolver. |

---

## Revisión v51 — Segunda pasada de reducción agresiva de archivos

**Fecha:** 2026-07-20
**Alcance:** Reducción de los 2 archivos restantes sobre 1 000 líneas: `forecast_widget.js` (1 347 → 455) y `mrp_planner_dashboard_forecast.py` (1 047 → 711). Fix adicional de ParseError por directiva OWL prohibida en XML de formulario.

---

### Fix urgente — ParseError en `mrp_production_request_views.xml`

Al actualizar el módulo, Odoo lanzaba `ParseError: directiva owl prohibida (t-esc)` en `wizard/mrp_production_request_views.xml:34`. El `<span t-esc="record.feasibility_summary.value"/>` insertado como fix D-05 es un OWL template directive válido en componentes, pero está explícitamente prohibido en la arquitectura XML de formularios de Odoo 18. Revertido al patrón de dos `<field>` con `invisible` excluyentes — que sí es válido — en commit `0ce74d2`.

### Split de archivos

| Archivo original | Líneas antes | Líneas después | Extraído a |
|-----------------|-------------|----------------|-----------|
| `static/src/js/forecast_widget.js` | 1 347 | 455 | `forecast_drilldown.js` (nuevo, 202 líneas): 9 funciones `openDrill*` + 2 helpers privados. `forecast_filters.js` (nuevo, 238 líneas): 5 getters computados + 16 handlers de filtro/sort. `forecast_formatters.js` (+103 líneas): 13 funciones puras nuevas (`accClass`, `fmtRotation`, `rotClass`, `fmtCoverage`, `covClass`, `demandGapClass`, `mosGapClass`, `fmtGapPct`, `fmt`, `fmtPct`, `fmtDate`, `sortIcon`, `colTitle`). |
| `models/mrp_planner_dashboard_forecast.py` | 1 047 | 711 | `mrp_forecast_calc_mixin.py` (nuevo, 413 líneas): `_fc_rotation_data`, `_fc_build_rows`, `_fc_no_fc_stats` + funciones puras `_cov_days`/`_cov_months`. |

### Cambios en manifests

| Archivo | Cambio |
|---------|--------|
| `__manifest__.py` | Agregadas entradas `forecast_drilldown.js` y `forecast_filters.js` en assets antes de `forecast_widget.js` |
| `models/__init__.py` | Agregado `from . import mrp_forecast_calc_mixin` antes de `mrp_planner_dashboard_forecast` |

### Notas técnicas

- **Patrón de delegación JS**: dentro del cuerpo de un método de clase, una llamada sin `this.` (`setSort(this, col)`) resuelve al import de módulo, nunca al método de clase — sin recursión. Esto es lo que permite que `sortedRows(col) { return sortedRows(this); }` funcione con el mismo nombre.
- **Calls internos en forecast_filters.js**: `filteredKpis(widget)` llama `filteredRowsAll(widget)` directamente (no `widget.filteredRowsAll`) para evitar indirección innecesaria.
- **`_to_utc`/`_dt_ym` en Python**: no extraídos al mixin porque cierran sobre `user_tz` del scope exterior de `get_forecast_dashboard_data`. Se extraen solo los bloques que no necesitan ese closure.

### Pending (sin cambios)

| # | Área | Descripción |
|---|------|-------------|
| D-03 | Performance | N+1 en `_build_lines` BFS (`mrp_reschedule_cascade_mixin.py`): requiere decisión arquitectónica antes de intervenir. |
| D-06 | XML | `result_message` declarado dos veces en el wizard de importación de forecast. |

---

## Revisión v52 — Cierre de pendientes técnicos

**Fecha:** 2026-07-20
**Alcance:** Cierre de D-06, G-02, G-16, comentarios `sudo()`, split sales/supplier. I-13 (ir.rule de depósito) bloqueado pendiente de decisión de alcance.

### D-06 — `result_message` duplicado en wizard de importación

Resuelto con campo computado `result_html = fields.Html(compute='_compute_result_html', sanitize=False)` en `wizard/mrp_forecast_import_wizard.py`. El campo incluye el HTML del alert (ícono + mensaje + clase CSS) calculado en Python. La vista XML ahora tiene **una sola declaración** `<field name="result_html" widget="html" .../>` en lugar de los dos `<div>` con `invisible` excluyentes que incluían el campo dos veces.

### G-02 — Consolidación de `_get_config()`

Eliminado el método wrapper `_get_config()` de `mrp_reschedule_alert.py` (era innecesario — solo delegaba a `env['mrp.reschedule.config'].get_config()`). Los 6 call sites en el mismo archivo pasan a llamar `env['mrp.reschedule.config'].get_config()` directamente.

### G-16 — Umbrales 90/70 como constantes nombradas

Añadidas a `models/const.py`:

| Constante | Valor | Descripción |
|-----------|-------|-------------|
| `DEFAULT_ON_TIME_GREEN_PCT` | 90 | Umbral verde entregas a tiempo (proveedor) |
| `DEFAULT_ON_TIME_YELLOW_PCT` | 70 | Umbral amarillo entregas a tiempo |
| `DEFAULT_RISK_DAYS` | 90 | Días sin compra → cliente/proveedor en riesgo |
| `DEFAULT_ROTATION_WARN_DAYS` | 90 | Días sin rotación → alerta quiebre |
| `FORECAST_WARNING_PCT` | 70 | Cobertura forecast: alerta |
| `FORECAST_CRITICAL_PCT` | 50 | Cobertura forecast: crítico |
| `RFM_RECENCY_RECENT_DAYS` | 30 | RFM: recencia alta (< 30 días) |
| `RFM_RECENCY_MEDIUM_DAYS` | 90 | RFM: recencia media (< 90 días) |

Usadas en: `mrp_planner_dashboard_sales.py`, `mrp_planner_dashboard_customer.py`, `mrp_planner_dashboard_stock.py`, `mrp_planner_dashboard_forecast.py`, `mrp_partner_category.py`.

### sudo() — Comentarios de justificación

Añadidos o reubicados comentarios en:
- `mrp_reschedule_alert.py`: `res.company.sudo().search([])` en `_cron_check_delays` — el cron corre en contexto de empresa activa y el multi-company record rule restringe la visibilidad.
- `product_template.py`: comentario movido a la línea anterior al `sudo()` (convención: comment before, not after).
- `res_partner.py`: añadido comentario inline antes de `mrp.reschedule.config.sudo().get_config()`.

### Split de `mrp_planner_dashboard_sales.py`

| Archivo original | Líneas antes | Líneas después | Extraído a |
|-----------------|-------------|----------------|-----------|
| `models/mrp_planner_dashboard_sales.py` | 618 | 227 | `models/mrp_planner_dashboard_supplier.py` (nuevo, ~290 líneas): `MrpPlannerDashboardSupplier` con `get_supplier_analysis_data` y `get_supplier_pos_for_analysis`. Importa `_parse_date` del módulo de ventas. |

### Pending

| # | Área | Descripción |
|---|------|-------------|
| D-03 | Performance | N+1 en `_build_lines` BFS (`mrp_reschedule_cascade_mixin.py`): requiere decisión arquitectónica antes de intervenir. |
| I-13 | Seguridad | Filtrado garantizado por depósito: pendiente de decisión de alcance (¿solo dashboard o global vía ir.rule?). |
