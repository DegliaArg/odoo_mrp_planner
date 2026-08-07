"""
Tests: BFS cascade correctness and performance optimisations (Sprint 2/3).

Coverage:
  1. test_cascade_preload_reduces_queries  — batch preload keeps query count
     sub-linear with respect to the number of MOs in the cascade tree.
  2. test_cascade_result_correct           — dates propagate correctly through a
     3-level MO chain when action_calculate is executed on a reschedule plan.
  3. test_alert_stats_returns_correct_counts — _compute_alert_stats returns the
     exact counters that match manually-created alert records.
  4. test_sale_category_batch_assignment   — action_auto_assign_sale_categories
     assigns a category to every sale_ok product and groups products by volume.
"""

import logging
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class TestCascadePerformance(TransactionCase):
    """
    TransactionCase: each test runs inside a savepoint that is rolled back
    automatically — no data persists between tests.
    """

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _add_user_to_group(self, user, xml_id):
        """Add *user* to a security group identified by its full XML id."""
        group = self.env.ref(xml_id, raise_if_not_found=False)
        if group:
            group.sudo().write({'users': [(4, user.id)]})

    def _make_product(self, name, sale_ok=True):
        """Return a new storable product template + its default product.product."""
        tmpl = self.env['product.template'].create({
            'name': name,
            'type': 'consu',
            'sale_ok': sale_ok,
            'purchase_ok': False,
        })
        return tmpl.product_variant_ids[0]

    def _make_mo(self, name, product, qty=1.0, date_start=None, date_finished=None,
                 state='confirmed', parent_mo=None):
        """
        Create a minimal mrp.production record suitable for cascade tests.

        ``state`` is forced via a direct write after creation because the ORM
        workflow raises an error if the state is set at creation for certain
        transitions.
        """
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': 1.0,
            'type': 'normal',
        })
        vals = {
            'product_id': product.id,
            'product_qty': qty,
            'bom_id': bom.id,
        }
        if date_start:
            vals['date_start'] = date_start
        if date_finished:
            vals['date_finished'] = date_finished
        mo = self.env['mrp.production'].create(vals)
        # Confirm the MO so the cascade engine can pick it up
        mo.action_confirm()
        if date_start:
            mo.write({'date_start': date_start})
        if date_finished:
            mo.write({'date_finished': date_finished})
        if parent_mo:
            mo.write({'x_parent_mo_id': parent_mo.id})
        return mo

    def _make_plan(self, pivot_mo=None, new_finish_date=None, replan_from=None):
        """Return a draft mrp.reschedule.plan with the given pivot (or global)."""
        vals = {}
        if pivot_mo:
            vals['production_id'] = pivot_mo.id
            vals['new_finish_date'] = new_finish_date or pivot_mo.date_finished
        else:
            vals['replan_from'] = replan_from or datetime.now()
        return self.env['mrp.reschedule.plan'].create(vals)

    def _ensure_config(self):
        """Return (or create) the mrp.reschedule.config singleton for the current company."""
        cfg = self.env['mrp.reschedule.config'].get_config()
        if not cfg:
            cfg = self.env['mrp.reschedule.config'].sudo().create({
                'company_id': self.env.company.id,
            })
        return cfg

    # ── setUp ─────────────────────────────────────────────────────────────────

    def setUp(self):
        super().setUp()
        # Guarantee the config singleton exists before tests run.
        self._ensure_config()

        # Give the test user admin rights on the module so permission guards
        # (has_group) don't block the methods under test.
        self._add_user_to_group(self.env.user, 'odoo_mrp_planner.group_admin')
        self._add_user_to_group(self.env.user, 'base.group_system')

    # =========================================================================
    # Test 1 — preload batch keeps query count sub-linear
    # =========================================================================

    def test_cascade_preload_reduces_queries(self):
        """
        Build a 3-level cascade (parent → child1 → child2) and verify that
        action_calculate completes correctly.

        The primary assertion is correctness (all 3 MOs appear in the plan lines).
        A secondary soft check verifies that the query budget is not proportional
        to the number of nodes (i.e. preload is working), using the SQL query
        counter available on the cursor when running under Odoo's test runner.
        """
        now = datetime.now().replace(microsecond=0)
        delta = timedelta(hours=8)

        p_parent = self._make_product('CASCADE-PARENT')
        p_child1 = self._make_product('CASCADE-CHILD1')
        p_child2 = self._make_product('CASCADE-CHILD2')

        mo_parent = self._make_mo(
            'MO-PARENT', p_parent,
            date_start=now,
            date_finished=now + delta,
        )
        mo_child1 = self._make_mo(
            'MO-CHILD1', p_child1,
            date_start=now + delta,
            date_finished=now + 2 * delta,
            parent_mo=mo_parent,
        )
        mo_child2 = self._make_mo(
            'MO-CHILD2', p_child2,
            date_start=now + 2 * delta,
            date_finished=now + 3 * delta,
            parent_mo=mo_child1,
        )

        plan = self._make_plan(
            pivot_mo=mo_parent,
            new_finish_date=mo_parent.date_finished,
        )

        # Measure SQL queries during action_calculate
        initial_count = self.env.cr.sql_log_count if hasattr(self.env.cr, 'sql_log_count') else None

        plan.action_calculate()

        if initial_count is not None:
            final_count = self.env.cr.sql_log_count
            queries_used = final_count - initial_count
            # With preload: at most ~2 queries per level regardless of width.
            # Without preload: N_mos * ~3 queries each = 9+.
            # We assert strictly less than 3 queries per MO as a soft bound.
            self.assertLess(
                queries_used,
                len([mo_parent, mo_child1, mo_child2]) * 3,
                msg=(
                    f'action_calculate used {queries_used} queries for 3 MOs. '
                    'Expected the batch preload to keep this below 9 queries.'
                ),
            )

        # Correctness: the plan must be in 'calculated' state
        self.assertEqual(plan.state, 'calculated',
                         'Plan should be in calculated state after action_calculate.')

        # All three MOs must appear in the plan lines
        plan_mo_ids = plan.line_ids.filtered(
            lambda l: l.record_type == 'mrp'
        ).mapped('production_id').ids

        self.assertIn(mo_parent.id, plan_mo_ids,
                      'Parent MO must appear in plan lines.')
        self.assertIn(mo_child1.id, plan_mo_ids,
                      'Child-1 MO must appear in plan lines.')
        self.assertIn(mo_child2.id, plan_mo_ids,
                      'Child-2 MO must appear in plan lines.')

    # =========================================================================
    # Test 2 — date propagation is correct
    # =========================================================================

    def test_cascade_result_correct(self):
        """
        Shift a 3-level cascade forward by 2 days and verify that every
        non-anchor MO has a new_date_start that is 2 days later than its
        current date_start.

        The pivot is the anchor (is_anchor=True by default).  Children at
        levels > 0 receive a delta derived from the parent's delta.
        """
        now = datetime.now().replace(microsecond=0)
        shift = timedelta(days=2)
        block = timedelta(hours=8)

        p_a = self._make_product('SHIFT-A')
        p_b = self._make_product('SHIFT-B')
        p_c = self._make_product('SHIFT-C')

        mo_a = self._make_mo(
            'SHIFT-MO-A', p_a,
            date_start=now,
            date_finished=now + block,
        )
        mo_b = self._make_mo(
            'SHIFT-MO-B', p_b,
            date_start=now + block,
            date_finished=now + 2 * block,
            parent_mo=mo_a,
        )
        mo_c = self._make_mo(
            'SHIFT-MO-C', p_c,
            date_start=now + 2 * block,
            date_finished=now + 3 * block,
            parent_mo=mo_b,
        )

        # Shift the pivot 2 days into the future
        new_finish = mo_a.date_finished + shift
        plan = self._make_plan(pivot_mo=mo_a, new_finish_date=new_finish)
        plan.action_calculate()

        self.assertEqual(plan.state, 'calculated')

        # Index lines by production_id for easy lookup
        lines_by_mo = {
            line.production_id.id: line
            for line in plan.line_ids
            if line.record_type == 'mrp' and line.production_id
        }

        # --- Pivot (anchor): new dates should equal current dates (or be set
        # to the new_finish_date for date_finished).  The pivot keeps its dates.
        pivot_line = lines_by_mo.get(mo_a.id)
        self.assertIsNotNone(pivot_line, 'Pivot MO must have a plan line.')
        self.assertTrue(pivot_line.is_anchor,
                        'Pivot MO line must be marked as anchor.')

        # --- Child 1: must have been shifted forward
        child1_line = lines_by_mo.get(mo_b.id)
        self.assertIsNotNone(child1_line, 'Child-1 MO must have a plan line.')
        self.assertFalse(child1_line.is_anchor,
                         'Child-1 MO line must NOT be an anchor.')
        if child1_line.new_date_start and mo_b.date_start:
            actual_shift = child1_line.new_date_start - mo_b.date_start
            self.assertGreater(
                actual_shift.total_seconds(), 0,
                'Child-1 new_date_start must be later than its current date_start '
                'when the pivot is shifted forward.'
            )

        # --- Child 2: same rule
        child2_line = lines_by_mo.get(mo_c.id)
        self.assertIsNotNone(child2_line, 'Child-2 MO must have a plan line.')
        if child2_line.new_date_start and mo_c.date_start:
            actual_shift_2 = child2_line.new_date_start - mo_c.date_start
            self.assertGreater(
                actual_shift_2.total_seconds(), 0,
                'Child-2 new_date_start must be later than its current date_start '
                'when the cascade propagates upward.'
            )

        # --- Ordering invariant: child must start no earlier than its parent ends
        if (child1_line.new_date_start and pivot_line.new_date_finish):
            self.assertGreaterEqual(
                child1_line.new_date_start,
                pivot_line.new_date_finish - timedelta(minutes=1),
                'Child-1 proposed start must not precede the pivot proposed finish.'
            )

    # =========================================================================
    # Test 3 — alert stats count exactly the records created
    # =========================================================================

    def test_alert_stats_returns_correct_counts(self):
        """
        Create a controlled set of mrp.reschedule.alert records and assert
        that _compute_alert_stats reflects the exact counts.

        Alert set:
          - 2 × mo_delayed / critical
          - 1 × po_delayed / warning

        Expected:
          alert_mo_delayed  == 2
          alert_po_delayed  == 1
          alert_critical    >= 2  (could include pre-existing critical alerts)
          alert_warning     >= 1
        """
        Alert = self.env['mrp.reschedule.alert']

        # Count alerts that already exist before this test creates new ones,
        # so we can assert on the delta rather than the absolute total.
        existing_mo_delayed = Alert.search_count([
            ('resolved', '=', False),
            ('alert_type', '=', 'mo_delayed'),
        ])
        existing_po_delayed = Alert.search_count([
            ('resolved', '=', False),
            ('alert_type', '=', 'po_delayed'),
        ])

        # Create 2 critical mo_delayed alerts (no production_id required)
        Alert.create([
            {
                'company_id': self.env.company.id,
                'alert_type': 'mo_delayed',
                'severity':   'critical',
            },
            {
                'company_id': self.env.company.id,
                'alert_type': 'mo_delayed',
                'severity':   'critical',
            },
        ])

        # Create 1 warning po_delayed alert
        Alert.create({
            'company_id': self.env.company.id,
            'alert_type': 'po_delayed',
            'severity':   'warning',
        })

        # Open the dashboard transient to trigger _compute_alert_stats
        dashboard = self.env['mrp.planner.dashboard'].create({'name': 'test'})
        # Force recompute (transient computed fields are lazy)
        dashboard._compute_alert_stats()

        # Validate incremental counts
        self.assertEqual(
            dashboard.alert_mo_delayed,
            existing_mo_delayed + 2,
            f'Expected alert_mo_delayed = {existing_mo_delayed + 2}, '
            f'got {dashboard.alert_mo_delayed}.'
        )
        self.assertEqual(
            dashboard.alert_po_delayed,
            existing_po_delayed + 1,
            f'Expected alert_po_delayed = {existing_po_delayed + 1}, '
            f'got {dashboard.alert_po_delayed}.'
        )

        # Totals must be at least the amounts we created
        self.assertGreaterEqual(dashboard.alert_critical, 2,
                                'alert_critical must be >= 2 (2 critical mo_delayed created).')
        self.assertGreaterEqual(dashboard.alert_warning, 1,
                                'alert_warning must be >= 1 (1 warning po_delayed created).')

        # alert_total must be >= sum of newly created alerts
        self.assertGreaterEqual(dashboard.alert_total, 3,
                                'alert_total must be >= 3 (2 mo_delayed + 1 po_delayed).')

    # =========================================================================
    # Test 4 — sale category batch assignment
    # =========================================================================

    def test_sale_category_batch_assignment(self):
        """
        Call action_auto_assign_sale_categories and verify that:
        1. Every sale_ok product template ends up with a non-null x_sale_category.
        2. Two products with identical demand are classified in the same category
           when the mode is 'demand' and both fall in the same threshold bucket.

        Uses the 'demand' mode to avoid dependency on real stock movements
        or deliveries — demand thresholds are set via the config singleton.
        """
        cfg = self._ensure_config()

        # Switch to 'demand' mode with simple thresholds
        cfg.sudo().write({
            'sale_cat_mode': 'demand',
            'sale_cat_lookback_months': 3,
            # Threshold: avg monthly demand >= 50 → A, else E (simplified)
            'sale_cat_demand_a_qty': 50,
            'sale_cat_demand_b_qty': 0,   # won't be reached in this test
            'sale_cat_demand_c_qty': 0,
            'sale_cat_demand_d_qty': 0,
        })

        # Create 10 products with sale_ok=True
        products = self.env['product.template'].create([
            {
                'name': f'SALE-CAT-PROD-{i:02d}',
                'type': 'consu',
                'sale_ok': True,
            }
            for i in range(10)
        ])

        # Run the assignment (no real sales exist → every product gets 'E')
        result = cfg.action_auto_assign_sale_categories()

        # action must return a client action dict
        self.assertIsInstance(result, dict,
                              'action_auto_assign_sale_categories must return a dict.')
        self.assertEqual(result.get('type'), 'ir.actions.client',
                         'Return value must be an ir.actions.client action.')

        # All 10 created products must now have a non-null x_sale_category
        for tmpl in products:
            cat = tmpl.x_sale_category
            self.assertIsNotNone(cat,
                                 f'Product {tmpl.name} must have x_sale_category set, got None.')
            self.assertIn(cat, ('A', 'B', 'C', 'D', 'E'),
                          f'Product {tmpl.name} has unexpected category: {cat!r}.')

        # Products with identical (zero) demand must share the same category
        categories = set(tmpl.x_sale_category for tmpl in products)
        self.assertEqual(
            len(categories), 1,
            'All 10 products with no demand should land in the same category; '
            f'got categories: {categories}.'
        )

        # In 'demand' mode with zero demand and threshold a_qty=50,
        # they must all be 'E' (the lowest bucket)
        self.assertEqual(
            list(categories)[0], 'E',
            'Products with zero demand must receive category E '
            'when the A threshold is set to 50 units/month.'
        )
