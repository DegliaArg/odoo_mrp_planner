/** @odoo-module **/

/**
 * @widget SupplierAnalysisWidget
 * @description Tabla interactiva de análisis de proveedores con métricas de desempeño
 * (puntualidad, retrasos, lead time, variación de precio, facturas pendientes).
 * Permite filtrar por período y tipo de OC, buscar por nombre, ordenar por cualquier
 * columna y expandir en acordeón las órdenes de compra de cada proveedor.
 *
 * Métodos RPC que consume:
 *   - get_supplier_analysis_data(date_from, date_to, search, po_type)
 *       → { rows: Array<SupplierRow>, config: Object, has_invoices: boolean, show_supplier_cat: boolean }
 *   - get_supplier_pos_for_analysis(partner_id, date_from, date_to)
 *       → Array<{ po_id, name, date_approve, amount_total, receipt_status, ... }>
 *
 * Props esperados:
 *   - record: Object — registro del dashboard (mrp.planner.dashboard)
 */
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
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

/**
 * Retorna el primer día del año en curso en formato YYYY-MM-DD.
 * Usado como valor inicial del filtro de período "Desde".
 * @returns {string} Fecha en formato YYYY-MM-DD (ej. "2026-01-01")
 */
function firstOfYearYMD() {
    return `${new Date().getFullYear()}-01-01`;
}

/**
 * Retorna la fecha de hoy en formato YYYY-MM-DD.
 * Usado como valor inicial del filtro de período "Hasta".
 * @returns {string} Fecha en formato YYYY-MM-DD (ej. "2026-07-03")
 */
function todayYMD() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

class SupplierAnalysisWidget extends Component {
    static template = "odoo_mrp_planner.SupplierAnalysisWidget";
    static props = { record: { type: Object }, "*": true };

    /**
     * Inicializa servicios, estado reactivo, gestor de columnas y lifecycle hooks.
     * El debounce de carga evita llamadas RPC excesivas al tipear en los filtros de fecha.
     */
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:            true,
            periodFrom:         firstOfYearYMD(),
            periodTo:           todayYMD(),
            search:             '',
            poType:             'all',
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

        this._loadDebounceTimer = null;
        this._loadDebounced = () => {
            clearTimeout(this._loadDebounceTimer);
            this._loadDebounceTimer = setTimeout(() => this._load(), 400);
        };

        onMounted(() => this._load());
        onWillUnmount(() => {
            this.colsSup.cancelResize();
            clearTimeout(this._loadDebounceTimer);
        });
    }

    /**
     * Manejador de clic en encabezado de columna para ordenar la tabla.
     * Delega en setSort usando el atributo data-sort-key del elemento clicado.
     * @param {MouseEvent} ev - Evento de clic sobre el th del encabezado
     */
    onHeaderClick(ev) {
        const sortKey = ev.currentTarget.dataset.sortKey;
        if (sortKey) this.setSort(sortKey);
    }

    /**
     * Carga los datos de análisis de proveedores desde el backend.
     * Reinicia el acordeón y los datos de OCs cacheados para evitar mostrar
     * datos de un período anterior mientras llega la respuesta del nuevo.
     * @returns {Promise<void>}
     */
    async _load() {
        this.state.loading = true;
        this.state.expandedSuppliers = {};
        this.state.posBySupplier     = {};
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_supplier_analysis_data",
                [this.state.periodFrom, this.state.periodTo, '', this.state.poType],
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

    /**
     * Actualiza la fecha de inicio del período y dispara una carga con debounce.
     * Si la nueva fecha es posterior al "Hasta", adelanta "Hasta" para mantener coherencia.
     * @param {Event} ev - Evento change del input[type=date] "Desde"
     */
    onPeriodFromChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodFrom = val;
        if (this.state.periodFrom > this.state.periodTo)
            this.state.periodTo = this.state.periodFrom;
        this._loadDebounced();
    }

    /**
     * Actualiza la fecha de fin del período y dispara una carga con debounce.
     * Si la nueva fecha es anterior al "Desde", retrocede "Desde" para mantener coherencia.
     * @param {Event} ev - Evento change del input[type=date] "Hasta"
     */
    onPeriodToChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodTo = val;
        if (this.state.periodTo < this.state.periodFrom)
            this.state.periodFrom = this.state.periodTo;
        this._loadDebounced();
    }

    // ── Búsqueda reactiva (client-side) ───────────────────────────────────────

    /**
     * Filtra la tabla por nombre de proveedor en tiempo real (client-side).
     * Reinicia la página a 1 para evitar quedarse en una página vacía.
     * @param {InputEvent} ev - Evento input del campo de búsqueda
     */
    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page   = 1;
    }

    /**
     * Cambia el filtro de tipo de OC y recarga los datos desde el backend.
     * El guard de igualdad evita una llamada innecesaria si se selecciona el tipo ya activo.
     * @param {'all'|'purchase'|'done'} t - Tipo de OC a filtrar
     */
    setPoType(t) {
        if (this.state.poType === t) return;
        this.state.poType = t;
        this.state.page   = 1;
        this._load();
    }

    // ── Sort ──────────────────────────────────────────────────────────────────

    /**
     * Cambia la columna de ordenamiento o invierte la dirección si ya está activa.
     * La columna "partner_name" ordena ascendente por defecto (A→Z);
     * el resto ordena descendente (mayor → menor).
     * @param {string} col - Clave de columna definida en SUP_COLS (sortKey)
     */
    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortCol = col;
            this.state.sortDir = col === 'partner_name' ? 'asc' : 'desc';
        }
        this.state.page = 1;
    }

    /**
     * Retorna la clase CSS del ícono de ordenamiento para una columna dada.
     * Muestra un ícono neutro si la columna no está activa, o un ícono
     * direccional (asc/desc) resaltado en azul si es la columna activa.
     * @param {string} col - Clave de columna
     * @returns {string} Clases CSS de FontAwesome para el ícono
     */
    sortIcon(col) {
        if (this.state.sortCol !== col) return 'fa fa-sort text-muted ms-1';
        return this.state.sortDir === 'asc'
            ? 'fa fa-sort-asc text-primary ms-1'
            : 'fa fa-sort-desc text-primary ms-1';
    }

    /**
     * Retorna las filas de proveedores filtradas por búsqueda y ordenadas.
     * Los nulos se ubican al final en cualquier dirección de orden (usando
     * Infinity/-Infinity) para no distorsionar el ranking de proveedores activos.
     * @returns {Array<Object>} Filas ordenadas y filtradas del dataset completo
     */
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

    /**
     * Retorna el subconjunto de filas correspondiente a la página actual.
     * @returns {Array<Object>} Filas visibles en la página activa
     */
    get pagedRows() {
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.sortedRows.slice(start, start + this.state.pageSize);
    }

    /** @returns {number} Total de páginas disponibles (mínimo 1 aunque no haya datos) */
    get totalPages()  { return Math.max(1, Math.ceil(this.sortedRows.length / this.state.pageSize)); }
    /** @returns {boolean} True si existe una página siguiente */
    get hasNextPage() { return this.state.page < this.totalPages; }
    /** @returns {boolean} True si existe una página anterior */
    get hasPrevPage() { return this.state.page > 1; }
    /** Avanza a la siguiente página si está disponible. */
    nextPage() { if (this.hasNextPage) this.state.page++; }
    /** Retrocede a la página anterior si está disponible. */
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    /**
     * Retorna el número de columnas visibles para el atributo colspan de filas de estado
     * (loading, sin datos, acordeón de OCs).
     * @returns {number} Cantidad de columnas visibles actualmente
     */
    get tableColspan() {
        return this.supVisibleCols.length;
    }

    /**
     * Retorna las columnas visibles filtradas por disponibilidad de datos.
     * "pending_inv" se oculta si el backend indica que no hay módulo de facturación activo.
     * "supplier_cat" se oculta si la clasificación ABC de proveedor no está configurada.
     * @returns {Array<Object>} Definiciones de columna visibles según contexto
     */
    get supVisibleCols() {
        return this.colsSup.visibleCols().filter(c => {
            if (c.key === 'pending_inv') return this.state.data && this.state.data.has_invoices;
            if (c.key === 'supplier_cat') return this.state.data && this.state.data.show_supplier_cat;
            return true;
        });
    }

    /**
     * Retorna la clase Bootstrap para el badge de categoría de proveedor (A–E).
     * Usa text-bg-* para garantizar contraste automático de texto según el fondo.
     * @param {'A'|'B'|'C'|'D'|'E'} cat - Letra de categoría Pareto del proveedor
     * @returns {string} Clases CSS del badge
     */
    catBadgeClass(cat) {
        const map = { A: 'text-bg-success', B: 'text-bg-primary', C: 'text-bg-warning text-dark', D: 'text-bg-secondary', E: 'text-bg-danger' };
        return map[cat] || 'text-bg-secondary';
    }

    // ── Acordeón de OCs ───────────────────────────────────────────────────────

    /**
     * Expande o colapsa el acordeón de OCs de un proveedor.
     * Si se abre por primera vez, carga las OCs desde el backend y las cachea
     * en posBySupplier para no repetir la llamada RPC en aperturas subsiguientes.
     * @param {Object} row - Fila del proveedor con al menos partner_id
     * @returns {Promise<void>}
     */
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

    /**
     * Retorna las clases CSS del badge para el estado de recepción de una OC.
     * @param {'full'|'partial'|'pending'|'none'} status - Estado de recepción
     * @returns {string} Clases CSS del badge Bootstrap
     */
    receiptBadge(status) {
        const map = {
            full:    'badge bg-success',
            partial: 'badge bg-warning text-dark',
            pending: 'badge bg-secondary',
            none:    'badge bg-light text-muted border',
        };
        return map[status] || 'badge bg-light';
    }

    /**
     * Retorna la etiqueta legible en español para el estado de recepción de una OC.
     * @param {'full'|'partial'|'pending'|'none'} status - Estado de recepción
     * @returns {string} Texto visible en el badge de recepción
     */
    receiptLabel(status) {
        const map = { full: 'Completa', partial: 'Parcial', pending: 'Pendiente', none: 'Sin recepción' };
        return map[status] || status;
    }

    // ── Formateo / clases ─────────────────────────────────────────────────────

    /**
     * Acceso seguro al objeto de configuración de umbrales del dashboard.
     * Retorna un objeto vacío si los datos aún no fueron cargados, evitando
     * errores al acceder a propiedades de configuración durante la carga inicial.
     * @returns {Object} Configuración con umbrales sup_on_time_*, sup_delay_*, etc.
     */
    _cfg() { return (this.state.data && this.state.data.config) || {}; }

    /**
     * Formatea un número como monto monetario sin decimales en locale es-AR.
     * @param {number|null|undefined} n - Monto a formatear
     * @returns {string} Monto formateado (ej. "1.234.567") o "—" si es nulo
     */
    fmtMoney(n) {
        if (n === null || n === undefined) return '—';
        return '$ ' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(n);
    }

    /**
     * Formatea un número como variación porcentual con signo explícito.
     * El signo "+" se muestra en valores positivos para facilitar lectura de variaciones.
     * @param {number|null|undefined} n - Porcentaje a formatear
     * @returns {string} Porcentaje con signo (ej. "+5%", "-3%") o "—" si es nulo
     */
    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return `${n > 0 ? '+' : ''}${n}%`;
    }

    /**
     * Retorna la clase CSS semafórica para el porcentaje de entregas a tiempo.
     * Los umbrales green/yellow se toman de la configuración del dashboard
     * (sup_on_time_green, sup_on_time_yellow), con defaults 90% y 70%.
     * @param {number|null|undefined} v - Porcentaje de entregas a tiempo (0–100)
     * @returns {string} Clase CSS de Bootstrap text-* según semáforo
     */
    onTimeCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const cfg = this._cfg();
        const green = cfg.sup_on_time_green ?? 90;
        const yellow = cfg.sup_on_time_yellow ?? 70;
        if (v >= green) return 'text-success fw-semibold';
        if (v >= yellow) return 'text-warning fw-semibold';
        return 'text-danger fw-semibold';
    }

    /**
     * Retorna la clase CSS semafórica para el promedio de días de retraso.
     * La lógica está invertida respecto a onTimeCls: menor valor es mejor,
     * por lo que verde corresponde a valores bajos. Defaults: green ≤ 1 d, yellow ≤ 3 d.
     * @param {number|null|undefined} v - Promedio de días de retraso
     * @returns {string} Clase CSS de Bootstrap text-* según semáforo
     */
    delayCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const cfg = this._cfg();
        const green = cfg.sup_delay_green ?? 1;
        const yellow = cfg.sup_delay_yellow ?? 3;
        if (v <= green) return 'text-success';
        if (v <= yellow) return 'text-warning';
        return 'text-danger';
    }

    /**
     * Retorna la clase CSS semafórica para el porcentaje de recepciones completas.
     * Umbral configurable via sup_complete_green (default 95%) y sup_complete_yellow (default 80%).
     * @param {number|null|undefined} v - Porcentaje de recepciones sin backorder (0–100)
     * @returns {string} Clase CSS de Bootstrap text-* según semáforo
     */
    completeCls(v) {
        if (v === null || v === undefined) return 'text-muted';
        const cfg = this._cfg();
        const green = cfg.sup_complete_green ?? 95;
        const yellow = cfg.sup_complete_yellow ?? 80;
        if (v >= green) return 'text-success';
        if (v >= yellow) return 'text-warning';
        return 'text-danger';
    }

    /**
     * Retorna la clase CSS semafórica para la variación de precio OC vs costo estándar.
     * Usa valor absoluto porque tanto sobreprecios como subprecios inusuales son señales
     * de alerta. Umbrales: sup_price_var_green (default 3%) y sup_price_var_yellow (default 10%).
     * @param {number|null|undefined} v - Variación porcentual (puede ser negativa)
     * @returns {string} Clase CSS de Bootstrap text-* según semáforo
     */
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

    openKpiList() {
        this.action.doAction({
            type:    'ir.actions.act_window',
            name:    'Órdenes de compra',
            res_model: 'purchase.order',
            views:   [[false, 'list'], [false, 'form']],
            target:  'current',
            domain:  [['state', 'in', ['purchase', 'done']],
                      ['date_approve', '>=', `${this.state.periodFrom} 00:00:00`],
                      ['date_approve', '<=', `${this.state.periodTo} 23:59:59`]],
        });
    }

    /**
     * Navega al formulario del proveedor en res.partner.
     * Detiene la propagación del evento para no disparar el toggleAccordion
     * de la fila padre al hacer clic en el enlace de nombre.
     * @param {MouseEvent} ev - Evento de clic
     * @param {Object} row - Fila del proveedor con partner_id
     */
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

    /**
     * Navega al formulario de una orden de compra específica.
     * Detiene la propagación para no colapsar el acordeón del proveedor al hacer clic.
     * @param {MouseEvent} ev - Evento de clic
     * @param {Object} po - Objeto de OC con po_id
     */
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

    /**
     * Abre la vista de lista de todas las OCs confirmadas del proveedor en el período activo.
     * El dominio replica exactamente los filtros aplicados en el análisis (partner, estados,
     * rango de fechas de aprobación) para que el usuario vea el mismo universo de datos.
     * @param {MouseEvent} ev - Evento de clic
     * @param {Object} row - Fila del proveedor con partner_id
     */
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

    supplierKpiTooltip(key) {
        const k = this.state.data && this.state.data.kpis;
        if (!k) return '';
        const cfg = this._cfg();
        switch (key) {
            case 'suppliers':
                return `Proveedores distintos con al menos una OC confirmada en el período\n→ ${k.supplier_count} proveedores`;
            case 'amount':
                return `Monto total neto de todas las OCs confirmadas en el período\n→ ${this.fmtMoney(k.total_amount)} en ${k.total_orders} OCs`;
            case 'orders':
                return `Cantidad de OCs confirmadas en el período\n→ ${k.total_orders} OCs`;
            case 'on_time':
                return `% de recepciones completadas antes o en la fecha planificada, promediado entre proveedores\nRecepciones a tiempo ÷ Total recepciones × 100\n→ ${k.avg_on_time_pct !== null ? k.avg_on_time_pct + '%' : '—'} promedio general\nVerde ≥ ${cfg.sup_on_time_green ?? 90}% | Amarillo ≥ ${cfg.sup_on_time_yellow ?? 70}% | Rojo < ${cfg.sup_on_time_yellow ?? 70}%`;
            case 'lead_time':
                return `Días promedio entre aprobación de OC y validación de recepción, promediado entre proveedores\n→ ${k.avg_lead_time_days !== null ? k.avg_lead_time_days + ' días' : '—'} promedio general`;
            case 'price_var':
                return `Variación porcentual promedio entre precio de OC y costo estándar del artículo\n(Precio OC − Costo estándar) ÷ Costo estándar × 100\n→ ${k.avg_price_var_pct !== null ? this.fmtPct(k.avg_price_var_pct) : '—'} promedio general\nVerde ≤ ${cfg.sup_price_var_green ?? 3}% | Amarillo ≤ ${cfg.sup_price_var_yellow ?? 10}% | Rojo > ${cfg.sup_price_var_yellow ?? 10}%`;
        }
        return '';
    }

    supplierCellTooltip(key, row) {
        const cfg = this._cfg();
        switch (key) {
            case 'on_time_pct':
                if (!row.pick_count) return 'Sin recepciones en el período';
                return `Recepciones completadas en fecha respecto al total del proveedor\nRecepciones a tiempo ÷ Total recepciones × 100\n→ ${row.on_time_pct}% de ${row.pick_count} recepciones\nVerde ≥ ${cfg.sup_on_time_green ?? 90}% | Amarillo ≥ ${cfg.sup_on_time_yellow ?? 70}% | Rojo < ${cfg.sup_on_time_yellow ?? 70}%`;
            case 'complete_pct':
                if (!row.pick_count) return 'Sin recepciones en el período';
                return `Recepciones recibidas completamente sin backorder respecto al total\nRecepciones completas ÷ Total recepciones × 100\n→ ${row.complete_pct}% de ${row.pick_count} recepciones\nVerde ≥ ${cfg.sup_complete_green ?? 95}% | Amarillo ≥ ${cfg.sup_complete_yellow ?? 80}% | Rojo < ${cfg.sup_complete_yellow ?? 80}%`;
            case 'avg_price_var_pct':
                if (row.avg_price_var_pct === null || row.avg_price_var_pct === undefined) return 'Sin datos de precio';
                return `Diferencia promedio entre precio de OC y costo estándar del artículo\n(Precio OC − Costo estándar) ÷ Costo estándar × 100\n→ ${row.avg_price_var_pct > 0 ? '+' : ''}${row.avg_price_var_pct}%\nVerde ≤ ${cfg.sup_price_var_green ?? 3}% | Amarillo ≤ ${cfg.sup_price_var_yellow ?? 10}% | Rojo > ${cfg.sup_price_var_yellow ?? 10}%`;
        }
        return '';
    }
}

registry.category("view_widgets").add("supplier_analysis_widget", {
    component: SupplierAnalysisWidget,
});
