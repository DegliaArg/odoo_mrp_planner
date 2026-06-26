/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WcLoadChart extends Component {
    static template = "odoo_mrp_planner.WcLoadChart";

    setup() {
        this.orm   = useService("orm");
        this.action = useService("action");
        this.state = useState({ rows: [], loading: true });
        onMounted(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            const rows = await this.orm.call(
                "mrp.planner.dashboard",
                "get_wc_load_data",
                [],
            );
            this.state.rows = rows || [];
        } catch (e) {
            console.error("[WcLoadChart]", e);
            this.state.rows = [];
        } finally {
            this.state.loading = false;
        }
    }

    openWc(wcId) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.workcenter",
            res_id:    wcId,
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    barClass(pct) {
        if (pct >= 90) return "bg-danger";
        if (pct >= 70) return "bg-warning";
        return "bg-success";
    }

    fmtH(h) {
        if (h === null || h === undefined) return "—";
        const hrs = Math.floor(h);
        const min = Math.round((h - hrs) * 60);
        return min > 0 ? `${hrs}h ${min}m` : `${hrs}h`;
    }
}

registry.category("view_widgets").add("wc_load_chart", {
    component: WcLoadChart,
});
