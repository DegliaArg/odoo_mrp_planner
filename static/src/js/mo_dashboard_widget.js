/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
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

    onClickTotal()      { this._navigate("OFs activas",          [["state", "not in", ["done", "cancel"]]]); }
    onClickInProgress() { this._navigate("OFs en progreso",      [["state", "in", ["progress", "to_close"]]]); }
    onClickDelayed() {
        const now = new Date().toISOString();
        this._navigate("OFs atrasadas", [["state", "not in", ["done", "cancel"]], ["date_finished", "<", now]]);
    }
    onClickReschedule() {
        this._navigate("Para reprogramar", [["state", "not in", ["done", "cancel"]], ["x_reschedule_needed", "=", true]]);
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
}

registry.category("view_widgets").add("mo_dashboard_widget", {
    component: MoDashboardWidget,
});
