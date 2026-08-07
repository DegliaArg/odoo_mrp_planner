# Estado de sesión — Panel de Inventario (actualizado 2026-08-04)

Archivo de handoff para retomar el trabajo. Rama: `18.0-split-modules`, todo commiteado
y pusheado hasta `9ec77cd`. Módulo `odoo_mrp_planner_dispatch` v18.0.2.0.0.

## Commits de la sesión 2026-08-03/04 (del más viejo al más nuevo)

| Commit | Qué |
|---|---|
| `dd9d3e5` | universo por eslabones de la cadena (flujo lazy) — superado por `9ec77cd` |
| `e848820` | columna Origen de la tabla con hipervínculo a la venta (`sale_id` del grupo de abastecimiento) |
| `d14e133` | **Tipos de operación con despacho** en Ajustes→Inventario (m2m de tipos `outgoing`) |
| `d6a4da9` | celda Despacho vacía fuera del circuito + limpieza total de estados al excluir un tipo |
| `9ec77cd` | **Panel de Inventario estándar** (ver abajo) — versión 18.0.2.0.0 con migración |

## Decisiones clave de la sesión

1. **Contexto**: Giacomelli tiene múltiples depósitos con transferencias entre ellos por
   rutas estándar de Odoo (el tramo origen usa tipo `outgoing`, p. ej. `MC/OUT`) y la
   mercadería se transforma entre depósitos.
2. **Circuito de despacho** (`x_dispatch_state`): gobernado por la lista "Tipos de
   operación con despacho" (Ajustes→Inventario). Se precarga al activar; al excluir un
   tipo se limpian estado/fecha/usuario (auditoría queda en chatter); al incluirlo, las
   validadas viejas se marcan despachadas. Vacía = todas las salidas. Franco lo probó y
   funciona.
3. **Panel de Inventario 100 % estándar** (pedido explícito de Franco: "no quiero usar
   ese campo, es solo una extensión"):
   - Números SIEMPRE con datos nativos, esté o no activo el circuito:
     - Pendiente = eslabones sin validar (`confirmed/waiting/assigned`); salidas solo con
       **destino cliente** (`location_dest_id.usage = 'customer'`, helper
       `_dispatch_chain_domain`) — excluye transferencias inter-depósito.
     - "Entregado del período" = salidas a cliente `done` por `date_done` (tz-aware).
     - Tasa de entrega s/ disponible = entregado ÷ (entregado + disponible no salido);
       cierre mensual excluye cadenas **entregadas** (`_dispatch_delivered_chain_products`).
     - "Atraso prom. de entrega" = `date_done` − `scheduled_date` (reemplaza al lag
       validación→despacho).
   - Registro de disponibilidad (snapshots) **independiente** del circuito en Ajustes.
   - Circuito activo = solo capa operativa de la tabla: etapa "Validado s/ despachar",
     chip con conteo (no suma a KPIs), checkboxes y despacho masivo. Sin circuito, tabla
     de solo lectura.
   - Filtro de fechas de la tabla ahora convierte la zona horaria del usuario (fix del
     bug pendiente).
   - Migración `18.0.2.0.0`: purga `mrp_dispatch_stock_log` y el consolidado
     `dispatch_available` (la serie cambió de criterio y se regenera).
4. **Panel de Ventas sin cambios**: sigue midiendo lo físico por despacho
   (`_forecast_dispatched_picking_ids` filtra sobre remitos de ventas, no se contamina).

## Pendientes al retomar

1. **Verificación en UAT de `9ec77cd`** (pull + restart + `-u odoo_mrp_planner_dispatch`
   — corre la migración y purga la serie): a) KPIs con criterio entregado; b) las
   transferencias inter-depósito no aparecen en pendiente ni en entregado; c) chip y
   despacho masivo solo con circuito activo; d) activar "Registrar disponibilidad" (ya
   sin exigir el circuito) y verificar el snapshot del cron.
2. ~~Redondeo forzoso~~ **RESUELTO (2026-08-04, `6899fc5`)**: toggle propio
   `inventory_force_integer` en Ajustes→Inventario; los paneles ya no leen el de
   Producción. La migración 18.0.2.2.0 lo inicializa con el valor viejo.
3. Pendientes previos: persistencia de filtros de tableros (falta diagnóstico de consola,
   ver memoria) y validar en staging de Odoo.sh el ciclo upgrade base + install de los
   módulos nuevos antes de mergear a `18.0`.

## Forma de trabajo acordada (memoria)

Ante reportes de problema: diagnóstico y opciones primero, código solo con OK explícito.
Commits estilo del repo (`fix:`/`feat:` en español), push tras cada aprobación.
