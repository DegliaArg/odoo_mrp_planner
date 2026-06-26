/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

function monthLabel(ym) {
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

function ymLastDay(ym) {
    const [y, m] = ym.split('-').map(Number);
    return new Date(y, m, 0).getDate();
}

class ForecastWidget extends Component {
    static template = "odoo_mrp_planner.ForecastWidget";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        const now = todayYM();
        this.state = useState({
            loading:          true,
            periodFrom:       now,
            periodTo:         addMonths(now, 2),
            warehouseIds:     [],
            warehouses:       [],
            whDropdownOpen:   false,
            whSearch:         "",
            productSearch:    "",
            colsDropdownOpen: false,
            visibleCols:      { forecast: true, mos: true, total: true },
            data:             null,
            canEdit:          true,
        });

        this._closeAll = () => {
            this.state.whDropdownOpen   = false;
            this.state.whSearch         = "";
            this.state.colsDropdownOpen = false;
        };

        onMounted(() => {
            this._init();
            document.addEventListener('click', this._closeAll);
        });
        onWillUnmount(() => {
            document.removeEventListener('click', this._closeAll);
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

    // type="date" needs YYYY-MM-DD; state stores YYYY-MM
    get periodFromDate() { return `${this.state.periodFrom}-01`; }
    get periodToDate() {
        const last = ymLastDay(this.state.periodTo);
        return `${this.state.periodTo}-${String(last).padStart(2, '0')}`;
    }

    onPeriodFromChange(ev) {
        const val = ev.target.value; // YYYY-MM-DD
        if (!val) return;
        this.state.periodFrom = val.substring(0, 7); // YYYY-MM
        if (this.state.periodFrom > this.state.periodTo)
            this.state.periodTo = this.state.periodFrom;
        this._load();
    }

    onPeriodToChange(ev) {
        const val = ev.target.value; // YYYY-MM-DD
        if (!val) return;
        this.state.periodTo = val.substring(0, 7); // YYYY-MM
        if (this.state.periodTo < this.state.periodFrom)
            this.state.periodFrom = this.state.periodTo;
        this._load();
    }

    toggleWhDropdown(ev) {
        ev.stopPropagation();
        const opening = !this.state.whDropdownOpen;
        this.state.whDropdownOpen   = opening;
        this.state.colsDropdownOpen = false;
        if (opening) this.state.whSearch = "";
    }

    toggleColsDropdown(ev) {
        ev.stopPropagation();
        this.state.colsDropdownOpen = !this.state.colsDropdownOpen;
        this.state.whDropdownOpen   = false;
        this.state.whSearch         = "";
    }

    toggleCol(colKey) {
        this.state.visibleCols[colKey] = !this.state.visibleCols[colKey];
    }

    get monthColspan() {
        let n = 0;
        if (this.state.visibleCols.forecast) n++;
        if (this.state.visibleCols.mos) n++;
        return n || 1;
    }

    get showTotal() {
        return this.state.visibleCols.total &&
               (this.state.visibleCols.forecast || this.state.visibleCols.mos);
    }

    get filteredRows() {
        if (!this.state.data || !this.state.data.rows) return [];
        const q = this.state.productSearch.toLowerCase();
        if (!q) return this.state.data.rows;
        return this.state.data.rows.filter(r => r.product.toLowerCase().includes(q));
    }

    get filteredWarehouses() {
        const q = this.state.whSearch.toLowerCase();
        if (!q) return this.state.warehouses;
        return this.state.warehouses.filter(w => w.name.toLowerCase().includes(q));
    }

    toggleWarehouse(ev) {
        const id = parseInt(ev.target.dataset.whId);
        const ids = this.state.warehouseIds;
        this.state.warehouseIds = ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id];
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
        const d = this.state.data;
        if (!d) return '';
        if (cell.pct >= 100) return 'forecast-ok';
        if (cell.pct >= d.warning_pct) return 'forecast-warning';
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
        // Navigate to the forecast lines list where Odoo's native import button is available
        await this.action.doAction('odoo_mrp_planner.action_mrp_forecast_line');
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
            if (res && res.url) window.open(res.url, '_blank');
        } catch (e) {
            console.error("[ForecastWidget] export error", e);
        }
    }
}

registry.category("view_widgets").add("forecast_widget", {
    component: ForecastWidget,
});
