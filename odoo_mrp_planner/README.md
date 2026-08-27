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

### Análisis de compras productivas
- Matriz CT × Semana con OFs y sus OCs descendientes a cualquier profundidad MTO.
- Navegación por ventana deslizante de 4 semanas.
- KPIs: OFs con OC vencida, sin confirmar, por aprobar y al día.
- Exportación a PDF con datos de empresa.

### Análisis de proveedores y clientes
- Scorecard de cumplimiento por proveedor: % a tiempo, lead time real, variación de precio.
- Clasificación A–E automática por volumen, frecuencia, RFM, % entregas a tiempo, variación de precio, exactitud de cantidad, devoluciones o calidad combinada.
- Panel de ventas: productos más vendidos y análisis de clientes con tasas de cumplimiento, ABC del período y segmentos de frecuencia.

### Forecast
- Tabla mensual comparativa: forecast, OFs planificadas, entregas y stock.
- Métricas de precisión configurables: Simple, MAPE, WAPE, WMAPE y Sesgo.
- Exportación a Excel y edición directa de valores en celda.

### Inventario
- Panel con análisis de movimientos: recepciones, transferencias internas y cadena de entrega en todos los estados.
- KPIs dinámicos, validados del período y tasa de entrega s/ disponible con snapshots diarios y consolidado mensual.

## Módulos relacionados

- `odoo_mrp_planner_scheduling` — Planificación desde demanda y reprogramación en cascada (standalone).
- `odoo_mrp_planner_dispatch` — Circuito de despacho desde el panel.

## Instalación

Requiere: `mrp`, `mrp_subcontracting`, `purchase`, `stock`, `mail`, `sale`.

## Autor

[Deglia](https://deglia.xyz) · Licencia OPL-1
