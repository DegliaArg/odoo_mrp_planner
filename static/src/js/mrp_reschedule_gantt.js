/** @odoo-module **/
import { Component, useState, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const DAY_MS = 86400000;
const DAYS_ES = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const COLORS = {
    mrp:      { fill: "#B5D4F4", stroke: "#185FA5" },
    purchase: { fill: "#9FE1CB", stroke: "#0F6E56" },
};

/**
 * Convierte un valor de campo Datetime de Odoo a un Date nativo.
 * Maneja: Luxon DateTime (Odoo 17+), string ISO, Date nativo, false/null.
 */
function toDate(v) {
    if (!v) return null;
    if (typeof v === "object" && v.isValid === false) return null;
    if (typeof v === "object" && typeof v.toJSDate === "function") return v.toJSDate();
    if (v instanceof Date) return v;
    if (typeof v === "string") {
        const s = v.replace(" ", "T");
        return new Date(s.includes("Z") || s.includes("+") ? s : s + "Z");
    }
    return null;
}

class MrpRescheduleGantt extends Component {
    static template = xml`
<div class="o_mrp_reschedule_gantt" style="margin:0 0 12px; border-top:1px solid #e5e5e5; padding-top:10px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:12px; font-weight:600; color:#444;">Gantt · cambios propuestos</span>
        <label style="display:flex; align-items:center; gap:6px; font-size:11px; color:#666; cursor:pointer; user-select:none;">
            <input type="checkbox" t-att-checked="state.showBefore" t-on-change="toggleBefore"/>
            Mostrar posición original
        </label>
    </div>
    <t t-if="ganttData">
        <svg style="width:100%; display:block; overflow:visible;"
             t-att-viewBox="'0 0 ' + ganttData.W + ' ' + ganttData.H">
            <t t-foreach="ganttData.days" t-as="day" t-key="'d' + day_index">
                <line t-att-x1="day.tx" y1="18"
                      t-att-x2="day.tx" t-att-y2="ganttData.H"
                      stroke="#e8e8e8" stroke-width="0.5"/>
                <text t-att-x="day.lx" y="12"
                      text-anchor="middle" dominant-baseline="central"
                      style="font-size:9px; fill:#999;">
                    <t t-esc="day.label"/>
                </text>
            </t>
            <t t-foreach="ganttData.rows" t-as="row" t-key="'r' + row_index">
                <rect x="0" t-att-y="row.by"
                      t-att-width="ganttData.W" t-att-height="ganttData.RH"
                      t-att-fill="row.bg" stroke="none"/>
                <text t-att-x="row.tx" t-att-y="row.ly"
                      dominant-baseline="central"
                      t-att-opacity="row.dimmed ? 0.4 : 1"
                      style="font-size:10px; fill:#444;">
                    <t t-esc="row.label"/>
                </text>
                <rect t-att-x="ganttData.LW - 13" t-att-y="row.by + 9"
                      width="9" height="12" rx="2"
                      t-att-fill="row.tc" t-att-stroke="row.ts" stroke-width="0.5"/>
                <t t-if="state.showBefore and row.bb">
                    <rect t-att-x="row.bb.x" t-att-y="row.bb.y"
                          t-att-width="row.bb.w" t-att-height="row.bb.h"
                          rx="3"
                          t-att-fill="row.bb.f" t-att-stroke="row.bb.s"
                          stroke-width="0.5" stroke-dasharray="4,2" opacity="0.4"/>
                </t>
                <t t-if="row.ab">
                    <rect t-att-x="row.ab.x" t-att-y="row.ab.y"
                          t-att-width="row.ab.w" t-att-height="row.ab.h"
                          rx="3"
                          t-att-fill="row.ab.f" t-att-stroke="row.ab.s"
                          stroke-width="1"
                          t-att-opacity="row.dimmed ? 0.4 : 1"/>
                </t>
            </t>
        </svg>
        <div style="display:flex; gap:14px; margin-top:6px; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:4px; font-size:10px; color:#888;">
                <svg width="14" height="8" style="display:inline-block;">
                    <rect x="0" y="0" width="14" height="8" rx="2"
                          fill="#B5D4F4" stroke="#185FA5" stroke-width="0.5"/>
                </svg>
                Fabricación
            </div>
            <div style="display:flex; align-items:center; gap:4px; font-size:10px; color:#888;">
                <svg width="14" height="8" style="display:inline-block;">
                    <rect x="0" y="0" width="14" height="8" rx="2"
                          fill="#9FE1CB" stroke="#0F6E56" stroke-width="0.5"/>
                </svg>
                Compra
            </div>
            <div style="display:flex; align-items:center; gap:4px; font-size:10px; color:#888;">
                <svg width="14" height="8" style="display:inline-block;">
                    <rect x="0" y="0" width="14" height="8" rx="2"
                          fill="#B5D4F4" stroke="#185FA5" stroke-width="0.5"
                          stroke-dasharray="3,2" opacity="0.4"/>
                </svg>
                Posición original
            </div>
            <div style="display:flex; align-items:center; gap:4px; font-size:10px; color:#888;">
                <svg width="14" height="8" style="display:inline-block;">
                    <rect x="0" y="0" width="14" height="8" rx="2"
                          fill="#B5D4F4" stroke="#185FA5" stroke-width="0.5"
                          opacity="0.4"/>
                </svg>
                Sin aplicar
            </div>
        </div>
    </t>
    <t t-else="">
        <div style="text-align:center; padding:14px; font-size:11px; color:#aaa;
                    border:1px dashed #ddd; border-radius:4px;">
            Use el botón <b>Calcular</b> para generar el Gantt.
        </div>
    </t>
</div>
    `;

    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.state = useState({ showBefore: true });
    }

    toggleBefore() {
        this.state.showBefore = !this.state.showBefore;
    }

    get ganttData() {
        const list = this.props.record.data.line_ids;
        const records = list?.records || [];
        if (!records.length) return null;

        // Layout constants (SVG units = CSS px at 1:1 in Odoo modal ~800px wide)
        const LW = 152; // label column width
        const GW = 436; // gantt track width
        const RH = 30;  // row height
        const BH = 16;  // bar height
        const W  = LW + GW;

        // Parse line records
        const lines = records.map(r => {
            const d = r.data;
            const isMrp = d.record_type === "mrp";
            const m2o   = isMrp ? d.production_id : d.purchase_id;
            const name  = Array.isArray(m2o) ? m2o[1] : String(m2o || "—");
            return {
                type:  d.record_type || "mrp",
                level: d.level || 0,
                apply: d.apply !== false,
                name:  name.slice(0, 18),
                cs:    toDate(d.current_date_start),
                cf:    toDate(d.current_date_finish),
                ns:    toDate(d.new_date_start),
                nf:    toDate(d.new_date_finish),
            };
        });

        // Date range across all lines
        const allDates = lines.flatMap(l => [l.cs, l.cf, l.ns, l.nf]).filter(Boolean);
        if (!allDates.length) return null;

        const minT = Math.min(...allDates.map(d => d.getTime()));
        const maxT = Math.max(...allDates.map(d => d.getTime()));

        // Expand to nearest day boundaries + 1 day padding each side
        const rs = new Date(minT);
        rs.setHours(0, 0, 0, 0);
        rs.setDate(rs.getDate() - 1);
        const re = new Date(maxT);
        re.setHours(23, 59, 59, 999);
        re.setDate(re.getDate() + 1);
        const rms = re.getTime() - rs.getTime();

        const toX = d => d ? Math.round(((d.getTime() - rs.getTime()) / rms) * GW) : 0;

        // Day tick marks and labels
        const days = [];
        const cur = new Date(rs);
        cur.setHours(0, 0, 0, 0);
        cur.setDate(cur.getDate() + 1);
        while (cur.getTime() < re.getTime()) {
            const tx = LW + toX(cur);
            const mid = new Date(cur);
            mid.setHours(12);
            days.push({
                tx,
                lx:    LW + toX(mid),
                label: `${DAYS_ES[cur.getDay()]} ${cur.getDate()}`,
            });
            cur.setDate(cur.getDate() + 1);
        }

        // Build one row object per line with all SVG coords pre-computed
        const rows = lines.map((line, i) => {
            const by = 20 + i * RH;
            const c  = COLORS[line.type] || COLORS.mrp;
            const BY = (RH - BH) / 2;

            const makeBar = (s, f) => {
                if (!s || !f) return null;
                return {
                    x: LW + toX(s),
                    y: by + BY,
                    w: Math.max(4, toX(f) - toX(s)),
                    h: BH,
                    f: c.fill,
                    s: c.stroke,
                };
            };

            // For purchase lines new_date_start is False → fall back to current_date_start
            const ns = line.ns || line.cs;
            const nf = line.nf || line.cf;

            return {
                label:  line.name,
                tx:     4 + line.level * 10,    // indent via x offset
                ly:     by + RH / 2,
                by,
                bg:     i % 2 === 0 ? "#f8f8f8" : "transparent",
                tc:     c.fill,
                ts:     c.stroke,
                dimmed: !line.apply,
                bb:     makeBar(line.cs, line.cf),   // before bar
                ab:     makeBar(ns, nf),              // after bar
            };
        });

        const H = 20 + lines.length * RH + 8;
        return { rows, days, W, H, LW, GW, RH };
    }
}

registry.category("view_widgets").add("reschedule_gantt", {
    component: MrpRescheduleGantt,
});
