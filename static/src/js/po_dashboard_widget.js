/** @odoo-module **/

import { Component, useState, onMounted, onPatched, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY_KPIS = {
    rfq: 0, to_approve: 0, total: 0, pending: 0, overdue: 0, overdue_critical: 0,
    receipts_total: 0, receipts_overdue: 0, deliveries_total: 0, deliveries_overdue: 0,
};

class PoDashboardWidget extends Component {
    static template = "odoo_mrp_reschedule.PoDashboardWidget";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        const now          = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            tab:        "all",      // "all" | "purchase" | "subcontract"
            listTab:    "overdue",  // "rfqs" | "approve" | "overdue" | "receipts" | "deliveries"
            dateFrom:   toDateStr(firstOfMonth),
            dateTo:     toDateStr(lastOfMonth),
            loading:    true,
            sortField:  null,
            sortDir:    "asc",
            kpis:       { ...EMPTY_KPIS },
            rfqs:       [],
            to_approve: [],
            overdue:    [],
            receipts:   [],
            deliveries: [],
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

        onMounted(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_po_dashboard_data",
                [this.state.tab, this.state.dateFrom, this.state.dateTo],
            );
            this.state.kpis       = d.kpis;
            this.state.rfqs       = d.rfqs;
            this.state.to_approve = d.to_approve;
            this.state.overdue    = d.overdue;
            this.state.receipts   = d.receipts   || [];
            this.state.deliveries = d.deliveries || [];
        } catch (e) {
            console.error("[PoDashboardWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    setTab(tab) {
        if (this.state.tab === tab) return;
        this.state.tab = tab;
        this.state.sortField = null;
        this.state.sortDir = "asc";
        this._load();
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this._load(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this._load(); }

    setListTab(tab) {
        this.state.listTab = tab;
        this.state.sortField = null;
        this.state.sortDir = "asc";
    }

    _scDomain() {
        if (this.state.tab === "purchase")    return [["subcontract_production_ids", "=", false]];
        if (this.state.tab === "subcontract") return [["subcontract_production_ids", "!=", false]];
        return [];
    }

    _navigate(name, baseDomain) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name,
            res_model: "purchase.order",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            domain:    [...baseDomain, ...this._scDomain()],
            target:    "current",
        });
    }

    _dateDomain() {
        const d = [];
        if (this.state.dateFrom) d.push(["date_planned", ">=", this.state.dateFrom + " 00:00:00"]);
        if (this.state.dateTo)   d.push(["date_planned", "<=", this.state.dateTo   + " 23:59:59"]);
        return d;
    }

    onClickRfqs()      { this._navigate("Cotizaciones", [["state", "in", ["draft", "sent"]], ...this._dateDomain()]); }
    onClickToApprove() { this._navigate("Por aprobar",  [["state", "=", "to approve"],       ...this._dateDomain()]); }
    onClickAll()       { this._navigate("Aprobadas",    [["state", "=", "purchase"], ["receipt_status", "!=", "full"], ...this._dateDomain()]); }
    onClickPending() {
        const now = new Date().toISOString();
        this._navigate("A tiempo", [
            ["state", "=", "purchase"], ["receipt_status", "!=", "full"],
            ["date_planned", ">=", now], ...this._dateDomain(),
        ]);
    }
    onClickOverdue() {
        const now = new Date().toISOString();
        this._navigate("Vencidas", [
            ["state", "=", "purchase"], ["receipt_status", "!=", "full"],
            ["date_planned", "<", now], ...this._dateDomain(),
        ]);
    }

    openPo(id) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "purchase.order",
            res_id:    id,
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    openPicking(id) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "stock.picking",
            res_id:    id,
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    get isEmpty() {
        const s = this.state;
        return !s.loading && s.rfqs.length === 0 && s.to_approve.length === 0 && s.overdue.length === 0
            && s.receipts.length === 0 && s.deliveries.length === 0;
    }

    get activeList() {
        switch (this.state.listTab) {
            case "rfqs":       return this.state.rfqs;
            case "approve":    return this.state.to_approve;
            case "receipts":   return this.state.receipts;
            case "deliveries": return this.state.deliveries;
            default:           return this.state.overdue;
        }
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

    get sortedList() { return this._sortList(this.activeList); }
}

registry.category("view_widgets").add("po_dashboard_widget", {
    component: PoDashboardWidget,
});
