/** @odoo-module **/

/**
 * Funciones de tooltip para ForecastWidget.
 * Cada función recibe `widget` como primer argumento para acceder a su estado
 * y métodos de formateo sin acoplar el módulo al componente completo.
 */

export function moTooltip(widget, cell) {
    if (!cell || cell.forecast === 0) return '';
    const denom = widget.state.data && widget.state.data.mo_coverage_denominator;
    const pct = widget.moCovPctCell(cell);
    if (denom === 'so_demand') {
        return `Cobertura de OFs planificadas respecto a la demanda real de pedidos de venta\nOFs ÷ demanda SO × 100\n→ ${widget.fmt(cell.mos)} ÷ ${widget.fmt(cell.so_demand)} × 100 = ${widget.fmtPct(pct)}`;
    }
    return `Cobertura de OFs planificadas respecto al forecast del período\nOFs ÷ forecast × 100\n→ ${widget.fmt(cell.mos)} ÷ ${widget.fmt(cell.forecast)} × 100 = ${widget.fmtPct(pct)}`;
}

export function svcTooltip(widget, cell) {
    if (cell.service_rate === null || cell.service_rate === undefined)
        return 'Sin pedidos de venta confirmados en el período';
    return `Porcentaje de la demanda real entregada efectivamente al cliente\nTotal entregado ÷ Total pedidos de venta × 100\n→ ${widget.fmt(cell.delivered)} ÷ ${widget.fmt(cell.so_demand)} × 100 = ${widget.fmtPct(cell.service_rate)}`;
}

export function rotHeaderTitle(widget) {
    const method = widget.state.data && widget.state.data.rotation_method;
    if (method === 'cogs')  return 'Rotación COGS = período (días) × inventario promedio (costo) ÷ costo de ventas. Clic para ordenar.';
    if (method === 'sales') return 'Rotación Ventas = período (días) × inventario promedio (costo) ÷ ventas netas. Clic para ordenar.';
    return 'Rotación Unidades = stock promedio del período ÷ (entregado ÷ N meses). Clic para ordenar.';
}

export function rotTooltip(widget, row) {
    const method = widget.state.data && widget.state.data.rotation_method;
    const unit   = widget.state.data && widget.state.data.rotation_unit;
    const val    = widget.fmtRotation(row);
    const n      = widget.state.data ? (widget.state.data.rotation_n_months || widget.state.data.months.length) : 1;
    const nLabel = Number.isInteger(n) ? n : n.toFixed(1).replace('.0', '');

    if (!val || val === '—') {
        if (method === 'cogs')  return 'Sin inventario promedio valorizado — rotación no calculable';
        if (method === 'sales') return 'Sin ventas o sin inventario valorizado — rotación no calculable';
        return 'Sin entregas en el período — rotación no calculable';
    }
    if (method === 'cogs') {
        return `Días cubiertos por el inventario valorizado al ritmo del costo de ventas\nPeríodo (días) × inventario promedio (costo) ÷ costo de lo vendido\n→ ${Math.round(n * 30)} d × inv. promedio ÷ COGS = ${val}`;
    }
    if (method === 'sales') {
        return `Días cubiertos por el inventario valorizado al ritmo de las ventas netas\nPeríodo (días) × inventario promedio (costo) ÷ ventas netas\n→ ${Math.round(n * 30)} d × inv. promedio ÷ ventas = ${val}`;
    }
    const suffix = unit !== 'months' ? ' × 30' : '';
    return `Tiempo que dura el inventario al ritmo de salidas del período\nStock promedio ÷ (entregado ÷ meses)${suffix}\n→ ${widget.fmt(row.avg_stock_qty)} ÷ (${widget.fmt(row.total_delivered)} ÷ ${nLabel} meses)${suffix} = ${val}`;
}

export function covTooltip(widget, row) {
    const d = widget.state.data;
    const val = widget.fmtCoverage(row);
    if (!val || val === '—') return 'Sin datos de demanda en el período — cobertura no calculable';
    const n = d ? (d.rotation_n_months || d.months.length) : 1;
    const periodDays = Math.round(n * 30);
    const source = d && d.coverage_demand_source;
    let demLabel, demQty;
    if (source === 'so_demand') {
        demLabel = 'demanda SO';
        demQty   = row.total_so_demand;
    } else if (source === 'delivered') {
        demLabel = 'entregado';
        demQty   = row.total_delivered;
    } else {
        demLabel = 'forecast';
        demQty   = row.total_forecast;
    }
    return `Días que cubre el stock actual al ritmo de ${demLabel} del período\nStock disponible ÷ (${demLabel} ÷ período)\n→ ${widget.fmt(row.stock_qty)} ÷ (${widget.fmt(demQty)} ${demLabel} ÷ ${periodDays} d) = ${val}`;
}

export function covHeaderTitle(widget) {
    const d = widget.state.data;
    const source = d && d.coverage_demand_source;
    const label = source === 'so_demand' ? 'demanda SO (pedidos confirmados)'
                : source === 'delivered' ? 'historial de entregas'
                : 'forecast planificado';
    return `Cobertura de inventario: días (o meses) que cubre el stock actual a la tasa de ${label}. Clic para ordenar.`;
}

export function accGlobalTooltip(widget) {
    const d = widget.state.data;
    if (!d) return '';
    const formula = d.acc_formula;
    const dem = widget.fmt(d.kpis.total_so_demand), fc = widget.fmt(d.kpis.total_forecast);
    const val = widget.fmtPct(d.kpis.overall_forecast_acc);
    if (formula === 'mape')
        return `Precisión promedio por artículo (sensible a artículos de bajo volumen)\nPromedio de precisiones individuales vs demanda real por artículo\n→ promedio global = ${val}`;
    if (formula === 'wape')
        return `Precisión ponderada por volumen de demanda real (menos sensible a bajo volumen)\n100 − (Σ|errores| ÷ demanda real × 100)\n→ 100 − (Σ|errores| ÷ ${dem} × 100) = ${val}`;
    if (formula === 'wmape')
        return `Precisión ponderada por volumen de forecast\n100 − (Σ|errores| ÷ Σforecast × 100)\n→ 100 − (Σ|errores| ÷ ${fc} × 100) = ${val}`;
    if (formula === 'bias')
        return `Sesgo del forecast: mide si se sobreestima o subestima la demanda real\n(demanda real − forecast) ÷ forecast × 100\n→ (${dem} − ${fc}) ÷ ${fc} × 100 = ${val}`;
    return `Porcentaje de la demanda real cubierta por el forecast (puede superar 100%)\ndemanda real ÷ forecast × 100\n→ ${dem} ÷ ${fc} × 100 = ${val}`;
}

export function accTooltip(widget, row) {
    const a = row.acc_all;
    if (!a) return 'Sin datos suficientes para calcular precisión';
    const configured = (widget.state.data && widget.state.data.acc_formula) || 'simple';
    const fv = v => v !== null && v !== undefined ? `${v}%` : '—';
    const mark = key => key === configured ? ' ◀' : '';
    return [
        `Simple (dem. real):  ${fv(a.simple)}${mark('simple')}`,
        `MAPE (dem. real):    ${fv(a.mape)}${mark('mape')}`,
        `WAPE (dem. real):    ${fv(a.wape)}${mark('wape')}`,
        `WMAPE:               ${fv(a.wmape)}${mark('wmape')}`,
        `Sesgo (dem. real):   ${fv(a.bias)}${mark('bias')}`,
    ].join('\n');
}

export function fcKpiTooltip(widget, key) {
    const d = widget.state.data;
    if (!d) return '';
    const k = d.kpis;
    switch (key) {
        case 'forecast':
            return `Unidades planificadas en líneas de forecast activas para el período seleccionado\n→ ${widget.fmt(k.total_forecast)} u`;
        case 'so_demand':
            return `Unidades pedidas en órdenes de venta confirmadas de productos con línea de forecast\n→ ${widget.fmt(k.total_so_demand)} u en el período`;
        case 'mos':
            return `Unidades en OFs activas con fecha de fin en el período, de productos con línea de forecast\n→ ${widget.fmt(k.total_mos)} u planificadas`;
        case 'delivered': {
            const fk = widget.filteredKpis;
            const byMonth = fk.del_by_order_month || {};
            const sortedMonths = Object.keys(byMonth).sort();
            const lines = sortedMonths.map(ym => {
                const [y, m] = ym.split('-');
                const label = new Date(+y, +m - 1, 1).toLocaleString('es', { month: 'long', year: 'numeric' });
                return `  ${label}: ${widget.fmt(byMonth[ym])} u`;
            });
            const breakdown = lines.length
                ? '\nPor mes de confirmación del pedido:\n' + lines.join('\n')
                : '';
            return `Unidades entregadas físicamente en el período seleccionado (albaranes validados), de cualquier pedido${breakdown}`;
        }
        case 'demand_delivered':
            return `Todo lo entregado de pedidos confirmados en el período, sin importar la fecha de entrega\n→ ${widget.fmt(widget.filteredKpis.total_demand_delivered)} u`;
        case 'svc': {
            const fk = widget.filteredKpis;
            const kpi = widget.state.data.kpis;
            const noFcDel = kpi.delivered_no_fc || 0;
            const noFcDem = kpi.so_demand_no_fc || 0;
            const totalDel = fk.total_delivered + noFcDel;
            const totalDem = (fk.total_so_demand || 0) + noFcDem;
            const noFcPart = noFcDel > 0 || noFcDem > 0
                ? `\n  Entregas: ${widget.fmt(fk.total_delivered)} FC + ${widget.fmt(noFcDel)} sin FC = ${widget.fmt(totalDel)}`
                + `\n  Demanda:  ${widget.fmt(fk.total_so_demand)} FC + ${widget.fmt(noFcDem)} sin FC = ${widget.fmt(totalDem)}`
                : '';
            return `Entregas físicas del período ÷ demanda real total${noFcPart}\n→ ${widget.fmt(totalDel)} ÷ ${widget.fmt(totalDem)} × 100 = ${widget.fmtPct(fk.overall_service_rate)}`;
        }
        case 'demand_svc': {
            const fk = widget.filteredKpis;
            const kpi = widget.state.data.kpis;
            const noFcDel = kpi.demand_delivered_no_fc || 0;
            const noFcDem = kpi.so_demand_no_fc || 0;
            const totalDel = fk.total_demand_delivered + noFcDel;
            const totalDem = (fk.total_so_demand || 0) + noFcDem;
            const noFcPart = noFcDel > 0 || noFcDem > 0
                ? `\n  Entregado: ${widget.fmt(fk.total_demand_delivered)} FC + ${widget.fmt(noFcDel)} sin FC = ${widget.fmt(totalDel)}`
                + `\n  Demanda:   ${widget.fmt(fk.total_so_demand)} FC + ${widget.fmt(noFcDem)} sin FC = ${widget.fmt(totalDem)}`
                : '';
            return `Cumplimiento (pedidos del período entregados en cualquier fecha) ÷ demanda real total${noFcPart}\n→ ${widget.fmt(totalDel)} ÷ ${widget.fmt(totalDem)} × 100 = ${widget.fmtPct(fk.overall_demand_service_rate)}`;
        }
    }
    return '';
}

export function demandGapTooltip(widget) {
    const d = widget.state.data;
    if (!d) return '';
    const dem = widget.fmt(d.kpis.total_so_demand), fc = widget.fmt(d.kpis.total_forecast);
    const val = widget.fmtGapPct(d.kpis.demand_gap_pct);
    return `Variación de la demanda real respecto al forecast. Positivo: se demandó más de lo planeado.\n(demanda real − forecast) ÷ forecast × 100\n→ (${dem} − ${fc}) ÷ ${fc} × 100 = ${val}`;
}

export function mosGapTooltip(widget) {
    const d = widget.state.data;
    if (!d) return '';
    const mos = widget.fmt(d.kpis.total_mos), fc = widget.fmt(d.kpis.total_forecast);
    const val = widget.fmtGapPct(d.kpis.mos_gap_pct);
    return `Cobertura de OFs planificadas respecto al forecast. Positivo: producción cubre el plan. Negativo: déficit.\n(OFs − forecast) ÷ forecast × 100\n→ (${mos} − ${fc}) ÷ ${fc} × 100 = ${val}`;
}

export function accSecondaryPills(widget) {
    const d = widget.state.data;
    if (!d || !d.kpis.acc_all) return [];
    const all = d.kpis.acc_all;
    const configured = d.acc_formula || 'simple';
    const LABELS = { simple: 'Simple', mape: 'MAPE', wape: 'WAPE', wmape: 'WMAPE', bias: 'Sesgo' };
    return Object.entries(LABELS)
        .filter(([key]) => key !== configured)
        .map(([key, label]) => ({ key, label, value: all[key] }));
}
