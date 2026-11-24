# KPIs — Módulo de producción para Odoo 18

Panel de control centralizado para la gestión operativa de producción.

## Funcionalidades

### Alertas proactivas
- Detección automática de OFs atrasadas, OFs por vencer, OCs vencidas, OCs por vencer, recepciones demoradas y desvíos de cantidad.
- Severidad configurable: avisos y críticas con umbrales independientes.
- Resolución reactiva al cerrar OFs, OCs o recepciones.

### Panel en tiempo real
- KPIs de OFs, OCs, centros de trabajo y quiebres de stock.
- Widgets interactivos con filtros, paginación y drill-down.
- Permisos por usuario: secciones visibles y acciones habilitadas.
- En quiebres de stock, la columna "Pronóstico" usa el stock proyectado (a mano + entrante − saliente, `virtual_available`) en el mismo ámbito de ubicaciones que el "Stock actual", igual que el "Pronosticado" nativo de Odoo (antes tomaba el pronóstico del punto de reorden, atado a su ubicación exacta, que podía ignorar lo entrante de otras sub-ubicaciones y dar valores errados).

### Análisis de compras productivas
- Matriz CT × Semana con OFs y sus OCs descendientes a cualquier profundidad MTO.
- Navegación por ventana deslizante de 4 semanas.
- KPIs: OFs con OC vencida, sin confirmar, por aprobar y al día.
- Exportación a PDF con datos de empresa.

### Análisis de proveedores y clientes
- Scorecard de cumplimiento por proveedor: % a tiempo, lead time real, variación de precio.
- Clasificación A–E automática por volumen, frecuencia, RFM, % entregas a tiempo, variación de precio, exactitud de cantidad, devoluciones o calidad combinada.
- Panel de ventas: productos más vendidos y análisis de clientes con tasas de cumplimiento, ABC del período y segmentos de frecuencia.
- **Base de salida** (Ajustes → Ventas): define qué evento cuenta como "salida física". Con **Embalaje (orden de entrega validada)** (predeterminado) el cumplimiento, el lead time, la puntualidad y la demanda insatisfecha se miden por la orden de entrega validada (qty_delivered / date_done) — comportamiento histórico. Con **Salida física (factura)** se miden por la factura del cliente posteada (qty_invoiced / fecha de factura; qty_invoiced netea notas de crédito). El mismo ajuste gobierna la Tasa de servicio de Gerencia y el cumplimiento del Forecast para que no diverjan. El panel de KPIs del cliente del CRM hereda la base automáticamente.

### Forecast
- Tabla mensual comparativa: forecast, OFs planificadas, entregas y stock.
- Métricas de precisión configurables: Simple, MAPE, WAPE, WMAPE y Sesgo.
- Exportación a Excel y edición directa de valores en celda.
- La "Tasa de cumplimiento" y la card "Cumplimiento de demanda" siguen la Base de salida (facturado vs. entregado). La comparación forecast vs. real por mes de entrega siempre usa la entrega física (precisión de pronóstico), independientemente de la base.

### Inventario
- Panel con análisis de movimientos: recepciones, transferencias internas y cadena de entrega en todos los estados.
- KPIs dinámicos, validados del período y tasa de entrega s/ disponible con snapshots diarios y consolidado mensual.
- Card "Disponible no hecho" con botón "Ver →": abre la lista de los snapshots (mrp.dispatch.stock.log) que componen ese número; la cantidad (qty_reserved) suma exacto el valor de la card. Incluye columnas de categoría de producto y categoría de venta (filtrables y agrupables). El método (al cierre / pico) se toma de Ajustes → Inventario.

## Módulos relacionados

- `odoo_mrp_planner_scheduling` — Planificación desde demanda y reprogramación en cascada (standalone).
- `odoo_mrp_planner_dispatch` — Circuito de despacho desde el panel.

## Instalación

Requiere: `mrp`, `mrp_subcontracting`, `purchase`, `stock`, `mail`, `sale`.

## Autor

[Deglia](https://deglia.xyz) · Licencia OPL-1
