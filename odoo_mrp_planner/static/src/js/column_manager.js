/** @odoo-module **/

import { useState } from "@odoo/owl";

function _storageKey(tableKey) { return `_planner_cols_v1_${tableKey}`; }

function _load(tableKey, defaultCols) {
    try {
        const raw = localStorage.getItem(_storageKey(tableKey));
        if (!raw) return null;
        const s = JSON.parse(raw);
        if (!s || !Array.isArray(s.order) || typeof s.widths !== 'object') return null;
        const valid = new Set(defaultCols.map(c => c.key));
        const order = s.order.filter(k => valid.has(k));
        // Columnas nuevas (no presentes en la config guardada): se insertan en su
        // posición por defecto — después de la columna default anterior que el
        // usuario ya tenga — en lugar de mandarlas al final de la tabla.
        defaultCols.forEach((c, idx) => {
            if (order.includes(c.key)) return;
            let insertAt = order.length;
            for (let i = idx - 1; i >= 0; i--) {
                const pos = order.indexOf(defaultCols[i].key);
                if (pos !== -1) { insertAt = pos + 1; break; }
            }
            order.splice(insertAt, 0, c.key);
        });
        return { order, widths: { ...s.widths } };
    } catch(e) { return null; }
}

function _save(tableKey, order, widths) {
    try { localStorage.setItem(_storageKey(tableKey), JSON.stringify({ order, widths })); } catch(e) {}
}

/**
 * OWL hook for column resize + reorder with localStorage persistence.
 * Call from setup(): const cols = useColManager('uniqueKey', DEFAULT_COLS);
 *
 * Column shape: { key, label, width?, sortKey?, align?, title?, fixed?, noResize? }
 *   fixed    — excluded from drag reorder, always stays in position
 *   noResize — no resize handle shown
 *   align    — 'end' | 'center' | null (left)
 *
 * Template usage — th attributes:
 *   t-att-data-col-key="col.key"
 *   t-att-data-sort-key="col.sortKey || ''"
 *   t-att-draggable="col.fixed ? 'false' : 'true'"
 *   t-on-dragstart="cols.onDragStart"  t-on-dragover="cols.onDragOver"
 *   t-on-drop="cols.onDrop"            t-on-dragend="cols.onDragEnd"
 *   (plus onHeaderClick in the component reads dataset.sortKey)
 *
 * Resize handle inside th:
 *   <div class="o_col_resize_handle" t-att-data-col-key="col.key"
 *        t-on-mousedown.stop="cols.onResizeStart" t-on-click.stop="() => {}"/>
 */
export function useColManager(tableKey, defaultCols) {
    const saved = _load(tableKey, defaultCols);
    const initOrder  = saved ? saved.order : defaultCols.map(c => c.key);
    const initWidths = saved ? saved.widths : Object.fromEntries(defaultCols.map(c => [c.key, c.width ?? null]));

    const colState = useState({
        order:    initOrder,
        widths:   { ...initWidths },
        dragFrom: null,
        dragOver: null,
    });

    const colMap = Object.fromEntries(defaultCols.map(c => [c.key, c]));

    function visibleCols() {
        return colState.order.map(k => colMap[k]).filter(Boolean);
    }

    function colGroupStyle(key) {
        const w = colState.widths[key];
        return w != null ? `width:${w}px; min-width:${Math.max(20, w)}px;` : '';
    }

    // Track pending resize listeners so they can be removed on unmount.
    let _resizeCleanup = null;

    function onResizeStart(ev) {
        ev.preventDefault();
        const key   = ev.currentTarget.dataset.colKey;
        const th    = ev.currentTarget.closest('th');
        const startX = ev.clientX;
        const startW = th ? th.offsetWidth : (colState.widths[key] ?? 100);
        function onMove(e) {
            const w = Math.max(30, startW + e.clientX - startX);
            colState.widths = { ...colState.widths, [key]: w };
        }
        function onUp() {
            _save(tableKey, colState.order, colState.widths);
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            _resizeCleanup = null;
        }
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        _resizeCleanup = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
    }

    function cancelResize() {
        if (_resizeCleanup) { _resizeCleanup(); _resizeCleanup = null; }
    }

    function onDragStart(ev) {
        const key = ev.currentTarget.dataset.colKey;
        const col = colMap[key];
        if (!col || col.fixed) { ev.preventDefault(); return; }
        colState.dragFrom = key;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', key);
    }

    function onDragOver(ev) {
        const key = ev.currentTarget.dataset.colKey;
        const col = colMap[key];
        if (!col || col.fixed) return;
        ev.preventDefault();
        if (colState.dragOver !== key) colState.dragOver = key;
        ev.dataTransfer.dropEffect = 'move';
    }

    function onDrop(ev) {
        ev.preventDefault();
        const toKey   = ev.currentTarget.dataset.colKey;
        const fromKey = colState.dragFrom;
        if (fromKey && fromKey !== toKey) {
            const fromCol = colMap[fromKey];
            const toCol   = colMap[toKey];
            if (fromCol && !fromCol.fixed && toCol && !toCol.fixed) {
                const ord = [...colState.order];
                const fi  = ord.indexOf(fromKey);
                const ti  = ord.indexOf(toKey);
                if (fi !== -1 && ti !== -1) {
                    ord.splice(fi, 1);
                    ord.splice(ti, 0, fromKey);
                    colState.order = ord;
                    _save(tableKey, ord, colState.widths);
                }
            }
        }
        colState.dragFrom = null;
        colState.dragOver = null;
    }

    function onDragEnd() {
        colState.dragFrom = null;
        colState.dragOver = null;
    }

    function reset() {
        colState.order  = defaultCols.map(c => c.key);
        colState.widths = Object.fromEntries(defaultCols.map(c => [c.key, c.width ?? null]));
        _save(tableKey, colState.order, colState.widths);
    }

    return { state: colState, colMap, visibleCols, colGroupStyle, onResizeStart, cancelResize, onDragStart, onDragOver, onDrop, onDragEnd, reset };
}
