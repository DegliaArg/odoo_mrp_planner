/** @odoo-module **/

/**
 * Panel de Análisis de compras productivas.
 *
 * Muestra las OFs del sector seleccionado (tag de CT) con sus OTs planificadas
 * en el rango de fechas, agrupadas por semana ISO, y para cada OF despliega
 * todas las OCs descendientes a cualquier profundidad de la cadena MTO.
 *
 * RPC: get_wc_tags, get_purchase_analysis
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function firstOfMonth() {
    const d = new Date();
    return toDateStr(new Date(d.getFullYear(), d.getMonth(), 1));
}
function lastOfMonth() {
    const d = new Date();
    return toDateStr(new Date(d.getFullYear(), d.getMonth() + 1, 0));
}

const PO_STATE_CLASS = {
    draft:          "badge bg-secondary",
    sent:           "badge bg-warning text-dark",
    "to approve":   "badge bg-info text-dark",
    purchase:       "badge bg-primary",
    done:           "badge bg-success",
    cancel:         "badge bg-danger",
};

const MO_STATE_CLASS = {
    draft:     "badge bg-secondary",
    confirmed: "badge bg-info text-dark",
    progress:  "badge bg-primary",
    to_close:  "badge bg-warning text-dark",
    done:      "badge bg-success",
    cancel:    "badge bg-danger",
};

class PurchaseAnalysisWidget extends Component {
    static template = "odoo_mrp_planner.PurchaseAnalysisWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm            = useService("orm");
        this.action         = useService("action");
        this.companyService = useService("company");
        this._company       = {};

        this.state = useState({
            tags:         [],
            tagIds:       [],
            wcs:          [],   // CTs disponibles para el sector seleccionado
            wcFilterId:   null, // CT seleccionado (null = todos)
            showFinished: false, // mostrar OFs con estado 'done'
            searchText:   '',   // búsqueda por nombre de producto
            dateFrom:     firstOfMonth(),
            dateTo:       lastOfMonth(),
            weekKeys:     [],
            weekLabels:   {},
            wcRows:       [],
            totalMos:     0,
            totalPos:     0,
            loading:      true,
            error:        null,
            activeMoId:   null,
            activeMoData: null,
            activeMoWcId:   null,
            expandedGroups: {},
            weekPage:       0,
            filteredRows:   [],
            kpi:            { late: [], pending: [], toApprove: [], noPos: [], ok: [] },
        });

        onMounted(async () => {
            this._loadCompany();   // fire-and-forget; no bloquea la carga principal
            try {
                await this._loadTags();
                // No cargamos datos hasta que el usuario seleccione un sector
            } catch (e) {
                if (e.message !== "Component is destroyed") {
                    this.state.error = (e && e.data && e.data.message) || e.message || String(e);
                    this.state.loading = false;
                }
            }
        });
    }

    // ── Carga de datos ──────────────────────────────────────────────────────

    async _loadTags() {
        const d = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
        this.state.tags = (d && d.tags) || [];
        const defaultTagId = d && d.default_purchase_analysis_tag_id;
        if (defaultTagId && !this.state.tagIds.length) {
            const found = this.state.tags.find(t => t.id === defaultTagId);
            if (found) {
                this.state.tagIds = [defaultTagId];
                await this._loadWcs();
                await this._loadData();
                return;
            }
        }
        this.state.loading = false;
    }

    async _loadWcs() {
        if (!this.state.tagIds.length) {
            this.state.wcs        = [];
            this.state.wcFilterId = null;
            return;
        }
        const wcs = await this.orm.call(
            "mrp.planner.dashboard", "get_wcs_for_tags", [this.state.tagIds]);
        this.state.wcs        = wcs || [];
        this.state.wcFilterId = null;
    }

    async _loadCompany() {
        try {
            const companyId = this.companyService?.currentCompany?.id || 1;
            const [co] = await this.orm.read(
                "res.company", [companyId],
                ["name", "logo", "primary_color", "secondary_color",
                 "street", "city", "zip", "phone", "email", "website"]
            );
            this._company = co || {};
        } catch (e) {
            console.warn("[PurchaseAnalysis] Could not load company info:", e);
        }
    }

    async _loadData() {
        if (!this.state.tagIds.length) {
            this.state.weekKeys   = [];
            this.state.weekLabels = {};
            this.state.wcRows     = [];
            this.state.totalMos   = 0;
            this.state.totalPos   = 0;
            this.state.loading    = false;
            return;
        }
        this.state.loading    = true;
        this.state.error      = null;
        this.state.activeMoId = null;
        this.state.activeMoData = null;
        try {
            const result = await this.orm.call(
                "mrp.planner.dashboard",
                "get_purchase_analysis",
                [this.state.tagIds, this.state.dateFrom, this.state.dateTo]
            );
            this.state.weekKeys   = (result && result.week_keys)   || [];
            this.state.weekLabels = (result && result.week_labels) || {};
            this.state.wcRows     = (result && result.wc_rows)     || [];
            this.state.totalMos   = (result && result.total_mos)   || 0;
            this.state.totalPos   = (result && result.total_pos)   || 0;
            // Auto-navegar a la página que contiene la semana actual
            const cwIdx = this.state.weekKeys.indexOf(this.currentWeekKey);
            this.state.weekPage = cwIdx >= 0 ? Math.floor(cwIdx / 4) : 0;
            this._recompute();
        } catch (e) {
            console.error("[PurchaseAnalysis]", e);
            this.state.error = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Handlers de filtros ─────────────────────────────────────────────────

    onTagChange(ev) {
        const val = ev.target.value;
        this.state.tagIds = val ? [parseInt(val)] : [];
        this._loadWcs();
        this._loadData();
    }

    onWcChange(ev) {
        const val = ev.target.value;
        this.state.wcFilterId   = val ? parseInt(val) : null;
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
        this.state.activeMoWcId = null;
        this._recompute();
    }

    toggleShowFinished() {
        this.state.showFinished = !this.state.showFinished;
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
        this.state.activeMoWcId = null;
        this._recompute();
    }

    onSearchChange(ev) {
        this.state.searchText   = ev.target.value;
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
        this.state.activeMoWcId = null;
        this._recompute();
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value || firstOfMonth();
        this._loadData();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value || lastOfMonth();
        this._loadData();
    }

    // ── Selección de OF para ver detalle OCs ────────────────────────────────

    selectMo(mo, wcId) {
        if (this.state.activeMoId === mo.mo_id) {
            this.state.activeMoId   = null;
            this.state.activeMoData = null;
            this.state.activeMoWcId = null;
        } else {
            this.state.activeMoId   = mo.mo_id;
            this.state.activeMoData = mo;
            this.state.activeMoWcId = wcId ?? null;
        }
    }

    closeMoDetail() {
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
        this.state.activeMoWcId = null;
    }

    // ── Formateo y clases ───────────────────────────────────────────────────

    poStateClass(state) {
        return PO_STATE_CLASS[state] || "badge bg-secondary";
    }

    moStateClass(state) {
        return MO_STATE_CLASS[state] || "badge bg-secondary";
    }

    fmtDate(d) {
        if (!d) return "—";
        const [y, m, day] = d.split("-");
        return `${day}/${m}/${y}`;
    }

    fmtQty(n) {
        if (n === null || n === undefined) return "—";
        return Number(n).toLocaleString("es", { maximumFractionDigits: 2 });
    }

    fmtPct(n) {
        if (n === null || n === undefined) return "—";
        return Number(n).toFixed(1) + "%";
    }

    rowClass(po) {
        if (po.is_late) return "table-danger";
        if (po.state === "draft" || po.state === "sent") return "table-warning";
        if (po.pct_received >= 100) return "table-success";
        return "";
    }

    moTooltip(mo) {
        const lines = [];

        // Título de estado
        if (mo.has_late_pos)
            lines.push("⚠  Hay OCs vencidas sin recibir completamente");
        else if (mo.has_pending_pos)
            lines.push("⏳  Hay OCs pendientes de recepción");
        else if (!mo.pos_count)
            lines.push("—  Sin órdenes de compra en la cadena MTO");
        else
            lines.push("✓  Todos los materiales fueron recibidos");

        if (!mo.pos_count) return lines.join("\n");

        // Agrupar líneas por OC
        const byPo = {};
        for (const p of mo.pos) {
            if (!byPo[p.po_name]) byPo[p.po_name] = { items: [], hasLate: false };
            byPo[p.po_name].items.push(p);
            if (p.is_late) byPo[p.po_name].hasLate = true;
        }

        lines.push("");
        const MAX_POS = 6;
        let poCount = 0;
        for (const [poName, data] of Object.entries(byPo)) {
            if (poCount >= MAX_POS) { lines.push(`   … y ${Object.keys(byPo).length - MAX_POS} OC(s) más`); break; }
            lines.push(`📄 ${poName}${data.hasLate ? "  ⚠" : ""}`);
            for (const p of data.items) {
                const icon = p.pct_received >= 100 ? "✓" : p.is_late ? "⚠" : "·";
                lines.push(`   ${icon}  ${p.product}  →  ${this.fmtQty(p.qty_ordered)} ped / ${this.fmtQty(p.qty_received)} rec  (${this.fmtPct(p.pct_received)})`);
            }
            poCount++;
        }

        // Resumen final
        const nLate     = mo.pos.filter(p => p.is_late).length;
        const nComplete = mo.pos.filter(p => p.pct_received >= 100).length;
        const nPending  = mo.pos_count - nLate - nComplete;
        const parts = [];
        if (nComplete) parts.push(`${nComplete} completa${nComplete !== 1 ? "s" : ""}`);
        if (nPending)  parts.push(`${nPending} pendiente${nPending !== 1 ? "s" : ""}`);
        if (nLate)     parts.push(`${nLate} atrasada${nLate !== 1 ? "s" : ""}`);
        lines.push("");
        lines.push(`${mo.pos_count} línea${mo.pos_count !== 1 ? "s" : ""}  ·  ${parts.join("  ·  ")}`);

        return lines.join("\n");
    }

    moAlertClass(mo) {
        if (mo.has_late_pos)    return "text-danger";
        if (mo.has_pending_pos) return "text-warning";
        if (!mo.pos_count)      return "text-muted";
        return "text-success";
    }

    moAlertIcon(mo) {
        if (mo.has_late_pos)    return "fa-exclamation-circle";
        if (mo.has_pending_pos) return "fa-clock-o";
        if (!mo.pos_count)      return "fa-minus";
        return "fa-check-circle";
    }

    // ── OCs únicas (una fila por OC, no por línea) para lista inline ────────

    uniquePos(mo) {
        const seen = new Set();
        return (mo.pos || []).filter(p => {
            if (seen.has(p.po_id)) return false;
            seen.add(p.po_id);
            return true;
        });
    }

    // ── Agrupación de backorders por nombre madre ───────────────────────────

    _groupedCell(mos, wcId, wk) {
        // 1. Deduplicar por mo_id (varias OTs del mismo MO → un chip)
        const seenId = new Set();
        const unique = (mos || []).filter(mo => {
            if (seenId.has(mo.mo_id)) return false;
            seenId.add(mo.mo_id);
            return true;
        });

        // 2. Agrupar por nombre base (elimina sufijo -NN de backorders)
        const groupMap = new Map();
        for (const mo of unique) {
            const base = mo.mo_name.replace(/-\d+$/, '');
            if (!groupMap.has(base)) groupMap.set(base, []);
            groupMap.get(base).push(mo);
        }

        // 3. Construir objetos de grupo con clave única por celda
        return Array.from(groupMap.entries()).map(([baseName, members]) => {
            // Contar PO IDs únicos entre todos los miembros (evita inflar el conteo
            // cuando las OCs se propagan a todos los backorders de la familia)
            const uniquePoIds = new Set(members.flatMap(m => (m.pos || []).map(p => p.po_id)));
            return {
                key:           `${wcId}|${wk}|${baseName}`,
                baseName,
                mos:           members,
                isGroup:       members.length > 1,
                hasLatePos:    members.some(m => m.has_late_pos),
                hasPendingPos: members.some(m => !m.has_late_pos && m.has_pending_pos),
                posCount:      uniquePoIds.size,
                totalQty:      members.reduce((s, m) => s + (m.qty || 0), 0),
                uom:           members[0].uom,
            };
        });
    }

    toggleGroup(key) {
        this.state.expandedGroups[key] = !this.state.expandedGroups[key];
    }

    // ── Cómputo reactivo de filas filtradas y KPIs ──────────────────────────
    // Llamar explícitamente cuando cambian datos o filtros; evita recalcular
    // en cada ciclo de render de OWL.

    _recompute() {
        const rows = this._computeFilteredRows();
        this.state.filteredRows = rows;

        const seen = new Set();
        const mos  = [];
        for (const row of rows) {
            for (const wk of this.state.weekKeys) {
                for (const mo of (row.cells[wk] || [])) {
                    if (!seen.has(mo.mo_id)) { seen.add(mo.mo_id); mos.push(mo); }
                }
            }
        }
        const active = mos.filter(m => m.state !== 'done' && m.state !== 'cancel');
        this.state.kpi = {
            late:      mos.filter(m => m.has_late_pos),
            pending:   mos.filter(m => !m.has_late_pos && m.has_pending_pos),
            toApprove: mos.filter(m => m.has_to_approve_pos && !m.has_late_pos),
            noPos:     active.filter(m => m.pos_count === 0),
            ok:        mos.filter(m => m.pos_count > 0 && !m.has_late_pos && !m.has_pending_pos),
        };
    }

    openKpiMos(mos, label) {
        if (!mos.length) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: label || 'Órdenes de Fabricación',
            res_model: 'mrp.production',
            domain: [['id', 'in', mos.map(m => m.mo_id)]],
            views: [[false, 'list'], [false, 'form']],
            target: 'current',
        });
    }

    // ── Filas visibles (con filtro CT aplicado) ─────────────────────────────

    _computeFilteredRows() {
        let rows = this.state.wcFilterId
            ? this.state.wcRows.filter(r => r.wc_id === this.state.wcFilterId)
            : this.state.wcRows;

        const search       = (this.state.searchText || "").trim().toLowerCase();
        const showFinished = this.state.showFinished;

        if (!search && showFinished) return rows;

        const result = [];
        for (const row of rows) {
            const cells = {};
            let hasVisible = false;
            for (const wk of this.state.weekKeys) {
                let mos = row.cells[wk] || [];
                if (!showFinished) {
                    mos = mos.filter(mo => mo.state !== "done");
                }
                if (search) {
                    mos = mos.filter(mo =>
                        (mo.product_name || "").toLowerCase().includes(search)
                    );
                }
                cells[wk] = mos;
                if (mos.length) hasVisible = true;
            }
            if (hasVisible) {
                result.push({ wc_id: row.wc_id, wc_name: row.wc_name, cells });
            }
        }
        return result;
    }

    // ── Exportar a PDF (estilo reporte Odoo con datos de empresa) ──────

    exportToPdf() {
        const rows       = this.state.filteredRows;
        const weekKeys   = this.state.weekKeys;
        const weekLabels = this.state.weekLabels;
        const co         = this._company || {};

        // ── Colores de empresa ──────────────────────────────────────────
        const primary = (co.primary_color && /^#[0-9a-f]{6}$/i.test(co.primary_color))
            ? co.primary_color : "#875a7b";
        const rgb = primary.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
        const [pr, pg, pb] = rgb
            ? [parseInt(rgb[1], 16), parseInt(rgb[2], 16), parseInt(rgb[3], 16)]
            : [135, 90, 123];
        const rgba08  = `rgba(${pr},${pg},${pb},0.08)`;
        const rgba18  = `rgba(${pr},${pg},${pb},0.18)`;
        const rgba35  = `rgba(${pr},${pg},${pb},0.35)`;

        // ── Escape HTML para evitar rotura con nombres especiales ──────
        const esc = s => String(s ?? "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

        // ── Datos de empresa (con escape) ───────────────────────────────
        const logoSrc  = co.logo ? `data:image/png;base64,${co.logo}` : "";
        const coName   = esc(co.name   || "");
        const coAddr   = esc([co.street, [co.zip, co.city].filter(Boolean).join(" ")].filter(Boolean).join(", "));
        const coContact= "";

        // ── Textos del documento ────────────────────────────────────────
        const now = new Date().toLocaleDateString("es-AR", { day: "2-digit", month: "long", year: "numeric" });
        const sectorLabel = this.state.tags.find(t => t.id === this.state.tagIds[0])?.name || "";
        const dateFrom    = this.fmtDate(this.state.dateFrom);
        const dateTo      = this.fmtDate(this.state.dateTo);
        const totalMos    = rows.reduce((acc, r) =>
            acc + weekKeys.reduce((a, wk) => a + (r.cells[wk]?.length || 0), 0), 0);

        // Rango de semanas para el encabezado del PDF
        const firstWkLabel = weekKeys.length ? weekLabels[weekKeys[0]] : null;
        const lastWkLabel  = weekKeys.length ? weekLabels[weekKeys[weekKeys.length - 1]] : null;
        const weekRangeStr = firstWkLabel && lastWkLabel
            ? (firstWkLabel === lastWkLabel
                ? `${esc(firstWkLabel.label)} ${esc(String(firstWkLabel.year))}`
                : `${esc(firstWkLabel.label)} – ${esc(lastWkLabel.label)} · ${esc(String(lastWkLabel.year))}`)
            : "";

        // ── Colores semánticos de OF ────────────────────────────────────
        const MO_COLORS = {
            draft: "#6c757d", confirmed: "#0dcaf0", progress: "#0d6efd",
            to_close: "#ffc107", done: "#198754", cancel: "#dc3545",
        };
        const chipAlert = mo => {
            if (mo.has_late_pos)    return "#dc3545";
            if (mo.has_pending_pos) return "#fd7e14";
            if (!mo.pos_count)      return "#adb5bd";
            return "#198754";
        };

        // ── Cabecera de la tabla ────────────────────────────────────────
        let thead = `<tr><th class="th-wc">CT</th>`;
        for (const wk of weekKeys) {
            const lbl = weekLabels[wk];
            thead += `<th class="th-week">${esc(lbl.label)} <span style="font-weight:400">${esc(lbl.year)}</span>` +
                     `<span class="th-dates">${esc(lbl.date_from)} – ${esc(lbl.date_to)}</span></th>`;
        }
        thead += `</tr>`;

        // ── Filas de la tabla ───────────────────────────────────────────
        let tbody = "";
        for (const row of rows) {
            tbody += `<tr><td class="wc-cell">${esc(row.wc_name)}</td>`;
            for (const wk of weekKeys) {
                const mos = row.cells[wk] || [];
                tbody += `<td class="mo-cell">`;
                for (const mo of mos) {
                    const stColor = MO_COLORS[mo.state] || "#6c757d";
                    const alColor = chipAlert(mo);
                    tbody +=
                        `<div class="chip">` +
                        `<div><span class="chip-dot" style="background:${alColor}"></span>` +
                        `<span class="chip-name">${esc(mo.mo_name)}</span></div>` +
                        `<div class="chip-product">${esc(mo.product_name)}</div>` +
                        `<div class="chip-meta">` +
                        `<span class="badge" style="background:${stColor}">${esc(mo.state_label)}</span> ` +
                        `${esc(this.fmtQty(mo.qty))} ${esc(mo.uom)} &middot; ${mo.pos_count} OC(s)` +
                        `</div></div>`;
                }
                tbody += `</td>`;
            }
            tbody += `</tr>`;
        }

        // ── HTML del documento ──────────────────────────────────────────
        const html = `<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Análisis de Compras – ${sectorLabel}</title>
<style>
  /* ── Estilos generales ── */
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 9.5px; color: #212529; background: #fff;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }

  /* ── Banda superior de color ── */
  .rpt-band      { background: ${primary}; height: 5px; }
  .rpt-band-sm   { height: 3px; }

  /* ── Cabecera: logo izq + empresa der ── */
  .rpt-header { overflow: hidden; padding: 12px 20px 10px; border-bottom: 1px solid #e9ecef; }
  .rpt-logo-wrap { float: left; }
  .rpt-logo   { max-height: 56px; max-width: 180px; display: block; object-fit: contain; }
  .rpt-co     { float: right; text-align: right; font-size: 8.5px; color: #6c757d; line-height: 1.55; }
  .rpt-co-name{ display: block; font-size: 11px; font-weight: 700; color: #212529; margin-bottom: 1px; }

  /* ── Fila de título ── */
  .rpt-title-row { overflow: hidden; padding: 9px 20px 8px; border-bottom: 1px solid #e9ecef; }
  .rpt-title-wrap { float: left; }
  .rpt-title  { display: block; font-size: 15px; font-weight: 700; color: ${primary}; line-height: 1.2; }
  .rpt-weeks  { display: block; font-size: 11.5px; font-weight: 600; color: #343a40; margin-top: 3px; letter-spacing: 0.01em; }
  .rpt-date   { float: right; font-size: 8.5px; color: #6c757d; line-height: 15px; }
  .rpt-meta   { clear: both; margin-top: 4px; }
  .rpt-chip   {
    display: inline-block; font-size: 8px; font-weight: 600;
    color: ${primary}; background: ${rgba08};
    border: 1px solid ${rgba18}; border-radius: 3px;
    padding: 1px 7px; margin-right: 5px;
  }

  /* ── Tabla ── */
  .rpt-table-wrap { padding: 10px 0 0; }
  table { border-collapse: collapse; width: 100%; table-layout: fixed; }
  th, td { border: 1px solid #dee2e6; padding: 4px 5px; vertical-align: top; }

  /* Columna CT */
  .th-wc  {
    width: 120px; background: ${primary}; color: #fff;
    font-size: 8.5px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; vertical-align: middle; text-align: center;
  }
  /* Columnas de semana */
  .th-week {
    background: ${rgba08}; color: ${primary};
    font-size: 8.5px; font-weight: 700; text-align: center;
    text-transform: uppercase; letter-spacing: 0.03em;
  }
  .th-dates { display: block; font-size: 7px; font-weight: 400; color: #6c757d; margin-top: 1px; }

  /* Celda CT */
  .wc-cell {
    background: ${rgba08}; font-weight: 600; color: ${primary};
    font-size: 9px; vertical-align: middle; text-align: center;
    border-right: 2px solid ${rgba35} !important;
    word-break: break-word;
  }
  /* Celda de OFs */
  .mo-cell { background: #fff; }

  /* ── Chips de OF ── */
  .chip {
    border: 1px solid #e9ecef; border-radius: 3px; padding: 3px 4px;
    margin-bottom: 3px; background: #fff;
  }
  .chip:last-child { margin-bottom: 0; }
  .chip-dot     { display: inline-block; width: 6px; height: 6px; border-radius: 50%; vertical-align: middle; margin-right: 3px; }
  .chip-name    { font-weight: 700; font-size: 9px; color: #212529; }
  .chip-product { font-size: 8px; color: #6c757d; margin: 1px 0 2px; }
  .chip-meta    { font-size: 8px; color: #495057; }
  .badge        { display: inline-block; padding: 1px 4px; border-radius: 2px; color: #fff; font-size: 7.5px; font-weight: 600; vertical-align: middle; }

  /* ── Footer ── */
  .rpt-footer {
    overflow: hidden; margin-top: 12px;
    border-top: 1px solid #e9ecef; padding: 6px 20px 4px;
    font-size: 8px; color: #adb5bd;
  }
  .rpt-footer-left  { float: left; }
  .rpt-footer-right { float: right; }

  /* ── Reglas de impresión ── */
  @media print {
    @page {
      size: A4 landscape;
      margin: 1.4cm 1.2cm 1.2cm 1.2cm;
    }
    body { font-size: 8.5px; }
    .chip { page-break-inside: avoid; break-inside: avoid; }
    tr   { page-break-inside: avoid; break-inside: avoid; }
    thead { display: table-header-group; }
    .rpt-band-sm { display: none; }
  }
</style>
</head><body>

<div class="rpt-band"></div>

<div class="rpt-header">
  <div class="rpt-logo-wrap">
    ${logoSrc
        ? `<img class="rpt-logo" src="${logoSrc}" onerror="this.style.display='none'" alt="${coName}">`
        : `<span style="font-size:13px;font-weight:700;color:${primary};">${coName}</span>`}
  </div>
  <div class="rpt-co">
    ${coName    ? `<span class="rpt-co-name">${coName}</span>` : ""}
    ${coAddr    ? `<span>${coAddr}</span><br>` : ""}
    ${coContact ? `<span>${coContact}</span>` : ""}
  </div>
</div>

<div class="rpt-title-row">
  <div class="rpt-title-wrap">
    <span class="rpt-title">Análisis de compras productivas</span>
    ${weekRangeStr ? `<span class="rpt-weeks">Semanas ${weekRangeStr}</span>` : ""}
  </div>
  <span class="rpt-date">${now}</span>
  <div class="rpt-meta">
    ${sectorLabel ? `<span class="rpt-chip">Sector: ${esc(sectorLabel)}</span>` : ""}
    <span class="rpt-chip">${esc(dateFrom)} – ${esc(dateTo)}</span>
    <span class="rpt-chip">${totalMos} OFs &middot; ${rows.length} CT(s)</span>
  </div>
</div>

<div class="rpt-table-wrap">
  <table>
    <thead>${thead}</thead>
    <tbody>${tbody}</tbody>
  </table>
</div>

<div class="rpt-footer">
  <span class="rpt-footer-left">${coName ? coName + " — " : ""}Planificador de Producción</span>
  <span class="rpt-footer-right">Impreso el ${now}</span>
</div>
<div class="rpt-band rpt-band-sm"></div>

</body></html>`;

        const win = window.open("", "_blank");
        win.document.write(html);
        win.document.close();
        win.focus();
        win.print();
    }

    // ── Paginación de semanas (máx. 4 por página) ──────────────────────

    get visibleWeekKeys() {
        const page = this.state.weekPage;
        return this.state.weekKeys.slice(page * 4, (page + 1) * 4);
    }

    get weekPageCount() {
        return Math.max(1, Math.ceil(this.state.weekKeys.length / 4));
    }

    prevPage() {
        if (this.state.weekPage > 0) {
            this.state.weekPage    -= 1;
            this.state.activeMoId   = null;
            this.state.activeMoData = null;
            this.state.activeMoWcId = null;
        }
    }

    nextPage() {
        if (this.state.weekPage < this.weekPageCount - 1) {
            this.state.weekPage    += 1;
            this.state.activeMoId   = null;
            this.state.activeMoData = null;
            this.state.activeMoWcId = null;
        }
    }

    // ── Abrir lista de OCs por aprobar ──────────────────────────────────

    openToApprovePOs() {
        const mos = this.state.kpi.toApprove;
        const poIds = new Set();
        for (const mo of mos) {
            for (const po of (mo.pos || [])) {
                if (po.state === 'to approve') poIds.add(po.po_id);
            }
        }
        if (!poIds.size) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'OCs por aprobar',
            res_model: 'purchase.order',
            domain: [['id', 'in', Array.from(poIds)]],
            views: [[false, 'list'], [false, 'form']],
            target: 'current',
        });
    }

    // ── Semana actual ───────────────────────────────────────────────────

    get currentWeekKey() {
        const d = new Date();
        const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
        const dayNum = utc.getUTCDay() || 7;
        utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
        const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
        const weekNo = Math.ceil((((utc - yearStart) / 86400000) + 1) / 7);
        return `${utc.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
    }

    // ── Navegación ──────────────────────────────────────────────────────────

    openMo(mo) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `OF ${mo.mo_name}`,
            res_model: "mrp.production",
            res_id: mo.mo_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPo(po) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `OC ${po.po_name}`,
            res_model: "purchase.order",
            res_id: po.po_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("view_widgets").add("purchase_analysis_widget", {
    component: PurchaseAnalysisWidget,
});
