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
    draft:    "badge bg-secondary",
    sent:     "badge bg-warning text-dark",
    purchase: "badge bg-primary",
    done:     "badge bg-success",
    cancel:   "badge bg-danger",
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
        this.orm    = useService("orm");
        this.action = useService("action");

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
        });

        onMounted(async () => {
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
    }

    toggleShowFinished() {
        this.state.showFinished = !this.state.showFinished;
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
    }

    onSearchChange(ev) {
        this.state.searchText   = ev.target.value;
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
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

    selectMo(mo) {
        if (this.state.activeMoId === mo.mo_id) {
            this.state.activeMoId   = null;
            this.state.activeMoData = null;
        } else {
            this.state.activeMoId   = mo.mo_id;
            this.state.activeMoData = mo;
        }
    }

    closeMoDetail() {
        this.state.activeMoId   = null;
        this.state.activeMoData = null;
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

    // ── Filas visibles (con filtro CT aplicado) ─────────────────────────────

    filteredWcRows() {
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
