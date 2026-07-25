# Guion UAT pre-producción — odoo_mrp_planner v18.0.3.0.0

Checklist para ejecutar en **staging** antes del pase a producción.
Marcá cada ítem con `[x]`. Si algo falla, anotá al lado qué pasó.

**Requisito previo:** staging actualizado al último commit de la rama 18.0 y módulo
actualizado (`-u odoo_mrp_planner`), para que los assets JS/XML se regeneren.

---

## 0. Instalación limpia (LA prueba más importante — prod será una instalación fresca)

En una **base de datos NUEVA** de staging (no la que venís usando):

- [ ] Instalar el módulo desde Apps → instala **sin errores** (los 2 bugs de instalación fresca ya se corrigieron, confirmar que no aparezca otro).
- [ ] `mrp_subcontracting` se instala automáticamente como dependencia (verificar en Apps).
- [ ] Ajustes del planificador se abren y muestran la config con **defaults** (singleton creado solo).
- [ ] Los 8 grupos existen en Ajustes → Usuarios → Grupos (categoría del planificador): Producción-lectura, Producción-admin, Compras, Compras-admin, Ventas-lectura, Ventas-admin, Programación, Administrador.
- [ ] Los 4 crons existen en Técnico → Acciones planificadas (chequeo de atrasos + 3 de categorías).
- [ ] Los 4 paneles (Producción / Compras / Ventas / y análisis) **cargan vacíos sin errores** (sin datos todavía).

## 1. Configuración (staging con datos)

- [ ] Recorrer TODAS las pestañas de Ajustes (General / Producción / Programación / Compras / Ventas): ningún campo da error al guardar.
- [ ] "Referencia para variación de precio" muestra las 3 opciones y está en la que corresponda (**Precio anterior pagado** = decisión tomada). ⚠️ En bases existentes conserva el valor viejo: setearlo a mano.
- [ ] "Parámetros RFM" visibles al elegir método RFM (proveedor y cliente).
- [ ] Verificar que **ya no existen** los ajustes muertos: "Meses por defecto en forecast" y "Período por defecto" (análisis de clientes).
- [ ] El grupo de umbrales dice "**% Cumplim. / % Físico**" (no "% Entrega").
- [ ] **Anotar en una planilla el valor de CADA ajuste de staging** → esa planilla es la que vas a replicar a mano en prod (la config NO viaja con el módulo).

## 2. Smoke test por panel (5-10 min c/u, con datos reales)

### Producción
- [ ] KPIs de alertas cargan; drill de cada card abre la lista correcta.
- [ ] Widget OFs: tabs, buscador (con debounce, sin colgarse), paginación, orden por columnas.
- [ ] Comparativo Producido vs Programado: si el criterio es solapamiento/proporcional aparece el **badge de aviso**; el estado **"s/plan"** se muestra (celeste) si hay producido sin plan.
- [ ] Carga de centros de trabajo: gráfico carga; tooltip del KPI Carga dice **verde <70 / amarillo 70–89.9 / rojo ≥90** y coincide con los colores.
- [ ] Quiebres de stock: carga, buscador, selector de ubicaciones; columna rotación (si está activada) con tooltip.
- [ ] **Export CSV de quiebres**: las columnas Rot. / Plazo fab. / Estado **tienen valores** (antes salían vacías) y exporta **todas** las filas filtradas, no solo la página.

### Compras
- [ ] KPIs de OC: cada uno filtra por su fecha (Cotizaciones/Por aprobar → pedido; Aprobadas → aprobación; A tiempo/Vencidas/Críticas → entrega). Mover el rango de fechas cambia los números coherentemente.
- [ ] Botón "Ver" de CADA KPI: la lista abierta tiene **exactamente** la misma cantidad que el número del KPI.
- [ ] Pestañas Recepciones y Entregas cargan; buscar en Entregas con un rango de fechas amplio **no cuelga** (fix de performance).
- [ ] Análisis de proveedores: % a tiempo con tooltip que indica "N sin fecha (excluidas)" si aplica; "Retraso" sin datos muestra "—" gris (no "0 d" verde); columna Var. precio coherente con la referencia configurada.

### Ventas
- [ ] Gráfico ABC de productos: métrica **PxQ = precio de lista × cantidad** en ambas fuentes (verificar 1 producto a mano).
- [ ] Forecast: carga completa; KPIs Tasa física / Tasa de cumplimiento; tooltips de rotación dicen "stock promedio".
- [ ] **Export Excel de forecast**: header "% Cobertura OFs" (no "% Cumplimiento"), incluye columnas Entregado/Cumplim./Demanda, y el % de cobertura coincide con la pantalla si el denominador es demanda OV.
- [ ] Análisis de clientes: columnas **% Cumplim.** y **% Físico** (ambas con semáforo); tooltip del físico con desglose "por mes de confirmación del pedido"; **ABC período** cambia al cambiar el rango de fechas (calculado al vuelo); fechas en DD/MM/YYYY; botón "Importe" (ex PxQ).
- [ ] Drill de un cliente: cards con ambas tasas, gráfico mensual con dataset "Despachado" (naranja) y su tooltip con desglose, tabla por producto con % Físico.

### Estados de error (nuevo)
- [ ] Cortar red o forzar un error (ej. filtro raro) → forecast/proveedores/quiebres muestran **alerta de error visible**, no spinner/skeleton infinito.

## 3. Validación numérica contra el Word de fórmulas (2-3 casos por métrica)

Elegí 1 proveedor, 1 cliente y 1 producto con datos conocidos y verificá A MANO:

- [ ] **% Cumplim. de un cliente** = qty_delivered de sus pedidos del período ÷ pedido (§4.1).
- [ ] **% Físico del mismo cliente** = remitos validados dentro del período ÷ pedido (§4.1b); si supera 100%, el desglose del tooltip lo explica.
- [ ] **% a tiempo de un proveedor** = recepciones en fecha ÷ recepciones con fecha (§2.3) — las sin fecha excluidas.
- [ ] **Variación de precio** de un proveedor con 2+ compras del mismo producto = promedio de |precio − precio anterior| ÷ anterior (§2.8c).
- [ ] **Rotación de un producto** en forecast (método unidades) = stock promedio ÷ promedio mensual entregado (§3.9).
- [ ] **KPIs de OC**: contar a mano las vencidas del rango (date_planned en rango y < hoy) y comparar con el KPI.
- [ ] **ABC del período** (clientes): el cliente que más facturó en el rango es **A** siempre.
- [ ] Ejecutar "Calcular ahora" de categorías de proveedor con método **devoluciones**: un proveedor con compras y 0 devoluciones queda **A** (no E).

## 4. Roles y permisos (crítico: los guards son nuevos)

Crear/usar un usuario por rol y verificar con cada uno:

- [ ] **Solo Producción-lectura**: ve panel de producción y quiebres; el panel de ventas/análisis de clientes le da **error de acceso** o no se muestra (guard nuevo); no puede calcular programaciones.
- [ ] **Solo Compras**: ve panel de compras y análisis de proveedores; no ve ventas.
- [ ] **Solo Ventas-lectura**: ve gráfico, forecast y análisis de clientes; NO puede editar forecast.
- [ ] **Usuario SIN ningún grupo del planificador**: no puede extraer datos ni por menú ni (si sabés probarlo) por RPC — los métodos devuelven error de acceso.
- [ ] **Programación**: solo los usuarios del grupo pueden Calcular/Confirmar una programación (probar con uno sin el grupo: el servidor rechaza aunque fuerce el botón).
- [ ] **Depósitos restringidos**: un usuario limitado a un depósito ve solo sus datos; quitarle el depósito **surte efecto inmediato** (fix de caché) y sin depósitos válidos ve vacío (no todo).
- [ ] **Multiempresa**: con la empresa B activa, los paneles muestran SOLO datos de B (clientes, ventas, quiebres, forecast). Cambiar de empresa cambia los datos.

## 5. Configuraciones con efecto (spot-check)

Cambiar cada una y verificar el efecto visible:

- [ ] Umbral crítico de OC (días) → KPI "Críticas" cambia.
- [ ] Excluir OCs de servicio ON/OFF → KPIs de OC cambian.
- [ ] Criterio del comparativo (cierre/inicio/solapamiento/proporcional) → números y badge cambian.
- [ ] Método de rotación (unidades/COGS/ventas) → columna de rotación cambia en forecast y quiebres.
- [ ] Umbrales semáforo % Cumplim./Físico → colores cambian en clientes.
- [ ] Umbrales ABC (A/B/C/D) y Parámetros RFM → recalcular categorías cambia resultados.

## 6. Casos borde (regresión de los fixes)

- [ ] Cliente con **1 solo pedido** → segmento "Ocasional", sin errores.
- [ ] OF **sin fecha de inicio** → en comparativo/forecast cae al mes de cierre.
- [ ] Período **sin datos** → todos los widgets muestran estado vacío prolijo.
- [ ] Producido sin plan → "s/plan", no 0%.
- [ ] Proveedor sin recepciones → "—" en retraso/% a tiempo, no números falsos.
- [ ] Producto E en quiebres → badge **gris** (paleta unificada), no rojo.

## 7. Runbook de deploy a producción

1. [ ] Backup/snapshot de prod (aunque sea instalación nueva, por el resto del sistema).
2. [ ] Subir el submódulo a prod apuntando al commit final validado de la rama 18.0.
3. [ ] Instalar `odoo_mrp_planner` desde Apps (instala `mrp_subcontracting` si falta).
4. [ ] **Replicar la planilla de configuración** de staging en Ajustes de prod (¡por cada empresa!). Incluye: umbrales, métodos ABC y RFM, referencia de variación de precio = "Precio anterior pagado", criterio del comparativo, métodos de rotación, semáforos, exclusión de servicios, crons automáticos ON/OFF.
5. [ ] Asignar grupos del planificador y depósitos a cada usuario real.
6. [ ] Smoke final en prod: los 4 paneles cargan con datos reales; 1 export de cada tipo; 1 verificación numérica rápida.
7. [ ] Ejecutar manualmente "Calcular ahora" de las categorías (proveedor/cliente/venta) la primera vez.
8. [ ] **Contingencia**: si algo falla grave → desinstalar el módulo (instalación fresca = rollback simple; los campos x_ del módulo se eliminan con él). Reportar el error antes de desinstalar.

---
*Generado en la revisión pre-producción del 2026-07-25 (ver docs/decisiones.md).*
