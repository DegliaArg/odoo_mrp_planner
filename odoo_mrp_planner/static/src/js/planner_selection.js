/** @odoo-module **/

/**
 * Selección de filas compartida por las tablas de los paneles del
 * planificador (Inventario, Quiebres, Análisis de clientes).
 *
 * Convención de los paneles: state.selected es un mapa id → bool; los KPIs
 * y totales describen SOLO la selección cuando la hay; "Seleccionar todos"
 * opera sobre la página visible.
 */

/**
 * @param {Component} widget - componente con state.selected reactivo
 * @param {Object} opts
 * @param {string} [opts.key] - campo id de las filas (default "id")
 * @param {Function} opts.pageRows - () => filas de la página visible
 * @param {Function|null} [opts.onChange] - callback tras cada cambio, para
 *        los widgets que recalculan KPIs/totales materializados (clientes);
 *        null si los KPIs son getters puros (inventario, quiebres).
 */
export function makeSelection(widget, { key = "id", pageRows, onChange = null } = {}) {
    return {
        toggle(row) {
            widget.state.selected[row[key]] = !widget.state.selected[row[key]];
            if (onChange) onChange();
        },
        get allSelected() {
            const rows = pageRows();
            return rows.length > 0 && rows.every((r) => widget.state.selected[r[key]]);
        },
        toggleAll() {
            const target = !this.allSelected;
            for (const r of pageRows()) {
                widget.state.selected[r[key]] = target;
            }
            if (onChange) onChange();
        },
        clear() {
            widget.state.selected = {};
            if (onChange) onChange();
        },
        /** Filas seleccionadas dentro del conjunto dado (todas las páginas). */
        pick(rows) {
            return rows.filter((r) => widget.state.selected[r[key]]);
        },
    };
}
