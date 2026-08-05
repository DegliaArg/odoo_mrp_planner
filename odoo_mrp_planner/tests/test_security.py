"""
Módulo: test_security.py
Tests: guards de seguridad del Sprint 1 del Planificador MRP

Cubre los guards implementados en:
- mrp.planner.dashboard.action_refresh          → group_prod | group_admin
- mrp.planner.dashboard.action_refresh_compras  → group_purchase | group_admin
- mrp.planner.dashboard.get_filtered_mos        → IDOR por warehouse_id
- mrp.planner.dashboard.get_customer_detail     → IDOR por partner_id
- mrp.reschedule.config.write                   → group_admin (módulo mrp_planner)
- mrp.forecast.import.wizard.action_download_template → group_sales | group_admin
"""
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError


@tagged('post_install', '-at_install', 'mrp_planner_security')
class TestMrpPlannerSecurity(TransactionCase):
    """Tests de seguridad para los guards del módulo odoo_mrp_planner."""

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _new_user(self, login, groups=None):
        """Crea un usuario interno mínimo con los grupos indicados.

        :param login: str — login único para el test.
        :param groups: list[str] — xmlids de grupos a asignar, p.ej.
                       ['odoo_mrp_planner.group_prod'].
        :returns: res.users record (con sudo ya aplicado para poder hacer write
                  en campos protegidos).
        """
        group_ids = []
        # Siempre se incluye base.group_user (usuario interno) para poder hacer login
        base_user_group = self.env.ref('base.group_user')
        group_ids.append((4, base_user_group.id))
        if groups:
            for xmlid in groups:
                grp = self.env.ref(xmlid, raise_if_not_found=False)
                if grp:
                    group_ids.append((4, grp.id))
        return self.env['res.users'].sudo().create({
            'name': f'Test User [{login}]',
            'login': login,
            'email': f'{login}@test.local',
            'groups_id': group_ids,
        })

    def _dashboard(self, user):
        """Retorna el modelo mrp.planner.dashboard en el contexto del usuario dado."""
        return self.env['mrp.planner.dashboard'].with_user(user)

    # ── Test 1: action_refresh requiere group_prod ────────────────────────────

    def test_action_refresh_requires_group(self):
        """Un usuario sin grupos del módulo no puede ejecutar action_refresh;
        con group_prod asignado la ejecución debe completarse sin error."""

        # Usuario sin ningún grupo del módulo
        user_no_group = self._new_user('test_refresh_no_group')

        # Crear el registro transitorio como superusuario para evitar que el
        # create() falle por falta de permiso antes de llegar al guard.
        dashboard_rec = self.env['mrp.planner.dashboard'].sudo().create({})

        with self.assertRaises(AccessError, msg="action_refresh debe lanzar AccessError sin group_prod"):
            dashboard_rec.with_user(user_no_group).action_refresh()

        # Ahora asignamos group_prod y volvemos a intentar
        group_prod = self.env.ref('odoo_mrp_planner.group_prod')
        user_no_group.sudo().write({'groups_id': [(4, group_prod.id)]})

        # No debe lanzar excepción (puede fallar por otras razones del cron, pero
        # el guard en sí no debe bloquear)
        try:
            dashboard_rec.with_user(user_no_group).action_refresh()
        except AccessError:
            self.fail("action_refresh lanzó AccessError con group_prod asignado")

    # ── Test 1b: action_refresh_compras requiere group_purchase ──────────────

    def test_action_refresh_compras_requires_group(self):
        """Un usuario sin group_purchase ni group_admin no puede ejecutar
        action_refresh_compras; con group_purchase asignado debe funcionar."""

        user_no_group = self._new_user('test_refresh_compras_no_group')
        dashboard_rec = self.env['mrp.planner.dashboard'].sudo().create({})

        with self.assertRaises(AccessError,
                               msg="action_refresh_compras debe lanzar AccessError sin group_purchase"):
            dashboard_rec.with_user(user_no_group).action_refresh_compras()

        group_purchase = self.env.ref('odoo_mrp_planner.group_purchase')
        user_no_group.sudo().write({'groups_id': [(4, group_purchase.id)]})

        try:
            dashboard_rec.with_user(user_no_group).action_refresh_compras()
        except AccessError:
            self.fail("action_refresh_compras lanzó AccessError con group_purchase asignado")

    # ── Test 2: get_filtered_mos bloquea IDOR por warehouse_id ───────────────

    def test_warehouse_idor_blocked(self):
        """Un usuario con acceso a warehouse A no puede consultar OFs del warehouse B.

        El guard en get_filtered_mos compara el warehouse_id enviado contra
        _get_allowed_wh_ids(). Si el warehouse solicitado no está en la lista
        permitida, debe lanzar AccessError.
        """
        # Buscar o crear dos almacenes de la misma empresa
        company = self.env.company
        warehouses = self.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=2
        )
        if len(warehouses) < 2:
            # Si solo hay un almacén creamos uno extra para el test
            wh_b = self.env['stock.warehouse'].sudo().create({
                'name': 'Test WH B',
                'code': 'TWHB',
                'company_id': company.id,
            })
            wh_a = warehouses[0]
        else:
            wh_a, wh_b = warehouses[0], warehouses[1]

        # Usuario restringido solo al warehouse A. Lleva también el grupo
        # NATIVO de Fabricación: lo que se prueba acá es el guard anti-IDOR
        # del dashboard, no el ACL de mrp.production (que el módulo no
        # modifica y en bases reales puede estar personalizado).
        user_restricted = self._new_user('test_idor_wh_restricted',
                                         groups=['odoo_mrp_planner.group_prod',
                                                 'mrp.group_mrp_user'])
        user_restricted.sudo().write({
            'mrp_planner_all_warehouses': False,
            'mrp_planner_warehouse_ids': [(6, 0, [wh_a.id])],
        })

        dashboard = self._dashboard(user_restricted)
        # Fecha mínima/máxima genérica para que no falle el parseo
        date_from = '2024-01-01'
        date_to   = '2024-12-31'

        # Intento de acceso al warehouse B → debe bloquear
        with self.assertRaises(AccessError,
                               msg="get_filtered_mos debe bloquear acceso a warehouse no permitido"):
            dashboard.get_filtered_mos(date_from, date_to, warehouse_id=wh_b.id)

        # Acceso al warehouse A → no debe bloquear (puede retornar lista vacía)
        try:
            result = dashboard.get_filtered_mos(date_from, date_to, warehouse_id=wh_a.id)
            self.assertIsInstance(result, list,
                                  "get_filtered_mos debe retornar una lista cuando el acceso es válido")
        except AccessError:
            self.fail("get_filtered_mos lanzó AccessError para el warehouse permitido")

    # ── Test 3: get_customer_detail bloquea IDOR por partner_id ──────────────

    def test_partner_idor_blocked(self):
        """Un usuario no puede obtener el detalle de un partner de otra empresa.

        El guard en get_customer_detail busca el partner con el filtro
        company_id in user.company_ids; si no lo encuentra lanza
        AccessError('Socio no encontrado o sin acceso').
        """
        company_own  = self.env.company
        # Crear una segunda empresa para aislar el partner externo
        company_other = self.env['res.company'].sudo().create({
            'name': 'Empresa Ajena Test',
        })

        # Partner que pertenece exclusivamente a la otra empresa
        partner_other = self.env['res.partner'].sudo().create({
            'name': 'Partner Empresa Ajena',
            'company_id': company_other.id,
        })

        # Partner de la empresa propia (sin company_id = visible a todos)
        partner_own = self.env['res.partner'].sudo().create({
            'name': 'Partner Empresa Propia',
            'company_id': False,  # global → visible en cualquier empresa
        })

        user = self._new_user('test_idor_partner',
                              groups=['odoo_mrp_planner.group_sales'])
        dashboard = self._dashboard(user)

        period_from = '2024-01-01'
        period_to   = '2024-12-31'

        # Partner de otra empresa → AccessError
        with self.assertRaises(AccessError,
                               msg="get_customer_detail debe bloquear partner de otra empresa"):
            dashboard.get_customer_detail(
                partner_id=partner_other.id,
                period_from=period_from,
                period_to=period_to,
            )

        # Partner accesible → no debe lanzar AccessError
        try:
            dashboard.get_customer_detail(
                partner_id=partner_own.id,
                period_from=period_from,
                period_to=period_to,
            )
        except AccessError:
            self.fail("get_customer_detail lanzó AccessError para un partner accesible")

    # ── Test 4: mrp.reschedule.config.write requiere administrador ────────────

    def test_config_write_requires_admin(self):
        """Un usuario sin ningún grupo del planificador no puede hacer write()
        en mrp.reschedule.config. Los administradores de área (group_prod,
        group_purchase_admin, etc.) y group_admin sí pueden, en línea con los
        permisos de escritura declarados en ir.model.access.csv.
        """
        # Crear el singleton de config si no existe
        config = self.env['mrp.reschedule.config'].sudo().search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not config:
            config = self.env['mrp.reschedule.config'].sudo().create({
                'company_id': self.env.company.id,
            })

        # Usuario interno sin grupos del planificador → debe fallar
        user_plain = self._new_user('test_config_write_plain', groups=[])

        with self.assertRaises(AccessError,
                               msg="config.write debe lanzar AccessError sin grupos del planificador"):
            config.with_user(user_plain).write({'alert_mo_critical_days': 5})

        # Usuario con group_prod (administrador de área) → debe poder escribir
        user_prod = self._new_user('test_config_write_prod',
                                   groups=['odoo_mrp_planner.group_prod'])

        try:
            config.with_user(user_prod).write({'alert_mo_critical_days': 5})
        except AccessError:
            self.fail("config.write no debería lanzar AccessError para group_prod")

        # Usuario con group_admin → debe poder escribir sin AccessError
        user_admin = self._new_user('test_config_write_admin',
                                    groups=['odoo_mrp_planner.group_admin'])

        try:
            config.with_user(user_admin).write({'alert_mo_critical_days': 5})
        except AccessError:
            self.fail("config.write no debería lanzar AccessError para group_admin")

    # ── Test 5: action_download_template requiere group_sales ─────────────────

    def test_forecast_download_requires_sales(self):
        """Un usuario sin group_sales ni group_admin no puede descargar la plantilla.

        El guard en action_download_template comprueba group_sales | group_admin
        antes de intentar importar openpyxl.
        """
        # Usuario sin group_sales ni group_admin
        user_no_sales = self._new_user('test_download_no_sales')

        wizard = self.env['mrp.forecast.import.wizard'].with_user(user_no_sales)

        with self.assertRaises(AccessError,
                               msg="action_download_template debe lanzar AccessError sin group_sales"):
            wizard.action_download_template()

        # Usuario con group_sales → el guard pasa; puede fallar por openpyxl ausente
        # (UserError), pero NO debe lanzar AccessError.
        user_sales = self._new_user('test_download_with_sales',
                                    groups=['odoo_mrp_planner.group_sales'])
        wizard_sales = self.env['mrp.forecast.import.wizard'].with_user(user_sales)

        try:
            wizard_sales.action_download_template()
        except AccessError:
            self.fail("action_download_template lanzó AccessError con group_sales asignado")
        except Exception:
            # UserError (openpyxl no disponible) u otros errores no de seguridad son aceptables
            pass
