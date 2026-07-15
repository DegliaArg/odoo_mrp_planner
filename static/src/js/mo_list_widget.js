/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class MoListWidget extends Component {
    static template = "odoo_mrp_planner.MoListWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        const now          = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            warehouses:          [],
            selectedWarehouseId: null,
            dateFrom:            toDateStr(firstOfMonth),
            dateTo:              toDateStr(lastOfMonth),
            loading:             false,
            mos:                 [],
        });

        onMounted(async () => {
            try {
                await Promise.all([this._loadWarehouses(), this._loadMos()]);
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });
    }

    async _loadWarehouses() {
        const res = await this.orm.call("mrp.planner.dashboard", "get_mo_warehouses", []);
        this.state.warehouses = res.warehouses;
    }

    async _loadMos() {
        if (!this.state.dateFrom || !this.state.dateTo) return;
        this.state.loading = true;
        try {
            this.state.mos = await this.orm.call(
                "mrp.planner.dashboard",
                "get_filtered_mos",
                [
                    this.state.dateFrom,
                    this.state.dateTo,
                    this.state.selectedWarehouseId || null,
                ],
            );
        } catch (e) {
            console.error("[MoListWidget] Error:", e);
            this.state.mos = [];
        } finally {
            this.state.loading = false;
        }
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        this._loadMos();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        this._loadMos();
    }

    onWarehouseChange(ev) {
        this.state.selectedWarehouseId = ev.target.value || null;
        this._loadMos();
    }

    openMo(moId) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.production",
            res_id:    moId,
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    stateLabel(state) {
        const labels = {
            confirmed: "Confirmada",
            progress:  "En progreso",
            to_close:  "Por cerrar",
            done:      "Completada",
            draft:     "Borrador",
        };
        return labels[state] || state;
    }

    stateClass(state) {
        const map = {
            confirmed: "badge bg-info",
            progress:  "badge bg-primary",
            to_close:  "badge bg-warning text-dark",
            done:      "badge bg-success",
            draft:     "badge bg-secondary",
        };
        return map[state] || "badge bg-secondary";
    }
}

registry.category("view_widgets").add("mo_list_widget", {
    component: MoListWidget,
});
