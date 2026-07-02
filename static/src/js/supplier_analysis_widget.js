/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useColManager } from "./column_manager";

const SUP_COLS = [
    { key: 'partner_name',     label: 'Proveedor',     width: 160, sortKey: 'partner_name',     title: 'Nombre del proveedor.' },
    { key: 'supplier_cat',     label: 'Cat.',           width: 45,  sortKey: 'supplier_cat',     align: 'center', title: 'Categoría de proveedor A–E calculada según el método configurado.' },
    { key: 'order_count',      label: 'OCs',           width: 55,  sortKey: 'order_count',      align: 'end', title: 'OCs confirmadas en el período.' },
    { key: 'distinct_products',label: 'Artículos',     width: 65,  sortKey: 'distinct_products', align: 'end', title: 'Artículos distintos comprados.' },
    { key: 'total_amount',     label: 'Monto',         width: 100, sortKey: 'total_amount',      align: 'end', title: 'Suma del monto total de OCs confirmadas.' },
    { key: 'on_time_pct',      label: '% A tiempo',    width: 80,  sortKey: 'on_time_pct',       align: 'center', title: '% recepciones completadas en fecha.' },
    { key: 'avg_delay_days',   label: 'Retraso (d)',   width: 80,  sortKey: 'avg_delay_days',    align: 'center', title: 'Promedio de días de retraso en recepciones tardías.' },
    { key: 'complete_pct',     label: '% Completas',   width: 85,  sortKey: 'complete_pct',      align: 'center', title: '% recepciones completadas sin backorder.' },
    { key: 'avg_lead_time',    label: 'Lead time (d)', width: 80,  sortKey: 'avg_lead_time',     align: 'center', title: 'Lead time real promedio: días entre aprobación y recepción.' },
    { key: 'avg_price_var_pct',label: 'Var. precio',   width: 80,  sortKey: 'avg_price_var_pct', align: 'center', title: 'Variación promedio de precio OC vs costo estándar.' },
    { key: 'pending_inv',      label: 'Fact. pend.',   width: 100, sortKey: 'pending_inv',       align: 'end', title: 'Facturas de proveedor pendientes de pago.' },
];

function firstOfYearYMD() {
    return `${new Date().getFullYear()}-01-01`;
}

function todayYMD() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

class SupplierAnalysisWidget extends Component {
    static template = "odoo_mrp_planner.SupplierAnalysisWidget";
    static props = { record: { type: Object }, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:            true,
            periodFrom:         firstOfYearYMD(),
            periodTo:           todayYMD(),
            search:             '',
            sortCol:            'total_amount',
            sortDir:            'desc',
            page:               1,
            pageSize:           20,
            data:               null,
            expandedSuppliers:  {},
            posLoading:         {},
            posBySupplier:      {},
        });

        this.colsSup = useColManager('supplier_analysis', SUP_COLS);

        onMounted(() => this._load());
    }

    onHeaderClick(ev) {
        const sortKey = ev.currentTarget.dataset.sortKey;
        if (sortKey) this.setSort(sortKey);
    }

    async _load() {
        this.state.loading = true;
        this.state.expandedSuppliers = {};
        this.state.posBySupplier     = {};
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_supplier_analysis_data",
                [this.state.periodFrom, this.state.periodTo, ''],
            );
            this.state.data = d;
            this.state.page = 1;
        } catch(e) {
            console.error("[SupplierAnalysis]", e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Filtros de período ─────────────────────────────────────────────────────

    onPeriodFromChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodFrom = val;
        if (this.state.periodFrom > this.state.periodTo)
            this.state.periodTo = this.state.periodFrom;
        this._load();
    }

    onPeriodToChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodTo = val;
        if (this.state.periodTo < this.state.periodFrom)
            this.state.periodFrom = this.state.periodTo;
        this._load();
    }

    // ── Búsqueda reactiva (client-side) ───────────────────────────────────────

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page   = 1;
    }

    // ── Sort ──────────────────────────────────────────────────────────────────

    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortCol = col;
            this.state.sortDir = col === 'partner_name' ? 'asc' : 'desc';
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
        let rows = [...this.state.data.rows];
        // Filtro client-side
        if (this.state.search) {
            const q = this.state.search.toLowerCase();
            rows = rows.filter(r => r.partner_name.toLowerCase().includes(q));
        }
        const col = this.state.sortCol;
        const dir = this.state.sortDir === 'asc' ? 1 : -1;
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

    get tableColspan() {
        return this.colsSup.visibleCols().filter(
            c => c.key !== 'pending_inv' || (this.state.data && this.state.data.has_invoices)
        ).length;
    }

    get supVisibleCols() {
        return this.colsSup.visibleCols().filter(c => {
            if (c.key === 'pending_inv') return this.state.data && this.state.data.has_invoices;
            if (c.key === 'supplier_cat') return this.state.data && this.state.data.show_supplier_cat;
            return true;
        });
    }

    catBadgeClass(cat) {
        const map = { A: 'text-bg-success', B: 'text-bg-primary', C: 'text-bg-warning text-dark', D: 'text-bg-secondary', E: 'text-bg-danger' };
        return map[cat] || 'text-bg-secondary';
    }

    // ── Acordeón de OCs ───────────────────────────────────────────────────────

    async toggleAccordion(row) {
        const pid = row.partner_id;
        const wasOpen = !!this.state.expandedSuppliers[pid];
        this.state.expandedSuppliers = { ...this.state.expandedSuppliers, [pid]: !wasOpen };
        if (!wasOpen && !this.state.posBySupplier[pid]) {
            this.state.posLoading = { ...this.state.posLoading, [pid]: true };
            try {
                const pos = await this.orm.call(
                    'mrp.planner.dashboard',
                    'get_supplier_pos_for_analysis',
                    [pid, this.state.periodFrom, this.state.periodTo],
                );
                this.state.posBySupplier = { ...this.state.posBySupplier, [pid]: pos };
            } catch(e) {
                console.error('[SupplierAnalysis] accordion error', e);
                this.state.posBySupplier = { ...this.state.posBySupplier, [pid]: [] };
            } finally {
                this.state.posLoading = { ...this.state.posLoading, [pid]: false };
            }
        }
    }

    receiptBadge(status) {
        const map = {
            full:    'badge bg-success',
            partial: 'badge bg-warning text-dark',
            pending: 'badge bg-secondary',
            none:    'badge bg-light text-muted border',
        };
        return map[status] || 'badge bg-light';
    }

    receiptLabel(status) {
        const map = { full: 'Completa', partial: 'Parcial', pending: 'Pendiente', none: 'Sin recepción' };
        return map[status] || status;
    }

    // ── Formateo / clases ─────────────────────────────────────────────────────

    _cfg() { return (this.state.data && this.state.data.config) || {}; }

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
        const cfg = this._cfg();
        const green = cfg.sup_on_time_green ?? 90;
        const yellow = cfg.sup_on_time_yellow ?? 70;
        if (v >= green) return 'text-success fw-semibold';
        if (v >= yellow) return 'text-warning fw-semibold';
        return 'text-danger fw-semibold';
    }

    delayCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const cfg = this._cfg();
        const green = cfg.sup_delay_green ?? 1;
        const yellow = cfg.sup_delay_yellow ?? 3;
        if (v <= green) return 'text-success';
        if (v <= yellow) return 'text-warning';
        return 'text-danger';
    }

    completeCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const cfg = this._cfg();
        const green = cfg.sup_complete_green ?? 95;
        const yellow = cfg.sup_complete_yellow ?? 80;
        if (v >= green) return 'text-success';
        if (v >= yellow) return 'text-warning';
        return 'text-danger';
    }

    priceVarCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const cfg = this._cfg();
        const green = cfg.sup_price_var_green ?? 3;
        const yellow = cfg.sup_price_var_yellow ?? 10;
        const abs = Math.abs(v);
        if (abs <= green) return 'text-success';
        if (abs <= yellow) return 'text-warning';
        return 'text-danger';
    }

    // ── Navegación ────────────────────────────────────────────────────────────

    openSupplier(ev, row) {
        ev.stopPropagation();
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'res.partner',
            res_id:    row.partner_id,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    openPO(ev, po) {
        ev.stopPropagation();
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'purchase.order',
            res_id:    po.po_id,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    openPOs(ev, row) {
        ev.stopPropagation();
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'purchase.order',
            views:     [[false, 'list'], [false, 'form']],
            target:    'current',
            domain:    [['partner_id', '=', row.partner_id],
                        ['state', 'in', ['purchase', 'done']],
                        ['date_approve', '>=', `${this.state.periodFrom} 00:00:00`],
                        ['date_approve', '<=', `${this.state.periodTo} 23:59:59`]],
        });
    }
}

registry.category("view_widgets").add("supplier_analysis_widget", {
    component: SupplierAnalysisWidget,
});
