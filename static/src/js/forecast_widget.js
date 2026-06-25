/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

function monthLabel(ym) {
    // ym = "2025-07"
    const [y, m] = ym.split('-');
    return `${MONTHS_ES[parseInt(m) - 1]} ${y}`;
}

function todayYM() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function addMonths(ym, n) {
    const [y, m] = ym.split('-').map(Number);
    const d = new Date(y, m - 1 + n, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

class ForecastWidget extends Component {
    static template = "odoo_mrp_planner.ForecastWidget";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        const now = todayYM();
        this.state = useState({
            loading:         true,
            periodFrom:      now,
            periodTo:        addMonths(now, 2),
            warehouseIds:    [],
            warehouses:      [],
            whDropdownOpen:  false,
            data:            null,
            canEdit:         true,
        });

        this._closeWhDropdown = () => { this.state.whDropdownOpen = false; };

        onMounted(() => {
            this._init();
            document.addEventListener('click', this._closeWhDropdown);
        });
        onWillUnmount(() => {
            document.removeEventListener('click', this._closeWhDropdown);
        });
    }

    async _init() {
        const [whs] = await Promise.all([
            this.orm.call("mrp.planner.dashboard", "get_warehouses_for_forecast", []),
            this._load(),
        ]);
        this.state.warehouses = whs;
        const rec = this.props.record;
        if (rec && rec.data) {
            this.state.canEdit = rec.data.can_edit_forecast;
        }
    }

    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_forecast_dashboard_data",
                [this.state.periodFrom, this.state.periodTo, this.state.warehouseIds],
            );
            this.state.data = d;
        } catch (e) {
            console.error("[ForecastWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    onPeriodFromChange(ev) {
        this.state.periodFrom = ev.target.value;
        if (this.state.periodFrom > this.state.periodTo) {
            this.state.periodTo = this.state.periodFrom;
        }
        this._load();
    }

    onPeriodToChange(ev) {
        this.state.periodTo = ev.target.value;
        if (this.state.periodTo < this.state.periodFrom) {
            this.state.periodFrom = this.state.periodTo;
        }
        this._load();
    }

    toggleWhDropdown(ev) {
        ev.stopPropagation();
        this.state.whDropdownOpen = !this.state.whDropdownOpen;
    }

    toggleWarehouse(ev) {
        const id = parseInt(ev.target.dataset.whId);
        const ids = this.state.warehouseIds;
        if (ids.includes(id)) {
            this.state.warehouseIds = ids.filter(i => i !== id);
        } else {
            this.state.warehouseIds = [...ids, id];
        }
        this._load();
    }

    clearWhFilter() {
        this.state.warehouseIds = [];
        this._load();
    }

    get selectedWhLabel() {
        const ids = this.state.warehouseIds;
        if (!ids.length) return 'Todos los depósitos';
        if (ids.length === 1) {
            const wh = this.state.warehouses.find(w => w.id === ids[0]);
            return wh ? wh.name : '1 seleccionado';
        }
        return `${ids.length} depósitos`;
    }

    get monthLabels() {
        if (!this.state.data) return [];
        return this.state.data.months.map(monthLabel);
    }

    cellClass(cell) {
        if (!cell || cell.forecast === 0) return '';
        const pct = cell.pct;
        const d = this.state.data;
        if (!d) return '';
        if (pct >= 100) return 'forecast-ok';
        if (pct >= d.warning_pct) return 'forecast-warning';
        return 'forecast-critical';
    }

    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n);
    }

    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return `${Math.round(n)}%`;
    }

    async openImport() {
        await this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.forecast.import.wizard",
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "new",
        });
        this._load();
    }

    openForecastList() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.forecast.line",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            target:    "current",
        });
    }

    async downloadExport() {
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard",
                "get_forecast_export",
                [this.state.periodFrom, this.state.periodTo, this.state.warehouseIds],
            );
            if (res && res.url) {
                window.open(res.url, '_blank');
            }
        } catch (e) {
            console.error("[ForecastWidget] export error", e);
        }
    }
}

registry.category("view_widgets").add("forecast_widget", {
    component: ForecastWidget,
});
