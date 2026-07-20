# Fórmulas de cálculo — Módulo de Planificación MRP

Notación: `max(a,b)` = máximo entre a y b · `min(a,b)` = mínimo · `floor(x)` = entero inferior ·
`abs(x)` = valor absoluto · `sum(...)` = suma de todos los elementos · `avg(...)` = promedio ·
`%` = porcentaje literal · subíndices con guion bajo (ej. `F_h` = "F con subíndice h").

---

## Panel de Producción

### 1.1.1 OFs atrasadas
DESCRIPCION: Se genera cuando una orden de fabricación activa tiene su fecha de fin planificada
en el pasado. Aplica a órdenes confirmadas, en progreso y por cerrar; excluye subcontratación.
VARIABLES:
- F = Fecha de fin planificada de la OF
- F_h = Fecha actual (hoy)
- U = Umbral de días críticos para OFs — 3 días por defecto
FORMULA: D = max(0, floor(F_h - F))
LABEL: Días de atraso
CONDICIONES:
- D >= U -> Crítica (roja)
- D < U -> Advertencia (amarilla)

### 1.1.2 OFs por vencer
DESCRIPCION: Se genera cuando una orden de fabricación activa tiene su fecha de fin dentro
de la ventana de aviso pero aún no ha vencido. Siempre se califica como advertencia.
VARIABLES:
- F = Fecha de fin planificada de la OF
- F_h = Fecha actual (hoy)
- U_av = Ventana de aviso en días — 7 días por defecto
FORMULA: F_h < F <= F_h + U_av
LABEL: Condición de próxima a vencer
CONDICIONES:
- Condición cumplida -> Advertencia (amarilla)

### 1.1.3 Cantidad diferente — desvío
DESCRIPCION: Se genera cuando una orden de fabricación recién cerrada produjo una cantidad
que difiere de la planificada más allá de la tolerancia configurada.
VARIABLES:
- Q_r = Cantidad real producida (suma de movimientos de producto terminado en estado Hecho)
- Q_p = Cantidad planificada de la OF
- T = Tolerancia de desvío porcentual — 5 % por defecto
FORMULA: delta = abs(Q_r - Q_p) / Q_p
LABEL: Desvío porcentual
CONDICIONES:
- delta > T and Q_r < Q_p -> Crítica (producción insuficiente, roja)
- delta > T and Q_r > Q_p -> Advertencia (excedente, amarilla)

### 1.1.4 OFs canceladas
DESCRIPCION: Se genera cuando una orden de fabricación pasa al estado Cancelada.
No se resuelve automáticamente; requiere acción manual del operador.
Excluye subcontratación.
VARIABLES:
- (sin fórmula numérica)
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Alerta por cancelación
CONDICIONES:
- OF pasa a estado Cancelada -> Advertencia (amarilla)

### 1.2 KPIs del panel OFs — contadores
DESCRIPCION: Cada tarjeta KPI cuenta órdenes de fabricación según su estado en el momento
de la consulta. Las categorías no se superponen; cada OF cuenta en un solo KPI.
VARIABLES:
- F = Fecha de fin planificada de la OF
- F_h = Fecha actual (hoy)
FORMULA: Activas = count(OFs con estado distinto de Terminada y Cancelada)
LABEL: OFs activas
CONDICIONES:
- estado = En progreso o Por cerrar -> En progreso (subconjunto de Activas)
- F < F_h (y estado activo) -> Atrasadas (subconjunto de Activas)
- OF marcada para reprogramar (y estado activo) -> Para reprogramar (subconjunto de Activas)

### 1.3 Cumplimiento de producción — por producto
DESCRIPCION: Compara lo producido con lo programado para cada producto en el período.
El criterio que determina qué OFs entran en el período se configura globalmente
y aplica tanto aquí como en la tabla de forecast.
VARIABLES:
- Q_prog = Suma de cantidades planificadas de OFs en el período para ese producto
- Q_prod = Suma de cantidades ya producidas de OFs en el período para ese producto
FORMULA: CumpPct = (Q_prod / Q_prog) * 100
LABEL: % Cumplimiento (0 si Q_prog = 0)
CONDICIONES:
- CumpPct >= 90 -> Verde
- CumpPct >= 50 -> Amarillo
- CumpPct < 50 -> Rojo

### 1.3b Cumplimiento de producción — KPIs globales
DESCRIPCION: Agrega el cumplimiento de todos los productos del período en un único indicador.
VARIABLES:
- Q_prog_tot = Suma de cantidades planificadas de todos los productos
- Q_prod_tot = Suma de cantidades producidas de todos los productos
FORMULA: CumpGlobal = (Q_prod_tot / Q_prog_tot) * 100
LABEL: % Cumplimiento global (0 si Q_prog_tot = 0)

### 1.3c Criterio de OFs por período — por fecha de cierre
DESCRIPCION: Solo entran en el período las OFs cuya fecha de fin planificada cae dentro del rango.
Se usa la cantidad planificada completa, sin prorrateo.
VARIABLES:
- F_fin = Fecha de fin planificada de la OF
- T0 = Inicio del período
- T1 = Fin del período
- Q_plan = Cantidad planificada total de la OF
FORMULA: Q_prog = Q_plan si T0 <= F_fin <= T1 ; 0 en caso contrario
LABEL: Cantidad al período — criterio fecha de cierre
CONFIG: Criterio de OFs por período = Por fecha de cierre (predeterminado)

### 1.3d Criterio de OFs por período — por solapamiento completo
DESCRIPCION: Entran todas las OFs activas durante cualquier parte del período. La cantidad
planificada se usa completa, sin prorrateo; una OF puede aparecer en varios períodos.
VARIABLES:
- T_ini = Fecha de inicio de la OF
- T_fin = Fecha de fin planificada de la OF
- T0 = Inicio del período
- T1 = Fin del período
- Q_plan = Cantidad planificada total de la OF
FORMULA: Q_prog = Q_plan si T_ini <= T1 and T_fin >= T0 ; 0 en caso contrario
LABEL: Cantidad al período — criterio solapamiento completo
CONFIG: Criterio de OFs por período = Por solapamiento completo

### 1.3e Criterio de OFs por período — proporcional por duración
DESCRIPCION: Entran todas las OFs activas durante el período. La cantidad planificada se
distribuye proporcionalmente al tiempo que la OF solapa el intervalo. El producido usa los
movimientos de stock reales con fecha dentro del período (no estimación).
VARIABLES:
- T_ini = Fecha de inicio de la OF
- T_fin = Fecha de fin planificada de la OF
- T0 = Inicio del período
- T1 = Fin del período
- Q_plan = Cantidad planificada total de la OF
FORMULA:
  solap = max(0, min(T_fin, T1) - max(T_ini, T0)) ;
  dur_total = T_fin - T_ini ;
  Q_prog = Q_plan * (solap / dur_total)
LABEL: Cantidad proporcional al período
CONFIG: Criterio de OFs por período = Proporcional por duración
CONDICIONES:
- Si T_ini o T_fin no están definidas -> se usa Q_plan completo (fallback a fecha de cierre)
- Si solap = 0 -> la OF no aporta cantidad al período

### 1.4 Horas disponibles en un centro de trabajo
DESCRIPCION: Capacidad real del centro de trabajo en el período, ajustada por su eficiencia.
Cuando el calendario no puede calcularse directamente, se estima en proporción a las horas
semanales de asistencia configuradas.
VARIABLES:
- H_cal = Horas hábiles del calendario laboral del centro de trabajo en el período
- E = Eficiencia del centro de trabajo en porcentaje (ej. 85 = 85 %)
FORMULA: H_disp = H_cal * (E / 100)
LABEL: Horas disponibles

### 1.5 Solapamiento parcial de una operación con el período
DESCRIPCION: Calcula qué fracción de una operación cae dentro del período seleccionado,
para sumar solo las horas que efectivamente corresponden al intervalo.
VARIABLES:
- s_i = Fecha de inicio de la operación i
- e_i = Fecha de fin de la operación i
- t0 = Inicio del período seleccionado
- t1 = Fin del período seleccionado
FORMULA: alpha_i = (min(e_i, t1) - max(s_i, t0)) / (e_i - s_i)
LABEL: Fracción solapada

### 1.5b Horas aportadas por operación
DESCRIPCION: Horas que la operación i aporta al período, según la fracción solapada.
VARIABLES:
- D_i = Duración esperada de la operación i (en minutos)
- alpha_i = Fracción solapada (ver 1.5)
FORMULA: h_i = (D_i / 60) * alpha_i
LABEL: Horas aportadas al período

### 1.6 Horas ejecutadas
DESCRIPCION: Horas de operaciones ya terminadas que solapan con el período.
VARIABLES:
- h_i = Horas aportadas por la operación i (ver 1.5b)
FORMULA: H_ejec = sum(h_i para operaciones en estado Terminada)
LABEL: Horas ejecutadas

### 1.6b Horas pendientes
DESCRIPCION: Horas de operaciones activas (cualquier estado excepto Terminada y Cancelada)
que solapan con el período.
VARIABLES:
- h_i = Horas aportadas por la operación i (ver 1.5b)
FORMULA: H_pend = sum(h_i para operaciones con estado distinto de Terminada y Cancelada)
LABEL: Horas pendientes

### 1.7 Tiempo libre del centro de trabajo
DESCRIPCION: Capacidad disponible que no está asignada ni ejecutada en el período.
VARIABLES:
- H_disp = Horas disponibles del centro de trabajo en el período (ver 1.4)
- H_ejec = Horas ejecutadas (ver 1.6)
- H_pend = Horas pendientes (ver 1.6b)
FORMULA: T_libre = max(0, H_disp - H_ejec - H_pend)
LABEL: Tiempo libre (horas)

### 1.7b Carga del centro de trabajo
DESCRIPCION: Porcentaje del tiempo disponible ocupado entre trabajo ya ejecutado y planificado.
VARIABLES:
- H_disp = Horas disponibles
- H_ejec = Horas ejecutadas
- H_pend = Horas pendientes
FORMULA: Carga = (H_ejec + H_pend) / H_disp * 100
LABEL: Carga % (0 si H_disp = 0)
CONDICIONES:
- Carga < 70 -> Verde
- Carga < 90 -> Amarillo
- Carga >= 90 -> Rojo

### 1.8 Quiebre de stock
DESCRIPCION: Un producto entra en quiebre cuando su stock en ubicaciones internas cae por
debajo del mínimo configurado en su punto de reorden (ruta Fabricación). Si hay varios
puntos de reorden, se toma el de mayor cantidad mínima.
VARIABLES:
- S = Stock actual en ubicaciones internas de la ubicación configurada
- Q_min = Cantidad mínima del punto de reorden de ruta Fabricación
FORMULA: DeltaStock = S - Q_min
LABEL: Diferencia de stock (negativa = quiebre)
CONDICIONES:
- S < Q_min (con tolerancia de 0.001) -> Quiebre
- S >= Q_min -> OK
- Sin punto de reorden configurado -> Sin mínimo

### 1.9 Rotación en quiebres de stock — por unidades
DESCRIPCION: Calcula los días de inventario a partir del stock promedio y el promedio mensual
de salidas (unidades físicas).
VARIABLES:
- S_ini = Stock al inicio del período (unidades)
- S_fin = Stock al final del período (unidades)
- Q_sal = Suma de unidades de salidas completadas en el período
- N = Cantidad de meses del período configurado
FORMULA: S_avg = (S_ini + S_fin) / 2 ; DIO = S_avg / (Q_sal / N) * 30
LABEL: Días de inventario — por unidades
CONFIG: Método de rotación en quiebres de stock = Por unidades

### 1.9b Rotación en quiebres de stock — por COGS
DESCRIPCION: Calcula los días de inventario valorando el stock al costo estándar y usando
el costo de las salidas (COGS) como denominador.
VARIABLES:
- S_ini_c = Stock inicial × costo estándar del producto
- S_fin_c = Stock final × costo estándar del producto
- COGS = Suma de (precio unitario × cantidad) de las salidas completadas en el período
- D = Días del período (meses configurados × 30)
FORMULA: S_avg_val = (S_ini_c + S_fin_c) / 2 ; DIO = D * S_avg_val / COGS
LABEL: Días de inventario — por COGS (a costo)
CONFIG: Método de rotación en quiebres de stock = Por COGS (a costo)

### 1.9c Rotación en quiebres de stock — por ventas
DESCRIPCION: Calcula los días de inventario valorando el stock al precio de lista y usando
las ventas netas (a precio de lista) como denominador.
VARIABLES:
- S_ini_p = Stock inicial × precio de lista del producto
- S_fin_p = Stock final × precio de lista del producto
- V_net = Suma de (precio unitario × cantidad) de las salidas valoradas a precio de lista
- D = Días del período (meses configurados × 30)
FORMULA: S_avg_val = (S_ini_p + S_fin_p) / 2 ; DIO = D * S_avg_val / V_net
LABEL: Días de inventario — por ventas (a precio de lista)
CONFIG: Método de rotación en quiebres de stock = Por ventas (a precio de lista)

### 1.10 Duración de una OF para reprogramación
DESCRIPCION: El sistema calcula la duración de la OF en este orden de prioridad: sumando
operaciones si existen, usando las fechas de la OF como fallback, o asumiendo 8 horas si
no hay ninguna referencia disponible.
VARIABLES:
- D_i = Duración esperada de la operación i (en minutos)
- F_ini = Fecha de inicio de la OF
- F_fin = Fecha de fin de la OF
FORMULA: H = sum(D_i / 60) si hay operaciones
LABEL: Duración (horas) — Prioridad 1 (con operaciones)
CONDICIONES:
- Sin operaciones pero con fechas -> H = F_fin - F_ini (en horas)
- Sin operaciones ni fechas -> H = 8 (horas fijas de fallback)

### 1.11 Delta de reprogramación
DESCRIPCION: Diferencia entre la nueva fecha de fin propuesta y la actual, expresada en
días y horas enteras para mostrarse en la tabla del plan.
VARIABLES:
- F_nueva = Nueva fecha de fin propuesta
- F_actual = Fecha de fin actual de la OF
FORMULA: Delta_s = F_nueva - F_actual
LABEL: Delta en segundos (positivo = se adelanta, negativo = se atrasa)

### 1.11b Delta — visualización en días y horas
VARIABLES:
- Delta_s = Delta en segundos (ver 1.11)
FORMULA: d = floor(abs(Delta_s) / 86400) ; h = floor((abs(Delta_s) / 3600) % 24)
LABEL: Formato "+2d 3h" o "-1d 0h"

### 1.12 Escalado proporcional de operaciones
DESCRIPCION: Cuando se ajusta la duración total de una OF, cada operación se reescala
para mantener las proporciones relativas entre centros de trabajo.
VARIABLES:
- H_aj = Duración total ajustada de la OF (en horas)
- D_orig_i = Duración original de la operación i (en minutos)
FORMULA: epsilon = H_aj / sum(D_orig_i / 60) ; D_nueva_i = D_orig_i * epsilon
LABEL: Factor de escala y nueva duración de cada operación

### 1.13 Criterio de prioridad al reprogramar — orden cronológico
DESCRIPCION: Las órdenes de fabricación se ordenan por su fecha de inicio actual, de la
más próxima a la más lejana, antes de ejecutar la reprogramación en cascada.
VARIABLES:
- T_ini_j = Fecha de inicio actual de la OF j
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Ordenación cronológica
CONFIG: Criterio de prioridad al reprogramar = Orden cronológico (por fecha de inicio)
CONDICIONES:
- OFs ordenadas por T_ini_j ascendente

### 1.13b Criterio de prioridad al reprogramar — más cortas primero (SPT)
DESCRIPCION: Las órdenes de fabricación se ordenan por su duración calculada, de menor
a mayor, antes de ejecutar la reprogramación. Minimiza el tiempo promedio de espera
(Shortest Processing Time).
VARIABLES:
- H_j = Duración de la OF j según la lógica de la sección 1.10
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Ordenación SPT
CONFIG: Criterio de prioridad al reprogramar = Más cortas primero (SPT)
CONDICIONES:
- OFs ordenadas por H_j ascendente

### 1.13c Criterio de prioridad al reprogramar — secuencia manual
DESCRIPCION: El operador define el orden arrastrando las órdenes de fabricación en el
asistente de reprogramación antes de ejecutar. El sistema respeta ese orden sin modificarlo.
VARIABLES:
- (sin fórmula — el orden lo determina el usuario)
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Ordenación manual por el operador
CONFIG: Criterio de prioridad al reprogramar = Secuencia manual en el asistente
CONDICIONES:
- OFs procesadas en el orden definido por el usuario

---

## Panel de Compras

### 2.1.1 OCs vencidas — días de atraso
DESCRIPCION: Se genera cuando una OC aprobada tiene su fecha de entrega estimada en el pasado.
El campo de referencia es la fecha de entrega comprometida, no la fecha de emisión.
VARIABLES:
- F_ent = Fecha de entrega estimada de la OC
- F_h = Fecha actual (hoy)
- U_oc = Umbral crítico de días para OCs — 5 días por defecto
FORMULA: D = max(0, floor(F_h - F_ent))
LABEL: Días de atraso OC
CONDICIONES:
- D >= U_oc -> Crítica (roja)
- D < U_oc -> Advertencia (amarilla)

### 2.1.2 OCs por vencer
DESCRIPCION: Se genera cuando una OC aprobada y no completamente recibida tiene su fecha
de entrega dentro de la ventana de aviso pero aún no venció.
VARIABLES:
- F_ent = Fecha de entrega estimada de la OC
- F_h = Fecha actual (hoy)
- U_av_oc = Ventana de aviso en días para OCs — 10 días por defecto
FORMULA: F_h < F_ent <= F_h + U_av_oc
LABEL: Condición de OC próxima a vencer
CONDICIONES:
- Condición cumplida -> Advertencia (amarilla)

### 2.1.3 Recepciones atrasadas — días de atraso
DESCRIPCION: Se genera cuando una recepción pendiente de una OC tiene su fecha programada
en el pasado.
VARIABLES:
- F_rec = Fecha programada de la recepción
- F_h = Fecha actual (hoy)
- U_rec = Umbral crítico de días para recepciones — 3 días por defecto
FORMULA: D = max(0, floor(F_h - F_rec))
LABEL: Días de atraso recepción
CONDICIONES:
- D >= U_rec -> Crítica (roja)
- D < U_rec -> Advertencia (amarilla)

### 2.2 KPIs del panel OCs
DESCRIPCION: Clasificación de las OCs aprobadas según su estado respecto a la fecha de entrega.
VARIABLES:
- F_ent = Fecha de entrega estimada de la OC
- F_h = Fecha actual (hoy)
- U_oc = Umbral crítico de días para OCs
FORMULA: Vencidas = count(OCs aprobadas con F_ent <= F_h)
LABEL: OCs vencidas
CONDICIONES:
- F_ent > F_h -> A tiempo
- F_ent <= F_h -> Vencidas
- (F_h - F_ent) en días >= U_oc (y vencida) -> Críticas

### 2.3 Días de retraso de recepciones (columna tabla)
DESCRIPCION: Días de diferencia entre la fecha de cierre real y la fecha programada,
solo para recepciones ya completadas.
VARIABLES:
- F_real = Fecha en que se completó la recepción
- F_prog = Fecha programada de la recepción
FORMULA: D_ret = max(0, floor(F_real - F_prog))
LABEL: Días de retraso recepción

### 2.4 % A tiempo — análisis de proveedores
DESCRIPCION: Porcentaje de recepciones que llegaron en la fecha y hora programadas o antes.
La comparación es a nivel de fecha y hora exactas: una recepción que llega el mismo día
pero una hora después de la fecha programada se clasifica como tardía.
VARIABLES:
- n = Total de recepciones del proveedor en el período
- n_ot = Recepciones donde la fecha y hora de cierre es menor o igual a la fecha y hora programadas
FORMULA: OT_pct = (n_ot / n) * 100
LABEL: % A tiempo (precisión horaria)

### 2.4b % A tiempo global (ponderado)
DESCRIPCION: Indicador global que divide el total de recepciones a tiempo entre el total
de recepciones de todos los proveedores. Evita que proveedores con pocos envíos distorsionen
el resultado respecto a un promedio de porcentajes individuales.
VARIABLES:
- n_ot_k = Recepciones a tiempo del proveedor k
- n_k = Total de recepciones del proveedor k
FORMULA: OT_global = sum(n_ot_k) / sum(n_k) * 100
LABEL: % A tiempo global (ponderado)

### 2.5 Retraso promedio de entregas tardías
DESCRIPCION: Promedio de días de atraso calculado solo sobre las recepciones que
efectivamente llegaron tarde. No incluye recepciones en fecha.
VARIABLES:
- d_i = Días de atraso de la recepción i tardía: floor(fecha_cierre_i - fecha_prog_i)
- n_tard = Cantidad de recepciones tardías del proveedor
FORMULA: d_prom = sum(d_i) / n_tard
LABEL: Retraso promedio (días, solo tardías)

### 2.6 % Recepciones completas
DESCRIPCION: Porcentaje de recepciones que se completaron sin generar un pedido pendiente
(se recibió todo lo pedido en una sola entrega).
VARIABLES:
- n = Total de recepciones del proveedor en el período
- n_comp = Recepciones sin pedido pendiente generado
FORMULA: Comp_pct = (n_comp / n) * 100
LABEL: % Completas

### 2.7 Lead time promedio
DESCRIPCION: Tiempo promedio en días desde que se aprueba una OC hasta que se cierra
la recepción correspondiente.
VARIABLES:
- LT_i = Días desde la aprobación de la OC i hasta el cierre de su recepción
- n = Total de recepciones del proveedor en el período
FORMULA: LT_prom = sum(LT_i) / n
LABEL: Lead time promedio (días)

### 2.8 Variación de precio — referencia por costo estándar
DESCRIPCION: Diferencia porcentual firmada entre el precio pagado y el costo estándar del
producto. Negativa si el precio pagado fue menor al costo de referencia.
VARIABLES:
- p_i = Precio pagado por unidad en la línea i de la OC
- p_std_i = Costo estándar del producto en la línea i
- n = Total de líneas del proveedor en el período
FORMULA: v_i = (p_i - p_std_i) / p_std_i * 100 ; v_prom = sum(v_i) / n
LABEL: Variación promedio de precio vs. costo estándar (%)
CONFIG: Referencia para variación de precio = Costo estándar del producto (predeterminado)

### 2.8b Variación de precio — referencia por lista del proveedor
DESCRIPCION: Diferencia porcentual firmada entre el precio pagado y el precio configurado
en la lista de precios del proveedor para ese artículo. Las líneas sin precio de proveedor
configurado se excluyen del promedio.
VARIABLES:
- p_i = Precio pagado por unidad en la línea i de la OC
- p_prov_i = Precio de la lista del proveedor para ese artículo en la línea i
- n_v = Total de líneas del proveedor con precio configurado en el período
FORMULA: v_i = (p_i - p_prov_i) / p_prov_i * 100 ; v_prom = sum(v_i) / n_v
LABEL: Variación promedio de precio vs. lista del proveedor (%)
CONFIG: Referencia para variación de precio = Lista de precio del proveedor

### 2.9 Umbrales Pareto comunes (proveedores y clientes)
DESCRIPCION: Parámetros de corte que definen los límites entre categorías A, B, C, D y E
en todos los métodos automáticos de clasificación por Pareto acumulado.
VARIABLES:
- A_cum_k = Participación acumulada hasta el proveedor/cliente k (ordenado de mayor a menor valor)
- U_A = Umbral para A — 20 % por defecto
- U_B = Umbral para B — 50 % por defecto
- U_C = Umbral para C — 80 % por defecto
- U_D = Umbral para D — 95 % por defecto
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Categoría por Pareto acumulado
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 2.10 Categoría de proveedor — ABC por volumen
DESCRIPCION: Clasifica proveedores según el importe total de sus órdenes de compra en el
período configurado. Mayor importe = categoría más alta.
VARIABLES:
- V_k = Importe total de OCs del proveedor k en el período
- V_tot = Suma de V_k de todos los proveedores
- P_k = Participación individual del proveedor k
- A_cum_k = Acumulado de participaciones ordenado de mayor a menor
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: P_k = V_k / V_tot ; A_cum_k = sum(P_j para j <= k, ordenado por V_j desc)
LABEL: Participación acumulada por importe (proveedores)
CONFIG: Método de categoría de proveedor = ABC por volumen (importe de órdenes de compra)
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 2.11 Categoría de proveedor — ABC por frecuencia
DESCRIPCION: Clasifica proveedores según la cantidad de órdenes de compra realizadas en
el período configurado. Mayor cantidad de órdenes = categoría más alta.
VARIABLES:
- C_k = Cantidad de OCs del proveedor k en el período
- C_tot = Suma de C_k de todos los proveedores
- P_k = Participación individual
- A_cum_k = Acumulado de mayor a menor
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: P_k = C_k / C_tot ; A_cum_k = sum(P_j para j <= k, ordenado por C_j desc)
LABEL: Participación acumulada por frecuencia (proveedores)
CONFIG: Método de categoría de proveedor = ABC por frecuencia (cantidad de órdenes de compra)
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 2.12 Categoría de proveedor — ABC por RFM
DESCRIPCION: Clasifica proveedores en función de tres dimensiones: cuándo fue la última
compra (Recencia), con qué frecuencia compran (Frecuencia), y cuánto representan en valor
(Monetario). Cada dimensión otorga entre 1 y 3 puntos.
VARIABLES:
- R = Puntos de Recencia (1–3)
- F_rfm = Puntos de Frecuencia (1–3)
- M = Puntos de Monetario (1–3)
- S = Puntaje total
FORMULA: S = R + F_rfm + M
LABEL: Puntaje RFM total (proveedores)
CONFIG: Método de categoría de proveedor = ABC por RFM
CONDICIONES:
- S >= 8 -> A
- S >= 6 -> B
- S >= 4 -> C
- S = 3 -> D
- Sin datos en el período -> E

### 2.12b Puntos de Recencia
DESCRIPCION: Días transcurridos desde la última orden del proveedor hasta hoy.
VARIABLES:
- dias_ult = Días desde la última OC hasta hoy
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Puntos de Recencia (R)
CONDICIONES:
- dias_ult < 30 -> R = 3
- dias_ult < 90 -> R = 2
- dias_ult >= 90 -> R = 1

### 2.12c Puntos de Frecuencia
DESCRIPCION: Cantidad de órdenes de compra realizadas en el último año.
VARIABLES:
- n_ord = Cantidad de OCs en el último año
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Puntos de Frecuencia (F)
CONDICIONES:
- n_ord > 10 -> F_rfm = 3
- n_ord >= 3 -> F_rfm = 2
- n_ord < 3 -> F_rfm = 1

### 2.12d Puntos de Monetario
DESCRIPCION: Importe total de órdenes del período comparado contra los percentiles del grupo.
VARIABLES:
- M_k = Importe total de OCs del proveedor k
- P33 = Percentil 33 del grupo de proveedores
- P66 = Percentil 66 del grupo de proveedores
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Puntos de Monetario (M)
CONDICIONES:
- M_k >= P66 -> M = 3
- M_k >= P33 -> M = 2
- M_k < P33 -> M = 1

### 2.13 Categoría de proveedor — ABC por % entrega a tiempo
DESCRIPCION: Clasifica proveedores según el porcentaje de recepciones que llegaron en la
fecha y hora programadas o antes. Mayor % = categoría más alta.
VARIABLES:
- OT_k = % de recepciones a tiempo del proveedor k (ver 2.4)
- A_cum_k = Acumulado de mayor a menor OT_k
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: A_cum_k = sum(P_j para j <= k, ordenado por OT_j desc)
LABEL: Participación acumulada por % a tiempo (proveedores)
CONFIG: Método de categoría de proveedor = ABC por % de entrega a tiempo
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 2.14 Categoría de proveedor — ABC por variación de precio
DESCRIPCION: Clasifica proveedores según el valor absoluto de la variación de precio
promedio respecto al costo estándar. Clasificación ascendente: menor variación = mejor
categoría (A). Usa Pareto por posición relativa (percentil), no por acumulado de valor.
VARIABLES:
- absvar_k = Promedio de |precio línea - costo estándar| / costo estándar * 100 del proveedor k
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Categoría por variación de precio (ascendente)
CONFIG: Método de categoría de proveedor = ABC por variación de precio
CONDICIONES:
- Proveedores ordenados por absvar_k ascendente (menor variación primero)
- posición relativa del proveedor en el grupo <= U_A -> A
- posición relativa <= U_B -> B
- posición relativa <= U_C -> C
- posición relativa <= U_D -> D
- resto -> E

### 2.15 Categoría de proveedor — ABC por exactitud de cantidad
DESCRIPCION: Porcentaje de movimientos de recepción donde la cantidad recibida coincide
exactamente con la cantidad pedida (tolerancia de 0.001 unidades). Mayor % = categoría más alta.
VARIABLES:
- n_mov_k = Total de movimientos de recepción del proveedor k en el período
- n_exact_k = Movimientos donde abs(cantidad_recibida - cantidad_pedida) < 0.001
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: Exactitud_k = (n_exact_k / n_mov_k) * 100
LABEL: % Exactitud de cantidad por proveedor
CONFIG: Método de categoría de proveedor = ABC por calidad — diferencia de cantidad
CONDICIONES:
- Clasificación Pareto descendente (mayor exactitud = A)
- Umbrales U_A, U_B, U_C, U_D (ver 2.9)

### 2.16 Categoría de proveedor — ABC por devoluciones
DESCRIPCION: Clasifica proveedores según la cantidad de recepciones revertidas. Clasificación
ascendente: menos devoluciones = mejor categoría (A). Usa Pareto por posición relativa.
VARIABLES:
- dev_k = Cantidad de recepciones revertidas del proveedor k en el período
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Categoría por devoluciones (ascendente)
CONFIG: Método de categoría de proveedor = ABC por calidad — devoluciones
CONDICIONES:
- Proveedores ordenados por dev_k ascendente (menos devoluciones primero)
- posición relativa <= U_A -> A
- posición relativa <= U_B -> B
- posición relativa <= U_C -> C
- posición relativa <= U_D -> D
- resto -> E

### 2.17 Categoría de proveedor — ABC por calidad combinada
DESCRIPCION: Combina el % de entregas a tiempo y el % de exactitud de cantidad en una
métrica única. Mayor promedio = mejor categoría (A).
VARIABLES:
- OT_k = % de recepciones a tiempo del proveedor k (ver 2.4)
- Exactitud_k = % de exactitud de cantidad del proveedor k (ver 2.15)
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: Calidad_k = (OT_k + Exactitud_k) / 2
LABEL: Índice de calidad combinado
CONFIG: Método de categoría de proveedor = ABC por calidad — combinado (a tiempo y cantidad exacta)
CONDICIONES:
- Clasificación Pareto descendente (mayor Calidad_k = A)
- Umbrales U_A, U_B, U_C, U_D (ver 2.9)

---

## Panel de Ventas

### 3.1 Cantidad vendida y monto estimado
DESCRIPCION: La cantidad vendida suma las unidades en salidas completadas del período,
agrupando variantes bajo el mismo producto base. El importe es una aproximación porque
usa el precio de lista actual, no el precio real de cada venta.
VARIABLES:
- Q_v = Suma de unidades en salidas completadas del período para el producto
- P_L = Precio de lista vigente del producto
FORMULA: Importe_est = Q_v * P_L
LABEL: Importe estimado (usa precio de lista actual)

### 3.2 Categoría de venta — modo rotación de inventario (fuente entregas)
DESCRIPCION: Clasifica productos según cuántos días de stock quedan al ritmo de entregas
físicas completadas en el período. Menor cantidad de días = mayor rotación = categoría A.
VARIABLES:
- Q_ent = Unidades entregadas (salidas completadas) en el período
- M = Cantidad de meses del período de análisis — 3 por defecto
- S = Stock actual en ubicaciones internas
- U_A, U_B, U_C, U_D = Umbrales en días (30, 60, 90, 180 días por defecto)
FORMULA: Q_prom = Q_ent / M ; R = floor((S / Q_prom) * 30)
LABEL: Días de rotación (999 si Q_prom = 0)
CONFIG: Modo de categoría de venta = Automática por rotación de inventario
CONDICIONES:
- R <= U_A -> A
- R <= U_B -> B
- R <= U_C -> C
- R <= U_D -> D
- R > U_D o sin ventas -> E

### 3.2b Categoría de venta — modo rotación de inventario (fuente demanda OV)
DESCRIPCION: Igual que 3.2 pero el denominador usa las unidades pedidas en órdenes de venta
confirmadas del período, en lugar de las entregas físicas.
VARIABLES:
- Q_dem = Unidades en órdenes de venta confirmadas del período
- M = Cantidad de meses del período de análisis
- S = Stock actual en ubicaciones internas
- U_A, U_B, U_C, U_D = Umbrales en días (30, 60, 90, 180 días por defecto)
FORMULA: Q_prom = Q_dem / M ; R = floor((S / Q_prom) * 30)
LABEL: Días de rotación por demanda (999 si Q_prom = 0)
CONFIG: Fuente del denominador de rotación = Demanda confirmada (órdenes de venta)
CONDICIONES:
- R <= U_A -> A
- R <= U_B -> B
- R <= U_C -> C
- R <= U_D -> D
- R > U_D o sin demanda -> E

### 3.3 Categoría de venta — modo demanda
DESCRIPCION: Clasifica productos por su promedio mensual de unidades entregadas.
Mayor volumen mensual = categoría más alta.
VARIABLES:
- Q_ent = Unidades entregadas (salidas completadas) en el período
- M = Cantidad de meses del período de análisis — 3 por defecto
- U_A, U_B, U_C, U_D = Umbrales en u/mes (100, 50, 20, 5 por defecto)
FORMULA: Q_prom = Q_ent / M
LABEL: Promedio mensual de entregas
CONFIG: Modo de categoría de venta = Automática por demanda
CONDICIONES:
- Q_prom >= U_A -> A
- Q_prom >= U_B -> B
- Q_prom >= U_C -> C
- Q_prom >= U_D -> D
- Q_prom < U_D -> E

### 3.4 Categoría de venta — modo participación acumulada por unidades
DESCRIPCION: Clasifica productos por su participación acumulada en el total de unidades
entregadas en el período. Los que acumulan la mayor parte primero son A.
VARIABLES:
- Q_k = Unidades entregadas del producto k en el período
- Q_tot = Suma de Q_k de todos los productos
- P_k = Participación individual
- A_cum_k = Participación acumulada de mayor a menor
- U_A, U_B, U_C, U_D = Umbrales (50, 80, 95, 99 % por defecto)
FORMULA: P_k = Q_k / Q_tot ; A_cum_k = sum(P_j para j <= k, ordenado por Q_j desc)
LABEL: Participación acumulada por unidades
CONFIG: Modo de categoría de venta = Automática por participación acumulada (Pareto) — por unidades entregadas
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 3.4b Categoría de venta — modo participación acumulada por importe
DESCRIPCION: Igual que 3.4 pero ordena por importe (unidades entregadas × precio de lista actual)
en lugar de por unidades.
VARIABLES:
- V_k = Unidades entregadas del producto k × precio de lista actual del producto k
- V_tot = Suma de V_k de todos los productos
- P_k = Participación individual por importe
- A_cum_k = Participación acumulada de mayor a menor
- U_A, U_B, U_C, U_D = Umbrales (50, 80, 95, 99 % por defecto)
FORMULA: P_k = V_k / V_tot ; A_cum_k = sum(P_j para j <= k, ordenado por V_j desc)
LABEL: Participación acumulada por importe
CONFIG: Modo de categoría de venta = Automática por participación acumulada (Pareto) — por importe (precio lista × cantidad)
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 3.5 Forecast — KPIs globales: cobertura
DESCRIPCION: Compara las órdenes de fabricación planificadas contra el forecast para el período.
Un valor mayor a 100 % indica que hay más producción planificada que la demanda forecasteada.
VARIABLES:
- Q_OF = Suma de cantidades planificadas de OFs en el período
- F_tot = Suma de cantidades de todas las líneas de forecast del período
FORMULA: Cobertura = (Q_OF / F_tot) * 100
LABEL: % Cobertura de forecast (0 si F_tot = 0)
CONDICIONES:
- Cobertura >= 100 -> Verde
- Cobertura >= U_aviso (configurable, 70 % por defecto) -> Amarillo
- Cobertura < U_aviso -> Rojo

### 3.5b Forecast — Gap de OFs
VARIABLES:
- Q_OF = Suma de cantidades de OFs del período
- F_tot = Suma de forecast del período
FORMULA: Gap_OF = Q_OF - F_tot
LABEL: Gap de OFs (negativo = déficit de cobertura)
CONDICIONES:
- Gap_OF >= 0 -> Verde
- Gap_OF / F_tot * 100 >= -10 -> Amarillo
- Gap_OF / F_tot * 100 < -10 -> Rojo

### 3.6 Forecast — tasa de servicio global
DESCRIPCION: Mide qué fracción de la demanda de órdenes de venta confirmadas fue
efectivamente entregada en el período.
VARIABLES:
- Q_ent = Suma de unidades entregadas del período para productos con forecast
- D_OV = Suma de unidades pedidas en órdenes de venta confirmadas o cerradas del período
FORMULA: TasaServicio = (Q_ent / D_OV) * 100
LABEL: Tasa de servicio % (— si D_OV = 0)
CONDICIONES:
- TasaServicio >= 95 -> Verde
- TasaServicio >= 80 -> Amarillo
- TasaServicio < 80 -> Rojo

### 3.7 Forecast — Gap de demanda global
DESCRIPCION: Diferencia porcentual entre la demanda real de órdenes de venta y el forecast.
Positivo significa que la demanda superó el forecast; negativo que fue menor.
VARIABLES:
- D_OV = Demanda en órdenes de venta confirmadas del período
- F_tot = Forecast total del período
FORMULA: Gap_D = (D_OV - F_tot) / F_tot * 100
LABEL: Gap de demanda % (— si F_tot = 0)
CONDICIONES:
- abs(Gap_D) <= 10 -> Verde (demanda alineada con forecast)
- abs(Gap_D) <= 25 -> Amarillo (desvío moderado)
- abs(Gap_D) > 25 -> Rojo (desvío significativo)

### 3.8 Forecast — % cobertura de OFs por celda (denominador: forecast)
DESCRIPCION: Para cada combinación de producto y mes, compara las OFs planificadas con
el forecast de ese producto en ese mes. El denominador es el forecast planificado.
VARIABLES:
- F_t = Forecast del producto para el mes t
- Q_OF_t = Suma de cantidades de OFs del producto para el mes t
FORMULA: CobPct_t = (Q_OF_t / F_t) * 100
LABEL: % Cobertura por celda — base forecast (0 si F_t = 0)
CONFIG: Divisor del % de cobertura de OFs = Forecast planificado (predeterminado)
CONDICIONES:
- CobPct_t >= 100 -> Verde
- CobPct_t >= U_aviso (configurable, 70 % por defecto) -> Amarillo
- CobPct_t < U_aviso -> Rojo

### 3.8b Forecast — % cobertura de OFs por celda (denominador: demanda OV)
DESCRIPCION: Igual que 3.8 pero el denominador son las unidades en órdenes de venta
confirmadas del mes en lugar del forecast planificado.
VARIABLES:
- D_OV_t = Unidades en órdenes de venta confirmadas del producto en el mes t
- Q_OF_t = Suma de cantidades de OFs del producto para el mes t
FORMULA: CobPct_t = (Q_OF_t / D_OV_t) * 100
LABEL: % Cobertura por celda — base demanda OV (0 si D_OV_t = 0)
CONFIG: Divisor del % de cobertura de OFs = Demanda real (pedidos de órdenes de venta)
CONDICIONES:
- CobPct_t >= 100 -> Verde
- CobPct_t >= U_aviso -> Amarillo
- CobPct_t < U_aviso -> Rojo

### 3.9 Forecast — tasa de servicio y gap de demanda por celda
VARIABLES:
- Q_ent_t = Unidades entregadas del producto en el mes t
- D_OV_t = Demanda en órdenes de venta del producto en el mes t
- F_t = Forecast del producto en el mes t
FORMULA: SvcRate_t = (Q_ent_t / D_OV_t) * 100 ; GapD_t = (D_OV_t - F_t) / F_t * 100
LABEL: Tasa de servicio y gap de demanda por celda (— si denominador = 0)

### 3.10 Rotación de inventario en forecast — por unidades
DESCRIPCION: Para cada producto en el forecast, indica cuántos días (o meses) de stock
quedan al ritmo de entregas del período del forecast.
VARIABLES:
- Q_ent = Unidades entregadas en el período del forecast
- M = Cantidad de meses del período
- S = Stock actual en ubicaciones internas
FORMULA: Q_prom = Q_ent / M ; R_m = S / Q_prom ; R_d = floor(S / Q_prom * 30)
LABEL: Rotación en meses y días (— si Q_prom = 0)
CONFIG: Método de rotación de inventario en forecast = Por unidades (entregas físicas)
CONDICIONES:
- R_m <= 3 -> Verde ; R_m <= 6 -> Amarillo ; R_m > 6 -> Gris
- R_d <= 90 -> Verde ; R_d <= 180 -> Amarillo ; R_d > 180 -> Gris

### 3.10b Rotación de inventario en forecast — por COGS
DESCRIPCION: Calcula los días de inventario valorando el stock al costo estándar y usando
el costo de las salidas (COGS) como denominador. El período es el rango del forecast.
VARIABLES:
- S_ini_c = Stock al inicio del período × costo estándar del producto
- S_fin_c = Stock al final del período × costo estándar del producto
- COGS = Suma de (precio unitario × cantidad) de las salidas completadas en el período
- D = Días del período del forecast
FORMULA: S_avg_val = (S_ini_c + S_fin_c) / 2 ; DIO = D * S_avg_val / COGS
LABEL: Días de inventario — por COGS (forecast)
CONFIG: Método de rotación de inventario en forecast = Por COGS (a costo)

### 3.10c Rotación de inventario en forecast — por ventas
DESCRIPCION: Calcula los días de inventario valorando el stock al precio de lista y usando
las ventas netas (a precio de lista) como denominador. El período es el rango del forecast.
VARIABLES:
- S_ini_p = Stock al inicio del período × precio de lista del producto
- S_fin_p = Stock al final del período × precio de lista del producto
- V_net = Suma de ventas netas (salidas × precio de lista) en el período
- D = Días del período del forecast
FORMULA: S_avg_val = (S_ini_p + S_fin_p) / 2 ; DIO = D * S_avg_val / V_net
LABEL: Días de inventario — por ventas a precio de lista (forecast)
CONFIG: Método de rotación de inventario en forecast = Por ventas (a precio de lista)

### 3.11 Cobertura de inventario — base forecast
DESCRIPCION: Días de stock disponible calculados dividiendo el inventario actual entre la
demanda del período de referencia. Distinto del % de cobertura de OFs: mide días de stock,
no cuánto de la demanda tiene OF asignada.
VARIABLES:
- S = Stock actual en ubicaciones internas del producto
- F_per = Total de forecast planificado del período
- D = Días del período del forecast
FORMULA: cobertura_dias = S * D / F_per
LABEL: Días de cobertura de inventario — base forecast (indefinida si F_per = 0)
CONFIG: Fuente de demanda para cobertura de inventario = Forecast planificado (predeterminado)

### 3.11b Cobertura de inventario — base demanda OV
DESCRIPCION: Igual que 3.11 pero usa las unidades en órdenes de venta confirmadas del
período como denominador en lugar del forecast.
VARIABLES:
- S = Stock actual en ubicaciones internas del producto
- D_OV = Total de unidades en órdenes de venta confirmadas del período
- D = Días del período del forecast
FORMULA: cobertura_dias = S * D / D_OV
LABEL: Días de cobertura de inventario — base demanda OV (indefinida si D_OV = 0)
CONFIG: Fuente de demanda para cobertura de inventario = Demanda real (pedidos de órdenes de venta)

### 3.11c Cobertura de inventario — base entregado histórico
DESCRIPCION: Igual que 3.11 pero usa las unidades entregadas (salidas completadas) del
período como denominador.
VARIABLES:
- S = Stock actual en ubicaciones internas del producto
- Q_ent = Total de unidades entregadas (salidas completadas) del período
- D = Días del período del forecast
FORMULA: cobertura_dias = S * D / Q_ent
LABEL: Días de cobertura de inventario — base entregado (indefinida si Q_ent = 0)
CONFIG: Fuente de demanda para cobertura de inventario = Entregado histórico

### 3.12 Precisión de forecast — Simple
DESCRIPCION: Relación directa entre el volumen real y el forecast. Puede superar 100 %
cuando la demanda fue mayor a lo planificado. Se calcula por período y también como total
acumulado sobre todos los períodos.
VARIABLES:
- F_t = Forecast planificado para el período t
- D_t = Volumen real del período t (fuente configurable: ver 3.12f)
FORMULA: Precision_t = D_t / F_t * 100 ; PrecisionTotal = sum(D_t) / sum(F_t) * 100
LABEL: Precisión Simple (— si F_t = 0)
CONFIG: Fórmula de precisión de forecast = Simple (real ÷ forecast × 100)
CONDICIONES:
- Precision_t >= 90 -> Verde
- Precision_t >= 70 -> Amarillo
- Precision_t < 70 -> Rojo

### 3.13 Precisión de forecast — MAPE
DESCRIPCION: Error porcentual absoluto medio. Se calcula solo sobre los períodos con
volumen real mayor a cero para evitar divisiones por cero. Muy sensible a períodos con
demanda baja o nula.
VARIABLES:
- F_t = Forecast del período t
- D_t = Volumen real del período t
- e_t = abs(D_t - F_t)
FORMULA: Precision_t = max(0, 100 - (e_t / D_t) * 100) ; PrecisionTotal = avg(Precision_t para D_t > 0)
LABEL: Precisión MAPE (solo períodos con real > 0)
CONFIG: Fórmula de precisión de forecast = MAPE (error porcentual absoluto medio)
CONDICIONES:
- PrecisionTotal >= 90 -> Verde
- PrecisionTotal >= 70 -> Amarillo
- PrecisionTotal < 70 -> Rojo

### 3.14 Precisión de forecast — WAPE
DESCRIPCION: Error porcentual absoluto ponderado por el volumen real. Pondera más los
períodos de mayor demanda. Robusto cuando el forecast o la demanda tienen ceros.
VARIABLES:
- e_t = abs(D_t - F_t)
- D_t = Volumen real del período t
FORMULA: PrecisionTotal = max(0, 100 - sum(e_t) / sum(D_t) * 100)
LABEL: Precisión WAPE (global, pondera por volumen real)
CONFIG: Fórmula de precisión de forecast = WAPE (error ponderado por demanda real)
CONDICIONES:
- PrecisionTotal >= 90 -> Verde
- PrecisionTotal >= 70 -> Amarillo
- PrecisionTotal < 70 -> Rojo

### 3.15 Precisión de forecast — WMAPE
DESCRIPCION: Error porcentual absoluto ponderado por el forecast planificado. Pondera más
los períodos de mayor volumen planificado. Estándar en supply chain cuando el forecast es
la referencia principal.
VARIABLES:
- e_t = abs(D_t - F_t)
- F_t = Forecast del período t
FORMULA: PrecisionTotal = max(0, 100 - sum(e_t) / sum(F_t) * 100)
LABEL: Precisión WMAPE (global, pondera por forecast)
CONFIG: Fórmula de precisión de forecast = WMAPE (error ponderado por forecast planificado)
CONDICIONES:
- PrecisionTotal >= 90 -> Verde
- PrecisionTotal >= 70 -> Amarillo
- PrecisionTotal < 70 -> Rojo

### 3.16 Sesgo de forecast (Bias)
DESCRIPCION: Mide si el forecast tiende sistemáticamente a sobrestimar o subestimar el
volumen real. Positivo: la demanda superó al forecast de forma consistente (forecast
conservador). Negativo: el forecast fue optimista.
VARIABLES:
- F_t = Forecast del período t
- D_t = Volumen real del período t
FORMULA: Sesgo_t = (D_t - F_t) / F_t * 100 ; SesgoTotal = (sum(D_t) - sum(F_t)) / sum(F_t) * 100
LABEL: Sesgo por período y sesgo total acumulado (— si F_t = 0)
CONFIG: Fórmula de precisión de forecast = Sesgo (Bias)
CONDICIONES:
- abs(Sesgo_t) <= 10 -> Verde
- abs(Sesgo_t) <= 20 -> Amarillo
- abs(Sesgo_t) > 20 -> Rojo

### 3.12f Fuente del «real» para precisión de forecast — demanda confirmada
DESCRIPCION: El volumen real en las cinco fórmulas de precisión son las unidades en
órdenes de venta confirmadas o cerradas del período, independientemente de si fueron
entregadas.
VARIABLES:
- D_t = Unidades en órdenes de venta confirmadas o cerradas del período t
FORMULA: D_t = sum(unidades en OVs confirmadas del período t)
LABEL: Real = demanda confirmada (órdenes de venta)
CONFIG: Fuente del «real» para precisión = Demanda confirmada (órdenes de venta)

### 3.12g Fuente del «real» para precisión de forecast — entregas completadas
DESCRIPCION: El volumen real en las cinco fórmulas de precisión son las unidades entregadas
físicamente en el período (salidas de stock completadas). Útil cuando la demanda confirmada
y la entregada difieren significativamente.
VARIABLES:
- D_t = Unidades en salidas de stock completadas del período t
FORMULA: D_t = sum(unidades entregadas en el período t)
LABEL: Real = entregas completadas
CONFIG: Fuente del «real» para precisión = Entregas completadas

### 3.17 Categoría de cliente — ABC por volumen
DESCRIPCION: Clasifica clientes según el importe total de sus órdenes de venta en el
período configurado. Mayor importe = categoría más alta.
VARIABLES:
- V_k = Importe total de OVs del cliente k en el período
- V_tot = Suma de V_k de todos los clientes
- P_k = Participación individual
- A_cum_k = Acumulado de mayor a menor
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: P_k = V_k / V_tot ; A_cum_k = sum(P_j para j <= k, ordenado por V_j desc)
LABEL: Participación acumulada por importe (clientes)
CONFIG: Método de categoría de cliente = ABC por volumen (importe de órdenes de venta)
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 3.18 Categoría de cliente — ABC por frecuencia
DESCRIPCION: Clasifica clientes según la cantidad de órdenes de venta realizadas en el
período configurado. Mayor cantidad = categoría más alta.
VARIABLES:
- C_k = Cantidad de OVs del cliente k en el período
- C_tot = Suma de C_k de todos los clientes
- P_k = Participación individual
- A_cum_k = Acumulado de mayor a menor
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: P_k = C_k / C_tot ; A_cum_k = sum(P_j para j <= k, ordenado por C_j desc)
LABEL: Participación acumulada por frecuencia (clientes)
CONFIG: Método de categoría de cliente = ABC por frecuencia (cantidad de órdenes de venta)
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 3.19 Categoría de cliente — ABC por RFM
DESCRIPCION: Mismo algoritmo que para proveedores (ver 2.12), aplicado a órdenes de venta
en lugar de órdenes de compra. Recencia = días desde la última OV; Frecuencia = cantidad
de OVs en el período; Monetario = importe total de OVs en el período.
VARIABLES:
- R = Puntos de Recencia (1–3, basados en días desde última OV)
- F_rfm = Puntos de Frecuencia (1–3, basados en cantidad de OVs)
- M = Puntos de Monetario (1–3, basados en percentil del grupo)
- N_m = Período de análisis en meses — 12 por defecto
FORMULA: S = R + F_rfm + M
LABEL: Puntaje RFM total (clientes)
CONFIG: Método de categoría de cliente = ABC por RFM
CONDICIONES:
- S >= 8 -> A
- S >= 6 -> B
- S >= 4 -> C
- S = 3 -> D
- Sin datos en el período -> E

---

## Panel de Ventas — Análisis de clientes

### 4.1 % de entrega
DESCRIPCION: Mide qué porcentaje de las unidades pedidas en órdenes de venta confirmadas
del período fueron efectivamente entregadas mediante salidas de stock completadas.
VARIABLES:
- Q_ped = Suma de unidades en líneas de órdenes de venta confirmadas del período
- Q_ent = Suma de unidades en salidas de stock completadas del período para el mismo cliente
FORMULA: PctEntrega = (Q_ent / Q_ped) * 100
LABEL: % de entrega (— si Q_ped = 0)

### 4.2 % a tiempo — referencia fecha compromiso del pedido
DESCRIPCION: Porcentaje de envíos (salidas completadas) que llegaron antes o en la fecha
que la orden de venta comprometió con el cliente. Los envíos sin fecha compromiso no se
incluyen en el cómputo.
VARIABLES:
- n_total = Total de envíos con fecha compromiso disponible en el período
- n_ot = Envíos donde la fecha de cierre del envío es menor o igual a la fecha compromiso de la OV
FORMULA: ontime_pct = (n_ot / n_total) * 100
LABEL: % a tiempo — base fecha compromiso
CONFIG: Método de entrega a tiempo en análisis de clientes = Fecha compromiso del pedido (predeterminado)

### 4.2b % a tiempo — referencia fecha programada del envío
DESCRIPCION: Porcentaje de envíos que llegaron antes o en la fecha programada del propio
envío saliente (no la fecha compromiso de la orden).
VARIABLES:
- n_total = Total de envíos con fecha programada disponible en el período
- n_ot = Envíos donde la fecha de cierre es menor o igual a la fecha programada del envío
FORMULA: ontime_pct = (n_ot / n_total) * 100
LABEL: % a tiempo — base fecha programada del envío
CONFIG: Método de entrega a tiempo en análisis de clientes = Fecha programada del envío

### 4.2c % a tiempo — referencia SLA en días
DESCRIPCION: Porcentaje de envíos que llegaron dentro del plazo definido como SLA: la
fecha de confirmación de la orden de venta más N días configurados.
VARIABLES:
- n_total = Total de envíos con fecha de confirmación disponible en el período
- n_ot = Envíos donde la fecha de cierre <= fecha confirmación de la OV + N_sla días
- N_sla = Días de SLA configurados
FORMULA: ontime_pct = (n_ot / n_total) * 100
LABEL: % a tiempo — base SLA en días desde confirmación
CONFIG: Método de entrega a tiempo en análisis de clientes = Días desde confirmación del pedido (SLA configurable)

### 4.3 Intervalos entre pedidos
DESCRIPCION: Mide la regularidad de compra de un cliente calculando el tiempo promedio
entre pedidos consecutivos en el período.
VARIABLES:
- fecha_i = Fecha de confirmación del pedido i (ordenadas cronológicamente)
- gaps = Diferencias en días entre pedidos consecutivos
FORMULA: gap_i = fecha_{i+1} - fecha_i ; prom_intervalo = sum(gaps) / count(gaps)
LABEL: Promedio de días entre pedidos (indefinido si el cliente tiene un solo pedido)

### 4.4 Ticket promedio
DESCRIPCION: Importe promedio por pedido del cliente en el período.
VARIABLES:
- V_tot = Importe total de órdenes de venta del cliente en el período
- n = Cantidad de pedidos del cliente en el período
FORMULA: ticket = V_tot / n
LABEL: Ticket promedio (importe por pedido)

### 4.5 Tendencia de ventas
DESCRIPCION: Compara el importe del período actual con el mismo rango de fechas del
año anterior. Positivo = crecimiento; negativo = caída.
VARIABLES:
- V_actual = Importe total de OVs del período seleccionado
- V_anterior = Importe total de OVs del mismo rango desplazado 1 año hacia atrás
FORMULA: trend_pct = (V_actual - V_anterior) / V_anterior * 100
LABEL: Tendencia de ventas % (no se muestra si V_anterior = 0)

### 4.6 ABC del período — clasificación en tiempo real
DESCRIPCION: Clasifica los clientes activos en el período según su participación acumulada
en el importe total de ventas. Calculado en tiempo real sobre los datos del widget; es
independiente de la categoría permanente A–E asignada por el proceso automatizado.
Usa tres categorías (A/B/C) con los parámetros globales de corte.
VARIABLES:
- V_k = Importe total de OVs del cliente k en el período
- V_tot = Suma de V_k de todos los clientes activos en el período
- acum_k = Participación acumulada de mayor a menor
- U_A = Umbral para A (configurable, 20 % por defecto)
- U_A_B = Umbral para B = U_A + umbral_B (50 % por defecto)
FORMULA: participacion_k = V_k / V_tot * 100 ; acum_k = sum(participacion_j para j <= k, desc)
LABEL: ABC del período (en tiempo real, 3 categorías)
CONDICIONES:
- acum_k <= U_A -> A
- acum_k <= U_A_B -> B
- resto -> C

### 4.7 Segmento de frecuencia
DESCRIPCION: Clasifica cada cliente según la regularidad y recencia de sus pedidos. La
condición "En riesgo" tiene precedencia sobre las demás: un cliente frecuente que no
compra desde hace más del tiempo configurado se clasifica como "En riesgo".
VARIABLES:
- dias_ult = Días desde el último pedido hasta hoy
- R_dias = Umbral de riesgo por inactividad — 90 días por defecto
- prom_interv = Promedio de días entre pedidos consecutivos (ver 4.3)
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Segmento de frecuencia
CONDICIONES:
- dias_ult > R_dias -> En riesgo (precedencia sobre el resto)
- prom_interv <= 30 -> Frecuente
- prom_interv <= 90 -> Ocasional
- prom_interv > 90 -> Inactivo
