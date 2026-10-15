/** @odoo-module **/

/**
 * @widget CrmCustomerKpisWidget
 * @description Panel de indicadores del cliente dentro del formulario de la
 * oportunidad (crm.lead). Es un field widget sobre partner_id ("Contacto"):
 * al abrir la pestaña (o cambiar el contacto/período) pide los KPIs al backend
 * con un único RPC (get_crm_customer_kpis) que reúsa el Análisis de clientes
 * del Planificador — no recalcula nada.
 *
 * La UI replica el panel de detalle del Análisis de clientes, reorganizada en
 * cards fijas + sub-pestañas (Evolución / Mix / Pedidos / Artículos). Los
 * gráficos y el top de artículos se dibujan con las MISMAS funciones del módulo
 * base (importadas), para garantizar idénticos números y estética.
 */

import { Component, useState, useRef, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { drawPanelCharts, destroyPanelCharts, CHART_COLORS } from "@odoo_mrp_planner/js/customer_analysis_charts";
import {
    panelTopProducts, setPanelMetric, setPanelChartMode, setPanelTopN, sortPanelProds,
} from "@odoo_mrp_planner/js/customer_analysis_panel";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Período por defecto: últimos 12 meses. */
function defaultPeriod() {
    const now = new Date();
    const from = new Date(now);
    from.setMonth(from.getMonth() - 12);
    return { from: toDateStr(from), to: toDateStr(now) };
}

class CrmCustomerKpisWidget extends Component {
    static template = "odoo_mrp_planner_crm.CustomerKpisWidget";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        // Refs de canvas — nombres idénticos a los que espera drawPanelCharts().
        this.saleCatRef = useRef("panelSaleCatCanvas");
        this.donutRef = useRef("panelDonutCanvas");
        this.barRef = useRef("panelBarCanvas");
        this._saleCatChart = null;
        this._donutChart = null;
        this._barChart = null;
        this._lineChart = null;
        this._panelDonutsKey = "";
        this._panelChartKey = "";

        this._loadedKey = null;
        this._chartsReady = false;

        const period = defaultPeriod();
        this.state = useState({
            loading: false,
            error: null,
            dateFrom: period.from,
            dateTo: period.to,
            row: null,            // fila de KPIs del cliente (get_customer_analysis_data)
            panelData: null,      // detalle (get_customer_detail)
            config: {},
            activeTab: "evolucion",
            // Claves que esperan drawPanelCharts() y los helpers del panel base:
            panelPartnerId: null,
            panelMetric: "amount",      // 'amount' | 'qty'
            panelChartMode: "bar",       // 'bar' | 'line'
            panelTopN: 10,
            panelProdSort: "qty_pending",
            panelProdDir: "desc",
            // Orden de la tabla de pedidos (local):
            orderSort: "date",
            orderDir: "desc",
        });

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                this._chartsReady = true;
                // El dibujo de gráficos lo dispara onPatched (cuando el canvas ya
                // está en el DOM): llamarlo acá marcaría las claves de caché antes
                // de tiempo y el patch real saltearía el primer render.
                await this._maybeLoad();
            } catch (e) {
                if (e.message !== "Component is destroyed") {
                    throw e;
                }
            }
        });

        onPatched(() => {
            this._maybeLoad();
            this._redraw();
        });

        onWillUnmount(() => destroyPanelCharts(this));
    }

    // ── Carga ──────────────────────────────────────────────────────────────

    /** ID del cliente del campo Contacto (partner_id), o null.
     *  Tolera ambas representaciones del many2one en record.data:
     *  objeto {id, display_name} (Odoo 17/18) o par [id, name] (legacy). */
    get partnerId() {
        const v = this.props.record.data[this.props.name];
        if (!v) {
            return null;
        }
        if (Array.isArray(v)) {
            return v[0] || null;
        }
        return v.id || null;
    }

    /** Carga perezosa: solo cuando cambia cliente o período y no hay otra en curso. */
    async _maybeLoad() {
        const pid = this.partnerId;
        if (!pid) {
            this.state.row = null;
            this.state.panelData = null;
            this._loadedKey = null;
            return;
        }
        const key = `${pid}_${this.state.dateFrom}_${this.state.dateTo}`;
        if (key === this._loadedKey || this.state.loading) {
            return;
        }
        this._loadedKey = key;
        await this._load(pid);
    }

    async _load(pid) {
        this.state.loading = true;
        this.state.error = null;
        destroyPanelCharts(this);
        this._panelDonutsKey = "";
        this._panelChartKey = "";
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard",
                "get_crm_customer_kpis",
                [pid, this.state.dateFrom, this.state.dateTo]
            );
            this.state.row = res.row || null;
            this.state.panelData = res.detail || null;
            this.state.config = res.config || {};
            this.state.panelPartnerId = pid;    // clave de caché de drawPanelCharts
        } catch (e) {
            console.error("[CrmCustomerKpis]", e);
            this.state.error = e?.data?.message || e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    _reload() {
        const pid = this.partnerId;
        if (!pid) {
            return;
        }
        this._loadedKey = `${pid}_${this.state.dateFrom}_${this.state.dateTo}`;
        this._load(pid);
    }

    /** Redibuja los gráficos del panel cuando la sub-pestaña activa los contiene. */
    _redraw() {
        if (!this._chartsReady || !this.state.panelData || this.state.loading) {
            return;
        }
        if (this.state.activeTab === "evolucion" || this.state.activeTab === "mix") {
            drawPanelCharts(this);
        }
    }

    // ── Controles ────────────────────────────────────────────────────────────

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom > this.state.dateTo) {
            this.state.dateTo = this.state.dateFrom;
        }
        this._reload();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateTo < this.state.dateFrom) {
            this.state.dateFrom = this.state.dateTo;
        }
        this._reload();
    }

    setPreset(kind) {
        const now = new Date();
        if (kind === "12m") {
            const from = new Date(now);
            from.setMonth(from.getMonth() - 12);
            this.state.dateFrom = toDateStr(from);
            this.state.dateTo = toDateStr(now);
        } else if (kind === "ytd") {
            this.state.dateFrom = toDateStr(new Date(now.getFullYear(), 0, 1));
            this.state.dateTo = toDateStr(now);
        }
        this._reload();
    }

    get isPreset12m() {
        const now = new Date();
        const from = new Date(now);
        from.setMonth(from.getMonth() - 12);
        return this.state.dateFrom === toDateStr(from) && this.state.dateTo === toDateStr(now);
    }

    get isPresetYtd() {
        const now = new Date();
        return this.state.dateFrom === toDateStr(new Date(now.getFullYear(), 0, 1))
            && this.state.dateTo === toDateStr(now);
    }

    setTab(tab) {
        if (this.state.activeTab === tab) {
            return;
        }
        this.state.activeTab = tab;
        // Forzar redibujo de los canvases de la pestaña recién mostrada.
        this._panelDonutsKey = "";
        this._panelChartKey = "";
    }

    // ── Delegados a los helpers del panel base ────────────────────────────────

    setPanelMetric(m) { setPanelMetric(this, m); }
    setPanelChartMode(mode) { setPanelChartMode(this, mode); }
    setPanelTopN(n) { setPanelTopN(this, n); }
    sortPanelProds(key) { sortPanelProds(this, key); }
    get panelTopProducts() { return panelTopProducts(this); }

    // ── Pedidos (orden local) ────────────────────────────────────────────────

    sortOrders(key) {
        if (this.state.orderSort === key) {
            this.state.orderDir = this.state.orderDir === "desc" ? "asc" : "desc";
        } else {
            this.state.orderSort = key;
            this.state.orderDir = "desc";
        }
    }

    get sortedOrders() {
        const orders = (this.state.panelData && this.state.panelData.orders) || [];
        const key = this.state.orderSort;
        const dir = this.state.orderDir === "desc" ? -1 : 1;
        return [...orders].sort((a, b) => {
            const va = a[key] ?? -Infinity;
            const vb = b[key] ?? -Infinity;
            if (typeof va === "string") {
                return dir * va.localeCompare(vb, "es", { sensitivity: "base" });
            }
            return dir * (va - vb);
        });
    }

    // ── Drill-down (cards "Ver →") ────────────────────────────────────────────

    get _partnerIds() {
        return (this.state.row && this.state.row.partner_ids) || [this.partnerId];
    }

    get _periodDomain() {
        return [
            ["date_order", ">=", this.state.dateFrom + " 00:00:00"],
            ["date_order", "<=", this.state.dateTo + " 23:59:59"],
        ];
    }

    openOrder(orderId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openProduct(tmplId) {
        if (!tmplId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.template",
            res_id: tmplId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCustomerOrders() {
        const partnerIds = this._partnerIds;
        const domain = [["state", "in", ["sale", "done"]], ...this._periodDomain];
        const context = {};
        if (partnerIds.length === 1) {
            context.search_default_partner_id = partnerIds[0];
        } else {
            domain.unshift(["partner_id", "child_of", partnerIds]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pedidos del período",
            res_model: "sale.order",
            views: [[false, "list"], [false, "form"]],
            domain,
            context,
            target: "current",
        });
    }

    openCustomerOrderLines() {
        const domain = [
            ["order_id.partner_id", "child_of", this._partnerIds],
            ["order_id.state", "in", ["sale", "done"]],
            ["order_id.date_order", ">=", this.state.dateFrom + " 00:00:00"],
            ["order_id.date_order", "<=", this.state.dateTo + " 23:59:59"],
        ];
        if (this.state.config && this.state.config.exclude_services) {
            domain.push(["product_id.type", "!=", "service"]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Piezas pedidas del período",
            res_model: "sale.order.line",
            views: [[false, "list"]],
            context: { list_view_ref: "odoo_mrp_planner.view_sale_order_line_planner_list" },
            domain,
            target: "current",
        });
    }

    openCustomerDemandPickings() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Entregas de pedidos del período (líneas)",
            res_model: "stock.move.line",
            views: [[false, "list"]],
            domain: [
                ["state", "=", "done"],
                ["picking_id.picking_type_id.code", "=", "outgoing"],
                ["picking_id.sale_id.partner_id", "child_of", this._partnerIds],
                ["picking_id.sale_id.state", "in", ["sale", "done"]],
                ["picking_id.sale_id.date_order", ">=", this.state.dateFrom + " 00:00:00"],
                ["picking_id.sale_id.date_order", "<=", this.state.dateTo + " 23:59:59"],
            ],
            target: "current",
        });
    }

    openCustomerDeliveryOrders() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Líneas de pedidos — cumplimiento de entrega",
            res_model: "sale.order.line",
            views: [[false, "list"]],
            domain: [
                ["order_id.partner_id", "child_of", this._partnerIds],
                ["order_id.state", "in", ["sale", "done"]],
                ["order_id.date_order", ">=", this.state.dateFrom + " 00:00:00"],
                ["order_id.date_order", "<=", this.state.dateTo + " 23:59:59"],
            ],
            context: {
                list_view_ref: "odoo_mrp_planner.view_sale_order_line_planner_list",
                group_by: ["delivery_status", "order_id"],
            },
            target: "current",
        });
    }

    // ── Formateo y semáforos (copia del Análisis de clientes base) ────────────

    fmt(n) {
        if (n === null || n === undefined) {
            return "—";
        }
        return new Intl.NumberFormat("es-AR").format(n);
    }

    fmtQty(v) {
        if (v == null) {
            return "—";
        }
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v);
    }

    fmtMoney(n) {
        if (n === null || n === undefined) {
            return "—";
        }
        return "$ " + new Intl.NumberFormat("es-AR", { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
    }

    fmtK(n) {
        if (!n && n !== 0) {
            return "—";
        }
        if (Math.abs(n) >= 1_000_000) {
            return (n / 1_000_000).toFixed(1) + "M";
        }
        if (Math.abs(n) >= 1_000) {
            return (n / 1_000).toFixed(0) + "k";
        }
        return String(n);
    }

    fmtPct(n) {
        if (n === null || n === undefined) {
            return "—";
        }
        return n.toFixed(1) + "%";
    }

    fmtDays(v) {
        return v !== null && v !== undefined ? this.fmt(v) + " d" : "—";
    }

    fmtDate(iso) {
        if (!iso) {
            return "—";
        }
        const [y, m, d] = String(iso).split("-");
        if (!y || !m || !d) {
            return String(iso);
        }
        return `${d}/${m}/${y}`;
    }

    /** Clase de tamaño del número de una card según su longitud (cards angostas). */
    numSizeClass(text, narrow = false) {
        const len = String(text ?? "").length;
        const md = narrow ? 10 : 17;
        const sm = narrow ? 14 : 21;
        if (len > sm) {
            return "o_planner_num_sm";
        }
        if (len > md) {
            return "o_planner_num_md";
        }
        return "";
    }

    deliveryClass(pct) {
        if (pct === null || pct === undefined) {
            return "text-muted";
        }
        const cfg = this.state.config;
        if (pct < (cfg.delivery_crit || 60)) {
            return "text-danger";
        }
        if (pct < (cfg.delivery_warn || 80)) {
            return "text-warning";
        }
        return "text-success";
    }

    ontimeClass(pct) {
        if (pct === null || pct === undefined) {
            return "text-muted";
        }
        const cfg = this.state.config;
        if (pct < (cfg.ontime_crit || 60)) {
            return "text-danger";
        }
        if (pct < (cfg.ontime_warn || 80)) {
            return "text-warning";
        }
        return "text-success";
    }

    riskClass(days) {
        if (days === null || days === undefined) {
            return "";
        }
        const risk = this.state.config.risk_days || 90;
        if (days > risk) {
            return "text-danger fw-semibold";
        }
        if (days > risk * 0.7) {
            return "text-warning";
        }
        return "";
    }

    abcBadgeClass(seg) {
        const map = { A: "text-bg-success", B: "text-bg-primary", C: "text-bg-warning text-dark" };
        return map[seg] || "text-bg-secondary";
    }

    freqBadgeClass(seg) {
        const map = { frecuente: "text-bg-success", ocasional: "text-bg-warning text-dark", inactivo: "text-bg-secondary", en_riesgo: "text-bg-danger" };
        return map[seg] || "text-bg-secondary";
    }

    freqLabel(seg) {
        const map = { frecuente: "Frecuente", ocasional: "Ocasional", inactivo: "Inactivo", en_riesgo: "En riesgo" };
        return map[seg] || seg || "—";
    }

    orderStateBadgeClass(state) {
        return {
            "Confirmado": "badge text-bg-primary",
            "Hecho": "badge text-bg-success",
            "Cancelado": "badge text-bg-danger",
            "Borrador": "badge text-bg-secondary",
        }[state] || "badge text-bg-secondary";
    }

    saleCatColor(name) {
        const map = { A: "#198754", B: "#0d6efd", C: "#ffc107", D: "#6c757d", E: "#c8d2dc" };
        return map[name] || "#6c757d";
    }

    donutColor(idx) {
        return CHART_COLORS.donut[idx % CHART_COLORS.donut.length];
    }

    leadMethodLabel(method) {
        const m = method || this.state.config.leadtime_method || "weighted";
        return { weighted: "ponderado", first: "1ª entrega", complete: "pedido completo" }[m] || m;
    }

    /** Método de valorización efectivo (config global; sin override en CRM). */
    get effectiveAmountMethod() {
        return (this.state.config && this.state.config.amount_method) || "pxq";
    }

    get amountLabelSuffix() {
        return this.effectiveAmountMethod === "real" ? "" : " (PxQ)";
    }

    amountNote() {
        if (this.effectiveAmountMethod === "real") {
            return "\nValorización: importe real de pedidos (con descuentos, sin impuestos).";
        }
        return "\nValorización: PxQ a precio de lista ACTUAL de la ficha (cantidad × precio de venta)."
            + "\n⚠ No considera precios históricos: si cambia la lista, el pasado se revaloriza. No cuadra con la facturación.";
    }

    svcNote() {
        return this.state.config && this.state.config.exclude_services
            ? "\n(Líneas de servicios excluidas según Ajustes → Ventas)" : "";
    }

    orderLeadTooltip(ord) {
        return `Lead time del pedido (método principal: ${this.leadMethodLabel()}). Días desde la confirmación hasta la fecha efectiva de cada remito.\n`
            + `Ponderado por cantidad: ${this.fmtDays(ord.lead_weighted)}\n`
            + `Primera entrega: ${this.fmtDays(ord.lead_first)}\n`
            + `Pedido completo: ${this.fmtDays(ord.lead_complete)}${ord.lead_complete == null ? " (aún sin entregar por completo)" : ""}`;
    }

    prodCellTooltip(prod) {
        if (!prod || prod.qty_ordered == null) {
            return "";
        }
        const n = (v) => new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v);
        return `Tasa de cumplimiento: entregado de los pedidos del período respecto a lo pedido de este artículo\n`
            + `Qty entregada ÷ Qty pedida × 100\n`
            + `→ ${n(prod.qty_delivered)} u ÷ ${n(prod.qty_ordered)} u = ${prod.delivery_pct != null ? prod.delivery_pct + "%" : "—"}`;
    }
}

registry.category("fields").add("crm_customer_kpis", {
    component: CrmCustomerKpisWidget,
    supportedTypes: ["many2one"],
});
