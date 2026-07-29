/** @odoo-module **/

/**
 * @description Sello "Actualizado HH:MM" para los encabezados de los paneles.
 *   Muestra la hora en que se cargó/recargó el panel (el botón Actualizar
 *   reabre la acción, por lo que el sello se renueva con cada actualización).
 */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

class RefreshStampWidget extends Component {
    static template = "odoo_mrp_planner.RefreshStampWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.time = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    }
}

registry.category("view_widgets").add("refresh_stamp", {
    component: RefreshStampWidget,
});
