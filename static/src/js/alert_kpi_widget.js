/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class AlertKpiWidget extends Component {
    static template = "odoo_mrp_planner.AlertKpiWidget";
    static props = { record: Object, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.state  = useState({
            kpis:    { mo_delayed: 0, mo_upcoming: 0, qty_mismatch: 0, mo_cancelled: 0, critical: 0 },
            loading: true,
        });
        onMounted(() => this._loadData());
    }

    async _loadData() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard", "get_alert_stats", []
            );
            this.state.kpis = d;
        } catch (e) {
            console.error("[AlertKpiWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    _navigate(name, alertType) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.reschedule.alert",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["resolved", "=", false],
                ["alert_type", "=", alertType],
                "|",
                ["production_id.bom_id", "=", false],
                ["production_id.bom_id.type", "!=", "subcontract"],
            ],
            target: "current",
        });
    }

    onViewDelayed()   { if (this.state.kpis.mo_delayed)   this._navigate("OFs atrasadas",    "mo_delayed"); }
    onViewUpcoming()  { if (this.state.kpis.mo_upcoming)  this._navigate("OFs por vencer",   "mo_upcoming"); }
    onViewMismatch()  { if (this.state.kpis.qty_mismatch) this._navigate("Cant. diferentes", "qty_mismatch"); }
    onViewCancelled() { if (this.state.kpis.mo_cancelled) this._navigate("OFs canceladas",   "mo_cancelled"); }

    fmt(n) { return new Intl.NumberFormat("es-AR").format(n || 0); }
}

registry.category("view_widgets").add("alert_kpi_widget", { component: AlertKpiWidget });
