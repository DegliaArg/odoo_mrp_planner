/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

function todayYM() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function firstOfYear() {
    return `${new Date().getFullYear()}-01`;
}

class SupplierAnalysisWidget extends Component {
    static template = "odoo_mrp_planner.SupplierAnalysisWidget";
    static props = { record: { type: Object }, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:    true,
            periodFrom: firstOfYear(),
            periodTo:   todayYM(),
            search:     '',
            searchInput: '',
            sortCol:    'total_amount',
            sortDir:    'desc',
            page:       1,
            pageSize:   20,
            data:       null,
        });

        onMounted(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_supplier_analysis_data",
                [this.state.periodFrom, this.state.periodTo, this.state.search],
            );
            this.state.data = d;
            this.state.page = 1;
        } catch(e) {
            console.error("[SupplierAnalysis]", e);
        } finally {
            this.state.loading = false;
        }
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

    onSearchInput(ev) {
        this.state.searchInput = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key === 'Enter') this._applySearch();
    }

    _applySearch() {
        this.state.search = this.state.searchInput;
        this._load();
    }

    // ── Sort ──────────────────────────────────────────────────────────────────

    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortCol = col;
            this.state.sortDir = col === 'total_amount' ? 'desc' : 'asc';
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
        if (!this.state.data) return [];
        const rows = [...this.state.data.rows];
        const col  = this.state.sortCol;
        const dir  = this.state.sortDir === 'asc' ? 1 : -1;
        rows.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === 'string') return dir * va.localeCompare(vb, 'es', { sensitivity: 'base' });
            va = va ?? (this.state.sortDir === 'asc' ? Infinity : -Infinity);
            vb = vb ?? (this.state.sortDir === 'asc' ? Infinity : -Infinity);
            return dir * (va - vb);
        });
        return rows;
    }

    // ── Paginación ────────────────────────────────────────────────────────────

    get pagedRows() {
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.sortedRows.slice(start, start + this.state.pageSize);
    }

    get totalPages()  { return Math.max(1, Math.ceil(this.sortedRows.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    // ── Formateo / clases ─────────────────────────────────────────────────────

    get periodFromDate() { return `${this.state.periodFrom}-01`; }
    get periodToDate() {
        const [y, m] = this.state.periodTo.split('-').map(Number);
        const last = new Date(y, m, 0).getDate();
        return `${this.state.periodTo}-${String(last).padStart(2, '0')}`;
    }

    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n);
    }

    fmtMoney(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(n);
    }

    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return `${n > 0 ? '+' : ''}${n}%`;
    }

    onTimeCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        if (v >= 90) return 'text-success fw-semibold';
        if (v >= 70) return 'text-warning fw-semibold';
        return 'text-danger fw-semibold';
    }

    delayCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        if (v <= 1) return 'text-success';
        if (v <= 3) return 'text-warning';
        return 'text-danger';
    }

    completeCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        if (v >= 95) return 'text-success';
        if (v >= 80) return 'text-warning';
        return 'text-danger';
    }

    priceVarCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const abs = Math.abs(v);
        if (abs <= 3)  return 'text-success';
        if (abs <= 10) return 'text-warning';
        return 'text-danger';
    }

    // ── Navegación ────────────────────────────────────────────────────────────

    openSupplier(row) {
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'res.partner',
            res_id:    row.partner_id,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    openPOs(row) {
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'purchase.order',
            views:     [[false, 'list'], [false, 'form']],
            target:    'current',
            domain:    [['partner_id', '=', row.partner_id],
                        ['state', 'in', ['purchase', 'done']],
                        ['date_approve', '>=', this.periodFromDate],
                        ['date_approve', '<=', this.periodToDate]],
        });
    }
}

registry.category("view_widgets").add("supplier_analysis_widget", {
    component: SupplierAnalysisWidget,
});
