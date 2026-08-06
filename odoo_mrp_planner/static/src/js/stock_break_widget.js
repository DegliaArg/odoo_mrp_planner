/** @odoo-module **/

/**
 * @description Widget de roturas de stock por ubicación/almacén.
 *   Filtra por tipo (all/broken/ok/no_min) y búsqueda por nombre, todo client-side,
 *   y por una o varias ubicaciones internas.
 * @fires RPC mrp.planner.dashboard.get_internal_locations — ubicaciones internas disponibles
 * @fires RPC mrp.planner.dashboard.get_stock_break_data — productos con rotura/sin mínimo
 *   Params: (search, locationIds) — el filtrado por tipo, ordenamiento y paginación
 *   se aplican client-side sobre la lista completa devuelta.
 *   @returns {{ kpis: {total,broken,ok,no_min}, products: ProductRow[],
 *              location_name: string }} más flags de configuración (rotación, cat. venta)
 * @listens onMounted — carga ubicaciones y datos iniciales
 * @listens onWillUnmount — cancela timer de debounce de búsqueda
 */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useColManager } from "./column_manager";
import { PlannerSearchBar } from "./planner_search_bar";
import { saleCatBadge } from "./forecast_formatters";
import { restoreFilters, saveFilters } from "./filter_persistence";

// Estado de filtros que sobrevive al remontaje del widget (volver de una sublista)
// y a la sesión del navegador.
const STOCK_PERSIST_KEYS = [
    'filterType', 'search', 'locationIds',
    'sortField', 'sortDir', 'page', 'pageSize',
    'groupBy', 'selectedGroup',
];

const STOCK_COLS = [
    { key: '_expand',      label: '',             width:  32, fixed: true, noResize: true, title: 'Expandir para ver OFs activas' },
    { key: 'name',         label: 'Artículo',     width: 200, sortKey: 'name',           title: 'Nombre o código del producto.' },
    { key: 'product_types',label: 'Tipo',         width: 130,                             title: 'Tipos de producto asignados en la ficha del artículo.' },
    { key: 'sale_category',label: 'Cat. venta',   width:  75, sortKey: 'sale_category',   align: 'center', title: 'Categoría de venta A–E asignada al artículo.' },
    { key: 'categ_name',   label: 'Categoría',    width: 120, sortKey: 'categ_name',      title: 'Categoría de producto de Odoo.' },
    { key: 'qty',          label: 'Stock actual', width:  95, sortKey: 'qty',             align: 'end', title: 'Cantidad disponible en las ubicaciones seleccionadas.' },
    { key: 'min_qty',      label: 'Mínimo',       width:  85, sortKey: 'min_qty',         align: 'end', title: 'Cantidad mínima del punto de reorden con ruta Fabricación.' },
    { key: 'qty_forecast', label: 'Pronóstico',   width:  95, sortKey: 'qty_forecast',    align: 'end', title: 'Cantidad pronosticada (qty_forecast): stock actual + entradas pendientes − salidas pendientes.' },
    { key: 'bom_lead',     label: 'Plazo fab.',   width:  85, sortKey: 'bom_lead',        align: 'end', title: 'Plazo total de fabricación según BoM de manufactura (fabricación + preparación de componentes). Tiempo estimado para reponer stock por producción.' },
    { key: 'rotation',     label: 'Rot.',         width:  75, sortKey: 'rotation',        align: 'end', title: 'Rotación = stock promedio del período ÷ promedio mensual de salidas × 30. Período configurable en Ajustes.' },
    { key: 'status',       label: 'Estado',       width: 115, sortKey: 'status',          align: 'center', title: 'Quiebre: stock menor que mínimo | OK: stock mayor o igual al mínimo | Sin mínimo: sin punto de reorden configurado. Los días en quiebre se estiman a partir del historial de movimientos de salida.' },
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
            loadError:        null,
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
            show_sale_cat:          false,
            sale_cat_mode:            'manual',
            sale_cat_lookback_months: 3,
            sale_cat_rotation_source: 'delivery',
            rotation_warn_days:     null,
            rotation_critical_days: null,
            groupBy:                null,
            selectedGroup:          null,
            expandedProducts: {},
            mosByProduct:     {},
            mosLoading:       {},
            selected:         {},
        });
        this.colsStock = useColManager('stock_break', STOCK_COLS);

        // Restaurar filtros de la última visita (por empresa). Se guarda en cada
        // _applyClientSort(), el punto único por el que pasa todo cambio de filtro.
        const companyId = this.env.services.company?.currentCompany?.id || 0;
        this._persistKey = `stock_break.${companyId}`;
        restoreFilters(this._persistKey, this.state, STOCK_PERSIST_KEYS);

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
        try {
            const [locs] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_internal_locations", []),
                this._load(),
            ]);
            this.state.locations = locs;
        } catch (e) {
            if (e.message !== "Component is destroyed") throw e;
        }
    }

    /** @returns {Promise<void>} Carga todos los productos del servidor y aplica sort/filtro/paginación client-side */
    async _load() {
        const seq = ++this._loadSeq;
        this.state.loading   = true;
        this.state.loadError = null;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_stock_break_data",
                // La búsqueda por texto es client-side (como clientes/ventas): se carga
                // el dataset completo una sola vez y se filtra en JS sin recargar.
                [null, this.state.locationIds.length ? this.state.locationIds : null],
            );
            if (seq !== this._loadSeq) return;
            if (d.error === "no_location") {
                this.state.error = "no_location";
            } else {
                this.state.error        = null;
                this.state.kpis         = d.kpis;
                this.state.locationName = d.location_name;
                this.state.allProducts  = d.products;
                this.state.selected     = {};
                this.state.rotation_unit          = d.rotation_unit          || 'days';
                this.state.show_rotation          = !!d.show_rotation;
                this.state.show_sale_cat          = !!d.show_sale_cat;
                this.state.sale_cat_mode            = d.sale_cat_mode            || 'manual';
                this.state.sale_cat_lookback_months = d.sale_cat_lookback_months || 3;
                this.state.sale_cat_rotation_source = d.sale_cat_rotation_source || 'delivery';
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
            this.state.loadError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            if (seq === this._loadSeq) this.state.loading = false;
        }
    }

    /**
     * Devuelve el dataset completo con filtro de tipo, sort y filtro de tab activo
     * aplicados (sin paginar). Base común de la tabla visible y del export CSV.
     * @returns {Array<Object>} Filas filtradas y ordenadas
     */
    _filteredSortedRows(skipTypeFilter = false) {
        let rows = [...this.state.allProducts];

        // Filtro por texto (client-side): el name incluye la referencia interna [REF].
        const q = (this.state.search || '').trim().toLowerCase();
        if (q) rows = rows.filter(r => (r.name || '').toLowerCase().includes(q));

        // Filtro de tipo (omitible: las cards KPI son los selectores de
        // segmento y sus conteos no deben auto-filtrarse)
        const f = skipTypeFilter ? 'all' : this.state.filterType;
        if      (f === 'broken') rows = rows.filter(r => r.is_broken);
        else if (f === 'ok')     rows = rows.filter(r => r.has_min && !r.is_broken);
        else if (f === 'no_min') rows = rows.filter(r => !r.has_min);

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
        } else if (field === 'bom_lead') {
            rows.sort((a, b) => {
                const av = a.bom_lead_days !== null && a.bom_lead_days !== undefined ? a.bom_lead_days : (rev ? -1 : 999999);
                const bv = b.bom_lead_days !== null && b.bom_lead_days !== undefined ? b.bom_lead_days : (rev ? -1 : 999999);
                return rev ? bv - av : av - bv;
            });
        } else if (field === 'status') {
            rows.sort((a, b) => {
                const av = a.is_broken ? 0 : !a.has_min ? 1 : 2;
                const bv = b.is_broken ? 0 : !b.has_min ? 1 : 2;
                return rev ? bv - av : av - bv;
            });
        } else if (field === 'sale_category' || field === 'categ_name') {
            rows.sort((a, b) => {
                const av = (a[field] || '').toLowerCase();
                const bv = (b[field] || '').toLowerCase();
                return rev ? bv.localeCompare(av, 'es') : av.localeCompare(bv, 'es');
            });
        } else {
            rows.sort((a, b) => {
                const av = a.is_broken ? 0 : !a.has_min ? 1 : 2;
                const bv = b.is_broken ? 0 : !b.has_min ? 1 : 2;
                return av - bv;
            });
        }

        // Filtro de tab activo (cuando groupBy está en uso)
        if (this.state.groupBy && this.state.selectedGroup !== null) {
            const gb = this.state.groupBy;
            if (gb === 'product_types') {
                // M2M: un artículo con varios tipos aparece en la pestaña de cada uno;
                // la pestaña '' agrupa los artículos sin tipo asignado.
                const sel = this.state.selectedGroup;
                rows = rows.filter(r => sel === ''
                    ? !(r.product_type_list || []).length
                    : (r.product_type_list || []).includes(sel));
            } else {
                rows = rows.filter(r => (r[gb] || '') === this.state.selectedGroup);
            }
        }

        return rows;
    }

    /**
     * Totales del dataset filtrado (todas las páginas, no solo la visible):
     * suma de stock/mínimo/pronóstico —como las listas de Odoo, sin distinguir
     * UdM— y promedio de plazo de fabricación y rotación sobre las filas con dato.
     * @returns {{count:number, qty:number, min_qty:number, qty_forecast:number,
     *            bom_lead_avg:number|null, rotation_avg:number|null}}
     */
    // ── Selección: recalcula KPIs y totales, igual que el Panel de Inventario ──

    toggleSelect(prod) {
        this.state.selected[prod.id] = !this.state.selected[prod.id];
    }
    get selectedRows() {
        return this._filteredSortedRows().filter(r => this.state.selected[r.id]);
    }
    // "Seleccionar todos" opera sobre la página visible
    get allSelected() {
        const rows = this.state.products;
        return rows.length > 0 && rows.every(r => this.state.selected[r.id]);
    }
    toggleSelectAll() {
        const target = !this.allSelected;
        for (const r of this.state.products) {
            this.state.selected[r.id] = target;
        }
    }
    clearSelection() {
        this.state.selected = {};
    }

    /** KPIs dinámicos: describen lo que muestra la tabla (búsqueda, depósito,
     *  pestaña activa y selección de filas), SIN el filtro de segmento — las
     *  cards son justamente los selectores de ese filtro. */
    get liveKpis() {
        const sel = Object.keys(this.state.selected).some(k => this.state.selected[k])
            ? this._filteredSortedRows(true).filter(r => this.state.selected[r.id])
            : this._filteredSortedRows(true);
        const k = { total: sel.length, broken: 0, ok: 0, no_min: 0 };
        for (const r of sel) {
            if (r.is_broken) k.broken++;
            else if (!r.has_min) k.no_min++;
            else k.ok++;
        }
        return k;
    }

    get stockTotals() {
        const sel = this.selectedRows;
        const rows = sel.length ? sel : this._filteredSortedRows();
        const t = { count: rows.length, qty: 0, min_qty: 0, qty_forecast: 0,
                    bom_lead_avg: null, rotation_avg: null };
        let leadSum = 0, leadN = 0, rotSum = 0, rotN = 0;
        for (const r of rows) {  // rows = selección si la hay, si no la tabla
            t.qty += r.qty || 0;
            if (r.has_min && r.min_qty !== null && r.min_qty !== undefined) t.min_qty += r.min_qty;
            if (r.qty_forecast !== null && r.qty_forecast !== undefined)    t.qty_forecast += r.qty_forecast;
            if (r.bom_lead_days !== null && r.bom_lead_days !== undefined) { leadSum += r.bom_lead_days; leadN++; }
            const rot = this.state.rotation_unit === 'months' ? r.rotation_months : r.rotation_days;
            if (rot !== null && rot !== undefined) { rotSum += rot; rotN++; }
        }
        if (leadN) t.bom_lead_avg = Math.round(leadSum / leadN);
        if (rotN)  t.rotation_avg = Math.round(rotSum / rotN * 10) / 10;
        return t;
    }

    /** Aplica filtro de tipo, sort, filtro de tab activo y paginación sobre `state.allProducts` */
    _applyClientSort() {
        // Con groupBy restaurado de otra sesión, la pestaña guardada puede ya no
        // existir en el dataset actual: caer a la primera disponible.
        if (this.state.groupBy && this.state.selectedGroup !== null) {
            const groups = this.allGroupsForTabs;
            if (groups && groups.length && !groups.some(g => g.key === this.state.selectedGroup)) {
                this.state.selectedGroup = groups[0].key;
            }
        }

        const rows = this._filteredSortedRows();
        this.state.totalFiltered = rows.length;

        // Paginación (si la página guardada quedó fuera de rango, volver a la 1)
        if ((Math.max(1, this.state.page) - 1) * this.state.pageSize >= rows.length && rows.length) {
            this.state.page = 1;
        }
        const offset = (Math.max(1, this.state.page) - 1) * this.state.pageSize;
        this.state.products = rows.slice(offset, offset + this.state.pageSize);

        saveFilters(this._persistKey, this.state, STOCK_PERSIST_KEYS);
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
            if (col.key === 'rotation')     return this.state.show_rotation;
            if (col.key === 'sale_category') return this.state.show_sale_cat;
            return true;
        });
    }

    get stockGroupByDefs() {
        const defs = [
            { key: 'categ_name',    label: 'Categoría' },
            { key: 'product_types', label: 'Tipo' },
        ];
        if (this.state.show_sale_cat) defs.push({ key: 'sale_category', label: 'Cat. venta' });
        return defs;
    }

    onGroupByChange(k) {
        this.state.groupBy = k;
        this.state.page = 1;
        if (k) {
            const groups = this.allGroupsForTabs;
            this.state.selectedGroup = groups && groups.length ? groups[0].key : null;
        } else {
            this.state.selectedGroup = null;
        }
        this._applyClientSort();
    }

    setGroup(key) {
        this.state.selectedGroup = key;
        this.state.page = 1;
        this._applyClientSort();
    }

    get baseFilteredForGroups() {
        let rows = [...this.state.allProducts];
        const f = this.state.filterType;
        if      (f === 'broken') rows = rows.filter(r => r.is_broken);
        else if (f === 'ok')     rows = rows.filter(r => r.has_min && !r.is_broken);
        else if (f === 'no_min') rows = rows.filter(r => !r.has_min);
        return rows;
    }

    get allGroupsForTabs() {
        const gb = this.state.groupBy;
        if (!gb) return null;
        const counts = new Map();
        for (const row of this.baseFilteredForGroups) {
            if (gb === 'product_types') {
                // M2M: el artículo cuenta en cada uno de sus tipos, por lo que la suma
                // de las pestañas puede superar el total de artículos.
                const types = row.product_type_list || [];
                if (!types.length) counts.set('', (counts.get('') || 0) + 1);
                for (const t of types) counts.set(t, (counts.get(t) || 0) + 1);
                continue;
            }
            const key = row[gb] || '';
            counts.set(key, (counts.get(key) || 0) + 1);
        }
        const entries = [...counts.entries()];
        if (gb === 'sale_category') {
            const ORDER = ['A', 'B', 'C', 'D', 'E', ''];
            entries.sort((a, b) => {
                const ia = ORDER.indexOf(a[0]);
                const ib = ORDER.indexOf(b[0]);
                return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
            });
        } else {
            entries.sort((a, b) => a[0].localeCompare(b[0], 'es', { sensitivity: 'base' }));
        }
        const emptyLabel = gb === 'product_types' ? 'Sin tipo' : 'Sin categoría';
        return entries.map(([key, count]) => ({ key, label: key || emptyLabel, count }));
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
        if (!ids.length) return 'Todos los depósitos';
        if (ids.length === 1) {
            const loc = this.state.locations.find(l => l.id === ids[0]);
            return loc ? loc.name : 'Todos los depósitos';
        }
        return `${ids.length} depósitos`;
    }

    /**
     * Maneja el evento `input` del campo de búsqueda nativo.
     * Filtra el dataset ya cargado en el cliente (sin RPC), como clientes/ventas.
     * @param {InputEvent} ev - Evento de entrada del campo de búsqueda
     */
    onSearchInput(ev) {
        this.setSearch(ev.target.value);
    }

    /**
     * Establece el texto de búsqueda programáticamente (usado por `PlannerSearchBar`)
     * y dispara la recarga con debounce de 300 ms.
     * @param {string} text - Texto de búsqueda a aplicar
     */
    setSearch(text) {
        // Filtro client-side sobre el dataset ya cargado: sin RPC ni recarga.
        this.state.search = text;
        this.state.page = 1;
        this._applyClientSort();
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
     * Botón "Ver" de un KPI: abre la lista de productos (product.product) del
     * estado correspondiente al KPI presionado, con los IDs ya calculados en el
     * widget. A diferencia de setFilter (que filtra la tabla en el lugar), esto
     * navega a una lista real de Odoo.
     * @param {string} kind - 'all' | 'broken' | 'ok' | 'no_min'
     */
    openKpiProducts(kind) {
        const all = this.state.allProducts || [];
        let rows = all;
        let name = 'Productos';
        if      (kind === 'broken') { rows = all.filter(r => r.is_broken);              name = 'Productos en quiebre'; }
        else if (kind === 'ok')     { rows = all.filter(r => r.has_min && !r.is_broken); name = 'Productos con stock OK'; }
        else if (kind === 'no_min') { rows = all.filter(r => !r.has_min);               name = 'Productos sin mínimo'; }
        const ids = rows.map(r => r.id);
        this.action.doAction({
            type:      'ir.actions.act_window',
            name,
            res_model: 'product.product',
            views:     [[false, 'list'], [false, 'form']],
            target:    'current',
            domain:    [['id', 'in', ids]],
        });
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

    /**
     * Clases del badge de categoría de venta A–E. Delegado a forecast_formatters
     * para usar la misma paleta en todos los widgets del planificador.
     * @param {string} cat - Categoría 'A'…'E'
     * @returns {string} Clases Bootstrap del badge
     */
    saleCatBadge(cat) { return saleCatBadge(cat); }

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
            if ((prod.rotation_period_out || 0) > 0) {
                return `Hubo salidas (${this.fmt(prod.rotation_period_out)}) pero el stock promedio del período fue 0 — rotación no calculable (posible quiebre permanente o venta directa sin stock).`;
            }
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

    rotHeaderTooltip() {
        const METHOD_LABELS = {
            units: 'por unidades (días de cobertura)',
            cogs:  'por COGS — período × inv. promedio (costo) ÷ costo vendido',
            sales: 'por ventas — período × inv. promedio (costo) ÷ ventas netas',
        };
        const method = this.state.rotation_method;
        const months = this.state.rotation_months;
        return `Rotación de inventario — configuración activa:\n`
             + `• Método: ${METHOD_LABELS[method] || method}\n`
             + `• Período: ${months} meses\n`
             + `• Fuente: entregas reales (consumo físico)`;
    }

    saleCatTooltip() {
        const MODE_LABELS = {
            automatic: 'rotación de inventario',
            demand:    'demanda mensual promedio',
            share:     'participación acumulada (Pareto)',
            manual:    'asignación manual',
        };
        const SRC_LABELS = {
            delivery: 'entregas completadas',
            demand:   'demanda OV confirmada',
        };
        const mode    = this.state.sale_cat_mode;
        const months  = this.state.sale_cat_lookback_months;
        const src     = this.state.sale_cat_rotation_source;
        let text = `Categoría de venta (A–E) — valor almacenado, calculado con:\n`
                 + `• Método: ${MODE_LABELS[mode] || mode}`;
        if (mode !== 'manual') {
            text += `\n• Período: ${months} meses`;
        }
        if (mode === 'automatic') {
            text += `\n• Base: ${SRC_LABELS[src] || src}`;
        }
        text += `\n\nNo se recalcula con el período/método de rotación de esta tabla.\nPara recalcular: Ajustes → Categorías de venta → Calcular ahora.`;
        return text;
    }

    colHeaderTitle(col) {
        if (col.key === 'rotation') return this.rotHeaderTooltip();
        return col.title || col.label;
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

    /**
     * Exporta el dataset completo filtrado (post-sort/filtro, sin paginar) como archivo CSV.
     * Usa las columnas visibles del gestor de columnas para determinar headers y keys.
     * Omite la columna '_expand' (control de acordeón). Descarga el archivo directamente
     * en el navegador sin requerir intervención del servidor.
     */
    downloadExport() {
        const rows = this._filteredSortedRows();
        if (!rows || !rows.length) return;
        const visibleCols = this.colsStock.visibleCols().filter(col => {
            if (col.key === 'rotation')      return this.state.show_rotation;
            if (col.key === 'sale_category') return this.state.show_sale_cat;
            return true;
        });
        const headers = visibleCols.map(c => c.label).filter(Boolean);
        const colKeys = visibleCols.map(c => c.key);
        const lines = [headers.join(',')];
        for (const row of rows) {
            const vals = colKeys.map(key => {
                if (key === '_expand') return '';
                let v;
                if (key === 'rotation') {
                    // Mismo valor que la celda visible ("N d" / "N m"); vacío si no calculable
                    const r = this.fmtRotation(row);
                    v = r === '—' ? '' : r;
                } else if (key === 'bom_lead') {
                    v = row.bom_lead_days ?? '';
                } else if (key === 'status') {
                    // Replica el estado derivado de la tabla visible
                    v = row.is_broken ? 'Quiebre' : row.has_min ? 'OK' : 'Sin mínimo';
                } else {
                    v = row[key] ?? '';
                }
                const s = String(v);
                return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
            });
            lines.push(vals.join(','));
        }
        const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'quiebres_stock.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    stockKpiTooltip(key) {
        const k = this.liveKpis;
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

    breakLabel(prod) {
        if (prod.break_days === null || prod.break_days === undefined) return 'Quiebre';
        if (prod.break_days === 0) return 'Quiebre · hoy';
        return `Quiebre · ${prod.break_days} d`;
    }

    bomLeadTooltip(prod) {
        if (prod.bom_lead_days === null || prod.bom_lead_days === undefined) {
            return 'Sin BoM';
        }
        return `Plazo total de fabricación según BoM de manufactura\n→ ${prod.bom_lead_days} d (fabricación + preparación de componentes)`;
    }

    statusTooltip(prod) {
        const f = n => this.fmt(n);
        if (prod.qty < prod.min_qty) {
            let msg = `Stock disponible menor que el mínimo del punto de reorden\n→ Stock: ${f(prod.qty)} | Mínimo: ${f(prod.min_qty)}`;
            if (prod.break_days !== null && prod.break_days !== undefined) {
                msg += prod.break_days === 0
                    ? '\n→ Quiebre detectado hoy (aprox.)'
                    : `\n→ En quiebre hace ${prod.break_days} día${prod.break_days === 1 ? '' : 's'} (aprox.)`;
            } else {
                msg += '\n→ Sin movimientos de salida registrados — fecha de inicio no determinable';
            }
            return msg;
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
