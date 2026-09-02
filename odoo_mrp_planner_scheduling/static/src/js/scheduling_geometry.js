/** @odoo-module **/

/**
 * Geometría del tablero de programación — funciones PURAS y testeables.
 *
 * No dependen de OWL ni del DOM. La Fase 2 (drag & drop) reusa estas funciones
 * para convertir la posición del drop en fecha, y el "+ Nueva OF" las usa para
 * derivar la fecha por defecto de la posición del cursor.
 *
 * CONVENCIÓN DE ZONA HORARIA: los datetimes viajan como ISO local *naive*
 * ('YYYY-MM-DDTHH:MM:SS'), ya convertidos a la TZ del usuario en el servidor.
 * Para hacer aritmética inmune a DST y a la TZ del navegador, se parsean los
 * componentes y se cuentan minutos con Date.UTC (monótono, sin saltos de hora).
 */

/** Minutos desde epoch tratando los componentes como UTC (wall-clock estable). */
export function parseLocalMinutes(iso) {
    if (!iso) return null;
    // Acepta 'YYYY-MM-DD' y 'YYYY-MM-DDTHH:MM[:SS]'
    const [datePart, timePart] = iso.split("T");
    const [y, mo, d] = datePart.split("-").map(Number);
    let h = 0, mi = 0;
    if (timePart) {
        const parts = timePart.split(":").map(Number);
        h = parts[0] || 0;
        mi = parts[1] || 0;
    }
    return Math.round(Date.UTC(y, mo - 1, d, h, mi) / 60000);
}

/** Formatea minutos-UTC de vuelta a ISO local naive 'YYYY-MM-DDTHH:MM:SS'. */
export function minutesToLocalIso(min) {
    const d = new Date(min * 60000);
    const p = (n) => String(n).padStart(2, "0");
    return (
        `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}` +
        `T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:00`
    );
}

/**
 * Límites del rango cargado en minutos.
 * startMin = date_from 00:00 ; endMin = (date_to + 1 día) 00:00 (exclusivo).
 */
export function rangeBounds(dateFrom, dateTo) {
    const startMin = parseLocalMinutes(dateFrom);
    const endMin = parseLocalMinutes(dateTo) + 24 * 60; // fin exclusivo
    return { startMin, endMin };
}

/** Porcentaje [0,100] de una posición en minutos dentro del rango. */
export function minutesToPct(min, startMin, endMin) {
    const span = endMin - startMin;
    if (span <= 0) return 0;
    const pct = ((min - startMin) / span) * 100;
    return Math.max(0, Math.min(100, pct));
}

/** ISO local → porcentaje de offset dentro del rango. */
export function dateToOffsetPct(iso, startMin, endMin) {
    return minutesToPct(parseLocalMinutes(iso), startMin, endMin);
}

// ── Escala de tiempo con días ocultos (eje no lineal) ───────────────────────────
//
// Cuando se ocultan días (fines de semana), esos días no ocupan ancho: el eje
// pasa a ser la concatenación de los días visibles. Todas las posiciones se
// calculan sobre "minutos visibles" en vez de minutos reales.

/** Intersección de [a,b] con una lista de intervalos [ [s,e], ... ] ordenados. */
function _intersect(a, b, intervals) {
    const out = [];
    for (const [s, e] of intervals) {
        const lo = Math.max(a, s), hi = Math.min(b, e);
        if (hi > lo) out.push([lo, hi]);
    }
    return out;
}

/** Construye la escala del eje visible (posiciones en "minutos visibles").
 *
 * Un DÍA se oculta si su día de semana está en `hiddenWeekdays` (findes).
 * Además, si se pasa `keptIntervals` (lista de [inicioMin, finMin] reales,
 * ordenada y fusionada), SOLO esos tramos quedan visibles: todo lo demás —
 * incluidas las horas muertas dentro de un día— se colapsa. Sirve al modo ruta
 * para pegar las OFs de la cadena cortando el tiempo sin actividad.
 *
 * El eje visible es la concatenación de "segmentos" (subtramos de día visibles,
 * intersecados con keptIntervals si viene). Todas las posiciones se calculan
 * sobre esos segmentos, así cortes y anchos funcionan con cualquier colapso. */
export function makeTimeScale(dateFrom, dateTo, hiddenWeekdays = [], keptIntervals = null) {
    const hidden = new Set(hiddenWeekdays);
    const [fy, fm, fd] = dateFrom.split("-").map(Number);
    const [ty, tm, td] = dateTo.split("-").map(Number);
    const firstEpochDay = Math.round(Date.UTC(fy, fm - 1, fd) / 86400000);
    const lastEpochDay = Math.round(Date.UTC(ty, tm - 1, td) / 86400000);
    const days = [];
    const segments = [];   // {rs, re, vs} tramos visibles en minutos reales
    let visMin = 0;
    for (let ed = firstEpochDay; ed <= lastEpochDay; ed++) {
        const weekday = (new Date(ed * 86400000).getUTCDay() + 6) % 7; // Lun=0…Dom=6
        const dayStart = ed * 1440, dayEnd = dayStart + 1440;
        const weekdayHidden = hidden.has(weekday);
        // Subtramos visibles del día: día completo, recortado por keptIntervals.
        const ranges = weekdayHidden ? []
            : (keptIntervals ? _intersect(dayStart, dayEnd, keptIntervals) : [[dayStart, dayEnd]]);
        const dayVisStart = visMin;
        for (const [a, b] of ranges) {
            segments.push({ rs: a, re: b, vs: visMin });
            visMin += b - a;
        }
        days.push({
            epochDay: ed, weekday, startRealMin: dayStart,
            hidden: ranges.length === 0,          // día sin ningún tramo visible
            visStartMin: dayVisStart,
        });
    }
    return { firstEpochDay, lastEpochDay, days, segments, totalVisibleMin: visMin || 1 };
}

/** Minutos reales → minutos visibles. Los tramos colapsados (fuera de todo
 *  segmento) mapean al borde del segmento siguiente (el eje "salta"). */
function realToVisibleMin(scale, realMin) {
    const segs = scale.segments;
    if (!segs.length) return 0;
    if (realMin <= segs[0].rs) return 0;
    if (realMin >= segs[segs.length - 1].re) return scale.totalVisibleMin;
    for (const s of segs) {
        if (realMin < s.rs) return s.vs;          // cae en un hueco → borde del próximo
        if (realMin <= s.re) return s.vs + (realMin - s.rs);
    }
    return scale.totalVisibleMin;
}

/** ¿El minuto real cae dentro de un tramo visible (no colapsado)? */
export function isRealMinVisible(scale, realMin) {
    for (const s of scale.segments) {
        if (realMin >= s.rs && realMin < s.re) return true;
    }
    return false;
}

/** Porcentaje [0,100] de un minuto real sobre el eje visible. */
export function scaleMinuteToPct(scale, realMin) {
    return Math.max(0, Math.min(100, (realToVisibleMin(scale, realMin) / scale.totalVisibleMin) * 100));
}

/** Porcentaje de un ISO local sobre el eje visible. */
export function scalePct(scale, iso) {
    return scaleMinuteToPct(scale, parseLocalMinutes(iso));
}

/** {left,width} en % de una ventana [startIso, endIso] sobre el eje visible. */
export function scaleSpan(scale, startIso, endIso) {
    const l = scalePct(scale, startIso);
    const r = endIso ? Math.max(l, scalePct(scale, endIso)) : 100;
    return { left: l, width: r - l };
}

/** Cortes del eje: donde el eje salta un hueco colapsado (entre dos segmentos
 *  visibles consecutivos hay un tramo de tiempo real sin dibujar). */
export function scaleCuts(scale) {
    const cuts = [];
    const segs = scale.segments;
    for (let i = 1; i < segs.length; i++) {
        const gapMin = segs[i].rs - segs[i - 1].re;
        if (gapMin <= 0) continue;   // segmentos pegados (mismo día partido) → sin corte
        cuts.push({
            leftPct: (segs[i].vs / scale.totalVisibleMin) * 100,
            gapDays: Math.round(gapMin / 1440),
        });
    }
    return cuts;
}

/** Inversa: porcentaje visible → ISO local (para Fase 2, snap opcional). */
export function scalePctToDate(scale, pct, snapMin = 0) {
    const vis = (Math.max(0, Math.min(100, pct)) / 100) * scale.totalVisibleMin;
    const segs = scale.segments;
    let real = segs.length ? segs[0].rs : 0;
    for (const s of segs) {
        if (vis <= s.vs + (s.re - s.rs)) { real = s.rs + (vis - s.vs); break; }
    }
    if (snapMin > 0) real = Math.round(real / snapMin) * snapMin;
    return minutesToLocalIso(Math.round(real));
}

/** Offset (ms) entre la hora de pared de `tz` y UTC para un instante dado. */
function tzOffset(utcMs, tz) {
    const dtf = new Intl.DateTimeFormat("en-US", {
        timeZone: tz, hourCycle: "h23",
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    const m = {};
    for (const p of dtf.formatToParts(new Date(utcMs))) m[p.type] = p.value;
    const asUTC = Date.UTC(+m.year, m.month - 1, +m.day, +m.hour, +m.minute, +m.second);
    return asUTC - utcMs;
}

/**
 * Convierte un ISO local de pared ('YYYY-MM-DDTHH:MM:SS') en la zona `tz` al
 * string UTC que espera Odoo ('YYYY-MM-DD HH:MM:SS').
 *
 * Usa Intl (nativo del navegador, sin dependencias del framework de fechas de
 * Odoo) para resolver el offset — inmune a DST vía punto fijo de 2 pasadas. Se
 * usa para default_date_start del "+ Nueva OF": Odoo lo guarda como UTC naive, y
 * sin convertir la OF nacería corrida por el offset de la zona horaria.
 */
export function localIsoToServerUTC(iso, tz) {
    const [datePart, timePart = "00:00:00"] = iso.split("T");
    const [y, mo, d] = datePart.split("-").map(Number);
    const tp = timePart.split(":").map(Number);
    const desiredAsUTC = Date.UTC(y, mo - 1, d, tp[0] || 0, tp[1] || 0, tp[2] || 0);
    let guess = desiredAsUTC;
    for (let i = 0; i < 2; i++) guess = desiredAsUTC - tzOffset(guess, tz);
    const dt = new Date(guess);
    const p = (n) => String(n).padStart(2, "0");
    return (
        `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())} ` +
        `${p(dt.getUTCHours())}:${p(dt.getUTCMinutes())}:${p(dt.getUTCSeconds())}`
    );
}

/** Inversa: porcentaje de offset → ISO local, con snap opcional a `snapMin`. */
export function offsetPctToDate(pct, startMin, endMin, snapMin = 0) {
    const span = endMin - startMin;
    let min = startMin + (Math.max(0, Math.min(100, pct)) / 100) * span;
    if (snapMin > 0) min = Math.round(min / snapMin) * snapMin;
    return minutesToLocalIso(Math.round(min));
}

/**
 * Geometría de una barra: {left, width} en % sobre el rango.
 * - end nulo o <= start se resuelve con un ancho mínimo en minutos (minMinutes)
 *   para que la barra siga siendo visible/clickeable (datos inconsistentes).
 * - Se recorta a los bordes del rango.
 */
export function barGeometry(startIso, endIso, startMin, endMin, minMinutes = 15) {
    let s = parseLocalMinutes(startIso);
    let e = endIso ? parseLocalMinutes(endIso) : endMin;
    if (e === null || e <= s) {
        e = s + minMinutes; // dato inconsistente o puntual
    }
    const left = minutesToPct(s, startMin, endMin);
    const right = minutesToPct(e, startMin, endMin);
    return { left, width: Math.max(0, right - left) };
}

/**
 * Reparte barras solapadas en lanes paralelos (partición codiciosa de
 * intervalos) y marca cada barra como sobrecarga si solapa a otra.
 *
 * Regla de capacidad: 1 WO por CT a la vez → cualquier solapamiento es
 * sobrecarga (no hay campo de máquinas paralelas en Odoo estándar).
 *
 * @param {Array<{startMin:number,endMin:number}>} bars
 * @returns {{lane:number[], laneCount:number, overload:boolean[]}}
 */
export function layoutLanes(bars) {
    const n = bars.length;
    const lane = new Array(n).fill(0);
    const overload = new Array(n).fill(false);
    if (!n) return { lane, laneCount: 1, overload };

    const order = bars
        .map((_, i) => i)
        .sort((a, b) => bars[a].startMin - bars[b].startMin || bars[a].endMin - bars[b].endMin);

    const laneEnds = []; // fin (min) de la última barra en cada lane
    for (const i of order) {
        let placed = false;
        for (let l = 0; l < laneEnds.length; l++) {
            if (bars[i].startMin >= laneEnds[l]) {
                laneEnds[l] = bars[i].endMin;
                lane[i] = l;
                placed = true;
                break;
            }
        }
        if (!placed) {
            lane[i] = laneEnds.length;
            laneEnds.push(bars[i].endMin);
        }
    }

    for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
            if (bars[i].startMin < bars[j].endMin && bars[j].startMin < bars[i].endMin) {
                overload[i] = true;
                overload[j] = true;
            }
        }
    }
    return { lane, laneCount: Math.max(1, laneEnds.length), overload };
}
