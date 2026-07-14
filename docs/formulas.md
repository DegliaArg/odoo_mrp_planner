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
- T = Tolerancia de desvío porcentual — 5% por defecto
FORMULA: delta = abs(Q_r - Q_p) / Q_p
LABEL: Desvío porcentual
CONDICIONES:
- delta > T and Q_r < Q_p -> Crítica (producción insuficiente, roja)
- delta > T and Q_r > Q_p -> Advertencia (excedente, amarilla)

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
DESCRIPCION: Compara lo producido con lo programado para cada producto en el período,
agrupando todas las órdenes de fabricación activas y terminadas del rango.
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

### 1.4 Horas disponibles en un centro de trabajo
DESCRIPCION: Capacidad real del centro de trabajo en el período, ajustada por su eficiencia.
Cuando el calendario no puede calcularse directamente, se estima en proporción a las horas
semanales de asistencia configuradas.
VARIABLES:
- H_cal = Horas hábiles del calendario laboral del CT en el período
- E = Eficiencia del CT en porcentaje (ej. 85 significa 85%)
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
- D_i = Duración esperada de la operación i (en minutos)
FORMULA: alpha_i = (min(e_i, t1) - max(s_i, t0)) / (e_i - s_i)
LABEL: Fracción solapada

### 1.5b Horas aportadas por operación
DESCRIPCION: Horas que la operación i aporta al período, según la fracción solapada.
VARIABLES:
- D_i = Duración esperada de la operación i (en minutos)
- alpha_i = Fracción solapada (ver 1.5)
FORMULA: h_i = (D_i / 60) * alpha_i
LABEL: Horas aportadas al período

### 1.6 Horas ejecutadas y horas pendientes
DESCRIPCION: Horas ejecutadas son las de operaciones ya terminadas que solapan con el período.
Horas pendientes son las de operaciones activas (cualquier estado excepto Terminada y Cancelada).
VARIABLES:
- h_i = Horas aportadas por la operación i (ver 1.5b)
FORMULA: H_ejec = sum(h_i para operaciones en estado Terminada)
LABEL: Horas ejecutadas

### 1.6b Horas pendientes
VARIABLES:
- h_i = Horas aportadas por la operación i (ver 1.5b)
FORMULA: H_pend = sum(h_i para operaciones con estado distinto de Terminada y Cancelada)
LABEL: Horas pendientes

### 1.7 Tiempo libre y carga del centro de trabajo
DESCRIPCION: Indica cuánta capacidad queda disponible y qué porcentaje del total está ocupado
entre trabajo ya hecho y trabajo planificado.
VARIABLES:
- H_disp = Horas disponibles del CT en el período (ver 1.4)
- H_ejec = Horas ejecutadas (ver 1.6)
- H_pend = Horas pendientes (ver 1.6b)
FORMULA: T_libre = max(0, H_disp - H_ejec - H_pend)
LABEL: Tiempo libre (horas)

### 1.7b Carga del centro de trabajo
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

### 1.9 Duración de una OF para reprogramación
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

### 1.10 Delta de reprogramación
DESCRIPCION: Diferencia entre la nueva fecha de fin propuesta y la actual, expresada en
días y horas enteras para mostrarse en la tabla del plan.
VARIABLES:
- F_nueva = Nueva fecha de fin propuesta
- F_actual = Fecha de fin actual de la OF
FORMULA: Delta_s = F_nueva - F_actual
LABEL: Delta en segundos (positivo = se adelanta, negativo = se atrasa)

### 1.10b Delta — visualización en días y horas
VARIABLES:
- Delta_s = Delta en segundos (ver 1.10)
FORMULA: d = floor(abs(Delta_s) / 86400)
LABEL: Días del delta

### 1.10c Delta — horas restantes
VARIABLES:
- Delta_s = Delta en segundos
FORMULA: h = floor((abs(Delta_s) / 3600) % 24)
LABEL: Horas restantes del delta (el formato completo es "+2d 3h" o "-1d 0h")

### 1.11 Escalado proporcional de operaciones
DESCRIPCION: Cuando se ajusta la duración total de una OF, cada operación se reescala
para mantener las proporciones relativas entre centros de trabajo.
VARIABLES:
- H_aj = Duración total ajustada de la OF (en horas)
- D_orig_i = Duración original de la operación i (en minutos)
FORMULA: epsilon = H_aj / sum(D_orig_i)
LABEL: Factor de escala

### 1.11b Nueva duración de operación
VARIABLES:
- D_orig_i = Duración original de la operación i (en minutos)
- epsilon = Factor de escala (ver 1.11)
FORMULA: D_nueva_i = D_orig_i * epsilon
LABEL: Nueva duración (mismas unidades que D_orig_i)

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
DESCRIPCION: Clasificación de las OCs aprobadas (confirmadas) según su estado respecto a
la fecha de entrega.
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
DESCRIPCION: Días de diferencia entre la fecha real de recepción y la fecha programada,
solo para recepciones ya completadas.
VARIABLES:
- F_real = Fecha en que se completó la recepción
- F_prog = Fecha programada de la recepción
FORMULA: D_ret = max(0, floor(F_real - F_prog))
LABEL: Días de retraso recepción

### 2.4 % A tiempo (análisis de proveedores)
DESCRIPCION: Porcentaje de recepciones que llegaron en la fecha programada o antes, sobre
el total de recepciones del proveedor en el período.
VARIABLES:
- n = Total de recepciones del proveedor en el período
- n_ot = Recepciones con fecha real menor o igual a la fecha programada
FORMULA: OT_pct = (n_ot / n) * 100
LABEL: % A tiempo

### 2.4b % A tiempo global (ponderado)
DESCRIPCION: Indicador global ponderado que evita que proveedores con pocos envíos distorsionen
el promedio. Divide el total de recepciones a tiempo entre el total de recepciones de todos
los proveedores.
VARIABLES:
- n_ot_k = Recepciones a tiempo del proveedor k
- n_k = Total de recepciones del proveedor k
FORMULA: OT_global = sum(n_ot_k) / sum(n_k) * 100
LABEL: % A tiempo global (ponderado)

### 2.5 Retraso promedio de entregas tardías
DESCRIPCION: Promedio de días de atraso calculado solo sobre las recepciones que efectivamente
llegaron tarde. No incluye recepciones en fecha.
VARIABLES:
- d_i = Días de atraso de la recepción i (solo recepciones con fecha real > fecha programada)
- n_tard = Cantidad de recepciones tardías
FORMULA: d_prom = sum(d_i) / n_tard
LABEL: Retraso promedio (días, solo tardías)

### 2.6 % Recepciones completas
DESCRIPCION: Porcentaje de recepciones que se completaron sin generar un backorder
(se recibió todo lo pedido en una sola entrega).
VARIABLES:
- n = Total de recepciones del proveedor en el período
- n_comp = Recepciones sin backorder
FORMULA: Comp_pct = (n_comp / n) * 100
LABEL: % Completas

### 2.7 Lead time promedio
DESCRIPCION: Tiempo promedio en días desde que se aprueba una OC hasta que se cierra
la recepción correspondiente.
VARIABLES:
- LT_i = Días desde la aprobación de la OC i hasta el cierre de su recepción
- n = Total de órdenes del proveedor en el período
FORMULA: LT_prom = sum(LT_i) / n
LABEL: Lead time promedio (días)

### 2.8 Variación de precio (por línea de OC)
DESCRIPCION: Diferencia porcentual firmada entre el precio pagado y el costo estándar del
producto. Puede ser negativa si el precio pagado fue menor al costo de referencia.
VARIABLES:
- p_i = Precio pagado por unidad en la línea i de la OC
- p_std_i = Costo estándar del producto en la línea i
FORMULA: v_i = (p_i - p_std_i) / p_std_i * 100
LABEL: Variación de precio por línea (%)

### 2.8b Variación de precio promedio (por proveedor)
VARIABLES:
- v_i = Variación por línea (ver 2.8)
- n = Total de líneas del proveedor en el período
FORMULA: v_prom = sum(v_i) / n
LABEL: Variación promedio de precio (%)

### 2.9 Clasificación ABC — Pareto (proveedores y clientes)
DESCRIPCION: Clasifica proveedores (o clientes) usando Pareto acumulado descendente. El valor
de cada uno depende del método elegido: importe total de órdenes, cantidad de órdenes,
% de entregas a tiempo, variación de precio, o calidad de cantidad. Los métodos de precio y
devoluciones usan Pareto ascendente: menor variación o menos devoluciones = mejor categoría.
VARIABLES:
- V_k = Valor del proveedor/cliente k según el método seleccionado
- V_tot = Suma de V_k de todos los proveedores/clientes
- A_cum_k = Participación acumulada hasta el proveedor k (ordenado de mayor a menor)
- U_A = Umbral de corte para A — 20% por defecto
- U_B = Umbral de corte para B — 50% por defecto
- U_C = Umbral de corte para C — 80% por defecto
- U_D = Umbral de corte para D — 95% por defecto
FORMULA: P_k = V_k / V_tot
LABEL: Participación individual

### 2.9b Acumulado Pareto
VARIABLES:
- P_k = Participación individual (ver 2.9)
FORMULA: A_cum_k = sum(P_j para j desde el primero hasta k, ordenado de mayor a menor V_j)
LABEL: Participación acumulada
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 2.10 Clasificación RFM (proveedores y clientes)
DESCRIPCION: Clasifica en función de tres dimensiones: cuándo fue la última compra (Recencia),
con qué frecuencia compra (Frecuencia), y cuánto representa en valor (Monetario). Cada dimensión
otorga entre 1 y 3 puntos. El puntaje total determina la categoría.
VARIABLES:
- R = Puntos de Recencia (1–3)
- F_rfm = Puntos de Frecuencia (1–3)
- M = Puntos de Monetario (1–3)
- S = Puntaje total: S = R + F_rfm + M
FORMULA: S = R + F_rfm + M
LABEL: Puntaje RFM total
CONDICIONES:
- S >= 8 -> A
- S >= 6 -> B
- S >= 4 -> C
- S = 3 -> D
- Sin datos en el período -> E

### 2.10b Puntos de Recencia
DESCRIPCION: Días transcurridos desde la última orden del proveedor/cliente hasta hoy.
VARIABLES:
- dias_ult = Días desde la última orden hasta hoy
FORMULA: R = 3 si dias_ult < 30
LABEL: Puntos de Recencia
CONDICIONES:
- dias_ult < 30 -> R = 3
- dias_ult < 90 -> R = 2
- dias_ult >= 90 -> R = 1

### 2.10c Puntos de Frecuencia
DESCRIPCION: Cantidad de órdenes en el último año.
VARIABLES:
- n_ord = Cantidad de órdenes en el último año
FORMULA: F_rfm = 3 si n_ord > 10
LABEL: Puntos de Frecuencia
CONDICIONES:
- n_ord > 10 -> F_rfm = 3
- n_ord >= 3 -> F_rfm = 2
- n_ord < 3 -> F_rfm = 1

### 2.10d Puntos Monetario
DESCRIPCION: Importe total de órdenes del período comparado contra percentiles del grupo.
VARIABLES:
- M_k = Importe total de órdenes del proveedor/cliente k
- P33 = Percentil 33 del grupo
- P66 = Percentil 66 del grupo
FORMULA: M = 3 si M_k >= P66
LABEL: Puntos Monetario
CONDICIONES:
- M_k >= P66 -> M = 3
- M_k >= P33 -> M = 2
- M_k < P33 -> M = 1

### 2.11 Exactitud de cantidad (calidad de proveedor)
DESCRIPCION: Porcentaje de movimientos de recepción donde la cantidad recibida coincide
exactamente con la cantidad pedida, con una tolerancia de 0.001 unidades.
VARIABLES:
- n_mov = Total de movimientos de recepción del proveedor en el período
- n_exact = Movimientos donde abs(cantidad_recibida - cantidad_pedida) < 0.001
FORMULA: Exactitud = (n_exact / n_mov) * 100
LABEL: % Exactitud de cantidad

---

## Panel de Ventas

### 3.1 Cantidad vendida y monto estimado
DESCRIPCION: La cantidad vendida se calcula sumando las unidades en salidas completadas
del período, agrupando variantes bajo el mismo producto base. El importe es una aproximación:
usa el precio de lista actual, no el precio real de cada venta.
VARIABLES:
- Q_v = Suma de unidades en salidas completadas del período para el producto
- P_L = Precio de lista vigente del producto
FORMULA: Importe_est = Q_v * P_L
LABEL: Importe estimado (usa precio de lista actual)

### 3.2 Clasificación de ventas — Modo Rotación de inventario
DESCRIPCION: Clasifica productos según cuántos días de stock quedan al ritmo de ventas
actual. Un producto con alta rotación (pocas días de stock) es categoría A.
VARIABLES:
- Q_ent = Unidades entregadas (salidas completadas) en el período
- M = Cantidad de meses del período de análisis
- S = Stock actual en ubicaciones internas
- U_A = Umbral en días para A — 30 días por defecto
- U_B = Umbral en días para B — 60 días por defecto
- U_C = Umbral en días para C — 90 días por defecto
- U_D = Umbral en días para D — 180 días por defecto
FORMULA: Q_prom = Q_ent / M
LABEL: Promedio mensual de entregas

### 3.2b Días de rotación
VARIABLES:
- S = Stock actual
- Q_prom = Promedio mensual de entregas (ver 3.2)
FORMULA: R = floor((S / Q_prom) * 30)
LABEL: Días de rotación (999 si Q_prom = 0)
CONDICIONES:
- R <= U_A -> A
- R <= U_B -> B
- R <= U_C -> C
- R <= U_D -> D
- R > U_D o sin ventas -> E

### 3.3 Clasificación de ventas — Modo Demanda
DESCRIPCION: Clasifica productos por su promedio mensual de unidades entregadas.
Un producto que se entrega en mayor volumen mensual es categoría A.
VARIABLES:
- Q_ent = Unidades entregadas en el período
- M = Cantidad de meses del período
- U_A = Umbral mínimo para A en u/mes — 100 u/mes por defecto
- U_B = Umbral mínimo para B en u/mes — 50 u/mes por defecto
- U_C = Umbral mínimo para C en u/mes — 20 u/mes por defecto
- U_D = Umbral mínimo para D en u/mes — 5 u/mes por defecto
FORMULA: Q_prom = Q_ent / M
LABEL: Promedio mensual de entregas
CONDICIONES:
- Q_prom >= U_A -> A
- Q_prom >= U_B -> B
- Q_prom >= U_C -> C
- Q_prom >= U_D -> D
- Q_prom < U_D -> E

### 3.4 Clasificación de ventas — Modo Participación (Pareto)
DESCRIPCION: Clasifica productos por participación acumulada en el total de ventas, ya sea
por unidades o por importe. Los productos que acumulan el mayor porcentaje primero son A.
VARIABLES:
- V_k = Valor del producto k (unidades o importe)
- V_tot = Suma de V_k de todos los productos
- A_cum_k = Participación acumulada hasta el producto k (ordenado de mayor a menor)
- U_A = Umbral acumulado para A — 50% por defecto
- U_B = Umbral acumulado para B — 80% por defecto
- U_C = Umbral acumulado para C — 95% por defecto
- U_D = Umbral acumulado para D — 99% por defecto
FORMULA: P_k = V_k / V_tot
LABEL: Participación individual

### 3.4b Acumulado Pareto — ventas
VARIABLES:
- P_k = Participación individual del producto k (ver 3.4)
FORMULA: A_cum_k = sum(P_j para j desde el primero hasta k, ordenado de mayor a menor V_j)
LABEL: Participación acumulada
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 3.5 Forecast — KPIs globales: Cobertura
DESCRIPCION: Compara las órdenes de fabricación planificadas contra el forecast para el período.
Un valor mayor a 100% indica que hay más producción planificada que la demanda forecasteada.
VARIABLES:
- Q_OF = Suma de cantidades planificadas de OFs en el período (estados habilitados)
- F_tot = Suma de cantidades de todas las líneas de forecast del período
FORMULA: Cobertura = (Q_OF / F_tot) * 100
LABEL: % Cobertura de forecast (0 si F_tot = 0)
CONDICIONES:
- Cobertura >= 100 -> Verde
- Cobertura >= 70 (umbral de aviso configurable) -> Amarillo
- Cobertura < 70 -> Rojo

### 3.5b Forecast — Gap de OFs
VARIABLES:
- Q_OF = Suma de cantidades planificadas de OFs
- F_tot = Suma de forecast del período
FORMULA: Gap_OF = Q_OF - F_tot
LABEL: Gap de OFs (negativo = déficit de cobertura)
CONDICIONES:
- Gap_OF >= 0 -> Verde (OFs cubren o superan el forecast)
- Gap_OF / F_tot * 100 >= -10 -> Amarillo
- Gap_OF / F_tot * 100 < -10 -> Rojo

### 3.6 Forecast — Tasa de servicio
DESCRIPCION: Mide qué fracción de la demanda de órdenes de venta confirmadas fue
efectivamente entregada en el período.
VARIABLES:
- Q_ent = Suma de unidades entregadas (salidas completadas) del período para productos con forecast
- D_OV = Suma de cantidades pedidas en órdenes de venta confirmadas o cerradas del período
FORMULA: TasaServicio = (Q_ent / D_OV) * 100
LABEL: Tasa de servicio % (— si D_OV = 0)
CONDICIONES:
- TasaServicio >= 95 -> Verde
- TasaServicio >= 80 -> Amarillo
- TasaServicio < 80 -> Rojo

### 3.7 Forecast — Gap de demanda
DESCRIPCION: Diferencia porcentual entre la demanda real de órdenes de venta y el forecast.
Positivo significa que la demanda superó el forecast; negativo que fue menor.
VARIABLES:
- D_OV = Demanda de órdenes de venta confirmadas del período
- F_tot = Forecast total del período
FORMULA: Gap_D = (D_OV - F_tot) / F_tot * 100
LABEL: Gap de demanda % (— si F_tot = 0)
CONDICIONES:
- abs(Gap_D) <= 10 -> Verde (demanda alineada con forecast)
- abs(Gap_D) <= 25 -> Amarillo (desvío moderado)
- abs(Gap_D) > 25 -> Rojo (desvío significativo)

### 3.8 Forecast — Cobertura por celda (producto × mes)
DESCRIPCION: Para cada combinación de producto y mes, compara las OFs planificadas con
el forecast de ese producto en ese mes específico.
VARIABLES:
- F_t = Forecast del producto para el mes t
- Q_OF_t = Suma de cantidades planificadas de OFs del producto para el mes t
FORMULA: CobPct_t = (Q_OF_t / F_t) * 100
LABEL: % Cobertura por celda (0 si F_t = 0)
CONDICIONES:
- CobPct_t >= 100 -> Verde
- CobPct_t >= U_aviso (configurable, defecto 70%) -> Amarillo
- CobPct_t < U_aviso -> Rojo

### 3.9 Forecast — Tasa de servicio por celda
VARIABLES:
- Q_ent_t = Unidades entregadas del producto en el mes t
- D_OV_t = Demanda de órdenes de venta del producto en el mes t
FORMULA: SvcRate_t = (Q_ent_t / D_OV_t) * 100
LABEL: Tasa de servicio por celda (— si D_OV_t = 0)

### 3.10 Forecast — Gap de demanda por celda
VARIABLES:
- D_OV_t = Demanda real del producto en el mes t
- F_t = Forecast del producto para el mes t
FORMULA: GapD_t = (D_OV_t - F_t) / F_t * 100
LABEL: Gap de demanda por celda (— si F_t = 0)

### 3.11 Rotación de inventario por producto
DESCRIPCION: Indica cuántos días (o meses) de stock quedan al ritmo de entregas del período.
Se calcula a partir de las salidas completadas y el stock actual.
VARIABLES:
- Q_ent = Total de unidades entregadas en el período
- M = Cantidad de meses del período
- S = Stock actual en ubicaciones internas
FORMULA: Q_prom = Q_ent / M
LABEL: Promedio mensual de entregas

### 3.11b Rotación en meses
VARIABLES:
- S = Stock actual
- Q_prom = Promedio mensual de entregas (ver 3.11)
FORMULA: R_m = S / Q_prom
LABEL: Rotación en meses (1 decimal, — si Q_prom = 0)
CONDICIONES:
- R_m <= 3 -> Verde
- R_m <= 6 -> Amarillo
- R_m > 6 -> Gris (sin color destacado)

### 3.11c Rotación en días
VARIABLES:
- S = Stock actual
- Q_prom = Promedio mensual de entregas (ver 3.11)
FORMULA: R_d = floor(S / Q_prom * 30)
LABEL: Rotación en días (— si Q_prom = 0)
CONDICIONES:
- R_d <= 90 -> Verde
- R_d <= 180 -> Amarillo
- R_d > 180 -> Gris (sin color destacado)

### 3.12 Precisión de forecast — Simple
DESCRIPCION: Relación directa entre la demanda real y el forecast. Puede superar 100%
cuando la demanda fue mayor a lo planificado. Se calcula por período y también como total.
VARIABLES:
- F_t = Forecast planificado para el período t
- D_t = Demanda real (órdenes de venta confirmadas) en el período t
FORMULA: Precision_t = D_t / F_t * 100
LABEL: Precisión por período (— si F_t = 0)
CONDICIONES:
- Precision_t >= 90 -> Verde
- Precision_t >= 70 -> Amarillo
- Precision_t < 70 -> Rojo

### 3.12b Precisión Simple — total
VARIABLES:
- D_t = Demanda real por período
- F_t = Forecast por período
FORMULA: PrecisionTotal = sum(D_t) / sum(F_t) * 100
LABEL: Precisión total Simple

### 3.13 Precisión de forecast — MAPE
DESCRIPCION: Error porcentual absoluto medio. Muy sensible a períodos con demanda baja
o nula — se calcula sólo sobre los períodos con demanda real mayor a cero.
VARIABLES:
- F_t = Forecast planificado para el período t
- D_t = Demanda real (órdenes de venta confirmadas) en el período t
- e_t = Error absoluto del período: abs(D_t - F_t)
FORMULA: Precision_t = max(0, 100 - (e_t / D_t) * 100)
LABEL: Precisión por período (sólo si D_t > 0)
CONDICIONES:
- Precision_t >= 90 -> Verde
- Precision_t >= 70 -> Amarillo
- Precision_t < 70 -> Rojo

### 3.13b Precisión MAPE — total
VARIABLES:
- Precision_t = Precisión MAPE por período (ver 3.13)
FORMULA: PrecisionTotal = avg(Precision_t para períodos donde D_t > 0)
LABEL: Precisión total MAPE

### 3.14 Precisión de forecast — WAPE
DESCRIPCION: Error porcentual absoluto ponderado por la demanda real. Más robusto que
MAPE cuando el forecast o la demanda tienen ceros, porque pondera más los períodos de
mayor volumen real.
VARIABLES:
- e_t = Error absoluto: abs(D_t - F_t)
- D_t = Demanda real en el período t
FORMULA: PrecisionTotal = max(0, 100 - sum(e_t) / sum(D_t) * 100)
LABEL: Precisión total WAPE
CONDICIONES:
- PrecisionTotal >= 90 -> Verde
- PrecisionTotal >= 70 -> Amarillo
- PrecisionTotal < 70 -> Rojo

### 3.15 Precisión de forecast — WMAPE
DESCRIPCION: Error porcentual absoluto ponderado por el forecast. Pondera más los períodos
de mayor volumen planificado. Es el estándar en supply chain cuando el forecast es la
referencia principal.
VARIABLES:
- e_t = Error absoluto: abs(D_t - F_t)
- F_t = Forecast del período t
FORMULA: PrecisionTotal = max(0, 100 - sum(e_t) / sum(F_t) * 100)
LABEL: Precisión total WMAPE
CONDICIONES:
- PrecisionTotal >= 90 -> Verde
- PrecisionTotal >= 70 -> Amarillo
- PrecisionTotal < 70 -> Rojo

### 3.16 Sesgo de forecast (Bias)
DESCRIPCION: Mide si el forecast tiende sistemáticamente a sobrestimar o subestimar la
demanda real. Positivo significa que la demanda superó al forecast de forma consistente
(forecast conservador); negativo significa que el forecast fue optimista.
VARIABLES:
- F_t = Forecast planificado para el período t
- D_t = Demanda real en el período t
FORMULA: Sesgo_t = (D_t - F_t) / F_t * 100
LABEL: Sesgo por período (— si F_t = 0)
CONDICIONES:
- abs(Sesgo_t) <= 10 -> Verde
- abs(Sesgo_t) <= 20 -> Amarillo
- abs(Sesgo_t) > 20 -> Rojo

### 3.16b Sesgo total
VARIABLES:
- D_t = Demanda real por período
- F_t = Forecast por período
FORMULA: SesgoTotal = (sum(D_t) - sum(F_t)) / sum(F_t) * 100
LABEL: Sesgo total acumulado

### 3.17 Clasificación ABC de clientes — Pareto por volumen
DESCRIPCION: Clasifica clientes por su participación acumulada en el total de ventas del
último año. Usa el mismo algoritmo Pareto que para proveedores (ver 2.9 y 2.9b), aplicado
al importe total de órdenes de venta confirmadas o cerradas.
VARIABLES:
- V_k = Importe total de órdenes de venta confirmadas/cerradas del cliente k en el último año
- V_tot = Suma de V_k de todos los clientes
- A_cum_k = Participación acumulada hasta el cliente k
- U_A, U_B, U_C, U_D = Umbrales de corte (mismos parámetros que para proveedores)
FORMULA: P_k = V_k / V_tot
LABEL: Participación individual del cliente

### 3.17b Acumulado Pareto — clientes
VARIABLES:
- P_k = Participación del cliente k (ver 3.17)
FORMULA: A_cum_k = sum(P_j para j desde el primero hasta k, ordenado de mayor a menor V_j)
LABEL: Participación acumulada del cliente
CONDICIONES:
- A_cum_k <= U_A -> A
- A_cum_k <= U_B -> B
- A_cum_k <= U_C -> C
- A_cum_k <= U_D -> D
- resto -> E

### 3.18 Clasificación RFM de clientes
DESCRIPCION: Mismo algoritmo que para proveedores (ver 2.10), aplicado a órdenes de venta
en lugar de órdenes de compra. Recencia = días desde la última OV; Frecuencia = cantidad
de OVs en el último año; Monetario = importe total de OVs en el último año.
VARIABLES:
- R = Puntos de Recencia (1–3, basados en días desde última OV)
- F_rfm = Puntos de Frecuencia (1–3, basados en cantidad de OVs)
- M = Puntos de Monetario (1–3, basados en percentil de importe)
FORMULA: S = R + F_rfm + M
LABEL: Puntaje RFM total
CONDICIONES:
- S >= 8 -> A
- S >= 6 -> B
- S >= 4 -> C
- S = 3 -> D
- Sin datos en el período -> E
