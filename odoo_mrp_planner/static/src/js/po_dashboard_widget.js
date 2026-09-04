/** @odoo-module **/

/**
 * @description Widget de órdenes de compra, recepciones y entregas para el dashboard.
 *   Soporta filtrado por tab (all/purchase/subcontract), fecha, tipo de OC y subtab.
 *   Paginado y ordenamiento server-side.
 * @fires RPC mrp.planner.dashboard.get_po_dashboard_data — datos de OCs y movimientos
 *   Params: (tab, dateFrom, dateTo, sortField, sortDir, page, pageSize, search)
 *   @returns {{ kpis: KpiPo, kpi_ids: Object, rfqs: PoRow[], to_approve: PoRow[],
 *              overdue: PoRow[], all_pos: PoRow[], pending_pos: PoRow[],
 *              receipts: PickRow[], deliveries: PickRow[], services: ServiceRow[],
 *              show_services_tab: boolean }}
 * @listens onMounted — carga datos y sincroniza altura
 */

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useColManager } from "./column_manager";
import { restoreFilters, saveFilters } from "./filter_persistence";

// Estado de filtros que sobrevive al remontaje del widget (volver de una sublista)
// y a la sesión del navegador.
const PO_PERSIST_KEYS = [
    'tab', 'ocFilter', 'listTab', 'dateFrom', 'dateTo',
    'search', 'sortField', 'sortDir', 'page', 'pageSize',
];

const PO_OC_COLS = [
    { key: 'name',         label: 'Referencia',      width: 130, sortKey: 'name',         title: 'Número de la orden de compra.' },
    { key: 'partner',      label: 'Proveedor',        width: 180, sortKey: 'partner',      title: 'Proveedor de la orden de compra.' },
    { key: 'date_planned', label: 'Entrega estimada', width: 130, sortKey: 'date_planned', title: 'Fecha de entrega planificada (date_planned).' },
    { key: 'amount_total', label: 'Total',            width: 100, sortKey: 'amount_total', align: 'end',    title: 'Importe total de la OC en moneda de la empresa.' },
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

/**
 * Convierte un objeto Date en cadena "YYYY-MM-DD" sin depender de toISOString,
 * evitando desfases por zona horaria (UTC vs. local).
 * @param {Date} d - Fecha a convertir
 * @returns {string} Fecha en formato ISO local "YYYY-MM-DD"
 */
function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY_KPIS = {
    rfq: 0, to_approve: 0, total: 0, pending: 0, overdue: 0, overdue_critical: 0,
    overdue_days: null, delay_stat: "max",
    receipts_total: 0, receipts_overdue: 0, deliveries_total: 0, deliveries_overdue: 0,
    services_total: 0, po_critical_days: 5,
};

class PoDashboardWidget extends Component {
    static template = "odoo_mrp_planner.PoDashboardWidget";
    static components = {};
    static props = {
        record: { type: Object },
        "*": true,
    };

    /**
     * Inicializa servicios OWL, gestores de columnas, estado reactivo y
     * registra los hooks de ciclo de vida (onMounted / onWillUnmount).
     * El rango de fechas inicial cubre el mes en curso.
     */
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this._loadSeq = 0;
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
            search:    '',
            loading:   true,
            sortField: null,
            sortDir:   "asc",
            page:      1,
            pageSize:  50,
            kpis:      { ...EMPTY_KPIS },
            kpi_ids:   {},
            rfqs:             [],
            to_approve:       [],
            overdue:          [],
            all_pos:          [],
            pending_pos:      [],
            receipts:         [],
            deliveries:       [],
            services:            [],
            show_services_tab:   false,
            exclude_service_pos: false,
            expandedIds: {},
        });

        // Restaurar filtros de la última visita (por empresa). Se guarda en cada
        // _load(), el punto único por el que pasa todo cambio de filtro.
        const companyId = this.env.services.company?.currentCompany?.id || 0;
        this._persistKey = `po_dashboard.${companyId}`;
        restoreFilters(this._persistKey, this.state, PO_PERSIST_KEYS);

        onMounted(async () => {
            try {
                await this._load();
                this._rafId = requestAnimationFrame(() => this._syncH());
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });

        onWillUnmount(() => {
            if (this._rafId) {
                cancelAnimationFrame(this._rafId);
                this._rafId = null;
            }
        });
    }

    /**
     * Llama al método Python get_po_dashboard_data y vuelca el resultado en
     * el estado reactivo. Gestiona el flag loading para el spinner del template.
     * Usa un contador de secuencia (_loadSeq) para descartar respuestas obsoletas
     * cuando se encadenan llamadas rápidas o el componente es destruido durante el await.
     * @returns {Promise<void>}
     */
    async _load() {
        saveFilters(this._persistKey, this.state, PO_PERSIST_KEYS);
        const seq = ++this._loadSeq;
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_po_dashboard_data",
                [this.state.tab, this.state.dateFrom, this.state.dateTo,
                 this.state.sortField || null, this.state.sortDir,
                 this.state.page, this.state.pageSize, this.state.search || null],
            );
            if (seq !== this._loadSeq) return;
            this.state.kpis            = d.kpis;
            this.state.kpi_ids         = d.kpi_ids || {};
            this.state.rfqs            = d.rfqs;
            this.state.to_approve      = d.to_approve;
            this.state.overdue         = d.overdue;
            this.state.all_pos         = d.all_pos    || [];
            this.state.pending_pos     = d.pending_pos || [];
            this.state.receipts        = d.receipts   || [];
            this.state.deliveries      = d.deliveries || [];
            this.state.services        = d.services   || [];
            this.state.show_services_tab   = d.show_services_tab   || false;
            // listTab 'services' restaurado de otra sesión con la pestaña ya deshabilitada
            if (this.state.listTab === 'services' && !this.state.show_services_tab) {
                this.state.listTab = null;
            }
            this.state.exclude_service_pos = d.kpis.exclude_service_pos || false;
        } catch (e) {
            if (seq !== this._loadSeq) return;
            console.error("[PoDashboardWidget]", e);
        } finally {
            if (seq === this._loadSeq) this.state.loading = false;
        }
    }

    /**
     * Cambia el tab principal (all / purchase / subcontract) y recarga datos.
     * Reinicia subtab, ordenamiento y página para evitar estados inconsistentes.
     * @param {string} tab - "all" | "purchase" | "subcontract"
     */
    setTab(tab) {
        if (this.state.tab === tab) return;
        this.state.tab       = tab;
        this.state.listTab   = null;
        this.state.sortField = null;
        this.state.sortDir   = "asc";
        this.state.page      = 1;
        this._load().then(() => {
            if (this._rafId) cancelAnimationFrame(this._rafId);
            this._rafId = requestAnimationFrame(() => this._syncH());
        });
    }

    /** Iguala la altura del panel de tabla a la del panel de KPIs */
    _syncH() {
        const root = this._root.el;
        if (!root) return;
        const kpiEl    = root.querySelector('.o_kpi_height_src');
        const tableEl  = root.querySelector('.o_table_scroll');
        if (!kpiEl || !tableEl) return;
        tableEl.style.height = '0';
        const searchEl = root.querySelector('.o_above_table_search');
        const searchH  = searchEl ? (searchEl.offsetHeight + 8) : 0;
        const h = kpiEl.offsetHeight - searchH;
        tableEl.style.height = Math.max(h, 150) + 'px';
    }

    /**
     * Actualiza el texto de búsqueda y recarga desde la página 1
     * con un debounce de 300ms.
     * @param {string} text - Texto de búsqueda
     */
    setSearch(text) {
        this.state.search = text;
        this.state.page   = 1;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this._load(), 300);
    }

    /**
     * Actualiza la fecha de inicio del filtro y recarga desde la página 1.
     * @param {Event} ev - Evento change del input date
     */
    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom > this.state.dateTo) this.state.dateTo = this.state.dateFrom;
        this.state.page = 1;
        this._load();
    }
    /**
     * Actualiza la fecha de fin del filtro y recarga desde la página 1.
     * @param {Event} ev - Evento change del input date
     */
    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateTo < this.state.dateFrom) this.state.dateFrom = this.state.dateTo;
        this.state.page = 1;
        this._load();
    }

    /**
     * Cambia el filtro de tipo de OC (all / pending / overdue / rfqs / approve)
     * desde el select del template y recarga datos.
     * @param {Event} ev - Evento change del select
     */
    onOcFilterChange(ev) {
        this.state.ocFilter  = ev.target.value;
        this.state.listTab   = null;
        this.state.sortField = null;
        this.state.sortDir   = "asc";
        this.state.page      = 1;
        this._load();
    }

    /**
     * Activa un subtab de movimientos (receipts / deliveries / services).
     * Pasar null vuelve al modo OC. Reinicia orden y página.
     * @param {string|null} tab - "receipts" | "deliveries" | "services" | null
     */
    setListTab(tab) {
        if (this.state.listTab === tab) return;
        this.state.listTab   = tab;
        this.state.sortField = null;
        this.state.sortDir   = "asc";
        this.state.page      = 1;
        this._load();
    }

    /**
     * Abre una vista lista/form de purchase.order acotada a un conjunto exacto
     * de IDs. El backend calcula esos IDs con los mismos criterios que el KPI
     * (campo de fecha por bucket, depósito, servicios y umbral crítico), de modo
     * que la lista mostrada coincide siempre con el número del KPI.
     * @param {string} name - Título que se muestra en la vista
     * @param {number[]} ids - IDs de purchase.order del KPI correspondiente
     */
    _navigateIds(name, ids) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name,
            res_model: "purchase.order",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            domain:    [["id", "in", ids || []]],
            target:    "current",
        });
    }

    /** Navega a las cotizaciones del KPI (estado borrador/enviada, filtradas por date_order). */
    onClickRfqs()      { this._navigateIds("Cotizaciones", this.state.kpi_ids.rfq); }
    /** Navega a las OCs por aprobar del KPI (filtradas por date_order). */
    onClickToApprove() { this._navigateIds("Por aprobar",  this.state.kpi_ids.to_approve); }
    /** Navega a las OCs aprobadas del KPI (filtradas por date_approve). */
    onClickAll()       { this._navigateIds("Aprobadas",    this.state.kpi_ids.total); }
    /** Navega a las OCs a tiempo del KPI (date_planned en rango y ≥ hoy). */
    onClickPending()   { this._navigateIds("A tiempo",     this.state.kpi_ids.pending); }
    /** Navega a las OCs vencidas del KPI (date_planned en rango y < hoy). */
    onClickOverdue()   { this._navigateIds("Vencidas",     this.state.kpi_ids.overdue); }
    /** Navega a las OCs críticas del KPI (vencidas con retraso ≥ umbral configurable). */
    onClickCritical() {
        const days = this.state.kpis.po_critical_days || 5;
        this._navigateIds(`Críticas (+${days} días)`, this.state.kpi_ids.overdue_critical);
    }

    /** @param {number|string} id — ID de la OC a abrir */
    openPo(id) {
        // res_id abre el form directamente; domain+list_view era redundante
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "purchase.order",
            res_id:    parseInt(id),
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    /**
     * Manejador de click en una fila de OC: extrae el data-po-id del tr
     * más cercano y delega en openPo.
     * @param {MouseEvent} ev - Click sobre cualquier celda de la fila
     */
    openPoFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.poId;
        if (id) this.openPo(id);
    }

    /** @param {number|string} id — ID del picking/recepción a abrir */
    openPicking(id) {
        // res_id abre el form directamente; domain+list_view era redundante
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "stock.picking",
            res_id:    parseInt(id),
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    /**
     * Manejador de click en una fila de picking: extrae el data-pick-id del tr
     * más cercano y delega en openPicking.
     * @param {MouseEvent} ev - Click sobre cualquier celda de la fila
     */
    openPickingFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.pickId;
        if (id) this.openPicking(id);
    }

    /**
     * Devuelve true cuando no hay datos en ninguna lista y la carga terminó,
     * para mostrar el estado vacío en el template.
     * @returns {boolean}
     */
    get isEmpty() {
        const s = this.state;
        return !s.loading
            && s.rfqs.length === 0 && s.to_approve.length === 0
            && s.overdue.length === 0 && s.all_pos.length === 0 && s.pending_pos.length === 0
            && s.receipts.length === 0 && s.deliveries.length === 0 && s.services.length === 0;
    }

    /**
     * Selecciona el array de filas que debe renderizar la tabla activa,
     * priorizando el subtab de movimientos sobre el filtro de OC.
     * @returns {Array} Lista de filas (PoRow[] | PickRow[] | ServiceRow[])
     */
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

    /**
     * Devuelve el total de registros (server-side) de la lista activa,
     * usado para calcular el número total de páginas.
     * @returns {number}
     */
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

    /**
     * Total de páginas calculado a partir de activeCount y pageSize.
     * Mínimo 1 para evitar divisiones por cero en el template.
     * @returns {number}
     */
    get totalPages()  { return Math.max(1, Math.ceil(this.activeCount / this.state.pageSize)); }
    /**
     * Indica si existe una página siguiente disponible.
     * @returns {boolean}
     */
    get hasNextPage() { return this.state.page < this.totalPages; }
    /**
     * Indica si existe una página anterior disponible.
     * @returns {boolean}
     */
    get hasPrevPage() { return this.state.page > 1; }

    // ── Exportar Excel ─────────────────────────────────────────────────────────

    /**
     * Exporta la lista activa (OCs, recepciones, entregas o servicios) a Excel
     * (.xlsx), con TODAS las páginas y respetando los filtros vigentes (tab,
     * estado OC, subpestaña, fecha, búsqueda y orden). El armado es server-side.
     */
    async exportExcel() {
        try {
            const res = await this.orm.call("mrp.planner.dashboard", "get_po_export", [
                this.state.tab,
                this.state.ocFilter,
                this.state.listTab || null,
                this.state.dateFrom,
                this.state.dateTo,
                this.state.sortField || null,
                this.state.sortDir,
                this.state.search || null,
            ]);
            if (res && res.url) {
                this.action.doAction({ type: "ir.actions.act_url", url: res.url, target: "self" });
            } else if (res && res.error) {
                this.notification.add(
                    `${res.error}. Instalá la librería openpyxl en el servidor para exportar a Excel.`,
                    { type: "danger" });
            }
        } catch (e) {
            console.error("[PoDashboardWidget] export", e);
            this.notification.add("No se pudo generar el archivo de exportación.", { type: "danger" });
        }
    }

    /** Avanza a la página siguiente y recarga datos si hay una disponible. */
    nextPage() { if (this.hasNextPage) { this.state.page++; this._load(); } }
    /** Retrocede a la página anterior y recarga datos si hay una disponible. */
    prevPage() { if (this.hasPrevPage) { this.state.page--; this._load(); } }

    /**
     * Formatea un número entero con separadores de miles en locale es-AR.
     * @param {number} n - Número a formatear
     * @returns {string} Número formateado (ej: "1.234")
     */
    fmt(n)    { return new Intl.NumberFormat('es-AR').format(n || 0); }

    /** Subtítulo de la card "Vencidas": días de atraso junto al conteo (C5) —
     *  "máx. 12 días" o "prom. 4 días" según Ajustes → Alertas. Vacío con
     *  conteo 0 o sin dato. */
    overdueDelayText() {
        const k = this.state.kpis;
        if (!k.overdue || k.overdue_days === null || k.overdue_days === undefined) {
            return '';
        }
        const stat = k.delay_stat === 'avg' ? 'prom.' : 'máx.';
        return `${stat} ${this.fmt(k.overdue_days)} día${k.overdue_days === 1 ? '' : 's'}`;
    }

    poKpiTooltip(key) {
        const k   = this.state.kpis;
        const f   = n => this.fmt(n);
        const cd  = k.po_critical_days || 5;
        // Nota: cada KPI filtra el rango de fechas por un campo distinto, por eso
        // "Aprobadas" NO es la suma de "A tiempo" + "Vencidas" (esas usan fecha de entrega).
        switch (key) {
            case 'rfq':
                return `OCs en estado Borrador o Enviada al proveedor, aún no aprobadas\nEstados: Borrador · Enviada al proveedor\nFiltro de fecha: fecha del pedido (date_order) dentro del rango\n→ ${f(k.rfq)} OCs en cotización`;
            case 'to_approve':
                return `OCs que requieren aprobación adicional antes de ser confirmadas\nEstado: Por aprobar (to approve)\nFiltro de fecha: fecha del pedido (date_order) dentro del rango\n→ ${f(k.to_approve)} OCs por aprobar`;
            case 'total':
                return `OCs aprobadas con recepción pendiente o parcial\nEstado: Aprobada, recepción pendiente o parcial\nFiltro de fecha: fecha de aprobación (date_approve) dentro del rango\nNota: cada KPI usa un campo de fecha distinto; Aprobadas NO es la suma de A tiempo + Vencidas (esas usan fecha de entrega)\n→ ${f(k.total)} OCs aprobadas`;
            case 'pending':
                return `OCs aprobadas cuya fecha de entrega aún no venció\nFiltro de fecha: fecha de entrega (date_planned) dentro del rango y ≥ hoy\n→ ${f(k.pending)} OCs a tiempo`;
            case 'overdue': {
                const dd = this.overdueDelayText();
                return `OCs aprobadas cuya fecha de entrega ya venció sin recepción total\nFiltro de fecha: fecha de entrega (date_planned) dentro del rango y < hoy\n→ ${f(k.overdue)} OCs vencidas${dd ? ` · ${dd} de atraso` : ''}${dd ? `\nEstadístico (${k.delay_stat === 'avg' ? 'promedio' : 'máximo'}) configurable en Ajustes → Alertas` : ''}`;
            }
            case 'overdue_critical':
                return `OCs vencidas con más de ${cd} días de retraso (umbral configurable en Ajustes)\nFiltro de fecha: fecha de entrega (date_planned) dentro del rango\nCondición: días de retraso ≥ ${cd}\n→ ${f(k.overdue_critical)} OCs críticas`;
        }
        return '';
    }

    /**
     * Formatea un importe monetario con dos decimales en locale es-AR.
     * @param {number} n - Importe a formatear
     * @returns {string} Importe formateado (ej: "1.234,56")
     */
    fmtAmt(n) { return '$ ' + new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0); }

    // ── Ordenamiento ─────────────────────────────────────────────────────────

    /**
     * Manejador de click en cabecera de columna: lee el atributo data-sort-key
     * y delega en sortBy para alternar la dirección.
     * @param {MouseEvent} ev - Click en el th de la tabla
     */
    onHeaderClick(ev) {
        const sortKey = ev.currentTarget.dataset.sortKey;
        if (sortKey) this.sortBy(sortKey);
    }

    /**
     * Activa el ordenamiento por un campo dado. Si ya estaba activo,
     * alterna entre asc y desc. Siempre reinicia la página a 1 y recarga.
     * @param {string} field - Clave de columna (sortKey) a ordenar
     */
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

    /**
     * Devuelve la clase CSS de Font Awesome adecuada para el icono de
     * ordenamiento de una columna (neutro / asc / desc).
     * @param {string} field - Clave de columna a evaluar
     * @returns {string} Clases CSS (fa fa-sort | fa fa-sort-asc | fa fa-sort-desc)
     */
    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    // El sort es siempre server-side (partner y availability se ordenan en Python antes de paginar)
    /**
     * Alias de activeList mantenido para compatibilidad con el template.
     * El sort real ocurre server-side en Python antes de la paginación;
     * no se reordena en el cliente para evitar inconsistencias entre páginas.
     * @returns {Array}
     */
    get sortedList() { return this.activeList; }

    /**
     * Alterna el estado expandido/colapsado de la fila detalle de un picking.
     * Usa spread al expandir para que OWL detecte el cambio de referencia
     * y reactive el template correctamente.
     * @param {number|string} id - ID del picking a expandir/colapsar
     */
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
