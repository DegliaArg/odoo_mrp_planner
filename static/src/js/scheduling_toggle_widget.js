/** @odoo-module **/

import { registry } from "@web/core/registry";
import { BooleanToggleField } from "@web/views/fields/boolean_toggle/boolean_toggle_field";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

class SchedulingToggleField extends BooleanToggleField {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }

    onChange(ev) {
        const newVal = ev.target.checked;
        if (!newVal && this.props.record.data[this.props.name]) {
            // Desactivando → pedir confirmación antes de guardar
            ev.preventDefault();
            ev.stopPropagation();
            this.dialog.add(ConfirmationDialog, {
                title: "Desactivar programación",
                body: "Al desactivar la programación se eliminarán los permisos de Programación de todos los usuarios. ¿Confirmar?",
                confirmLabel: "Sí, desactivar",
                cancelLabel: "Cancelar",
                confirm: () => {
                    this.props.record.update({ [this.props.name]: false });
                },
                cancel: () => {},
            });
        } else {
            super.onChange(ev);
        }
    }
}

registry.category("fields").add("scheduling_toggle", SchedulingToggleField);
