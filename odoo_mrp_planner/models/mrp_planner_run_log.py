"""
Módulo: mrp_planner_run_log.py
Modelo: mrp.planner.run.log

Historial de ejecuciones de los procesos del planificador: asignación de
categorías (venta/proveedor/cliente), chequeo de alertas e importación de
forecast. Cada corrida —manual o por cron— deja una fila con su resultado.

Responsabilidades:
- Registrar cada ejecución con origen, usuario, resultado, métricas y duración.
- Conservar solo las últimas N corridas por proceso y empresa (configurable
  en Ajustes, default 100): la limpieza ocurre al insertar, sin cron extra.

Relacionado con:
- mrp.reschedule.config: run_log_keep define la retención; los procesos de
  categorías escriben aquí además de los campos "última corrida" de Ajustes.
- mrp.reschedule.alert: el cron de detección de desvíos registra cada pasada.
- mrp.forecast.import.wizard: cada importación registra líneas y advertencias.
"""
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

PROCESS_SELECTION = [
    ('sale_cat',        'Categorías de venta'),
    ('supplier_cat',    'Categorías de proveedor'),
    ('customer_cat',    'Categorías de cliente'),
    ('alerts_check',    'Chequeo de alertas'),
    ('forecast_import', 'Importación de forecast'),
]


class MrpPlannerRunLog(models.Model):
    _name = 'mrp.planner.run.log'
    _description = 'Registro de ejecuciones del planificador'
    _order = 'run_date desc, id desc'

    run_date = fields.Datetime(string='Fecha y hora', required=True,
                               default=fields.Datetime.now, index=True)
    process = fields.Selection(PROCESS_SELECTION, string='Proceso', required=True, index=True)
    trigger = fields.Selection([
        ('manual', 'Manual'),
        ('cron',   'Automático (cron)'),
    ], string='Origen', required=True, default='manual')
    user_id = fields.Many2one('res.users', string='Usuario', readonly=True,
                              help='Usuario que disparó la corrida. En las corridas por cron es el usuario del sistema.')
    company_id = fields.Many2one('res.company', string='Empresa', required=True, index=True,
                                 default=lambda self: self.env.company)
    status = fields.Selection([
        ('ok',    'OK'),
        ('error', 'Con error'),
    ], string='Resultado', required=True, default='ok')
    updated_count = fields.Integer(string='Registros actualizados',
                                   help='Registros que la corrida modificó (artículos recategorizados, líneas importadas, etc.).')
    duration = fields.Float(string='Duración (s)', digits=(12, 2))
    message = fields.Text(string='Detalle',
                          help='Resumen de la corrida, o el error completo cuando el resultado es "Con error".')

    @api.model
    def log_run(self, process, trigger='manual', status='ok', updated=0,
                duration=0.0, message=False, company=None):
        """Crea una fila del historial y aplica la retención configurada.

        Siempre con sudo(): el registro debe escribirse aunque quien dispara
        la corrida (cron o admin de área) no tenga permisos sobre este modelo,
        y especialmente cuando la corrida termina en error.

        :returns: mrp.planner.run.log — registro creado (sudo).
        """
        company = company or self.env.company
        rec = self.sudo().create({
            'process':       process,
            'trigger':       trigger,
            'status':        status,
            'updated_count': updated,
            'duration':      round(duration, 2),
            'message':       message or False,
            'user_id':       self.env.user.id,
            'company_id':    company.id,
        })
        try:
            cfg = self.env['mrp.reschedule.config'].sudo().with_company(company).get_config()
            keep = max(1, int(cfg.run_log_keep or 100)) if cfg else 100
            # _order deja lo más nuevo primero: todo lo que esté después de
            # las `keep` filas más recientes del proceso/empresa se purga.
            stale = self.sudo().search([
                ('process', '=', process),
                ('company_id', '=', company.id),
            ], offset=keep)
            if stale:
                stale.unlink()
        except Exception as e:
            _logger.warning('MRP Planner: no se pudo aplicar la retención del historial: %s', e)
        return rec

    @api.model
    def action_open_history(self):
        """Abre el historial de ejecuciones (lista de solo lectura)."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registro de ejecuciones',
            'res_model': 'mrp.planner.run.log',
            'view_mode': 'list,form',
            'context': {'create': False, 'edit': False},
            'target': 'current',
        }
