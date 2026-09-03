# Sesión 2026-09-02 — Modo ruta del tablero + cascada parciales + prueba de motores (button_plan y demanda)

Rama única de trabajo: **`18.0-analisis-produccion`** (18.0 es prod intocable).
Módulo tocado: **`odoo_mrp_planner_scheduling`** (+ un archivo de `odoo_mrp_planner`
leído para verificación). 26 commits, todos pusheados a origin.

Instancia de test (Odoo.sh, DB neutralizada): 
- host XML/JSON-RPC: `https://deglia-capemi-test-37236453.dev.odoo.com`
- DB: `deglia-capemi-test-37236453` · login `Deglia` (uid 2).
- **La API key se ROTA seguido**: si `authenticate` devuelve `uid=False`, pedir una
  key nueva (Settings → Users → API Keys). El DB/host se mantienen.
- **OJO: el reloj de la instancia está en ~15/02/2027.** Los datos existentes son
  mayormente sep-oct 2026, pero `now()` = feb 2027 → toda planificación nueva
  arranca en feb 2027.

---

## 1. MODO RUTA del tablero de scheduling ("Ver ruta de una OF")

### Objetivo (confirmado con el usuario)
Ver el **CAMINO** de una OF: su cadena de padres/hijas (por `origin`), ubicada en
el tiempo, conectada por un **hilo**. NO es la carga del centro. Ver
[[modo_ruta_objetivo]] en memoria.

### Estado final — cómo quedó (todo desplegable)
- **Filas = CTs** (igual que el Gantt común). Las OFs son los "escalones": cada OF
  aparece en su(s) centro(s) y, al pasar CT1→CT2→CT3 en el tiempo, forma un
  escalonado. **NO** cambiar filas a OFs (error que rechazó fuerte el usuario).
- **Solo la cadena**: `get_route_board` pasa `only_mo_ids=tree_ids` a
  `_build_board_payload` → solo barras de la cadena, no todas las del centro.
- **OFs sin programar** (93% de WOs sin `date_start`): se dibujan igual con
  **fallback por fechas de la MO** (una barra por centro de su ruta), estilo
  "sin programar" (`sm-bar-unsched`: rayado + borde punteado + badge; `wo_id`
  nulo lo dispara). El fallback aplica a TODA la cadena.
- **Solo la OF ENFOCADA fuerza sus CTs** (`force_wc_ids = focus`). Los CTs de
  OFs del árbol aparecen solo si tienen barra. Filtro defensivo extra en
  `get_route_board`: descarta filas de CT sin barras salvo la enfocada.
- **Colapsar vacíos** (toggle, default ON): `makeTimeScale` colapsa por INTERVALO
  (no día entero) los tramos sin OFs de la cadena — corta huecos y horas muertas.
  `_occupiedIntervals` en el cliente arma los tramos con margen.
- **Gutter** (`GUTTER_MIN=90` en scheduling_geometry.js): separación visible a
  cada lado del corte del eje; la marca ✂ va en el medio.
- **Finde con trabajo**: `forceVisibleDays` — un día de finde con barras NO se
  colapsa aunque "Ocultar fines de semana" esté activo; se marca en el header
  (ámbar + ícono).
- **Orden de filas** cronológico (por barra más temprana de cada CT) = coincide
  con el panel lateral.
- **`_compute_route` en ORDEN TOPOLÓGICO** por `blocked_by_workorder_ids` (Kahn),
  con `sequence` de respaldo. (El `sequence` del workorder está invertido vs las
  dependencias en el ~89% de las OFs — no es fuente de orden fiable.)
- **Auto-zoom por ancho de viewport** (`_fitRouteZoom`): elige la resolución más
  fina cuyo contenido colapsado entra en pantalla.
- **Filtro de ESTADO multi-selección** (default Confirmada + En proceso) reemplaza
  el toggle "Mostrar terminadas". Aplica a barras Y al árbol (padres+hijas).
- **Marca de OF seleccionada**: PUNTO violeta en la esquina (`sm-bar-focus::after`),
  NO tiñe la barra (violeta ≠ color de estado). Multi-selección con **Shift**
  (panel o barras). El buscador NO se aplica en modo ruta.
- **Hilo conector** (Fase 2): `route_edges` (aristas componente→consumidora,
  resueltas por nombre base para parciales, política = más cercana en el tiempo).
  Dibuja **TODAS** las aristas de la cadena (SVG overlay en `.sm-rows`, violeta,
  flecha en el sentido del flujo). Las barras "sin programar" se dibujan
  CONTINUAS (no partidas por día no laborable) — son ventana estimada.
- **Texto en barras angostas**: container queries — cae la línea 2, luego el badge,
  y por último muestra el NÚMERO de OF (`shortRef`); detalle completo en tooltip.

### Bug de raíz encontrado al final (importante)
El filtro de búsqueda (`matchBar`) se aplicaba a las barras **también en modo
ruta**. El buscador está oculto en ruta pero su valor persiste → si el usuario
buscó la OF por texto antes de "Ver ruta", solo pasaban las barras cuyo
mo_name/producto lo contenían → se perdían las relacionadas. Fix `cd5787c`:
en modo ruta NO se aplica `matchBar`.

### PENDIENTE del modo ruta
- Fase 2 drag&drop (arrastrar la OF, no la operación — ver
  [[wo_sin_planificar_button_plan]]). El diseño ya lo soporta.
- Atenuado de contexto (distinguir movido-por-cascada de lo-que-quedó) — reservado
  para cuando se toque esa parte.

---

## 2. CASCADA de reprogramación — fix de parciales (commit 7beaf10)

Mismo bug que el modo ruta: las MO **partidas** (`XX/MO/NNNNN-PPP`) citan en
`origin` el nombre BASE (`XX/MO/NNNNN`), pero el padre real está partido → el
matcheo por nombre exacto perdía toda la descendencia. Verificado: pivot parcial
CP/MO/04069-001 → hijas por nombre completo = 0, por base = 13.
Fix: `_get_child_mos` y `_preload_child_mos_batch` buscan por nombre **completo +
base**. `_base_name` movido al mixin (fuente única). Ver [[origin_compuestos_reschedule]].
Las OC por origin (`_get_pos_for_mo`) NO se tocaron (no se sabe si citan base o
completo — revisar si aparece el problema).

---

## 3. PRUEBA de `button_plan` (Odoo core) — 5 OFs de staging

Ver [[button_plan_dependencias]]. Se planificaron 5 OFs (43277 CP/MO/04015, 43286,
45035, 45071, 44914 TN/MO/02999). **Quedan planificadas** — revertir con
`env['mrp.production'].browse([43277,43286,45035,45071,44914]).button_unplan()`.

Hallazgos:
- button_plan **respeta `blocked_by`** (encadena) y **reasigna a CTs alternativos**
  para balancear (CAL01↔CAL02/03/04, CE01↔CE02..06, Cuba01↔Cuba02/03).
- Donde una OF NO tiene dependencias (TN), pone las 3 operaciones **en paralelo**
  al `date_start` de la MO → físicamente imposible. Es problema de DATOS de ruta.
- Alcance (OFs activas, nivel workorder): 1.518 multi-op → 1.295 full, 24
  parciales, **199 SIN dependencias (~13%)**.
- El `sequence` del workorder está **invertido** vs `blocked_by` en **1.177 de
  1.319 (89%)** de las OFs con deps. Sistémico.
- Todos los CTs usan calendarios tipo "Jornada de Xhs" (ej. 8hs = 6-14 Lun-Sáb).

---

## 4. MOTOR DE DEMANDA (`mrp.production.request`, wizard "Programaciones")

Prueba end-to-end SIN crear OFs: se crea un request scratch → `action_calculate`
(el paso previo a crear OFs) → se leen las líneas → **se borra** el request.
Producto de prueba: **"Buje semi terminado CEP" (id 46469)** — 7 niveles de
fabricación (CP→VL→Ext/Int AD→TS→MC subcontrato + COMP MEZCLA), operaciones con
`blocked_by`, mezcla fabricar/subcontratar/stock/materia prima.

### Cómo funciona (código: `mrp_demand_expansion_mixin` + `mrp_demand_scheduling_mixin`)
- `action_calculate` → `_build_demand_tree` (explosión) → `_get_wc_anchors_multi`
  (carga existente) → `_schedule_tree` (bottom-up) → `_collect_lines`.
- Explosión: recursiva multinivel por BOM; salta phantom; fabricar recursiona,
  comprar/subcontratar/stock son hojas.
- Scheduling **bottom-up**: hijas primero; `after_dt = max(start, children_end,
  hoy)` → el padre arranca tras terminar las hijas. Comprados: no antes de
  `hoy + lead_days`.
- Calendario: `_schedule_duration` (compartido con la cascada) recorre los turnos
  de cada CT.

### Análisis (con números reales)
- Explosión de BOM: **✅ correcta, todos los niveles**.
- Dependencia hija→padre: **✅ verificada** (VL termina 17/02 → CP arranca 25/02).
- Calendario: **✅** respeta el de cada CT.
- **Merma: ❌ no se aplica** ningún factor (cantidades 1:1 por BOM). PENDIENTE que
  CAPEMI confirme si la merma ya está en las cantidades de la BOM. Si sí, nada que
  hacer.
- **Stock con `qty_available` (global, sin reservas): ⚠️ contaba material
  comprometido** → planificaba de menos (COMP MEZCLA on_hand 47 pero free_qty −30;
  Adhesivo 27/0). **ARREGLADO (commit 6549469): usa `free_qty`** (clamp a 0).
  Salvedad: `free_qty` no descuenta lo saliente-no-reservado (`outgoing_qty`);
  `virtual_available` sí pero suma entradas especulativas.
- **Almacén**: hay **16 almacenes por etapa** (Vulcanizado, Cepillo, Mezclado…).
  `free_qty` es global. Filtrar por almacén (de `picking_type_id`) queda PENDIENTE
  — necesita el modelo de flujo de stock entre etapas de CAPEMI.
- Centros: con `x_centros_compatibles` VACÍA (0 filas), cae en la ruta de la BOM
  (`op.workcenter_id`). Salvedades: (a) usaba el CT primario **sin alternativos**;
  (b) orden de operaciones por `op.sequence` invertido vs `blocked_by`; (c) el
  resumen de carga atribuía todo el OF al primer CT.

### CÓMO CALCULA LA CARGA EXISTENTE (ancla) — respuesta clave
`_get_wc_anchors_multi`: OFs `confirmed`/`progress`; por cada WO
`ancla = max(wo.date_finished OR mo.date_finished OR mo.date_start+dur)`.
**No usa `wo.date_start`.** Como el 93% de WOs no está planificado, casi todas
caen a `mo.date_finished` (poblado) → las anclas están **infladas** (el MO.fin se
aplica a TODOS sus CTs), no vacías. Con `button_plan` poblando `wo.date_finished`
se afinan (por WO, por CT).

### CAMBIO EN CURSO — centros alternativos (commit 8621a52, PENDIENTE VERIFICAR)
Implementado, **falta redeployar y correr el "después"**:
- `_build_demand_tree`: operaciones = `(primario, candidatos, dur)`;
  `_wc_candidates` = primario + `alternative_workcenter_ids` activos.
- `_schedule_tree`: elige el candidato que **termina más temprano** (empate →
  primario); guarda en `node['scheduled_ops']`.
- `_get_wc_anchors_multi`: junta anclas de TODOS los candidatos (si no, un
  alternativo sin ancla ganaría siempre).
- `_collect_lines`: cadena con CTs elegidos + marca `(alt)`; nueva bandera
  **`used_alternative`** en la línea.
- Resumen de carga (#5): desde `wc_collector` (por operación, CT elegido).

**ANTES (deploy previo a 8621a52):** CP = `Rebabado › CAL01 › CE01` (primarios),
arranca 25/02; carga = Rebabado 9.5h (todo a un CT).
**DESPUÉS esperado:** CAL01/CE01 reasignados a alternativos menos cargados,
CP termina antes, carga repartida, `used_alternative=True`.

### PENDIENTES del motor de demanda
3. **Merma** — esperar confirmación de CAPEMI (si la BOM ya la incluye, nada).
4. **Orden de operaciones por `blocked_by`** en vez de `sequence` — no afecta
   fechas cuando comparten calendario; hacerlo al tocar esa parte.
5. Resumen de carga por CT — se arregló junto con el #2.
- Verificar #2 en vivo (después de redeploy) con la simulación CP 1000u.
- Filtro de stock por almacén (necesita modelo de flujo).

---

## Próximo paso inmediato
Redeployar `8621a52` y correr la simulación CP 1000u para comparar antes/después
del balanceo de alternativos. Script en `/tmp/simcmp.py` (efímero; recrear con la
key vigente). Todo con requests scratch que se borran — nunca crear OFs.
