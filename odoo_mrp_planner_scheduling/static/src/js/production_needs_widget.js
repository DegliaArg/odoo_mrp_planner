/**
 * production_needs_widget.js (odoo_mrp_planner_scheduling)
 *
 * Panel 1 — Motor de necesidades de producción.
 *
 * Muestra, para un mes a programar y una ventana de promedio de forecast, la
 * necesidad neta y la cantidad sugerida a fabricar por artículo (replica la
 * hoja PLANIFICACION del Excel). Desde cada fila con estado "Programar" (o la
 * selección múltiple) se dispara la OF del producto terminado; las OF/OC de los
 * componentes las genera Odoo hacia atrás por las rutas de abastecimiento.
 *
 *   RPC: mrp.production.needs.get_needs_data(targetMonth, dateFrom, dateTo, warehouseId)
 *        mrp.production.needs.action_generate_mo(items, warehouseId)
 *
 * Reutiliza el formateador de números es-AR del módulo base. El filtrado por
 * texto/estado/origen (ambos con multiselección), el orden y la visibilidad de
 * columnas se aplican client-side sobre state.rows.
 */
/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { fmt, kpiNumClass } from "@odoo_mrp_planner/js/forecast_formatters";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function firstOfMonth(offset = 0) {
    const d = new Date();
    return toDateStr(new Date(d.getFullYear(), d.getMonth() + offset, 1));
}

// Columnas de datos de la tabla, todas mostrables/ocultables desde el selector.
//   type:  'num' | 'badge' | 'text' | 'money'
//   def:   visible por defecto
const DATA_COLS = [
    { key: "origin",         label: "Origen",             type: "badge", def: true,  align: "start", title: "Tipo de origen del artículo (producción interna, compra-venta, etc.)." },
    { key: "sale_category",  label: "Categoría de venta", type: "badge", def: false, align: "center", title: "Categoría de venta (A–E) almacenada en el artículo." },
    { key: "categ",          label: "Categoría de producción", type: "text", def: false, align: "start", title: "Categoría interna del artículo (categ_id)." },
    { key: "list_price",     label: "Precio de venta",    type: "money", def: false, align: "end", title: "Precio de venta de la ficha del artículo." },
    { key: "stock_position", label: "Posición de stock",  type: "num",   def: true,  align: "end", title: "Cantidad pronosticada (a la mano + entrante − saliente) del almacén." },
    { key: "avg_forecast",   label: "Promedio forecast",  type: "num",   def: true,  align: "end", title: "Promedio de forecast = suma de la ventana / Nº de meses de la ventana." },
    { key: "month_forecast", label: "Forecast del mes",   type: "num",   def: true,  align: "end", title: "Forecast del mes a programar." },
    { key: "safety_stock",   label: "Stock de seguridad", type: "num",   def: true,  align: "end", title: "ROUNDUP(promedio × factor de seguridad)." },
    { key: "target_stock",   label: "Stock objetivo",     type: "num",   def: true,  align: "end", title: "Stock de seguridad + forecast del mes." },
    { key: "net_need",       label: "Necesidad neta",     type: "num",   def: true,  align: "end", title: "MAX(0, objetivo − posición)." },
    { key: "suggested_qty",  label: "Cantidad a fabricar", type: "num",  def: true,  align: "end", title: "Cantidad sugerida: MAX(lote mínimo, necesidad). Dispara OF tanto en producción interna como en compra-venta (las rutas generan la OC)." },
    { key: "coverage_now",   label: "Cobertura actual (meses)", type: "num", def: true,  align: "end", title: "Cobertura actual en meses = posición de stock / promedio de forecast." },
    { key: "coverage_plan",  label: "Cobertura con programa (meses)", type: "num", def: false, align: "end", title: "Cobertura con programa en meses = (posición de stock + cantidad a fabricar) / promedio de forecast." },
    { key: "machine",        label: "Máquina / proveedor", type: "text", def: false, align: "start", title: "Producción interna: máquina preferida del vulcanizado. Compra-venta: proveedor preferido." },
    { key: "min_per_shift",  label: "Mínimo (lote)",      type: "num",   def: true,  align: "end", title: "Lote mínimo. Producción interna: mínimo por turno del vulcanizado. Compra-venta: cantidad mínima del proveedor." },
];

const COLS_STORAGE_KEY = "_planner_needs_visible_cols_v1";
const WIDTHS_STORAGE_KEY = "_planner_needs_col_widths_v1";

export class ProductionNeedsWidget extends Component {
    static template = "odoo_mrp_planner_scheduling.ProductionNeedsWidget";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.allCols = DATA_COLS;

        this.state = useState({
            targetMonth: firstOfMonth(0),
            dateFrom: firstOfMonth(-5),
            dateTo: firstOfMonth(0),
            search: "",
            stateFilter: [],    // multiselección; vacío = todos. Admite el token especial "necesidad".
            originFilter: [],   // multiselección; vacío = todos
            rows: [],
            kpis: {},
            meta: {},
            sortCol: "suggested_qty",
            sortDir: "desc",
            selected: {},   // {product_id: true}
            loading: false,
            generating: false,
            visibleCols: this._loadVisibleCols(),
            colWidths: this._loadColWidths(),   // {colKey: px}
            openMenu: null,     // 'cols' | 'origin' | 'state' | null
        });

        onWillStart(async () => {
            await this.load();
        });
    }

    // ── Menús desplegables (columnas, origen, estado) ─────────────────────────
    toggleMenu(name) { this.state.openMenu = this.state.openMenu === name ? null : name; }
    isMenuOpen(name) { return this.state.openMenu === name; }
    closeMenus() { this.state.openMenu = null; }

    // ── Visibilidad de columnas (persistida en localStorage) ──────────────────
    _loadVisibleCols() {
        const def = Object.fromEntries(DATA_COLS.map(c => [c.key, c.def]));
        try {
            const raw = localStorage.getItem(COLS_STORAGE_KEY);
            if (!raw) return def;
            const saved = JSON.parse(raw);
            for (const c of DATA_COLS) if (c.key in saved) def[c.key] = !!saved[c.key];
            return def;
        } catch (e) { return def; }
    }
    _saveVisibleCols() {
        try { localStorage.setItem(COLS_STORAGE_KEY, JSON.stringify(this.state.visibleCols)); } catch (e) {}
    }
    toggleCol(key) {
        this.state.visibleCols[key] = !this.state.visibleCols[key];
        this._saveVisibleCols();
    }
    resetCols() {
        for (const c of DATA_COLS) this.state.visibleCols[c.key] = c.def;
        this._saveVisibleCols();
    }
    get dataCols() { return DATA_COLS.filter(c => this.state.visibleCols[c.key]); }
    get hiddenColsCount() { return DATA_COLS.filter(c => !this.state.visibleCols[c.key]).length; }

    // ── Ancho de columnas (arrastrando el borde derecho; persistido) ──────────
    _loadColWidths() {
        try { return JSON.parse(localStorage.getItem(WIDTHS_STORAGE_KEY) || "{}") || {}; }
        catch (e) { return {}; }
    }
    _saveColWidths() {
        try { localStorage.setItem(WIDTHS_STORAGE_KEY, JSON.stringify(this.state.colWidths)); } catch (e) {}
    }
    colStyle(key) {
        const w = this.state.colWidths[key];
        return w ? `width:${w}px; min-width:${w}px; max-width:${w}px;` : "";
    }
    onResizeStart(key, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const th = ev.currentTarget.closest("th");
        const startX = ev.clientX;
        const startW = th ? th.offsetWidth : (this.state.colWidths[key] || 100);
        const onMove = (e) => {
            this.state.colWidths[key] = Math.max(40, startW + e.clientX - startX);
        };
        const onUp = () => {
            this._saveColWidths();
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    }

    async load() {
        this.state.loading = true;
        try {
            const res = await this.orm.call(
                "mrp.production.needs", "get_needs_data",
                [this.state.targetMonth, this.state.dateFrom, this.state.dateTo]);
            this.state.rows = res.rows || [];
            this.state.kpis = res.kpis || {};
            this.state.meta = res.meta || {};
            this.state.selected = {};
        } finally {
            this.state.loading = false;
        }
    }

    // ── Filtros de fecha ──────────────────────────────────────────────────────
    onFilterChange(field, ev) {
        this.state[field] = ev.target.value;
        this.load();
    }

    // ── Filtro de estado (multiselección) ─────────────────────────────────────
    // Las cards KPI fijan un único estado (reemplazan la selección); el menú
    // desplegable permite combinar varios.
    setStateFilter(tok) {
        this.state.stateFilter = tok === "all" ? [] : [tok];
    }
    toggleStateTok(tok) {
        const arr = this.state.stateFilter;
        const i = arr.indexOf(tok);
        if (i === -1) arr.push(tok); else arr.splice(i, 1);
    }
    isStateActive(tok) { return this.state.stateFilter.includes(tok); }
    get stateFilterEmpty() { return this.state.stateFilter.length === 0; }
    // Para resaltar las cards: activas sólo si es el único token seleccionado.
    isCardActive(tok) {
        if (tok === "all") return this.state.stateFilter.length === 0;
        return this.state.stateFilter.length === 1 && this.state.stateFilter[0] === tok;
    }

    // ── Filtro de origen (multiselección) ─────────────────────────────────────
    toggleOriginTok(tok) {
        const arr = this.state.originFilter;
        const i = arr.indexOf(tok);
        if (i === -1) arr.push(tok); else arr.splice(i, 1);
    }
    isOriginActive(tok) { return this.state.originFilter.includes(tok); }
    clearOriginFilter() { this.state.originFilter = []; }
    clearStateFilter() { this.state.stateFilter = []; }

    get stateOptions() {
        const set = new Set();
        for (const r of this.state.rows) {
            for (const tok of (r.state || "").split(" | ")) if (tok) set.add(tok);
        }
        return [...set].sort();
    }
    get originOptions() {
        const set = new Set();
        for (const r of this.state.rows) if (r.origin) set.add(r.origin);
        return [...set].sort();
    }

    // ── Orden ───────────────────────────────────────────────────────────────
    sortBy(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortCol = col;
            this.state.sortDir = "desc";
        }
    }

    _matchesState(row) {
        const sel = this.state.stateFilter;
        if (!sel.length) return true;
        return sel.some(tok =>
            tok === "necesidad" ? (row.net_need || 0) > 0 : (row.state || "").includes(tok));
    }

    get visibleRows() {
        let rows = [...this.state.rows];
        const q = (this.state.search || "").trim().toLowerCase();
        if (q) {
            rows = rows.filter(r =>
                (r.name || "").toLowerCase().includes(q) ||
                (r.code || "").toLowerCase().includes(q));
        }
        if (this.state.originFilter.length) {
            rows = rows.filter(r => this.state.originFilter.includes(r.origin || ""));
        }
        rows = rows.filter(r => this._matchesState(r));

        const col = this.state.sortCol;
        const dir = this.state.sortDir === "asc" ? 1 : -1;
        rows.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === "string" || typeof vb === "string") {
                return dir * String(va || "").localeCompare(String(vb || ""));
            }
            va = va == null ? -Infinity : va;
            vb = vb == null ? -Infinity : vb;
            return dir * (va - vb);
        });
        return rows;
    }

    // ── Formateo / estilos ──────────────────────────────────────────────────
    f(n) { return n == null ? "—" : fmt(n); }
    kpiCls(n) { return kpiNumClass(fmt(n)); }

    cellValue(row, col) {
        const v = row[col.key];
        if (col.type === "num" || col.type === "money") return this.f(v);
        return v || "—";
    }
    cellClass(row, col) {
        let c = "text-" + (col.align || "start");
        if (col.key === "suggested_qty" && row.suggested_qty > 0) c += " o_needs_fab text-success";
        return c;
    }

    sortIcon(col) {
        if (this.state.sortCol !== col) return "fa fa-sort text-muted opacity-50 ms-1";
        return this.state.sortDir === "asc" ? "fa fa-sort-up ms-1" : "fa fa-sort-down ms-1";
    }

    saleCatBadge(cat) {
        const map = { A: "text-bg-success", B: "text-bg-info", C: "text-bg-primary",
                      D: "text-bg-warning", E: "text-bg-secondary" };
        return "badge rounded-pill " + (map[cat] || "text-bg-light border");
    }

    stateClass(state) {
        const s = state || "";
        if (s.includes("Programar")) return "text-bg-success";
        if (s === "Analizar cobertura") return "text-bg-info";
        if (s === "Stock suficiente") return "text-bg-light border";
        if (s === "No fabricar") return "text-bg-secondary";
        if (s.includes("Revisar") || s === "Sin forecast") return "text-bg-warning";
        return "text-bg-light border";
    }

    // ── Selección ───────────────────────────────────────────────────────────
    isSelectable(row) { return (row.state || "").includes("Programar"); }
    get hasSelectable() { return this.visibleRows.some(r => this.isSelectable(r)); }
    toggleRow(row) {
        if (!this.isSelectable(row)) return;
        if (this.state.selected[row.product_id]) delete this.state.selected[row.product_id];
        else this.state.selected[row.product_id] = true;
    }
    toggleAll() {
        const sel = this.selectedCount;
        if (sel > 0) { this.state.selected = {}; return; }
        const next = {};
        for (const r of this.visibleRows) if (this.isSelectable(r)) next[r.product_id] = true;
        this.state.selected = next;
    }
    get selectedCount() { return Object.keys(this.state.selected).length; }

    // ── Disparo de OF ───────────────────────────────────────────────────────
    async _generate(items) {
        if (!items.length) {
            this.notification.add("No hay artículos con cantidad a fabricar.", { type: "warning" });
            return;
        }
        this.state.generating = true;
        try {
            const act = await this.orm.call(
                "mrp.production.needs", "action_generate_mo", [items, this.state.targetMonth]);
            this.notification.add(
                `${items.length} orden(es) de fabricación generada(s).`, { type: "success" });
            if (act) await this.action.doAction(act);
        } finally {
            this.state.generating = false;
        }
    }
    async generateRow(row) {
        await this._generate([{ product_id: row.product_id, qty: row.suggested_qty }]);
    }
    async generateSelected() {
        const items = this.state.rows
            .filter(r => this.state.selected[r.product_id] && (r.suggested_qty || 0) > 0)
            .map(r => ({ product_id: r.product_id, qty: r.suggested_qty }));
        await this._generate(items);
    }
}

registry.category("view_widgets").add("production_needs_widget", {
    component: ProductionNeedsWidget,
});
