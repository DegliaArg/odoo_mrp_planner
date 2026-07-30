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
 * Umbrales configurables en Ajustes (reusa los de entrega del análisis de clientes).
 * @param {number|null} rate - Tasa de servicio en porcentaje.
 * @param {number} green - Desde este % se muestra verde.
 * @param {number} warn - Desde este % se muestra amarillo; por debajo, rojo.
 * @returns {string} Clase Bootstrap de color.
 */
export function svcClass(rate, green = 80, warn = 60) {
    if (rate === null || rate === undefined) return 'text-muted';
    if (rate >= green) return 'text-success';
    if (rate >= warn)  return 'text-warning';
    return 'text-danger';
}

export function accClass(acc, formula, green = 90, warn = 70) {
    if (acc === null || acc === undefined) return 'text-muted';
    if (formula === 'bias') {
        // El sesgo mide desviación absoluta: se colorea con los complementos
        // de los mismos umbrales (verde ≤ 100−green, amarillo ≤ 100−warn).
        const abs = Math.abs(acc);
        if (abs <= 100 - green) return 'text-success';
        if (abs <= 100 - warn)  return 'text-warning';
        return 'text-danger';
    }
    if (acc >= green) return 'text-success';
    if (acc >= warn)  return 'text-warning';
    return 'text-danger';
}

export function fmtRotation(row, rotation_unit) {
    if (rotation_unit === 'months') {
        const v = row.rotation_months;
        return v !== null && v !== undefined ? `${v} m` : '—';
    }
    const v = row.rotation_days;
    return v !== null && v !== undefined ? `${v} d` : '—';
}

export function rotClass(row, rotation_unit) {
    const v = rotation_unit === 'months' ? row.rotation_months : row.rotation_days;
    if (v === null || v === undefined) return 'text-muted';
    const threshold = rotation_unit === 'months' ? 3 : 90;
    return v <= threshold ? 'text-success' : v <= threshold * 2 ? 'text-warning' : 'text-muted';
}

export function fmtCoverage(row, coverage_unit) {
    if (coverage_unit === 'months') {
        const v = row.coverage_months;
        return v !== null && v !== undefined ? `${v} m` : '—';
    }
    const v = row.coverage_days;
    return v !== null && v !== undefined ? `${v} d` : '—';
}

export function covClass(row, d) {
    if (!d || !d.coverage_alerts_enabled) return 'text-muted';
    const v = row.coverage_days;
    if (v === null || v === undefined) return 'text-muted';
    const warn = d.coverage_warn_days || 30;
    const crit = d.coverage_critical_days || 15;
    if (v <= crit) return 'text-danger fw-bold';
    if (v <= warn) return 'text-warning fw-semibold';
    return 'text-success';
}

export function demandGapClass(pct, ok = 10, warn = 25) {
    if (pct === null || pct === undefined) return 'text-muted';
    const abs = Math.abs(pct);
    if (abs <= ok)   return 'text-success fw-semibold';
    if (abs <= warn) return 'text-warning fw-semibold';
    return 'text-danger fw-semibold';
}

export function mosGapClass(pct, ok = 10) {
    if (pct === null || pct === undefined) return 'text-muted';
    if (pct >= 0)   return 'text-success fw-semibold';
    if (pct >= -ok) return 'text-warning fw-semibold';
    return 'text-danger fw-semibold';
}

export function fmtGapPct(n) {
    if (n === null || n === undefined) return '—';
    return `${n > 0 ? '+' : ''}${n}%`;
}

export function fmt(n) {
    if (n === null || n === undefined) return '—';
    return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n);
}

export function fmtPct(n) {
    if (n === null || n === undefined) return '—';
    return `${Math.round(n)}%`;
}

export function fmtDate(d) {
    if (!d) return '—';
    const [y, m, day] = d.split('-');
    return `${day}/${m}/${y}`;
}

export function sortIcon(col, sortCol, sortDir) {
    if (sortCol !== col) return 'fa fa-sort text-muted ms-1';
    return sortDir === 'asc'
        ? 'fa fa-sort-asc text-primary ms-1'
        : 'fa fa-sort-desc text-primary ms-1';
}

export function colTitle(col, rotTitle, covTitle) {
    if (col.key === 'rotation')     return rotTitle;
    if (col.key === 'coverage')     return covTitle;
    if (col.key === 'product')      return 'Ordenar por nombre de artículo';
    if (col.key === 'saleCategory') return 'Categoría de venta (A=alta rotación, E=baja). Clic para ordenar.';
    if (col.key === 'productCateg') return 'Familia de producto (product.template.categ_id). Clic para ordenar.';
    if (col.key === 'productTypes') return 'Tipos de producto asignados en la ficha (x_product_type_ids). Clic para ordenar.';
    if (col.key === 'listPrice')    return 'Precio de venta de la ficha del artículo (tarifa base, sin impuestos). Clic para ordenar.';
    if (col.key === 'stock')        return 'Stock disponible en ubicaciones internas. Clic para ordenar.';
    if (col.key === 'demand')       return 'Demanda del período: cantidad total de pedidos de venta confirmados. Clic para ordenar.';
    return '';
}
