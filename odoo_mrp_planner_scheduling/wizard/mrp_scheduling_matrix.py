"""
Módulo: mrp_scheduling_matrix.py

Métodos de backend para el tablero de programación de producción (eje horario
continuo).

Fuente de datos: mrp.production (todas las OFs, no solo las generadas por
solicitudes de programación).

Organización: filas = centro de trabajo (una por CT). Cada barra es una
mrp.workorder, posicionada por sus date_start / date_finished. Una OF con work
orders en varios CTs genera una barra por CT. Las OFs sin work orders caen al
centro preferido del producto (x_centros_compatibles) o a una fila final
"Sin centro asignado".

CONVENCIÓN DE ZONA HORARIA (única, no mezclar):
  El servidor convierte de UTC a la TZ del usuario (self.env.user.tz) y manda
  TODOS los datetimes como ISO local *naive* ('YYYY-MM-DDTHH:MM:SS'): barras,
  intervalos laborables y rango. El cliente los trata como hora de pared y NO
  reinterpreta zonas. Los límites de turno (mrp.planner.shift.hour_from, float)
  y los intervalos del calendario también viajan ya en hora local.
"""
import logging
from datetime import datetime, timedelta

import pytz

from odoo import models, api

from ..models.mrp_reschedule_cascade_mixin import (
    _get_old_code, _origin_tokens, _search_by_origin, _base_name,
)

_logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _shift_label(s):
    """Etiqueta compacta del turno: nombre + rango horario."""
    hf = int(s.hour_from)
    ht = int(s.hour_to)
    return f'{s.name} ({hf:02d}–{ht:02d})'


# ── Extensión de mrp.production ───────────────────────────────────────────────


class MrpProductionBoard(models.Model):
    _inherit = 'mrp.production'

    # ── Filtros ───────────────────────────────────────────────────────────────

    @api.model
    def get_scheduling_board_filters(self):
        """Devuelve sectores (tags de CT) y turnos disponibles."""
        tags = self.env['mrp.workcenter.tag'].search([], order='name')
        cfg  = self.env['mrp.reschedule.config'].get_config()
        default_tag_id = (
            cfg.default_scheduling_tag_id.id
            if cfg and cfg.default_scheduling_tag_id else None
        )
        shifts = []
        if cfg and getattr(cfg, 'enable_shifts', False):
            shifts = [
                {
                    'id':        s.id,
                    'name':      s.name,
                    'hour_from': s.hour_from,
                    'hour_to':   s.hour_to,
                    'label':     _shift_label(s),
                }
                for s in cfg.shift_ids.sorted('hour_from')
            ]
        return {
            'tags':                      [{'id': t.id, 'name': t.name} for t in tags],
            'default_scheduling_tag_id': default_tag_id,
            'shifts':                    shifts,
        }

    @api.model
    def get_scheduling_board_wcs_for_tags(self, tag_ids):
        """CTs activos que tienen al menos uno de los tags dados."""
        if not tag_ids:
            return []
        wcs = self.env['mrp.workcenter'].search(
            [('tag_ids', 'in', tag_ids), ('active', '=', True)],
            order='name',
        )
        return [{'id': w.id, 'name': w.name} for w in wcs]

    # ── Datos del tablero ─────────────────────────────────────────────────────

    @api.model
    def get_scheduling_board(self, tag_ids=None, date_from=None, date_to=None,
                             include_done=False, states=None):
        """Tablero filtrado por sector (tags). Delega en _build_board_payload."""
        if not date_from or not date_to:
            return {
                'range_from': date_from, 'range_to': date_to,
                'shifts': [], 'rows': [], 'total_bars': 0, 'empty_reason': 'no_dates',
            }
        if tag_ids:
            tagged = self.env['mrp.workcenter'].search(
                [('tag_ids', 'in', tag_ids), ('active', '=', True)]
            )
            valid_wc_ids = set(tagged.ids)
        else:
            valid_wc_ids = None   # None = todos
        return self._build_board_payload(valid_wc_ids, date_from, date_to,
                                         include_done, states=states)

    def _build_board_payload(self, valid_wc_ids, date_from, date_to, include_done,
                             force_wc_ids=None, only_mo_ids=None, states=None):
        """
        Construye el tablero (eje horario continuo) para el conjunto de CTs
        `valid_wc_ids` (None = todos) en [date_from, date_to].

        force_wc_ids: CTs que deben aparecer como fila SIEMPRE, aunque no tengan
        barras en el rango (usado por el modo ruta, donde los CTs de la ruta se
        muestran aunque sus operaciones no estén programadas).

        El cliente genera ticks y agrupamientos; el servidor manda barras, bandas
        y ocupación. Ver convención de zona horaria en la cabecera del módulo.
        Reutilizado por get_scheduling_board (filtro por sector) y por
        get_route_board (CTs de la ruta de una OF).
        """
        _empty = lambda reason: {
            'range_from': date_from, 'range_to': date_to,
            'shifts': [], 'rows': [], 'total_bars': 0, 'empty_reason': reason,
        }
        if not date_from or not date_to:
            return _empty('no_dates')

        tz = pytz.timezone(self.env.user.tz or 'UTC')

        # Rango en hora local → UTC naive para los dominios de búsqueda.
        local_from = tz.localize(datetime.strptime(date_from, '%Y-%m-%d'))
        local_to   = tz.localize(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        utc_from   = local_from.astimezone(pytz.utc).replace(tzinfo=None)
        utc_to     = local_to.astimezone(pytz.utc).replace(tzinfo=None)

        def _iso(dt):
            """UTC naive → ISO local naive ('YYYY-MM-DDTHH:MM:SS')."""
            if not dt:
                return None
            return pytz.utc.localize(dt).astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S')

        def _fmt(dt):
            """UTC naive → 'dd/mm HH:MM' local para tooltip."""
            if not dt:
                return ''
            return pytz.utc.localize(dt).astimezone(tz).strftime('%d/%m %H:%M')

        # ── Turnos (para divisorias / tinte nocturno) ──────────────────────────
        cfg = self.env['mrp.reschedule.config'].get_config()
        shifts_payload = []
        if cfg and getattr(cfg, 'enable_shifts', False):
            for s in cfg.shift_ids.sorted('hour_from'):
                shifts_payload.append({
                    'name':      s.name,
                    'hour_from': s.hour_from,
                    'hour_to':   s.hour_to,
                    'is_night':  s.hour_from > s.hour_to,   # cruza medianoche (22–06)
                })

        # ── OFs que solapan el rango (no solo las que arrancan dentro) ──────────
        # `states` (multi-selección del cliente) manda; si no viene, el default
        # histórico (confirmadas/en curso/por cerrar, + terminadas si include_done).
        if states is not None:
            board_states = list(states)
        else:
            board_states = ['confirmed', 'progress', 'to_close']
            if include_done:
                board_states.append('done')
        domain = [
            ('state', 'in', board_states),
            ('date_start', '!=', False),
            ('date_start', '<', utc_to),
            '|', ('date_finished', '>', utc_from), ('date_finished', '=', False),
        ]
        # Modo ruta: solo las OFs de la cadena (enfocada + padres/hijas), no todas
        # las que pasan por esos centros. Así el Gantt muestra el camino de la OF.
        if only_mo_ids is not None:
            domain.append(('id', 'in', list(only_mo_ids)))
        mos = self.env['mrp.production'].search(domain, order='date_start, id')

        # Prefetch para evitar N+1
        mos.mapped('bom_id')
        mos.mapped('product_uom_id')
        mos.mapped('product_id.product_tmpl_id.x_centros_compatibles.workcenter_id')
        mos.mapped('workorder_ids.workcenter_id.resource_calendar_id')
        mos.mapped('workorder_ids.workcenter_id.tag_ids')

        wc_records      = {}   # wc_id → workcenter
        bars_by_wc      = {}   # wc_id → [bar]
        unassigned_bars = []
        total_bars      = 0
        _UNASSIGNED     = object()

        def _fallback_wc(mo):
            """Centro preferido del producto (x_centros_compatibles), respetando
            el filtro de tags. Solo se usa para OFs sin work orders."""
            centros = mo.product_id.product_tmpl_id.x_centros_compatibles.filtered(
                'active'
            ).sorted(lambda c: (not c.is_preferred, c.sequence))
            for c in centros:
                wc = c.workcenter_id
                if wc and wc.active and (valid_wc_ids is None or wc.id in valid_wc_ids):
                    return wc
            return None

        def _add_bar(wc, mo, wo_id, wo_state, ds, df, dur_min,
                     prod_name, prod_code, uom):
            nonlocal total_bars
            inconsistent  = bool(ds) and bool(df) and df <= ds
            clipped_start = bool(ds) and ds < utc_from
            clipped_end   = (df is None) or (df > utc_to)
            bar = {
                'wo_id':              wo_id,
                'mo_id':              mo.id,
                'mo_name':            mo.name,
                'product_name':       prod_name,
                'product_code':       prod_code,
                'qty':                mo.product_qty,
                'uom':                uom,
                'wc_id':              None if wc is _UNASSIGNED else wc.id,
                'date_start':         _iso(ds),
                'date_finished':      _iso(df),
                'date_start_str':     _fmt(ds),
                'date_finished_str':  _fmt(df),
                'duration_expected':  round(dur_min or 0.0),   # minutos
                'wo_state':           wo_state,
                'mo_state':           mo.state,
                'clipped_start':      clipped_start,
                'clipped_end':        clipped_end,
                'inconsistent_dates': inconsistent,
                # Fechas crudas (UTC naive) para segmentar contra el calendario;
                # se quitan del payload antes de devolver (no son serializables).
                '_ds':                ds,
                '_df':                df,
            }
            if wc is _UNASSIGNED:
                unassigned_bars.append(bar)
            else:
                wc_records[wc.id] = wc
                bars_by_wc.setdefault(wc.id, []).append(bar)
            total_bars += 1

        for mo in mos:
            # Subcontratación fuera del tablero, por criterio EXPLÍCITO
            # (bom_id.type == 'subcontract'), nunca por ausencia de centro:
            # filtrar por "sin centro" ocultaría también OFs normales sin WO,
            # que SÍ deben verse en "Sin operaciones definidas".
            if mo.bom_id and mo.bom_id.type == 'subcontract':
                continue

            prod      = mo.product_id
            prod_name = prod.display_name if prod else ''
            prod_code = _get_old_code(mo)
            uom       = mo.product_uom_id.name if mo.product_uom_id else ''

            if mo.workorder_ids:
                # Una barra por WO con CT activo que pase el filtro y solape el rango.
                # Medido en la base real: 51% de las OFs activas tienen ≥2 WOs, así
                # que expandir por WO evita ocultar la carga de los demás centros.
                added = 0
                route_wcs = []   # CTs de la ruta (para el respaldo del modo ruta)
                for wo in mo.workorder_ids.sorted('sequence'):
                    wc = wo.workcenter_id
                    if not (wc and wc.active):
                        continue
                    if valid_wc_ids is not None and wc.id not in valid_wc_ids:
                        continue
                    if wc.id not in [w.id for w in route_wcs]:
                        route_wcs.append(wc)
                    wds, wdf = wo.date_start, wo.date_finished
                    if not wds:
                        continue   # sin inicio: no se puede posicionar
                    if not (wds < utc_to and (wdf is None or wdf > utc_from)):
                        continue   # la WO no solapa el rango visible
                    _add_bar(wc, mo, wo.id, wo.state, wds, wdf,
                             wo.duration_expected, prod_name, prod_code, uom)
                    added += 1
                # Modo ruta: si la OF tiene operaciones pero NINGUNA está programada
                # (WOs sin date_start — button_plan no corrido, el 93% en esta base),
                # igual se dibuja, ubicada por las fechas de la MO en cada centro de
                # su ruta, con estilo "sin programar" (wo_id nulo → sm-bar-unsched en
                # el cliente). Aplica a TODA la cadena, no solo a la enfocada: así los
                # relacionados sin programar se ven ubicados en el tiempo y el hilo
                # tiene sus dos puntas. Los CTs que NO reciben ninguna barra no se
                # fuerzan como fila (force_wc_ids = solo la OF enfocada).
                if not added and only_mo_ids is not None and mo.date_start:
                    for wc in route_wcs:
                        _add_bar(wc, mo, None, mo.state, mo.date_start, mo.date_finished,
                                 0.0, prod_name, prod_code, uom)
            else:
                # OFs sin work orders (15% en la base real): respaldo al centro
                # preferido; si no hay ninguno determinable, van a "Sin centro
                # asignado" para que se vean como pendientes en vez de desaparecer.
                wc = _fallback_wc(mo)
                _add_bar(wc if wc is not None else _UNASSIGNED, mo, None, mo.state,
                         mo.date_start, mo.date_finished, 0.0,
                         prod_name, prod_code, uom)

        # ── Bandas laborables por calendario (leaves-aware) ────────────────────
        iv_cache = {}

        def _intervals_for(cal):
            # None = no se pudieron calcular (sin calendario o fallo de la API);
            # [] = calculadas y sin franja laborable. El cliente los distingue.
            if not cal:
                return None
            if cal.id not in iv_cache:
                iv_cache[cal.id] = self._board_working_intervals(cal, local_from, local_to)
            return iv_cache[cal.id]

        wd_cache = {}   # cal.id → set de fechas locales laborables del CT

        def _working_dates(cal, ivs):
            """Fechas locales (del usuario) en que el CT tiene algún intervalo
            laborable. Un día que no está acá es un día COMPLETO no laborable.

            Devuelve None si las bandas NO se pudieron calcular (ivs is None): es
            "desconocido", distinto de un set VACÍO (calculado: el CT no trabaja
            ningún día del rango). El llamador propaga esa diferencia."""
            if ivs is None:
                return None
            if cal.id not in wd_cache:
                dates = set()
                for ws, we in ivs:
                    a = pytz.utc.localize(ws).astimezone(tz).date()
                    b = pytz.utc.localize(we - timedelta(microseconds=1)).astimezone(tz).date()
                    d = a
                    while d <= b:
                        dates.add(d)
                        d += timedelta(days=1)
                wd_cache[cal.id] = dates
            return wd_cache[cal.id]

        def _day_bounds_utc(d):
            a = tz.localize(datetime(d.year, d.month, d.day))
            b = tz.localize(datetime(d.year, d.month, d.day) + timedelta(days=1))
            return (a.astimezone(pytz.utc).replace(tzinfo=None),
                    b.astimezone(pytz.utc).replace(tzinfo=None))

        def _segment_bar(ds, df, working_dates):
            """La barra es CONTINUA de ds a df; SOLO se parte cuando atraviesa un
            día COMPLETO no laborable del CT (domingo para la mayoría, o un
            feriado). Las horas no laborables dentro de un día laborable (14→06 en
            un CT 6-14) NO parten la barra.

            working_dates: None = bandas desconocidas (no calculables) → NO se
            parte, barra continua (la fila ya se marca con bands_failed). Un set
            (aunque VACÍO) = calculado: un día que no está en el set es no
            laborable; set vacío ⇒ el CT no trabaja ningún día ⇒ todo_fuera=True.

            :returns: (segmentos_iso, todo_fuera). todo_fuera=True si la barra no
                toca ningún día laborable (se dibuja igual, continua y marcada).
            """
            span_end = df if (df and df > ds) else utc_to
            s0 = max(ds, utc_from)
            e0 = min(span_end, utc_to)
            if e0 <= s0:
                return [[_iso(s0), _iso(s0)]], False
            first = pytz.utc.localize(s0).astimezone(tz).date()
            last  = pytz.utc.localize(e0 - timedelta(microseconds=1)).astimezone(tz).date()
            segs = []
            run_a = run_b = None
            d = first
            while d <= last:
                da, db = _day_bounds_utc(d)
                # None (bandas no calculables) → no se parte: continua. Un set
                # (aun vacío) → se respeta la membresía (vacío ⇒ ningún día).
                if working_dates is None or d in working_dates:
                    seg_a, seg_b = max(s0, da), min(e0, db)
                    if run_a is None:
                        run_a, run_b = seg_a, seg_b
                    else:
                        run_b = seg_b
                elif run_a is not None:
                    segs.append((run_a, run_b))
                    run_a = None
                d += timedelta(days=1)
            if run_a is not None:
                segs.append((run_a, run_b))
            if not segs:
                return [[_iso(s0), _iso(e0)]], True
            return [[_iso(a), _iso(b)] for a, b in segs if b > a], False

        def _range_frac(ds, df):
            """Fracción de la ventana [ds, df] que cae dentro del rango cargado."""
            span_end = df if (df and df > ds) else utc_to
            total = (span_end - ds).total_seconds()
            if total <= 0:
                return 0.0
            ov = (min(span_end, utc_to) - max(ds, utc_from)).total_seconds()
            return max(0.0, min(1.0, ov / total))

        # CTs forzados (modo ruta): que aparezcan como fila aunque no tengan barras.
        if force_wc_ids:
            for wc in self.env['mrp.workcenter'].browse(sorted(force_wc_ids)):
                if wc.exists() and wc.id not in wc_records:
                    wc_records[wc.id] = wc
                    bars_by_wc.setdefault(wc.id, [])

        # ── Construir filas (una por CT, ordenadas por nombre) ─────────────────
        cal_cache = {}
        rows = []
        for wc in sorted(wc_records.values(), key=lambda w: w.name):
            bars = bars_by_wc.get(wc.id, [])
            cal  = wc.resource_calendar_id
            ivs = _intervals_for(cal)   # [(ws,we) UTC naive] | None
            if ivs is None and not cal:
                _logger.warning(
                    "Tablero: CT %s (id=%s) sin resource_calendar_id; "
                    "no se pueden calcular las bandas laborables.", wc.name, wc.id,
                )
            # Sin calendario → None (desconocido, no set vacío): la barra queda
            # continua y la fila se marca con bands_failed (no un CT que "no trabaja").
            wdates = _working_dates(cal, ivs) if cal else None

            # Barra continua, partida solo por día completo no laborable. La
            # ocupación prorratea la duración de las WO al rango cargado y EXCLUYE
            # las terminadas (son historial, no compiten por capacidad).
            planned_min = 0.0
            for bar in bars:
                ds = bar.pop('_ds')
                df = bar.pop('_df')
                if only_mo_ids is not None and bar.get('wo_id') is None:
                    # Modo ruta: barra "sin programar" (respaldo por fechas de MO) =
                    # ventana ESTIMADA, no operaciones discretas: se dibuja CONTINUA
                    # (un solo segmento), sin partir por días no laborables — el
                    # conector punteado largo la hacía parecer dos OFs distintas.
                    s0 = max(ds, utc_from)
                    e0 = min(df if (df and df > ds) else utc_to, utc_to)
                    segs = [[_iso(s0), _iso(max(e0, s0))]]
                    all_outside = False
                else:
                    segs, all_outside = _segment_bar(ds, df, wdates)
                bar['segments'] = segs
                bar['outside_calendar'] = all_outside
                if bar['mo_state'] != 'done' and bar['duration_expected']:
                    planned_min += bar['duration_expected'] * _range_frac(ds, df)

            avail_h   = cal._planner_available_hours(utc_from, utc_to, cal_cache) if cal else 0.0
            planned_h = planned_min / 60.0
            pct       = round(planned_h / avail_h * 100) if avail_h > 0 else 0
            bands_iso = [[_iso(ws), _iso(we)] for ws, we in ivs] if ivs else []
            rows.append({
                'wc_id':             wc.id,
                'wc_name':           wc.name,
                'tag_names':         [t.name for t in wc.tag_ids],
                'bars':              bars,
                'working_intervals': bands_iso,
                'bands_failed':      ivs is None,
                'occupancy': {
                    'planned_hours':   round(planned_h, 1),
                    'available_hours': round(avail_h, 1),
                    'pct':             pct,
                },
            })

        if unassigned_bars:
            for bar in unassigned_bars:
                bar.pop('_ds', None)
                bar.pop('_df', None)
            rows.append({
                'wc_id':             None,
                'wc_name':           'Sin operaciones definidas',
                'is_unassigned':     True,
                'tag_names':         [],
                'bars':              unassigned_bars,
                'working_intervals': [],
                'occupancy':         None,
            })

        return {
            'range_from':      date_from,
            'range_to':        date_to,
            'user_tz':         self.env.user.tz or 'UTC',
            'hidden_weekdays': self.env['mrp.reschedule.config']._board_hidden_weekdays_list(),
            'shifts':          shifts_payload,
            'rows':            rows,
            'total_bars':      total_bars,
        }

    def _compute_route(self, mo):
        """Ruta de una OF: sus work orders con CT activo, en ORDEN TOPOLÓGICO por
        `blocked_by_workorder_ids`, como lista [(workcenter, posición)] sin repetir
        CT. `sequence` se usa solo de respaldo (desempate y cuando la OF no tiene
        dependencias): en esta instancia el sequence del workorder contradice las
        dependencias en el ~89% de las OFs, así que NO es fuente de orden fiable.

        La "ruta" son las workorder_ids de UNA mrp.production (la OF pasa por
        varios CTs); NO es un árbol de OFs distintas. Método reutilizable: la
        Fase 2 responde "qué se mueve al arrastrar" con la misma estructura, y el
        árbol de OFs relacionadas (hijas/consumidoras) se sumará después como una
        segunda fuente sin reescribir esto.

        NOTA FASE 2 (drag): se decidió arrastrar la OF completa, no la operación,
        porque en esta instancia el ~93% de las WOs no tiene date_start (no se
        corre button_plan). El diseño SÍ soporta drag por-operación: cuando las
        WOs tengan date_start poblado (button_plan en el flujo), el drop puede
        anclar la WO en vez de la OF usando esta misma ruta. No re-descubrir esto.
        """
        wos = mo.workorder_ids.filtered(
            lambda w: w.workcenter_id and w.workcenter_id.active
        )
        by_id = {w.id: w for w in wos}
        wo_ids = set(by_id)
        # Predecesores dentro de la OF (blocked_by acotado a esta OF) y sucesores.
        preds = {wid: [b for b in by_id[wid].blocked_by_workorder_ids.ids if b in wo_ids]
                 for wid in wo_ids}
        succ = {}
        for wid, ps in preds.items():
            for p in ps:
                succ.setdefault(p, []).append(wid)
        indeg = {wid: len(preds[wid]) for wid in wo_ids}
        seq_key = lambda i: (by_id[i].sequence, i)   # desempate/respaldo por sequence

        # Kahn: orden topológico; los "listos" se ordenan por sequence.
        ready = sorted([wid for wid in wo_ids if indeg[wid] == 0], key=seq_key)
        order = []
        while ready:
            wid = ready.pop(0)
            order.append(wid)
            for s in succ.get(wid, []):
                indeg[s] -= 1
                if indeg[s] == 0:
                    ready.append(s)
            ready.sort(key=seq_key)
        # Ciclo (no debería): los que queden, por sequence.
        if len(order) < len(wo_ids):
            order += sorted(wo_ids - set(order), key=seq_key)

        route, seen = [], set()
        for wid in order:
            wc = by_id[wid].workcenter_id
            if wc.id not in seen:
                seen.add(wc.id)
                route.append((wc, len(route) + 1))
        return route

    def _compute_related_tree(self, mo, max_depth=12, include_done=True, states=None):
        """Árbol de OFs relacionadas por `origin`.

        En esta instancia `origin` es el único vínculo poblado (86%);
        x_parent_mo_id está al 0% y los stock-moves (move_orig/move_dest) vacíos.
        - Ancestros ("padres", que consumen esta OF): se sigue mo.origin hacia
          arriba (cada token del origin es el nombre de una OF).
        - Descendientes ("hijas", que fabrican sus componentes): OFs cuyo origin
          cita a esta OF — matcheo por token con _search_by_origin (soporta origin
          compuesto y evita el falso positivo MO/001↔MO/0011).

        Las hijas se fabrican ANTES, así que suelen estar `done`. Con
        `include_done=True` (la ruta muestra el historial) NO se filtran por
        estado, para que aparezcan igual que los padres (que nunca se filtran).

        :returns: (items, tree_ids). items = lista ordenada
            hijas (más profundas primero) → self → padres, cada uno con
            {mo_id,name,product,qty,uom,state,date_start,date_finished,relation,level}.
        """
        Prod = self.env['mrp.production']
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        # `states` (multi-selección del cliente) manda; si no viene, el default.
        # Se aplica a padres Y a hijas (antes los padres no se filtraban, por eso
        # se colaban las canceladas).
        if states is not None:
            tree_states = list(states)
        else:
            tree_states = ['confirmed', 'progress', 'to_close']
            if include_done:
                tree_states = tree_states + ['done']
        act = [('state', 'in', tree_states)]

        def _fmt(dt):
            return pytz.utc.localize(dt).astimezone(tz).strftime('%d/%m %H:%M') if dt else ''

        def _info(m, relation, level):
            return {
                'mo_id': m.id, 'name': m.name,
                'product': m.product_id.display_name if m.product_id else '',
                'qty': m.product_qty,
                'uom': m.product_uom_id.name if m.product_uom_id else '',
                'state': m.state,
                'date_start': _fmt(m.date_start), 'date_finished': _fmt(m.date_finished),
                'relation': relation, 'level': level,
            }

        MAX_NODES = 80   # cota de seguridad ante cadenas patológicamente anchas
        seen = {mo.id}

        truncated = False   # True si se cortó por MAX_NODES (hay más cadena)

        # Ancestros: seguir origin hacia arriba (compuesto → varios padres). Los
        # parciales citan la BASE en origin y el padre puede estar partido, así que
        # se matchea por name = tok | base | base-%. Batch: UNA query por nivel con
        # todos los tokens de la frontera (no un search por token → evita N+1).
        ancestors, frontier, depth = [], [mo], 0
        while frontier and depth < max_depth and not truncated:
            toks = set()
            for cur in frontier:
                toks |= _origin_tokens(cur.origin)
            if not toks:
                break
            exact_names, bases = set(), set()
            for tok in toks:
                b = _base_name(tok)
                exact_names.update((tok, b))
                bases.add(b)
            leaves = [('name', 'in', list(exact_names))]
            leaves += [('name', '=like', b + '-%') for b in bases]
            domain = ['|'] * (len(leaves) - 1) + leaves + act
            nxt = []
            for p in Prod.search(domain):
                if p.id in seen:
                    continue
                if len(seen) >= MAX_NODES:
                    truncated = True
                    break
                seen.add(p.id)
                ancestors.append((depth + 1, p))
                nxt.append(p)
            frontier, depth = nxt, depth + 1

        # Descendientes: OFs cuyo origin cita el nombre BASE (recursivo por nivel).
        # Se busca por base para captar OFs enteras y parciales por igual.
        descendants, seen_d, names, depth = [], set(seen), [_base_name(mo.name)], 0
        while names and depth < max_depth and not truncated:
            matches = _search_by_origin(self.env, 'mrp.production', names, act)
            nxt, stop = [], False
            for name in names:
                for child in matches.get(name, Prod):
                    if child.id in seen_d:
                        continue
                    if len(seen_d) >= MAX_NODES:
                        truncated = stop = True
                        break
                    seen_d.add(child.id)
                    descendants.append((depth, child))
                    nxt.append(_base_name(child.name))
                if stop:
                    break
            names, depth = nxt, depth + 1

        items = [_info(m, 'descendant', lvl) for lvl, m in sorted(descendants, key=lambda x: -x[0])]
        items.append(_info(mo, 'self', 0))
        items += [_info(m, 'ancestor', lvl) for lvl, m in sorted(ancestors, key=lambda x: x[0])]
        return items, {i['mo_id'] for i in items}, truncated

    @api.model
    def get_route_board(self, mo_id, include_done=True, states=None):
        """Modo ruta: el "camino" de una OF (su cadena de padres/hijas).

        Devuelve las filas de los CTs por los que pasan las OFs de la cadena, con
        SOLO las barras de esa cadena (only_mo_ids = tree_ids), no todas las OFs
        de esos centros. El rango abarca la cadena completa + margen; el cliente
        colapsa los huecos vacíos y ajusta el zoom. Las filas se ordenan
        cronológicamente (escalonado) para coincidir con el panel lateral.
        `route_edges` lleva las aristas componente→consumidora para el hilo.
        """
        mo = self.env['mrp.production'].browse(mo_id)
        if not mo.exists():
            return {'empty_reason': 'not_found'}
        route = self._compute_route(mo)
        if not route:
            return {'empty_reason': 'no_route', 'route_mo_name': mo.name}

        tz = pytz.timezone(self.env.user.tz or 'UTC')

        # Árbol de OFs relacionadas (por origin) — panel lateral y alcance del Gantt.
        # `states` (filtro de estado del cliente) acota qué padres/hijas entran.
        tree, tree_ids, tree_truncated = self._compute_related_tree(mo, states=states)
        tree_mos = self.env['mrp.production'].browse(sorted(tree_ids))

        # El Gantt abarca los CTs y el rango de TODO el árbol (no solo la OF
        # enfocada). Se lee en batch (una sola pasada de workorders del árbol),
        # en vez de _compute_route por cada OF (N+1 con MAX_NODES=80).
        wos = tree_mos.mapped('workorder_ids')
        all_wc_ids = set(wos.mapped('workcenter_id').filtered('active').ids)
        dts = [d for d in wos.mapped('date_start') if d]
        dts += [d for d in wos.mapped('date_finished') if d]
        dts += [d for d in tree_mos.mapped('date_start') if d]
        dts += [d for d in tree_mos.mapped('date_finished') if d]
        if not dts:
            return {'empty_reason': 'no_dates', 'route_mo_name': mo.name}
        lo = pytz.utc.localize(min(dts)).astimezone(tz).date() - timedelta(days=1)
        hi = pytz.utc.localize(max(dts)).astimezone(tz).date() + timedelta(days=1)

        # force_wc_ids: SOLO los CTs de la OF ENFOCADA aparecen siempre (aunque
        # estén vacíos). Los CTs de las OFs del árbol (padres/hijas) aparecen solo
        # si tienen alguna barra en el rango — si no, ocupaban media pantalla vacíos
        # (venían de OFs sin operaciones programadas). valid_wc_ids sigue siendo
        # todo el árbol (para que las barras de las relacionadas se dibujen).
        focus_wc_ids = {wc.id for wc, _seq in route}
        payload = self._build_board_payload(
            all_wc_ids, lo.strftime('%Y-%m-%d'), hi.strftime('%Y-%m-%d'), include_done,
            force_wc_ids=focus_wc_ids, only_mo_ids=tree_ids, states=states,
        )

        # Orden de filas = orden del escalonado (cronológico por la barra más
        # temprana de cada CT), para que coincida con el orden del panel lateral
        # (hijas antes → padres después). Empate/CT sin barras: por nombre.
        seq_by_wc = {wc.id: seq for wc, seq in route}
        # Solo filas con barras, MÁS los CTs de la OF enfocada (que se conservan
        # aunque estén vacíos). Nunca una fila de CT de una OF del árbol sin barra.
        rows = [r for r in payload['rows']
                if not r.get('is_unassigned')
                and (r.get('bars') or r['wc_id'] in focus_wc_ids)]

        def _row_min_start(r):
            starts = [b['date_start'] for b in r.get('bars', []) if b.get('date_start')]
            return (min(starts) if starts else '9999', r['wc_name'])

        rows.sort(key=_row_min_start)
        for r in rows:
            r['route_seq'] = seq_by_wc.get(r['wc_id'])
        payload['rows'] = rows

        # Aristas de la cadena (para el hilo conector): cada OF apunta, por su
        # origin, a la OF que consume su producto (from = componente/hija →
        # to = consumidora/padre). Se resuelve con el MISMO criterio que el árbol:
        # match exacto o, si no, por nombre BASE (los parciales citan la base en su
        # origin y el padre puede estar partido). POLÍTICA cuando una base matchea
        # varias parciales: se conecta a la MÁS CERCANA EN EL TIEMPO al hijo (una
        # sola arista limpia por relación), en vez de una a cada parcial.
        exact_to_id = {tm.name: tm.id for tm in tree_mos}
        base_to_mos = {}
        for tm in tree_mos:
            base_to_mos.setdefault(_base_name(tm.name), []).append(tm)

        def _edge_target(tok, child):
            if tok in exact_to_id:
                return exact_to_id[tok]
            cands = [c for c in base_to_mos.get(_base_name(tok), []) if c.id != child.id]
            if not cands:
                return None
            if child.date_start:
                cands = sorted(cands, key=lambda c: (
                    abs((c.date_start - child.date_start).total_seconds())
                    if c.date_start else float('inf')))
            return cands[0].id

        edges, seen_edges = [], set()
        for tm in tree_mos:
            for tok in _origin_tokens(tm.origin):
                pid = _edge_target(tok, tm)
                if pid and pid != tm.id and (tm.id, pid) not in seen_edges:
                    seen_edges.add((tm.id, pid))
                    edges.append({'from': tm.id, 'to': pid})

        payload.update({
            'route_mo_id':     mo.id,
            'route_mo_name':   mo.name,
            'route_product':   mo.product_id.display_name if mo.product_id else '',
            'route_qty':       mo.product_qty,
            'route_uom':       mo.product_uom_id.name if mo.product_uom_id else '',
            'related_tree':    tree,
            'route_tree_ids':  sorted(tree_ids),
            'route_edges':     edges,
            'route_truncated': tree_truncated,
        })
        return payload

    @api.model
    def get_request_board(self, request_id, states=None):
        """Modo propuesta: dibuja el plan calculado de una solicitud como Gantt.

        Igual que el modo ruta (filas = CT, una barra por OPERACIÓN, hilos por la
        cadena), pero alimentado por las líneas-OF de la solicitud y sus
        operaciones (mrp.production.request.line[.op]) en vez de OFs reales.

        La OCUPACIÓN de cada CT suma la carga de la PROPUESTA a la carga real ya
        existente en ese centro (OFs confirmadas planificadas en el rango), para
        que el planificador vea si la propuesta lo deja sobrecargado ANTES de
        confirmar. La carga existente se obtiene reutilizando _build_board_payload.

        :param request_id: int — ID de la mrp.production.request calculada.
        :param states: list | None — estados de las OFs reales a considerar para la
            carga existente (None = default: confirmadas/en curso/por cerrar).
        :returns: dict — payload con la MISMA forma que get_route_board (rows/bars/
            route_edges/related_tree), más los datos de ocupación existente+propuesta.
        """
        req = self.env['mrp.production.request'].browse(request_id)
        if not req.exists():
            return {'empty_reason': 'not_found'}

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        lines = req.line_ids.filtered(lambda l: l.record_type == 'mrp')
        ops   = lines.mapped('op_ids')
        if not ops:
            return {'empty_reason': 'no_ops', 'request_name': req.name or ''}

        dts = [o.date_start for o in ops if o.date_start]
        dts += [o.date_finish for o in ops if o.date_finish]
        if not dts:
            return {'empty_reason': 'no_dates', 'request_name': req.name or ''}
        lo = pytz.utc.localize(min(dts)).astimezone(tz).date() - timedelta(days=1)
        hi = pytz.utc.localize(max(dts)).astimezone(tz).date() + timedelta(days=1)
        date_from, date_to = lo.strftime('%Y-%m-%d'), hi.strftime('%Y-%m-%d')

        wc_ids = set(ops.mapped('workcenter_id').filtered('active').ids)

        def _iso(dt):
            if not dt:
                return None
            return pytz.utc.localize(dt).astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S')

        def _fmt(dt):
            if not dt:
                return ''
            return pytz.utc.localize(dt).astimezone(tz).strftime('%d/%m %H:%M')

        # Carga real EXISTENTE + bandas + turnos, reutilizando el builder del tablero.
        # include_done=False: las terminadas son historial, no compiten por capacidad.
        # force_wc_ids: todos los CTs de la propuesta aparecen aunque no tengan carga
        # real. only_mo_ids=None: se cuenta TODA la carga real de esos centros.
        base = self._build_board_payload(
            wc_ids, date_from, date_to, include_done=False,
            force_wc_ids=wc_ids, only_mo_ids=None, states=states,
        )
        base_rows = {r['wc_id']: r for r in base.get('rows', []) if r.get('wc_id')}

        # ── Barras de propuesta (una por operación) agrupadas por CT ───────────
        bars_by_wc  = {}
        proposal_by_wc = {}   # wc_id → horas de propuesta
        for line in lines:
            prod = line.product_id
            for op in line.op_ids:
                wc = op.workcenter_id
                if not (wc and wc.active and wc.id in wc_ids):
                    continue
                ds, df = op.date_start, op.date_finish
                bars_by_wc.setdefault(wc.id, []).append({
                    'wo_id':              op.id,
                    'mo_id':              line.id,    # id de la línea-OF (para hilos)
                    'line_id':            line.id,
                    # Etiqueta = NOMBRE del producto (identifica de un vistazo). El
                    # código va al tooltip (product_name/display_name): los códigos
                    # comparten el sufijo de orden, así que no distinguen en la barra.
                    'mo_name':            prod.name or prod.default_code or '',
                    'product_name':       prod.display_name if prod else '',
                    'product_code':       prod.default_code or '',
                    'qty':                line.product_qty,
                    'uom':                prod.uom_id.name if prod.uom_id else '',
                    'wc_id':              wc.id,
                    'date_start':         _iso(ds),
                    'date_finished':      _iso(df),
                    'date_start_str':     _fmt(ds),
                    'date_finished_str':  _fmt(df),
                    'duration_expected':  round((op.duration_hours or 0.0) * 60),
                    'wo_state':           'proposal',
                    'mo_state':           'proposal',
                    'clipped_start':      False,
                    'clipped_end':        False,
                    'inconsistent_dates': bool(ds) and bool(df) and df <= ds,
                    # Ventana estimada: barra CONTINUA (un segmento), como las
                    # "sin programar" del modo ruta — no se parte por días no laborables.
                    'segments':           [[_iso(ds), _iso(df or ds)]],
                    'outside_calendar':   False,
                    'is_alternative':     op.is_alternative,
                    'is_proposal':        True,
                    'level':              line.level,
                })
                proposal_by_wc[wc.id] = proposal_by_wc.get(wc.id, 0.0) + (op.duration_hours or 0.0)

        # ── Backlog INVISIBLE por CT: WOs de OFs activas SIN fecha ─────────────
        # El ancla solo cuenta las WOs con date_start; las sin planificar (el grueso,
        # button_plan no corrido) no reservan capacidad → la ocupación es un PISO.
        # Se cuentan para avisar la subestimación (no se reprograma nada).
        unplanned_by_wc = {}   # wc_id → (count, minutos)
        grp = self.env['mrp.workorder'].read_group(
            [('workcenter_id', 'in', list(wc_ids)),
             ('production_id.state', 'in', ['confirmed', 'progress', 'to_close']),
             ('date_start', '=', False)],
            ['duration_expected:sum'], ['workcenter_id'],
        )
        for g in grp:
            wc_id = g['workcenter_id'][0]
            unplanned_by_wc[wc_id] = (g.get('__count', 0), g.get('duration_expected') or 0.0)

        # ── Filas: ocupación = existente (real) + propuesta ────────────────────
        rows = []
        for wc in self.env['mrp.workcenter'].browse(sorted(wc_ids)):
            base_row = base_rows.get(wc.id, {})
            occ      = base_row.get('occupancy') or {}
            avail_h    = occ.get('available_hours', 0.0)
            existing_h = occ.get('planned_hours', 0.0)
            proposal_h = proposal_by_wc.get(wc.id, 0.0)
            total_h    = existing_h + proposal_h
            pct        = round(total_h / avail_h * 100) if avail_h > 0 else 0
            unp_count, unp_min = unplanned_by_wc.get(wc.id, (0, 0.0))
            bars = sorted(bars_by_wc.get(wc.id, []), key=lambda b: b['date_start'] or '')
            rows.append({
                'wc_id':             wc.id,
                'wc_name':           wc.name,
                'tag_names':         base_row.get('tag_names', []),
                'bars':              bars,
                'working_intervals': base_row.get('working_intervals', []),
                'bands_failed':      base_row.get('bands_failed', False),
                'occupancy': {
                    'existing_hours':  round(existing_h, 1),
                    'proposal_hours':  round(proposal_h, 1),
                    'planned_hours':   round(total_h, 1),
                    'available_hours': round(avail_h, 1),
                    'pct':             pct,
                    # Subestimación: WOs sin fecha en este CT (no cuentan en la carga).
                    'unplanned_count': unp_count,
                    'unplanned_hours': round(unp_min / 60.0, 1),
                },
            })

        # Orden cronológico (escalonado), igual que el modo ruta.
        rows.sort(key=lambda r: (
            min([b['date_start'] for b in r['bars'] if b['date_start']], default='9999'),
            r['wc_name'],
        ))
        # Desde 1: el template oculta route_seq con t-if (0 sería falsy → la fila
        # más temprana quedaba sin número).
        for i, r in enumerate(rows, 1):
            r['route_seq'] = i

        # Aristas de la cadena: componente(hija) → consumidora(padre), por parent_line_id.
        line_ids_set = set(lines.ids)
        edges = [
            {'from': line.id, 'to': line.parent_line_id.id}
            for line in lines
            if line.parent_line_id and line.parent_line_id.id in line_ids_set
        ]

        # Árbol lateral (misma forma que _compute_related_tree): raíces = 'self',
        # el resto = 'descendant' (se fabrican antes que su consumidora).
        tree = []
        for line in lines.sorted(lambda l: (l.sequence, l.id)):
            prod = line.product_id
            tree.append({
                'mo_id':         line.id,
                'name':          prod.default_code or prod.name or '',
                'product':       prod.display_name if prod else '',
                'qty':           line.product_qty,
                'uom':           prod.uom_id.name if prod.uom_id else '',
                'state':         'proposal',
                'date_start':    _fmt(line.new_date_start),
                'date_finished': _fmt(line.new_date_finish),
                'relation':      'self' if not line.parent_line_id else 'descendant',
                'level':         line.level,
            })

        return {
            'range_from':      date_from,
            'range_to':        date_to,
            'user_tz':         self.env.user.tz or 'UTC',
            'hidden_weekdays': base.get('hidden_weekdays', []),
            'shifts':          base.get('shifts', []),
            'rows':            rows,
            'total_bars':      sum(len(r['bars']) for r in rows),
            'route_edges':     edges,
            'related_tree':    tree,
            'route_tree_ids':  sorted(line_ids_set),
            'request_id':      req.id,
            'request_name':    req.name or '',
            'is_proposal':     True,
        }

    def _board_working_intervals(self, calendar, start_aware, end_aware):
        """Intervalos laborables del calendario en [start_aware, end_aware],
        descontando feriados/licencias, como pares (start, end) en UTC naive.

        Usa resource.calendar._work_intervals_batch (misma fuente que
        get_work_hours_count(compute_leaves=True), que ya usa el % de ocupación,
        para que bandas, segmentos y ocupación sean coherentes). Las tuplas que
        devuelve son (start, end, record) — se toman los dos primeros. Se
        normaliza a UTC-aware (localize si viniera naive) antes de pasar a naive.

        Devuelve None si la API falla: NO se degrada en silencio a lista vacía,
        porque eso sería indistinguible de un CT 24x7. El llamador marca la fila
        con bands_failed y el cliente muestra un indicador; acá se loguea.
        """
        try:
            intervals = calendar._work_intervals_batch(start_aware, end_aware)[False]
        except Exception as e:
            _logger.warning(
                "Tablero: no se pudieron calcular las bandas laborables del "
                "calendario %s (id=%s): %s", calendar.display_name, calendar.id, e,
            )
            return None
        out = []
        for iv in intervals:
            s, e = iv[0], iv[1]
            if s.tzinfo is None:
                s = pytz.utc.localize(s)
            if e.tzinfo is None:
                e = pytz.utc.localize(e)
            out.append((
                s.astimezone(pytz.utc).replace(tzinfo=None),
                e.astimezone(pytz.utc).replace(tzinfo=None),
            ))
        return out

    @api.model
    def get_mo_components(self, mo_id):
        """Devuelve los componentes (movimientos de materia prima) de la OF."""
        mo = self.env['mrp.production'].browse(mo_id)
        if not mo.exists():
            return []
        result = []
        for move in mo.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            uom = move.product_uom.name if move.product_uom else ''
            result.append({
                'product_name': move.product_id.display_name if move.product_id else '',
                'qty':          move.product_uom_qty,
                'uom':          uom,
            })
        return result
