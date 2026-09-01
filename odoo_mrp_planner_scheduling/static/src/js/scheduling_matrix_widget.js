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
    rangeBounds,
    minutesToPct,
    barGeometry,
    layoutLanes,
    offsetPctToDate,
    localIsoToServerUTC,
    parseLocalMinutes,
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

const ROW_BASE_PX = 54;   // alto de una fila con un solo lane
const LANE_PX     = 44;   // alto de cada lane (crece con el solapamiento)

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

            // Datos del tablero (payload)
            shifts:     [],
            rows:       [],        // filas crudas del backend
            totalBars:  0,
            userTz:     'UTC',     // TZ del usuario (la manda el backend)

            // Layout derivado
            layout:     null,      // {startMin,endMin,contentWidthPx,ticks,groups,dayLines,gridlines,shiftDividers,nightBands}
            viewRows:   [],        // filas filtradas con geometría de barras

            // Estado UI
            loading:     true,
            error:       null,
            emptyReason: null,
            unassignedExpanded: false,   // fila "Sin centro asignado" (arranca cerrada)

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
            this.state.totalBars   = result.total_bars || 0;
            this.state.userTz      = result.user_tz    || 'UTC';
            this.state.emptyReason = result.empty_reason || null;
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

    toggleUnassigned() {
        this.state.unassignedExpanded = !this.state.unassignedExpanded;
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

    // ── Crear OF desde el eje (botón al hover; fecha = posición del cursor) ─────

    /**
     * Reposiciona el botón "+" siguiendo al cursor mediante una variable CSS.
     * NO toca el estado reactivo (evita re-render en cada mousemove); guarda el
     * porcentaje actual en el dataset de la pista para leerlo al hacer click.
     */
    onTrackHover(ev) {
        const track = ev.currentTarget;
        const rect  = track.getBoundingClientRect();
        const x     = ev.clientX - rect.left;
        track.style.setProperty('--sm-hover-x', `${x}px`);
        track.dataset.hoverPct = String((x / rect.width) * 100);
    }

    onAddClick(ev, row) {
        ev.stopPropagation();
        if (!this.state.layout) return;
        const track = ev.currentTarget.closest('.sm-row-track');
        const pct   = parseFloat((track && track.dataset.hoverPct) || '0');
        const iso   = offsetPctToDate(pct, this.state.layout.startMin, this.state.layout.endMin, 15);
        // iso es hora de pared en la TZ del usuario (el server manda todo en esa
        // TZ). Se convierte a UTC con la TZ que mandó el backend, porque Odoo
        // guarda default_date_start como UTC naive; sin convertir, la OF nacería
        // corrida por el offset de la zona horaria.
        const dateStr = localIsoToServerUTC(iso, this.state.userTz);
        const ctx     = { default_date_start: dateStr };
        if (row && row.wc_id) {
            ctx.default_workcenter_id = row.wc_id;   // sugerencia de CT
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

    /** Geometría global: ancho, ticks, grupos, líneas de día, divisorias de turno, tinte nocturno. */
    _buildLayout() {
        const { dateFrom, dateTo, resolution } = this.state;
        if (!dateFrom || !dateTo) return null;
        const cfg = RESOLUTIONS[resolution] || RESOLUTIONS.day;
        const { startMin, endMin } = rangeBounds(dateFrom, dateTo);
        const spanMin = endMin - startMin;
        if (spanMin <= 0) return null;

        const contentWidthPx = Math.round((spanMin / 60) * cfg.pxPerHour);
        const spanDays = Math.round(spanMin / 1440);

        const pct = (min) => minutesToPct(min, startMin, endMin);

        const dayLines = [];       // sólidas, cambio de día
        const gridlines = [];      // faint, cada gridHours
        const shiftDividers = [];  // punteadas, límite de turno
        const nightBands = [];     // tinte suave turno noche
        const ticks = [];          // etiquetas del header inferior
        const groups = [];         // header superior (día / semana / mes)

        const nightShifts = (this.state.shifts || []).filter(s => s.is_night);

        for (let dayIdx = 0; dayIdx < spanDays; dayIdx++) {
            const dayStart = startMin + dayIdx * 1440;
            const dayDate  = new Date(dayStart * 60000);   // UTC = wall clock

            dayLines.push({ leftPct: pct(dayStart) });

            // Divisorias de turno (punteadas) en cada hour_from, salvo 00:00 (ya es día).
            for (const s of (this.state.shifts || [])) {
                if (s.hour_from > 0) {
                    shiftDividers.push({ leftPct: pct(dayStart + Math.round(s.hour_from * 60)) });
                }
            }
            // Tinte nocturno: [hour_from, 24) y [0, hour_to) de cada turno noche.
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

            // Gridlines cada gridHours dentro del día (para hour mode).
            if (cfg.tickMode === 'hour') {
                for (let h = 0; h < 24; h += cfg.gridHours) {
                    const m = dayStart + h * 60;
                    if (h !== 0) gridlines.push({ leftPct: pct(m) });
                    ticks.push({ leftPct: pct(m), label: String(h).padStart(2, '0'), major: h === 0 });
                }
            } else {
                // tickMode 'day': una etiqueta por día
                ticks.push({
                    leftPct: pct(dayStart),
                    label:   `${dayDate.getUTCDate()}`,
                    sublabel: DAYS[(dayDate.getUTCDay() + 6) % 7],
                    major:   dayDate.getUTCDay() === 1,
                });
            }
        }

        // Grupos del header superior
        if (resolution === 'day' || resolution === '3days') {
            for (let dayIdx = 0; dayIdx < spanDays; dayIdx++) {
                const dayStart = startMin + dayIdx * 1440;
                const d = new Date(dayStart * 60000);
                groups.push({
                    leftPct:  pct(dayStart),
                    widthPct: pct(dayStart + 1440) - pct(dayStart),
                    label:    `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}`,
                    sublabel: DAYS[(d.getUTCDay() + 6) % 7],
                });
            }
        } else if (resolution === 'week') {
            let cur = null;
            for (let dayIdx = 0; dayIdx < spanDays; dayIdx++) {
                const dayStart = startMin + dayIdx * 1440;
                const d = new Date(dayStart * 60000);
                const [yr, wk] = isoWeek(d);
                const gkey = `${yr}-W${wk}`;
                if (!cur || cur.key !== gkey) {
                    cur = { key: gkey, startMin: dayStart, endMin: dayStart + 1440, label: `Sem ${String(wk).padStart(2, '0')}`, sublabel: String(yr) };
                    groups.push(cur);
                } else {
                    cur.endMin = dayStart + 1440;
                }
            }
            for (const g of groups) { g.leftPct = pct(g.startMin); g.widthPct = pct(g.endMin) - pct(g.startMin); }
        } else { // month
            let cur = null;
            for (let dayIdx = 0; dayIdx < spanDays; dayIdx++) {
                const dayStart = startMin + dayIdx * 1440;
                const d = new Date(dayStart * 60000);
                const gkey = `${d.getUTCFullYear()}-${d.getUTCMonth()}`;
                if (!cur || cur.key !== gkey) {
                    cur = { key: gkey, startMin: dayStart, endMin: dayStart + 1440, label: MONTHS[d.getUTCMonth()], sublabel: String(d.getUTCFullYear()) };
                    groups.push(cur);
                } else {
                    cur.endMin = dayStart + 1440;
                }
            }
            for (const g of groups) { g.leftPct = pct(g.startMin); g.widthPct = pct(g.endMin) - pct(g.startMin); }
        }

        // Marca "ahora" si cae dentro del rango (hora de pared del navegador).
        const now = new Date();
        const nowLocal = parseLocalMinutes(
            `${toDateStr(now)}T${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
        );
        const nowPct = (nowLocal >= startMin && nowLocal <= endMin) ? pct(nowLocal) : null;

        return {
            startMin, endMin, contentWidthPx,
            ticks, groups, dayLines, gridlines, shiftDividers, nightBands, nowPct,
        };
    }

    /** Filas filtradas con geometría de barras, lanes y bandas laborables. */
    _computeRows() {
        const layout = this.state.layout;
        if (!layout) return [];
        const { startMin, endMin } = layout;
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

            // Geometría por SEGMENTO (cada tramo laborable) + envelope para el
            // conector/etiqueta. Los minutos del span completo van a los lanes.
            const geom = bars.map(b => {
                const sMin = parseLocalMinutes(b.date_start);
                let eMin = b.date_finished ? parseLocalMinutes(b.date_finished) : endMin;
                if (eMin <= sMin) eMin = sMin + 15;
                const segs = (b.segments || [])
                    .map(([s, e]) => barGeometry(s, e, startMin, endMin))
                    .filter(g => g.width > 0);
                const env = barGeometry(b.date_start, b.date_finished, startMin, endMin);
                if (!segs.length) segs.push(env);   // nunca dejar una barra sin dibujar
                return { ...b, segs, env, startMin: sMin, endMin: eMin };
            });
            const { lane, laneCount, overload } = layoutLanes(geom);
            const barsOut = geom.map((b, i) => ({ ...b, lane: lane[i], overload: overload[i] }));

            // Bandas laborables → bloques blancos sobre el fondo gris (no laborable)
            const workBlocks = (row.working_intervals || []).map(([s, e]) => {
                const l = minutesToPct(parseLocalMinutes(s), startMin, endMin);
                const r = minutesToPct(parseLocalMinutes(e), startMin, endMin);
                return { leftPct: l, widthPct: Math.max(0, r - l) };
            });

            out.push({
                ...row,
                bars: barsOut,
                laneCount,
                heightPx: ROW_BASE_PX + (laneCount - 1) * LANE_PX,
                workBlocks,
            });
        }
        return out;
    }

    // ── Helpers de presentación ──────────────────────────────────────────────

    moStateLabel(state) { return MO_STATE_LABEL[state] || state; }
    moStateClass(state) { return MO_STATE_CLASS[state] || ''; }

    /** Estilo de un segmento (tramo laborable) de una barra. */
    segStyle(bar, seg) {
        return `left:${seg.left}%;width:${seg.width}%;top:${2 + bar.lane * LANE_PX}px;height:${LANE_PX - 4}px;`;
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
        if (pct >= 100) return 'sm-occ-over';
        if (pct >= 80)  return 'sm-occ-high';
        return 'sm-occ-normal';
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
