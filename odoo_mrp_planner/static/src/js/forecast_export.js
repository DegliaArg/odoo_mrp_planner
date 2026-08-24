/** @odoo-module **/

import { moCovPctCell, moCovPctRow } from "./forecast_formatters";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

/**
 * Genera y descarga el forecast como Excel SpreadsheetML.
 * @param {Array}    rows        - Filas filtradas del widget (baseFilteredRows).
 * @param {string[]} months      - Array de "YYYY-MM" del período.
 * @param {string}   periodFrom  - Período inicial "YYYY-MM-DD".
 * @param {string}   periodTo    - Período final "YYYY-MM-DD".
 * @param {Object}   [data]      - Payload del dashboard (state.data).
 * @param {Object}   [visibleCols] - Estado de visibilidad de columnas (state.visibleCols).
 */
export function downloadForecastExcel(rows, months, periodFrom, periodTo, data, visibleCols = {}) {
    const vc = visibleCols;
    const showTotal = vc.total && (vc.forecast || vc.mos || vc.delivered || vc.demand_delivered);
    const showAcc   = showTotal && vc.forecast && vc.delivered;
    const covDenominator = data && data.mo_coverage_denominator;

    const esc = s => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const strCell    = v  => `<Cell><Data ss:Type="String">${esc(v)}</Data></Cell>`;
    const numCell    = v  => `<Cell><Data ss:Type="Number">${v == null ? 0 : v}</Data></Cell>`;
    const numOrEmpty = v  => v !== null && v !== undefined
        ? `<Cell><Data ss:Type="Number">${v}</Data></Cell>`
        : `<Cell><Data ss:Type="String"></Data></Cell>`;

    let xml = `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Forecast">
  <Table>
   <Row>`;

    // — Columnas estáticas izquierdas —
    xml += strCell('Artículo');
    if (vc.saleCategory) xml += strCell('Cat. venta');
    if (vc.productCateg) xml += strCell('Familia');
    if (vc.productTypes) xml += strCell('Tipo');
    if (vc.listPrice)    xml += strCell('P. venta');
    if (vc.stock)        xml += strCell('Stock');
    if (vc.rotation)     xml += strCell('Rotación (d)');
    if (vc.coverage)     xml += strCell('Cobertura (d)');
    if (vc.demand)       xml += strCell('Demanda');

    // — Columnas por mes —
    months.forEach(ym => {
        const [y, m] = ym.split('-');
        const label = `${MONTHS_ES[parseInt(m) - 1]} ${y}`;
        if (vc.forecast)         xml += strCell(`${label} - Forecast`);
        if (vc.mos)              xml += strCell(`${label} - OFs`);
        if (vc.mos)              xml += strCell(`${label} - % Cob.`);
        if (vc.delivered)        xml += strCell(`${label} - Entregado`);
        if (vc.demand_delivered) xml += strCell(`${label} - Cumplim.`);
    });

    // — Columnas de totales —
    if (showTotal) {
        if (vc.forecast)         xml += strCell('Total Forecast');
        if (vc.mos)              xml += strCell('Total OFs');
        if (vc.mos)              xml += strCell('% Cob. OFs');
        if (vc.delivered)        xml += strCell('Total Entregado');
        if (vc.demand_delivered) xml += strCell('Total Cumplim.');
        if (showAcc)             xml += strCell('Precisión %');
    }
    xml += '</Row>';

    // — Filas de datos —
    rows.forEach(row => {
        xml += '<Row>';

        xml += strCell(row.product);
        if (vc.saleCategory) xml += strCell(row.sale_category || '');
        if (vc.productCateg) xml += strCell(row.product_categ || '');
        if (vc.productTypes) xml += strCell(row.product_types || '');
        if (vc.listPrice)    xml += numCell(row.list_price || 0);
        if (vc.stock)        xml += numCell(row.stock_qty || 0);
        if (vc.rotation)     xml += numOrEmpty(row.rotation_days);
        if (vc.coverage)     xml += numOrEmpty(row.coverage_days);
        if (vc.demand)       xml += numCell(row.total_so_demand || 0);

        months.forEach(ym => {
            const cell    = (row.cells || []).find(c => c.month === ym) || {};
            const covPct  = cell.month ? moCovPctCell(cell, covDenominator) : 0;
            if (vc.forecast)         xml += numCell(cell.forecast || 0);
            if (vc.mos)              xml += numCell(cell.mos || 0);
            if (vc.mos)              xml += numCell(covPct || 0);
            if (vc.delivered)        xml += numCell(cell.delivered || 0);
            if (vc.demand_delivered) xml += numCell(cell.demand_delivered || 0);
        });

        if (showTotal) {
            if (vc.forecast)         xml += numCell(row.total_forecast || 0);
            if (vc.mos)              xml += numCell(row.total_mos || 0);
            if (vc.mos)              xml += numCell(moCovPctRow(row, covDenominator) || 0);
            if (vc.delivered)        xml += numCell(row.total_delivered || 0);
            if (vc.demand_delivered) xml += numCell(row.total_demand_delivered || 0);
            if (showAcc)             xml += numOrEmpty(row.total_forecast_acc);
        }
        xml += '</Row>';
    });

    xml += `  </Table>
 </Worksheet>
</Workbook>`;

    const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `forecast_${periodFrom}_${periodTo}.xls`;
    a.click();
    URL.revokeObjectURL(url);
}
