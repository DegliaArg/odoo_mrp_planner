/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class AlertKpiWidget extends Component {
    static template = "odoo_mrp_planner.AlertKpiWidget";
    static components = {};
    static props = { record: { type: Object }, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.state  = useState({
            kpis:      { mo_delayed: 0, mo_upcoming: 0, mo_in_progress: 0, qty_mismatch: 0, critical: 0 },
            sc_loc_ids: [],
            loading:   true,
        });
        onMounted(async () => {
            try {
                await this._loadData();
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });
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
            // Alcance fijo: solo la exclusión de subcontratación. El tipo de alerta
            // y "Sin resolver" viajan como facetas removibles (filtros con nombre de
            // la vista de búsqueda), para poder ampliar la vista desde la lista.
            domain: [
                "|",
                ["production_id", "=", false],
                ["production_id.location_src_id.is_subcontracting_location", "!=", true],
            ],
            context: {
                search_default_unresolved: 1,
                ["search_default_" + alertType]: 1,
            },
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

    alertKpiTooltip(key) {
        const k = this.state.kpis;
        const f = n => this.fmt(n);
        switch (key) {
            case 'mo_delayed':
                return `OFs activas cuya fecha de fin planificada ya superó la fecha actual. Indica retrasos que requieren acción inmediata.\n→ ${f(k.mo_delayed)} OFs atrasadas`;
            case 'mo_upcoming':
                return `OFs activas con fecha de fin próxima a vencer, dentro del horizonte de advertencia configurado.\n→ ${f(k.mo_upcoming)} OFs por vencer`;
            case 'mo_in_progress':
                return `OFs actualmente en producción (en progreso o listas para cerrar).\n→ ${f(k.mo_in_progress)} OFs en curso`;
            case 'qty_mismatch':
                return `OFs completadas donde la cantidad producida difiere de la planificada más allá de la tolerancia configurada.\n→ ${f(k.qty_mismatch)} OFs con cant. diferente`;
        }
        return '';
    }
}

registry.category("view_widgets").add("alert_kpi_widget", { component: AlertKpiWidget });
