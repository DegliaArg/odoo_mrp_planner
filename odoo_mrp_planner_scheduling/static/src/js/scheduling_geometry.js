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
