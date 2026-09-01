/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import {
    parseLocalMinutes,
    rangeBounds,
    dateToOffsetPct,
    offsetPctToDate,
    barGeometry,
    layoutLanes,
    localIsoToServerUTC,
    makeTimeScale,
    scalePct,
    scaleSpan,
    scaleCuts,
} from "@odoo_mrp_planner_scheduling/js/scheduling_geometry";

describe("scheduling_geometry", () => {
    const { startMin, endMin } = rangeBounds("2026-09-01", "2026-09-03"); // 3 días

    test("rangeBounds cubre 3 días completos", () => {
        expect(endMin - startMin).toBe(3 * 1440);
    });

    test("parseLocalMinutes: fecha sola == medianoche", () => {
        expect(parseLocalMinutes("2026-09-01")).toBe(parseLocalMinutes("2026-09-01T00:00:00"));
    });

    test("offset: inicio 0%, fin 100%", () => {
        expect(dateToOffsetPct("2026-09-01T00:00:00", startMin, endMin)).toBeCloseTo(0, 6);
        expect(dateToOffsetPct("2026-09-04T00:00:00", startMin, endMin)).toBeCloseTo(100, 6);
    });

    test("round-trip offset <-> fecha (snap 15)", () => {
        for (const iso of ["2026-09-01T06:30:00", "2026-09-02T14:45:00", "2026-09-03T22:00:00"]) {
            const pct = dateToOffsetPct(iso, startMin, endMin);
            expect(offsetPctToDate(pct, startMin, endMin, 15)).toBe(iso);
        }
    });

    test("snap 15 min redondea al tramo más cercano", () => {
        const p1 = dateToOffsetPct("2026-09-01T06:37:00", startMin, endMin);
        expect(offsetPctToDate(p1, startMin, endMin, 15)).toBe("2026-09-01T06:30:00");
        const p2 = dateToOffsetPct("2026-09-01T06:38:00", startMin, endMin);
        expect(offsetPctToDate(p2, startMin, endMin, 15)).toBe("2026-09-01T06:45:00");
    });

    test("barGeometry: fin nulo se extiende al fin del rango", () => {
        const g = barGeometry("2026-09-02T00:00:00", null, startMin, endMin);
        expect(g.left).toBeCloseTo((1440 / 4320) * 100, 6);
        expect(g.width).toBeCloseTo(100 - (1440 / 4320) * 100, 6);
    });

    test("barGeometry: fechas inconsistentes → ancho mínimo", () => {
        const g = barGeometry("2026-09-01T10:00:00", "2026-09-01T09:00:00", startMin, endMin);
        expect(g.width).toBeCloseTo((15 / 4320) * 100, 9);
    });

    test("localIsoToServerUTC: hora de pared local → UTC server", () => {
        // Argentina (UTC-3, sin DST): 10:00 local → 13:00 UTC
        expect(localIsoToServerUTC("2026-09-01T10:00:00", "America/Argentina/Buenos_Aires"))
            .toBe("2026-09-01 13:00:00");
        // Cruce de día
        expect(localIsoToServerUTC("2026-09-01T22:30:00", "America/Argentina/Buenos_Aires"))
            .toBe("2026-09-02 01:30:00");
        // DST: New York en invierno (UTC-5) vs verano (UTC-4)
        expect(localIsoToServerUTC("2026-01-15T10:00:00", "America/New_York"))
            .toBe("2026-01-15 15:00:00");
        expect(localIsoToServerUTC("2026-07-01T10:00:00", "America/New_York"))
            .toBe("2026-07-01 14:00:00");
    });

    test("makeTimeScale: días ocultos colapsan el eje", () => {
        // Vie 04/09 a Lun 07/09 (2026), ocultar sáb(5) y dom(6)
        const s = makeTimeScale("2026-09-04", "2026-09-07", [5, 6]);
        expect(s.totalVisibleMin).toBe(2 * 1440);
        expect(scalePct(s, "2026-09-04T12:00:00")).toBeCloseTo(25, 6);
        expect(scalePct(s, "2026-09-07T00:00:00")).toBeCloseTo(50, 6);
        // Sábado (oculto) colapsa al punto de corte (50%)
        expect(scalePct(s, "2026-09-05T09:00:00")).toBeCloseTo(50, 6);
        // Barra vie 12 → lun 12: continua a través del finde
        const sp = scaleSpan(s, "2026-09-04T12:00:00", "2026-09-07T12:00:00");
        expect(sp.left).toBeCloseTo(25, 6);
        expect(sp.width).toBeCloseTo(50, 6);
        // Un corte al 50%
        const cuts = scaleCuts(s);
        expect(cuts.length).toBe(1);
        expect(cuts[0].leftPct).toBeCloseTo(50, 6);
    });

    test("layoutLanes: solapamiento → 2 lanes y sobrecarga", () => {
        const L = layoutLanes([
            { startMin: 0, endMin: 120 },
            { startMin: 60, endMin: 180 },
            { startMin: 200, endMin: 260 },
        ]);
        expect(L.laneCount).toBe(2);
        expect(L.overload).toEqual([true, true, false]);
        expect(L.lane).toEqual([0, 1, 0]);
    });
});
