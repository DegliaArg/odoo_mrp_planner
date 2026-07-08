/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class AlertKpiWidget extends Component {
    static template = "odoo_mrp_planner.AlertKpiWidget";
    static props = { record: { type: Object }, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.state  = useState({
            kpis:      { mo_delayed: 0, mo_upcoming: 0, mo_in_progress: 0, qty_mismatch: 0, critical: 0 },
            sc_loc_ids: [],
            loading:   true,
        });
        onMounted(() => this._loadData());
    }

    async _loadData() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard", "get_alert_stats", []
            );
            this.state.kpis      = d;
            this.state.sc_loc_ids = d.sc_loc_ids || [];
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
                ["production_id.location_src_id.is_subcontracting_location", "!=", true],
            ],
            target: "current",
        });
    }

    onViewDelayed()    { if (this.state.kpis.mo_delayed)     this._navigate("OFs atrasadas",    "mo_delayed"); }
    onViewUpcoming()   { if (this.state.kpis.mo_upcoming)   this._navigate("OFs por vencer",   "mo_upcoming"); }
    onViewMismatch()   { if (this.state.kpis.qty_mismatch)  this._navigate("Cant. diferentes", "qty_mismatch"); }
    onViewInProgress() {
        if (!this.state.kpis.mo_in_progress) return;
        const domain = [["state", "in", ["progress", "to_close"]]];
        if (this.state.sc_loc_ids.length) {
            domain.push(["location_src_id", "not in", this.state.sc_loc_ids]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "OFs en curso",
            res_model: "mrp.production",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    fmt(n) { return new Intl.NumberFormat("es-AR").format(n || 0); }
}

registry.category("view_widgets").add("alert_kpi_widget", { component: AlertKpiWidget });
