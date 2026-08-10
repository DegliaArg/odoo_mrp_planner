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
        this.localState = useState({
            open:        false,
            favoriteName:'',
            favorites:   this._loadFavs(),
            numModalOpen:false,
            numDraftGroup: { match: 'all', rules: [] },
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

    // ── Filtro numérico (modal "Agregar filtro personalizado", estilo Odoo) ─────

    _numColLabel(key) {
        return ((this.props.numericFields || []).find(c => c.key === key) || {}).label || key;
    }
    _numOpLabel(op) { return (NUM_OPS.find(o => o.op === op) || {}).label || op; }

    _ruleLabel(r) {
        const right = r.mode === 'col'
            ? this._numColLabel(r.col2)
            : new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 }).format(r.value || 0);
        return `${this._numColLabel(r.col)} ${this._numOpLabel(r.op)} ${right}`;
    }

    /** Etiqueta de una faceta: una regla suelta, o un grupo unido por "y"/"o". */
    numFilterLabel(g) {
        const grp = (g && g.rules) ? g : { match: 'all', rules: [g] };
        const sep = grp.match === 'any' ? ' o ' : ' y ';
        return grp.rules.map(r => this._ruleLabel(r)).join(sep);
    }

    _newRule() {
        const nf = this.props.numericFields || [];
        return { col: (nf[0] || {}).key || '', op: '<', mode: 'value',
                 value: null, col2: (nf[1] || nf[0] || {}).key || '' };
    }

    openNumModal(ev) {
        if (ev) ev.stopPropagation();
        this.localState.numDraftGroup = { match: 'all', rules: [this._newRule()] };
        this.localState.numModalOpen = true;
        this.localState.open = false;   // cerrar el dropdown al abrir el modal
    }
    cancelNumModal() { this.localState.numModalOpen = false; }
    addNumRule()     { this.localState.numDraftGroup.rules.push(this._newRule()); }
    removeNumRule(i) {
        const rules = this.localState.numDraftGroup.rules;
        if (rules.length > 1) rules.splice(i, 1);
    }
    setNumRuleMode(i, mode) { this.localState.numDraftGroup.rules[i].mode = mode; }

    /** Valida las reglas del grupo y lo agrega como una faceta. */
    confirmNumGroup() {
        if (!this.props.onNumFilterAdd) return;
        const g = this.localState.numDraftGroup;
        const rules = g.rules.filter(r => {
            if (r.mode === 'value') {
                return !(r.value === null || r.value === undefined || r.value === '' || Number.isNaN(Number(r.value)));
            }
            return r.col2 && r.col2 !== r.col;
        }).map(r => ({
            col: r.col, op: r.op, mode: r.mode,
            value: r.mode === 'value' ? Number(r.value) : null,
            col2: r.mode === 'col' ? r.col2 : null,
        }));
        if (!rules.length) { this.localState.numModalOpen = false; return; }
        this.props.onNumFilterAdd({ match: g.match, rules });
        this.localState.numModalOpen = false;
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
