/** @odoo-module **/

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

/**
 * Genera y descarga el forecast como Excel SpreadsheetML.
 * @param {Array}    rows       - Filas filtradas del widget (baseFilteredRows).
 * @param {string[]} months     - Array de "YYYY-MM" del período.
 * @param {string}   periodFrom - Período inicial "YYYY-MM-DD".
 * @param {string}   periodTo   - Período final "YYYY-MM-DD".
 */
export function downloadForecastExcel(rows, months, periodFrom, periodTo) {
    const esc = s => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

    let xml = `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Forecast">
  <Table>
   <Row>`;

    xml += `<Cell><Data ss:Type="String">Artículo</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Cat. venta</Data></Cell>`;
    months.forEach(ym => {
        const [y, m] = ym.split('-');
        const label = `${MONTHS_ES[parseInt(m) - 1]} ${y}`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - Forecast</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - OFs</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(label)} - %</Data></Cell>`;
    });
    xml += `<Cell><Data ss:Type="String">Total Forecast</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Total OFs</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">% Cumplimiento</Data></Cell>`;
    xml += `<Cell><Data ss:Type="String">Stock</Data></Cell>`;
    xml += '</Row>';

    rows.forEach(row => {
        xml += '<Row>';
        xml += `<Cell><Data ss:Type="String">${esc(row.product)}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="String">${esc(row.sale_category || '')}</Data></Cell>`;
        months.forEach(ym => {
            const cell = (row.cells || []).find(c => c.month === ym) || {};
            xml += `<Cell><Data ss:Type="Number">${cell.forecast || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${cell.mos || 0}</Data></Cell>`;
            xml += `<Cell><Data ss:Type="Number">${cell.pct || 0}</Data></Cell>`;
        });
        xml += `<Cell><Data ss:Type="Number">${row.total_forecast || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.total_mos || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.total_pct || 0}</Data></Cell>`;
        xml += `<Cell><Data ss:Type="Number">${row.stock_qty || 0}</Data></Cell>`;
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
