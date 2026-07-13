/** @odoo-module **/

/**
 * Funciones puras de formateo para el widget de forecast.
 * No dependen de ningún estado del componente — reciben todos los datos
 * como parámetros y devuelven strings CSS o HTML.
 */

/**
 * Devuelve la clase CSS del badge de estado de una OF.
 * @param {string} state - Estado Odoo de la OF.
 * @returns {string} Clases Bootstrap del badge.
 */
export function moStateBadge(state) {
    const map = {
        draft:     'bg-secondary',
        confirmed: 'bg-info text-dark',
        progress:  'bg-primary',
        to_close:  'bg-warning text-dark',
        done:      'bg-success',
        cancel:    'bg-light text-muted',
    };
    return `badge ${map[state] || 'bg-secondary'}`;
}

/**
 * Devuelve la clase CSS del badge de categoría ABC de ventas.
 * @param {string} cat - Categoría ABC: 'A', 'B', 'C', 'D' o 'E'.
 * @returns {string} Clases Bootstrap del badge.
 */
export function saleCatBadge(cat) {
    const map = {
        A: 'bg-success text-white',
        B: 'bg-info text-dark',
        C: 'bg-warning text-dark',
        D: 'bg-secondary text-white',
        E: 'bg-light text-muted border',
    };
    return `badge ${map[cat] || 'bg-light text-muted'}`;
}

/**
 * Calcula el % efectivo de cobertura de OFs según el denominador configurado.
 * @param {number} mos - OFs del período.
 * @param {number} forecast - Forecast del período.
 * @param {number} so_demand - Demanda SO del período.
 * @param {string} mo_coverage_denominator - 'so_demand' u otro valor.
 * @returns {number}
 */
export function moCovPct(mos, forecast, so_demand, mo_coverage_denominator) {
    if (mo_coverage_denominator === 'so_demand') {
        return so_demand > 0 ? Math.round(mos / so_demand * 1000) / 10 : 0.0;
    }
    return forecast > 0 ? Math.round(mos / forecast * 1000) / 10 : 0.0;
}

/**
 * Pct efectivo para una celda mensual.
 * @param {Object} cell - Celda con mos, forecast, so_demand.
 * @param {string} mo_coverage_denominator
 * @returns {number}
 */
export function moCovPctCell(cell, mo_coverage_denominator) {
    return moCovPct(cell.mos, cell.forecast, cell.so_demand, mo_coverage_denominator);
}

/**
 * Pct efectivo para el total de una fila.
 * @param {Object} row - Fila con total_mos, total_forecast, total_so_demand.
 * @param {string} mo_coverage_denominator
 * @returns {number}
 */
export function moCovPctRow(row, mo_coverage_denominator) {
    return moCovPct(row.total_mos, row.total_forecast, row.total_so_demand, mo_coverage_denominator);
}

/**
 * Clase CSS de cobertura de OFs basada en un pct y los umbrales configurados.
 * @param {number} forecast
 * @param {number} pct
 * @param {number} warning_pct - Umbral amarillo de cobertura.
 * @returns {string}
 */
export function cellClassForPct(forecast, pct, warning_pct) {
    if (!forecast) return '';
    if (pct >= 100) return 'forecast-ok';
    if (pct >= warning_pct) return 'forecast-warning';
    return 'forecast-critical';
}

/**
 * Clase CSS para una celda mensual.
 * Respeta el alcance de color (solo totales vs mensual+total).
 * @param {Object} cell
 * @param {string} mo_coverage_color_scope
 * @param {number} warning_pct
 * @param {string} mo_coverage_denominator
 * @returns {string}
 */
export function cellClassMonthly(cell, mo_coverage_color_scope, warning_pct, mo_coverage_denominator) {
    if (mo_coverage_color_scope === 'total_only') return '';
    return cellClassForPct(cell.forecast, moCovPctCell(cell, mo_coverage_denominator), warning_pct);
}

/**
 * Clase CSS para la celda de total de OFs de una fila.
 * Siempre se colorea independientemente del alcance configurado.
 * @param {Object} row
 * @param {number} warning_pct
 * @param {string} mo_coverage_denominator
 * @returns {string}
 */
export function cellClassTotal(row, warning_pct, mo_coverage_denominator) {
    return cellClassForPct(row.total_forecast, moCovPctRow(row, mo_coverage_denominator), warning_pct);
}

/**
 * Clase CSS para una celda de cobertura mensual.
 * @param {Object} cell
 * @param {number} warning_pct
 * @param {string} mo_coverage_denominator
 * @returns {string}
 */
export function cellClass(cell, warning_pct, mo_coverage_denominator) {
    if (!cell || cell.forecast === 0) return '';
    return cellClassForPct(cell.forecast, moCovPctCell(cell, mo_coverage_denominator), warning_pct);
}

/**
 * Clase CSS para la tasa de servicio al cliente.
 * Verde ≥ 95 %, amarillo ≥ 80 %, rojo por debajo.
 * @param {number|null} rate - Tasa de servicio en porcentaje.
 * @returns {string} Clase Bootstrap de color.
 */
export function svcClass(rate) {
    if (rate === null || rate === undefined) return 'text-muted';
    if (rate >= 95) return 'text-success';
    if (rate >= 80) return 'text-warning';
    return 'text-danger';
}
