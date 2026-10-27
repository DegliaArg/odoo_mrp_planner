/** @odoo-module **/

/**
 * @widget HomeLauncherWidget
 * @description Pantalla de Inicio del módulo KPIs: un mosaico de accesos a los
 * paneles que el usuario puede ver. Evita que al entrar al módulo se abra
 * directamente el panel de Producción. Cada tarjeta abre su panel reutilizando
 * el método de apertura del backend (action_open_*) + el servicio de acciones.
 *
 * Método RPC que consume:
 *   - get_home_panels() → Array<{ section, name, desc, icon, method }>
 *
 * Props: { record: Object } (requerido por la infraestructura de widgets).
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class HomeLauncherWidget extends Component {
    static template = "odoo_mrp_planner.HomeLauncherWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: null, panels: [] });

        onMounted(async () => {
            try {
                const panels = await this.orm.call(
                    "mrp.planner.dashboard", "get_home_panels", []);
                this.state.panels = panels || [];
            } catch (e) {
                if (e.message === "Component is destroyed") return;
                this.state.error = e?.data?.message || e?.message || String(e);
            } finally {
                this.state.loading = false;
            }
        });
    }

    /** Paneles agrupados por sección, preservando el orden del backend. */
    get sections() {
        const order = [];
        const map = {};
        for (const p of this.state.panels) {
            if (!map[p.section]) { map[p.section] = []; order.push(p.section); }
            map[p.section].push(p);
        }
        return order.map(s => ({ name: s, panels: map[s] }));
    }

    /** Abre el panel: pide su acción al backend y la ejecuta. */
    async open(panel) {
        const action = await this.orm.call("mrp.planner.dashboard", panel.method, []);
        this.action.doAction(action);
    }
}

registry.category("view_widgets").add("home_launcher_widget", {
    component: HomeLauncherWidget,
});
