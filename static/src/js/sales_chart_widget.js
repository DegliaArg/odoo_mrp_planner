/** @odoo-module **/

/**
 * @widget SalesChartWidget
 * @description Widget de gráficos de ventas para el dashboard MRP.
 * Muestra un gráfico de barras con los productos más vendidos (por cantidad
 * o importe) y un gráfico de dona con la distribución de SKUs por categoría
 * ABC de venta. Permite filtrar por período, métrica, top-N, categoría de
 * venta ABC y categoría de producto.
 *
 * Métodos RPC que consume:
 *   - get_product_categories_for_chart([]) → Array<{ id: number, name: string }>
 *   - get_sales_chart_data(date_from, date_to, top_n, sale_category, product_categ_id, metric, doc_type)
 *       → Array<{ name: string, code: string, qty: number, amount: number, sale_category: string }>
 *
 * Props esperados:
 *   - record: Object — registro activo del dashboard (requerido por la infraestructura de widgets)
 */

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry }  from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Paleta de colores RGBA asignada a cada categoría ABC de venta.
 * La clave vacía `""` cubre productos sin categoría asignada.
 * @type {Object.<string, string>}
 */
const CAT_COLORS = {
    A: "rgba(25, 135, 84, 0.80)",
    B: "rgba(13, 110, 253, 0.80)",
    C: "rgba(255, 193, 7, 0.85)",
    D: "rgba(108, 117, 125, 0.80)",
    E: "rgba(200, 210, 220, 0.90)",
    "": "rgba(108, 117, 125, 0.65)",
};

/**
 * Convierte un objeto Date a cadena ISO parcial con formato YYYY-MM-DD,
 * compatible con los campos Date de Odoo sin componente horaria.
 * @param {Date} d - Fecha a convertir.
 * @returns {string} Cadena con formato "YYYY-MM-DD".
 */
function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class SalesChartWidget extends Component {
    static template = "odoo_mrp_planner.SalesChartWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    /**
     * Inicializa servicios ORM, referencias al canvas, estado reactivo y
     * hooks del ciclo de vida del componente.
     *
     * - onMounted: lanza en paralelo la carga de categorías de producto y
     *   los datos del gráfico para minimizar la latencia inicial.
     * - onPatched: re-dibuja los gráficos cada vez que el DOM se actualiza
     *   tras un cambio de estado, siempre que haya datos disponibles.
     * - onWillUnmount: destruye las instancias de Chart.js para liberar
     *   recursos del canvas y evitar memory leaks.
     */
    setup() {
        this.orm      = useService("orm");
        this.chartRef = useRef("salesCanvas");
        this.pieRef   = useRef("pieCanvas");
        this._chart   = null;
        this._pie     = null;

        this.state = useState({
            loading:         true,
            period:          "3m",
            metric:          "qty",
            topN:            20,
            saleCategory:    "",
            productCategId:  "",
            productCategs:   [],
            rows:            [],
            docType:         "sales",
        });

        onMounted(async () => {
            // Paralelizar: get_product_categories_for_chart y _load() son RPCs independientes
            const [cats] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_product_categories_for_chart", []),
                this._load(),
            ]);
            this.state.productCategs = cats || [];
        });

        onPatched(() => {
            if (!this.state.loading && this.state.rows.length) {
                if (this.chartRef.el) this._drawChart();
                if (this.pieRef.el)   this._drawPie();
            }
        });

        onWillUnmount(() => {
            if (this._chart) { this._chart.destroy(); this._chart = null; }
            if (this._pie)   { this._pie.destroy();   this._pie   = null; }
        });
    }

    /**
     * Calcula el rango de fechas [desde, hasta] en formato "YYYY-MM-DD"
     * a partir del período seleccionado en el estado.
     * "Hasta" es siempre la fecha de hoy; "Desde" se retrocede el número
     * de meses indicado por `state.period` (1m / 3m / 6m / 12m).
     * @returns {[string, string]} Tupla [date_from, date_to].
     */
    _dateRange() {
        const to   = new Date();
        const from = new Date(to);
        const m    = { "1m": 1, "3m": 3, "6m": 6, "12m": 12 }[this.state.period] || 3;
        from.setMonth(from.getMonth() - m);
        return [toDateStr(from), toDateStr(to)];
    }

    /**
     * Carga los datos del gráfico desde el servidor vía RPC y los almacena
     * en `state.rows`. Destruye las instancias de Chart.js previas antes de
     * la petición para evitar renderizados sobre canvas obsoletos.
     * Ante cualquier error RPC, deja `state.rows` vacío y registra el error
     * en consola sin interrumpir la UI.
     * @returns {Promise<void>}
     */
    async _load() {
        this.state.loading = true;
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        if (this._pie)   { this._pie.destroy();   this._pie   = null; }
        try {
            const [df, dt] = this._dateRange();
            const rows = await this.orm.call(
                "mrp.planner.dashboard",
                "get_sales_chart_data",
                [df, dt, this.state.topN, this.state.saleCategory || null, this.state.productCategId || null, this.state.metric, this.state.docType],
            );
            this.state.rows = rows || [];
        } catch (e) {
            console.error("[SalesChartWidget]", e);
            this.state.rows = [];
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Renderiza el gráfico de barras horizontales con los top-N productos
     * más vendidos, ordenados de mayor a menor según la métrica activa.
     * Cada barra recibe el color de la categoría ABC del producto.
     * Los tooltips muestran el código interno + nombre completo del producto
     * y el valor formateado en la unidad correspondiente (unidades o pesos).
     * No hace nada si el canvas no está disponible o Chart.js no se cargó.
     */
    _drawChart() {
        const canvas = this.chartRef.el;
        if (!canvas) return;

        const ChartJs = globalThis.Chart;
        if (typeof ChartJs === "undefined") {
            console.warn("[SalesChartWidget] Chart.js no disponible");
            return;
        }

        if (this._chart) { this._chart.destroy(); this._chart = null; }

        const isQty  = this.state.metric === "qty";
        const rows   = [...this.state.rows].sort((a, b) => isQty ? b.qty - a.qty : b.amount - a.amount);
        const labels = rows.map(r => r.code || r.name);
        const data   = rows.map(r => isQty ? r.qty : r.amount);
        const colors = rows.map(r => CAT_COLORS[r.sale_category] ?? CAT_COLORS[""]);

        const fmt = isQty
            ? v => new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v) + " u."
            : v => "$ " + new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);

        this._chart = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: isQty ? "Unidades vendidas" : "Importe",
                    data,
                    backgroundColor: colors,
                    borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => {
                                const r = rows[items[0].dataIndex];
                                return r.code ? `${r.code} — ${r.name}` : r.name;
                            },
                            label: ctx => fmt(ctx.raw),
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11 }, maxRotation: 45 },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.06)" },
                        ticks: { font: { size: 11 } },
                    },
                },
            },
        });
    }

    /**
     * Renderiza el gráfico de dona que muestra la distribución de SKUs por
     * categoría ABC de venta. Agrega por categoría la cantidad de SKUs,
     * cantidad total y el importe total de los `state.rows` actuales.
     *
     * Incluye un plugin inline `pieLabelPlugin` que dibuja el porcentaje
     * directamente sobre cada segmento; los segmentos menores al 5% no
     * muestran etiqueta para evitar solapamiento visual.
     *
     * Los tooltips detallan: SKUs y su porcentaje, cantidad total en
     * unidades e importe total en pesos.
     */
    _drawPie() {
        const canvas = this.pieRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._pie) { this._pie.destroy(); this._pie = null; }

        const ORDER  = ['A', 'B', 'C', 'D', 'E', ''];
        const NAMES  = { A: 'Cat. A', B: 'Cat. B', C: 'Cat. C', D: 'Cat. D', E: 'Cat. E', '': 'Sin cat.' };
        const bycat  = {};
        for (const r of this.state.rows) {
            const c = r.sale_category || '';
            if (!bycat[c]) bycat[c] = { skus: 0, qty: 0, amount: 0 };
            bycat[c].skus++;
            bycat[c].qty    += r.qty    || 0;
            bycat[c].amount += r.amount || 0;
        }

        const cats   = ORDER.filter(c => bycat[c]);
        const total  = cats.reduce((s, c) => s + bycat[c].skus, 0);
        const fmtN   = v => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v);
        const fmtAmt = v => '$ ' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(v);

        const pieLabelPlugin = {
            id: 'pieLabels',
            afterDatasetsDraw(chart) {
                const { ctx, data } = chart;
                const dataset = data.datasets[0];
                const ttl = dataset.data.reduce((a, b) => a + b, 0);
                chart.getDatasetMeta(0).data.forEach((arc, i) => {
                    const pct = ttl ? Math.round(dataset.data[i] / ttl * 100) : 0;
                    if (pct < 5) return;
                    const { x, y } = arc.getCenterPoint();
                    ctx.save();
                    ctx.fillStyle    = '#fff';
                    ctx.font         = 'bold 11px sans-serif';
                    ctx.textAlign    = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.shadowColor  = 'rgba(0,0,0,0.35)';
                    ctx.shadowBlur   = 3;
                    ctx.fillText(`${pct}%`, x, y);
                    ctx.restore();
                });
            },
        };

        this._pie = new ChartJs(canvas, {
            type: 'doughnut',
            data: {
                labels: cats.map(c => NAMES[c]),
                datasets: [{
                    data:            cats.map(c => bycat[c].skus),
                    backgroundColor: cats.map(c => CAT_COLORS[c] ?? CAT_COLORS['']),
                    borderWidth: 1,
                    borderColor: '#fff',
                }],
            },
            plugins: [pieLabelPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '48%',
                plugins: {
                    legend: { position: 'bottom', labels: { font: { size: 11 }, padding: 6, boxWidth: 14 } },
                    tooltip: {
                        callbacks: {
                            title: items => NAMES[cats[items[0].dataIndex]],
                            label: ctx => {
                                const d   = bycat[cats[ctx.dataIndex]];
                                const pct = total ? Math.round(d.skus / total * 100) : 0;
                                return [
                                    `  ${d.skus} SKU (${pct}%)`,
                                    `  Qty total: ${fmtN(d.qty)} u.`,
                                    `  Importe: ${fmtAmt(d.amount)}`,
                                ];
                            },
                        },
                    },
                },
            },
        });
    }

    /**
     * Cambia el período de análisis y recarga los datos si el valor difiere
     * del actual, evitando peticiones RPC redundantes.
     * @param {string} p - Período deseado: "1m" | "3m" | "6m" | "12m".
     */
    setPeriod(p)   { if (this.state.period !== p)          { this.state.period = p;          this._load(); } }

    /**
     * Cambia la métrica visualizada y recarga los datos si el valor difiere
     * del actual.
     * @param {string} m - Métrica deseada: "qty" (unidades) | "amount" (importe).
     */
    setMetric(m)   { if (this.state.metric !== m)          { this.state.metric = m;          this._load(); } }

    /**
     * Cambia el número máximo de productos a mostrar en el ranking y recarga
     * los datos si el valor difiere del actual.
     * @param {number} n - Cantidad de productos top a mostrar (ej. 10, 20, 50).
     */
    setTopN(n)     { if (this.state.topN !== n)            { this.state.topN = n;            this._load(); } }

    /**
     * Filtra los datos por una categoría ABC de venta específica y recarga
     * si el valor difiere del actual. Cadena vacía equivale a "todas".
     * @param {string} c - Categoría de venta: "A" | "B" | "C" | "D" | "E" | "".
     */
    setSaleCat(c)  { if (this.state.saleCategory !== c)    { this.state.saleCategory = c;    this._load(); } }

    /**
     * Cambia el tipo de documento origen de las ventas y recarga los datos
     * si el valor difiere del actual.
     * @param {string} d - Tipo de documento: "sales" (órdenes de venta) | "invoices" (facturas).
     */
    setDocType(d)  { if (this.state.docType !== d)         { this.state.docType = d;         this._load(); } }

    /**
     * Maneja el evento change del selector de categoría de producto Odoo.
     * Extrae el valor del elemento del DOM y recarga los datos si cambió.
     * Se usa el event handler en lugar de un setter directo porque el valor
     * proviene de un <select> nativo cuyo v-model no aplica en OWL sin binding.
     * @param {Event} ev - Evento change del elemento <select>.
     */
    setProductCat(ev) {
        const v = ev.target.value;
        if (this.state.productCategId !== v) { this.state.productCategId = v; this._load(); }
    }
}

registry.category("view_widgets").add("sales_chart_widget", {
    component: SalesChartWidget,
});
