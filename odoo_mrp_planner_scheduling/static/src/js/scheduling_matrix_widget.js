/** @odoo-module **/

/**
 * Tablero de Programación de Producción.
 *
 * Muestra las líneas planificadas de las solicitudes de programación (Circuit 2)
 * organizadas en una matriz semanas × centros de trabajo (CTs).
 *
 * Soporta dos modos:
 *  - Embebido: dentro del formulario de mrp.production.request (tab "Tablero").
 *  - Standalone: vista global desde el menú de Planificación.
 *
 * Interacciones:
 *  - Click en chip → panel de detalle.
 *  - Drag dentro del mismo CT → reordenar secuencia.
 *  - Drag a otro CT → reasignar centro de trabajo.
 *
 * RPC: get_scheduling_matrix_filters, get_scheduling_wcs_for_tags,
 *      get_scheduling_matrix, action_resequence_lines, action_reassign_wc.
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// ── Helpers de fecha ──────────────────────────────────────────────────────────

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function mondayOfCurrentWeek() {
    const d = new Date();
    const day = d.getDay() || 7;
    d.setDate(d.getDate() - (day - 1));
    return toDateStr(d);
}

function sundayInNWeeks(n) {
    const d = new Date();
    const day = d.getDay() || 7;
    d.setDate(d.getDate() - (day - 1) + 7 * n - 1);
    return toDateStr(d);
}

// Semana ISO actual (formato YYYY-Www)
function currentIsoWeekKey() {
    const d = new Date();
    const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const dayNum = utc.getUTCDay() || 7;
    utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil((((utc - yearStart) / 86400000) + 1) / 7);
    return `${utc.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}

// ── Constantes de estilo ──────────────────────────────────────────────────────

const REQUEST_STATE_LABEL = {
    draft:      'Borrador',
    calculated: 'Calculado',
    confirmed:  'Creado',
};

// ── Componente principal ──────────────────────────────────────────────────────

class SchedulingMatrixWidget extends Component {
    static template = "odoo_mrp_planner_scheduling.SchedulingMatrixWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.notification = useService("notification");

        // Modo embebido: hay un record (formulario de solicitud)
        this._isEmbedded = !!(this.props.record && this.props.record.data);
        const embeddedId = this._isEmbedded ? (this.props.record.data.id || null) : null;

        this.state = useState({
            // Opciones de filtros (desde backend)
            tags:     [],
            wcs:      [],
            requests: [],

            // Filtros activos
            tagIds:       [],
            wcFilterIds:  [],
            requestIds:   embeddedId ? [embeddedId] : [],
            dateFrom:     mondayOfCurrentWeek(),
            dateTo:       sundayInNWeeks(6),
            searchText:   '',
            hideEmptyCts: true,

            // Datos de la matriz
            weekKeys:   [],
            weekLabels: {},
            wcRows:     [],
            totalLines: 0,

            // Estado UI
            loading:      true,
            error:        null,
            weekPage:     0,
            filteredRows: [],

            // Selección para panel de detalle
            activeLineId:   null,
            activeLineData: null,
            activeWcId:     null,

            // Estado de dropdowns
            tagDropdownOpen:     false,
            wcDropdownOpen:      false,
            requestDropdownOpen: false,
            tagMenuPos:     { top: 0, left: 0 },
            wcMenuPos:      { top: 0, left: 0 },
            requestMenuPos: { top: 0, left: 0 },

            // Estado de drag & drop
            dragLineId:     null,
            dragWcId:       null,
            dragOverKey:    null,   // "wcId|wk" — celda sobre la que se arrastra
            dragOverLineId: null,   // chip sobre el que se arrastra (insert-before)
        });

        this._currentWeekKey = currentIsoWeekKey();

        onMounted(async () => {
            try {
                await this._loadFilters();
                // En modo embebido con una solicitud ya calculada, cargamos de inmediato
                if (this._isEmbedded && embeddedId) {
                    // Ajustar rango de fechas según start_from del record
                    const startFrom = this.props.record.data.start_from;
                    if (startFrom) {
                        const d = typeof startFrom === 'string'
                            ? new Date(startFrom)
                            : startFrom;
                        if (!isNaN(d)) {
                            this.state.dateFrom = toDateStr(d);
                            const dEnd = new Date(d);
                            dEnd.setDate(dEnd.getDate() + 42);
                            this.state.dateTo = toDateStr(dEnd);
                        }
                    }
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
            'mrp.production.request',
            'get_scheduling_matrix_filters',
            []
        );
        this.state.tags     = result.tags     || [];
        this.state.requests = result.requests || [];
    }

    async _loadWcs() {
        if (!this.state.tagIds.length) {
            this.state.wcs        = [];
            this.state.wcFilterIds = [];
            return;
        }
        const wcs = await this.orm.call(
            'mrp.production.request',
            'get_scheduling_wcs_for_tags',
            [this.state.tagIds]
        );
        this.state.wcs        = wcs || [];
        this.state.wcFilterIds = [];
    }

    async _loadData() {
        this.state.loading      = true;
        this.state.error        = null;
        this.state.activeLineId = null;
        this.state.activeLineData = null;
        this.state.activeWcId   = null;

        try {
            const result = await this.orm.call(
                'mrp.production.request',
                'get_scheduling_matrix',
                [
                    this.state.requestIds.length ? this.state.requestIds : null,
                    this.state.tagIds.length     ? this.state.tagIds     : null,
                    this.state.dateFrom,
                    this.state.dateTo,
                ]
            );
            this.state.weekKeys   = result.week_keys   || [];
            this.state.weekLabels = result.week_labels || {};
            this.state.wcRows     = result.wc_rows     || [];
            this.state.totalLines = result.total_lines || 0;
            this.state.weekPage   = 0;
            this._recompute();
        } catch (e) {
            console.error("[SchedulingMatrix]", e);
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
        this.state.tagDropdownOpen     = !this.state.tagDropdownOpen;
        this.state.wcDropdownOpen      = false;
        this.state.requestDropdownOpen = false;
    }

    toggleWcDropdown(ev) {
        if (!this.state.wcDropdownOpen) {
            const r = ev.currentTarget.getBoundingClientRect();
            this.state.wcMenuPos = { top: r.bottom + 3, left: r.left };
        }
        this.state.wcDropdownOpen      = !this.state.wcDropdownOpen;
        this.state.tagDropdownOpen     = false;
        this.state.requestDropdownOpen = false;
    }

    toggleRequestDropdown(ev) {
        if (!this.state.requestDropdownOpen) {
            const r = ev.currentTarget.getBoundingClientRect();
            this.state.requestMenuPos = { top: r.bottom + 3, left: r.left };
        }
        this.state.requestDropdownOpen = !this.state.requestDropdownOpen;
        this.state.tagDropdownOpen     = false;
        this.state.wcDropdownOpen      = false;
    }

    closeDropdowns() {
        this.state.tagDropdownOpen     = false;
        this.state.wcDropdownOpen      = false;
        this.state.requestDropdownOpen = false;
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
        this._clearSelection();
        this._recompute();
    }

    async toggleRequest(requestId) {
        if (this._isEmbedded) return;
        const ids = this.state.requestIds;
        this.state.requestIds = ids.includes(requestId)
            ? ids.filter(id => id !== requestId)
            : [...ids, requestId];
        await this._loadData();
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

    get requestFilterLabel() {
        if (!this.state.requestIds.length) return "Todas";
        const names = this.state.requests
            .filter(r => this.state.requestIds.includes(r.id))
            .map(r => r.name);
        return names.length <= 2 ? names.join(", ") : `${names.length} solicitudes`;
    }

    onSearchChange(ev) {
        this.state.searchText = ev.target.value;
        this._clearSelection();
        this._recompute();
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value || mondayOfCurrentWeek();
        this._loadData();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value || sundayInNWeeks(6);
        this._loadData();
    }

    toggleHideEmptyCts() {
        this.state.hideEmptyCts = !this.state.hideEmptyCts;
        this._clearSelection();
        this._recompute();
    }

    // ── Selección / panel de detalle ─────────────────────────────────────────

    selectLine(line, wcId) {
        if (this.state.activeLineId === line.line_id) {
            this._clearSelection();
        } else {
            this.state.activeLineId   = line.line_id;
            this.state.activeLineData = line;
            this.state.activeWcId     = wcId;
        }
    }

    closeDetail() {
        this._clearSelection();
    }

    _clearSelection() {
        this.state.activeLineId   = null;
        this.state.activeLineData = null;
        this.state.activeWcId     = null;
    }

    // ── Drag & drop ───────────────────────────────────────────────────────────

    onDragStart(ev, line, wcId) {
        this.state.dragLineId = line.line_id;
        this.state.dragWcId   = wcId;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', String(line.line_id));
    }

    onDragEnd() {
        this.state.dragLineId     = null;
        this.state.dragWcId       = null;
        this.state.dragOverKey    = null;
        this.state.dragOverLineId = null;
    }

    onCellDragOver(ev, wcId, wk) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        this.state.dragOverKey    = `${wcId}|${wk}`;
        this.state.dragOverLineId = null;
    }

    onCellDragLeave(ev) {
        // Solo limpiar si realmente salimos de la celda (no hacia un chip hijo)
        if (!ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.dragOverKey = null;
        }
    }

    onChipDragOver(ev, line) {
        ev.preventDefault();
        ev.stopPropagation();
        ev.dataTransfer.dropEffect = 'move';
        this.state.dragOverLineId = line.line_id;
    }

    async onChipDrop(ev, targetLine, targetWcId, wk) {
        ev.preventDefault();
        ev.stopPropagation();

        const srcLineId = this.state.dragLineId;
        const srcWcId   = this.state.dragWcId;

        if (!srcLineId || srcLineId === targetLine.line_id) {
            this.onDragEnd();
            return;
        }

        if (srcWcId === targetWcId) {
            await this._reorderInCt(targetWcId, wk, srcLineId, targetLine.line_id);
        } else {
            await this._reassignToCt(srcLineId, targetWcId);
        }

        this.onDragEnd();
    }

    async onCellDrop(ev, targetWcId, wk) {
        ev.preventDefault();

        const srcLineId = this.state.dragLineId;
        const srcWcId   = this.state.dragWcId;

        if (!srcLineId) { this.onDragEnd(); return; }

        if (srcWcId !== targetWcId) {
            // Soltar en celda de otro CT sin pasar por un chip → mover al final
            await this._reassignToCt(srcLineId, targetWcId);
        }
        // Mismo CT, soltar en zona vacía → no hace falta reordenar

        this.onDragEnd();
    }

    async _reorderInCt(wcId, wk, movedLineId, beforeLineId) {
        const row = this.state.wcRows.find(r => r.wc_id === wcId);
        if (!row) return;

        const cell = [...(row.cells[wk] || [])];
        const movedIdx = cell.findIndex(l => l.line_id === movedLineId);
        if (movedIdx === -1) return;

        const [movedItem] = cell.splice(movedIdx, 1);
        const insertIdx   = cell.findIndex(l => l.line_id === beforeLineId);
        if (insertIdx === -1) {
            cell.push(movedItem);
        } else {
            cell.splice(insertIdx, 0, movedItem);
        }

        // Renumerar secuencias: 10, 20, 30, ...
        const sequenceMap = cell.map((l, i) => ({
            line_id: l.line_id, new_sequence: (i + 1) * 10,
        }));

        try {
            await this.orm.call('mrp.production.request', 'action_resequence_lines', [sequenceMap]);
            // Actualizar estado local sin recargar del servidor
            row.cells[wk] = cell.map((l, i) => ({ ...l, sequence: (i + 1) * 10 }));
            this._recompute();
        } catch (e) {
            this.notification.add(
                (e?.data?.message) || 'Error al reordenar',
                { type: 'danger', sticky: false }
            );
        }
    }

    async _reassignToCt(lineId, newWcId) {
        try {
            await this.orm.call('mrp.production.request', 'action_reassign_wc', [lineId, newWcId]);
            this.notification.add('CT reasignado correctamente.', { type: 'success', sticky: false });
            await this._loadData();
        } catch (e) {
            this.notification.add(
                (e?.data?.message) || 'Error al reasignar CT',
                { type: 'danger', sticky: false }
            );
        }
    }

    // ── Cómputo reactivo ─────────────────────────────────────────────────────

    _recompute() {
        this.state.filteredRows = this._computeFilteredRows();
    }

    _computeFilteredRows() {
        let rows = this.state.wcFilterIds.length
            ? this.state.wcRows.filter(r => this.state.wcFilterIds.includes(r.wc_id))
            : this.state.wcRows;

        const search    = (this.state.searchText || '').trim().toLowerCase();
        const hideEmpty = this.state.hideEmptyCts;

        if (!search && !hideEmpty) return rows;

        const result = [];
        for (const row of rows) {
            const cells = {};
            let hasVisible = false;
            for (const wk of this.state.weekKeys) {
                let lines = row.cells[wk] || [];
                if (search) {
                    lines = lines.filter(l =>
                        (l.product_name || '').toLowerCase().includes(search)
                    );
                }
                cells[wk] = lines;
                if (lines.length) hasVisible = true;
            }
            if (hasVisible || !hideEmpty) {
                result.push({ ...row, cells });
            }
        }
        return result;
    }

    // ── Barra de carga ───────────────────────────────────────────────────────

    getLoadPct(row, wk) {
        const planned  = row.planned_hours_per_week?.[wk] ?? 0;
        const capacity = row.capacity_hours_per_week?.[wk] ?? 0;
        if (!capacity) return null;
        return Math.round((planned / capacity) * 100);
    }

    loadBarClass(pct) {
        if (pct >= 100) return 'sm-load-danger';
        if (pct >= 80)  return 'sm-load-warning';
        return 'sm-load-ok';
    }

    // ── Ventana deslizante de semanas ─────────────────────────────────────────

    get visibleWeekKeys() {
        return this.state.weekKeys.slice(this.state.weekPage, this.state.weekPage + 4);
    }

    get sliderMax() {
        return Math.max(0, this.state.weekKeys.length - 4);
    }

    get weekRangeLabel() {
        const keys = this.state.weekKeys;
        if (!keys.length) return '';
        const from = keys[this.state.weekPage];
        const to   = keys[Math.min(this.state.weekPage + 3, keys.length - 1)];
        const lbl  = this.state.weekLabels;
        if (!from || !lbl[from]) return '';
        if (from === to) return `${lbl[from].label} ${lbl[from].year}`;
        return `${lbl[from].label} – ${lbl[to].label} · ${lbl[from].year}`;
    }

    onSliderChange(ev) {
        this.state.weekPage = parseInt(ev.target.value, 10);
        this._clearSelection();
    }

    prevPage() {
        if (this.state.weekPage > 0) { this.state.weekPage--; this._clearSelection(); }
    }

    nextPage() {
        if (this.state.weekPage < this.sliderMax) { this.state.weekPage++; this._clearSelection(); }
    }

    // ── Helpers de formato ───────────────────────────────────────────────────

    fmtQty(n) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('es', { maximumFractionDigits: 2 });
    }

    fmtPct(n) {
        if (n === null || n === undefined) return '';
        return `${n}%`;
    }

    fmtHours(h) {
        if (!h) return '—';
        const hrs  = Math.floor(h);
        const mins = Math.round((h - hrs) * 60);
        return mins ? `${hrs}h ${mins}m` : `${hrs}h`;
    }

    requestStateLabel(state) {
        return REQUEST_STATE_LABEL[state] || state;
    }

    // ── Apertura de MO en Odoo ───────────────────────────────────────────────

    openRequest(line) {
        if (!line.request_id) return;
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      line.request_name,
            res_model: 'mrp.production.request',
            res_id:    line.request_id,
            views:     [[false, 'form']],
            target:    'current',
        });
    }
}

// Registrar como widget de vista (para uso en formulario con <widget name="..."/>)
registry.category("view_widgets").add("scheduling_matrix_widget", {
    component: SchedulingMatrixWidget,
});

// Registrar como acción cliente (para vista standalone desde menú)
registry.category("actions").add("mrp_scheduling_matrix_action", SchedulingMatrixWidget);
