/** @odoo-module **/

/**
 * @description Barra de búsqueda estilo Odoo reutilizable para los widgets del planificador.
 *   Muestra un input con chips para los filtros activos y un dropdown con tres secciones:
 *   Filtros, Agrupar por y Favoritos (guardados en localStorage).
 *
 * @prop {string}   widgetKey        — clave única para persistir favoritos (por widget+usuario)
 * @prop {string}   [placeholder]    — texto del input vacío
 * @prop {string}   [search]         — texto de búsqueda actual (controlado por el padre)
 * @prop {string|null} [activeFilter]  — clave del filtro activo (o null)
 * @prop {string|null} [activeGroupBy] — clave del agrupamiento activo (o null)
 * @prop {Array}    [filterDefs]     — [{key, label, icon?}] opciones de filtro
 * @prop {Array}    [groupByDefs]    — [{key, label}] opciones de agrupamiento
 * @prop {Function} onSearch         — (text: string) => void
 * @prop {Function} [onFilterChange] — (key: string|null) => void
 * @prop {Function} [onGroupByChange]— (key: string|null) => void
 */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

export class PlannerSearchBar extends Component {
    static template = "odoo_mrp_planner.PlannerSearchBar";
    static props = {
        widgetKey:      { type: String },
        placeholder:    { type: String, optional: true },
        search:         { type: String, optional: true },
        activeFilter:   { optional: true },
        activeGroupBy:  { optional: true },
        filterDefs:     { type: Array, optional: true },
        groupByDefs:    { type: Array, optional: true },
        onSearch:       { type: Function },
        onFilterChange: { type: Function, optional: true },
        onGroupByChange:{ type: Function, optional: true },
        "*":            true,
    };

    setup() {
        this.localState = useState({
            open:        false,
            favoriteName:'',
            favorites:   this._loadFavs(),
        });

        this._closeDropdown = () => { this.localState.open = false; };

        onMounted(() => document.addEventListener('click', this._closeDropdown));
        onWillUnmount(() => document.removeEventListener('click', this._closeDropdown));
    }

    // ── Favoritos ─────────────────────────────────────────────────────────────

    _key() { return `_planner_search_fav_${this.props.widgetKey}`; }

    _loadFavs() {
        try { return JSON.parse(localStorage.getItem(this._key()) || '[]'); }
        catch { return []; }
    }

    _persistFavs(list) {
        localStorage.setItem(this._key(), JSON.stringify(list));
        this.localState.favorites = list;
    }

    // ── Dropdown ──────────────────────────────────────────────────────────────

    toggleOpen(ev) {
        ev.stopPropagation();
        this.localState.open = !this.localState.open;
    }

    // ── Chips activos ─────────────────────────────────────────────────────────

    get activeChips() {
        const chips = [];
        if (this.props.search) {
            chips.push({ type: 'search', key: '_search', prefix: 'Buscar', label: this.props.search });
        }
        const af = this.props.activeFilter;
        if (af) {
            const def = (this.props.filterDefs || []).find(f => f.key === af);
            if (def) chips.push({ type: 'filter', key: af, prefix: 'Filtro', label: def.label });
        }
        const ag = this.props.activeGroupBy;
        if (ag) {
            const def = (this.props.groupByDefs || []).find(g => g.key === ag);
            if (def) chips.push({ type: 'groupBy', key: ag, prefix: 'Agrupar', label: def.label });
        }
        return chips;
    }

    removeChip(chip) {
        if (chip.type === 'search')   this.props.onSearch('');
        if (chip.type === 'filter'   && this.props.onFilterChange)  this.props.onFilterChange(null);
        if (chip.type === 'groupBy'  && this.props.onGroupByChange) this.props.onGroupByChange(null);
    }

    clearAll() {
        this.props.onSearch('');
        this.props.onFilterChange  && this.props.onFilterChange(null);
        this.props.onGroupByChange && this.props.onGroupByChange(null);
    }

    get hasActiveState() {
        return !!(this.props.search || this.props.activeFilter || this.props.activeGroupBy);
    }

    // ── Filtros / Agrupar ─────────────────────────────────────────────────────

    onSearchInput(ev) { this.props.onSearch(ev.target.value); }

    onKeydown(ev) {
        if (ev.key === 'Escape') {
            this.localState.open = false;
            ev.target.blur();
        }
    }

    toggleFilter(key) {
        if (!this.props.onFilterChange) return;
        this.props.onFilterChange(this.props.activeFilter === key ? null : key);
    }

    toggleGroupBy(key) {
        if (!this.props.onGroupByChange) return;
        this.props.onGroupByChange(this.props.activeGroupBy === key ? null : key);
    }

    // ── Favoritos: guardar / aplicar / borrar ─────────────────────────────────

    onFavInput(ev) { this.localState.favoriteName = ev.target.value; }

    onFavKeydown(ev) { if (ev.key === 'Enter') this.saveFavorite(); }

    saveFavorite() {
        const name = this.localState.favoriteName.trim();
        if (!name) return;
        const fav = {
            name,
            search:  this.props.search  || '',
            filter:  this.props.activeFilter  || null,
            groupBy: this.props.activeGroupBy || null,
        };
        this._persistFavs([...this.localState.favorites.filter(f => f.name !== name), fav]);
        this.localState.favoriteName = '';
    }

    applyFavorite(fav) {
        this.props.onSearch(fav.search || '');
        this.props.onFilterChange  && this.props.onFilterChange(fav.filter  || null);
        this.props.onGroupByChange && this.props.onGroupByChange(fav.groupBy || null);
        this.localState.open = false;
    }

    deleteFavorite(fav) {
        this._persistFavs(this.localState.favorites.filter(f => f.name !== fav.name));
    }
}
