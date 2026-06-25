/** @odoo-module */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class SheetSelectorField extends Component {
    static template = "odoo_mrp_planner.SheetSelectorField";
    static props = { ...standardFieldProps };

    get sheets() {
        const raw = this.props.record.data.sheet_names_hint;
        if (!raw) return [];
        try { return JSON.parse(raw); } catch { return []; }
    }

    onChange(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }
}

registry.category("fields").add("sheet_selector", SheetSelectorField);
