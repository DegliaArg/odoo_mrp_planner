/** @odoo-module **/

/**
 * Tablero de Programación de Producción — eje horario continuo.
 *
 *   Filas    = Centro de trabajo (una por CT).
 *   Eje X    = tiempo continuo (scroll horizontal); el zoom cambia la densidad.
 *   Barras   = mrp.workorder, ancho = ventana date_start → date_finished.
 *
 * El servidor manda barras, bandas laborables y ocupación; el cliente genera
 * ticks, agrupamientos (Sem/Mes) y la geometría (ver scheduling_geometry.js).
 * Convención TZ: ISO local naive; ver cabecera de mrp_scheduling_matrix.py.
 *
 * RPC: get_scheduling_board_filters, get_scheduling_board_wcs_for_tags,
 *      get_scheduling_board, get_mo_components
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    layoutLanes,
    parseLocalMinutes,
    makeTimeScale,
    scaleMinuteToPct,
    scaleSpan,
    scaleCuts,
} from "./scheduling_geometry";

// ── Etiquetas de calendario (es) ────────────────────────────────────────────────
const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
const DAYS   = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];

// ── Resoluciones de zoom ─────────────────────────────────────────────────────────
// pxPerHour define el ancho total del contenido (spanHoras × pxPerHour); el
// scroll horizontal recorre, el zoom ubica. spanDays acota el rango cargado.
const RESOLUTIONS = {
    day:     { label: 'Día',    pxPerHour: 56,  gridHours: 1,  spanDays: 3,  tickMode: 'hour' },
    '3days': { label: '3 días', pxPerHour: 30,  gridHours: 2,  spanDays: 7,  tickMode: 'hour' },
    week:    { label: 'Semana', pxPerHour: 13,  gridHours: 4,  spanDays: 21, tickMode: 'day'  },
    month:   { label: 'Mes',    pxPerHour: 2.6, gridHours: 24, spanDays: 70, tickMode: 'day'  },
};

// Geometría vertical: barra 42px, 10px arriba/abajo → fila 62px.
const ROW_PAD     = 10;                      // margen vertical de la barra
const BAR_H       = 42;                      // alto de barra
const LANE_PITCH  = BAR_H + 9;               // alto de un lane (barra + 9px de gap) = 51
const ROW_BASE_PX = 2 * ROW_PAD + BAR_H;     // 62 (un solo lane)

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** date_from por defecto: hoy / lunes / primero de mes, según resolución. */
function defaultDateFrom(res) {
    const d = new Date();
    if (res === 'week') {
        const day = d.getDay() || 7;
        d.setDate(d.getDate() - day + 1);   // lunes de esta semana
    } else if (res === 'month') {
        d.setDate(1);
    }
    return toDateStr(d);
}

/** date_to por defecto: date_from + spanDays - 1. */
function defaultDateTo(res) {
    const from = new Date(defaultDateFrom(res) + "T00:00:00");
    from.setDate(from.getDate() + RESOLUTIONS[res].spanDays - 1);
    return toDateStr(from);
}

/** [añoISO, semanaISO] de una fecha JS. */
function isoWeek(date) {
    const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
    const dayNum = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
    return [d.getUTCFullYear(), week];
}

// ── Estado de la OF ───────────────────────────────────────────────────────────
const MO_STATE_LABEL = {
    confirmed: 'Confirmada', progress: 'En proceso', to_close: 'Por cerrar', done: 'Terminada',
};
const MO_STATE_CLASS = {
    confirmed: 'sm-state-confirmed', progress: 'sm-state-progress',
    to_close:  'sm-state-toclose',   done:     'sm-state-done',
};

// ── Componente principal ──────────────────────────────────────────────────────

class SchedulingMatrixWidget extends Component {
    static template = "odoo_mrp_planner_scheduling.SchedulingMatrixWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.notification = useService("notification");

        const res = 'day';

        this.state = useState({
            // Opciones de filtros
            tags: [], wcs: [],

            // Filtros activos
            tagIds:        [],
            wcFilterIds:   [],
            dateFrom:      defaultDateFrom(res),
            dateTo:        defaultDateTo(res),
            resolution:    res,
            searchText:    '',
            hideEmptyRows: true,
            showDone:      false,
            hideWeekends:  true,        // ocultar fines de semana (default ON)
            hiddenWeekdays: [],         // días a ocultar (los manda el backend)

            // Datos del tablero (payload)
            shifts:     [],
            rows:       [],        // filas crudas del backend
            totalBars:  0,

            // Layout derivado
            layout:     null,      // {startMin,endMin,contentWidthPx,ticks,groups,dayLines,gridlines,shiftDividers,nightBands}
            viewRows:   [],        // filas filtradas con geometría de barras

            // Estado UI
            loading:     true,
            error:       null,
            emptyReason: null,
            unassignedExpanded: false,   // fila "Sin operaciones definidas" (arranca cerrada)
            collapsedSectors: {},        // sector → true (colapsado); no persiste

            // Popover de componentes (anclado a la barra)
            popoverKey:       null,   // wo_id / mo_id de la barra abierta
            popoverMoId:      null,
            popoverPos:       { top: 0, left: 0 },
            componentsCache:  {},
            loadingComponents:{},

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
        const result = await this.orm.call('mrp.production', 'get_scheduling_board_filters', []);
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
            this.state.wcs = [];
            this.state.wcFilterIds = [];
            return;
        }
        const wcs = await this.orm.call(
            'mrp.production', 'get_scheduling_board_wcs_for_tags', [this.state.tagIds]
        );
        this.state.wcs = wcs || [];
        this.state.wcFilterIds = [];
    }

    async _loadData() {
        this.state.loading = true;
        this.state.error   = null;
        this._closePopover();
        try {
            const result = await this.orm.call(
                'mrp.production', 'get_scheduling_board', [],
                {
                    tag_ids:      this.state.tagIds.length ? this.state.tagIds : null,
                    date_from:    this.state.dateFrom,
                    date_to:      this.state.dateTo,
                    include_done: this.state.showDone,
                }
            );
            this.state.shifts      = result.shifts     || [];
            this.state.rows        = result.rows       || [];
            this.state.totalBars      = result.total_bars || 0;
            this.state.hiddenWeekdays = result.hidden_weekdays || [];
            this.state.emptyReason    = result.empty_reason || null;
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
        this._closePopover();
    }

    async toggleTag(tagId) {
        const ids = this.state.tagIds;
        this.state.tagIds = ids.includes(tagId) ? ids.filter(id => id !== tagId) : [...ids, tagId];
        await this._loadWcs();
        await this._loadData();
    }

    toggleWc(wcId) {
        const ids = this.state.wcFilterIds;
        this.state.wcFilterIds = ids.includes(wcId) ? ids.filter(id => id !== wcId) : [...ids, wcId];
        this._recompute();
    }

    get tagFilterLabel() {
        if (!this.state.tagIds.length) return "Seleccionar…";
        const names = this.state.tags.filter(t => this.state.tagIds.includes(t.id)).map(t => t.name);
        return names.length <= 2 ? names.join(", ") : `${names.length} sectores`;
    }

    get wcFilterLabel() {
        if (!this.state.wcFilterIds.length) return "Todos";
        const names = this.state.wcs.filter(w => this.state.wcFilterIds.includes(w.id)).map(w => w.name);
        return names.length <= 2 ? names.join(", ") : `${names.length} CTs`;
    }

    onSearchChange(ev) {
        this.state.searchText = ev.target.value;
        this._recompute();
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value || defaultDateFrom(this.state.resolution);
        this._loadData();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value || defaultDateTo(this.state.resolution);
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

    toggleHideWeekends() {
        this.state.hideWeekends = !this.state.hideWeekends;
        this._recompute();   // solo cambia la escala del eje; no hace falta RPC
    }

    toggleUnassigned() {
        this.state.unassignedExpanded = !this.state.unassignedExpanded;
    }

    toggleSector(name) {
        this.state.collapsedSectors = {
            ...this.state.collapsedSectors,
            [name]: !this.state.collapsedSectors[name],
        };
    }

    // ── Agrupación por sector (solo con más de un sector seleccionado) ─────────

    /**
     * Agrupa las filas de CT por sector. Un CT con varios tags va al primer
     * sector alfabético entre los seleccionados, sin duplicar. Devuelve null si
     * hay 0 o 1 sector seleccionado (layout plano, sin encabezados).
     */
    get sectorGroups() {
        if (this.state.tagIds.length <= 1) return null;
        const selected = this.state.tags
            .filter(t => this.state.tagIds.includes(t.id))
            .map(t => t.name)
            .sort((a, b) => a.localeCompare(b));
        const byName = new Map(selected.map(n => [n, []]));
        for (const row of this.state.viewRows) {
            if (row.is_unassigned) continue;
            const g = selected.find(n => (row.tag_names || []).includes(n));
            if (g) byName.get(g).push(row);
        }
        const groups = [];
        for (const name of selected) {
            const rows = byName.get(name);
            if (!rows.length) continue;   // sector sin CTs visibles: sin encabezado vacío
            const avg = Math.round(
                rows.reduce((s, r) => s + (r.occupancy ? r.occupancy.pct : 0), 0) / rows.length
            );
            groups.push({
                name, rows, ctCount: rows.length, avgOcc: avg,
                collapsed: !!this.state.collapsedSectors[name],
            });
        }
        return groups;
    }

    /** Lista plana de ítems a renderizar: encabezados + filas + "sin operaciones".
     *  Los ítems de fila llevan `alt` (paridad) para el fondo alternado. */
    get boardItems() {
        const items = [];
        let n = 0;
        const pushRow = (row) => items.push({ type: 'row', row, alt: (n++ % 2) === 1 });
        const groups = this.sectorGroups;
        if (groups) {
            for (const g of groups) {
                items.push({ type: 'header', group: g });
                if (!g.collapsed) g.rows.forEach(pushRow);
            }
        } else {
            this.state.viewRows.filter(r => !r.is_unassigned).forEach(pushRow);
        }
        const un = this.state.viewRows.find(r => r.is_unassigned);
        if (un) items.push({ type: 'unassigned', row: un });
        return items;
    }

    itemKey(item) {
        if (item.type === 'header') return 'h_' + item.group.name;
        if (item.type === 'unassigned') return 'unassigned';
        return 'r_' + item.row.wc_id;
    }

    async setResolution(res) {
        if (res === this.state.resolution) return;
        this.state.resolution = res;
        // Ajustar el rango para que el ancho renderizado siga siendo manejable.
        this.state.dateFrom = defaultDateFrom(res);
        this.state.dateTo   = defaultDateTo(res);
        await this._loadData();
    }

    get resolutions() {
        return Object.keys(RESOLUTIONS).map(k => ({ key: k, label: RESOLUTIONS[k].label }));
    }

    // ── Crear OF desde la fila (botón "+" a la derecha de la última barra) ─────

    /** Estilo del botón "+": justo a la derecha de la última barra de la fila. */
    addBtnStyle(row) {
        const left = Math.min(row.addLeftPct || 0, 98);
        return `left:calc(${left}% + 8px);`;
    }

    onAddClick(ev, row) {
        ev.stopPropagation();
        // Sin fecha calculada: el usuario elige la fecha en el diálogo. Solo se
        // sugiere el CT de la fila.
        const ctx = {};
        if (row && row.wc_id) {
            ctx.default_workcenter_id = row.wc_id;
        }
        this.action.doAction(
            {
                type:      'ir.actions.act_window',
                name:      'Nueva Orden de Fabricación',
                res_model: 'mrp.production',
                views:     [[false, 'form']],
                target:    'new',
                context:   ctx,
            },
            { onClose: () => this._loadData() }
        );
    }

    // ── Popover de componentes (anclado a la barra) ───────────────────────────

    async toggleBarPopover(ev, bar) {
        ev.stopPropagation();
        const key = bar.wo_id ? `wo_${bar.wo_id}` : `mo_${bar.mo_id}`;
        if (this.state.popoverKey === key) {
            this._closePopover();
            return;
        }
        const r = ev.currentTarget.getBoundingClientRect();
        this.state.popoverPos  = { top: r.bottom + 4, left: r.left };
        this.state.popoverKey  = key;
        this.state.popoverMoId = bar.mo_id;

        if (this.state.componentsCache[bar.mo_id]) return;
        this.state.loadingComponents = { ...this.state.loadingComponents, [bar.mo_id]: true };
        try {
            const comps = await this.orm.call('mrp.production', 'get_mo_components', [bar.mo_id]);
            this.state.componentsCache = { ...this.state.componentsCache, [bar.mo_id]: comps };
        } catch (e) {
            this.state.componentsCache = { ...this.state.componentsCache, [bar.mo_id]: [] };
        } finally {
            const next = { ...this.state.loadingComponents };
            delete next[bar.mo_id];
            this.state.loadingComponents = next;
        }
    }

    _closePopover() {
        this.state.popoverKey  = null;
        this.state.popoverMoId = null;
    }

    isLoadingComp(moId) { return !!this.state.loadingComponents[moId]; }
    getComponents(moId) { return this.state.componentsCache[moId] || []; }

    // ── Abrir OF en Odoo ─────────────────────────────────────────────────────

    openMo(ev, bar) {
        ev.stopPropagation();
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      bar.mo_name,
            res_model: 'mrp.production',
            res_id:    bar.mo_id,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    // ── Cómputo reactivo ─────────────────────────────────────────────────────

    _recompute() {
        this.state.layout   = this._buildLayout();
        this.state.viewRows = this._computeRows();
    }

    /** Geometría global sobre el eje visible (con días ocultos colapsados). */
    _buildLayout() {
        const { dateFrom, dateTo, resolution } = this.state;
        if (!dateFrom || !dateTo) return null;
        const cfg = RESOLUTIONS[resolution] || RESOLUTIONS.day;
        const hidden = this.state.hideWeekends ? (this.state.hiddenWeekdays || []) : [];
        const scale = makeTimeScale(dateFrom, dateTo, hidden);
        if (scale.totalVisibleMin <= 0) return null;

        const contentWidthPx = Math.round((scale.totalVisibleMin / 60) * cfg.pxPerHour);
        const pct = (realMin) => scaleMinuteToPct(scale, realMin);

        const dayLines = [], gridlines = [], shiftDividers = [], nightBands = [], ticks = [], groups = [];
        const nightShifts = (this.state.shifts || []).filter(s => s.is_night);
        const visibleDays = scale.days.filter(d => !d.hidden);

        for (const day of visibleDays) {
            const dayStart = day.startRealMin;             // minutos reales (día 00:00)
            const dayDate  = new Date(dayStart * 60000);   // UTC = hora de pared
            dayLines.push({ leftPct: pct(dayStart) });
            for (const s of (this.state.shifts || [])) {
                if (s.hour_from > 0) shiftDividers.push({ leftPct: pct(dayStart + Math.round(s.hour_from * 60)) });
            }
            for (const s of nightShifts) {
                nightBands.push({
                    leftPct:  pct(dayStart + Math.round(s.hour_from * 60)),
                    widthPct: pct(dayStart + 1440) - pct(dayStart + Math.round(s.hour_from * 60)),
                });
                if (s.hour_to > 0) {
                    nightBands.push({
                        leftPct:  pct(dayStart),
                        widthPct: pct(dayStart + Math.round(s.hour_to * 60)) - pct(dayStart),
                    });
                }
            }
            if (cfg.tickMode === 'hour') {
                for (let h = 0; h < 24; h += cfg.gridHours) {
                    const m = dayStart + h * 60;
                    if (h !== 0) gridlines.push({ leftPct: pct(m) });
                    ticks.push({ leftPct: pct(m), label: String(h).padStart(2, '0'), major: h === 0 });
                }
            } else {
                ticks.push({
                    leftPct: pct(dayStart),
                    label:   `${dayDate.getUTCDate()}`,
                    sublabel: DAYS[(dayDate.getUTCDay() + 6) % 7],
                    major:   dayDate.getUTCDay() === 1,
                });
            }
        }

        // Grupos del header superior (solo días visibles)
        if (resolution === 'day' || resolution === '3days') {
            for (const day of visibleDays) {
                const d = new Date(day.startRealMin * 60000);
                groups.push({
                    leftPct:  pct(day.startRealMin),
                    widthPct: pct(day.startRealMin + 1440) - pct(day.startRealMin),
                    label:    `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}`,
                    sublabel: DAYS[(d.getUTCDay() + 6) % 7],
                });
            }
        } else {
            const monthMode = resolution === 'month';
            let cur = null;
            for (const day of visibleDays) {
                const d = new Date(day.startRealMin * 60000);
                let gkey, label, sublabel;
                if (monthMode) {
                    gkey = `${d.getUTCFullYear()}-${d.getUTCMonth()}`;
                    label = MONTHS[d.getUTCMonth()]; sublabel = String(d.getUTCFullYear());
                } else {
                    const [yr, wk] = isoWeek(d);
                    gkey = `${yr}-W${wk}`; label = `Sem ${String(wk).padStart(2, '0')}`; sublabel = String(yr);
                }
                if (!cur || cur.key !== gkey) {
                    cur = { key: gkey, a: day.startRealMin, b: day.startRealMin + 1440, label, sublabel };
                    groups.push(cur);
                } else {
                    cur.b = day.startRealMin + 1440;
                }
            }
            for (const g of groups) { g.leftPct = pct(g.a); g.widthPct = pct(g.b) - pct(g.a); }
        }

        // Cortes por días ocultos + nota al pie
        const cuts = scaleCuts(scale);
        const WD = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
        const cutFootnote = hidden.length
            ? `Días ocultos: ${[...hidden].sort((a, b) => a - b).map(w => WD[w]).join(', ')} — el eje los saltea (marcas de corte).`
            : null;

        // Marca "ahora" (solo si su día es visible y está en rango).
        const now = new Date();
        const nowReal = parseLocalMinutes(
            `${toDateStr(now)}T${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
        );
        const nowEpochDay = Math.floor(nowReal / 1440);
        let nowPct = null;
        if (nowEpochDay >= scale.firstEpochDay && nowEpochDay <= scale.lastEpochDay) {
            const nd = scale.days[nowEpochDay - scale.firstEpochDay];
            if (nd && !nd.hidden) nowPct = pct(nowReal);
        }

        return {
            scale, contentWidthPx,
            ticks, groups, dayLines, gridlines, shiftDividers, nightBands, nowPct,
            cuts, cutFootnote,
        };
    }

    /** Filas filtradas con geometría de barras, lanes y bandas laborables. */
    _computeRows() {
        const layout = this.state.layout;
        if (!layout) return [];
        const scale = layout.scale;
        const search    = (this.state.searchText || '').trim().toLowerCase();
        const hideEmpty = this.state.hideEmptyRows;
        const wcFilter  = this.state.wcFilterIds;

        const matchBar = (b) => !search ||
            (b.mo_name || '').toLowerCase().includes(search) ||
            (b.product_name || '').toLowerCase().includes(search) ||
            (b.product_code || '').toLowerCase().includes(search);

        const out = [];
        for (const row of this.state.rows) {
            if (wcFilter.length && !wcFilter.includes(row.wc_id)) continue;

            // Filtrar barras por búsqueda
            let bars = (row.bars || []).filter(matchBar);
            if (hideEmpty && !bars.length) continue;

            // "Sin centro asignado": lista simple, sin lanes ni sobrecarga.
            // Colapsable; el alto es el de una fila normal cuando está cerrada.
            if (row.is_unassigned) {
                out.push({ ...row, bars, count: bars.length, heightPx: ROW_BASE_PX });
                continue;
            }

            // Geometría por SEGMENTO sobre el eje visible + envelope. Los minutos
            // reales del span completo van a los lanes (el solapamiento es en
            // tiempo real, no en el eje colapsado).
            const geom = bars.map(b => {
                const sMin = parseLocalMinutes(b.date_start);
                let eMin = b.date_finished ? parseLocalMinutes(b.date_finished) : sMin + 15;
                if (eMin <= sMin) eMin = sMin + 15;
                let segs = (b.segments || [])
                    .map(([s, e]) => scaleSpan(scale, s, e))
                    .filter(g => g.width > 0.0001);
                // Fusionar tramos que quedan pegados en el eje visible (partidos
                // en el backend por un día no laborable que además está oculto).
                segs = segs.reduce((acc, g) => {
                    const prev = acc[acc.length - 1];
                    if (prev && g.left - (prev.left + prev.width) < 0.05) {
                        prev.width = (g.left + g.width) - prev.left;
                    } else {
                        acc.push({ ...g });
                    }
                    return acc;
                }, []);
                const env = scaleSpan(scale, b.date_start, b.date_finished);
                if (!segs.length) segs.push(env);   // nunca dejar una barra sin dibujar
                return { ...b, segs, env, startMin: sMin, endMin: eMin };
            });
            // Las OFs terminadas no compiten por capacidad: se excluyen de los
            // lanes y de la sobrecarga (van al lane 0, de fondo).
            const active = geom.filter(b => b.mo_state !== 'done');
            const doneBars = geom.filter(b => b.mo_state === 'done');
            const { lane, laneCount, overload } = layoutLanes(active);
            const barsOut = active
                .map((b, i) => ({ ...b, lane: lane[i], overload: overload[i] }))
                .concat(doneBars.map(b => ({ ...b, lane: 0, overload: false })));

            // Bandas laborables → bloques blancos sobre el fondo gris (no laborable)
            const workBlocks = (row.working_intervals || []).map(([s, e]) => {
                const g = scaleSpan(scale, s, e);
                return { leftPct: g.left, widthPct: g.width };
            });

            out.push({
                ...row,
                bars: barsOut,
                laneCount,
                heightPx: ROW_BASE_PX + (laneCount - 1) * LANE_PITCH,
                laneSeps: Array.from({ length: laneCount - 1 }, (_, i) => ROW_PAD + (i + 1) * LANE_PITCH - 4.5),
                addLeftPct: barsOut.reduce((m, b) => Math.max(m, b.env.left + b.env.width), 0),
                workBlocks,
            });
        }
        return out;
    }

    // ── Helpers de presentación ──────────────────────────────────────────────

    moStateLabel(state) { return MO_STATE_LABEL[state] || state; }
    moStateClass(state) { return MO_STATE_CLASS[state] || ''; }

    /** Estilo de un segmento (tramo continuo) de una barra. */
    segStyle(bar, seg) {
        return `left:${seg.left}%;width:${seg.width}%;top:${ROW_PAD + bar.lane * LANE_PITCH}px;height:${BAR_H}px;`;
    }

    /** Conector punteado entre tramos de la misma OF (partida por día no laborable). */
    connStyle(bar) {
        const top = ROW_PAD + bar.lane * LANE_PITCH + BAR_H / 2;
        return `left:${bar.env.left}%;width:${bar.env.width}%;top:${top}px;`;
    }

    /** Clase de esquinas de un segmento (redondeo solo en los extremos exteriores). */
    segCorner(bar, isFirst, isLast) {
        if (bar.segs.length <= 1) return 'sm-seg-solo';
        if (isFirst) return 'sm-seg-first';
        if (isLast) return 'sm-seg-last';
        return 'sm-seg-mid';
    }

    /** Tooltip completo de una barra (incluye el estado, que es lo que codifica el color). */
    barTitle(bar) {
        let t = `${bar.mo_name} · ${bar.product_name} · ${this.fmtQty(bar.qty)} ${bar.uom}`;
        if (bar.duration_expected) t += ` · ${this.fmtHours(bar.duration_expected)}`;
        t += ` · ${bar.date_start_str}`;
        if (bar.date_finished_str) t += ` → ${bar.date_finished_str}`;
        t += ` · Estado: ${this.moStateLabel(bar.mo_state)}`;
        if (bar.overload) t += ' · ⚠ sobrecarga (solapada en el centro)';
        if (bar.inconsistent_dates) t += ' · ⚠ fechas inconsistentes';
        else if (bar.outside_calendar) t += ' · ⚠ planificada fuera del calendario del centro';
        return t;
    }

    occupancyClass(pct) {
        if (pct > 120)  return 'sm-occ-over';    // rojo
        if (pct >= 100) return 'sm-occ-high';    // ámbar
        return 'sm-occ-normal';                  // verde
    }

    fmtQty(n) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('es', { maximumFractionDigits: 2 });
    }

    fmtHours(mins) {
        if (!mins) return '';
        const h = Math.floor(mins / 60);
        const m = Math.round(mins % 60);
        return m ? `${h}h ${m}m` : `${h}h`;
    }
}

registry.category("view_widgets").add("scheduling_matrix_widget", {
    component: SchedulingMatrixWidget,
});

registry.category("actions").add("mrp_scheduling_matrix_action", SchedulingMatrixWidget);
