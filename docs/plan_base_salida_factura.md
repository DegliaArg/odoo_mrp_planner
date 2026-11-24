# Plan — Base de salida física (factura) para cumplimiento y lead time

> Estado: **propuesta funcional acordada, pendiente de construir**. Rama de trabajo: `18.0-dev`.
> Módulo afectado: `odoo_mrp_planner` (paneles Clientes y Gerencia). **Inventario NO se toca.**

## 1. Problema

Hoy la **tasa de cumplimiento** y el **lead time de entrega** se calculan contra la
**validación de la orden de entrega** (`date_done` del picking de salida). En la operación real esa
validación significa **embalaje** (la pieza está lista y empaquetada, pero todavía dentro de
la empresa); la **salida física** ocurre un rato/días después.

La dirección quiere poder **diferenciar** estos indicadores respecto a las piezas que ya
**salieron físicamente**. El camino "correcto" (módulo `dispatch`, paso Ship extra, portería)
agrega **carga de registro al depósito**, que gerencia **no quiere**. Hay que apoyarse en un
evento ya registrado por otro motivo.

## 2. Proxy elegido: la factura

- **Nada sale sin factura**, aun con la orden de entrega ya validada (candado de salida).
- **Casi nunca se factura por anticipado** → la factura no se adelanta a la salida.
- El **remito se imprime desde la factura**, después de hacerla → la factura *es* el evento de
  salida, no un proxy lejano.

**Conclusión:** usar la **fecha de factura** como momento de "salida física".

## 3. Decisión de diseño: no casar entregas con facturas

Un pedido tiene **varias entregas y varias facturas** (más notas de crédito), y Odoo **no**
guarda una correspondencia entrega↔factura a nivel de unidades. En vez de reconciliar los dos
flujos (pegado FIFO frágil), se cambia la **unidad de medida** del indicador:

- Cumplimiento: se usa `qty_invoiced` (agregado nativo por línea de venta, gemelo de
  `qty_delivered`) en lugar de `qty_delivered`. **Sin N:M.**
- Lead time / Puntualidad: se iteran las **facturas posteadas** del pedido (fecha de factura −
  `date_order`), igual que hoy se iteran los remitos (`date_done`). Múltiples facturas por
  pedido deja de ser problema: cada factura es un evento, como hoy cada remito.

## 4. Config: un único setting compartido

Campo nuevo en la config de Ventas:

**`Base de salida: Embalaje (orden de entrega) / Salida física (factura)`** — default **Embalaje**
(nadie nota cambios de entrada).

Gobierna **las dos** zonas a la vez (Ventas + Gerencia) para que **nunca diverjan**. Encaja al
lado de los métodos ya existentes (`ontime_method`, `leadtime_method`, `sla_days`).

## 5. Alcance (qué se re-basa y qué no)

### Ventas — panel Clientes (`mrp_planner_dashboard_customer.py`)
| Métrica | Visible hoy | Cambio |
|---|---|---|
| Tasa de cumplimiento (`delivery_pct`) | **sí** (KPI + col) | `qty_delivered` ⇒ `qty_invoiced` |
| Lead time de entrega (`lead_time`) | **sí** (KPI + col) | órdenes de entrega ⇒ facturas posteadas |
| Puntualidad (`ontime_pct`) | col oculta por default | ídem (de yapa, mismo evento) |
| Tasa física (`physical_pct`) | **no se renderiza** | **no se toca** (calculada y oculta; eventual reuso aparte) |

### Gerencia (`mrp_planner_dashboard_management.py` + `report_management_daily.py`)
| Métrica | Dónde | Cambio |
|---|---|---|
| Tasa de servicio | panel **+ PDF del mail diario** | numerador entregado ⇒ facturado. El denominador (demanda disponible del período) no cambia. |
| Despachos (pz) | panel + PDF | **NO se toca** — es volumen físico de depósito (`date_done`), no una tasa; hace contraste con Facturado. |
| Facturado | panel + PDF | **NO se toca** — ya es base factura (`invoice_date`, `out_invoice`−`out_refund`). |

**Inventario (Tasa de entrega por eslabón): NO se toca, nada.**

## 6. Motivo de incluir Gerencia

La **Tasa de servicio** de Gerencia es la **prima hermana** del cumplimiento de Ventas (el
código la emparenta: *"espeja la Tasa de servicio del panel de Ventas, antes Tasa de
cumplimiento"*; solo cambia el denominador). Si Ventas pasara a factura y Gerencia quedara en
entregado, dos números que la dirección cree equivalentes divergirían — y el de Gerencia **sale
por mail todos los días**. El setting único los mantiene alineados.

## 7. Caveat: notas de crédito

`qty_invoiced` **netea** las notas de crédito. Si una NC es ajuste de precio (no devolución
física), baja la cantidad "salida" sin que haya vuelto nada. A tener presente. Al menos sería
**consistente** con el Facturado de Gerencia, que ya netea NC (`out_refund` con signo −).

## 8. Paso previo recomendado antes de codear

Correr sobre datos reales (XML-RPC capemi) el **análisis de brecha embalaje→factura**:
valida que la factura ocurre *después* del embalaje de forma consistente y cuantifica cuánto se
mueve cada número al cambiar de base. Si la brecha fuera ruidosa o negativa, revisar el proxy.

## 9. Orden de construcción (tentativo)

1. Campo de config `Base de salida` + vista en Ajustes de Ventas.
2. Clientes: re-basar cumplimiento (`qty_invoiced`) y lead/puntualidad (facturas posteadas)
   según el setting; tooltips que reflejen la base activa.
3. Gerencia: re-basar numerador de la tasa de servicio (panel + PDF) según el mismo setting.
4. Revisar textos/tooltips/leyendas en ambas zonas para que digan qué base está activa.
