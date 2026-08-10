# Decisiones pendientes — Cálculos ABC y Comparativo Producido vs Programado

Este documento reúne los puntos que **no son bugs claros** sino decisiones de criterio de
negocio. Cada uno describe cómo funciona hoy, por qué está en duda, las opciones y una
recomendación. Al final hay un registro de lo que **ya se corrigió**.

> Convención de severidad:
> - 🔴 **Bug** = da un resultado incorrecto → ya corregido (ver final).
> - 🟠 **Inconsistencia** = técnicamente no rompe, pero puede confundir o sesgar → decidir.
> - 🟡 **Menor** = impacto chico, mejora opcional.

---

## A) Clasificación ABC de clientes y proveedores

### A1 🟠 "Pareto invertido" en realidad reparte por posición, no por participación
- **Dónde:** `models/mrp_abc_helpers.py` → `_assign_abc_pareto_lower` (líneas 64-92).
- **Afecta a:** ABC de proveedores por **variación de precio** y por **devoluciones**.
- **Hoy:** ordena de mejor a peor y asigna las letras por **posición** en la fila
  (el 20% de proveedores = A, el siguiente 30% = B, etc.). Es una cuartilización por
  cantidad de proveedores, **no** un Pareto por participación acumulada.
- **Consecuencia:** las cuotas son fijas. Aunque todos los proveedores tengan una
  variación de precio excelente y casi idéntica, el peor 5% igual cae en E. La etiqueta
  "Pareto invertido" en Ajustes es engañosa.
- **Opciones:**
  1. **Dejarlo así** pero renombrar la etiqueta a algo como "Ranking por percentil"
     (recomendado si te sirve repartir parejo).
  2. Convertirlo en un Pareto real invertido (por participación) — más complejo y no
     siempre tiene sentido para métricas sin un "total" natural (ej. variación de precio).
  3. Usar cortes por **umbral absoluto** configurable (ej. A = variación < 5%, B < 10%…),
     más interpretable para el usuario.
- **Recomendación:** Opción 1 (renombrar) salvo que quieras cortes absolutos (Opción 3),
  que sería lo más claro para el negocio.

### A2 🟠 "% de entrega a tiempo" penaliza entregas sin fecha planificada
- **Dónde:** `models/mrp_partner_category.py` → `abc_delivery_pct` (líneas ~342-363) y el
  combinado (líneas ~461-476).
- **Hoy:** el denominador cuenta **todas** las recepciones; una recepción sin
  `scheduled_date` o sin `date_done` se cuenta como "llegó tarde".
- **Consecuencia:** un proveedor puede quedar mal clasificado por datos faltantes que no
  son culpa suya.
- **Opciones:**
  1. Excluir del cálculo las recepciones sin fecha (solo medir las que sí tienen fecha).
  2. Dejarlo (asumir "sin fecha = incumplimiento").
- **Recomendación:** Opción 1 (excluir las sin fecha del denominador).

### A3 🟠 Variación de precio se compara contra el costo/lista ACTUAL, no el histórico
- **Dónde:** `models/mrp_partner_category.py` → `abc_price_var` (líneas ~365-416).
- **Hoy:** compara el precio de cada línea de OC contra el `standard_price` (o el precio
  de `supplierinfo`) **de hoy**. Una OC de hace 11 meses se mide contra el costo de hoy.
- **Consecuencia:** si el costo de referencia cambió durante el período, la "variación"
  se infla o desinfla artificialmente.
- **Opciones:**
  1. Dejarlo (simple, aceptable si los costos son estables).
  2. Usar una referencia histórica por fecha (más preciso, bastante más complejo).
- **Recomendación:** Opción 1 salvo que tus costos se muevan mucho en el año.

### A4 🟡 El período de "N meses" se calcula como N × 30 días
- **Dónde:** `models/mrp_partner_category.py` (líneas ~275, 548) y ventas (línea ~74).
- **Hoy:** `inicio = hoy − meses × 30`. 12 meses = 360 días, no 365.
- **Consecuencia:** el "último año" pierde ~5 días. Sesgo sistemático mínimo.
- **Opciones:** usar `dateutil.relativedelta(months=…)` para meses calendario exactos, o
  dejarlo.
- **Recomendación:** cambio menor y barato; hacerlo si buscamos precisión, no urgente.

### A5 🟡 Filtro de fecha sin límite superior (proveedores/clientes)
- **Dónde:** `models/mrp_partner_category.py` (varios `read_group`/`search`).
- **Hoy:** filtran `date_order >= inicio` **sin** `<= fin`. En ventas sí se acota arriba.
- **Consecuencia:** si hay OCs/SOs con fecha futura (programadas), entran al cálculo.
  Inconsistente entre secciones.
- **Opciones:** agregar `<= hoy` para uniformar, o dejarlo si querés incluir lo futuro.
- **Recomendación:** agregar el límite superior por consistencia.

### A6 🟡 RFM usa cortes fijos en el código, no los configurables
- **Dónde:** `models/mrp_partner_category.py` (líneas ~315-317, 334-338 y equivalentes de
  clientes) y `models/const.py` (`RFM_RECENCY_*`).
- **Hoy:** los cortes de Recencia (30/90 días), Frecuencia (>10 / ≥3) y del score total
  (8/6/4/3) están hardcodeados; no se leen de Ajustes como sí ocurre con los umbrales
  Pareto.
- **Consecuencia:** el usuario no puede afinar el RFM desde la configuración.
- **Opciones:** exponerlos como campos de configuración, o dejarlos fijos y documentarlos.
- **Recomendación:** documentarlos ahora; hacerlos configurables solo si te lo piden.

### A7 🟡 Uso de `sudo()` inconsistente entre modelos
- **Dónde:** `models/mrp_partner_category.py` (varios).
- **Hoy:** algunos modelos se leen con `sudo()` (para no recortar por permisos) y otros no
  (`purchase.order`, `stock.picking`, `stock.move`, `sale.order`).
- **Consecuencia:** si el usuario que corre la acción manual tiene reglas de registro
  (ej. multicompañía) restrictivas, el conteo puede quedar incompleto y sesgar la
  clasificación. El cron suele correr como superusuario y no sufre esto.
- **Opciones:** unificar el criterio de `sudo()` en todos los modelos del cálculo.
- **Recomendación:** unificar (usar `sudo()` en todos, ya que es un cálculo global de
  clasificación, no una operación del usuario).

---

## B) Comparativo Producido vs Programado (solapamiento)

> Recordatorio: se elige en Ajustes con `comparison_date_mode`
> (`models/mrp_reschedule_config.py:130-141`). Opciones: por fecha de cierre, por fecha de
> inicio, **solapamiento completo** y **proporcional por duración**.

### B1 🟠 "Solapamiento completo" cuenta cada orden entera en cada mes que toca (doble conteo)
- **Dónde:** `models/mrp_planner_dashboard_mo.py` (líneas ~511-525).
- **Hoy:** una orden de fabricación (OF) que cruza varios meses suma su cantidad **total**
  en cada mes. Si mirás abril, mayo y junio por separado, la misma OF aparece entera en
  los tres.
- **Consecuencia:** si el usuario suma meses, los totales se inflan. Está avisado en el
  texto de ayuda de Ajustes, o sea es "a propósito", pero puede confundir.
- **Opciones:**
  1. Dejarlo (es esperable en una vista mes-a-mes tipo forecast).
  2. Acotar la cantidad al período (ya existe ese comportamiento en el modo "proporcional").
- **Recomendación:** dejarlo, pero reforzar el aviso en la UI del comparativo (no solo en
  Ajustes), para que quede claro que no hay que sumar meses.

### B2 🟠 "Proporcional" mezcla programado prorrateado con producido real → el % puede dar raro
- **Dónde:** `models/mrp_planner_dashboard_mo.py` (líneas ~472-510).
- **Hoy:** lo **programado** se reparte por la fracción de tiempo que la OF pasa en el mes;
  lo **producido** se toma de los movimientos de stock reales fechados en el mes (dato
  exacto, sin prorratear).
- **Consecuencia:** si una OF larga registra toda su producción en un solo mes, ese mes
  puede mostrar >100% (incluso >300%) de cumplimiento, y ~0% en los otros meses. El % es
  matemáticamente correcto pero engañoso.
- **Opciones:**
  1. Dejarlo (el producido real es el dato más fiel; el % es orientativo).
  2. Prorratear también el producido por tiempo (coherente entre sí, pero deja de ser un
     dato "real" y pasa a ser una estimación).
  3. No mostrar % por mes en este modo, solo cantidades absolutas.
- **Recomendación:** Opción 1 o 3. Prorratear el producido (Opción 2) lo haría más
  "prolijo" pero menos honesto. Decidir según qué te importa más: fidelidad del dato
  producido vs. que el % cierre lindo.

### B3 🟠 El "producido" se mide distinto según el modo
- **Dónde:** `models/mrp_planner_dashboard_mo.py` (línea ~525 vs ~497-500).
- **Hoy:** en "completo" (y en "por fecha de inicio/cierre") el producido es el acumulado
  total de la OF (`qty_produced`); en "proporcional" es lo movido a stock dentro del mes.
- **Consecuencia:** cambiar el modo cambia el número de "producido" del mismo período de
  una forma que el usuario no espera.
- **Opciones:**
  1. Unificar la definición de "producido" entre modos.
  2. Dejarlo y documentar la diferencia claramente.
- **Recomendación:** decidir junto con B2. Si se elige medir el producido siempre por
  movimientos reales del período, B2 y B3 se resuelven juntos y quedan consistentes.

### B4 🟡 KPI "OFs terminadas" mide un universo distinto al del comparativo
- **Dónde:** `models/mrp_planner_dashboard_mo.py` (líneas ~564-568).
- **Hoy:** el contador de "OFs terminadas" cuenta por `date_finished` en el rango, sin
  importar el modo elegido. Puede haber OFs que entran al programado (por solape) pero no
  a este contador, y viceversa. El código lo declara intencional.
- **Consecuencia:** el usuario podría esperar que "terminadas" sea un subconjunto del
  comparativo y no siempre lo es.
- **Opciones:** dejarlo (documentado) o alinear ambos criterios.
- **Recomendación:** dejarlo; a lo sumo aclararlo en el tooltip del KPI.

### B5 🟡 Caso "programado = 0 y producido > 0"
- **Dónde:** `models/mrp_planner_dashboard_mo.py` (líneas ~528-538).
- **Hoy:** si no había nada programado pero se produjo algo, el % de cumplimiento muestra
  0% (no hay división válida) y el desvío queda negativo.
- **Consecuencia:** "0% de cumplimiento" cuando en realidad hubo sobreproducción es
  confuso.
- **Opciones:** mostrar un estado especial ("sin plan / sobreproducción") en vez de 0%.
- **Recomendación:** mejora de UI menor; hacerla si molesta en la práctica.

### B6 🟡 Diferencia de fallback entre Comparativo (MO) y Forecast
- **Dónde:** `models/mrp_planner_dashboard_mo.py` (~486-487) vs
  `models/mrp_planner_dashboard_forecast.py` (~291-297).
- **Hoy:** cuando una OF no tiene fecha de inicio, el comparativo le asigna la cantidad
  completa al período y el forecast la ubica en el mes de cierre. Comportamientos distintos
  en ese caso borde.
- **Consecuencia:** divergencia mínima solo con datos incompletos.
- **Recomendación:** unificar el fallback; muy bajo impacto.

---

## Estado de las decisiones

**Todas las decisiones fueron tomadas e implementadas** (A1–A7, B1, B2, B4, B5, B6).
Los ítems B3 quedaron "como están" por decisión del usuario (documentados).

- **A3** — La referencia de variación de precio es ahora **configurable con 3 opciones**
  (`supplier_price_var_method`): costo estándar, lista de proveedor o **precio anterior
  pagado** (default). Ese único ajuste controla **tanto la clasificación ABC como la columna
  del panel de análisis**, así siempre coinciden. Con "precio anterior" cada compra se compara
  con la compra previa del mismo producto al mismo proveedor (tendencia de precio, independiente
  del costo estándar volátil). *(`mrp_partner_category.py`, `mrp_planner_dashboard_supplier.py`,
  `mrp_reschedule_config.py`, `supplier_analysis_widget.js`, config/vista/docs actualizados.)*
  Nota: en instalaciones existentes el ajuste conserva su valor guardado; para obtener el
  comportamiento por defecto (precio anterior) hay que setearlo en Ajustes → "Referencia para
  variación de precio".
- **B6** — El fallback del comparativo cuando una OF no tiene fecha de inicio válida ahora usa
  la **fecha de cierre** (cantidad completa solo si el cierre cae en el período), igual que el
  forecast. *(`mrp_planner_dashboard_mo.py`.)*

Decisiones posteriores (revisión del documento Word de fórmulas):
- **S1** — La clasificación ABC por entrega a tiempo y la combinada excluyen del denominador
  las recepciones sin fecha (criterio unificado con el panel de análisis de proveedores).
  *(`mrp_partner_category.py`.)*
- **S2** — Los totales por producto de precisión de forecast (Simple, WAPE, Sesgo) respetan
  la fuente del «real» configurada (demanda u entregas), igual que celdas y KPI global.
  *(`mrp_forecast_calc_mixin.py`.)*
- **4.8 (opción B)** — La columna "ABC período" del análisis de clientes ahora se calcula
  **al vuelo** por participación en la facturación del rango visible (A ≤ a%, B ≤ a%+b%,
  C = resto; acumulado exclusivo). Los umbrales de Ajustes ahora sí se usan; tooltip
  explicativo. *(`mrp_planner_dashboard_customer.py`, widget/row XML, JS.)*
- **4.1 (opción 2, simetría física/cumplimiento)** — Toda tasa de entrega por cliente muestra
  ahora **ambas tasas**: "% Cumplim." (entregado de los pedidos del período ÷ pedido) y
  "% Físico" (despachado dentro del período, de cualquier pedido ÷ pedido; puede superar
  100%). Aplica en: tabla principal, KPIs superiores (Cumplim. prom. + Física prom.),
  detalle del cliente (cards, gráfico mensual con dataset "Despachado" y desglose por mes
  de confirmación del pedido en el tooltip, tabla por producto), export y ordenamiento.
  Ambas comparten el semáforo configurable de entrega. *(`mrp_planner_dashboard_customer.py`,
  `customer_analysis_widget.js/.xml`, `customer_analysis_row.xml`,
  `customer_analysis_detail_panel.xml`, `customer_analysis_charts.js`; docs
  `formulas.md` §4.1/§4.1b y `docs.md`.)*

Detalle de lo implementado en esta ronda:
- **A1** — Etiqueta "Pareto invertido" → "Ranking por percentil" (variación de precio y
  devoluciones), en config, vista de ajustes y docs.
- **A2** — % entrega a tiempo: las recepciones sin fecha se excluyen del denominador y se
  informan en el tooltip (por proveedor y global). *(`mrp_planner_dashboard_supplier.py`,
  `supplier_analysis_widget.js`.)*
- **A4** — Período de análisis con meses calendario exactos (`relativedelta`) en lugar de
  N×30 días. *(`mrp_partner_category.py`.)*
- **A5** — Se agregó límite superior de fecha (`<= fin`) a todos los métodos ABC de
  proveedores y clientes, para no incluir OCs/SOs con fecha futura.
- **A6** — Cortes RFM (recencia, frecuencia y score A/B/C/D) expuestos como campos de
  configuración en Ajustes → "Parámetros RFM" (compartidos por clientes y proveedores).
  *(`const.py`, `mrp_reschedule_config.py`, `res_config_settings_views.xml`,
  `mrp_partner_category.py`.)*
- **A7** — Unificación de `sudo()` en todos los modelos leídos por los cálculos ABC
  (purchase.order, sale.order, stock.picking, stock.move, purchase.order.line).
- **B1** — Badge visible en el comparativo con el criterio de fechas activo (aviso de doble
  conteo en "solapamiento completo" y de producido real vs. programado prorrateado en
  "proporcional"). *(`mo_dashboard_widget.js` / `.xml`.)*
- **B2** — Notas del criterio activo anexadas a los tooltips del comparativo.
- **B4** — Tooltip del KPI "OFs completadas" aclara que se cuenta por fecha de fin,
  independiente del criterio, y puede no coincidir con el comparativo de cantidades.
- **B5** — Caso programado=0 y producido>0: se muestra "s/plan" (sin plan / sobreproducción)
  en vez de 0%, tanto por producto como en el KPI global. *(`mrp_planner_dashboard_mo.py`,
  `mo_dashboard_widget.js` / `.xml`.)*

Documentación (`docs/formulas.md`, `docs/docs.md`) actualizada para todos los ítems
anteriores.

---

## Registro de correcciones ya aplicadas (no requieren decisión)

- ✅ 🔴 **ABC por devoluciones — ranking invertido.** Los proveedores con **cero
  devoluciones** (los mejores) quedaban en E (el peor) porque "sin devoluciones" se
  confundía con "sin datos". Se agregó una base de proveedores con OCs en el período que
  parten de 0 devoluciones, para que se clasifiquen como A.
  *(`models/mrp_partner_category.py`, método `abc_quality_returns`.)*

- ✅ 🟠 **Corte Pareto — el ítem dominante no caía en A.** El acumulado se sumaba antes de
  comparar, así que el cliente/proveedor más grande podía saltarse la categoría A (o, en
  casos muy concentrados, dejar a todos fuera de A). Se cambió a **acumulado exclusivo**
  (comparar antes de sumar): ahora el registro más grande siempre cae en A.
  *(`models/mrp_abc_helpers.py` → `_assign_abc_pareto`, y el modo participación/PxQ en
  `models/mrp_partner_category.py`.)*

- ✅ **Documentación de rotación (forecast, método "por unidades").** Se corrigió la doc
  que decía "stock actual" cuando el código usa "stock promedio del período".
  *(`docs/formulas.md` §3.9 y `docs/docs.md` tabla "Por unidades".)*

---

## Falsos positivos verificados (no hay nada que hacer)

- ✔️ **Conteo de órdenes (`partner_id_count`).** Se sospechó un posible error de clave que
  rompería el ABC por volumen/frecuencia. Al revisar el código, la clave es válida en
  Odoo 18 (se pide `id:count` y el groupby genera `partner_id_count`). **Funciona bien.**

- ✔️ **Divisiones por cero y husos horarios en el comparativo.** Todas las divisiones
  tienen guarda; las fechas se comparan en UTC de forma coherente entre backend y frontend.
  **Sin problemas.**

---

## Revisión pre-producción (2026-07-25)

Se ejecutó una auditoría de 6 dimensiones (seguridad, multiempresa, performance,
dependencias, código muerto y configuración) previa al pase a producción. Fixes aplicados:

- **Seguridad multiempresa:** filtros `company_id` + guards de grupo en el servidor
  (`_ensure_planner_group`) en los RPCs de ventas, clientes, forecast y quiebres; colapso
  del caso `allowed == []` (usuario sin depósitos permitidos no ve datos ajenos).
- **Dependencias:** `mrp_subcontracting` agregado a `depends` y `mrp_workorder` eliminado.
- **Migraciones:** carpeta `migrations/` (18.0.46.0.0) eliminada — el módulo se instala fresco.
- **Performance:** batcheo de la estrategia 4 de entregas de OC, cota de 365 días en el
  cálculo de días-en-quiebre, cota de 6 meses en el historial de "precio anterior pagado"
  e invalidación correcta del `ormcache` de depósitos.
- **Seguridad de registros:** record rules para los modelos hijos de
  `mrp.production.request`; guard de `group_scheduling` en calcular/confirmar.
- **Limpieza:** eliminación de adjuntos temporales de export, ajustes muertos
  (meses por defecto del forecast, período preseleccionado de clientes) y código muerto
  (`mo_list_widget`, `MrpTooltip`, 16 acciones sin uso del mixin, imports).

## Auditoría post-split de módulos (2026-08-06)

Auditoría de 5 dimensiones (separación de módulos, seguridad, código muerto, tamaño de
archivos y backlog) sobre los tres módulos — base 18.0.7.0.0, scheduling 18.0.5.2.1 y
dispatch 18.0.3.0.0 — tras mover el Panel de Inventario al módulo base (migración
18.0.6.0.0) y fusionar el panel de Movimientos dentro del de Inventario.

- **Separación de módulos: limpia.** Sin modelos ni helpers duplicados (todo por
  `_inherit`); `depends` completos en los tres manifests; cada módulo declara ACLs solo
  de sus modelos; referencias cruzadas siempre calificadas (`odoo_mrp_planner.*`); la
  pre-migración 18.0.6.0.0 reasigna bien los `ir_model_data` movidos; todos los anchors
  que hereda el dispatch (drills, `inventory_settings_row`, form de Ajustes) existen en
  el base. El circuito de despacho está completo: tipos elegibles con precarga y
  sincronización (limpia estados al excluir un tipo), hooks del panel
  (`_inventory_dispatch_enabled/_queue_ids/_can_dispatch`) y columna Despacho agregada
  por herencia a los drills.
- **Seguridad: sin hallazgos accionables.** Los tres RPC del Panel de Inventario llaman
  `_inventory_ensure_group()` antes de leer con `sudo()`; todos los `sudo()` nuevos
  están comentados; el filtrado por depósito sigue entrando únicamente por
  `_get_allowed_wh_ids()` (vía `_inventory_effective_whs`). Dos anotaciones **por
  diseño** (no bugs): (a) ningún `action_open_*` de los cinco paneles lleva guard — solo
  crean el transient; los datos se protegen en los `get_*`; (b) los campos `x_qty_*` de
  `stock.picking` no filtran por depósito: muestran cantidades del propio remito (ya
  protegido por record rules) y la disponibilidad por cadena cruza depósitos a propósito.
- ✔️ **Falso positivo verificado:** el `(3, ref('group_inventory_admin'))` de
  `odoo_mrp_planner_dispatch/security/groups.xml` no es un bug: deshace a propósito la
  herencia que existía hasta v18.0.2.x (los grupos de Inventario se asignan por usuario,
  no vía Administrador del planificador) y en instalaciones frescas es un no-op.
- ✅ **Código muerto eliminado:** campo `x_qty_pieces` + `_compute_x_qty_pieces`
  (reemplazados en los drills por los almacenados `x_qty_done` / `x_qty_pending_store`)
  y el helper `_inventory_wh_domain`, nunca llamado. Verificados **vivos** antes de
  borrar (búsqueda por string en todo el repo): `_planner_qty_move_date_dom` (lo usa
  `_compute_x_qty_chain` con el contexto `planner_date_from/_to` que manda el widget),
  `STATE_LABELS`/`rowStateLabel` y `_dispatch_chain_types`.
- 🟡 **Tamaño/responsabilidad (diagnóstico, sin refactor aplicado):** hay ~450 líneas de
  lógica casi idéntica repetida entre `customer_analysis_widget.js`,
  `stock_break_widget.js` e `inventory_dashboard_widget.js` (orden/filtro/paginación,
  pestañas de agrupación, selección de filas, dropdowns multi-select de depósito/tipo,
  export). `customer_analysis_widget.js` (~1440 líneas) siguió creciendo porque cada
  iteración de UX (panel lateral de detalle, selección, persistencia, export) se agregó
  al archivo principal — solo los gráficos se extrajeron a
  `customer_analysis_charts.js`. `mrp_reschedule_config.py` (~990) concentra 8 dominios
  de configuración (alertas, forecast, categorías ×3, análisis de clientes,
  inventario/snapshots). Propuesta en el backlog (requiere decisión).

## Ejecución de las decisiones de la auditoría (2026-08-06, tarde)

Las tres decisiones que la auditoría dejó pendientes fueron confirmadas y ejecutadas
(commits separados por riesgo). Con esto se cierran los tres ítems que la auditoría
había agregado al backlog, más el C5 histórico.

- ✅ **(a) Refactor de mecánica compartida JS + split de la config.**
  - Nuevos módulos `static/src/js/planner_table.js` (orden genérico, pestañas de
    agrupación, paginación), `planner_selection.js` (selección de filas),
    `planner_multiselect.js` (dropdowns multi-selección) y `planner_export.js`
    (CSV/Excel); `kpiNumClass` pasó a `forecast_formatters.js`. Los widgets de
    Inventario, Quiebres y Clientes delegan en las factories y conservan wrappers de
    una línea para sus templates (sin cambios de template ni de comportamiento).
  - Panel lateral y filas expandibles de clientes extraídos a
    `customer_analysis_panel.js` (mismo patrón que `customer_analysis_charts.js`).
  - `mrp_reschedule_config.py` (994 líneas) dividido por dominio en
    `mrp_reschedule_config_forecast.py`, `_categories.py` y `_inventory.py`
    (verificado por script: 109 campos, cero perdidos/duplicados). De paso se
    eliminaron el import muerto de `mrp_abc_helpers` y `_logger` sin uso.
  - Tamaños finales: clientes 1436→1270, quiebres 954→899, inventario 945→855,
    config 994→527.
- ✅ 🔴 **Bug: restauración de filtros rota en clientes Y forecast (TypeError).**
  `restoreFilters` se llamaba ANTES de crear `this.state` (useState): con filtros
  guardados de una visita anterior el widget tiraba TypeError al remontarse (el Panel
  de Ventas crasheó en staging por el ForecastWidget); sin guardados, la restauración
  era un no-op. Venía de la ola de homogeneización del 2026-08-06 a la mañana
  (persistencia CA/FC). Corregido moviendo la llamada después de crear el estado; los
  demás widgets con persistencia (inventario, quiebres, OFs, OCs) ya tenían el orden
  correcto — verificado por script sobre los 6.
  *(`customer_analysis_widget.js`, `forecast_widget.js`.)*
- ✅ **(b) C5 cerrado — días de atraso en los KPI de alertas (decisión: máximo).**
  Las cards "OFs atrasadas" (Producción) y "Vencidas" (Compras) muestran el dato de
  días junto al conteo ("máx. 12 días"), con estadístico configurable en Ajustes →
  Alertas (`alert_delay_stat`: Máximo default / Promedio). Producción lo calcula desde
  la fecha de fin planificada de la OF de cada alerta activa; Compras sobre el mismo
  conjunto exacto del KPI (`kpi_overdue_rs`, por `date_planned`). Con conteo 0 no se
  muestra. Campo nuevo en la config ⇒ **requiere `-u`** (base v18.0.7.1.0).
- ✅ **(c) ARQUITECTURA.md actualizado y doc de sesión archivado.** El doc ahora cubre
  la suite de 3 módulos (tabla de módulos y depends), el split de la config, el Panel
  de Inventario (`mrp_planner_dashboard_inventory.py`, `mrp.dispatch.stock.log` /
  `mrp.planner.kpi.monthly`, campos `x_qty_*` de stock.picking), los grupos de
  Inventario/despacho (incluida la no-herencia intencional de `group_admin` →
  `group_inventory_admin`), los helpers `planner_*` y una sección completa de
  `odoo_mrp_planner_dispatch`. `docs/sesion-2026-08-03-panel-inventario.md` →
  `docs/archivo/` (describía el estado previo al split).

Pendiente de verificación (no había Odoo local): smoke test en staging de los 3
paneles refactorizados (filtros/orden/pestañas/selección/export/despacho masivo),
la card de días de atraso en Producción y Compras, y el `-u odoo_mrp_planner`.

## Consistencia KPI ↔ sublistas del Panel de Inventario (2026-08-07)

Reporte: al abrir "Ver →" en las cards, la columna "Demanda (Pz)" no cuadraba con
el KPI ni con Con stock + Sin stock de la misma lista.

- 🔴 **Causa:** la columna "Demanda (Pz)" usaba `x_qty_pending_store`, un campo
  ALMACENADO que sumaba TODAS las líneas pendientes del remito **sin el recorte por
  rango de fechas**, mientras el KPI y las columnas Con/Sin stock usan la demanda
  **del rango** (por línea, vía contexto `planner_date_from/_to`). Resultado: KPI =
  Con stock + Sin stock, pero ≠ "Demanda (Pz)"; y dentro de la lista las tres no
  cerraban. Además, las recepciones mostraban Con stock calculado en el drill mientras
  el panel las fuerza a 0.
- ✅ **Fix (v18.0.7.2.0, requiere `-u`):** se reemplazó `x_qty_pending_store` por
  `x_qty_pending_chain`, calculado por el mismo `_compute_x_qty_chain` y con el mismo
  universo del rango, de modo que **Demanda = Con stock + Sin stock** y el total al pie
  cierra con el KPI. Se agregó la regla de recepciones (Con stock = 0) al compute. El
  campo almacenado quedó eliminado.
- **#1:** se probó mostrar las 3 columnas también en "Validados del período", pero
  para remitos entregados Con/Sin stock no aplican (Demanda = Con stock, Sin stock = 0)
  y confundía; decisión de Franco: el drill de Validados vuelve a una sola columna
  "Cantidad hecha". Las sublistas de pendientes conservan las 3.
- **Redondeo KPI ↔ total de la lista:** con "Forzar cantidades enteras" el KPI redondea
  por fila y la lista suma en crudo (decimales), de ahí un residual de pocas piezas
  sobre millones (< 0,0001%). Decisión de Franco: se deja así (cosmético).
- **Límite conocido (respuesta a "¿suma por grupo?"):** al ser recortadas por fecha,
  las tres columnas no pueden almacenarse ⇒ **totalizan al pie** (suma de las filas
  cargadas, que es lo que cuadra con el KPI) pero **no por grupo** si se agrupa la
  lista manualmente. Es intrínseco a un valor dependiente del rango en una lista nativa.
  Residual posible de ±1 por el redondeo "Forzar cantidades enteras".
- **#3 — diferencia vs. "Análisis de movimientos" nativo: es intencional, no un bug.**
  El panel acota además por universo de tipos de la compañía, por el/los depósito(s)
  seleccionados o permitidos, por estado del remito (confirmado/en espera/preparado) y
  por el corte de antigüedad de Ajustes; el filtro nativo sobre `stock.move` no tiene
  esas restricciones, por eso da mayor. Sin cambio de código.

## Criterio Con/Sin stock configurable por estado del movimiento (2026-08-10)

Franco observó que el criterio "por cadena" marcaba casi todo como "con stock"
(un subcontratista "en espera de otra operación" figuraba con stock porque un
eslabón anterior tenía reserva), y que operaciones internas presentes en el
Análisis de movimientos nativo no aparecían en la lista del panel.

- ✅ **Decisión (v18.0.7.3.0, requiere `-u`):** el panel deja de usar la
  disponibilidad por cadena y clasifica Con/Sin stock por **estado del
  stock.move**, configurable en Ajustes → Inventario. "Con stock" suma solo la
  **cantidad reservada** del movimiento (parcialmente disponible: solo esa
  parte), así Demanda = Con stock + Sin stock cierra.
  - 4 estados editables (Con/Sin stock), defaults acordados con Franco:
    Disponible = con, Parcialmente disponible = con, En espera de
    disponibilidad = sin, En espera de otro movimiento = sin.
  - Draft/Cancel no cuentan; Done va a Validados (fijos, descritos en Ajustes).
- ✅ **Cierra el #2:** al filtrar filas por estado del movimiento (como el
  nativo) en vez de por estado del remito, las operaciones internas que
  faltaban entran a la lista. Se eliminó el override de recepciones (una
  recepción "Lista" reservó su cantidad → con stock, por el mismo criterio).
- **No se tocó** la Tasa de entrega s/ disponible (snapshots/consolidado):
  conserva su definición por cadena, es una métrica histórica aparte.
- Pendiente de verificación en staging (no había Odoo local): que los números
  del panel cierren con el nativo filtrando por los mismos estados, y el
  comportamiento de las recepciones "Listas".

## Auditoría v18.0.7.4.0 (2026-08-10)

Auditoría de los tres módulos partiendo del estado post-refactor y post-cambios
de inventario. Resultado: **sin defectos accionables**; el detalle:

- **Refactor anterior — verificado por código (no había Odoo local):**
  - Split de `mrp.reschedule.config` en 4 archivos: **114 campos, cero
    duplicados, cero pérdidas** (los 109 documentados + 4 `inventory_state_*`
    del 2026-08-10 + 1 `alert_delay_stat` de C5; todo explicado).
  - `restoreFilters` se llama **después** de `useState` en los 6 widgets con
    persistencia (no se reintrodujo el orden roto).
  - Los 4 mixins (`planner_table/selection/multiselect/export`) exportan e
    importan sin referencias rotas; `planner_multiselect` solo en inventario y
    quiebres (clientes no tiene dropdowns multi-select — correcto).
- **`mrp_dispatch_stock_log.py` (604 líneas) — cohesivo, sin dividir.** Es un
  único subsistema: pipeline de la Tasa de entrega s/ disponible (snapshot
  diario → consolidado mensual → retención → cálculo de tasa), con dos modelos
  acoplados (`mrp.dispatch.stock.log` + `mrp.planner.kpi.monthly`). Sin código
  muerto. Seguridad: el cron `_cron_dispatch_snapshot` es de sistema, itera
  empresas con sudo y acota **cada** búsqueda/creación por `company_id`; los
  `sudo()` son propios de un modelo de fondo y están explicados en docstrings.
  Nota menor de estilo: un par de `sudo()` no tienen comentario inline (sí en
  docstring) — no es un hallazgo de seguridad.
- **Criterio Con/Sin stock por estado del movimiento — verificado completo.**
  Los 4 estados configurables (Disponible / Parcialmente disponible / En espera
  de disponibilidad / En espera de otro movimiento) cubren **todos** los estados
  pendientes reales de `stock.move`; draft/cancel quedan excluidos y done va a
  Validados, así que **ningún estado queda sin clasificar**. `Demanda = Con
  stock + Sin stock` cierra para **cualquier** configuración (sin = demanda −
  con, con = mín(reservado, demanda) ≤ demanda). No quedó ningún resabio del
  criterio viejo "por cadena" en el panel: la única llamada a
  `_chain_available_qty()` es la de la tasa/snapshots (línea 331), que conserva
  ese criterio a propósito.
- **`mrp_planner_dashboard_customer.py` (~961 líneas) — se deja como está.** Es
  una responsabilidad grande pero cohesiva: dos RPC (`get_customer_analysis_data`
  ~525 líneas y `get_customer_detail` ~358) del análisis de clientes. Dividir en
  archivos agregaría acoplamiento sin beneficio funcional. Se anota como backlog
  (opcional, sin urgencia) un refactor **interno** —extraer métodos privados
  (`_load_period_data`, `_unify_by_vat`, cálculo de lead time), reusar
  `mrp_abc_helpers._assign_abc_pareto` en vez del ABC inline, y unificar
  `_to_date`/`_parse_date`—; no se toca ahora porque es código que anda y sin
  motivo funcional el riesgo no se justifica (el ABC inline podría diferir a
  propósito del ABC de categorías).
- **Seguridad y código muerto (barrido general):** sin código muerto en los tres
  módulos (verificado por string); guards de grupo en los 3 RPC del panel de
  inventario; filtrado por depósito sigue entrando por `_inventory_effective_whs`
  / universo de tipos; los 4 campos `inventory_state_*` heredan
  `groups=group_inventory_admin` de la pestaña Inventario. Falso positivo
  verificado: `_dispatch_chain_keys()` no valida `company_id` de sus ids, pero es
  interno y sus únicos callers (pipeline de snapshot/tasa) ya vienen acotados por
  compañía — no es explotable.

## Cumplimiento Producido vs Programado — ponderado y configurable (2026-08-10)

Franco planteó que el KPI global del comparativo era poco representativo para un
mix de producción. Diagnóstico: el número era `Σ producido / Σ programado` sobre
cantidades crudas → (1) mezclaba unidades de medida, (2) la sobreproducción de un
producto compensaba el faltante de otro, (3) lo dominaba el producto de mayor
volumen. Decisión (charlada y acordada): hacerlo **configurable**.

- ✅ **Implementado (v18.0.7.7.0, requiere `-u`):**
  - Ajustes → Producción, **"Ponderación del cumplimiento"**: Cantidad / Valor–
    precio de venta / Valor–costo / Horas de CT (peso por unidad; horas = tiempo
    de la ruta de la BoM). Default **Valor–costo**. Cada opción aclara en el help
    su requisito de dato.
  - **"Cumplimiento con tope al 100% por producto"** (fill rate), default **activo**:
    la sobreproducción de un producto no compensa el faltante de otro.
  - Fórmula global: `Σ(mín(prod,prog)·w) / Σ(prog·w) × 100` (con tope) — ver
    `docs/formulas.md` §1.4b.
  - **Tarjeta nueva "Productos en target"** (§1.4c): conteo mix-justo (cada
    producto pesa igual) de cuántos llegaron al umbral verde.
  - Las tarjetas Programado / Producido / Desvío se muestran en la magnitud
    ponderada ($ u horas); los productos sin el dato (precio/costo/ruta) se
    excluyen con aviso visible en el panel.
- **Alcance:** la tabla por producto no se tocó (sigue por cantidad; su % por
  fila es §1.4). El default cambia el número respecto de la versión anterior
  (era Cantidad sin tope) — decisión aceptada por Franco.
- Pendiente de verificación en staging (sin Odoo local): en especial la
  ponderación por Horas de CT, que es una aproximación (Σ tiempo de operaciones
  ÷ cantidad de la BoM); confirmar que las BoM de Giacomelli tengan operaciones.

## Filtro numérico por columna en Quiebres de stock (2026-08-10)

A pedido de Franco, la tabla de quiebres gana un filtro numérico estilo Odoo
sobre las columnas numéricas (Stock actual, Mínimo, Pronóstico, Plazo fab.,
Rotación).

- ✅ **Implementado (v18.0.7.8.0):** botón "Filtro numérico" con popover que arma
  condiciones `columna [>, ≥, <, ≤, =, ≠] (valor | otra columna)`. "Contra qué"
  puede ser un número fijo **o** otra columna numérica (ej. "Stock < Mínimo",
  "Pronóstico < Mínimo"). Cada condición queda como chip removible; se combinan
  con **Y**. Todo client-side (el dataset ya está cargado), instantáneo.
- Compone con el resto: búsqueda + tipo + ubicación + numérico aplican juntos, y
  la agrupación (pestañas) y los KPIs/totales se calculan sobre ese conjunto ya
  filtrado (`_applyCommonFilters` es la base común de la tabla y de
  `baseFilteredForGroups`). Persistido en `numFilters` (sobrevive al remontaje).
- La igualdad/desigualdad usa tolerancia (1e-6) para floats; las filas sin dato
  en la columna comparada no matchean.

## Backlog post-producción

- **Umbrales de % hardcodeados** en forecast/comparativo (95/80 y 90/50) vs. los
  configurables del análisis de clientes — diferencia aceptada por ahora.
