/**
 * inventory_dashboard_widget.js (odoo_mrp_planner_dispatch)
 *
 * Widget del Panel de Inventario. Dos zonas con barras de filtros
 * independientes (misma estructura que el panel de ventas):
 *   - Zona superior: KPIs de despacho + gráficos (evolución mensual de la
 *     tasa física s/ disponible y composición del pendiente por depósito).
 *     RPC: get_inventory_dashboard_data(periodFrom, periodTo, warehouseIds).
 *   - Zona inferior: tabla operativa de salidas pendientes con selección y
 *     "Marcar despachado" masivo.
 *     RPC: get_inventory_pending_table(dateFrom, dateTo, warehouseIds, search).
 *
 * Reutiliza los formateadores del módulo base (números es-AR, tasas con un
 * decimal y semáforo) para mantener la estética de los demás paneles.
 */

/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { fmt, fmtPct, svcClass, sortIcon } from "@odoo_mrp_planner/js/forecast_formatters";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function firstOfMonth() { const d = new Date(); return toDateStr(new Date(d.getFullYear(), d.getMonth(), 1)); }
function lastOfMonth()  { const d = new Date(); return toDateStr(new Date(d.getFullYear(), d.getMonth() + 1, 0)); }

const TABLE_COLS = [
    { key: "name",           label: "Remito" },
    { key: "partner",        label: "Cliente" },
    { key: "origin",         label: "Origen" },
    { key: "warehouse",      label: "Depósito" },
    { key: "scheduled",      label: "Fecha prog." },
    { key: "product_names",  label: "Artículos" },
    { key: "qty_pending",    label: "Pendiente" },
    { key: "qty_available",  label: "Con stock" },
    { key: "days_available", label: "Días disp." },
    { key: "state",          label: "Estado" },
];

const STATE_LABELS = {
    confirmed: "En espera",
    waiting:   "Esperando otra op.",
    assigned:  "Preparado",
};

class InventoryDashboardWidget extends Component {
    static template = "odoo_mrp_planner_dispatch.InventoryDashboardWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.notification = useService("notification");
        this.trendRef     = useRef("trendCanvas");
        this.pendingRef   = useRef("pendingCanvas");
        this.trendChart   = null;
        this.pendingChart = null;
        this.tableCols    = TABLE_COLS;

        this.state = useState({
            // ── Zona gráficos ──
            chartFrom:      firstOfMonth(),
            chartTo:        lastOfMonth(),
            chartWhIds:     [],
            whDropdownOpen: false,
            warehouses:     [],
            data:           null,
            chartLoading:   true,
            chartError:     null,
            // ── Zona tabla ──
            tblFrom:        "",
            tblTo:          "",
            tblSearch:      "",
            tblWhIds:       [],
            tblWhDropdownOpen: false,
            colsDropdownOpen:  false,
            visibleCols: {
                name: true, partner: true, origin: true, warehouse: false,
                scheduled: true, product_names: true, qty_pending: true,
                qty_available: true, days_available: true, state: true,
            },
            rows:           [],
            canDispatch:    false,
            tableLoading:   true,
            tableError:     null,
            selected:       {},
            sortCol:        "scheduled",
            sortDir:        "asc",
            dispatching:    false,
        });

        this._closeAll = () => {
            this.state.whDropdownOpen    = false;
            this.state.tblWhDropdownOpen = false;
            this.state.colsDropdownOpen  = false;
        };
        this._tblDebounceTimer = null;

        onMounted(async () => {
            document.addEventListener("click", this._closeAll);
            await loadBundle("web.chartjs_lib");
            // Los depósitos, los gráficos y la tabla son RPCs independientes
            await Promise.all([this._loadWarehouses(), this._loadCharts(), this._loadTable()]);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", this._closeAll);
            clearTimeout(this._tblDebounceTimer);
            this._destroyCharts();
        });
    }

    // ── Formateadores compartidos ─────────────────────────────────────────────
    fmt(n)     { return fmt(n); }
    fmtPct(n)  { return fmtPct(n); }
    svcClass(n){ return svcClass(n); }
    sortIcon(col) { return sortIcon(col, this.state.sortCol, this.state.sortDir); }
    stateLabel(s) { return STATE_LABELS[s] || s; }

    // ── Zona gráficos ─────────────────────────────────────────────────────────

    async _loadWarehouses() {
        try {
            this.state.warehouses = await this.orm.call(
                "mrp.planner.dashboard", "get_warehouses_for_forecast", []);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[InventoryPanel]", e);
        }
    }

    async _loadCharts() {
        this.state.chartLoading = true;
        this.state.chartError   = null;
        try {
            this.state.data = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_dashboard_data",
                [this.state.chartFrom, this.state.chartTo, this.state.chartWhIds]);
            this._renderCharts();
        } catch (e) {
            console.error("[InventoryPanel]", e);
            this.state.chartError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.chartLoading = false;
        }
    }

    onChartFromChange(ev) { this.state.chartFrom = ev.target.value; this._loadCharts(); }
    onChartToChange(ev)   { this.state.chartTo   = ev.target.value; this._loadCharts(); }
    setCurrentMonth() {
        this.state.chartFrom = firstOfMonth();
        this.state.chartTo   = lastOfMonth();
        this._loadCharts();
    }
    toggleWhDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.whDropdownOpen;
        this._closeAll();
        this.state.whDropdownOpen = open;
    }
    toggleWarehouse(whId) {
        const ids = this.state.chartWhIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._loadCharts();
    }
    get whFilterLabel() {
        const n = this.state.chartWhIds.length;
        if (!n) return "Todos los depósitos";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.chartWhIds[0]);
            return wh ? wh.name : "1 depósito";
        }
        return `${n} depósitos`;
    }

    _destroyCharts() {
        if (this.trendChart)   { this.trendChart.destroy();   this.trendChart = null; }
        if (this.pendingChart) { this.pendingChart.destroy(); this.pendingChart = null; }
    }

    _renderCharts() {
        this._destroyCharts();
        const d = this.state.data;
        if (!d || typeof Chart === "undefined") return;

        // ── Evolución mensual de la tasa s/ disponible ──
        if (this.trendRef.el && d.trend && d.trend.length) {
            const labels = d.trend.map(m => {
                const [y, mo] = m.ym.split("-");
                return new Date(+y, +mo - 1, 1).toLocaleString("es", { month: "short", year: "2-digit" });
            });
            this.trendChart = new Chart(this.trendRef.el, {
                type: "line",
                data: {
                    labels,
                    datasets: [{
                        label: "Tasa física s/ disponible",
                        data: d.trend.map(m => m.rate),
                        borderColor: "#0d6efd",
                        backgroundColor: "rgba(13,110,253,0.10)",
                        fill: true,
                        spanGaps: true,
                        tension: 0.25,
                        pointRadius: 4,
                        // Meses en vivo (sin consolidar) con punto vacío
                        pointBackgroundColor: d.trend.map(
                            m => m.source === "monthly" ? "#0d6efd" : "#ffffff"),
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => {
                                    const m = d.trend[ctx.dataIndex];
                                    const src = m.source === "monthly" ? "consolidado" : "en vivo";
                                    return m.rate === null
                                        ? "Sin datos"
                                        : `${m.rate}% (${src}) — desp. ${fmt(m.num)} / disp. no desp. ${fmt(m.den_extra)}`;
                                },
                            },
                        },
                    },
                },
            });
        }

        // ── Composición del pendiente por depósito ──
        if (this.pendingRef.el && d.pending_by_wh && d.pending_by_wh.length) {
            this.pendingChart = new Chart(this.pendingRef.el, {
                type: "bar",
                data: {
                    labels: d.pending_by_wh.map(w => w.warehouse),
                    datasets: [
                        {
                            label: "Con stock",
                            data: d.pending_by_wh.map(w => w.available),
                            backgroundColor: "rgba(13,202,240,0.75)",
                        },
                        {
                            label: "Sin stock",
                            data: d.pending_by_wh.map(w => w.blocked),
                            backgroundColor: "rgba(220,53,69,0.65)",
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { x: { stacked: true }, y: { stacked: true } },
                    plugins: { legend: { position: "bottom" } },
                },
            });
        }
    }

    // ── Tooltips de KPIs ──────────────────────────────────────────────────────

    kpiTooltip(key) {
        const k = (this.state.data && this.state.data.kpis) || {};
        switch (key) {
            case "pending":
                return `Cantidad pendiente en salidas sin validar (estado actual)\n${k.pending_pickings || 0} remito(s) pendiente(s)`;
            case "available":
                return "Del pendiente actual, cantidad con stock reservado: podría despacharse hoy. Clic para ver los remitos preparados.";
            case "blocked":
                return "Del pendiente actual, cantidad sin stock reservado: frenada por falta de disponibilidad. Clic para ver los remitos en espera.";
            case "dispatched":
                return `Cantidad de remitos marcados como despachados en el período (por fecha de despacho)\n${k.dispatched_pickings || 0} remito(s)`;
            case "rate":
                return `Despachado ÷ (despachado + lo que estuvo disponible y no salió)\n→ ${fmt(k.rate_available_num)} ÷ ${fmt(k.rate_available_den)} = ${fmtPct(k.rate_available)}\nMeses cerrados desde el consolidado; mes en curso desde los snapshots diarios.`;
            case "lag":
                return "Días promedio entre la validación del remito y su despacho, para los despachos del período.";
            default:
                return "";
        }
    }

    // ── Drills ────────────────────────────────────────────────────────────────

    async openPending(mode) {
        const act = await this.orm.call("mrp.planner.dashboard", "action_inventory_pending",
            [mode, this.state.chartWhIds]);
        this.action.doAction(act);
    }
    async openDispatched() {
        const act = await this.orm.call("mrp.planner.dashboard", "action_inventory_dispatched",
            [this.state.chartFrom, this.state.chartTo, this.state.chartWhIds]);
        this.action.doAction(act);
    }
    openPicking(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: row.picking_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ── Zona tabla ────────────────────────────────────────────────────────────

    async _loadTable() {
        this.state.tableLoading = true;
        this.state.tableError   = null;
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_pending_table",
                [this.state.tblFrom || null, this.state.tblTo || null,
                 this.state.tblWhIds, this.state.tblSearch]);
            this.state.rows        = res.rows || [];
            this.state.canDispatch = !!res.can_dispatch;
            this.state.selected    = {};
        } catch (e) {
            console.error("[InventoryPanel]", e);
            this.state.tableError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.tableLoading = false;
        }
    }

    _loadTableDebounced() {
        clearTimeout(this._tblDebounceTimer);
        this._tblDebounceTimer = setTimeout(() => this._loadTable(), 400);
    }

    onTblFromChange(ev)   { this.state.tblFrom   = ev.target.value; this._loadTable(); }
    onTblToChange(ev)     { this.state.tblTo     = ev.target.value; this._loadTable(); }
    onTblSearchInput(ev)  { this.state.tblSearch = ev.target.value; this._loadTableDebounced(); }
    toggleTblWhDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.tblWhDropdownOpen;
        this._closeAll();
        this.state.tblWhDropdownOpen = open;
    }
    toggleTblWarehouse(whId) {
        const ids = this.state.tblWhIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._loadTable();
    }
    get tblWhFilterLabel() {
        const n = this.state.tblWhIds.length;
        if (!n) return "Todos los depósitos";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.tblWhIds[0]);
            return wh ? wh.name : "1 depósito";
        }
        return `${n} depósitos`;
    }
    toggleColsDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.colsDropdownOpen;
        this._closeAll();
        this.state.colsDropdownOpen = open;
    }
    toggleCol(key) { this.state.visibleCols[key] = !this.state.visibleCols[key]; }
    get visibleColsList() { return TABLE_COLS.filter(c => this.state.visibleCols[c.key]); }

    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortCol = col;
            this.state.sortDir = "asc";
        }
    }

    get sortedRows() {
        const { sortCol, sortDir } = this.state;
        const dir = sortDir === "asc" ? 1 : -1;
        return [...this.state.rows].sort((a, b) => {
            const va = a[sortCol], vb = b[sortCol];
            if (va === null || va === undefined) return 1;
            if (vb === null || vb === undefined) return -1;
            if (typeof va === "number") return (va - vb) * dir;
            return String(va).localeCompare(String(vb), "es") * dir;
        });
    }

    // ── Selección + despacho masivo ───────────────────────────────────────────

    toggleSelect(row) {
        // Solo tiene sentido seleccionar lo preparado (despachable)
        if (row.state !== "assigned") return;
        this.state.selected[row.picking_id] = !this.state.selected[row.picking_id];
    }
    get selectedIds() {
        return Object.keys(this.state.selected).filter(k => this.state.selected[k]).map(Number);
    }
    get selectableRows() { return this.sortedRows.filter(r => r.state === "assigned"); }
    get allSelected() {
        const sel = this.selectableRows;
        return sel.length > 0 && sel.every(r => this.state.selected[r.picking_id]);
    }
    toggleSelectAll() {
        const target = !this.allSelected;
        for (const r of this.selectableRows) {
            this.state.selected[r.picking_id] = target;
        }
    }

    async markDispatched() {
        const ids = this.selectedIds;
        if (!ids.length || this.state.dispatching) return;
        this.state.dispatching = true;
        try {
            await this.orm.call("stock.picking", "action_mark_dispatched", [ids]);
            this.notification.add(
                `${ids.length} remito(s) marcados como despachados.`, { type: "success" });
            await Promise.all([this._loadTable(), this._loadCharts()]);
        } catch (e) {
            console.error("[InventoryPanel]", e);
            this.notification.add(
                (e && e.data && e.data.message) || e.message || String(e), { type: "danger" });
        } finally {
            this.state.dispatching = false;
        }
    }

    // ── Export CSV ────────────────────────────────────────────────────────────

    exportCsv() {
        const cols = this.visibleColsList;
        const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
        const lines = [cols.map(c => esc(c.label)).join(";")];
        for (const r of this.sortedRows) {
            lines.push(cols.map(c => {
                if (c.key === "state") return esc(this.stateLabel(r.state));
                return esc(r[c.key]);
            }).join(";"));
        }
        const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `salidas_pendientes_${toDateStr(new Date())}.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
}

registry.category("view_widgets").add("inventory_dashboard_widget", {
    component: InventoryDashboardWidget,
});
