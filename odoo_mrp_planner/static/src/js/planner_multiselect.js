/** @odoo-module **/

/**
 * Dropdown de filtro multi-selección de los paneles del planificador
 * (depósitos y tipos de operación de Inventario, ubicaciones de Quiebres).
 *
 * Cada instancia opera sobre dos claves del state del widget: el flag de
 * apertura y el array de ids seleccionados. La etiqueta sigue la convención
 * de los paneles: "Todos los X" / nombre del único seleccionado / "N Xs".
 */

/**
 * @param {Component} widget - componente con state reactivo
 * @param {Object} opts
 * @param {string} opts.open - clave del state con el flag de apertura
 * @param {string} opts.ids - clave del state con el array de ids seleccionados
 * @param {Function} opts.items - () => [{id, name}] opciones disponibles
 * @param {string} opts.all - etiqueta sin selección ("Todos los depósitos")
 * @param {string} opts.one - sustantivo singular ("depósito")
 * @param {string} opts.many - sustantivo plural ("depósitos")
 * @param {Function|null} [opts.closeOthers] - cierra el resto de los dropdowns
 *        antes de abrir este (widgets con varios dropdowns y listener global)
 * @param {Function} opts.onChange - callback tras seleccionar/limpiar
 *        (normalmente la recarga del dataset correspondiente)
 */
export function makeMultiFilter(widget, { open, ids, items, all, one, many, closeOthers = null, onChange }) {
    return {
        toggleOpen(ev) {
            ev.stopPropagation();
            const willOpen = !widget.state[open];
            if (closeOthers) closeOthers();
            widget.state[open] = willOpen;
        },
        toggleItem(id) {
            const arr = widget.state[ids];
            const i = arr.indexOf(id);
            if (i >= 0) arr.splice(i, 1); else arr.push(id);
            onChange();
        },
        clear() {
            if (!widget.state[ids].length) return;
            widget.state[ids] = [];
            onChange();
        },
        get label() {
            const selected = widget.state[ids];
            if (!selected.length) return all;
            if (selected.length === 1) {
                const it = items().find((x) => x.id === selected[0]);
                return it ? it.name : `1 ${one}`;
            }
            return `${selected.length} ${many}`;
        },
    };
}
