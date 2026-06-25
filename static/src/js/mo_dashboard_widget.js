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

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class MoDashboardWidget extends Component {
    static template = "odoo_mrp_planner.MoDashboardWidget";
    static props = {
        record: { type: Object },
    };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this._root  = useRef("moRoot");

        const now          = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            tab:         "ofs",     // "ofs" | "requests" | "comparison"
            tags:        [],
            selectedTag: "",
            dateFrom:    toDateStr(firstOfMonth),
            dateTo:      toDateStr(lastOfMonth),
            loading:     true,
            sortField:   null,
            sortDir:     "asc",
            page:        1,
            pageSize:    50,
            // OFs
            ofs_kpis:    { total: 0, in_progress: 0, delayed: 0, reschedule: 0, done: 0, partial: 0 },
            mos:         [],
            // Programaciones
            req_kpis:    { active: 0, calculated: 0, reschedule: 0, mos_delayed: 0 },
            requests:    [],
            // Comparativo
            cmp_kpis:    { planned: 0, produced: 0, pct: 0, ofs_done: 0 },
            comparison:  [],
        });

        onMounted(async () => {
            await this._loadTags();
            await this._loadData();
            requestAnimationFrame(() => this._syncH());
        });
        onPatched(() => requestAnimationFrame(() => this._syncH()));
    }

    /** @returns {Promise<void>} Carga las etiquetas/sectores de centros de trabajo */
    async _loadTags() {
        this.state.tags = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
    }

    /** @returns {Promise<void>} Carga datos desde el servidor y actualiza state */
    async _loadData() {
        this.state.loading = true;
        try {
            if (this.state.tab === "ofs") {
                const d = await this.orm.call("mrp.planner.dashboard", "get_mo_widget_data", [
                    this.state.dateFrom,
                    this.state.dateTo,
                    this.state.selectedTag ? parseInt(this.state.selectedTag) : null,
                    this.state.sortField || null,
                    this.state.sortDir,
                    this.state.page,
                    this.state.pageSize,
                ]);
                this.state.ofs_kpis = d.kpis;
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
                ]);
                this.state.cmp_kpis   = d.kpis;
                this.state.comparison = d.items;
            }
        } catch (e) {
            console.error("[MoDashboardWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

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

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this.state.page = 1; this._loadData(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this.state.page = 1; this._loadData(); }
    onTagChange(ev)      { this.state.selectedTag = ev.target.value; this.state.page = 1; this._loadData(); }

    get showFilters() { return this.state.tab !== "requests"; }

    // ── Navegación OFs ───────────────────────────────────────────────────────

    _navigate(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.production", view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }

    _dateDomain() {
        const d = [];
        if (this.state.dateFrom) d.push(["date_finished", ">=", this.state.dateFrom + " 00:00:00"]);
        if (this.state.dateTo)   d.push(["date_finished", "<=", this.state.dateTo   + " 23:59:59"]);
        return d;
    }

    onClickTotal()      { this._navigate("OFs activas",     [["state", "not in", ["done", "cancel"]], ...this._dateDomain()]); }
    onClickInProgress() { this._navigate("OFs en progreso", [["state", "in", ["progress", "to_close"]], ...this._dateDomain()]); }
    onClickDelayed() {
        const now = new Date().toISOString();
        this._navigate("OFs atrasadas", [
            ["state", "not in", ["done", "cancel"]], ["date_finished", "<", now], ...this._dateDomain(),
        ]);
    }
    onClickReschedule() {
        this._navigate("Para reprogramar", [
            ["state", "not in", ["done", "cancel"]], ["x_reschedule_needed", "=", true], ...this._dateDomain(),
        ]);
    }
    onClickDone() {
        this._navigate("OFs finalizadas", [
            ["state", "=", "done"],
            ["date_finished", ">=", this.state.dateFrom + " 00:00:00"],
            ["date_finished", "<=", this.state.dateTo   + " 23:59:59"],
        ]);
    }
    onClickPartial() {
        this._navigate("Por cerrar", [["state", "=", "to_close"]]);
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

    openMoFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.moId;
        if (id) this.openMo(id);
    }

    // ── Navegación Programaciones ────────────────────────────────────────────

    onClickReqActive()     { this._navReq("OFs creadas",              [["state", "=", "confirmed"]]); }
    onClickReqCalc()       { this._navReq("Programaciones calculadas", [["state", "=", "calculated"]]); }
    onClickReqReschedule() { this._navReq("Con reprogramación",        [["state", "=", "confirmed"], ["item_ids.production_id.x_reschedule_needed", "=", true]]); }
    onClickAllRequests()   { this._navReq("Todas las programaciones",  []); }

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

    openRequestFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.reqId;
        if (id) this.openRequest(id);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    stateLabel(state) {
        return { confirmed: "Confirmada", progress: "En progreso", to_close: "Por cerrar",
                 done: "Completada", draft: "Borrador" }[state] || state;
    }

    stateClass(state) {
        return { confirmed: "badge bg-info", progress: "badge bg-primary",
                 to_close: "badge bg-warning text-dark", done: "badge bg-success",
                 draft: "badge bg-secondary" }[state] || "badge bg-secondary";
    }

    reqStateLabel(state) {
        return { confirmed: "OFs creadas", calculated: "Calculada" }[state] || state;
    }

    reqStateClass(state) {
        return { confirmed: "badge bg-success", calculated: "badge bg-info" }[state] || "badge bg-secondary";
    }

    pctClass(pct) {
        if (pct >= 90) return "text-success fw-semibold";
        if (pct >= 50) return "text-warning fw-semibold";
        return "text-danger fw-semibold";
    }

    get activeCount() {
        if (this.state.tab === 'ofs')      return this.state.ofs_kpis.total || 0;
        if (this.state.tab === 'requests') return this.state.req_kpis.total || 0;
        return this.state.comparison.length;
    }

    get totalPages()  { return Math.max(1, Math.ceil(this.activeCount / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }

    nextPage() { if (this.hasNextPage) { this.state.page++; this._loadData(); } }
    prevPage() { if (this.hasPrevPage) { this.state.page--; this._loadData(); } }

    fmt(n)    { return new Intl.NumberFormat('es-AR').format(n || 0); }
    fmtAmt(n) { return new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0); }

    // ── Ordenamiento ─────────────────────────────────────────────────────────

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

    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    // Campos computados en el dict que el backend no puede ordenar en DB
    static _CLIENT_SORT_MO  = new Set(["pending_delivery", "partner"]);
    static _CLIENT_SORT_REQ = new Set(["mos_total", "mos_done", "mos_delayed", "partner"]);

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

    get sortedMos()        { return this._sortList(this.state.mos,        MoDashboardWidget._CLIENT_SORT_MO); }
    get sortedRequests()   { return this._sortList(this.state.requests,    MoDashboardWidget._CLIENT_SORT_REQ); }
    get sortedComparison() { return this._sortList(this.state.comparison,  null); }  // client-side always (aggregated)
}

registry.category("view_widgets").add("mo_dashboard_widget", {
    component: MoDashboardWidget,
});
