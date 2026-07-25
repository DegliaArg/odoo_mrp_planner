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

## Backlog post-producción

- **Umbrales de % hardcodeados** en forecast/comparativo (95/80 y 90/50) vs. los
  configurables del análisis de clientes — diferencia aceptada por ahora.
- **C5 — Días de retraso/vencimiento no aparecen en los KPI de alertas.** Los KPI de
  alertas (producción y compras) solo muestran conteos, sin indicar cuántos días lleva el
  retraso o cuántos faltan para vencer. Pendiente definir qué dato mostrar (máximo,
  promedio u otro). *(`views/mrp_planner_dashboard_views.xml`,
  `models/mrp_planner_dashboard.py`, `static/src/js/alert_kpi_widget.js`.)*
