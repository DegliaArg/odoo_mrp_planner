/** @odoo-module **/

/**
 * @description Persistencia de filtros de los widgets del planificador en localStorage.
 *   Los widgets del tablero pierden su estado OWL al navegar a una sublista y volver
 *   (el componente se remonta). Guardando los filtros por widget y empresa, el usuario
 *   recupera fechas, búsquedas, agrupados y paginación al volver — y también en la
 *   próxima sesión del navegador.
 *   Mismo patrón que column_manager.js (orden/ancho de columnas persistidos).
 */

const PREFIX = 'odoo_mrp_planner.filters.';

/**
 * Restaura sobre `state` las claves indicadas desde localStorage, si hay algo guardado.
 * Las claves ausentes en lo guardado conservan su valor por defecto.
 * @param {string} key - Identificador del widget (incluir la empresa, ej. 'mo_dashboard.1').
 * @param {Object} state - Estado reactivo del widget (useState).
 * @param {string[]} keys - Claves del estado a restaurar.
 */
export function restoreFilters(key, state, keys) {
    let saved = null;
    try {
        const raw = localStorage.getItem(PREFIX + key);
        saved = raw ? JSON.parse(raw) : null;
    } catch (e) {
        return;
    }
    if (!saved || typeof saved !== 'object') return;
    for (const k of keys) {
        if (k in saved && saved[k] !== undefined) state[k] = saved[k];
    }
}

/**
 * Guarda en localStorage las claves indicadas del estado del widget.
 * @param {string} key - Identificador del widget (mismo usado en restoreFilters).
 * @param {Object} state - Estado reactivo del widget.
 * @param {string[]} keys - Claves del estado a persistir.
 */
export function saveFilters(key, state, keys) {
    try {
        const data = {};
        for (const k of keys) data[k] = state[k];
        localStorage.setItem(PREFIX + key, JSON.stringify(data));
    } catch (e) {
        // storage lleno o bloqueado: la persistencia es best-effort
    }
}
