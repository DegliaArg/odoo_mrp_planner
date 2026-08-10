/** @odoo-module **/

/**
 * Mecánica de tabla compartida por los paneles del planificador
 * (Inventario, Quiebres de stock, Análisis de clientes): ordenamiento
 * genérico, pestañas de agrupación y paginación client-side.
 *
 * Funciones puras + factory del paginador. Cada widget conserva sus
 * particularidades (comparadores por columna, claves de grupo, cuándo
 * rematerializar la página) y delega acá solo la mecánica común.
 */

/**
 * Ordena por una columna con el comparador genérico de los paneles:
 * null/undefined siempre al final, números en orden numérico y strings
 * con localeCompare es. Devuelve una copia (no muta el array recibido).
 * @param {Array<Object>} rows
 * @param {string} col - clave de la columna
 * @param {string} dir - 'asc' | 'desc'
 * @returns {Array<Object>}
 */
export function sortRows(rows, col, dir) {
    const mult = dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
        const va = a[col], vb = b[col];
        if (va === null || va === undefined) return 1;
        if (vb === null || vb === undefined) return -1;
        if (typeof va === "number") return (va - vb) * mult;
        return String(va).localeCompare(String(vb), "es") * mult;
    });
}

/**
 * Pestañas de agrupación: un grupo por valor devuelto por keyFn, con conteo.
 * keyFn puede devolver un string o un array de strings (M2M: la fila cuenta
 * en la pestaña de cada valor, por lo que la suma puede superar el total).
 * @param {Array<Object>} rows - conjunto base (filtrado/buscado, sin la pestaña)
 * @param {Function} keyFn - fila → clave de grupo (string | string[])
 * @param {Object} [opts]
 * @param {Function} [opts.sortEntries] - comparador de entradas [key, count]
 *        (default: alfabético es, sensitivity base)
 * @param {Function} [opts.labelFn] - clave → etiqueta visible (default: la clave)
 * @returns {Array<{key: string, label: string, count: number}>}
 */
export function buildGroupTabs(rows, keyFn, { sortEntries = null, labelFn = null } = {}) {
    const counts = new Map();
    for (const row of rows) {
        let keys = keyFn(row);
        if (!Array.isArray(keys)) keys = [keys];
        for (const k of keys) counts.set(k, (counts.get(k) || 0) + 1);
    }
    const entries = [...counts.entries()];
    entries.sort(sortEntries ||
        ((a, b) => String(a[0]).localeCompare(String(b[0]), "es", { sensitivity: "base" })));
    return entries.map(([key, count]) => ({ key, label: labelFn ? labelFn(key) : key, count }));
}

/**
 * Pestaña activa: la seleccionada si sigue existiendo en los grupos actuales,
 * si no la primera disponible (o null sin grupos).
 * @param {Array<{key: string}>} groups
 * @param {string|null} selectedKey
 * @returns {string|null}
 */
export function resolveActiveGroup(groups, selectedKey) {
    if ((groups || []).some((g) => g.key === selectedKey)) return selectedKey;
    return groups && groups.length ? groups[0].key : null;
}

/** Operadores del filtro numérico y su símbolo (compartido con la barra). */
export const NUM_OPS = [
    { op: ">",  label: ">" },
    { op: ">=", label: "≥" },
    { op: "<",  label: "<" },
    { op: "<=", label: "≤" },
    { op: "=",  label: "=" },
    { op: "!=", label: "≠" },
];

/** Compara a (op) b; igualdad/desigualdad con tolerancia para floats. */
export function numCompare(a, op, b) {
    switch (op) {
        case ">":  return a >  b;
        case ">=": return a >= b;
        case "<":  return a <  b;
        case "<=": return a <= b;
        case "=":  return Math.abs(a - b) < 1e-6;
        case "!=": return Math.abs(a - b) >= 1e-6;
    }
    return true;
}

/**
 * Aplica una lista de condiciones numéricas (AND) a las filas. Cada condición
 * es {col, op, mode, value, col2}: compara col contra un valor fijo
 * (mode 'value') o contra otra columna (mode 'col'). Las filas sin dato en la
 * columna comparada no matchean.
 * @param {Array} rows
 * @param {Array} numFilters
 * @param {Function} getVal - (row, colKey) => number|null — extractor del widget
 * @returns {Array}
 */
export function applyNumericFilters(rows, numFilters, getVal) {
    if (!numFilters || !numFilters.length) return rows;
    return rows.filter((r) => numFilters.every((c) => {
        const a = getVal(r, c.col);
        if (a === null || a === undefined) return false;
        const b = c.mode === "col" ? getVal(r, c.col2) : c.value;
        if (b === null || b === undefined) return false;
        return numCompare(a, c.op, b);
    }));
}

/**
 * Página actual de un conjunto ya filtrado y ordenado.
 * @param {Array} rows
 * @param {number} page - base 1
 * @param {number} pageSize
 * @returns {Array}
 */
export function pageSlice(rows, page, pageSize) {
    const start = (Math.max(1, page) - 1) * pageSize;
    return rows.slice(start, start + pageSize);
}

/**
 * Paginador sobre state.page/state.pageSize del widget.
 * @param {Component} widget - componente con state reactivo
 * @param {Function} total - () => cantidad total de filas filtradas
 * @param {Function|null} [onChange] - callback tras cambiar de página, para los
 *        widgets que materializan la página visible en el estado (clientes,
 *        quiebres); null si la página es un getter puro (inventario).
 */
export function makePager(widget, total, onChange = null) {
    return {
        get totalPages() { return Math.max(1, Math.ceil(total() / widget.state.pageSize)); },
        get hasNext()    { return widget.state.page < this.totalPages; },
        get hasPrev()    { return widget.state.page > 1; },
        next() { if (this.hasNext) { widget.state.page++; if (onChange) onChange(); } },
        prev() { if (this.hasPrev) { widget.state.page--; if (onChange) onChange(); } },
    };
}
