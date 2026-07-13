/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

class SchedulingToggleField extends Component {
    static template = "odoo_mrp_planner.SchedulingToggleField";
    static props = { "*": true };

    get value() {
        return this.props.record.data[this.props.name];
    }

    onChange(ev) {
        const newVal = ev.target.checked;
        if (!newVal && this.value) {
            ev.preventDefault();
            ev.stopPropagation();
            const ok = window.confirm(
                "Al desactivar la programación se eliminarán los permisos de " +
                "Programación de todos los usuarios.\n\n¿Confirmar?"
            );
            if (ok) {
                this.props.record.update({ [this.props.name]: false });
            }
        } else {
            this.props.record.update({ [this.props.name]: newVal });
        }
    }
}

registry.category("fields").add("scheduling_toggle", SchedulingToggleField);
