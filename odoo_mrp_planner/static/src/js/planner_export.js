/** @odoo-module **/

/**
 * Export a archivo compartido por las tablas de los paneles del planificador:
 * CSV (Inventario, Quiebres) y Excel XML (Análisis de clientes).
 *
 * Cada widget aporta sus encabezados y una función de celda; acá vive solo
 * la mecánica común (escape, armado del archivo y descarga en el navegador).
 */

/** Descarga un contenido como archivo en el navegador. */
export function downloadFile(content, filename, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

/**
 * Exporta filas como CSV.
 * @param {Object} opts
 * @param {string} opts.filename
 * @param {Array<string>} opts.headers - etiquetas de columna
 * @param {Array} opts.rows - filas (cualquier forma; cell las interpreta)
 * @param {Function} opts.cell - fila → array de valores en el orden de headers
 * @param {string} [opts.sep] - separador (default ",")
 * @param {boolean} [opts.bom] - anteponer BOM UTF-8 (Excel es-AR con sep ";")
 * @param {string} [opts.quote] - "auto" (solo si hace falta) | "always"
 */
export function downloadCsv({ filename, headers, rows, cell, sep = ",", bom = false, quote = "auto" }) {
    const esc = (v) => {
        const s = String(v ?? "");
        if (quote === "always" || s.includes(sep) || s.includes('"') || s.includes("\n")) {
            return `"${s.replace(/"/g, '""')}"`;
        }
        return s;
    };
    const lines = [headers.map(esc).join(sep)];
    for (const row of rows) {
        lines.push(cell(row).map(esc).join(sep));
    }
    downloadFile((bom ? "﻿" : "") + lines.join("\n"), filename, "text/csv;charset=utf-8;");
}

/** Escape de texto para XML (Excel XML del análisis de clientes). */
export function escXml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/**
 * Exporta filas como Excel XML (SpreadsheetML .xls).
 * @param {Object} opts
 * @param {string} opts.filename
 * @param {string} opts.sheet - nombre de la hoja
 * @param {Array<string>} opts.headers - etiquetas de columna
 * @param {Array} opts.rows
 * @param {Function} opts.cell - fila → array de valores; los number van como
 *        Number en el XML, el resto como String
 */
export function downloadExcelXml({ filename, sheet, headers, rows, cell }) {
    let xml = `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="${escXml(sheet)}">
  <Table>
   <Row>`;
    headers.forEach((h) => {
        xml += `<Cell><Data ss:Type="String">${escXml(h)}</Data></Cell>`;
    });
    xml += "</Row>";
    rows.forEach((row) => {
        xml += "<Row>";
        cell(row).forEach((v) => {
            const type = typeof v === "number" ? "Number" : "String";
            xml += `<Cell><Data ss:Type="${type}">${escXml(String(v))}</Data></Cell>`;
        });
        xml += "</Row>";
    });
    xml += `  </Table>
 </Worksheet>
</Workbook>`;
    downloadFile(xml, filename, "application/vnd.ms-excel;charset=utf-8");
}
