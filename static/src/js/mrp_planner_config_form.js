/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { FormView } from "@web/views/form/form_view";
import { usePager } from "@web/search/pager_hook";

/**
 * FormController variant that hides the pager for singleton config forms.
 * A second usePager() call overrides pagerProps in the child env with total=0,
 * which the ControlPanel template uses to conditionally render the pager.
 */
class NoPagerFormController extends FormController {
    setup() {
        super.setup();
        usePager(() => undefined);
    }
}

registry.category("views").add("mrp_planner_config_form", {
    ...FormView,
    Controller: NoPagerFormController,
});
