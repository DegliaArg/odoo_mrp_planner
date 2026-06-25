/** @odoo-module **/

/**
 * @description Widget de roturas de stock por ubicación/almacén.
 *   Filtra por tipo (all/broken/ok/no_min), búsqueda por nombre con debounce 300ms,
 *   y por una o varias ubicaciones internas.
 * @fires RPC mrp.planner.dashboard.get_internal_locations — ubicaciones internas disponibles
 * @fires RPC mrp.planner.dashboard.get_stock_break_data — productos con rotura/sin mínimo
 *   Params: (filterType, sortField, sortDir, page, pageSize, search, locationIds)
 *   @returns {{ kpis: {total,broken,ok,no_min}, products: ProductRow[],
 *              location_name: string, total_filtered: number }}
 * @listens onMounted — carga ubicaciones y datos iniciales
 * @listens onWillUnmount — cancela timer de debounce de búsqueda
 */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class StockBreakWidget extends Component {
    static template = "odoo_mrp_planner.StockBreakWidget";
    static props = {
        record: { type: Object },
    };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:          true,
            error:            null,
            filterType:       "all",
            sortField:        null,
            sortDir:          "asc",
            page:             1,
            pageSize:         20,
            search:           "",
            locationIds:      [],
            locations:        [],
            locDropdownOpen:  false,
            locSearch:        "",
            kpis:             { total: 0, broken: 0, ok: 0, no_min: 0 },
            products:         [],
            locationName:     "",
            totalFiltered:    0,
        });
        this._searchTimer = null;
        this._closeLocDropdown = () => { this.state.locDropdownOpen = false; this.state.locSearch = ""; };

        onMounted(() => {
            this._init();
            document.addEventListener('click', this._closeLocDropdown);
        });
        onWillUnmount(() => {
            clearTimeout(this._searchTimer);
            document.removeEventListener('click', this._closeLocDropdown);
        });
    }

    /** @returns {Promise<void>} Carga ubicaciones y datos iniciales en paralelo */
    async _init() {
        const [locs] = await Promise.all([
            this.orm.call("mrp.planner.dashboard", "get_internal_locations", []),
            this._load(),
        ]);
        this.state.locations = locs;
    }

    /** @returns {Promise<void>} Carga datos de roturas de stock y actualiza state */
    async _load() {
        this.state.loading = true;
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_stock_break_data",
                [this.state.filterType, this.state.sortField || null,
                 this.state.sortDir, this.state.page, this.state.pageSize,
                 this.state.search, this.state.locationIds.length ? this.state.locationIds : null],
            );
            if (d.error === "no_location") {
                this.state.error = "no_location";
            } else {
                this.state.error         = null;
                this.state.kpis          = d.kpis;
                this.state.products      = d.products;
                this.state.locationName  = d.location_name;
                this.state.totalFiltered = d.total_filtered;
            }
        } catch (e) {
            console.error("[StockBreakWidget]", e);
        } finally {
            this.state.loading = false;
        }
    }

    toggleLocDropdown(ev) {
        ev.stopPropagation();
        this.state.locDropdownOpen = !this.state.locDropdownOpen;
        if (this.state.locDropdownOpen) this.state.locSearch = "";
    }

    get filteredLocations() {
        const q = this.state.locSearch.toLowerCase();
        if (!q) return this.state.locations;
        return this.state.locations.filter(l => l.name.toLowerCase().includes(q));
    }

    toggleLocation(ev) {
        const id = parseInt(ev.target.dataset.locId);
        const ids = this.state.locationIds;
        this.state.locationIds = ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id];
        this.state.page = 1;
        this._load();
    }

    clearLocFilter() {
        this.state.locationIds = [];
        this.state.page = 1;
        this._load();
    }

    get selectedLocLabel() {
        const ids = this.state.locationIds;
        if (!ids.length) return 'Todas las ubicaciones';
        if (ids.length === 1) {
            const loc = this.state.locations.find(l => l.id === ids[0]);
            return loc ? loc.name : 'Todas las ubicaciones';
        }
        return `${ids.length} ubicaciones`;
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

    onFilterChange(ev) {
        const f = ev.target.value;
        if (this.state.filterType === f) return;
        this.state.filterType = f;
        this.state.page = 1;
        this._load();
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

    async openConfig() {
        await this.action.doAction('odoo_mrp_planner.action_mrp_reschedule_config');
    }
}

registry.category("view_widgets").add("stock_break_widget", {
    component: StockBreakWidget,
});
