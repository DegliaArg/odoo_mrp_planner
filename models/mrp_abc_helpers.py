"""
Módulo: mrp_abc_helpers.py

Funciones auxiliares para clasificación ABC/Pareto. No dependen de ningún modelo
Odoo — se importan desde mrp_reschedule_config y mrp_partner_category sin crear
dependencias circulares entre ellos.
"""


def _abc_thresholds(config=None):
    """
    Devuelve los umbrales Pareto como fracciones (0–1) desde la configuración activa.

    Si no se pasa config (o sus campos están vacíos) se usan los valores por defecto
    20 % / 50 % / 80 % / 95 %, que representan los cortes clásicos de Pareto A/B/C/D/E.

    :param config: registro mrp.reschedule.config con abc_pct_a/b/c/d, o None.
    :returns: tuple (t_a, t_b, t_c, t_d) de float entre 0 y 1.
    """
    if config:
        return (
            (config.abc_pct_a or 20) / 100.0,
            (config.abc_pct_b or 50) / 100.0,
            (config.abc_pct_c or 80) / 100.0,
            (config.abc_pct_d or 95) / 100.0,
        )
    return (0.20, 0.50, 0.80, 0.95)


def _assign_abc_pareto(partners, value_by_id, field_name, thresholds=(0.20, 0.50, 0.80, 0.95)):
    """
    Clasifica registros A–E usando Pareto acumulado descendente (mayor valor = mejor categoría).

    Ordena los partners de mayor a menor valor, acumula el porcentaje sobre el total
    y asigna la categoría en el primer umbral superado. Partners sin valor → E.

    :param partners: recordset de los registros a clasificar.
    :param value_by_id: dict {partner_id: float} con la métrica a ordenar.
    :param field_name: nombre del campo Many2one/Selection donde se escribe la categoría.
    :param thresholds: tuple (t_a, t_b, t_c, t_d) de fracciones acumuladas para los cortes.
    """
    t_a, t_b, t_c, t_d = thresholds
    total = sum(value_by_id.get(p.id, 0.0) for p in partners)
    if total <= 0:
        for p in partners:
            p[field_name] = 'E'
        return
    sorted_p = sorted(partners, key=lambda p: value_by_id.get(p.id, 0.0), reverse=True)
    cumulative = 0.0
    for p in sorted_p:
        v = value_by_id.get(p.id, 0.0)
        if v <= 0:
            p[field_name] = 'E'
            continue
        cumulative += v / total
        if   cumulative <= t_a: cat = 'A'
        elif cumulative <= t_b: cat = 'B'
        elif cumulative <= t_c: cat = 'C'
        elif cumulative <= t_d: cat = 'D'
        else:                   cat = 'E'
        p[field_name] = cat


def _assign_abc_pareto_lower(partners, value_by_id, field_name, thresholds=(0.20, 0.50, 0.80, 0.95)):
    """
    Clasifica registros A–E donde un valor MENOR representa mejor desempeño (A = más bajo).

    Útil para métricas inversas como varianza de precio o cantidad de devoluciones,
    donde el proveedor más confiable tiene el número más bajo. Los partners sin dato → E.
    La clasificación se hace por posición relativa (percentil) en lugar de valor acumulado,
    ya que la escala puede ser arbitraria y no siempre tiene un "total" significativo.

    :param partners: recordset de los registros a clasificar.
    :param value_by_id: dict {partner_id: float | None} con la métrica (menor = mejor).
    :param field_name: nombre del campo donde se escribe la categoría.
    :param thresholds: tuple (t_a, t_b, t_c, t_d) de percentiles para los cortes.
    """
    t_a, t_b, t_c, t_d = thresholds
    with_val = [(p, value_by_id.get(p.id)) for p in partners]
    for p, v in with_val:
        if v is None:
            p[field_name] = 'E'
    has_val = sorted([(p, v) for p, v in with_val if v is not None], key=lambda x: x[1])
    n = len(has_val)
    for i, (p, _) in enumerate(has_val):
        pct = (i + 1) / n if n > 0 else 1.0
        if   pct <= t_a: cat = 'A'
        elif pct <= t_b: cat = 'B'
        elif pct <= t_c: cat = 'C'
        elif pct <= t_d: cat = 'D'
        else:            cat = 'E'
        p[field_name] = cat
