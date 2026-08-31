/** @odoo-module **/

/**
 * Tablero de Programación de Producción.
 *
 * Muestra TODAS las OFs confirmadas/en-curso organizadas en una matriz:
 *   Filas    = Centro de trabajo × Turno
 *   Columnas = Períodos (días / semanas → días / meses → semanas)
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

/** Lunes de la semana actual. */
function mondayOfCurrentWeek() {
    const d = new Date();
    const day = d.getDay() || 7;
    d.setDate(d.getDate() - day + 1);
    return d;
}

/** date_from por defecto según granularidad. */
function defaultDateFrom(gran) {
    if (gran === 'week') return toDateStr(mondayOfCurrentWeek());
    if (gran === 'month') {
        const d = new Date();
        d.setDate(1);
        return toDateStr(d);
    }
    return todayStr();
}

/** date_to por defecto según granularidad. */
function defaultDateTo(gran) {
    if (gran === 'week') return daysFromToday(41);   // 6 semanas completas
    if (gran === 'month') {
        const d = new Date();
        d.setMonth(d.getMonth() + 3);
        d.setDate(0);   // último día del 3er mes futuro
        return toDateStr(d);
    }
    return daysFromToday(13);   // 2 semanas
}

/**
 * Tamaño de ventana visible en número de HOJAS.
 *  day   → 7  hojas = días   → 1 semana visible
 *  week  → 14 hojas = días   → 2 semanas visibles
 *  month → 8  hojas = semanas → ~2 meses visibles
 */
function windowSize(gran) {
    if (gran === 'day')   return 7;
    if (gran === 'month') return 8;
    return 14;   // week
}

// ── Estado de la OF ───────────────────────────────────────────────────────────

const MO_STATE_LABEL = {
    confirmed: 'Confirmada',
    progress:  'En proceso',
    to_close:  'Por cerrar',
    done:      'Terminada',
};

const MO_STATE_CLASS = {
    confirmed: 'sm-state-confirmed',
    progress:  'sm-state-progress',
    to_close:  'sm-state-toclose',
    done:      'sm-state-done',
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
            showDone:      false,

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

            // Chips expandidos
            expandedMoIds:    {},   // mo_id → true
            componentsCache:  {},   // mo_id → [components]
            loadingComponents: {},  // mo_id → true

            // Dropdowns
            tagDropdownOpen: false,
            wcDropdownOpen:  false,
            tagMenuPos: { top: 0, left: 0 },
            wcMenuPos:  { top: 0, left: 0 },
        });

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
        this.state.loading        = true;
        this.state.error          = null;
        this.state.expandedMoIds      = {};
        this.state.componentsCache    = {};
        this.state.loadingComponents  = {};

        try {
            const result = await this.orm.call(
                'mrp.production',
                'get_scheduling_board',
                [],
                {
                    tag_ids:      this.state.tagIds.length ? this.state.tagIds : null,
                    date_from:    this.state.dateFrom,
                    date_to:      this.state.dateTo,
                    granularity:  this.state.granularity,
                    include_done: this.state.showDone,
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

    toggleShowDone() {
        this.state.showDone = !this.state.showDone;
        this._loadData();
    }

    // ── Crear OF desde celda ─────────────────────────────────────────────────

    /**
     * Convierte una clave de período en una fecha ISO string (YYYY-MM-DD).
     * - Día:    clave ya es YYYY-MM-DD
     * - Semana: calcula el lunes de la semana ISO
     */
    _pkToDateStr(pk) {
        if (!pk.includes('W')) return pk;
        const year = parseInt(pk.slice(0, 4));
        const week = parseInt(pk.slice(6));
        // Lunes de la semana ISO usando Jan 4 (siempre en semana 1)
        const jan4 = new Date(Date.UTC(year, 0, 4));
        const dayOfWeek = jan4.getUTCDay() || 7;
        jan4.setUTCDate(jan4.getUTCDate() - dayOfWeek + 1);  // lunes sem 1
        jan4.setUTCDate(jan4.getUTCDate() + (week - 1) * 7); // lunes sem N
        return jan4.toISOString().slice(0, 10);
    }

    createMoInCell(ev, row, pk) {
        ev.stopPropagation();
        const dateStr = this._pkToDateStr(pk);
        this.action.doAction(
            {
                type:      'ir.actions.act_window',
                name:      'Nueva Orden de Fabricación',
                res_model: 'mrp.production',
                views:     [[false, 'form']],
                target:    'new',
                context:   { default_date_start: `${dateStr} 00:00:00` },
            },
            { onClose: () => this._loadData() }
        );
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
            const next = { ...this.state.expandedMoIds };
            delete next[moId];
            this.state.expandedMoIds = next;
            return;
        }

        this.state.expandedMoIds = { ...this.state.expandedMoIds, [moId]: true };

        if (this.state.componentsCache[moId]) return;

        this.state.loadingComponents = { ...this.state.loadingComponents, [moId]: true };
        try {
            const comps = await this.orm.call(
                'mrp.production',
                'get_mo_components',
                [moId]
            );
            this.state.componentsCache = { ...this.state.componentsCache, [moId]: comps };
        } catch (e) {
            this.state.componentsCache = { ...this.state.componentsCache, [moId]: [] };
        } finally {
            const next = { ...this.state.loadingComponents };
            delete next[moId];
            this.state.loadingComponents = next;
        }
    }

    isExpanded(moId)    { return !!this.state.expandedMoIds[moId]; }
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

        // Paso 1: filtrar por CT seleccionados en dropdown
        let rows = this.state.wcShiftRows;
        if (this.state.wcFilterIds.length) {
            rows = rows.filter(r => this.state.wcFilterIds.includes(r.wc_id));
        }

        // Paso 2: filtrar por búsqueda y/o filas vacías
        let result;
        if (!search && !hideEmpty) {
            result = rows;
        } else {
            const filtered = [];
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
                    filtered.push({ ...row, cells });
                }
            }
            result = filtered;
        }

        // Paso 3: recalcular is_first_shift y shift_count según las filas
        // efectivamente visibles (crítico cuando hideEmptyRows elimina algunos
        // turnos de un CT, el rowspan de la columna CT debe reflejar solo los
        // turnos visibles).
        const wcCounts = {};
        for (const row of result) {
            wcCounts[row.wc_id] = (wcCounts[row.wc_id] || 0) + 1;
        }
        const seenWcs = {};
        return result.map(row => {
            const isFirst = !seenWcs[row.wc_id];
            seenWcs[row.wc_id] = true;
            return {
                ...row,
                is_first_shift: isFirst,
                shift_count:    wcCounts[row.wc_id],
            };
        });
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

    /**
     * Grupos de cabecera para semanas y meses.
     * Retorna null en modo día (sin agrupación).
     *
     * Estructura: [{ key, label, sublabel, span }]
     */
    get visiblePeriodGroups() {
        const labels = this.state.periodLabels;
        const groups = [];
        for (const pk of this.visiblePeriodKeys) {
            const lbl = labels[pk];
            if (!lbl?.group_key) return null;   // modo día: sin grupos
            const last = groups[groups.length - 1];
            if (last && last.key === lbl.group_key) {
                last.span++;
            } else {
                groups.push({
                    key:      lbl.group_key,
                    label:    lbl.group_label,
                    sublabel: lbl.group_sublabel,
                    span:     1,
                });
            }
        }
        return groups.length ? groups : null;
    }

    get periodRangeLabel() {
        const keys = this.visiblePeriodKeys;
        if (!keys.length) return '';
        const labels = this.state.periodLabels;
        const first  = labels[keys[0]];
        if (!first) return '';

        const groups = this.visiblePeriodGroups;
        if (groups && groups.length) {
            const gf = groups[0];
            const gl = groups[groups.length - 1];
            const yr = first.group_sublabel || keys[0].slice(0, 4);
            if (gf.key === gl.key) return `${gf.label} · ${yr}`;
            return `${gf.label} – ${gl.label} · ${yr}`;
        }

        // Modo día: mostrar rango de fechas
        const last = labels[keys[keys.length - 1]];
        const lf   = first.label;
        const lt   = last?.label;
        const yr   = keys[0].slice(0, 4);
        if (keys[0] === keys[keys.length - 1]) return `${lf} · ${yr}`;
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
}

registry.category("view_widgets").add("scheduling_matrix_widget", {
    component: SchedulingMatrixWidget,
});

registry.category("actions").add("mrp_scheduling_matrix_action", SchedulingMatrixWidget);
