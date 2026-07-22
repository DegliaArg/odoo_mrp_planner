"""
Tests para mrp.planner.dashboard y sus KPIs.

Cobertura:
- test_dashboard_opens_without_error: el dashboard se instancia sin excepciones y
  expone campos Integer/Boolean con valores válidos (no None).
- test_alert_kpis_count_correctly: _compute_alert_stats cuenta alertas por tipo y
  respeta el flag resolved al bajar contadores.
- test_warehouse_filter_applied: get_filtered_mos respeta el filtro por warehouse_id
  y no mezcla OFs de depósitos distintos.
- test_mo_stats_no_full_load: _compute_mo_stats produce contadores coherentes
  (mo_in_progress + otros <= mo_total) con cinco OFs en distintos estados.
"""
from datetime import datetime, timedelta

from odoo.tests import tagged, TransactionCase
from odoo.exceptions import AccessError


@tagged("post_install", "-at_install")
class TestMrpPlannerDashboard(TransactionCase):
    """Suite de tests para el panel de control del planificador MRP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Producto y BOM mínimos reutilizados por varios tests.
        cls.product = cls.env["product.product"].create({
            "name": "Producto Test Dashboard",
            "type": "consu",
        })
        # Depósito principal de la empresa activa (siempre existe en Odoo).
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        # Tipo de operación de fabricación del depósito principal.
        cls.mfg_type = cls.env["stock.picking.type"].search([
            ("code", "=", "mrpoperation"),
            ("warehouse_id", "=", cls.warehouse.id),
        ], limit=1)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _new_dashboard(self):
        """Crea y devuelve un registro transitorio del dashboard."""
        return self.env["mrp.planner.dashboard"].create({})

    def _make_alert(self, alert_type, severity, resolved=False):
        """Crea una alerta mínima de prueba."""
        return self.env["mrp.reschedule.alert"].create({
            "alert_type": alert_type,
            "severity": severity,
            "resolved": resolved,
            "company_id": self.env.company.id,
        })

    def _make_mo(self, state, date_finished=None, reschedule_needed=False):
        """
        Crea una OF mínima con estado y campos de planificación dados.

        Para OFs en estado 'confirmed' o 'progress' que necesitan una fecha de
        finalización pasada (delayed), se crea primero en borrador y luego se fuerza
        el estado con write() para evitar validaciones de flujo del botón confirm.
        """
        vals = {
            "product_id": self.product.id,
            "product_qty": 1.0,
            "company_id": self.env.company.id,
        }
        if self.mfg_type:
            vals["picking_type_id"] = self.mfg_type.id

        mo = self.env["mrp.production"].create(vals)

        write_vals = {"x_reschedule_needed": reschedule_needed}
        if date_finished:
            write_vals["date_finished"] = date_finished
        if state != "draft":
            write_vals["state"] = state
        if write_vals:
            mo.write(write_vals)
        return mo

    # ── Test 1: el dashboard abre sin errores ─────────────────────────────────

    def test_dashboard_opens_without_error(self):
        """
        El dashboard se crea sin lanzar excepciones y los KPIs enteros son >= 0.

        Verifica que:
        - create({}) no falla para el usuario actual (base.group_user).
        - Todos los campos Integer de alertas y OFs son no-None y >= 0.
        - Todos los campos Boolean de permisos son non-None.
        """
        # Arrange / Act
        dash = self._new_dashboard()

        # Assert — campos Integer de alertas: nunca deben ser None ni negativos
        integer_alert_fields = [
            "alert_total", "alert_critical", "alert_warning",
            "alert_mo_delayed", "alert_mo_upcoming",
            "alert_po_delayed", "alert_po_upcoming",
            "alert_po_cancelled", "alert_receipt_delayed",
            "alert_qty_mismatch", "alert_mo_cancelled",
        ]
        for fname in integer_alert_fields:
            val = getattr(dash, fname)
            self.assertIsNotNone(val, f"{fname} no debe ser None")
            self.assertGreaterEqual(val, 0, f"{fname} debe ser >= 0")

        # Assert — campos Integer de OFs
        integer_mo_fields = [
            "mo_total", "mo_in_progress", "mo_done",
            "mo_delayed", "mo_reschedule_needed",
        ]
        for fname in integer_mo_fields:
            val = getattr(dash, fname)
            self.assertIsNotNone(val, f"{fname} no debe ser None")
            self.assertGreaterEqual(val, 0, f"{fname} debe ser >= 0")

        # Assert — campos Boolean de permisos: deben ser explícitamente True o False
        bool_perm_fields = [
            "can_see_alerts", "can_see_mo", "can_see_po",
            "can_see_stock_breaks", "can_see_forecast",
            "can_schedule", "can_reschedule", "can_edit_forecast",
        ]
        for fname in bool_perm_fields:
            val = getattr(dash, fname)
            self.assertIsNotNone(val, f"{fname} no debe ser None")
            self.assertIn(val, (True, False), f"{fname} debe ser True o False")

    # ── Test 2: contadores de alertas por tipo y severidad ─────────────────────

    def test_alert_kpis_count_correctly(self):
        """
        _compute_alert_stats agrega correctamente alertas por tipo y las descuenta
        cuando se marcan como resueltas.

        Escenario:
        - 2 alertas mo_delayed / critical  (sin resolver)
        - 1 alerta  po_delayed / warning   (sin resolver)
        → alert_mo_delayed == 2, alert_po_delayed == 1, alert_total == 3
        → Resolver una mo_delayed → alert_mo_delayed == 1, alert_total == 2
        """
        # Arrange: limpiar alertas previas de la empresa para conteo limpio
        self.env["mrp.reschedule.alert"].search([
            ("company_id", "=", self.env.company.id),
            ("resolved", "=", False),
        ]).write({"resolved": True})

        alert_mo1 = self._make_alert("mo_delayed", "critical")
        alert_mo2 = self._make_alert("mo_delayed", "critical")
        self._make_alert("po_delayed", "warning")

        # Act
        dash = self._new_dashboard()

        # Assert — conteos iniciales
        self.assertEqual(
            dash.alert_mo_delayed, 2,
            "Deben contarse exactamente 2 alertas mo_delayed sin resolver"
        )
        self.assertEqual(
            dash.alert_po_delayed, 1,
            "Debe contarse exactamente 1 alerta po_delayed sin resolver"
        )
        self.assertEqual(
            dash.alert_total, 3,
            "El total debe ser la suma de todas las alertas sin resolver (3)"
        )
        self.assertEqual(
            dash.alert_critical, 2,
            "Deben contarse 2 alertas críticas"
        )
        self.assertEqual(
            dash.alert_warning, 1,
            "Debe contarse 1 alerta de aviso"
        )

        # Act — resolver una alerta mo_delayed
        alert_mo1.write({"resolved": True})
        dash2 = self._new_dashboard()

        # Assert — conteos tras resolver
        self.assertEqual(
            dash2.alert_mo_delayed, 1,
            "Tras resolver una alerta mo_delayed debe quedar solo 1"
        )
        self.assertEqual(
            dash2.alert_total, 2,
            "El total debe bajar a 2 tras resolver una alerta"
        )

        # Resolver la segunda mo_delayed también
        alert_mo2.write({"resolved": True})
        dash3 = self._new_dashboard()
        self.assertEqual(dash3.alert_mo_delayed, 0)
        self.assertEqual(dash3.alert_total, 1)

    # ── Test 3: filtro por warehouse en get_filtered_mos ──────────────────────

    def test_warehouse_filter_applied(self):
        """
        get_filtered_mos con warehouse_id solo retorna OFs del depósito solicitado.

        Escenario:
        - Depósito A: warehouse principal de la empresa.
        - Depósito B: depósito secundario creado ad-hoc.
        - Se crean OFs en cada depósito con fechas que solapan con el rango del test.
        - Filtrando por warehouse A no deben aparecer OFs del warehouse B.
        - Filtrando por warehouse B no deben aparecer OFs del warehouse A.
        """
        # Depósito secundario — Odoo crea automáticamente sus picking types.
        wh_b = self.env["stock.warehouse"].create({
            "name": "Depósito Test B",
            "code": "TSTB",
            "company_id": self.env.company.id,
        })
        mfg_type_b = self.env["stock.picking.type"].search([
            ("code", "=", "mrpoperation"),
            ("warehouse_id", "=", wh_b.id),
        ], limit=1)

        today = datetime.now()
        date_from = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        date_to = (today + timedelta(days=7)).strftime("%Y-%m-%d")

        # OF en depósito A
        mo_a = self.env["mrp.production"].create({
            "product_id": self.product.id,
            "product_qty": 1.0,
            "picking_type_id": self.mfg_type.id,
            "date_start": today,
            "date_finished": today + timedelta(days=3),
            "company_id": self.env.company.id,
        })

        # OF en depósito B — solo si se pudo obtener el picking type
        mo_b = None
        if mfg_type_b:
            mo_b = self.env["mrp.production"].create({
                "product_id": self.product.id,
                "product_qty": 1.0,
                "picking_type_id": mfg_type_b.id,
                "date_start": today,
                "date_finished": today + timedelta(days=3),
                "company_id": self.env.company.id,
            })

        dash = self._new_dashboard()

        # Asegurarse que el usuario puede ver todos los depósitos (sin restricción)
        self.env.user.write({"mrp_planner_all_warehouses": True})

        # Filtrar por depósito A
        result_a = dash.get_filtered_mos(date_from, date_to, warehouse_id=self.warehouse.id)
        ids_a = [r["id"] for r in result_a]

        self.assertIn(
            mo_a.id, ids_a,
            "La OF del depósito A debe aparecer al filtrar por depósito A"
        )
        if mo_b:
            self.assertNotIn(
                mo_b.id, ids_a,
                "La OF del depósito B NO debe aparecer al filtrar por depósito A"
            )

        # Filtrar por depósito B (solo si existe)
        if mo_b and mfg_type_b:
            result_b = dash.get_filtered_mos(date_from, date_to, warehouse_id=wh_b.id)
            ids_b = [r["id"] for r in result_b]
            self.assertIn(
                mo_b.id, ids_b,
                "La OF del depósito B debe aparecer al filtrar por depósito B"
            )
            self.assertNotIn(
                mo_a.id, ids_b,
                "La OF del depósito A NO debe aparecer al filtrar por depósito B"
            )

    # ── Test 4: contadores de OFs son coherentes entre sí ──────────────────────

    def test_mo_stats_no_full_load(self):
        """
        _compute_mo_stats produce contadores coherentes con 5 OFs en distintos estados.

        Invariantes verificadas:
        - mo_in_progress <= mo_total  (los en progreso son un subconjunto del total)
        - mo_delayed <= mo_total      (los atrasados son un subconjunto del total)
        - mo_reschedule_needed >= 0
        - mo_done >= 0 (las OFs done no forman parte de mo_total por definición)
        - mo_total >= 2               (al menos las 2 OFs activas que creamos)
        - mo_delayed >= 1             (al menos la OF atrasada que creamos)
        - mo_in_progress >= 1         (al menos la OF en progreso que creamos)

        Escenario: se crean 5 OFs con estados variados para poblar la base.
        """
        # Limpiar estado previo resolviendo alertas abiertas para no interferir
        # con el dominio active. No es necesario borrar OFs existentes.

        now = datetime.now()
        past = now - timedelta(days=5)
        future = now + timedelta(days=10)

        # OF confirmada con fecha de fin pasada → debe sumarse a mo_delayed
        mo_delayed = self._make_mo("confirmed", date_finished=past)
        # OF en progreso con fecha futura → suma a mo_in_progress y mo_total
        mo_in_prog = self._make_mo("progress", date_finished=future)
        # OF en to_close → suma a mo_in_progress y mo_total
        mo_to_close = self._make_mo("to_close", date_finished=future)
        # OF marcada para reprogramar
        mo_reschedule = self._make_mo("confirmed", reschedule_needed=True)
        # OF done → suma solo a mo_done, NO a mo_total
        mo_done = self._make_mo("done")

        # Act
        dash = self._new_dashboard()

        # Assert — invariantes de coherencia
        self.assertGreaterEqual(
            dash.mo_total, 2,
            "mo_total debe incluir al menos las OFs activas creadas en este test"
        )
        self.assertGreaterEqual(
            dash.mo_in_progress, 1,
            "mo_in_progress debe incluir al menos la OF en estado 'progress'"
        )
        self.assertLessEqual(
            dash.mo_in_progress, dash.mo_total,
            "mo_in_progress no puede superar mo_total"
        )
        self.assertGreaterEqual(
            dash.mo_delayed, 1,
            "mo_delayed debe incluir al menos la OF con fecha_fin pasada"
        )
        self.assertLessEqual(
            dash.mo_delayed, dash.mo_total,
            "mo_delayed no puede superar mo_total"
        )
        self.assertGreaterEqual(
            dash.mo_reschedule_needed, 1,
            "mo_reschedule_needed debe incluir al menos la OF marcada x_reschedule_needed=True"
        )
        self.assertGreaterEqual(
            dash.mo_done, 1,
            "mo_done debe incluir al menos la OF en estado done"
        )
        # Las OFs done NO deben contarse en mo_total
        # (mo_total excluye done/cancel/draft según la implementación)
        # No podemos asegurar la igualdad exacta porque existen OFs previas en la BD,
        # pero sí que mo_in_progress <= mo_total
        self.assertLessEqual(
            dash.mo_in_progress, dash.mo_total,
            "mo_in_progress siempre debe ser <= mo_total"
        )

    # ── Test 5 (bonus): AccessError en action_refresh sin permisos ─────────────

    def test_action_refresh_raises_access_error_without_group(self):
        """
        action_refresh lanza AccessError cuando el usuario no tiene
        group_prod ni group_admin del módulo.
        """
        # Crear usuario sin grupos del módulo
        user_no_perms = self.env["res.users"].create({
            "name": "Usuario Sin Permisos",
            "login": "test_no_perms_dashboard@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        dash = self._new_dashboard()
        with self.assertRaises(AccessError):
            dash.with_user(user_no_perms).action_refresh()

    def test_action_refresh_compras_raises_access_error_without_group(self):
        """
        action_refresh_compras lanza AccessError cuando el usuario no tiene
        group_purchase ni group_admin del módulo.
        """
        user_no_perms = self.env["res.users"].create({
            "name": "Usuario Sin Permisos Compras",
            "login": "test_no_perms_compras@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        dash = self._new_dashboard()
        with self.assertRaises(AccessError):
            dash.with_user(user_no_perms).action_refresh_compras()
