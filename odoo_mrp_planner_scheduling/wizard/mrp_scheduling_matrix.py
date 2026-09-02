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
import re
from datetime import datetime, timedelta

import pytz

from odoo import models, api

from ..models.mrp_reschedule_cascade_mixin import (
    _get_old_code, _origin_tokens, _search_by_origin,
)

_logger = logging.getLogger(__name__)

# Sufijo de parcial en el nombre de una OF: '-NNN' al final ('VL/MO/03365-013').
_PARTIAL_SUFFIX = re.compile(r'-\d+$')


def _base_name(name):
    """Nombre BASE de una OF, sin el sufijo de parcial '-NNN'.

    Los parciales (MO partida) se nombran 'XX/MO/NNNNN-PPP', pero el campo
    `origin` cita el nombre base 'XX/MO/NNNNN'. Para reconstruir la cadena hay
    que matchear por base: 'VL/MO/03365-013' → 'VL/MO/03365'; 'CP/MO/04069' se
    deja igual.
    """
    return _PARTIAL_SUFFIX.sub('', name or '')


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
                # igual debe aparecer en el escalonado. Se ubica por las fechas de la
                # MO en cada centro de su ruta.
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
            laborable. Un día que no está acá es un día COMPLETO no laborable."""
            if cal.id not in wd_cache:
                dates = set()
                for ws, we in (ivs or []):
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
                # Sin working_dates (bandas no calculables) → no se parte: continua.
                if not working_dates or d in working_dates:
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
            wdates = _working_dates(cal, ivs) if cal else set()

            # Barra continua, partida solo por día completo no laborable. La
            # ocupación prorratea la duración de las WO al rango cargado y EXCLUYE
            # las terminadas (son historial, no compiten por capacidad).
            planned_min = 0.0
            for bar in bars:
                ds = bar.pop('_ds')
                df = bar.pop('_df')
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
        """Ruta de una OF: sus work orders con CT activo, ordenadas por sequence,
        como lista [(workcenter, posición)] sin repetir CT.

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
        route = []
        seen = set()
        wos = mo.workorder_ids.filtered(
            lambda w: w.workcenter_id and w.workcenter_id.active
        ).sorted('sequence')
        for wo in wos:
            wc = wo.workcenter_id
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

        # Ancestros: seguir origin hacia arriba (puede ser compuesto → varios
        # padres). Los parciales citan el nombre BASE en origin ('CP/MO/04069')
        # pero el padre real está partido ('CP/MO/04069-001/-002'): se matchea por
        # base (name = tok, o name = base, o name like base-%).
        ancestors, frontier, depth = [], [mo], 0
        while frontier and depth < max_depth and len(seen) < MAX_NODES:
            nxt = []
            for cur in frontier:
                for tok in _origin_tokens(cur.origin):
                    btok = _base_name(tok)
                    parents = Prod.search([
                        '|', '|', ('name', '=', tok),
                        ('name', '=', btok), ('name', '=like', btok + '-%'),
                    ] + act)
                    for p in parents:
                        if p.id not in seen:
                            seen.add(p.id)
                            ancestors.append((depth + 1, p))
                            nxt.append(p)
            frontier, depth = nxt, depth + 1

        # Descendientes: OFs cuyo origin cita el nombre BASE (recursivo por nivel).
        # Se busca por base para captar OFs enteras y parciales por igual.
        descendants, seen_d, names, depth = [], set(seen), [_base_name(mo.name)], 0
        while names and depth < max_depth and len(seen_d) < MAX_NODES:
            matches = _search_by_origin(self.env, 'mrp.production', names, act)
            nxt = []
            for name in names:
                for child in matches.get(name, Prod):
                    if child.id not in seen_d:
                        seen_d.add(child.id)
                        descendants.append((depth, child))
                        nxt.append(_base_name(child.name))
            names, depth = nxt, depth + 1

        items = [_info(m, 'descendant', lvl) for lvl, m in sorted(descendants, key=lambda x: -x[0])]
        items.append(_info(mo, 'self', 0))
        items += [_info(m, 'ancestor', lvl) for lvl, m in sorted(ancestors, key=lambda x: x[0])]
        return items, {i['mo_id'] for i in items}

    @api.model
    def get_route_board(self, mo_id, include_done=True, states=None):
        """Modo ruta: el tablero enfocado en los CTs por los que pasa una OF.

        Devuelve las filas SOLO de esos CTs, ordenadas por secuencia de operación
        (no alfabéticamente), con TODAS las OFs de esos centros en un rango que
        abarca la ruta completa + margen. El cliente pinta en color pleno las
        barras de la OF (bar.mo_id == route_mo_id) y atenúa el resto.
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
        tree, tree_ids = self._compute_related_tree(mo, states=states)
        tree_mos = self.env['mrp.production'].browse(sorted(tree_ids))

        # El Gantt abarca los CTs y el rango de TODO el árbol (no solo la OF
        # enfocada), para ver las OFs relacionadas ubicadas en el tiempo.
        all_wc_ids = set()
        dts = []
        for tm in tree_mos:
            all_wc_ids.update(wc.id for wc, _seq in self._compute_route(tm))
            dts += [w.date_start for w in tm.workorder_ids if w.date_start]
            dts += [w.date_finished for w in tm.workorder_ids if w.date_finished]
            dts += [d for d in (tm.date_start, tm.date_finished) if d]
        if not dts:
            return {'empty_reason': 'no_dates', 'route_mo_name': mo.name}
        lo = pytz.utc.localize(min(dts)).astimezone(tz).date() - timedelta(days=1)
        hi = pytz.utc.localize(max(dts)).astimezone(tz).date() + timedelta(days=1)

        # force_wc_ids: los CTs del árbol aparecen como fila aunque sus WOs no
        # estén programadas (date_start vacío).
        payload = self._build_board_payload(
            all_wc_ids, lo.strftime('%Y-%m-%d'), hi.strftime('%Y-%m-%d'), include_done,
            force_wc_ids=all_wc_ids, only_mo_ids=tree_ids, states=states,
        )

        # Orden de filas = orden del escalonado (cronológico por la barra más
        # temprana de cada CT), para que coincida con el orden del panel lateral
        # (hijas antes → padres después). Empate/CT sin barras: por nombre.
        seq_by_wc = {wc.id: seq for wc, seq in route}
        rows = [r for r in payload['rows'] if not r.get('is_unassigned')]

        def _row_min_start(r):
            starts = [b['date_start'] for b in r.get('bars', []) if b.get('date_start')]
            return (min(starts) if starts else '9999', r['wc_name'])

        rows.sort(key=_row_min_start)
        for r in rows:
            r['route_seq'] = seq_by_wc.get(r['wc_id'])
        payload['rows'] = rows

        # Aristas de la cadena (para el hilo conector): cada OF apunta, por su
        # origin, a la OF que consume su producto. Solo aristas entre nodos del
        # árbol. from = componente (hija) → to = consumidora (padre).
        name_to_id = {tm.name: tm.id for tm in tree_mos}
        edges = []
        for tm in tree_mos:
            for tok in _origin_tokens(tm.origin):
                pid = name_to_id.get(tok)
                if pid and pid != tm.id:
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
        })
        return payload

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
