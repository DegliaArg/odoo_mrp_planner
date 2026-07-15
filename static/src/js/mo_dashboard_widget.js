/** @odoo-module **/

/**
 * @description Widget de órdenes de fabricación para el dashboard del planificador.
 *   Muestra KPIs de OFs, solicitudes de programación y comparativo producción vs plan.
 *   Paginado y ordenamiento server-side para OFs y solicitudes; client-side para comparativo.
 * @fires RPC mrp.planner.dashboard.get_mo_widget_data — KPIs + lista de OFs paginada
 *   @returns {{ kpis: {total,in_progress,delayed,reschedule,done,partial}, mos: MoRow[] }}
 * @fires RPC mrp.planner.dashboard.get_request_widget_data — solicitudes de programación
 *   @returns {{ kpis: {active,calculated,reschedule,mos_delayed}, requests: ReqRow[] }}
 * @fires RPC mrp.planner.dashboard.get_comparison_data — comparativo plan vs producido
 *   @returns {{ kpis: {planned,produced,pct,ofs_done}, items: CmpRow[] }}
 * @fires RPC mrp.planner.dashboard.get_wc_tags — lista de sectores/categorías de WC
 * @listens onMounted — carga tags y datos iniciales
 * @listens onPatched — resincroniza altura de paneles
 */

import { Component, useState, onMounted, onPatched, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useColManager } from "./column_manager";

const MO_OF_COLS = [
    { key: 'name',             label: 'Referencia',    width: 130, sortKey: 'name',             title: 'Número de la orden de fabricación.' },
    { key: 'product',          label: 'Producto',      width: 210, sortKey: 'product',           title: 'Producto a fabricar en esta OF.' },
    { key: 'date_finished',    label: 'Fin planificado', width: 130, sortKey: 'date_finished',  title: 'Fecha de finalización planificada (date_finished).' },
    { key: 'state',            label: 'Estado',        width: 105, sortKey: 'state',             title: 'Estado actual de la OF: Confirmada / En progreso / Por cerrar / Completada.' },
    { key: 'pending_delivery', label: 'Entregas',      width: 85,  sortKey: 'pending_delivery',  align: 'end', title: 'Entregas pendientes del producto.' },
];

const MO_SCHED_COLS = [
    { key: 'name',      label: 'Referencia',       width: 200, sortKey: 'name',       title: 'Identificador de la solicitud de programación.' },
    { key: 'start_from',label: 'Disponible desde', width: 155, sortKey: 'start_from', title: 'Fecha más temprana desde la que el material está disponible.' },
    { key: 'state',     label: 'Estado',           width: 100, sortKey: 'state',      title: 'Estado de la solicitud: Borrador / Calculada / Confirmada.' },
];

const MO_COMP_COLS = [
    { key: 'product',      label: 'Producto',   width: 250, sortKey: 'product',      title: 'Nombre del producto fabricado.' },
    { key: 'planned_qty',  label: 'Programado', width: 100, sortKey: 'planned_qty',  align: 'end', title: 'Total de unidades planificadas en OFs del período.' },
    { key: 'produced_qty', label: 'Producido',  width: 100, sortKey: 'produced_qty', align: 'end', title: 'Total de unidades producidas y registradas.' },
    { key: 'pct',          label: '%',          width: 80,  sortKey: 'pct',          align: 'end', title: 'Cumplimiento = Producido ÷ Programado × 100.' },
];

/**
 * Convierte un objeto Date en string con formato YYYY-MM-DD.
 * @param {Date} d - Fecha a convertir.
 * @returns {string} Fecha en formato ISO local (sin zona horaria).
 */
function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class MoDashboardWidget extends Component {
    static template = "odoo_mrp_planner.MoDashboardWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    /**
     * Inicializa servicios ORM y action, gestores de columnas, estado reactivo y
     * ciclos de vida del componente. Calcula el rango de fechas del mes actual como
     * valor inicial de los filtros dateFrom / dateTo.
     */
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this._root   = useRef("moRoot");
        this.colsOf  = useColManager('mo_ofs',        MO_OF_COLS);
        this.colsReq = useColManager('mo_requests',   MO_SCHED_COLS);
        this.colsComp= useColManager('mo_comparison', MO_COMP_COLS);

        const now          = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            tab:            "ofs",     // "ofs" | "requests" | "comparison"
            tags:           [],
            selectedTag:    "",
            dateFrom:    toDateStr(firstOfMonth),
            dateTo:         toDateStr(lastOfMonth),
            loading:        true,
            sortField:      null,
            sortDir:        "asc",
            page:           1,
            pageSize:       50,
            enable_scheduling: true,
            // OFs
            ofs_kpis:    { total: 0, in_progress: 0, delayed: 0, reschedule: 0, done: 0, partial: 0 },
            mos:         [],
            // Programaciones
            req_kpis:    { active: 0, calculated: 0, reschedule: 0, mos_delayed: 0 },
            requests:    [],
            // Comparativo
            cmp_kpis:      { planned: 0, produced: 0, pct: 0, ofs_done: 0 },
            comparison:    [],
            cmp_total:     0,
            cmp_mode:      'finish_date',
            cmp_wh_ids:    null,
        });

        onMounted(async () => {
            try {
                // Paralelizar: get_wc_tags y get_mo_widget_data son RPCs independientes
                await Promise.all([this._loadTags(), this._loadData()]);
                requestAnimationFrame(() => this._syncH());
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });
        onPatched(() => requestAnimationFrame(() => this._syncH()));
    }

    /** @returns {Promise<void>} Carga las etiquetas/sectores de centros de trabajo y config */
    async _loadTags() {
        const res = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
        this.state.tags = res.tags;
        this.state.enable_scheduling = res.enable_scheduling;
        if (!res.enable_scheduling && this.state.tab === 'requests') {
            this.state.tab = 'ofs';
        }
    }

    /** @returns {Promise<void>} Carga datos desde el servidor y actualiza state */
    async _loadData() {
        this.state.loading = true;
        try {
            if (this.state.tab === "ofs") {
                const [d, kpis] = await Promise.all([
                    this.orm.call("mrp.planner.dashboard", "get_mo_widget_data", [
                        this.state.dateFrom,
                        this.state.dateTo,
                        this.state.selectedTag ? parseInt(this.state.selectedTag) : null,
                        this.state.sortField || null,
                        this.state.sortDir,
                        this.state.page,
                        this.state.pageSize,
                    ]),
                    this.orm.call("mrp.planner.dashboard", "get_mo_kpi_counts", [
                        this.state.dateFrom,
                        this.state.dateTo,
                        this.state.selectedTag ? parseInt(this.state.selectedTag) : null,
                    ]),
                ]);
                this.state.ofs_kpis = kpis;
                this.state.mos      = d.mos;
            } else if (this.state.tab === "requests") {
                const d = await this.orm.call("mrp.planner.dashboard", "get_request_widget_data", [
                    this.state.sortField || null,
                    this.state.sortDir,
                    this.state.page,
                    this.state.pageSize,
                ]);
                this.state.req_kpis  = d.kpis;
                this.state.requests  = d.requests;
            } else {
                const d = await this.orm.call("mrp.planner.dashboard", "get_comparison_data", [
                    this.state.dateFrom,
                    this.state.dateTo,
                    this.state.selectedTag ? parseInt(this.state.selectedTag) : null,
                    this.state.page,
                    this.state.pageSize,
                    this.state.sortField || null,
                    this.state.sortDir,
                ]);
                this.state.cmp_kpis   = d.kpis;
                this.state.comparison = d.items;
                this.state.cmp_total  = d.total || 0;
                this.state.cmp_mode   = d.mo_mode || 'finish_date';
                this.state.cmp_wh_ids = d.allowed_wh_ids ?? null;
            }
        } catch (e) {
            console.error("[MoDashboardWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Cambia la pestaña activa y recarga los datos correspondientes.
     * Resetea la paginación y el ordenamiento para evitar estados inconsistentes
     * entre pestañas que manejan columnas diferentes.
     * @param {"ofs"|"requests"|"comparison"} tab - Pestaña destino.
     */
    setTab(tab) {
        if (this.state.tab === tab) return;
        this.state.tab = tab;
        this.state.sortField = null;
        this.state.sortDir = "asc";
        this.state.page = 1;
        this._loadData().then(() => requestAnimationFrame(() => this._syncH()));
    }

    /** Iguala la altura del panel de tabla a la del panel de KPIs */
    _syncH() {
        const root = this._root.el;
        if (!root) return;
        const kpiEl   = root.querySelector('.o_kpi_height_src');
        const tableEl = root.querySelector('.o_table_scroll');
        if (!kpiEl || !tableEl) return;
        tableEl.style.height = '0';
        const h = kpiEl.offsetHeight;
        tableEl.style.height = Math.max(h, 150) + 'px';
    }

    /**
     * Actualiza el filtro de fecha inicial y recarga datos desde la página 1.
     * @param {Event} ev - Evento change del input[type=date].
     */
    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this.state.page = 1; this._loadData(); }

    /**
     * Actualiza el filtro de fecha final y recarga datos desde la página 1.
     * @param {Event} ev - Evento change del input[type=date].
     */
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this.state.page = 1; this._loadData(); }

    /**
     * Actualiza el filtro de sector/tag y recarga datos desde la página 1.
     * @param {Event} ev - Evento change del select de categorías de WC.
     */
    onTagChange(ev)      { this.state.selectedTag = ev.target.value; this.state.page = 1; this._loadData(); }

    /**
     * Indica si se deben mostrar los filtros de fecha y sector.
     * La pestaña "requests" no aplica estos filtros porque las programaciones
     * no tienen rango de fechas propio.
     * @returns {boolean}
     */
    get showFilters() { return this.state.tab !== "requests"; }

    // ── Navegación OFs ───────────────────────────────────────────────────────

    /**
     * Abre la vista lista/form de mrp.production aplicando el dominio indicado.
     * Excluye siempre las OFs de subcontratación para no mezclar flujos.
     * @param {string} name - Título de la ventana de acción.
     * @param {Array} domain - Dominio Odoo adicional para filtrar las OFs.
     */
    _navigate(name, domain) {
        const baseDomain = [...domain, ["location_src_id.is_subcontracting_location", "!=", true]];
        if (this.state.selectedTag) {
            baseDomain.push("|",
                ["workorder_ids", "=", false],
                ["workorder_ids.workcenter_id.tag_ids", "in", [parseInt(this.state.selectedTag)]]
            );
        }
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.production", view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: baseDomain,
            target: "current",
        });
    }

    /**
     * Construye el fragmento de dominio de rango de fechas según los filtros activos.
     * Agrega condiciones sobre date_finished solo si los valores no están vacíos.
     * @returns {Array} Tuplas de dominio Odoo para dateFrom y/o dateTo.
     */
    _dateDomain() {
        const d = [];
        if (this.state.dateFrom) d.push(["date_finished", ">=", this.state.dateFrom + " 00:00:00"]);
        if (this.state.dateTo)   d.push(["date_finished", "<=", this.state.dateTo   + " 23:59:59"]);
        return d;
    }

    /** Navega a la lista de OFs activas (excluye done, cancel y draft) del período. */
    onClickTotal()      { this._navigate("OFs activas",     [["state", "not in", ["done", "cancel", "draft"]], ...this._dateDomain()]); }

    /** Navega a la lista de OFs en progreso o por cerrar del período. */
    onClickInProgress() { this._navigate("OFs en progreso", [["state", "in", ["progress", "to_close"]], ...this._dateDomain()]); }

    /** Navega a las OFs atrasadas: estado no terminal y date_finished menor al momento actual. */
    onClickDelayed() {
        const now = new Date().toISOString();
        this._navigate("OFs atrasadas", [
            ["state", "not in", ["done", "cancel"]], ["date_finished", "<", now], ...this._dateDomain(),
        ]);
    }
    /** Navega a las OFs marcadas con x_reschedule_needed que aún no finalizaron. */
    onClickReschedule() {
        this._navigate("Para reprogramar", [
            ["state", "not in", ["done", "cancel"]], ["x_reschedule_needed", "=", true], ...this._dateDomain(),
        ]);
    }

    /** Navega a las OFs con state=done dentro del rango de fechas seleccionado. */
    onClickDone() {
        this._navigate("OFs finalizadas", [
            ["state", "=", "done"],
            ["date_finished", ">=", this.state.dateFrom + " 00:00:00"],
            ["date_finished", "<=", this.state.dateTo   + " 23:59:59"],
        ]);
    }

    /** Navega a las OFs con state=to_close (producción terminada, pendiente de cierre formal). */
    onClickPartial() {
        this._navigate("Por cerrar", [["state", "=", "to_close"], ...this._dateDomain()]);
    }

    /** @param {number|string} id — ID de la OF a abrir */
    openMo(id) {
        // FIX [FASE-3]: res_id abre el form directamente; domain+list_view era redundante
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mrp.production",
            res_id: parseInt(id),
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    /**
     * Maneja el click en una fila de la tabla de OFs y abre el formulario de esa OF.
     * Obtiene el ID desde el atributo data-mo-id del tr más cercano.
     * @param {MouseEvent} ev - Evento click sobre la fila.
     */
    openMoFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.moId;
        if (id) this.openMo(id);
    }

    // ── Navegación Programaciones ────────────────────────────────────────────

    /** Navega a las solicitudes de programación en estado confirmed (OFs ya creadas). */
    onClickReqActive()     { this._navReq("OFs creadas",              [["state", "=", "confirmed"]]); }

    /** Navega a las solicitudes en estado calculated (con fechas de inicio calculadas). */
    onClickReqCalc()       { this._navReq("Programaciones calculadas", [["state", "=", "calculated"]]); }

    /** Navega a las solicitudes confirmed que tienen al menos una OF marcada para reprogramar. */
    onClickReqReschedule() { this._navReq("Con reprogramación",        [["state", "=", "confirmed"], ["item_ids.production_id.x_reschedule_needed", "=", true]]); }

    /** Navega a todas las solicitudes de programación sin filtro de estado. */
    onClickAllRequests()   { this._navReq("Todas las programaciones",  []); }

    onClickAllComparison() {
        const mode     = this.state.cmp_mode || 'finish_date';
        const dateFrom = this.state.dateFrom + ' 00:00:00';
        const dateTo   = this.state.dateTo   + ' 23:59:59';
        const domain   = [["state", "not in", ["cancel"]]];
        if (mode === 'start_date') {
            domain.push(["date_start", ">=", dateFrom], ["date_start", "<=", dateTo]);
        } else if (mode === 'overlap' || mode === 'proportional') {
            domain.push(["date_start", "<=", dateTo], "|",
                        ["date_finished", ">=", dateFrom], ["date_finished", "=", false]);
        } else {
            domain.push(["date_finished", ">=", dateFrom], ["date_finished", "<=", dateTo]);
        }
        const wh = this.state.cmp_wh_ids;
        if (wh && wh.length) {
            domain.push(["picking_type_id.warehouse_id", "in", wh]);
        }
        this._navigate("Producido vs Programado", domain);
    }

    /**
     * Abre la vista lista/form de mrp.production.request con el dominio indicado.
     * @param {string} name - Título de la ventana de acción.
     * @param {Array} domain - Dominio Odoo para filtrar las solicitudes.
     */
    _navReq(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.production.request", view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }

    /** @param {number|string} id — ID de la solicitud de programación a abrir */
    openRequest(id) {
        // FIX [FASE-3]: res_id abre el form directamente; domain+list_view era redundante
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mrp.production.request",
            res_id: parseInt(id),
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    /**
     * Maneja el click en una fila de la tabla de solicitudes y abre el formulario.
     * Obtiene el ID desde el atributo data-req-id del tr más cercano.
     * @param {MouseEvent} ev - Evento click sobre la fila.
     */
    openRequestFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.reqId;
        if (id) this.openRequest(id);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    /**
     * Devuelve la etiqueta legible para el estado de una OF.
     * @param {string} state - Valor del campo state en mrp.production.
     * @returns {string} Etiqueta en español, o el valor original si no está mapeado.
     */
    stateLabel(state) {
        return { confirmed: "Confirmada", progress: "En progreso", to_close: "Por cerrar",
                 done: "Completada", draft: "Borrador" }[state] || state;
    }

    /**
     * Devuelve las clases CSS Bootstrap para el badge del estado de una OF.
     * @param {string} state - Valor del campo state en mrp.production.
     * @returns {string} Clases CSS del badge.
     */
    stateClass(state) {
        return { confirmed: "badge bg-info", progress: "badge bg-primary",
                 to_close: "badge bg-warning text-dark", done: "badge bg-success",
                 draft: "badge bg-secondary" }[state] || "badge bg-secondary";
    }

    /**
     * Devuelve la etiqueta legible para el estado de una solicitud de programación.
     * @param {string} state - Valor del campo state en mrp.production.request.
     * @returns {string} Etiqueta en español, o el valor original si no está mapeado.
     */
    reqStateLabel(state) {
        return { confirmed: "OFs creadas", calculated: "Calculada" }[state] || state;
    }

    /**
     * Devuelve las clases CSS Bootstrap para el badge del estado de una solicitud.
     * @param {string} state - Valor del campo state en mrp.production.request.
     * @returns {string} Clases CSS del badge.
     */
    reqStateClass(state) {
        return { confirmed: "badge bg-success", calculated: "badge bg-info" }[state] || "badge bg-secondary";
    }

    /**
     * Devuelve las clases CSS de color según el porcentaje de cumplimiento.
     * Umbrales: >= 90 → verde, >= 50 → amarillo, < 50 → rojo.
     * @param {number} pct - Porcentaje de cumplimiento (0–100+).
     * @returns {string} Clases CSS Bootstrap de color y peso de fuente.
     */
    pctClass(pct) {
        if (pct >= 90) return "text-success fw-semibold";
        if (pct >= 50) return "text-warning fw-semibold";
        return "text-danger fw-semibold";
    }

    /**
     * Total de registros del dataset activo según la pestaña.
     * Para OFs y requests usa el conteo del servidor (KPI); para comparativo
     * usa la longitud del array local porque es una agregación client-side.
     * @returns {number}
     */
    get activeCount() {
        if (this.state.tab === 'ofs')        return this.state.ofs_kpis.total || 0;
        if (this.state.tab === 'requests')   return this.state.req_kpis.total || 0;
        return this.state.cmp_total;
    }

    /**
     * Número total de páginas calculado a partir de activeCount y pageSize.
     * Devuelve al menos 1 para evitar división por cero en la plantilla.
     * @returns {number}
     */
    get totalPages()  { return Math.max(1, Math.ceil(this.activeCount / this.state.pageSize)); }

    /**
     * Indica si existe una página siguiente disponible.
     * @returns {boolean}
     */
    get hasNextPage() { return this.state.page < this.totalPages; }

    /**
     * Indica si existe una página anterior disponible.
     * @returns {boolean}
     */
    get hasPrevPage() { return this.state.page > 1; }

    /** Avanza a la página siguiente y recarga datos si hay página disponible. */
    nextPage() { if (this.hasNextPage) { this.state.page++; this._loadData(); } }

    /** Retrocede a la página anterior y recarga datos si hay página disponible. */
    prevPage() { if (this.hasPrevPage) { this.state.page--; this._loadData(); } }

    /**
     * Formatea un número entero con separadores de miles en locale es-AR.
     * @param {number} n - Número a formatear.
     * @returns {string} Número formateado (ej. "1.234").
     */
    fmt(n)    { return new Intl.NumberFormat('es-AR').format(n || 0); }

    moKpiTooltip(section, key) {
        const f = n => this.fmt(n);
        const pct = (a, b) => b > 0 ? ` (${Math.round(a / b * 100)}%)` : '';
        if (section === 'ofs') {
            const k = this.state.ofs_kpis;
            switch (key) {
                case 'total':
                    return `OFs confirmadas, en progreso o por cerrar con fecha de fin en el período\nEstados incluidos: Confirmada · En progreso · Por cerrar\n→ ${f(k.total)} OFs activas`;
                case 'in_progress':
                    return `OFs cuya producción fue iniciada formalmente en el sistema\nEstados: En progreso · Por cerrar\nOFs en progreso ÷ OFs activas × 100\n→ ${f(k.in_progress)} ÷ ${f(k.total)} × 100 = ${k.total > 0 ? Math.round(k.in_progress / k.total * 100) : 0}%`;
                case 'delayed':
                    return `OFs activas con fecha_fin < hoy\nCondición: scheduled_date_finished < fecha actual y estado activo\nOFs atrasadas ÷ OFs activas × 100\n→ ${f(k.delayed)} ÷ ${f(k.total)} × 100 = ${k.total > 0 ? Math.round(k.delayed / k.total * 100) : 0}%`;
                case 'reschedule':
                    return `OFs con campo "Requiere reprogramación" activado (x_reschedule_needed = Sí)\nSe marca automáticamente por alertas o manualmente\nOFs a reprogramar ÷ OFs activas × 100\n→ ${f(k.reschedule)} ÷ ${f(k.total)} × 100 = ${k.total > 0 ? Math.round(k.reschedule / k.total * 100) : 0}%`;
                case 'done':
                    return `OFs con estado Completada (done) cerradas formalmente en el período\nFecha fin dentro del rango seleccionado\n→ ${f(k.done)} OFs finalizadas`;
                case 'partial':
                    return `OFs con producción completa pendientes de cierre formal en Odoo\nEstado: Por cerrar (to_close) — qty_produced >= product_qty pero sin validación final\n→ ${f(k.partial)} OFs por cerrar`;
            }
        }
        if (section === 'req') {
            const k = this.state.req_kpis;
            switch (key) {
                case 'active':
                    return `Solicitudes de programación confirmadas con OFs generadas\nEstado de la solicitud: Confirmada\n→ ${f(k.active)} solicitudes activas`;
                case 'calculated':
                    return `Solicitudes que pasaron por el cálculo de fechas y capacidad de CTs\nEstado: Calculada\nSolicitudes calculadas ÷ Solicitudes activas × 100\n→ ${f(k.calculated)} ÷ ${f(k.active)} × 100 = ${k.active > 0 ? Math.round(k.calculated / k.active * 100) : 0}%`;
                case 'reschedule':
                    return `Solicitudes con al menos una OF marcada como "requiere reprogramación"\nCampo x_reschedule_needed = Sí en alguna OF asociada\n→ ${f(k.reschedule)} solicitudes`;
                case 'mos_delayed':
                    return `OFs atrasadas (fecha_fin < hoy y estado activo) asociadas a solicitudes activas\n→ ${f(k.mos_delayed)} OFs atrasadas`;
            }
        }
        if (section === 'cmp') {
            const k = this.state.cmp_kpis;
            const f2 = n => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n || 0);
            switch (key) {
                case 'planned':
                    return `Suma de product_qty de las OFs en el período seleccionado\n→ ${f2(k.planned)} unidades planificadas`;
                case 'produced':
                    return `Suma de qty_produced de las OFs con estado Completada (done) en el período\n→ ${f2(k.produced)} u producidas de ${f2(k.planned)} u planificadas`;
                case 'pct':
                    return `Relación entre lo producido y lo programado en el período\nProducido ÷ Programado × 100\n→ ${f2(k.produced)} ÷ ${f2(k.planned)} × 100 = ${k.pct}%\nVerde ≥ 90% | Amarillo ≥ 50% | Rojo < 50%`;
                case 'ofs_done':
                    return `OFs con estado Completada (done) finalizadas dentro del período\n→ ${f(k.ofs_done)} OFs completadas`;
            }
        }
        return '';
    }

    cmpRowTooltip(item) {
        const f = n => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n || 0);
        return `Relación entre producido y programado para este artículo en el período\nProducido ÷ Programado × 100\n→ ${f(item.produced_qty)} ÷ ${f(item.planned_qty)} × 100 = ${item.pct}%\nVerde ≥ 90% | Amarillo ≥ 50% | Rojo < 50%`;
    }

    /**
     * Formatea un número decimal con exactamente 2 decimales en locale es-AR.
     * @param {number} n - Número a formatear.
     * @returns {string} Número formateado (ej. "1.234,56").
     */
    fmtAmt(n) { return new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0); }

    // ── Ordenamiento ─────────────────────────────────────────────────────────

    /**
     * Maneja el click en el encabezado de una columna sorteable.
     * Lee el atributo data-sort-key del th y delega en sortBy.
     * @param {MouseEvent} ev - Evento click sobre el th.
     */
    onHeaderClick(ev) {
        const sortKey = ev.currentTarget.dataset.sortKey;
        if (sortKey) this.sortBy(sortKey);
    }

    /**
     * Cambia el campo de ordenamiento o invierte la dirección si ya estaba activo.
     * Resetea a la página 1 para no quedar en una página inexistente tras re-sort.
     * @param {string} field - Clave de columna a ordenar (coincide con sortKey de la columna).
     */
    sortBy(field) {
        if (this.state.sortField === field) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortField = field;
            this.state.sortDir = "asc";
        }
        this.state.page = 1;
        this._loadData();
    }

    /**
     * Devuelve las clases CSS del ícono de ordenamiento para la columna indicada.
     * Muestra fa-sort neutro si la columna no es la activa, o la flecha direccional si lo es.
     * @param {string} field - Clave de columna a evaluar.
     * @returns {string} Clases Font Awesome para el ícono de sort.
     */
    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    // Campos computados en el dict que el backend no puede ordenar en DB
    static _CLIENT_SORT_MO  = new Set(["pending_delivery", "partner"]);
    static _CLIENT_SORT_REQ = new Set(["mos_total", "mos_done", "mos_delayed", "partner"]);

    /**
     * Ordena una lista de filas en el cliente cuando el campo no puede resolverse en BD.
     * Si clientFields es null, aplica siempre el sort client-side (caso comparativo).
     * Si clientFields es un Set, solo ordena si el campo activo está en ese Set;
     * de lo contrario el backend ya devolvió la lista ordenada y no hay que tocarla.
     * Detecta fechas en formato DD/MM/YYYY y las convierte a YYYYMMDD antes de comparar.
     * @param {Array<Object>} list - Filas a ordenar (no muta el array original).
     * @param {Set<string>|null} clientFields - Campos que requieren sort en cliente, o null para forzarlo.
     * @returns {Array<Object>} Nueva copia del array ordenada.
     */
    _sortList(list, clientFields) {
        const { sortField, sortDir } = this.state;
        if (!sortField) return list;
        if (clientFields && !clientFields.has(sortField)) return list;
        const dateRe = /^\d{2}\/\d{2}\/\d{4}$/;
        return [...list].sort((a, b) => {
            let va = a[sortField] ?? "";
            let vb = b[sortField] ?? "";
            if (typeof va === "number" && typeof vb === "number") {
                return sortDir === "asc" ? va - vb : vb - va;
            }
            if (dateRe.test(va) && dateRe.test(vb)) {
                va = va.split("/").reverse().join("");
                vb = vb.split("/").reverse().join("");
            }
            const cmp = String(va).localeCompare(String(vb), "es", { sensitivity: "base" });
            return sortDir === "asc" ? cmp : -cmp;
        });
    }

    /**
     * Lista de OFs ordenada, aplicando sort client-side solo para campos calculados
     * que el backend no puede resolver directamente en la query (pending_delivery, partner).
     * @returns {Array<Object>}
     */
    get sortedMos()        { return this._sortList(this.state.mos,        MoDashboardWidget._CLIENT_SORT_MO); }

    /**
     * Lista de solicitudes de programación ordenada, aplicando sort client-side solo
     * para campos agregados que no existen en la tabla (mos_total, mos_done, etc.).
     * @returns {Array<Object>}
     */
    get sortedRequests()   { return this._sortList(this.state.requests,    MoDashboardWidget._CLIENT_SORT_REQ); }

    /**
     * Lista del comparativo producción vs plan siempre ordenada en cliente,
     * ya que los datos son resultado de una agregación y no tienen orden de BD propio.
     * @returns {Array<Object>}
     */
    get sortedComparison() { return this.state.comparison; }  // server-sorted and paginated
}

registry.category("view_widgets").add("mo_dashboard_widget", {
    component: MoDashboardWidget,
});
