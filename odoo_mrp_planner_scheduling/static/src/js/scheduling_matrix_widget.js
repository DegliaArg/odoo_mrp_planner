/** @odoo-module **/

/**
 * Tablero de Programación de Producción.
 *
 * Muestra TODAS las OFs confirmadas/en-curso organizadas en una matriz:
 *   Filas    = Centro de trabajo × Turno
 *   Columnas = Períodos (días / semanas / meses)
 *
 * Interacciones:
 *  - Click en chip → despliega componentes (movimientos de materia prima).
 *  - Selector de granularidad: Día / Semana / Mes.
 *  - Filtros: sector (tag de CT), CT específico, rango de fechas, búsqueda.
 *
 * RPC: get_scheduling_board_filters, get_scheduling_board_wcs_for_tags,
 *      get_scheduling_board, get_mo_components
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// ── Helpers de fecha ──────────────────────────────────────────────────────────

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function todayStr() { return toDateStr(new Date()); }

function daysFromToday(n) {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return toDateStr(d);
}

/** Semana ISO actual (formato YYYY-Www) */
function currentIsoWeekKey() {
    const d = new Date();
    const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const dayNum = utc.getUTCDay() || 7;
    utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil((((utc - yearStart) / 86400000) + 1) / 7);
    return `${utc.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}

/** Retorna el date_from por defecto según granularidad (hoy o inicio de semana/mes). */
function defaultDateFrom(gran) {
    if (gran === 'week') {
        const d = new Date();
        d.setDate(d.getDate() - d.getDay() + (d.getDay() === 0 ? -6 : 1)); // lunes
        return toDateStr(d);
    }
    if (gran === 'month') {
        const d = new Date();
        d.setDate(1);
        return toDateStr(d);
    }
    return todayStr();
}

/** Retorna el date_to por defecto según granularidad. */
function defaultDateTo(gran) {
    if (gran === 'week') return daysFromToday(6 * 7 - 1);
    if (gran === 'month') {
        const d = new Date();
        d.setMonth(d.getMonth() + 2);
        d.setDate(0); // último día del mes siguiente
        return toDateStr(d);
    }
    return daysFromToday(13); // 2 semanas de días
}

/** Ventana visible de períodos según granularidad. */
function windowSize(gran) {
    if (gran === 'day')   return 7;
    if (gran === 'month') return 3;
    return 4;   // week
}

// ── Estado de la OF (etiqueta legible) ───────────────────────────────────────

const MO_STATE_LABEL = {
    confirmed:  'Confirmada',
    progress:   'En proceso',
    to_close:   'Por cerrar',
};

const MO_STATE_CLASS = {
    confirmed: 'sm-state-confirmed',
    progress:  'sm-state-progress',
    to_close:  'sm-state-toclose',
};

// ── Componente principal ──────────────────────────────────────────────────────

class SchedulingMatrixWidget extends Component {
    static template = "odoo_mrp_planner_scheduling.SchedulingMatrixWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.notification = useService("notification");

        const gran = 'day';

        this.state = useState({
            // Opciones de filtros
            tags:   [],
            wcs:    [],

            // Filtros activos
            tagIds:       [],
            wcFilterIds:  [],
            dateFrom:     defaultDateFrom(gran),
            dateTo:       defaultDateTo(gran),
            granularity:  gran,
            searchText:   '',
            hideEmptyRows: true,

            // Datos del tablero
            periodKeys:    [],
            periodLabels:  {},
            wcShiftRows:   [],
            totalMos:      0,
            hasShifts:     false,

            // Estado UI
            loading:       true,
            error:         null,
            emptyReason:   null,
            periodPage:    0,
            filteredRows:  [],

            // Chips expandidos (set de mo_id)
            expandedMoIds:    {},   // mo_id → true
            componentsCache:  {},   // mo_id → [components]
            loadingComponents: {},  // mo_id → true

            // Estado de dropdowns
            tagDropdownOpen: false,
            wcDropdownOpen:  false,
            tagMenuPos: { top: 0, left: 0 },
            wcMenuPos:  { top: 0, left: 0 },
        });

        this._currentPeriodKey = currentIsoWeekKey();

        onMounted(async () => {
            try {
                const defaultTagSelected = await this._loadFilters();
                if (defaultTagSelected || this.state.tagIds.length) {
                    await this._loadData();
                } else {
                    this.state.loading = false;
                }
            } catch (e) {
                if (e.message !== "Component is destroyed") {
                    this.state.error = (e?.data?.message) || e.message || String(e);
                    this.state.loading = false;
                }
            }
        });
    }

    // ── Carga de datos ────────────────────────────────────────────────────────

    async _loadFilters() {
        const result = await this.orm.call(
            'mrp.production',
            'get_scheduling_board_filters',
            []
        );
        this.state.tags = result.tags || [];

        const defaultTagId = result.default_scheduling_tag_id;
        if (defaultTagId && !this.state.tagIds.length) {
            const found = this.state.tags.find(t => t.id === defaultTagId);
            if (found) {
                this.state.tagIds = [defaultTagId];
                await this._loadWcs();
                return true;
            }
        }
        return false;
    }

    async _loadWcs() {
        if (!this.state.tagIds.length) {
            this.state.wcs        = [];
            this.state.wcFilterIds = [];
            return;
        }
        const wcs = await this.orm.call(
            'mrp.production',
            'get_scheduling_board_wcs_for_tags',
            [this.state.tagIds]
        );
        this.state.wcs        = wcs || [];
        this.state.wcFilterIds = [];
    }

    async _loadData() {
        this.state.loading     = true;
        this.state.error       = null;
        this.state.expandedMoIds    = {};
        this.state.componentsCache  = {};
        this.state.loadingComponents = {};

        try {
            const result = await this.orm.call(
                'mrp.production',
                'get_scheduling_board',
                [],
                {
                    tag_ids:     this.state.tagIds.length     ? this.state.tagIds     : null,
                    date_from:   this.state.dateFrom,
                    date_to:     this.state.dateTo,
                    granularity: this.state.granularity,
                }
            );
            this.state.periodKeys   = result.period_keys   || [];
            this.state.periodLabels = result.period_labels || {};
            this.state.wcShiftRows  = result.wc_shift_rows || [];
            this.state.totalMos     = result.total_mos     || 0;
            this.state.hasShifts    = result.has_shifts    || false;
            this.state.emptyReason  = result.empty_reason  || null;
            this.state.periodPage   = 0;
            this._recompute();
        } catch (e) {
            console.error("[SchedulingBoard]", e);
            this.state.error = (e?.data?.message) || e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Handlers de filtros ───────────────────────────────────────────────────

    toggleTagDropdown(ev) {
        if (!this.state.tagDropdownOpen) {
            const r = ev.currentTarget.getBoundingClientRect();
            this.state.tagMenuPos = { top: r.bottom + 3, left: r.left };
        }
        this.state.tagDropdownOpen = !this.state.tagDropdownOpen;
        this.state.wcDropdownOpen  = false;
    }

    toggleWcDropdown(ev) {
        if (!this.state.wcDropdownOpen) {
            const r = ev.currentTarget.getBoundingClientRect();
            this.state.wcMenuPos = { top: r.bottom + 3, left: r.left };
        }
        this.state.wcDropdownOpen  = !this.state.wcDropdownOpen;
        this.state.tagDropdownOpen = false;
    }

    closeDropdowns() {
        this.state.tagDropdownOpen = false;
        this.state.wcDropdownOpen  = false;
    }

    async toggleTag(tagId) {
        const ids = this.state.tagIds;
        this.state.tagIds = ids.includes(tagId)
            ? ids.filter(id => id !== tagId)
            : [...ids, tagId];
        await this._loadWcs();
        await this._loadData();
    }

    toggleWc(wcId) {
        const ids = this.state.wcFilterIds;
        this.state.wcFilterIds = ids.includes(wcId)
            ? ids.filter(id => id !== wcId)
            : [...ids, wcId];
        this._recompute();
    }

    get tagFilterLabel() {
        if (!this.state.tagIds.length) return "Seleccionar…";
        const names = this.state.tags
            .filter(t => this.state.tagIds.includes(t.id))
            .map(t => t.name);
        return names.length <= 2 ? names.join(", ") : `${names.length} sectores`;
    }

    get wcFilterLabel() {
        if (!this.state.wcFilterIds.length) return "Todos";
        const names = this.state.wcs
            .filter(w => this.state.wcFilterIds.includes(w.id))
            .map(w => w.name);
        return names.length <= 2 ? names.join(", ") : `${names.length} CTs`;
    }

    onSearchChange(ev) {
        this.state.searchText = ev.target.value;
        this._recompute();
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value || defaultDateFrom(this.state.granularity);
        this._loadData();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value || defaultDateTo(this.state.granularity);
        this._loadData();
    }

    toggleHideEmptyRows() {
        this.state.hideEmptyRows = !this.state.hideEmptyRows;
        this._recompute();
    }

    async setGranularity(gran) {
        if (gran === this.state.granularity) return;
        this.state.granularity = gran;
        this.state.dateFrom    = defaultDateFrom(gran);
        this.state.dateTo      = defaultDateTo(gran);
        this.state.periodPage  = 0;
        await this._loadData();
    }

    // ── Chips: expandir / componentes ────────────────────────────────────────

    async toggleChip(moId) {
        if (this.state.expandedMoIds[moId]) {
            // Colapsar
            const next = { ...this.state.expandedMoIds };
            delete next[moId];
            this.state.expandedMoIds = next;
            return;
        }

        // Expandir
        this.state.expandedMoIds = { ...this.state.expandedMoIds, [moId]: true };

        if (this.state.componentsCache[moId]) return;  // ya cargados

        this.state.loadingComponents = { ...this.state.loadingComponents, [moId]: true };
        try {
            const comps = await this.orm.call(
                'mrp.production',
                'get_mo_components',
                [moId]
            );
            this.state.componentsCache  = { ...this.state.componentsCache,  [moId]: comps };
        } catch (e) {
            this.state.componentsCache  = { ...this.state.componentsCache,  [moId]: [] };
        } finally {
            const next = { ...this.state.loadingComponents };
            delete next[moId];
            this.state.loadingComponents = next;
        }
    }

    isExpanded(moId) { return !!this.state.expandedMoIds[moId]; }
    isLoadingComp(moId) { return !!this.state.loadingComponents[moId]; }
    getComponents(moId) { return this.state.componentsCache[moId] || []; }

    // ── Abrir OF en Odoo ─────────────────────────────────────────────────────

    openMo(ev, mo) {
        ev.stopPropagation();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      mo.mo_name,
            res_model: 'mrp.production',
            res_id:    mo.mo_id,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    // ── Cómputo reactivo ─────────────────────────────────────────────────────

    _recompute() {
        this.state.filteredRows = this._computeFilteredRows();
    }

    _computeFilteredRows() {
        const search    = (this.state.searchText || '').trim().toLowerCase();
        const hideEmpty = this.state.hideEmptyRows;

        // Paso 1: filtrar por CT seleccionados
        let rows = this.state.wcShiftRows;
        if (this.state.wcFilterIds.length) {
            rows = rows.filter(r => this.state.wcFilterIds.includes(r.wc_id));
        }

        if (!search && !hideEmpty) return rows;

        const result = [];
        for (const row of rows) {
            const cells = {};
            let hasVisible = false;
            for (const pk of this.state.periodKeys) {
                let lines = row.cells[pk] || [];
                if (search) {
                    lines = lines.filter(l =>
                        (l.mo_name      || '').toLowerCase().includes(search) ||
                        (l.product_name || '').toLowerCase().includes(search)
                    );
                }
                cells[pk] = lines;
                if (lines.length) hasVisible = true;
            }
            if (hasVisible || !hideEmpty) {
                result.push({ ...row, cells });
            }
        }
        return result;
    }

    // ── Ventana deslizante de períodos ────────────────────────────────────────

    get visiblePeriodKeys() {
        const wSize = windowSize(this.state.granularity);
        return this.state.periodKeys.slice(
            this.state.periodPage,
            this.state.periodPage + wSize
        );
    }

    get sliderMax() {
        return Math.max(0, this.state.periodKeys.length - windowSize(this.state.granularity));
    }

    get periodRangeLabel() {
        const keys = this.state.periodKeys;
        if (!keys.length) return '';
        const from = keys[this.state.periodPage];
        const wSize = windowSize(this.state.granularity);
        const to   = keys[Math.min(this.state.periodPage + wSize - 1, keys.length - 1)];
        const lbl  = this.state.periodLabels;
        if (!from || !lbl[from]) return '';
        const lf = lbl[from].label;
        const lt = lbl[to]?.label;
        const yr = lbl[from].sublabel;
        if (from === to) return `${lf} · ${yr}`;
        return `${lf} – ${lt} · ${yr}`;
    }

    onSliderChange(ev) {
        this.state.periodPage = parseInt(ev.target.value, 10);
    }

    prevPage() {
        if (this.state.periodPage > 0) this.state.periodPage--;
    }

    nextPage() {
        if (this.state.periodPage < this.sliderMax) this.state.periodPage++;
    }

    // ── Helpers de estado ────────────────────────────────────────────────────

    moStateLabel(state) { return MO_STATE_LABEL[state] || state; }
    moStateClass(state) { return MO_STATE_CLASS[state] || ''; }

    // ── Helpers de formato ───────────────────────────────────────────────────

    fmtQty(n) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('es', { maximumFractionDigits: 2 });
    }

    fmtHours(h) {
        if (!h) return '';
        const hrs  = Math.floor(h);
        const mins = Math.round((h - hrs) * 60);
        return mins ? `${hrs}h ${mins}m` : `${hrs}h`;
    }

    // Detectar si una fila es la primera del CT (para rowspan)
    isFirstRowOfWc(rowIndex) {
        const rows = this.state.filteredRows;
        if (rowIndex === 0) return true;
        return rows[rowIndex].wc_id !== rows[rowIndex - 1].wc_id;
    }

    // Cuántas filas tiene el CT de la fila dada (para rowspan)
    wcRowspan(wc_id) {
        return this.state.filteredRows.filter(r => r.wc_id === wc_id).length;
    }
}

// Registrar como widget de vista (embebido en formulario)
registry.category("view_widgets").add("scheduling_matrix_widget", {
    component: SchedulingMatrixWidget,
});

// Registrar como acción cliente (vista standalone desde menú)
registry.category("actions").add("mrp_scheduling_matrix_action", SchedulingMatrixWidget);
