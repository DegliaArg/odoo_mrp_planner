/** @odoo-module **/

/**
 * @description Componente de tooltip accesible que reemplaza los atributos title= nativos.
 *   Envuelve cualquier elemento trigger y muestra un tooltip en el posicionamiento
 *   indicado. Soporta tanto hover como focus de teclado (accesibilidad WCAG 2.1 AA).
 *
 * @prop {string}  content   — Texto del tooltip (puede contener saltos de línea con \n).
 * @prop {string}  [position] — Posición relativa al trigger: 'top' | 'bottom' | 'left' | 'right'.
 *                              Por defecto: 'top'.
 * @prop {Object}  [slots]   — Slot por defecto: el elemento que actúa como trigger.
 *
 * Uso en template:
 *   <MrpTooltip content="'Texto del tooltip'" position="'top'">
 *       <div>Elemento trigger</div>
 *   </MrpTooltip>
 */

import { Component, useState, useRef, onWillUnmount } from "@odoo/owl";

export class MrpTooltip extends Component {
    static template = "odoo_mrp_planner.MrpTooltip";
    static props = {
        content:  { type: String },
        position: { type: String, optional: true },
        slots:    { type: Object, optional: true },
    };
    static defaultProps = { position: "top" };

    setup() {
        this.state = useState({ visible: false });
        this.tooltipId = `mrp-tip-${Math.random().toString(36).slice(2, 9)}`;
        this._showTimeout = null;

        onWillUnmount(() => {
            clearTimeout(this._showTimeout);
        });
    }

    showTooltip() {
        clearTimeout(this._showTimeout);
        this._showTimeout = setTimeout(() => {
            this.state.visible = true;
        }, 400);
    }

    hideTooltip() {
        clearTimeout(this._showTimeout);
        this.state.visible = false;
    }

    /** Permite cerrar con Escape cuando el trigger tiene foco. */
    onKeydown(ev) {
        if (ev.key === "Escape") {
            this.hideTooltip();
        }
    }
}
