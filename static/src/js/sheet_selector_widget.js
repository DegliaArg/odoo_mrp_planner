/** @odoo-module */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

class SheetSelectorWidget extends Component {
    static template = "odoo_mrp_planner.SheetSelectorWidget";
    static props = {
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
    };

    get sheets() {
        const raw = this.props.record.data.sheet_names_hint;
        if (!raw) return [];
        try { return JSON.parse(raw); } catch { return []; }
    }

    onChange(ev) {
        this.props.record.update({ sheet_name: ev.target.value });
    }
}

registry.category("view_widgets").add("sheet_selector", SheetSelectorWidget);
