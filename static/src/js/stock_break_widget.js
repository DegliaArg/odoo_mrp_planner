/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class StockBreakWidget extends Component {
    static template = "odoo_mrp_reschedule.StockBreakWidget";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:       true,
            error:         null,
            filterType:    "all",
            sortField:     null,
            sortDir:       "asc",
            page:          1,
            pageSize:      20,
            search:        "",
            locationId:    null,
            locations:     [],
            kpis:          { total: 0, broken: 0, ok: 0, no_min: 0 },
            products:      [],
            locationName:  "",
            totalFiltered: 0,
        });
        this._searchTimer = null;

        onMounted(() => this._init());
    }

    async _init() {
        const [locs] = await Promise.all([
            this.orm.call("mrp.planner.dashboard", "get_internal_locations", []),
            this._load(),
        ]);
        this.state.locations = locs;
        // Si no hay override manual, usar la ubicación que devolvió el backend
        if (!this.state.locationId && locs.length) {
            // locationId ya fue seteado en _load() desde d.location_id
        }
    }

    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_stock_break_data",
                [this.state.filterType, this.state.sortField || null,
                 this.state.sortDir, this.state.page, this.state.pageSize,
                 this.state.search, this.state.locationId || null],
            );
            if (d.error === "no_location") {
                this.state.error = "no_location";
            } else {
                this.state.error         = null;
                this.state.kpis          = d.kpis;
                this.state.products      = d.products;
                this.state.locationName  = d.location_name;
                this.state.totalFiltered = d.total_filtered;
                if (!this.state.locationId && d.location_id) {
                    this.state.locationId = d.location_id;
                }
            }
        } catch (e) {
            console.error("[StockBreakWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    onLocationChange(ev) {
        const id = parseInt(ev.target.value);
        this.state.locationId = id || null;
        this.state.page = 1;
        this._load();
    }

    onSearchInput(ev) {
        const val = ev.target.value;
        this.state.search = val;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
            this.state.page = 1;
            this._load();
        }, 300);
    }

    setFilter(f) {
        if (this.state.filterType === f) return;
        this.state.filterType = f;
        this.state.page = 1;
        this._load();
    }

    sortBy(field) {
        if (this.state.sortField === field) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortField = field;
            this.state.sortDir   = "asc";
        }
        this.state.page = 1;
        this._load();
    }

    sortIcon(field) {
        if (this.state.sortField !== field) return "fa fa-sort text-muted ms-1 small";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    get totalPages()  { return Math.max(1, Math.ceil(this.state.totalFiltered / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) { this.state.page++; this._load(); } }
    prevPage() { if (this.hasPrevPage) { this.state.page--; this._load(); } }

    fmt(n) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(n || 0);
    }

    openProductFromRow(ev) {
        const id = ev.currentTarget.closest("tr").dataset.productId;
        if (!id) return;
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "product.product",
            res_id:    parseInt(id),
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    openConfig() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.reschedule.config",
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }
}

registry.category("view_widgets").add("stock_break_widget", {
    component: StockBreakWidget,
});
