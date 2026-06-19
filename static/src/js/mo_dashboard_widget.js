/** @odoo-module **/

import { Component, useState, onMounted, onPatched, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class MoDashboardWidget extends Component {
    static template = "odoo_mrp_reschedule.MoDashboardWidget";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

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
            // OFs
            ofs_kpis:    { total: 0, in_progress: 0, delayed: 0, reschedule: 0 },
            mos:         [],
            // Programaciones
            req_kpis:    { active: 0, calculated: 0, reschedule: 0, mos_delayed: 0 },
            requests:    [],
            // Comparativo
            cmp_kpis:    { planned: 0, produced: 0, pct: 0, ofs_done: 0 },
            comparison:  [],
        });

        this._kpiRowRef = useRef("kpiRow");
        const syncH = () => {
            const row = this._kpiRowRef.el;
            if (!row) return;
            const srcRow = row.querySelector(".o_kpi_height_src > .row");
            if (!srcRow) return;
            const h = srcRow.offsetHeight;
            row.querySelectorAll(".o_table_scroll").forEach(el => { el.style.height = h + "px"; });
        };
        onMounted(syncH);
        onPatched(syncH);

        onMounted(async () => {
            await this._loadTags();
            await this._loadData();
        });
    }

    async _loadTags() {
        this.state.tags = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
    }

    async _loadData() {
        this.state.loading = true;
        try {
            if (this.state.tab === "ofs") {
                const d = await this.orm.call("mrp.planner.dashboard", "get_mo_widget_data", [
                    this.state.dateFrom,
                    this.state.dateTo,
                    this.state.selectedTag ? parseInt(this.state.selectedTag) : null,
                ]);
                this.state.ofs_kpis = d.kpis;
                this.state.mos      = d.mos;
            } else if (this.state.tab === "requests") {
                const d = await this.orm.call("mrp.planner.dashboard", "get_request_widget_data", []);
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
        this._loadData();
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this._loadData(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this._loadData(); }
    onTagChange(ev)      { this.state.selectedTag = ev.target.value; this._loadData(); }

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

    openMo(id) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "mrp.production",
            res_id: id, view_mode: "form", views: [[false, "form"]], target: "current",
        });
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

    openRequest(id) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "mrp.production.request",
            res_id: id, view_mode: "form", views: [[false, "form"]], target: "current",
        });
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
    }

    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    _sortList(list) {
        const { sortField, sortDir } = this.state;
        if (!sortField) return list;
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

    get sortedMos()        { return this._sortList(this.state.mos); }
    get sortedRequests()   { return this._sortList(this.state.requests); }
    get sortedComparison() { return this._sortList(this.state.comparison); }
}

registry.category("view_widgets").add("mo_dashboard_widget", {
    component: MoDashboardWidget,
});
