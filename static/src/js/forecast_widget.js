/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PlannerSearchBar } from "./planner_search_bar";

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
    static components = { PlannerSearchBar };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        const now = todayYM();
        this.state = useState({
            loading:            true,
            periodFrom:         now,
            periodTo:           addMonths(now, 2),
            warehouseIds:       [],
            warehouses:         [],
            whDropdownOpen:     false,
            whSearch:           "",
            productSearch:      "",
            colsDropdownOpen:   false,
            filterDropdownOpen: false,
            groupDropdownOpen:  false,
            activeFilter:       null,
            groupBy:            null,
            selectedGroup:      null,
            visibleCols: {
                forecast:      true,
                mos:           true,
                delivered:     true,
                stock:         true,
                rotation:      true,
                total:         true,
                saleCategory:  false,
                productCateg:  false,
                productTypes:  false,
            },
            sortCol:          'product',
            sortDir:          'asc',
            page:             1,
            pageSize:         50,
            data:             null,
            canEdit:          true,
            expandedProducts: {},
            mosByProduct:     {},
            mosLoading:       {},
        });

        this._closeAll = () => {
            this.state.whDropdownOpen     = false;
            this.state.whSearch           = "";
            this.state.colsDropdownOpen   = false;
            this.state.filterDropdownOpen = false;
            this.state.groupDropdownOpen  = false;
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
        this.state.loading      = true;
        this.state.page         = 1;
        this.state.mosByProduct = {};
        this.state.expandedProducts = {};
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

    setSearch(text) {
        this.state.productSearch = text;
        this.state.page = 1;
    }

    toggleWhDropdown(ev) {
        ev.stopPropagation();
        const opening = !this.state.whDropdownOpen;
        this.state.whDropdownOpen     = opening;
        this.state.colsDropdownOpen   = false;
        this.state.filterDropdownOpen = false;
        this.state.groupDropdownOpen  = false;
        if (opening) this.state.whSearch = "";
    }

    toggleColsDropdown(ev) {
        ev.stopPropagation();
        this.state.colsDropdownOpen   = !this.state.colsDropdownOpen;
        this.state.whDropdownOpen     = false;
        this.state.whSearch           = "";
        this.state.filterDropdownOpen = false;
        this.state.groupDropdownOpen  = false;
    }

    toggleFilterDropdown(ev) {
        ev.stopPropagation();
        this.state.filterDropdownOpen = !this.state.filterDropdownOpen;
        this.state.colsDropdownOpen   = false;
        this.state.whDropdownOpen     = false;
        this.state.whSearch           = "";
        this.state.groupDropdownOpen  = false;
    }

    toggleGroupDropdown(ev) {
        ev.stopPropagation();
        this.state.groupDropdownOpen  = !this.state.groupDropdownOpen;
        this.state.colsDropdownOpen   = false;
        this.state.whDropdownOpen     = false;
        this.state.whSearch           = "";
        this.state.filterDropdownOpen = false;
    }

    toggleCol(colKey) {
        this.state.visibleCols[colKey] = !this.state.visibleCols[colKey];
    }

    setFilter(key) {
        this.state.activeFilter = key;
        this.state.page = 1;
    }

    setGroupBy(key) {
        this.state.groupBy = key;
        this.state.page = 1;
        if (key) {
            const groups = this.allGroupsForTabs;
            this.state.selectedGroup = (groups && groups.length) ? groups[0].key : null;
        } else {
            this.state.selectedGroup = null;
        }
    }

    setGroup(key) {
        this.state.selectedGroup = key;
        this.state.page = 1;
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

    get tableColspan() {
        const n = this.state.data ? this.state.data.months.length : 0;
        let cols = 1;
        if (this.state.visibleCols.saleCategory)  cols++;
        if (this.state.visibleCols.productCateg)  cols++;
        if (this.state.visibleCols.productTypes)  cols++;
        if (this.state.visibleCols.stock)         cols++;
        if (this.state.visibleCols.rotation)      cols++;
        cols += n * this.monthColspan;
        if (this.showTotal) cols += this.totalColspan;
        return cols;
    }

    // ── Sort ──────────────────────────────────────────────────────────────────

    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortCol = col;
            this.state.sortDir = 'asc';
        }
        this.state.page = 1;
    }

    sortIcon(col) {
        if (this.state.sortCol !== col) return 'fa fa-sort text-muted ms-1';
        return this.state.sortDir === 'asc'
            ? 'fa fa-sort-asc text-primary ms-1'
            : 'fa fa-sort-desc text-primary ms-1';
    }

    get sortedRows() {
        const rows = [...this.filteredRowsAll];
        const col  = this.state.sortCol;
        const dir  = this.state.sortDir === 'asc' ? 1 : -1;
        rows.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === 'string') {
                if (!va && vb) return dir;   // empty strings at end in both directions
                if (va && !vb) return -dir;
                return dir * va.localeCompare(vb, 'es', { sensitivity: 'base' });
            }
            va = va ?? -Infinity;
            vb = vb ?? -Infinity;
            return dir * (va - vb);
        });
        return rows;
    }

    // ── Filtrado + paginación ─────────────────────────────────────────────────

    get baseFilteredRows() {
        if (!this.state.data || !this.state.data.rows) return [];
        let rows = this.state.data.rows;
        const q = this.state.productSearch.toLowerCase();
        if (q) rows = rows.filter(r => r.product.toLowerCase().includes(q));
        const f = this.state.activeFilter;
        if (f === 'with_mos') rows = rows.filter(r => r.total_mos > 0);
        if (f === 'no_mos')   rows = rows.filter(r => r.total_mos === 0);
        if (f === 'gap')      rows = rows.filter(r => r.total_forecast > 0 && r.total_mos < r.total_forecast);
        return rows;
    }

    get filteredRowsAll() {
        let rows = this.baseFilteredRows;
        const gb = this.state.groupBy;
        if (gb && this.state.selectedGroup !== null) {
            rows = rows.filter(r => (r[gb] || '') === this.state.selectedGroup);
        }
        return rows;
    }

    get filteredRows() {
        const all   = this.sortedRows;
        const start = (this.state.page - 1) * this.state.pageSize;
        return all.slice(start, start + this.state.pageSize);
    }

    get totalPages()  { return Math.max(1, Math.ceil(this.filteredRowsAll.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    // ── Agrupación / tabs ─────────────────────────────────────────────────────

    get allGroupsForTabs() {
        const gb = this.state.groupBy;
        if (!gb) return null;
        const counts = new Map();
        for (const row of this.baseFilteredRows) {
            const key = row[gb] || '';
            counts.set(key, (counts.get(key) || 0) + 1);
        }
        let entries = [...counts.entries()];
        if (gb === 'sale_category') {
            const CAT_ORDER = ['A', 'B', 'C', 'D', 'E', ''];
            entries.sort((a, b) => {
                const ia = CAT_ORDER.indexOf(a[0]);
                const ib = CAT_ORDER.indexOf(b[0]);
                return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
            });
        } else {
            entries.sort((a, b) => a[0].localeCompare(b[0], 'es', { sensitivity: 'base' }));
        }
        return entries.map(([key, count]) => ({ key, label: key || 'Sin categoría', count }));
    }

    get tableItems() {
        return this.filteredRows.map(r => ({ ...r, _type: 'row' }));
    }

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

    // ── Navegación ────────────────────────────────────────────────────────────

    openProduct(row) {
        this.action.doAction({
            type:    'ir.actions.act_window',
            res_model: 'product.template',
            res_id:  row.product_tmpl_id,
            views:   [[false, 'form']],
            target:  'current',
        });
    }

    openMo(moId) {
        this.action.doAction({
            type:    'ir.actions.act_window',
            res_model: 'mrp.production',
            res_id:  moId,
            views:   [[false, 'form']],
            target:  'current',
        });
    }

    // ── Acordeón de OFs ───────────────────────────────────────────────────────

    async toggleAccordion(row) {
        if (!row.total_mos) return;
        const pid = row.product_id;
        const wasOpen = !!this.state.expandedProducts[pid];
        this.state.expandedProducts[pid] = !wasOpen;
        if (!wasOpen && !this.state.mosByProduct[pid]) {
            this.state.mosLoading[pid] = true;
            try {
                const mos = await this.orm.call(
                    'mrp.planner.dashboard',
                    'get_product_mos_for_forecast',
                    [pid, this.state.periodFrom, this.state.periodTo, this.state.warehouseIds],
                );
                this.state.mosByProduct[pid] = mos;
            } catch (e) {
                console.error('[ForecastWidget] accordion error', e);
                this.state.mosByProduct[pid] = [];
            } finally {
                this.state.mosLoading[pid] = false;
            }
        }
    }

    moStateBadge(state) {
        const map = {
            draft:     'bg-secondary',
            confirmed: 'bg-info text-dark',
            progress:  'bg-primary',
            to_close:  'bg-warning text-dark',
            done:      'bg-success',
            cancel:    'bg-light text-muted',
        };
        return `badge ${map[state] || 'bg-secondary'}`;
    }

    saleCatBadge(cat) {
        const map = {
            A: 'bg-success text-white',
            B: 'bg-info text-dark',
            C: 'bg-warning text-dark',
            D: 'bg-secondary text-white',
            E: 'bg-light text-muted border',
        };
        return `badge ${map[cat] || 'bg-light text-muted'}`;
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
        const formula = this.state.data && this.state.data.acc_formula;
        if (formula === 'bias') {
            const abs = Math.abs(acc);
            if (abs <= 10) return 'text-success';
            if (abs <= 20) return 'text-warning';
            return 'text-danger';
        }
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

    moTooltip(cell) {
        if (!cell || cell.forecast === 0) return '';
        return `Cobertura OF = ${this.fmt(cell.mos)} OFs ÷ ${this.fmt(cell.forecast)} forecast × 100 = ${this.fmtPct(cell.pct)}`;
    }

    svcTooltip(cell) {
        if (cell.service_rate === null || cell.service_rate === undefined)
            return 'Sin pedidos de venta confirmados en el período';
        return `Tasa de servicio = ${this.fmt(cell.delivered)} entregado ÷ ${this.fmt(cell.so_demand)} pedidos × 100 = ${this.fmtPct(cell.service_rate)}`;
    }

    rotTooltip(row) {
        const n = this.state.data ? this.state.data.months.length : 1;
        if (!row.total_delivered) return 'Sin entregas en el período — rotación no calculable';
        const unit  = this.state.data && this.state.data.rotation_unit;
        const val   = this.fmtRotation(row);
        return `Rotación = ${this.fmt(row.stock_qty)} stock ÷ (${this.fmt(row.total_delivered)} entregado ÷ ${n} meses)${unit !== 'months' ? ' × 30' : ''} = ${val}`;
    }

    accGlobalTooltip() {
        const d = this.state.data;
        if (!d) return '';
        const formula = d.acc_formula;
        const del = this.fmt(d.kpis.total_delivered), fc = this.fmt(d.kpis.total_forecast);
        const val = this.fmtPct(d.kpis.overall_forecast_acc);
        if (formula === 'mape')
            return `MAPE global = promedio de precisiones por artículo = ${val}`;
        if (formula === 'wape')
            return `WAPE global = 100 − (Σ|errores| ÷ ${del} entregado × 100) = ${val}`;
        if (formula === 'wmape')
            return `WMAPE global = 100 − (Σ|errores| ÷ ${fc} forecast × 100) = ${val}`;
        if (formula === 'bias')
            return `Sesgo global = (${del} − ${fc}) ÷ ${fc} × 100 = ${val}`;
        return `Precisión global = ${del} entregado ÷ ${fc} forecast × 100 = ${val}`;
    }

    accTooltip(row) {
        const a = row.acc_all;
        if (!a) return 'Sin datos suficientes para calcular precisión';
        const configured = (this.state.data && this.state.data.acc_formula) || 'simple';
        const fv = v => v !== null && v !== undefined ? `${v}%` : '—';
        const mark = key => key === configured ? ' ◀' : '';
        return [
            `Simple:  ${fv(a.simple)}${mark('simple')}`,
            `MAPE:    ${fv(a.mape)}${mark('mape')}`,
            `WAPE:    ${fv(a.wape)}${mark('wape')}`,
            `WMAPE:   ${fv(a.wmape)}${mark('wmape')}`,
            `Sesgo:   ${fv(a.bias)}${mark('bias')}`,
        ].join('\n');
    }

    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n);
    }

    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return `${Math.round(n)}%`;
    }

    fmtDate(d) {
        if (!d) return '—';
        const [y, m, day] = d.split('-');
        return `${day}/${m}/${y}`;
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
