# MRP Reschedule Cascade

**Odoo 18 Enterprise · Fabricación**  
Desarrollado por [Deglia](https://deglia.xyz)

---

## ¿Qué hace este módulo?

Cuando una orden de fabricación intermedia termina antes o después de lo planificado, todas las órdenes subsecuentes planificadas en el mismo centro de trabajo quedan desfasadas. Este módulo permite corregir eso en segundos, con un wizard que muestra todos los cambios propuestos antes de aplicarlos.

Un solo clic reprograma en cascada:

- **Órdenes de fabricación** subsecuentes en el mismo centro de trabajo
- **Órdenes de compra** de subcontratación y de componentes vinculadas
- **Órdenes hijas** (MOs cuyo `origin` apunta a cada MO afectada), de forma recursiva
- **Órdenes de trabajo** — se replanifican automáticamente con el botón nativo de Odoo

---

## Instalación

1. Copiar la carpeta `odoo_mrp_reschedule/` en el directorio de addons del proyecto.
2. Actualizar la lista de aplicaciones.
3. Instalar **MRP Reschedule Cascade** desde el menú Aplicaciones.

**Dependencias:** `mrp`, `purchase`

---

## Uso

1. Ir a **Fabricación → Órdenes de fabricación** (vista lista).
2. Seleccionar la orden que terminó (la orden "pivot") — o no seleccionar ninguna para elegirla dentro del asistente.
3. Menú **Acción → Reprogramar en cascada**.
4. El wizard se abre pre-completado con la fecha real de finalización calculada desde las órdenes de trabajo terminadas.
5. Ajustar la **nueva fecha de fin** si es necesario.
6. Hacer clic en **↻ Calcular / Recalcular cambios** para ver todas las órdenes afectadas.
7. Revisar la tabla — se pueden editar fechas individuales y desmarcar filas para excluirlas.
8. Confirmar con **Aplicar cambios**.

### Lógica del wizard

| Color de fila | Significado |
|---|---|
| Azul | OF directamente subsecuente en el mismo WC (nivel 0) |
| Naranja | OF hija o descendiente (nivel 1+) |
| Gris | Orden de compra vinculada |

El **desplazamiento** se calcula como `nueva_fecha_fin − fecha_fin_planificada` de la orden pivot y se aplica uniformemente a todas las filas marcadas.

---

## Campos verificados en Odoo 18 SH Enterprise

| Modelo | Campo | Uso |
|---|---|---|
| `mrp.production` | `date_start` | Fecha planificada de inicio |
| `mrp.production` | `date_finished` | Fecha planificada de fin |
| `mrp.production` | `origin` | Vínculo a MO madre (MOs hijas) |
| `mrp.production` | `purchase_order_id` | PO de subcontratación (directo) |
| `mrp.production` | `purchase_line_id` | Línea de OC vinculada |
| `mrp.workorder` | `date_finished` | Fecha real de fin (WOs terminadas) |
| `purchase.order` | `date_planned` | Fecha de entrega esperada |
| `purchase.order.line` | `date_planned` | Fecha de entrega por línea |

---

## Soporte

**Deglia**  
✉️ administracion@deglia.xyz  
🌐 https://deglia.xyz

---

## Licencia

[Odoo Proprietary License v1.0 (OPL-1)](LICENSE)  
Copyright © 2026 Deglia
