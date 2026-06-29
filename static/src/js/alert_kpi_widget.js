/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const ALL_STATES = ["confirmed", "progress", "to_close"];

class AlertKpiWidget extends Component {
    static template = "odoo_mrp_planner.AlertKpiWidget";
    static props = { record: Object, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.state  = useState({
            states:  [...ALL_STATES],
            kpis:    { mo_delayed: 0, mo_upcoming: 0, qty_mismatch: 0, mo_cancelled: 0, critical: 0 },
            loading: true,
        });
        onMounted(() => this._loadData());
    }

    async _loadData() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard", "get_alert_stats", [this.state.states]
            );
            this.state.kpis = d;
        } catch (e) {
            console.error("[AlertKpiWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    isStateActive(s) { return this.state.states.includes(s); }

    onStateToggle(s) {
        const cur = this.state.states;
        if (cur.includes(s)) {
            if (cur.length > 1) this.state.states = cur.filter(x => x !== s);
        } else {
            this.state.states = [...cur, s];
        }
        this._loadData();
    }

    _stateFilter() {
        return this.state.states.length === ALL_STATES.length
            ? []
            : [["production_id.state", "in", this.state.states]];
    }

    _navigate(name, alertType) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.reschedule.alert",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["resolved", "=", false], ["alert_type", "=", alertType], ...this._stateFilter()],
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
