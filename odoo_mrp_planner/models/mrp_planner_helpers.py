"""
Módulo: mrp_planner_helpers.py

Utilidades compartidas del planificador, sin modelos propios.

Responsabilidades:
- Construir el dominio que excluye órdenes de fabricación subcontratadas
  (con caché por cursor de base de datos).
- Definir el mapa de sangría visual para jerarquías de BoM en vistas HTML.

Relacionado con:
- stock.location: consulta ubicaciones de subcontratación al armar el dominio.
- odoo_mrp_planner_scheduling: los mixins de programación importan estos
  helpers desde aquí.
"""
import weakref

_N = ' '  # non-breaking space — los espacios normales colapsan en HTML

# Cache de no_subcontract_domain por cursor (transacción).
# Las ubicaciones de subcontratación no cambian dentro de una misma transacción,
# por lo que es seguro reutilizar el resultado para evitar N queries en loops.
# Se indexa por id(env.cr) y se limpia automáticamente cuando el cursor es
# recolectado por el GC, previniendo memory leaks entre requests.
_no_subcontract_domain_cache: dict = {}


def _make_cache_cleanup(cr_id: int):
    """Retorna un callback de weakref que elimina la entrada del cache al liberar el cursor."""
    def _cleanup(_):
        _no_subcontract_domain_cache.pop(cr_id, None)
    return _cleanup


def no_subcontract_domain(env):
    """
    Construye un dominio que excluye órdenes de fabricación subcontratadas.

    Pre-carga los IDs de ubicaciones de subcontratación y usa 'not in' directo
    para evitar problemas de travesía relacional en search/search_count.
    Retorna una lista vacía cuando no existen ubicaciones de subcontratación
    para no penalizar el rendimiento de la consulta innecesariamente.

    El resultado se cachea por cursor de base de datos: dentro de la misma
    transacción se reutiliza sin ejecutar una nueva query SQL.

    :param env: entorno de Odoo (odoo.api.Environment).
    :returns: list — dominio de búsqueda compatible con ORM de Odoo.
    """
    cr_id = id(env.cr)
    if cr_id in _no_subcontract_domain_cache:
        return _no_subcontract_domain_cache[cr_id]

    sc_loc_ids = env['stock.location'].search(
        [('is_subcontracting_location', '=', True)]
    ).ids
    result = [] if not sc_loc_ids else [('location_src_id', 'not in', sc_loc_ids)]

    _no_subcontract_domain_cache[cr_id] = result
    try:
        weakref.finalize(env.cr, _make_cache_cleanup(cr_id))
    except TypeError:
        # env.cr no soporta weakref en algunos backends de test; ignorar
        pass

    return result


# Prefijos de sangría visual para jerarquías de BoM en vistas HTML.
# Se usa _N (espacio no separable) porque los espacios normales colapsan en HTML.
# Cada nivel agrega 3 caracteres _N antes del conector de árbol '└─ '.
INDENT_MAP = {
    0: '',
    1: '└─ ',
    2: f'{_N*3}└─ ',
    3: f'{_N*6}└─ ',
    4: f'{_N*9}└─ ',
    5: f'{_N*12}└─ ',
}
