/** @odoo-module **/

import { Component, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

class SchedulingToggleField extends Component {
    static template = "odoo_mrp_planner.SchedulingToggleField";
    static props = { "*": true };

    setup() {
        this.checkboxRef = useRef("checkbox");
        this.dialogService = useService("dialog");
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    onChange(ev) {
        const newVal = ev.target.checked;
        if (!newVal && this.value) {
            ev.preventDefault();
            ev.stopPropagation();
            this.dialogService.add(ConfirmationDialog, {
                title: "Desactivar programación",
                body: "Al desactivar la programación se eliminarán los permisos de Programación de todos los usuarios. ¿Confirmar?",
                confirmLabel: "Desactivar",
                cancelLabel: "Cancelar",
                confirm: () => {
                    this.props.record.update({ [this.props.name]: false });
                },
                cancel: () => {
                    if (this.checkboxRef.el) {
                        this.checkboxRef.el.checked = true;
                    }
                },
            });
        } else {
            this.props.record.update({ [this.props.name]: newVal });
        }
    }
}

registry.category("fields").add("scheduling_toggle", { component: SchedulingToggleField });
