/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const EMPTY_KPIS = { rfq: 0, to_approve: 0, total: 0, pending: 0, overdue: 0, overdue_critical: 0 };

class PoDashboardWidget extends Component {
    static template = "odoo_mrp_reschedule.PoDashboardWidget";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            tab:        "all",      // "all" | "purchase" | "subcontract"
            listTab:    "overdue",  // "rfqs" | "approve" | "overdue"
            loading:    true,
            kpis:       { ...EMPTY_KPIS },
            rfqs:       [],
            to_approve: [],
            overdue:    [],
        });

        onMounted(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_po_dashboard_data",
                [this.state.tab],
            );
            this.state.kpis       = d.kpis;
            this.state.rfqs       = d.rfqs;
            this.state.to_approve = d.to_approve;
            this.state.overdue    = d.overdue;
        } catch (e) {
            console.error("[PoDashboardWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    setTab(tab) {
        if (this.state.tab === tab) return;
        this.state.tab = tab;
        this._load();   // dimming keeps previous content visible during load
    }

    setListTab(tab) {
        this.state.listTab = tab;
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
            domain:    [...baseDomain, ...this._scDomain()],
            target:    "current",
        });
    }

    onClickRfqs()      { this._navigate("Cotizaciones", [["state", "in", ["draft", "sent"]]]); }
    onClickToApprove() { this._navigate("Por aprobar",  [["state", "=", "to approve"]]); }
    onClickAll()       { this._navigate("Aprobadas",    [["state", "=", "purchase"], ["receipt_status", "!=", "full"]]); }
    onClickPending() {
        const now = new Date().toISOString();
        this._navigate("A tiempo", [
            ["state", "=", "purchase"], ["receipt_status", "!=", "full"], ["date_planned", ">=", now],
        ]);
    }
    onClickOverdue() {
        const now = new Date().toISOString();
        this._navigate("Vencidas", [
            ["state", "=", "purchase"], ["receipt_status", "!=", "full"], ["date_planned", "<", now],
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

    get isEmpty() {
        const s = this.state;
        return !s.loading && s.rfqs.length === 0 && s.to_approve.length === 0 && s.overdue.length === 0;
    }

    get activeList() {
        switch (this.state.listTab) {
            case "rfqs":    return this.state.rfqs;
            case "approve": return this.state.to_approve;
            default:        return this.state.overdue;
        }
    }
}

registry.category("view_widgets").add("po_dashboard_widget", {
    component: PoDashboardWidget,
});
