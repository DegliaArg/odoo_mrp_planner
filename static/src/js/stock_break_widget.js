/** @odoo-module **/

/**
 * @description Widget de roturas de stock por ubicación/almacén.
 *   Filtra por tipo (all/broken/ok/no_min), búsqueda por nombre con debounce 300ms,
 *   y por una o varias ubicaciones internas.
 * @fires RPC mrp.planner.dashboard.get_internal_locations — ubicaciones internas disponibles
 * @fires RPC mrp.planner.dashboard.get_stock_break_data — productos con rotura/sin mínimo
 *   Params: (filterType, sortField, sortDir, page, pageSize, search, locationIds)
 *   @returns {{ kpis: {total,broken,ok,no_min}, products: ProductRow[],
 *              location_name: string, total_filtered: number }}
 * @listens onMounted — carga ubicaciones y datos iniciales
 * @listens onWillUnmount — cancela timer de debounce de búsqueda
 */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useColManager } from "./column_manager";
import { PlannerSearchBar } from "./planner_search_bar";

const STOCK_COLS = [
    { key: '_expand',      label: '',           width:  32, fixed: true, noResize: true, title: 'Expandir para ver OFs activas' },
    { key: 'name',         label: 'Artículo',   width: 200, sortKey: 'name',         title: 'Nombre o código del producto.' },
    { key: 'product_types',label: 'Tipo',       width: 130,                           title: 'Tipos de producto asignados en la ficha del artículo.' },
    { key: 'qty',          label: 'Stock actual', width: 95, sortKey: 'qty',          align: 'end', title: 'Cantidad disponible en las ubicaciones seleccionadas.' },
    { key: 'min_qty',      label: 'Mínimo',     width:  85, sortKey: 'min_qty',       align: 'end', title: 'Cantidad mínima del punto de reorden con ruta Fabricación.' },
    { key: 'qty_forecast', label: 'Pronóstico', width:  95, sortKey: 'qty_forecast',  align: 'end', title: 'Cantidad pronosticada (qty_forecast): stock actual + entradas pendientes − salidas pendientes.' },
    { key: 'rotation',     label: 'Rot.',       width:  75, sortKey: 'rotation',      align: 'end', title: 'Rotación = stock promedio del período ÷ promedio mensual de salidas × 30. Período configurable en Ajustes.' },
    { key: 'status',       label: 'Estado',     width: 100, sortKey: 'status',        align: 'center', title: 'Quiebre: stock menor que mínimo | OK: stock mayor o igual al mínimo | Sin mínimo: sin punto de reorden configurado.' },
];

class StockBreakWidget extends Component {
    static template = "odoo_mrp_planner.StockBreakWidget";
    static components = { PlannerSearchBar };
    static props = {
        record: { type: Object },
        "*": true,
    };

    /**
     * Inicializa servicios ORM y action, estado reactivo, gestor de columnas,
     * timer de debounce y listeners de ciclo de vida del componente.
     * Registra un listener global en `document` para cerrar el dropdown de
     * ubicaciones al hacer clic fuera de él.
     */
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:          true,
            error:            null,
            filterType:       "all",
            sortField:        null,
            sortDir:          "asc",
            page:             1,
            pageSize:         20,
            search:           "",
            locationIds:      [],
            locations:        [],
            locDropdownOpen:  false,
            locSearch:        "",
            kpis:             { total: 0, broken: 0, ok: 0, no_min: 0 },
            products:         [],
            allProducts:      [],
            locationName:     "",
            totalFiltered:    0,
            rotation_unit:          'days',
            rotation_months:        3,
            rotation_method:        'units',
            show_rotation:          false,
            rotation_warn_days:     null,
            rotation_critical_days: null,
            expandedProducts: {},
            mosByProduct:     {},
            mosLoading:       {},
        });
        this.colsStock = useColManager('stock_break', STOCK_COLS);

        this._searchTimer = null;
        this._loadSeq     = 0;
        this._closeLocDropdown = () => { this.state.locDropdownOpen = false; this.state.locSearch = ""; };

        onMounted(() => {
            this._init();
            document.addEventListener('click', this._closeLocDropdown);
        });
        onWillUnmount(() => {
            clearTimeout(this._searchTimer);
            document.removeEventListener('click', this._closeLocDropdown);
        });
    }

    /**
     * Maneja el clic en la cabecera de una columna ordenable.
     * Lee el atributo `data-sort-key` del elemento disparador y delega en `sortBy`.
     * @param {MouseEvent} ev - Evento de clic del encabezado de tabla
     */
    onHeaderClick(ev) {
        const sortKey = ev.currentTarget.dataset.sortKey;
        if (sortKey) this.sortBy(sortKey);
    }

    /** @returns {Promise<void>} Carga ubicaciones y datos iniciales en paralelo */
    async _init() {
        const [locs] = await Promise.all([
            this.orm.call("mrp.planner.dashboard", "get_internal_locations", []),
            this._load(),
        ]);
        this.state.locations = locs;
    }

    /** @returns {Promise<void>} Carga todos los productos del servidor y aplica sort/filtro/paginación client-side */
    async _load() {
        const seq = ++this._loadSeq;
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_stock_break_data",
                [this.state.search, this.state.locationIds.length ? this.state.locationIds : null],
            );
            if (seq !== this._loadSeq) return;
            if (d.error === "no_location") {
                this.state.error = "no_location";
            } else {
                this.state.error        = null;
                this.state.kpis         = d.kpis;
                this.state.locationName = d.location_name;
                this.state.allProducts  = d.products;
                this.state.rotation_unit          = d.rotation_unit          || 'days';
                this.state.show_rotation          = !!d.show_rotation;
                this.state.rotation_months        = d.rotation_months        || 3;
                this.state.rotation_method        = d.rotation_method        || 'units';
                this.state.rotation_warn_days     = d.rotation_warn_days     ?? null;
                this.state.rotation_critical_days = d.rotation_critical_days ?? null;
                this.state.expandedProducts = {};
                this.state.mosByProduct     = {};
                this.state.mosLoading       = {};
                this._applyClientSort();
            }
        } catch (e) {
            if (seq !== this._loadSeq) return;
            console.error("[StockBreakWidget]", e);
        } finally {
            if (seq === this._loadSeq) this.state.loading = false;
        }
    }

    /** Aplica filtro, sort y paginación sobre `state.allProducts` sin ir al servidor */
    _applyClientSort() {
        let rows = [...this.state.allProducts];

        // Filtro
        const f = this.state.filterType;
        if      (f === 'broken') rows = rows.filter(r => r.is_broken);
        else if (f === 'ok')     rows = rows.filter(r => r.has_min && !r.is_broken);
        else if (f === 'no_min') rows = rows.filter(r => !r.has_min);

        this.state.totalFiltered = rows.length;

        // Sort
        const field = this.state.sortField;
        const rev   = this.state.sortDir === 'desc';
        if (field === 'name') {
            rows.sort((a, b) => {
                const av = (a.name || '').toLowerCase();
                const bv = (b.name || '').toLowerCase();
                return rev ? bv.localeCompare(av) : av.localeCompare(bv);
            });
        } else if (field === 'qty') {
            rows.sort((a, b) => rev ? b.qty - a.qty : a.qty - b.qty);
        } else if (field === 'min_qty') {
            rows.sort((a, b) => {
                const av = a.min_qty !== null ? a.min_qty : -1;
                const bv = b.min_qty !== null ? b.min_qty : -1;
                return rev ? bv - av : av - bv;
            });
        } else if (field === 'qty_forecast') {
            rows.sort((a, b) => {
                const av = a.qty_forecast !== null ? a.qty_forecast : -999999;
                const bv = b.qty_forecast !== null ? b.qty_forecast : -999999;
                return rev ? bv - av : av - bv;
            });
        } else if (field === 'rotation') {
            rows.sort((a, b) => {
                const av = a.rotation_days !== null ? a.rotation_days : 999999;
                const bv = b.rotation_days !== null ? b.rotation_days : 999999;
                return rev ? bv - av : av - bv;
            });
        } else if (field === 'status') {
            rows.sort((a, b) => {
                const av = a.is_broken ? 0 : !a.has_min ? 1 : 2;
                const bv = b.is_broken ? 0 : !b.has_min ? 1 : 2;
                return rev ? bv - av : av - bv;
            });
        } else {
            rows.sort((a, b) => {
                const av = a.is_broken ? 0 : !a.has_min ? 1 : 2;
                const bv = b.is_broken ? 0 : !b.has_min ? 1 : 2;
                return av - bv;
            });
        }

        // Paginación
        const offset = (Math.max(1, this.state.page) - 1) * this.state.pageSize;
        this.state.products = rows.slice(offset, offset + this.state.pageSize);
    }

    /**
     * Abre o cierra el dropdown de selección de ubicaciones.
     * Llama a `stopPropagation` para evitar que el listener global lo cierre
     * inmediatamente después de abrirlo. Resetea `locSearch` al abrir.
     * @param {MouseEvent} ev - Evento de clic sobre el botón del dropdown
     */
    toggleLocDropdown(ev) {
        ev.stopPropagation();
        this.state.locDropdownOpen = !this.state.locDropdownOpen;
        if (this.state.locDropdownOpen) this.state.locSearch = "";
    }

    /**
     * Lista de ubicaciones internas filtradas por el texto de búsqueda del dropdown.
     * Retorna todas las ubicaciones si `locSearch` está vacío.
     * @returns {Array<{id: number, name: string}>} Ubicaciones que coinciden con la búsqueda
     */
    get filteredLocations() {
        const q = this.state.locSearch.toLowerCase();
        if (!q) return this.state.locations;
        return this.state.locations.filter(l => l.name.toLowerCase().includes(q));
    }

    get visibleStockCols() {
        return this.colsStock.visibleCols().filter(col => {
            if (col.key === 'rotation') return this.state.show_rotation;
            return true;
        });
    }

    /**
     * Agrega o quita una ubicación del filtro activo según el checkbox marcado.
     * Lee el id desde `data-loc-id` del elemento disparador. Resetea la página a 1
     * y recarga los datos.
     * @param {MouseEvent} ev - Evento de cambio del checkbox de ubicación
     */
    toggleLocation(ev) {
        const id = parseInt(ev.target.dataset.locId);
        const ids = this.state.locationIds;
        this.state.locationIds = ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id];
        this.state.page = 1;
        this._load();
    }

    /**
     * Elimina todos los filtros de ubicación activos, resetea la página a 1
     * y recarga los datos para mostrar todas las ubicaciones.
     */
    clearLocFilter() {
        this.state.locationIds = [];
        this.state.page = 1;
        this._load();
    }

    /**
     * Texto resumen del filtro de ubicaciones activo para mostrar en el botón del dropdown.
     * - Sin selección → "Todas las ubicaciones"
     * - Una seleccionada → nombre de la ubicación
     * - Varias → "N ubicaciones"
     * @returns {string} Etiqueta descriptiva del filtro de ubicación actual
     */
    get selectedLocLabel() {
        const ids = this.state.locationIds;
        if (!ids.length) return 'Todas las ubicaciones';
        if (ids.length === 1) {
            const loc = this.state.locations.find(l => l.id === ids[0]);
            return loc ? loc.name : 'Todas las ubicaciones';
        }
        return `${ids.length} ubicaciones`;
    }

    /**
     * Maneja el evento `input` del campo de búsqueda nativo.
     * Actualiza `state.search` de forma inmediata para reflejar el texto en la UI
     * y aplana la recarga mediante debounce de 300 ms.
     * @param {InputEvent} ev - Evento de entrada del campo de búsqueda
     */
    onSearchInput(ev) {
        const val = ev.target.value;
        this.state.search = val;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
            this.state.page = 1;
            this._load();
        }, 300);
    }

    /**
     * Establece el texto de búsqueda programáticamente (usado por `PlannerSearchBar`)
     * y dispara la recarga con debounce de 300 ms.
     * @param {string} text - Texto de búsqueda a aplicar
     */
    setSearch(text) {
        this.state.search = text;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
            this.state.page = 1;
            this._load();
        }, 300);
    }

    /**
     * Cambia el filtro de tipo directamente por clave (usado desde botones KPI del template).
     * Si la clave está vacía o es undefined, normaliza a 'all'.
     * Evita recargar si el filtro ya estaba activo.
     * @param {string} key - Clave del filtro: 'all' | 'broken' | 'ok' | 'no_min'
     */
    setFilterDirect(key) {
        const f = key || 'all';
        if (this.state.filterType === f) return;
        this.state.filterType = f;
        this.state.page = 1;
        this._applyClientSort();
    }

    /**
     * Maneja el evento `change` del selector `<select>` de filtro de tipo.
     * Evita recargar si el filtro seleccionado ya estaba activo.
     * @param {Event} ev - Evento change del elemento select
     */
    onFilterChange(ev) {
        const f = ev.target.value;
        if (this.state.filterType === f) return;
        this.state.filterType = f;
        this.state.page = 1;
        this._applyClientSort();
    }

    /**
     * Cambia el filtro de tipo programáticamente. Alias semántico de `setFilterDirect`
     * para uso desde el template con t-on-click, sin normalización de falsy.
     * @param {string} f - Clave del filtro: 'all' | 'broken' | 'ok' | 'no_min'
     */
    setFilter(f) {
        if (this.state.filterType === f) return;
        this.state.filterType = f;
        this.state.page = 1;
        this._applyClientSort();
    }

    /**
     * Ordena la tabla por el campo indicado. Si el campo ya era el activo,
     * invierte la dirección (asc ↔ desc); si es diferente, inicia en 'asc'.
     * Resetea la página a 1 y recarga los datos.
     * @param {string} field - Clave de ordenamiento (sortKey) de la columna
     */
    sortBy(field) {
        if (this.state.sortField === field) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortField = field;
            this.state.sortDir   = "asc";
        }
        this.state.page = 1;
        this._applyClientSort();
    }

    /**
     * Devuelve la clase CSS de Font Awesome correspondiente al estado de ordenamiento
     * de una columna: icono neutro si no es la columna activa, flecha arriba/abajo si lo es.
     * @param {string} field - Clave de la columna a evaluar
     * @returns {string} Clases CSS para el ícono de ordenamiento
     */
    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    /** Total de páginas calculado a partir de `totalFiltered` y `pageSize`. Mínimo 1.
     * @returns {number} Número total de páginas disponibles */
    get totalPages()  { return Math.max(1, Math.ceil(this.state.totalFiltered / this.state.pageSize)); }
    /** Indica si existe una página siguiente a la actual.
     * @returns {boolean} */
    get hasNextPage() { return this.state.page < this.totalPages; }
    /** Indica si existe una página anterior a la actual.
     * @returns {boolean} */
    get hasPrevPage() { return this.state.page > 1; }
    /** Avanza a la siguiente página y recarga los datos si es posible. */
    nextPage() { if (this.hasNextPage) { this.state.page++; this._applyClientSort(); } }
    /** Retrocede a la página anterior y recarga los datos si es posible. */
    prevPage() { if (this.hasPrevPage) { this.state.page--; this._applyClientSort(); } }

    /**
     * Formatea un número con separador de miles y hasta 2 decimales en locale es-AR.
     * Trata `null`, `undefined` y `NaN` como 0.
     * @param {number|null|undefined} n - Valor numérico a formatear
     * @returns {string} Número formateado, ej. "1.234,56"
     */
    fmt(n) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(n || 0);
    }

    fmtRotation(p) {
        if (this.state.rotation_unit === 'months') {
            const v = p.rotation_months;
            return v !== null && v !== undefined ? `${v} m` : '—';
        }
        const v = p.rotation_days;
        return v !== null && v !== undefined ? `${v} d` : '—';
    }

    rotClass(p) {
        const days = p.rotation_days;
        if (days === null || days === undefined) return 'text-muted';
        const warn = this.state.rotation_warn_days;
        const crit = this.state.rotation_critical_days;
        if (warn === null && crit === null) return '';
        if (crit !== null && days > crit) return 'text-danger';
        if (warn !== null && days > warn) return 'text-warning';
        return 'text-success';
    }

    rotTooltipStock(prod) {
        const method = this.state.rotation_method;
        const unit   = this.state.rotation_unit;
        const months = this.state.rotation_months;
        const val    = this.fmtRotation(prod);
        const warn   = this.state.rotation_warn_days;
        const crit   = this.state.rotation_critical_days;

        const thresholds = (warn || crit)
            ? '\n' + [crit ? `Rojo > ${crit} d` : null, warn ? `Amarillo > ${warn} d` : null].filter(Boolean).join(' | ')
            : '';

        if (!val || val === '—') {
            if (method === 'cogs')  return 'Sin inventario promedio valorizado — rotación no calculable';
            if (method === 'sales') return 'Sin ventas o sin inventario valorizado — rotación no calculable';
            return `Sin salidas en los últimos ${months * 30} días — rotación no calculable`;
        }

        if (method === 'cogs') {
            const formula = `Período × inventario promedio (costo) ÷ costo de lo vendido`;
            const calc = (prod.rotation_avg_inv != null && prod.rotation_base != null)
                ? `→ ${months * 30} d × $ ${this.fmt(prod.rotation_avg_inv)} ÷ $ ${this.fmt(prod.rotation_base)} = ${val}`
                : `→ ${months * 30} d × inv. promedio ÷ costo vendido = ${val}`;
            return formula + '\n' + calc + thresholds;
        }

        if (method === 'sales') {
            const formula = `Período × inventario promedio (costo) ÷ ventas netas`;
            const calc = (prod.rotation_avg_inv != null && prod.rotation_base != null)
                ? `→ ${months * 30} d × $ ${this.fmt(prod.rotation_avg_inv)} ÷ $ ${this.fmt(prod.rotation_base)} = ${val}`
                : `→ ${months * 30} d × inv. promedio ÷ ventas netas = ${val}`;
            return formula + '\n' + calc + thresholds;
        }

        // units
        const suffix = unit !== 'months' ? ' × 30' : '';
        const formula = `Stock promedio ÷ (salidas del período ÷ meses)${suffix}`;
        const calc = `→ ${this.fmt(prod.rotation_avg_stock)} ÷ (${this.fmt(prod.rotation_period_out)} ÷ ${months})${suffix} = ${val}`;
        return formula + '\n' + calc + thresholds;
    }

    /**
     * Abre el formulario del producto `product.product` al hacer clic en una fila.
     * Lee el id desde el atributo `data-product-id` del `<tr>` ancestro del elemento
     * disparador. No hace nada si no encuentra el atributo.
     * @param {MouseEvent} ev - Evento de clic dentro de la fila de tabla
     */
    openProductFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.productId;
        if (!id) return;
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "product.product",
            res_id:    parseInt(id),
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    /**
     * Expande o colapsa el acordeón de órdenes de fabricación activas de un producto.
     * Si se abre por primera vez y no hay datos en caché, llama al RPC
     * `get_product_mos_for_stock_break` para obtener las OFs del producto.
     * Usa `stopPropagation` para evitar que el clic propague a la fila y abra el formulario.
     * @param {{ id: number }} prod - Objeto de producto de la tabla (debe tener `id`)
     * @param {MouseEvent} ev - Evento de clic sobre el botón de expandir
     * @returns {Promise<void>}
     */
    async toggleAccordion(prod, ev) {
        ev.stopPropagation();
        const pid = prod.id;
        const wasOpen = !!this.state.expandedProducts[pid];
        this.state.expandedProducts = { ...this.state.expandedProducts, [pid]: !wasOpen };
        if (!wasOpen && !this.state.mosByProduct[pid]) {
            this.state.mosLoading = { ...this.state.mosLoading, [pid]: true };
            try {
                const mos = await this.orm.call(
                    'mrp.planner.dashboard',
                    'get_product_mos_for_stock_break',
                    [pid],
                );
                this.state.mosByProduct = { ...this.state.mosByProduct, [pid]: mos };
            } catch (e) {
                console.error('[StockBreakWidget] accordion error', e);
                this.state.mosByProduct = { ...this.state.mosByProduct, [pid]: [] };
            } finally {
                this.state.mosLoading = { ...this.state.mosLoading, [pid]: false };
            }
        }
    }

    /**
     * Abre el formulario de una orden de fabricación `mrp.production` en la vista actual.
     * @param {number} moId - ID de la orden de fabricación a abrir
     */
    openMo(moId) {
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'mrp.production',
            res_id:    moId,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    /**
     * Devuelve las clases CSS Bootstrap para el badge de estado de una OF.
     * Estados reconocidos: 'confirmed' (info), 'progress' (primary), 'to_close' (warning).
     * Cualquier otro estado recibe 'bg-secondary'.
     * @param {string} state - Estado de la orden de fabricación
     * @returns {string} Clases CSS del badge, ej. "badge bg-info text-dark"
     */
    moStateBadge(state) {
        const map = {
            confirmed: 'bg-info text-dark',
            progress:  'bg-primary',
            to_close:  'bg-warning text-dark',
        };
        return `badge ${map[state] || 'bg-secondary'}`;
    }

    /**
     * Abre la vista de configuración de reprogramación del planificador MRP
     * usando la acción XML `action_mrp_reschedule_config`.
     * @returns {Promise<void>}
     */
    async openConfig() {
        await this.action.doAction('odoo_mrp_planner.action_mrp_reschedule_config');
    }

    stockKpiTooltip(key) {
        const k = this.state.kpis;
        const f = n => this.fmt(n);
        switch (key) {
            case 'total':
                return `Artículos con venta habilitada en los tipos de producto configurados\n→ ${f(k.total)} productos vendibles`;
            case 'broken':
                return `Productos con stock actual menor que la cantidad mínima del punto de reorden con ruta Fabricación\n→ ${f(k.broken)} de ${f(k.total - k.no_min)} con reorden`;
            case 'ok':
                return `Productos con punto de reorden activo y stock actual mayor o igual al mínimo configurado\n→ ${f(k.ok)} de ${f(k.total - k.no_min)} con reorden`;
            case 'no_min':
                return `Artículos vendibles sin punto de reorden configurado con ruta Fabricación\n→ ${f(k.no_min)} de ${f(k.total)} productos sin mínimo`;
        }
        return '';
    }

    statusTooltip(prod) {
        const f = n => this.fmt(n);
        if (prod.qty < prod.min_qty) {
            return `Stock disponible menor que el mínimo del punto de reorden\n→ Stock: ${f(prod.qty)} | Mínimo: ${f(prod.min_qty)}`;
        }
        if (prod.min_qty !== null && prod.min_qty !== undefined) {
            return `Stock disponible mayor o igual al mínimo del punto de reorden\n→ Stock: ${f(prod.qty)} | Mínimo: ${f(prod.min_qty)}`;
        }
        return 'Sin punto de reorden con ruta Fabricación';
    }
}

registry.category("view_widgets").add("stock_break_widget", {
    component: StockBreakWidget,
});
