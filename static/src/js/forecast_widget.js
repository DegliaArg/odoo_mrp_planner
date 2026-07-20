/**
 * @widget ForecastWidget
 * @description Widget de dashboard de forecast de producción. Muestra una tabla
 * mensualizada por producto con demanda forecast, cobertura de órdenes de fabricación
 * (OFs), entregas reales, stock actual, rotación y categoría ABC de ventas.
 * Permite filtrar por período, depósito, producto y agrupar por categoría.
 *
 * Métodos RPC que consume:
 *   - get_warehouses_for_forecast([]) → [{ id: Number, name: String }]
 *   - get_forecast_dashboard_data(periodFrom, periodTo, warehouseIds) → {
 *       months: String[],        // array de "YYYY-MM"
 *       rows: Object[],          // una fila por producto
 *       kpis: Object,            // totales globales
 *       warning_pct: Number,     // umbral amarillo de cobertura
 *       acc_formula: String,     // fórmula de precisión activa
 *       rotation_unit: String,   // 'months' | 'days'
 *       mo_states: String[]      // estados de OF considerados activos
 *     }
 *   - get_product_mos_for_forecast(productId, periodFrom, periodTo, warehouseIds)
 *       → [{ id, name, state, date_planned, qty_production, product_uom_qty }]
 *   - get_forecast_export(periodFrom, periodTo, warehouseIds) → { url: String }
 *
 * Props esperados:
 *   - record: Object — registro del dashboard (opcional); se usa para leer `can_edit_forecast`
 */

/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PlannerSearchBar } from "./planner_search_bar";
import { useColManager } from "./column_manager";
import {
    moStateBadge, saleCatBadge, moCovPct, moCovPctCell, moCovPctRow,
    cellClassForPct, cellClassMonthly, cellClassTotal, cellClass, svcClass,
} from "./forecast_formatters";
import {
    moTooltip, svcTooltip, rotHeaderTitle, rotTooltip,
    covTooltip, covHeaderTitle, accGlobalTooltip, accTooltip,
    fcKpiTooltip, demandGapTooltip, mosGapTooltip, accSecondaryPills,
} from "./forecast_tooltips";
import { downloadForecastExcel } from "./forecast_export";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

const FC_STATIC_COLS = [
    { key: 'product',      label: 'Artículo', width: 200, fixed: true, align: 'start' },
    { key: 'saleCategory', label: 'Cat.',      width:  55, align: 'center' },
    { key: 'productCateg', label: 'Familia',   width: 120, align: 'start' },
    { key: 'productTypes', label: 'Tipo',      width: 120, align: 'start' },
    { key: 'stock',        label: 'Stock',     width:  80, align: 'end' },
    { key: 'rotation',     label: 'Rot.',      width:  75, align: 'end' },
    { key: 'coverage',     label: 'Cob.',      width:  75, align: 'end' },
    { key: 'demand',       label: 'Demanda',   width:  90, align: 'end' },
];

const FC_SORT_KEYS = {
    product:      'product',
    saleCategory: 'sale_category',
    productCateg: 'product_categ',
    productTypes: 'product_types',
    stock:        'stock_qty',
    rotation:     'rotation_days',
    coverage:     'coverage_days',
    demand:       'total_so_demand',
};

/**
 * Convierte una clave "YYYY-MM" en una etiqueta legible en español, p. ej. "Ene 2025".
 * @param {string} ym - Clave de mes en formato "YYYY-MM".
 * @returns {string} Etiqueta del mes, p. ej. "Mar 2025".
 */
function monthLabel(ym) {
    const [y, m] = ym.split('-');
    return `${MONTHS_ES[parseInt(m) - 1]} ${y}`;
}

/**
 * Devuelve la fecha de hoy en formato "YYYY-MM-DD".
 * @returns {string} Fecha de hoy.
 */
function todayYMD() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * A partir de una fecha "YYYY-MM-DD", avanza n meses y devuelve el último día
 * de ese mes resultante en formato "YYYY-MM-DD".
 * @param {string} ymd - Fecha de referencia en formato "YYYY-MM-DD".
 * @param {number} n   - Cantidad de meses a sumar.
 * @returns {string} Último día del mes destino en formato "YYYY-MM-DD".
 */
function addMonthsLastDayYMD(ymd, n) {
    const [y, m] = ymd.split('-').map(Number);
    // new Date(y, m-1+n+1, 0) retorna el día 0 del mes siguiente, que equivale al último día del mes destino
    const last = new Date(y, m - 1 + n + 1, 0);
    return `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`;
}

/**
 * Devuelve el primer día del mes actual en formato "YYYY-MM-DD".
 * @returns {string} Primer día del mes en curso.
 */
function firstOfMonthYMD() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

/**
 * Devuelve el último día del mes actual en formato "YYYY-MM-DD".
 * @returns {string} Último día del mes en curso.
 */
function lastOfMonthYMD() {
    const d = new Date();
    // day 0 del mes siguiente = último día del mes actual
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`;
}

class ForecastWidget extends Component {
    static template = "odoo_mrp_planner.ForecastWidget";
    static components = { PlannerSearchBar };
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm       = useService("orm");
        this.action    = useService("action");
        this.cols      = useColManager('forecast_static', FC_STATIC_COLS);
        this.fcSortKeys = FC_SORT_KEYS;

        this.state = useState({
            loading:            true,
            periodFrom:         firstOfMonthYMD(),
            periodTo:           lastOfMonthYMD(),
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
                forecast:         true,
                mos:              true,
                delivered:        true,
                demand_delivered: true,
                stock:            true,
                rotation:      true,
                coverage:      true,
                total:         true,
                saleCategory:  false,
                productCateg:  false,
                productTypes:  false,
                demand:        false,
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

        this._loadDebounceTimer = null;
        this._loadDebounced = () => {
            clearTimeout(this._loadDebounceTimer);
            this._loadDebounceTimer = setTimeout(() => this._load(), 400);
        };

        onMounted(() => {
            this._init();
            document.addEventListener('click', this._closeAll);
        });
        onWillUnmount(() => {
            document.removeEventListener('click', this._closeAll);
            clearTimeout(this._loadDebounceTimer);
        });
    }

    /**
     * Inicializa el widget: carga en paralelo la lista de depósitos disponibles
     * y los datos de forecast, y sincroniza el permiso de edición desde el record padre.
     * @returns {Promise<void>}
     */
    async _init() {
        try {
            const [whs] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_warehouses_for_forecast", []),
                this._load(),
            ]);
            this.state.warehouses = whs;
            const rec = this.props.record;
            if (rec && rec.data) {
                this.state.canEdit = rec.data.can_edit_forecast;
            }
        } catch (e) {
            if (e.message !== "Component is destroyed") throw e;
        }
    }

    /**
     * Carga (o recarga) los datos de forecast desde el servidor.
     * Resetea la paginación y los acordeones abiertos para evitar inconsistencias
     * con un dataset anterior.
     * @returns {Promise<void>}
     */
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

    /**
     * Maneja el cambio en el campo "Desde" del período.
     * Si la nueva fecha supera el "Hasta", arrastra el "Hasta" para mantener rango válido.
     * Dispara una recarga con debounce para no saturar el servidor mientras el usuario escribe.
     * @param {Event} ev - Evento change del input de fecha.
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
     * Maneja el cambio en el campo "Hasta" del período.
     * Si la nueva fecha es anterior al "Desde", arrastra el "Desde" hacia atrás.
     * Dispara una recarga con debounce.
     * @param {Event} ev - Evento change del input de fecha.
     */
    onPeriodToChange(ev) {
        const val = ev.target.value;
        if (!val) return;
        this.state.periodTo = val;
        if (this.state.periodTo < this.state.periodFrom)
            this.state.periodFrom = this.state.periodTo;
        this._loadDebounced();
    }

    /**
     * Actualiza el texto de búsqueda de producto a medida que el usuario escribe
     * y resetea a la primera página para que el filtro sea inmediato.
     * @param {Event} ev - Evento input del campo de búsqueda.
     */
    onProductSearchInput(ev) {
        this.state.productSearch = ev.target.value;
        this.state.page = 1;
    }

    /**
     * Establece el texto de búsqueda de producto programáticamente
     * (p. ej. desde el componente PlannerSearchBar).
     * @param {string} text - Texto a buscar.
     */
    setSearch(text) {
        this.state.productSearch = text;
        this.state.page = 1;
    }

    /**
     * Alterna la visibilidad del dropdown de selección de depósitos.
     * Cierra todos los demás dropdowns para evitar que coexistan abiertos.
     * Al abrir, limpia el campo de búsqueda interno del dropdown.
     * @param {MouseEvent} ev - Evento click sobre el botón de depósitos.
     */
    toggleWhDropdown(ev) {
        ev.stopPropagation();
        const opening = !this.state.whDropdownOpen;
        this.state.whDropdownOpen     = opening;
        this.state.colsDropdownOpen   = false;
        this.state.filterDropdownOpen = false;
        this.state.groupDropdownOpen  = false;
        if (opening) this.state.whSearch = "";
    }

    /**
     * Alterna la visibilidad del dropdown de columnas visibles.
     * Cierra todos los demás dropdowns.
     * @param {MouseEvent} ev - Evento click sobre el botón de columnas.
     */
    toggleColsDropdown(ev) {
        ev.stopPropagation();
        this.state.colsDropdownOpen   = !this.state.colsDropdownOpen;
        this.state.whDropdownOpen     = false;
        this.state.whSearch           = "";
        this.state.filterDropdownOpen = false;
        this.state.groupDropdownOpen  = false;
    }

    /**
     * Alterna la visibilidad del dropdown de filtros rápidos.
     * Cierra todos los demás dropdowns.
     * @param {MouseEvent} ev - Evento click sobre el botón de filtros.
     */
    toggleFilterDropdown(ev) {
        ev.stopPropagation();
        this.state.filterDropdownOpen = !this.state.filterDropdownOpen;
        this.state.colsDropdownOpen   = false;
        this.state.whDropdownOpen     = false;
        this.state.whSearch           = "";
        this.state.groupDropdownOpen  = false;
    }

    /**
     * Alterna la visibilidad del dropdown de agrupación.
     * Cierra todos los demás dropdowns.
     * @param {MouseEvent} ev - Evento click sobre el botón de agrupar.
     */
    toggleGroupDropdown(ev) {
        ev.stopPropagation();
        this.state.groupDropdownOpen  = !this.state.groupDropdownOpen;
        this.state.colsDropdownOpen   = false;
        this.state.whDropdownOpen     = false;
        this.state.whSearch           = "";
        this.state.filterDropdownOpen = false;
    }

    /**
     * Activa o desactiva la visibilidad de una columna individual en la tabla.
     * @param {string} colKey - Clave de la columna, p. ej. 'forecast', 'mos', 'stock'.
     */
    toggleCol(colKey) {
        this.state.visibleCols[colKey] = !this.state.visibleCols[colKey];
    }

    /**
     * Aplica un filtro rápido sobre las filas de la tabla.
     * @param {string|null} key - Identificador del filtro: 'with_mos', 'no_mos', 'gap' o null para limpiar.
     */
    setFilter(key) {
        this.state.activeFilter = key;
        this.state.page = 1;
    }

    /**
     * Establece la dimensión de agrupación de filas (tabs de grupo).
     * Al activar un grupo, selecciona automáticamente el primer tab disponible.
     * Al desactivar (key = null), limpia la selección de grupo.
     * @param {string|null} key - Campo de agrupación: 'sale_category', 'product_categ_name', etc.
     */
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

    /**
     * Selecciona el tab de grupo activo dentro de la agrupación vigente.
     * @param {string} key - Valor del grupo a seleccionar.
     */
    setGroup(key) {
        this.state.selectedGroup = key;
        this.state.page = 1;
    }

    // ── Columnas ─────────────────────────────────────────────────────────────

    /**
     * Calcula cuántas sub-columnas ocupa cada mes según las columnas visibles
     * (forecast, cobertura OFs, entregado). Mínimo 1 para que el colspan sea válido.
     * @returns {number} Cantidad de sub-columnas por mes.
     */
    get monthColspan() {
        let n = 0;
        if (this.state.visibleCols.forecast)         n++;
        if (this.state.visibleCols.mos)              n++;
        if (this.state.visibleCols.delivered)        n++;
        if (this.state.visibleCols.demand_delivered) n++;
        return n || 1;
    }

    /**
     * Indica si debe mostrarse la columna de precisión acumulada de forecast.
     * Solo es relevante cuando tanto forecast como entregado son visibles junto con total.
     * @returns {boolean}
     */
    get showForecastAcc() {
        return this.state.visibleCols.total &&
               this.state.visibleCols.forecast &&
               this.state.visibleCols.delivered;
    }

    /**
     * Colspan de la sección "Total" del encabezado, incluyendo la columna de
     * precisión acumulada si corresponde.
     * @returns {number}
     */
    get totalColspan() {
        return this.monthColspan + (this.showForecastAcc ? 1 : 0);
    }

    /**
     * Indica si debe renderizarse la columna de totales acumulados del período.
     * Requiere que la opción 'total' esté activa y al menos una sub-columna visible.
     * @returns {boolean}
     */
    get showTotal() {
        return this.state.visibleCols.total &&
               (this.state.visibleCols.forecast         ||
                this.state.visibleCols.mos              ||
                this.state.visibleCols.delivered        ||
                this.state.visibleCols.demand_delivered);
    }

    /**
     * Colspan total de la tabla, usado para filas de estado vacío o carga.
     * Suma columnas fijas (producto + opcionales) más las columnas de meses y totales.
     * @returns {number}
     */
    get tableColspan() {
        const n = this.state.data ? this.state.data.months.length : 0;
        let cols = this.staticVisibleCols.length;
        cols += n * this.monthColspan;
        if (this.showTotal) cols += this.totalColspan;
        return cols;
    }

    // ── Column manager helpers ────────────────────────────────────────────────

    get staticVisibleCols() {
        return this.cols.visibleCols().filter(col => {
            if (col.key === 'product') return true;
            return !!this.state.visibleCols[col.key];
        });
    }

    colTitle(col) {
        if (col.key === 'rotation')     return this.rotHeaderTitle;
        if (col.key === 'coverage')     return this.covHeaderTitle;
        if (col.key === 'product')      return 'Ordenar por nombre de artículo';
        if (col.key === 'saleCategory') return 'Categoría de venta (A=alta rotación, E=baja). Clic para ordenar.';
        if (col.key === 'productCateg') return 'Familia de producto (product.template.categ_id). Clic para ordenar.';
        if (col.key === 'productTypes') return 'Tipos de producto asignados en la ficha (x_product_type_ids). Clic para ordenar.';
        if (col.key === 'stock')        return 'Stock disponible en ubicaciones internas. Clic para ordenar.';
        if (col.key === 'demand')       return 'Demanda del período: cantidad total de pedidos de venta confirmados. Clic para ordenar.';
        return '';
    }

    onColHeaderClick(col) {
        const sk = FC_SORT_KEYS[col.key];
        if (sk) this.setSort(sk);
    }

    // ── Sort ──────────────────────────────────────────────────────────────────

    /**
     * Establece la columna de ordenamiento. Si ya estaba activa, invierte la dirección.
     * Si es una columna nueva, ordena ascendente por defecto.
     * @param {string} col - Clave del campo a ordenar, p. ej. 'product', 'total_forecast'.
     */
    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortCol = col;
            this.state.sortDir = 'asc';
        }
        this.state.page = 1;
    }

    /**
     * Devuelve la clase CSS del ícono de ordenamiento para una columna.
     * @param {string} col - Clave de la columna.
     * @returns {string} Clase Font Awesome del ícono.
     */
    sortIcon(col) {
        if (this.state.sortCol !== col) return 'fa fa-sort text-muted ms-1';
        return this.state.sortDir === 'asc'
            ? 'fa fa-sort-asc text-primary ms-1'
            : 'fa fa-sort-desc text-primary ms-1';
    }

    /**
     * Devuelve todas las filas filtradas y ordenadas según la columna y dirección activas.
     * Los strings vacíos se empujan al final independientemente de la dirección.
     * Los valores null/undefined se tratan como -Infinity para ordenamiento numérico.
     * @returns {Object[]} Filas ordenadas.
     */
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

    /**
     * Filas base con búsqueda de texto y filtro rápido aplicados,
     * pero sin restricción de grupo (permite calcular los tabs de grupo sobre el total).
     * @returns {Object[]} Filas que pasan el filtro de texto y el filtro rápido activo.
     */
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

    /**
     * Filas con todos los filtros aplicados, incluyendo el filtro de grupo activo.
     * Es la base para el ordenamiento y la paginación.
     * @returns {Object[]} Filas filtradas completas (sin paginar).
     */
    get filteredRowsAll() {
        let rows = this.baseFilteredRows;
        const gb = this.state.groupBy;
        if (gb && this.state.selectedGroup !== null) {
            rows = rows.filter(r => (r[gb] || '') === this.state.selectedGroup);
        }
        return rows;
    }

    /**
     * KPIs calculados a partir de las filas actualmente filtradas (búsqueda + filtro rápido + grupo).
     * Reemplaza a `state.data.kpis` en las cards de KPI para que reaccionen a los filtros de tabla.
     * Los campos no recalculables (ej. so_demand_no_fc, acc_all) se heredan del estado global.
     * @returns {Object} KPIs calculados sobre las filas filtradas.
     */
    get filteredKpis() {
        if (!this.state.data) return {};
        const rows = this.filteredRowsAll;
        const total_forecast          = rows.reduce((s, r) => s + (r.total_forecast          || 0), 0);
        const total_mos               = rows.reduce((s, r) => s + (r.total_mos               || 0), 0);
        const total_delivered         = rows.reduce((s, r) => s + (r.total_delivered         || 0), 0);
        const total_so_demand         = rows.reduce((s, r) => s + (r.total_so_demand         || 0), 0);
        const total_demand_delivered  = rows.reduce((s, r) => s + (r.total_demand_delivered  || 0), 0);

        // Incluir sin FC en tasas para reflejar demanda y entregas reales totales
        const kpis0 = this.state.data.kpis;
        const no_fc_demand     = kpis0.so_demand_no_fc         || 0;
        const no_fc_delivered  = kpis0.delivered_no_fc         || 0;
        const no_fc_demand_del = kpis0.demand_delivered_no_fc  || 0;
        const total_demand_all = total_so_demand + no_fc_demand;

        const overall_service_rate       = total_demand_all > 0
            ? Math.round((total_delivered       + no_fc_delivered)  / total_demand_all * 100) : null;
        const overall_demand_service_rate = total_demand_all > 0
            ? Math.round((total_demand_delivered + no_fc_demand_del) / total_demand_all * 100) : null;
        const demand_gap_pct = total_forecast > 0
            ? Math.round((total_so_demand - total_forecast) / total_forecast * 100) : null;
        const mos_gap_pct = total_forecast > 0
            ? Math.round((total_mos - total_forecast) / total_forecast * 100) : null;

        const accRows = rows.filter(r => r.total_forecast_acc !== null && r.total_forecast_acc !== undefined);
        const overall_forecast_acc = accRows.length > 0
            ? Math.round(accRows.reduce((s, r) => s + r.total_forecast_acc, 0) / accRows.length)
            : null;

        // Desglose entregas físicas por mes de confirmación del pedido origen
        const del_by_order_month = {};
        for (const r of rows) {
            for (const [ym, qty] of Object.entries(r.del_by_order_month || {})) {
                del_by_order_month[ym] = (del_by_order_month[ym] || 0) + qty;
            }
        }

        return {
            ...this.state.data.kpis,
            total_forecast,
            total_mos,
            total_delivered,
            total_so_demand,
            total_demand_delivered,
            overall_forecast_acc,
            overall_service_rate,
            overall_demand_service_rate,
            demand_gap_pct,
            mos_gap_pct,
            del_by_order_month,
        };
    }

    /**
     * Página actual de filas: aplica el slice de paginación sobre las filas ordenadas.
     * @returns {Object[]} Filas de la página actual.
     */
    get filteredRows() {
        const all   = this.sortedRows;
        const start = (this.state.page - 1) * this.state.pageSize;
        return all.slice(start, start + this.state.pageSize);
    }

    /**
     * Total de páginas de la tabla, mínimo 1.
     * @returns {number}
     */
    get totalPages()  { return Math.max(1, Math.ceil(this.filteredRowsAll.length / this.state.pageSize)); }
    /**
     * Indica si existe una página siguiente.
     * @returns {boolean}
     */
    get hasNextPage() { return this.state.page < this.totalPages; }
    /**
     * Indica si existe una página anterior.
     * @returns {boolean}
     */
    get hasPrevPage() { return this.state.page > 1; }
    /** Avanza a la página siguiente si existe. */
    nextPage() { if (this.hasNextPage) this.state.page++; }
    /** Retrocede a la página anterior si existe. */
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    // ── Agrupación / tabs ─────────────────────────────────────────────────────

    /**
     * Genera la lista de tabs para la agrupación activa, con conteo de productos por grupo.
     * La categoría de ventas (sale_category) tiene orden fijo A→B→C→D→E→sin categoría.
     * El resto se ordena alfabéticamente en español.
     * @returns {Array<{key: string, label: string, count: number}>|null}
     *   Array de tabs, o null si no hay agrupación activa.
     */
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

    /**
     * Items de la tabla en la página actual, con marcador de tipo para el template.
     * @returns {Object[]} Filas de la página con la propiedad `_type: 'row'` agregada.
     */
    get tableItems() {
        return this.filteredRows.map(r => ({ ...r, _type: 'row' }));
    }

    // ── Depósito ──────────────────────────────────────────────────────────────

    /**
     * Lista de depósitos filtrada por el texto de búsqueda interno del dropdown.
     * @returns {Array<{id: number, name: string}>} Depósitos que coinciden con la búsqueda.
     */
    get filteredWarehouses() {
        const q = this.state.whSearch.toLowerCase();
        if (!q) return this.state.warehouses;
        return this.state.warehouses.filter(w => w.name.toLowerCase().includes(q));
    }

    /**
     * Agrega o quita un depósito del filtro activo y recarga los datos.
     * El ID se lee del atributo `data-wh-id` del elemento que disparó el evento.
     * @param {MouseEvent} ev - Evento click sobre el checkbox de depósito.
     */
    toggleWarehouse(ev) {
        const id = parseInt(ev.target.dataset.whId);
        const ids = this.state.warehouseIds;
        this.state.warehouseIds = ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id];
        this._load();
    }

    /**
     * Limpia la selección de depósitos (muestra todos) y recarga los datos.
     */
    clearWhFilter() {
        this.state.warehouseIds = [];
        this._load();
    }

    /**
     * Etiqueta resumida para el botón del selector de depósitos.
     * @returns {string} "Todos los depósitos", el nombre del único seleccionado, o "N depósitos".
     */
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

    /**
     * Navega al formulario del template de producto correspondiente a una fila.
     * @param {Object} row - Fila de la tabla con la propiedad `product_tmpl_id`.
     */
    openProduct(row) {
        this.action.doAction({
            type:    'ir.actions.act_window',
            res_model: 'product.template',
            res_id:  row.product_tmpl_id,
            views:   [[false, 'form']],
            target:  'current',
        });
    }

    /**
     * Navega al formulario de una orden de fabricación específica.
     * @param {number} moId - ID del registro `mrp.production`.
     */
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

    /**
     * Abre o cierra el acordeón de órdenes de fabricación de una fila de producto.
     * La primera vez que se abre, solicita las OFs al servidor (lazy load).
     * Si el producto no tiene OFs (total_mos === 0), no hace nada para evitar llamadas vacías.
     * @param {Object} row - Fila de la tabla con `product_id` y `total_mos`.
     * @returns {Promise<void>}
     */
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

    /**
     * Devuelve la clase CSS del badge de estado de una orden de fabricación.
     * @param {string} state - Estado de la OF: 'draft', 'confirmed', 'progress', 'to_close', 'done', 'cancel'.
     * @returns {string} Clases Bootstrap del badge.
     */
    moStateBadge(state) { return moStateBadge(state); }

    /**
     * Devuelve la clase CSS del badge de categoría ABC de ventas.
     * @param {string} cat - Categoría ABC: 'A', 'B', 'C', 'D' o 'E'.
     * @returns {string} Clases Bootstrap del badge.
     */
    saleCatBadge(cat) { return saleCatBadge(cat); }

    // ── Formateo / clases ─────────────────────────────────────────────────────

    /**
     * Etiquetas de mes legibles para los encabezados de columna de la tabla.
     * @returns {string[]} Etiquetas como "Ene 2025", "Feb 2025", etc.
     */
    get monthLabels() {
        if (!this.state.data) return [];
        return this.state.data.months.map(monthLabel);
    }

    /**
     * Clase CSS de la celda de cobertura de OF de un mes.
     * Verde si la cobertura es ≥ 100 %, amarillo si supera el umbral configurado,
     * rojo en caso contrario. Sin clase si no hay forecast para ese mes.
     * @param {Object|null} cell - Objeto de celda mensual con `forecast` y `pct`.
     * @returns {string} Clase CSS.
     */
    /**
     * Calcula el % efectivo de cobertura de OFs según el denominador configurado.
     * @param {number} mos - OFs del período.
     * @param {number} forecast - Forecast del período.
     * @param {number} so_demand - Demanda SO del período.
     * @returns {number}
     */
    moCovPct(mos, forecast, so_demand) {
        const denom = this.state.data && this.state.data.mo_coverage_denominator;
        return moCovPct(mos, forecast, so_demand, denom);
    }

    /** Pct efectivo para una celda mensual. */
    moCovPctCell(cell) {
        const denom = this.state.data && this.state.data.mo_coverage_denominator;
        return moCovPctCell(cell, denom);
    }

    /** Pct efectivo para el total de una fila. */
    moCovPctRow(row) {
        const denom = this.state.data && this.state.data.mo_coverage_denominator;
        return moCovPctRow(row, denom);
    }

    /**
     * Clase CSS de cobertura de OFs basada en un pct y los umbrales configurados.
     * @param {number} forecast
     * @param {number} pct
     * @returns {string}
     */
    cellClassForPct(forecast, pct) {
        const d = this.state.data;
        if (!d) return '';
        return cellClassForPct(forecast, pct, d.warning_pct);
    }

    /**
     * Clase CSS para una celda mensual.
     * Respeta el alcance de color (solo totales vs mensual+total).
     * @param {Object} cell
     * @returns {string}
     */
    cellClassMonthly(cell) {
        const d = this.state.data;
        if (!d) return '';
        return cellClassMonthly(cell, d.mo_coverage_color_scope, d.warning_pct, d.mo_coverage_denominator);
    }

    /**
     * Clase CSS para la celda de total de OFs de una fila.
     * Siempre se colorea independientemente del alcance configurado.
     * @param {Object} row
     * @returns {string}
     */
    cellClassTotal(row) {
        const d = this.state.data;
        if (!d) return '';
        return cellClassTotal(row, d.warning_pct, d.mo_coverage_denominator);
    }

    cellClass(cell) {
        const d = this.state.data;
        if (!d) return '';
        return cellClass(cell, d.warning_pct, d.mo_coverage_denominator);
    }

    /**
     * Clase CSS para la tasa de servicio al cliente.
     * Verde ≥ 95 %, amarillo ≥ 80 %, rojo por debajo.
     * @param {number|null} rate - Tasa de servicio en porcentaje.
     * @returns {string} Clase Bootstrap de color.
     */
    svcClass(rate) { return svcClass(rate); }

    /**
     * Clase CSS para el indicador de precisión de forecast de una fila.
     * Para la fórmula 'bias' usa valor absoluto (desviación ± 10 % / ± 20 %).
     * Para el resto usa umbrales de 90 % y 70 %.
     * @param {number|null} acc - Valor de precisión en porcentaje.
     * @returns {string} Clase Bootstrap de color.
     */
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

    /**
     * Formatea el valor de rotación de inventario de una fila según la unidad configurada.
     * Agrega el sufijo "m" (meses) o "d" (días) según corresponda.
     * @param {Object} row - Fila de la tabla con `rotation_months` y `rotation_days`.
     * @returns {string} Valor formateado, p. ej. "3 m" o "90 d", o "—" si no hay dato.
     */
    fmtRotation(row) {
        const unit = this.state.data && this.state.data.rotation_unit;
        if (unit === 'months') {
            const v = row.rotation_months;
            return v !== null && v !== undefined ? `${v} m` : '—';
        }
        const v = row.rotation_days;
        return v !== null && v !== undefined ? `${v} d` : '—';
    }

    /**
     * Clase CSS para el indicador de rotación.
     * El umbral verde es ≤ 3 meses (o ≤ 90 días); el doble de ese valor es umbral amarillo.
     * @param {Object} row - Fila de la tabla.
     * @returns {string} Clase Bootstrap de color.
     */
    rotClass(row) {
        const unit = this.state.data && this.state.data.rotation_unit;
        const v = unit === 'months' ? row.rotation_months : row.rotation_days;
        if (v === null || v === undefined) return 'text-muted';
        const threshold = unit === 'months' ? 3 : 90;
        return v <= threshold ? 'text-success' : v <= threshold * 2 ? 'text-warning' : 'text-muted';
    }

    moTooltip(cell)  { return moTooltip(this, cell); }
    svcTooltip(cell) { return svcTooltip(this, cell); }
    get rotHeaderTitle() { return rotHeaderTitle(this); }
    rotTooltip(row)  { return rotTooltip(this, row); }

    /**
     * Formatea el valor de cobertura de inventario de una fila.
     * @param {Object} row
     * @returns {string} P. ej. "45 d" o "1.5 m" o "—".
     */
    fmtCoverage(row) {
        const unit = this.state.data && this.state.data.coverage_unit;
        if (unit === 'months') {
            const v = row.coverage_months;
            return v !== null && v !== undefined ? `${v} m` : '—';
        }
        const v = row.coverage_days;
        return v !== null && v !== undefined ? `${v} d` : '—';
    }

    /**
     * Clase CSS para la celda de cobertura de inventario.
     * Verde si cubre bien, amarillo si está ajustado, rojo si es crítico.
     * Respeta el flag coverage_alerts_enabled del config.
     * @param {Object} row
     * @returns {string}
     */
    covClass(row) {
        const d = this.state.data;
        if (!d || !d.coverage_alerts_enabled) return 'text-muted';
        const v = row.coverage_days;
        if (v === null || v === undefined) return 'text-muted';
        const warn = d.coverage_warn_days || 30;
        const crit = d.coverage_critical_days || 15;
        if (v <= crit) return 'text-danger fw-bold';
        if (v <= warn) return 'text-warning fw-semibold';
        return 'text-success';
    }

    covTooltip(row)       { return covTooltip(this, row); }
    get covHeaderTitle()  { return covHeaderTitle(this); }
    accGlobalTooltip()    { return accGlobalTooltip(this); }
    accTooltip(row)       { return accTooltip(this, row); }
    fcKpiTooltip(key)     { return fcKpiTooltip(this, key); }
    demandGapTooltip()    { return demandGapTooltip(this); }
    mosGapTooltip()       { return mosGapTooltip(this); }
    accSecondaryPills()   { return accSecondaryPills(this); }

    /**
     * Clase CSS para la brecha entre demanda real y forecast de un KPI.
     * Usa valor absoluto: ≤ 10 % es verde, ≤ 25 % es amarillo, mayor es rojo.
     * @param {number|null} pct - Porcentaje de brecha.
     * @returns {string} Clases Bootstrap de color y peso.
     */
    demandGapClass(pct) {
        if (pct === null || pct === undefined) return 'text-muted';
        const abs = Math.abs(pct);
        if (abs <= 10) return 'text-success fw-semibold';
        if (abs <= 25) return 'text-warning fw-semibold';
        return 'text-danger fw-semibold';
    }

    /**
     * Clase CSS para la brecha de cobertura de OFs respecto al forecast.
     * Positivo (superávit) es verde; hasta -10 % es amarillo; más negativo es rojo.
     * @param {number|null} pct - Porcentaje de brecha de OFs.
     * @returns {string} Clases Bootstrap de color y peso.
     */
    mosGapClass(pct) {
        if (pct === null || pct === undefined) return 'text-muted';
        if (pct >= 0) return 'text-success fw-semibold';
        if (pct >= -10) return 'text-warning fw-semibold';
        return 'text-danger fw-semibold';
    }

    /**
     * Formatea un porcentaje de brecha con signo explícito para valores positivos.
     * @param {number|null} n - Valor de la brecha en porcentaje.
     * @returns {string} P. ej. "+5%", "-12%" o "—" si no hay dato.
     */
    fmtGapPct(n) {
        if (n === null || n === undefined) return '—';
        return `${n > 0 ? '+' : ''}${n}%`;
    }

    /**
     * Formatea un número con separadores de miles en locale es-AR, máximo 1 decimal.
     * @param {number|null} n - Número a formatear.
     * @returns {string} Número formateado o "—" si es null/undefined.
     */
    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n);
    }

    /**
     * Formatea un número como porcentaje redondeado al entero más cercano.
     * @param {number|null} n - Valor porcentual.
     * @returns {string} P. ej. "85%" o "—" si es null/undefined.
     */
    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return `${Math.round(n)}%`;
    }

    /**
     * Convierte una fecha "YYYY-MM-DD" al formato de pantalla "DD/MM/YYYY".
     * @param {string|null} d - Fecha en formato ISO.
     * @returns {string} Fecha formateada o "—" si es falsy.
     */
    fmtDate(d) {
        if (!d) return '—';
        const [y, m, day] = d.split('-');
        return `${day}/${m}/${y}`;
    }

    // ── Acciones ──────────────────────────────────────────────────────────────

    /**
     * Abre la vista de importación/edición de líneas de forecast usando la acción
     * XML definida en el módulo. Requiere permiso `can_edit_forecast`.
     * @returns {Promise<void>}
     */
    async openImport() {
        await this.action.doAction('odoo_mrp_planner.action_mrp_forecast_line');
    }

    /**
     * Abre la vista lista/form de líneas de forecast (`mrp.forecast.line`)
     * en la pestaña actual para consulta o edición manual.
     */
    openForecastList() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.forecast.line",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            target:    "current",
        });
    }

    // ── Drill-down KPIs forecast ──────────────────────────────────────────────

    /**
     * Construye el rango de fechas del período activo con hora completa
     * para usarlo en dominios de búsqueda de Odoo (datetime fields).
     * @returns {{ dateFrom: string, dateTo: string }} Rango con formato "YYYY-MM-DD HH:MM:SS".
     */
    _periodDateRange() {
        // Odoo's ORM treats bare datetime strings as UTC.  Build the boundaries
        // in local time and then shift them to UTC so the domain window matches
        // the user's calendar day, regardless of server/client timezone offset.
        const toUtcStr = (localIso) => {
            const d = new Date(localIso);
            const pad = n => String(n).padStart(2, '0');
            return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
                   `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
        };
        return {
            dateFrom: toUtcStr(`${this.state.periodFrom}T00:00:00`),
            dateTo:   toUtcStr(`${this.state.periodTo}T23:59:59`),
        };
    }

    /**
     * Extrae los IDs de producto de todas las filas cargadas en el dashboard.
     * Se usa para construir dominios de drill-down que acotan a los mismos productos.
     * @returns {number[]} Array de IDs de `product.product`.
     */
    _forecastProductIds() {
        return (this.state.data && this.state.data.rows || []).map(r => r.product_id);
    }

    /**
     * Drill-down al KPI de forecast: abre las líneas de `mrp.forecast.line`
     * del período activo.
     * El dominio usa el primer día de cada mes para comparar con el campo `period`.
     */
    openDrillForecast() {
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Demanda forecast',
            res_model: 'mrp.forecast.line',
            view_mode: 'list,form',
            views:     [[false, 'list'], [false, 'form']],
            domain:    [
                ['period', '>=', this.state.periodFrom.substring(0, 7) + '-01'],
                ['period', '<=', this.state.periodTo.substring(0, 7)   + '-01'],
            ],
            target: 'current',
        });
    }

    /**
     * Drill-down al KPI de producción planificada: abre las órdenes de fabricación
     * activas del período para los productos del forecast.
     * Excluye ubicaciones de subcontratación para no inflar el total.
     */
    openDrillMos() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids     = this._forecastProductIds();
        const moStates = (this.state.data && this.state.data.mo_states) || ['confirmed', 'progress', 'to_close'];
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Producción planificada',
            res_model: 'mrp.production',
            view_mode: 'list,form',
            views:     [[false, 'list'], [false, 'form']],
            domain:    [
                ['product_id', 'in', pids],
                ['state', 'in', moStates],
                ['date_finished', '>=', dateFrom],
                ['date_finished', '<=', dateTo],
                ['location_src_id.is_subcontracting_location', '!=', true],
            ],
            target: 'current',
        });
    }

    /**
     * Drill-down al KPI de demanda real: abre las líneas de órdenes de venta
     * confirmadas o hechas del período para los productos del forecast.
     */
    openDrillSoDemand() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids = this._forecastProductIds();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Demanda real (órdenes de venta)',
            res_model: 'sale.order.line',
            view_mode: 'list',
            views:     [[false, 'list']],
            domain:    [
                ['order_id.state', 'in', ['sale', 'done']],
                ['order_id.date_order', '>=', dateFrom],
                ['order_id.date_order', '<=', dateTo],
                ['product_id', 'in', pids],
            ],
            target: 'current',
        });
    }

    /**
     * Drill-down al KPI de entregas: abre los movimientos de stock de salida
     * completados en el período para los productos del forecast.
     */
    openDrillDelivered() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids = this._forecastProductIds();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Entregas Físicas (movimientos de salida)',
            res_model: 'stock.move.line',
            view_mode: 'list',
            views:     [[false, 'list']],
            domain:    [
                ['state', '=', 'done'],
                ['picking_id.picking_type_id.code', '=', 'outgoing'],
                ['date', '>=', dateFrom],
                ['date', '<=', dateTo],
                ['product_id', 'in', pids],
            ],
            target: 'current',
        });
    }

    /** Drill-down al KPI de cumplimiento de demanda: entregas de pedidos confirmados
     *  en el período, sin importar la fecha de entrega. */
    openDrillDemandDelivered() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids = this._forecastProductIds();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Cumplimiento de demanda (entregas de pedidos del período)',
            res_model: 'stock.move.line',
            view_mode: 'list',
            views:     [[false, 'list']],
            domain:    [
                ['state', '=', 'done'],
                ['picking_id.picking_type_id.code', '=', 'outgoing'],
                ['picking_id.sale_id.date_order', '>=', dateFrom],
                ['picking_id.sale_id.date_order', '<=', dateTo],
                ['product_id', 'in', pids],
            ],
            target: 'current',
        });
    }

    /** Drill-down para demanda real de productos SIN línea de forecast. */
    openDrillSoDemandNoFc() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids = this._forecastProductIds();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Demanda real – productos sin forecast',
            res_model: 'sale.order.line',
            view_mode: 'list',
            views:     [[false, 'list']],
            domain:    [
                ['order_id.state', 'in', ['sale', 'done']],
                ['order_id.date_order', '>=', dateFrom],
                ['order_id.date_order', '<=', dateTo],
                ['product_id.sale_ok', '=', true],
                ['product_id', 'not in', pids],
            ],
            target: 'current',
        });
    }

    /** Drill-down para producción planificada de productos SIN línea de forecast. */
    openDrillMosNoFc() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids     = this._forecastProductIds();
        const moStates = (this.state.data && this.state.data.mo_states) || ['confirmed', 'progress', 'to_close'];
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Producción planificada – productos sin forecast',
            res_model: 'mrp.production',
            view_mode: 'list,form',
            views:     [[false, 'list'], [false, 'form']],
            domain:    [
                ['state', 'in', moStates],
                ['date_finished', '>=', dateFrom],
                ['date_finished', '<=', dateTo],
                ['product_id.sale_ok', '=', true],
                ['location_src_id.is_subcontracting_location', '!=', true],
                ['product_id', 'not in', pids],
            ],
            target: 'current',
        });
    }

    /** Drill-down para cumplimiento de demanda de productos SIN línea de forecast. */
    openDrillDemandDeliveredNoFc() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids = this._forecastProductIds();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Cumplimiento de demanda – productos sin forecast',
            res_model: 'stock.move.line',
            view_mode: 'list',
            views:     [[false, 'list']],
            domain:    [
                ['state', '=', 'done'],
                ['picking_id.picking_type_id.code', '=', 'outgoing'],
                ['picking_id.sale_id.date_order', '>=', dateFrom],
                ['picking_id.sale_id.date_order', '<=', dateTo],
                ['product_id.sale_ok', '=', true],
                ['product_id', 'not in', pids],
            ],
            target: 'current',
        });
    }

    /** Drill-down para entregas físicas de productos SIN línea de forecast. */
    openDrillDeliveredNoFc() {
        const { dateFrom, dateTo } = this._periodDateRange();
        const pids = this._forecastProductIds();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Entregas físicas – productos sin forecast',
            res_model: 'stock.move.line',
            view_mode: 'list',
            views:     [[false, 'list']],
            domain:    [
                ['state', '=', 'done'],
                ['picking_id.picking_type_id.code', '=', 'outgoing'],
                ['date', '>=', dateFrom],
                ['date', '<=', dateTo],
                ['product_id.sale_ok', '=', true],
                ['product_id', 'not in', pids],
            ],
            target: 'current',
        });
    }

    downloadExport() {
        const d = this.state.data;
        if (!d || !d.rows || !d.months) return;
        downloadForecastExcel(this.baseFilteredRows, d.months, this.state.periodFrom, this.state.periodTo);
    }
}

registry.category("view_widgets").add("forecast_widget", {
    component: ForecastWidget,
});
