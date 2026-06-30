/** @odoo-module **/

/**
 * @description Widget de órdenes de compra, recepciones y entregas para el dashboard.
 *   Soporta filtrado por tab (all/purchase/subcontract), fecha, tipo de OC y subtab.
 *   Paginado y ordenamiento server-side.
 * @fires RPC mrp.planner.dashboard.get_po_dashboard_data — datos de OCs y movimientos
 *   Params: (tab, dateFrom, dateTo, sortField, sortDir, page, pageSize)
 *   @returns {{ kpis: KpiPo, rfqs: PoRow[], to_approve: PoRow[], overdue: PoRow[],
 *              all_pos: PoRow[], pending_pos: PoRow[], receipts: PickRow[],
 *              deliveries: PickRow[], services: ServiceRow[], show_services_tab: boolean }}
 * @listens onMounted — carga datos y sincroniza altura
 */

import { Component, useState, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useColManager } from "./column_manager";

const PO_OC_COLS = [
    { key: 'name',        label: 'Referencia',      width: 130, sortKey: 'name',        title: 'Número de la orden de compra.' },
    { key: 'partner',     label: 'Proveedor',        width: 200, sortKey: 'partner',     title: 'Proveedor de la orden de compra.' },
    { key: 'date_planned',label: 'Entrega estimada', width: 130, sortKey: 'date_planned',title: 'Fecha de entrega planificada (date_planned).' },
    { key: 'amount_total',label: 'Total',            width: 100, sortKey: 'amount_total', align: 'end', title: 'Importe total de la OC en moneda de la empresa.' },
];

const PO_RECEIPT_COLS = [
    { key: '_expand',       label: '',               width: 32,  fixed: true, noResize: true },
    { key: 'name',          label: 'Referencia',     width: 85,  sortKey: 'name',    title: 'Número del albarán.' },
    { key: 'po_name',       label: 'OC',             width: 85,  sortKey: 'po_name', title: 'Número de la orden de compra asociada.' },
    { key: 'partner',       label: 'Proveedor',      width: 140, sortKey: 'partner', title: 'Proveedor.' },
    { key: 'scheduled_date',label: 'Fecha prevista', width: 100, sortKey: 'scheduled_date', title: 'Fecha programada del movimiento de stock (scheduled_date).' },
    { key: 'overdue',       label: 'Estado',         width: 65,  sortKey: 'overdue', align: 'center', title: 'Días de retraso. +Nd = vencido hace N días.' },
];

const PO_PICK_COLS = [
    { key: '_expand',          label: '',                   width: 32,  fixed: true, noResize: true },
    { key: 'name',             label: 'Referencia',         width: 85,  sortKey: 'name',    title: 'Número del albarán.' },
    { key: 'po_name',          label: 'OC',                 width: 85,  sortKey: 'po_name', title: 'Número de la orden de compra asociada.' },
    { key: 'finished_product', label: 'Prod. terminado',    width: 110, sortKey: 'finished_product', title: 'Producto final a fabricar por el subcontratista (vía OF de subcontratación).' },
    { key: 'partner',          label: 'Proveedor',          width: 120, sortKey: 'partner', title: 'Proveedor o subcontratista.' },
    { key: 'scheduled_date',   label: 'Fecha prevista',     width: 100, sortKey: 'scheduled_date', title: 'Fecha programada del movimiento de stock (scheduled_date).' },
    { key: 'overdue',          label: 'Estado',             width: 65,  sortKey: 'overdue', align: 'center', title: 'Días de retraso. +Nd = vencido hace N días.' },
    { key: 'availability',     label: 'Disp.',              width: 80,  sortKey: 'availability', align: 'center', title: 'Disponible / Parcialmente / No disponible.' },
];

const PO_SVC_COLS = [
    { key: 'name',        label: 'Referencia',      width: 130, sortKey: 'name',        title: 'Número de la OC de servicio.' },
    { key: 'partner',     label: 'Proveedor',        width: 200, sortKey: 'partner',     title: 'Proveedor del servicio.' },
    { key: 'date_planned',label: 'Entrega estimada', width: 130, sortKey: 'date_planned',title: 'Fecha de entrega estimada del servicio.' },
    { key: 'amount_total',label: 'Total',            width: 100, sortKey: 'amount_total', align: 'end', title: 'Importe total de la OC de servicio.' },
];

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY_KPIS = {
    rfq: 0, to_approve: 0, total: 0, pending: 0, overdue: 0, overdue_critical: 0,
    receipts_total: 0, receipts_overdue: 0, deliveries_total: 0, deliveries_overdue: 0,
    services_total: 0, po_critical_days: 5,
};

class PoDashboardWidget extends Component {
    static template = "odoo_mrp_planner.PoDashboardWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this._root        = useRef("poRoot");
        this.colsOc       = useColManager('po_ocs',       PO_OC_COLS);
        this.colsReceipts = useColManager('po_receipts',  PO_RECEIPT_COLS);
        this.colsDeliveries= useColManager('po_deliveries', PO_PICK_COLS);
        this.colsSvc      = useColManager('po_services',  PO_SVC_COLS);

        const now          = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            tab:       "all",
            ocFilter:  "overdue",  // "all" | "pending" | "overdue" | "rfqs" | "approve"
            listTab:   null,       // null = OC mode | "receipts" | "deliveries" | "services"
            dateFrom:  toDateStr(firstOfMonth),
            dateTo:    toDateStr(lastOfMonth),
            loading:   true,
            sortField: null,
            sortDir:   "asc",
            page:      1,
            pageSize:  50,
            kpis:      { ...EMPTY_KPIS },
            rfqs:             [],
            to_approve:       [],
            overdue:          [],
            all_pos:          [],
            pending_pos:      [],
            receipts:         [],
            deliveries:       [],
            services:         [],
            show_services_tab: false,
            expandedIds: {},
        });

        onMounted(async () => {
            await this._load();
            requestAnimationFrame(() => this._syncH());
        });
    }

    /** @returns {Promise<void>} Carga datos desde el servidor y actualiza state */
    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_po_dashboard_data",
                [this.state.tab, this.state.dateFrom, this.state.dateTo,
                 this.state.sortField || null, this.state.sortDir,
                 this.state.page, this.state.pageSize],
            );
            this.state.kpis            = d.kpis;
            this.state.rfqs            = d.rfqs;
            this.state.to_approve      = d.to_approve;
            this.state.overdue         = d.overdue;
            this.state.all_pos         = d.all_pos    || [];
            this.state.pending_pos     = d.pending_pos || [];
            this.state.receipts        = d.receipts   || [];
            this.state.deliveries      = d.deliveries || [];
            this.state.services        = d.services   || [];
            this.state.show_services_tab = d.show_services_tab || false;
        } catch (e) {
            console.error("[PoDashboardWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    setTab(tab) {
        if (this.state.tab === tab) return;
        this.state.tab       = tab;
        this.state.listTab   = null;
        this.state.sortField = null;
        this.state.sortDir   = "asc";
        this.state.page      = 1;
        this._load().then(() => requestAnimationFrame(() => this._syncH()));
    }

    /** Iguala la altura del panel de tabla a la del panel de KPIs */
    _syncH() {
        const root = this._root.el;
        if (!root) return;
        const kpiEl   = root.querySelector('.o_kpi_height_src');
        const tableEl = root.querySelector('.o_table_scroll');
        if (!kpiEl || !tableEl) return;
        tableEl.style.height = '0';
        const h = kpiEl.offsetHeight;
        tableEl.style.height = Math.max(h, 150) + 'px';
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this.state.page = 1; this._load(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this.state.page = 1; this._load(); }

    onOcFilterChange(ev) {
        this.state.ocFilter  = ev.target.value;
        this.state.listTab   = null;
        this.state.sortField = null;
        this.state.sortDir   = "asc";
        this.state.page      = 1;
        this._load();
    }

    setListTab(tab) {
        if (this.state.listTab === tab) return;
        this.state.listTab   = tab;
        this.state.sortField = null;
        this.state.sortDir   = "asc";
        this.state.page      = 1;
        this._load();
    }

    _scDomain() {
        if (this.state.tab === "purchase")    return [["subcontract_production_ids", "=", false]];
        if (this.state.tab === "subcontract") return [["subcontract_production_ids", "!=", false]];
        return [];
    }

    _navigate(name, baseDomain) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name,
            res_model: "purchase.order",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            domain:    [...baseDomain, ...this._scDomain()],
            target:    "current",
        });
    }

    _dateDomain() {
        const d = [];
        if (this.state.dateFrom) d.push(["date_planned", ">=", this.state.dateFrom + " 00:00:00"]);
        if (this.state.dateTo)   d.push(["date_planned", "<=", this.state.dateTo   + " 23:59:59"]);
        return d;
    }

    onClickRfqs()      { this._navigate("Cotizaciones", [["state", "in", ["draft", "sent"]], ...this._dateDomain()]); }
    onClickToApprove() { this._navigate("Por aprobar",  [["state", "=", "to approve"],       ...this._dateDomain()]); }
    onClickAll()       { this._navigate("Aprobadas",    [["state", "=", "purchase"], ["receipt_status", "!=", "full"], ...this._dateDomain()]); }
    onClickPending() {
        const now = new Date().toISOString();
        this._navigate("A tiempo", [
            ["state", "=", "purchase"], ["receipt_status", "!=", "full"],
            ["date_planned", ">=", now], ...this._dateDomain(),
        ]);
    }
    onClickOverdue() {
        const now = new Date().toISOString();
        this._navigate("Vencidas", [
            ["state", "=", "purchase"], ["receipt_status", "!=", "full"],
            ["date_planned", "<", now], ...this._dateDomain(),
        ]);
    }

    /** @param {number|string} id — ID de la OC a abrir */
    openPo(id) {
        // FIX [FASE-3]: res_id abre el form directamente; domain+list_view era redundante
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "purchase.order",
            res_id:    parseInt(id),
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    openPoFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.poId;
        if (id) this.openPo(id);
    }

    /** @param {number|string} id — ID del picking/recepción a abrir */
    openPicking(id) {
        // FIX [FASE-3]: res_id abre el form directamente; domain+list_view era redundante
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "stock.picking",
            res_id:    parseInt(id),
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    openPickingFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.pickId;
        if (id) this.openPicking(id);
    }

    get isEmpty() {
        const s = this.state;
        return !s.loading
            && s.rfqs.length === 0 && s.to_approve.length === 0
            && s.overdue.length === 0 && s.all_pos.length === 0 && s.pending_pos.length === 0
            && s.receipts.length === 0 && s.deliveries.length === 0 && s.services.length === 0;
    }

    get activeList() {
        if (this.state.listTab) {
            switch (this.state.listTab) {
                case "receipts":   return this.state.receipts;
                case "deliveries": return this.state.deliveries;
                case "services":   return this.state.services;
            }
        }
        switch (this.state.ocFilter) {
            case "all":     return this.state.all_pos;
            case "pending": return this.state.pending_pos;
            case "rfqs":    return this.state.rfqs;
            case "approve": return this.state.to_approve;
            default:        return this.state.overdue;
        }
    }

    get activeCount() {
        const s = this.state;
        if (s.listTab === 'receipts')   return s.kpis.receipts_total;
        if (s.listTab === 'deliveries') return s.kpis.deliveries_total;
        if (s.listTab === 'services')   return s.kpis.services_total;
        switch (s.ocFilter) {
            case 'all':     return s.kpis.total;
            case 'pending': return s.kpis.pending;
            case 'rfqs':    return s.kpis.rfq;
            case 'approve': return s.kpis.to_approve;
            default:        return s.kpis.overdue;
        }
    }

    get totalPages()  { return Math.max(1, Math.ceil(this.activeCount / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }

    nextPage() { if (this.hasNextPage) { this.state.page++; this._load(); } }
    prevPage() { if (this.hasPrevPage) { this.state.page--; this._load(); } }

    fmt(n)    { return new Intl.NumberFormat('es-AR').format(n || 0); }
    fmtAmt(n) { return new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0); }

    // ── Ordenamiento ─────────────────────────────────────────────────────────

    onHeaderClick(ev) {
        const sortKey = ev.currentTarget.dataset.sortKey;
        if (sortKey) this.sortBy(sortKey);
    }

    sortBy(field) {
        if (this.state.sortField === field) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortField = field;
            this.state.sortDir = "asc";
        }
        this.state.page = 1;
        this._load();
    }

    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    // El sort es siempre server-side (partner y availability se ordenan en Python antes de paginar)
    get sortedList() { return this.activeList; }

    toggleExpand(id) {
        if (this.state.expandedIds[id]) {
            delete this.state.expandedIds[id];
        } else {
            this.state.expandedIds = { ...this.state.expandedIds, [id]: true };
        }
    }
}

registry.category("view_widgets").add("po_dashboard_widget", {
    component: PoDashboardWidget,
});
