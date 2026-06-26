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
            visibleCols: {
                forecast:  true,
                mos:       true,
                delivered: true,
                stock:     true,
                rotation:  true,
                total:     true,
            },
            page:     1,
            pageSize: 20,
            data:     null,
            canEdit:  true,
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
        this.state.page    = 1;
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

    get periodFromDate() { return `${this.state.periodFrom}-01`; }
    get periodToDate() {
        const last = ymLastDay(this.state.periodTo);
        return `${this.state.periodTo}-${String(last).padStart(2, '0')}`;
    }

    onPeriodFromChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodFrom = val.substring(0, 7);
        if (this.state.periodFrom > this.state.periodTo)
            this.state.periodTo = this.state.periodFrom;
        this._load();
    }

    onPeriodToChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodTo = val.substring(0, 7);
        if (this.state.periodTo < this.state.periodFrom)
            this.state.periodFrom = this.state.periodTo;
        this._load();
    }

    onProductSearchInput(ev) {
        this.state.productSearch = ev.target.value;
        this.state.page = 1;
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

    // ── Columnas ─────────────────────────────────────────────────────────────

    get monthColspan() {
        let n = 0;
        if (this.state.visibleCols.forecast)  n++;
        if (this.state.visibleCols.mos)       n++;
        if (this.state.visibleCols.delivered) n++;
        return n || 1;
    }

    get showForecastAcc() {
        return this.state.visibleCols.total &&
               this.state.visibleCols.forecast &&
               this.state.visibleCols.delivered;
    }

    get totalColspan() {
        return this.monthColspan + (this.showForecastAcc ? 1 : 0);
    }

    get showTotal() {
        return this.state.visibleCols.total &&
               (this.state.visibleCols.forecast ||
                this.state.visibleCols.mos      ||
                this.state.visibleCols.delivered);
    }

    // ── Filtrado + paginación ─────────────────────────────────────────────────

    get filteredRowsAll() {
        if (!this.state.data || !this.state.data.rows) return [];
        const q = this.state.productSearch.toLowerCase();
        if (!q) return this.state.data.rows;
        return this.state.data.rows.filter(r => r.product.toLowerCase().includes(q));
    }

    get filteredRows() {
        const all   = this.filteredRowsAll;
        const start = (this.state.page - 1) * this.state.pageSize;
        return all.slice(start, start + this.state.pageSize);
    }

    get totalPages()  { return Math.max(1, Math.ceil(this.filteredRowsAll.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    // ── Depósito ──────────────────────────────────────────────────────────────

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

    // ── Formateo / clases ─────────────────────────────────────────────────────

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

    svcClass(rate) {
        if (rate === null || rate === undefined) return 'text-muted';
        if (rate >= 95) return 'text-success';
        if (rate >= 80) return 'text-warning';
        return 'text-danger';
    }

    accClass(acc) {
        if (acc === null || acc === undefined) return 'text-muted';
        if (acc >= 90) return 'text-success';
        if (acc >= 70) return 'text-warning';
        return 'text-danger';
    }

    fmtRotation(row) {
        const unit = this.state.data && this.state.data.rotation_unit;
        if (unit === 'months') {
            const v = row.rotation_months;
            return v !== null && v !== undefined ? `${v} m` : '—';
        }
        const v = row.rotation_days;
        return v !== null && v !== undefined ? `${v} d` : '—';
    }

    rotClass(row) {
        const unit = this.state.data && this.state.data.rotation_unit;
        const v = unit === 'months' ? row.rotation_months : row.rotation_days;
        if (v === null || v === undefined) return 'text-muted';
        const threshold = unit === 'months' ? 3 : 90;
        return v <= threshold ? 'text-success' : v <= threshold * 2 ? 'text-warning' : 'text-muted';
    }

    // Tooltip dinámico para la celda de OFs
    moTooltip(cell) {
        if (!cell || cell.forecast === 0) return '';
        return `Cobertura OF = ${this.fmt(cell.mos)} OFs ÷ ${this.fmt(cell.forecast)} forecast × 100 = ${this.fmtPct(cell.pct)}`;
    }

    // Tooltip dinámico para la celda de Entregado
    svcTooltip(cell) {
        if (cell.service_rate === null || cell.service_rate === undefined)
            return 'Sin pedidos de venta confirmados en el período';
        return `Tasa de servicio = ${this.fmt(cell.delivered)} entregado ÷ ${this.fmt(cell.so_demand)} pedidos × 100 = ${this.fmtPct(cell.service_rate)}`;
    }

    // Tooltip dinámico para la celda de rotación
    rotTooltip(row) {
        const n = this.state.data ? this.state.data.months.length : 1;
        if (!row.total_delivered) return 'Sin entregas en el período — rotación no calculable';
        const unit  = this.state.data && this.state.data.rotation_unit;
        const label = unit === 'months' ? 'meses' : 'días';
        const val   = this.fmtRotation(row);
        return `Rotación = ${this.fmt(row.stock_qty)} stock ÷ (${this.fmt(row.total_delivered)} entregado ÷ ${n} meses)${unit !== 'months' ? ' × 30' : ''} = ${val} ${label}`;
    }

    // Tooltip para precisión forecast por artículo
    accTooltip(row) {
        if (row.total_forecast_acc === null || row.total_forecast_acc === undefined)
            return 'Sin datos suficientes para calcular precisión';
        return `Precisión forecast = ${this.fmt(row.total_delivered)} entregado ÷ ${this.fmt(row.total_forecast)} forecast × 100 = ${this.fmtPct(row.total_forecast_acc)}`;
    }

    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n);
    }

    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return `${Math.round(n)}%`;
    }

    // ── Acciones ──────────────────────────────────────────────────────────────

    async openImport() {
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
