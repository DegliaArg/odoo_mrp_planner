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
import { NUM_OPS } from "./planner_table";

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
        showFavorites:  { type: Boolean, optional: true },
        // Filtro numérico por columna (opcional; si no hay numericFields no se muestra)
        numericFields:    { type: Array, optional: true },   // [{key, label}]
        numFilters:       { type: Array, optional: true },   // [{col, op, mode, value, col2}]
        onNumFilterAdd:   { type: Function, optional: true }, // (condición) => void
        onNumFilterRemove:{ type: Function, optional: true }, // (índice) => void
        "*":            true,
    };

    setup() {
        this.numOps = NUM_OPS;
        const nf = this.props.numericFields || [];
        this.localState = useState({
            open:        false,
            favoriteName:'',
            favorites:   this._loadFavs(),
            numDraft:    { col: nf[0] ? nf[0].key : '', op: '<', mode: 'value',
                           value: null, col2: (nf[1] || nf[0] || {}).key || '' },
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
        (this.props.numFilters || []).forEach((c, i) => {
            chips.push({ type: 'num', key: 'num_' + i, index: i,
                         prefix: 'Filtro', label: this.numFilterLabel(c) });
        });
        return chips;
    }

    removeChip(chip) {
        if (chip.type === 'search')   this.props.onSearch('');
        if (chip.type === 'filter'   && this.props.onFilterChange)  this.props.onFilterChange(null);
        if (chip.type === 'groupBy'  && this.props.onGroupByChange) this.props.onGroupByChange(null);
        if (chip.type === 'num'      && this.props.onNumFilterRemove) this.props.onNumFilterRemove(chip.index);
    }

    clearAll() {
        this.props.onSearch('');
        this.props.onFilterChange  && this.props.onFilterChange(null);
        this.props.onGroupByChange && this.props.onGroupByChange(null);
        if (this.props.onNumFilterRemove) {
            // Quitar de atrás para adelante para que los índices no se corran
            for (let i = (this.props.numFilters || []).length - 1; i >= 0; i--) {
                this.props.onNumFilterRemove(i);
            }
        }
    }

    get hasActiveState() {
        return !!(this.props.search || this.props.activeFilter || this.props.activeGroupBy
                  || (this.props.numFilters || []).length);
    }

    // ── Filtro numérico ────────────────────────────────────────────────────────

    _numColLabel(key) {
        return ((this.props.numericFields || []).find(c => c.key === key) || {}).label || key;
    }
    _numOpLabel(op) { return (NUM_OPS.find(o => o.op === op) || {}).label || op; }

    /** Etiqueta de una condición: "Stock actual < 10" o "Stock actual < Mínimo". */
    numFilterLabel(c) {
        const right = c.mode === 'col'
            ? this._numColLabel(c.col2)
            : new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 }).format(c.value || 0);
        return `${this._numColLabel(c.col)} ${this._numOpLabel(c.op)} ${right}`;
    }

    setNumMode(mode) { this.localState.numDraft.mode = mode; }

    addNumFilter() {
        const d = this.localState.numDraft;
        if (!this.props.onNumFilterAdd) return;
        if (d.mode === 'value' && (d.value === null || d.value === undefined || d.value === '' || Number.isNaN(Number(d.value)))) return;
        if (d.mode === 'col' && d.col2 === d.col) return;
        this.props.onNumFilterAdd({
            col: d.col, op: d.op, mode: d.mode,
            value: d.mode === 'value' ? Number(d.value) : null,
            col2: d.mode === 'col' ? d.col2 : null,
        });
        this.localState.numDraft = { ...d, value: null };  // listo para agregar otra
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
