/** @odoo-module **/

import { moCovPctCell, moCovPctRow } from "./forecast_formatters";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

/**
 * Genera y descarga el forecast como Excel SpreadsheetML.
 * @param {Array}    rows       - Filas filtradas del widget (baseFilteredRows).
 * @param {string[]} months     - Array de "YYYY-MM" del período.
 * @param {string}   periodFrom - Período inicial "YYYY-MM-DD".
 * @param {string}   periodTo   - Período final "YYYY-MM-DD".
 * @param {Object}   [data]     - Payload del dashboard (state.data); se usa para
 *                                mo_coverage_denominator (denominador de cobertura de OFs).
 */
export function downloadForecastExcel(rows, months, periodFrom, periodTo, data) {
    const esc = s => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const covDenominator = data && data.mo_coverage_denominator;

    let xml = `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Forecast">
  <Table>
   <Row>`;

    xml += `<Cell><Data ss:Type="String">Artículo</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Cat. venta</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Precio venta</Data></Cell>`;
    months.forEach(ym => {
        const [y, m] = ym.split('-');
        const label = `${MONTHS_ES[parseInt(m) - 1]} ${y}`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - Forecast</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - OFs</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - %</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - Entregado</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - Cumplim.</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - Demanda</Data></Cell>`;
    });
    xml += `<Cell><Data ss:Type="String">Total Forecast</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Total OFs</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">% Cobertura OFs</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Total Entregado</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Total Cumplim.</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Total Demanda</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Stock</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Rotación (d)</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Cobertura (d)</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Precisión %</Data></Cell>`;
    xml += '</Row>';

    rows.forEach(row => {
        xml += '<Row>';
        xml += `<Cell><Data ss:Type="String">${esc(row.product)}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(row.sale_category || '')}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.list_price || 0}</Data></Cell>`;
        months.forEach(ym => {
            const cell = (row.cells || []).find(c => c.month === ym) || {};
            const covPct = cell.month ? moCovPctCell(cell, covDenominator) : 0;
            xml += `<Cell><Data ss:Type="Number">${cell.forecast || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${cell.mos || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${covPct || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${cell.delivered || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${cell.demand_delivered || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${cell.so_demand || 0}</Data></Cell>`;
        });
        xml += `<Cell><Data ss:Type="Number">${row.total_forecast || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.total_mos || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${moCovPctRow(row, covDenominator) || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.total_delivered || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.total_demand_delivered || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.total_so_demand || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.stock_qty || 0}</Data></Cell>`;
        xml += row.rotation_days !== null && row.rotation_days !== undefined
            ? `<Cell><Data ss:Type="Number">${row.rotation_days}</Data></Cell>`
            : `<Cell><Data ss:Type="String"></Data></Cell>`;
        xml += row.coverage_days !== null && row.coverage_days !== undefined
            ? `<Cell><Data ss:Type="Number">${row.coverage_days}</Data></Cell>`
            : `<Cell><Data ss:Type="String"></Data></Cell>`;
        xml += row.total_forecast_acc !== null && row.total_forecast_acc !== undefined
            ? `<Cell><Data ss:Type="Number">${row.total_forecast_acc}</Data></Cell>`
            : `<Cell><Data ss:Type="String"></Data></Cell>`;
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
