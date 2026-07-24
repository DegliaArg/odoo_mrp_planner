# Fórmulas de cálculo — odoo_mrp_planner

> Versión para cliente. Sin referencias a modelos ni campos internos del sistema.
> Notación: subíndices con `_`, funciones en minúscula con paréntesis.
> Bloques con `CONFIG:` corresponden a una opción de una configuración seleccionable.

---

## Sección 1 — Panel de Producción

---

### 1.1 Días de atraso — órdenes de fabricación
DESCRIPCION: Cuantifica cuántos días lleva atrasada una orden de fabricación activa cuya fecha de fin ya pasó. El resultado es siempre mayor o igual a cero.
VARIABLES:
- D_hoy = fecha y hora actuales
- D_fin = fecha y hora de fin planificada de la OF
- A = días de atraso
FORMULA: A = max(0, floor((D_hoy - D_fin) / 86400))
LABEL: Días de atraso (OFs)
CONDICIONES:
- A >= umbral_critico_OF -> severidad roja
- A < umbral_critico_OF AND A > 0 -> severidad amarilla

---

### 1.2 Alerta de OF por vencer
DESCRIPCION: Identifica las órdenes de fabricación cuya fecha de fin está dentro de la ventana de aviso configurada pero todavía no venció. Estas alertas siempre tienen severidad amarilla.
VARIABLES:
- D_hoy = fecha actual
- D_fin = fecha de fin planificada de la OF
- V = ventana de aviso en días (configurable, def: 7)
FORMULA: D_hoy < D_fin AND D_fin <= D_hoy + V
LABEL: OFs por vencer (alerta)

---

### 1.3 Desvío de cantidad producida
DESCRIPCION: Mide la diferencia porcentual entre la cantidad efectivamente producida y la planificada al cerrar una orden de fabricación. Se genera una alerta si el desvío supera la tolerancia configurada.
VARIABLES:
- Q_real = suma de unidades del producto terminado en movimientos con estado Hecho
- Q_plan = cantidad planificada de la OF
- D_pct = desvío porcentual
FORMULA: D_pct = abs(Q_real - Q_plan) / Q_plan * 100
LABEL: Desvío de cantidad producida (%)
CONDICIONES:
- D_pct > tolerancia_config -> generar alerta
- Q_real < Q_plan -> alerta roja (producción insuficiente)
- Q_real > Q_plan -> alerta amarilla (excedente)

---

### 1.4 % de cumplimiento — producido vs. programado
DESCRIPCION: Indica qué porcentaje de la cantidad planificada para un producto en el período fue efectivamente producida. Se calcula agrupando las OFs del producto que correspondan al período según el criterio configurado.
VARIABLES:
- P_prod = suma de cantidades producidas de las OFs del producto en el período
- P_prog = suma de cantidades planificadas de las OFs del producto en el período
- C = porcentaje de cumplimiento
FORMULA: C = (P_prod / P_prog) * 100
LABEL: Cumplimiento producido vs. programado (%)
CONDICIONES:
- C >= 90 -> verde
- 50 <= C < 90 -> amarillo
- C < 50 -> rojo
- P_prog = 0 y P_prod = 0 -> C = 0
- P_prog = 0 y P_prod > 0 -> "s/plan" (sin plan / sobreproducción): se produjo sin cantidad programada; no se muestra 0%

---

### 1.5 Criterio de OFs por período — por fecha de cierre
DESCRIPCION: Una OF entra en el período únicamente si su fecha de cierre cae dentro del rango seleccionado. La cantidad utilizada es la planificada completa de la OF.
VARIABLES:
- D_cierre = fecha de cierre de la OF
- D_ini = inicio del período
- D_fin_per = fin del período
FORMULA: D_ini <= D_cierre <= D_fin_per
LABEL: OFs por fecha de cierre
CONFIG: Criterio de OFs por período = Por fecha de cierre (predeterminado)

---

### 1.5b Criterio de OFs por período — por solapamiento completo
DESCRIPCION: Una OF entra en el período si estuvo activa en algún momento dentro del rango: su inicio es anterior o igual al fin del período, y su fin es posterior o igual al inicio del período. La cantidad es la planificada completa, y una OF puede aparecer en múltiples períodos (doble conteo): no deben sumarse los períodos entre sí. Tanto lo programado como lo producido usan los totales de la OF (product_qty y qty_produced), sin acotar al período.
VARIABLES:
- D_ini_OF = fecha de inicio de la OF
- D_fin_OF = fecha de fin de la OF
- D_ini = inicio del período
- D_fin_per = fin del período
FORMULA: D_ini_OF <= D_fin_per AND D_fin_OF >= D_ini
LABEL: OFs por solapamiento completo
CONFIG: Criterio de OFs por período = Por solapamiento completo

---

### 1.5c Criterio de OFs por período — proporcional por duración
DESCRIPCION: Una OF entra en el período si estuvo activa en algún momento dentro del rango. La cantidad atribuida es proporcional a la fracción de la duración de la OF que cae en el período. Las unidades producidas reales solo cuentan si su fecha de movimiento cae dentro del período. Si una OF no tiene fecha de inicio válida, se usa como fallback su fecha de cierre: se atribuye la cantidad completa solo si el cierre cae en el período (mismo criterio en la comparativa y en el forecast).
VARIABLES:
- s_solap = segundos solapados entre la OF y el período
- s_total = duración total de la OF en segundos
- Q_plan = cantidad planificada de la OF
- f = fracción proporcional
FORMULA: f = s_solap / s_total ; Q_atribuida = Q_plan * f
LABEL: OFs proporcionales por duración
CONFIG: Criterio de OFs por período = Proporcional por duración

---

### 1.6 Horas disponibles — centro de trabajo
DESCRIPCION: Calcula las horas productivas reales de un centro de trabajo en el período, considerando el calendario laboral y la eficiencia del equipamiento. Si no hay calendario disponible, se estima a partir de las horas semanales de asistencia.
VARIABLES:
- H_cal = horas hábiles según calendario en el período
- E = eficiencia del centro de trabajo (%, ej: 85 significa 85 %)
- H_disp = horas disponibles efectivas
FORMULA: H_disp = H_cal * (E / 100)
LABEL: Horas disponibles CT

---

### 1.7 Solapamiento de operación con el período
DESCRIPCION: Determina qué fracción de la duración de una operación cae dentro del período seleccionado. Se usa para asignar horas ejecutadas o pendientes a cada período de análisis.
VARIABLES:
- D_ini_op = inicio de la operación
- D_fin_op = fin de la operación
- D_ini_per = inicio del período
- D_fin_per = fin del período
- s_solap = segundos solapados entre la operación y el período
- s_total_op = duración total de la operación en segundos
- H_op = horas esperadas de la operación
- H_aport = horas aportadas al período
FORMULA: s_solap = min(D_fin_op, D_fin_per) - max(D_ini_op, D_ini_per) ; H_aport = H_op * (s_solap / s_total_op)
LABEL: Horas de operación solapadas con el período

---

### 1.8 Tiempo libre y carga — centro de trabajo
DESCRIPCION: El tiempo libre es la capacidad no utilizada del centro de trabajo en el período. La carga porcentual mide qué fracción de la capacidad disponible está ocupada sumando las horas de operaciones ya realizadas y las planificadas en curso.
VARIABLES:
- H_disp = horas disponibles del CT en el período
- H_ej = horas de operaciones terminadas que solapan el período
- H_pend = horas de operaciones activas (no terminadas ni canceladas) que solapan el período
- TL = tiempo libre en horas
- C_pct = carga porcentual
FORMULA: TL = max(0, H_disp - H_ej - H_pend) ; C_pct = (H_ej + H_pend) / H_disp * 100
LABEL: Tiempo libre y carga % (CT)
CONDICIONES:
- C_pct < 70 -> verde
- 70 <= C_pct < 90 -> amarillo
- C_pct >= 90 -> rojo
- H_disp = 0 -> C_pct = 0

---

### 1.9 Condición de quiebre de stock
DESCRIPCION: Un producto está en situación de quiebre cuando su stock disponible en las ubicaciones internas configuradas cae por debajo del nivel mínimo definido en su punto de reorden. Se aplica una tolerancia mínima para evitar falsos positivos por redondeo.
VARIABLES:
- S = stock actual en ubicaciones internas
- M = cantidad mínima del punto de reorden (si hay varios, se toma el mayor)
- tol = tolerancia (0.001 unidades)
FORMULA: quiebre = S < (M - tol)
LABEL: Condición de quiebre de stock

---

### 1.10 Diferencia de stock
DESCRIPCION: Indica en cuántas unidades el stock disponible supera o cae por debajo del mínimo configurado. Un valor negativo confirma quiebre.
VARIABLES:
- S = stock actual
- M = mínimo del punto de reorden
FORMULA: diferencia = S - M
LABEL: Diferencia stock vs. mínimo

---

### 1.11 Rotación en quiebres de stock — por unidades
DESCRIPCION: Estima los días de inventario disponible dividiendo el stock promedio del período por el promedio mensual de salidas, expresado en días. El período es el configurado para el análisis de quiebres.
VARIABLES:
- S_ini = stock al inicio del período (unidades)
- S_fin = stock al final del período (unidades)
- S_avg = stock promedio del período
- sal = suma de unidades de salidas completadas en el período
- n_m = número de meses del período configurado
- DIO = días de inventario
FORMULA: S_avg = (S_ini + S_fin) / 2 ; DIO = S_avg / (sal / n_m) * 30
LABEL: Días de inventario — por unidades (quiebres)
CONFIG: Método de rotación en quiebres de stock = Por unidades

---

### 1.11b Rotación en quiebres de stock — por COGS
DESCRIPCION: Estima los días de inventario comparando el valor monetario del stock promedio (a costo estándar) contra el costo de lo vendido en el período. Más preciso cuando los productos tienen costos muy distintos entre sí.
VARIABLES:
- I_ini = stock inicial × costo estándar del producto
- I_fin = stock final × costo estándar del producto
- I_avg = inventario promedio valorizado a costo
- COGS = suma de (precio unitario de costo × cantidad) de salidas completadas en el período
- D = días del período
- DIO = días de inventario
FORMULA: I_avg = (I_ini + I_fin) / 2 ; DIO = D * I_avg / COGS
LABEL: Días de inventario — por COGS (quiebres)
CONFIG: Método de rotación en quiebres de stock = Por COGS (a costo)

---

### 1.11c Rotación en quiebres de stock — por ventas
DESCRIPCION: Estima los días de inventario comparando el valor monetario del stock promedio (a precio de lista) contra las ventas netas del período valoradas a precio de lista.
VARIABLES:
- I_ini = stock inicial × precio de lista del producto
- I_fin = stock final × precio de lista del producto
- I_avg = inventario promedio valorizado a precio de lista
- V_net = suma de ventas netas en el período (salidas valoradas a precio de lista)
- D = días del período
- DIO = días de inventario
FORMULA: I_avg = (I_ini + I_fin) / 2 ; DIO = D * I_avg / V_net
LABEL: Días de inventario — por ventas (quiebres)
CONFIG: Método de rotación en quiebres de stock = Por ventas (a precio de lista)

---

### 1.12 Duración de una OF
DESCRIPCION: El sistema calcula la duración de una orden de fabricación según la información disponible, en orden de prioridad descendente: primero operaciones, luego fechas de la OF, y como último recurso un valor fijo de 8 horas.
VARIABLES:
- H_ops = suma de duraciones esperadas de todas las operaciones, convertidas de minutos a horas
- D_fin = fecha y hora de fin de la OF
- D_ini = fecha y hora de inicio de la OF
- H_dur = duración resultante en horas
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Duración de una OF
CONDICIONES:
- hay operaciones -> H_dur = sum(duracion_operacion_i / 60) para todo i
- no hay operaciones AND hay fechas -> H_dur = (D_fin - D_ini) en horas
- no hay operaciones AND no hay fechas -> H_dur = 8

---

### 1.13 Delta de reprogramación
DESCRIPCION: Expresa en días y horas la diferencia entre la nueva fecha de fin propuesta por el plan de reprogramación y la fecha de fin original de la OF. Un valor positivo indica que la OF se adelanta; negativo, que se atrasa.
VARIABLES:
- D_nueva = nueva fecha de fin propuesta
- D_orig = fecha de fin original de la OF
- delta_h = diferencia en horas
- dias = parte entera de delta_h / 24
- horas_rest = resto de delta_h / 24
FORMULA: delta_h = (D_nueva - D_orig) / 3600 ; dias = floor(delta_h / 24) ; horas_rest = floor(delta_h mod 24)
LABEL: Delta de reprogramación (días y horas)

---

### 1.14 Escala de operaciones por CT
DESCRIPCION: Cuando la duración total de una OF se ajusta en el plan de reprogramación, cada operación se escala proporcionalmente para mantener la distribución relativa de carga entre centros de trabajo.
VARIABLES:
- H_ajust = duración total ajustada de la OF (horas)
- H_sum_orig = suma de duraciones esperadas originales de todas las operaciones
- f_escala = factor de escala
- H_i_orig = duración esperada original de la operación i
- H_i_new = nueva duración de la operación i
FORMULA: f_escala = H_ajust / H_sum_orig ; H_i_new = H_i_orig * f_escala
LABEL: Duración de operación escalada

---

### 1.15 Criterio de prioridad al reprogramar — orden cronológico
DESCRIPCION: Las órdenes de fabricación se ordenan por fecha de inicio actual de menor a mayor (primero las que comienzan antes) antes de ejecutar la reprogramación en cascada.
VARIABLES:
- D_ini_i = fecha de inicio actual de la OF i
FORMULA: ordenar OFs por D_ini_i ascendente
LABEL: Orden de reprogramación — cronológico
CONFIG: Criterio de prioridad al reprogramar = Orden cronológico (por fecha de inicio)

---

### 1.15b Criterio de prioridad al reprogramar — más cortas primero (SPT)
DESCRIPCION: Las órdenes de fabricación se ordenan por duración calculada de menor a mayor (primero las más rápidas). Este criterio minimiza el tiempo promedio de espera en cola, siguiendo el método Shortest Processing Time.
VARIABLES:
- H_dur_i = duración calculada de la OF i (según prioridad: operaciones -> fechas -> 8 h)
FORMULA: ordenar OFs por H_dur_i ascendente
LABEL: Orden de reprogramación — más cortas primero (SPT)
CONFIG: Criterio de prioridad al reprogramar = Más cortas primero (SPT)

---

### 1.15c Criterio de prioridad al reprogramar — secuencia manual
DESCRIPCION: El operador define el orden de las órdenes de fabricación arrastrando las filas en el wizard antes de ejecutar la reprogramación. El sistema respeta ese orden exacto.
VARIABLES:
- pos_i = posición asignada manualmente a la OF i en el wizard
FORMULA: ordenar OFs por pos_i ascendente
LABEL: Orden de reprogramación — secuencia manual
CONFIG: Criterio de prioridad al reprogramar = Secuencia manual en el wizard

---

## Sección 2 — Panel de Compras

---

### 2.1 Días de atraso — órdenes de compra
DESCRIPCION: Cuantifica cuántos días lleva atrasada una orden de compra aprobada cuya fecha de entrega estimada ya venció. El resultado es siempre mayor o igual a cero.
VARIABLES:
- D_hoy = fecha actual
- D_entr = fecha de entrega estimada de la OC
- A = días de atraso
FORMULA: A = max(0, floor(D_hoy - D_entr))
LABEL: Días de atraso (OCs)
CONDICIONES:
- A >= umbral_critico_OC -> severidad roja
- A < umbral_critico_OC AND A > 0 -> severidad amarilla

---

### 2.2 Días de atraso — recepciones
DESCRIPCION: Cuantifica cuántos días lleva atrasada una recepción pendiente cuya fecha programada ya pasó. El resultado es siempre mayor o igual a cero.
VARIABLES:
- D_hoy = fecha actual
- D_prog = fecha programada de la recepción
- A = días de atraso
FORMULA: A = max(0, floor(D_hoy - D_prog))
LABEL: Días de atraso (recepciones)
CONDICIONES:
- A >= umbral_critico_recepcion -> severidad roja
- A < umbral_critico_recepcion AND A > 0 -> severidad amarilla

---

### 2.3 % a tiempo — proveedor individual
DESCRIPCION: Mide el porcentaje de recepciones de un proveedor que llegaron antes o exactamente en la fecha y hora programada. La comparación es a nivel de fecha y hora exacta: una recepción que llega el mismo día pero una hora después se considera tarde. Las recepciones sin fecha programada o sin fecha de cierre no se pueden evaluar: se excluyen del denominador y se informan aparte como "sin fecha".
VARIABLES:
- n_ot = cantidad de recepciones donde fecha_cierre <= fecha_programada (comparación de fecha y hora exacta)
- n_sf = recepciones sin fecha programada o sin fecha de cierre (no evaluables)
- n_eval = recepciones evaluables del proveedor = total de recepciones − n_sf
- pct_ot = porcentaje a tiempo
FORMULA: pct_ot = n_ot / n_eval * 100
LABEL: % a tiempo (proveedor)
CONDICIONES:
- pct_ot >= umbral_verde_config -> verde
- pct_ot >= umbral_amarillo_config -> amarillo
- pct_ot < umbral_amarillo_config -> rojo

---

### 2.4 % a tiempo global — ponderado
DESCRIPCION: Combina la puntualidad de todos los proveedores en un único indicador. No es el promedio de porcentajes individuales sino el cociente entre el total de recepciones a tiempo y el total de recepciones evaluables (con fecha) de todos los proveedores. Las recepciones sin fecha se excluyen del denominador.
VARIABLES:
- N_ot = suma de recepciones a tiempo de todos los proveedores
- N_eval = suma de recepciones evaluables (con fecha programada y de cierre) de todos los proveedores
- pct_ot_global = porcentaje a tiempo global
FORMULA: pct_ot_global = N_ot / N_eval * 100
LABEL: % a tiempo global — ponderado (todos los proveedores)

---

### 2.5 Retraso promedio — proveedores
DESCRIPCION: Promedia los días de atraso solo entre las recepciones que llegaron tarde, excluyendo las que llegaron a tiempo. Un valor alto indica que los retrasos existentes son sistemáticamente prolongados.
VARIABLES:
- d_i = (fecha_cierre_i - fecha_programada_i) en días, solo para recepciones donde fecha_cierre > fecha_programada
- n_tard = cantidad de recepciones tardías
- R_avg = retraso promedio en días
FORMULA: R_avg = sum(d_i para toda i tardía) / n_tard
LABEL: Retraso promedio (días, solo recepciones tardías)
CONDICIONES:
- R_avg <= umbral_verde_retraso -> verde
- R_avg <= umbral_amarillo_retraso -> amarillo
- R_avg > umbral_amarillo_retraso -> rojo

---

### 2.6 % de recepciones completas
DESCRIPCION: Mide qué porcentaje de las recepciones del proveedor se completaron sin generar un backorder. Una recepción completa es aquella que no derivó en una segunda recepción por saldo pendiente.
VARIABLES:
- n_comp = cantidad de recepciones sin backorder asociado
- n_total = total de recepciones del proveedor en el período
- pct_comp = porcentaje de recepciones completas
FORMULA: pct_comp = n_comp / n_total * 100
LABEL: % recepciones completas

---

### 2.7 Lead time promedio — proveedores
DESCRIPCION: Promedia en días el tiempo transcurrido entre la aprobación de cada orden de compra y el cierre de la recepción correspondiente.
VARIABLES:
- LT_i = (fecha_cierre_recepcion_i - fecha_aprobacion_OC_i) en días, para cada recepción i del período
- n = cantidad de recepciones del proveedor en el período
- LT_avg = lead time promedio en días
FORMULA: LT_avg = sum(LT_i) / n
LABEL: Lead time promedio (días)

---

### 2.8 Variación de precio — referencia: costo estándar
DESCRIPCION: Compara el precio pagado en cada línea de compra contra el costo estándar del producto en el catálogo. El resultado es el promedio firmado de esas diferencias porcentuales; un valor positivo indica que se pagó más que el costo de referencia.
VARIABLES:
- p_i = precio unitario pagado en la línea i de OC
- c_i = costo estándar del producto de la línea i
- v_i = variación porcentual de la línea i
- n = cantidad de líneas con costo estándar distinto de cero
- V_avg = variación promedio firmada
FORMULA: v_i = (p_i - c_i) / c_i * 100 ; V_avg = sum(v_i) / n
LABEL: Variación de precio — costo estándar (%)
CONFIG: Referencia para variación de precio = Costo estándar del producto

---

### 2.8b Variación de precio — referencia: lista del proveedor
DESCRIPCION: Compara el precio pagado contra el precio configurado en la lista del proveedor para ese artículo. Las líneas sin precio de proveedor configurado se excluyen del promedio.
VARIABLES:
- p_i = precio unitario pagado en la línea i de OC
- pl_i = precio configurado en la lista del proveedor para el artículo
- v_i = variación porcentual de la línea i
- n = cantidad de líneas con precio de proveedor configurado
- V_avg = variación promedio firmada
FORMULA: v_i = (p_i - pl_i) / pl_i * 100 ; V_avg = sum(v_i para toda i con pl_i definido) / n
LABEL: Variación de precio — lista de proveedor (%)
CONFIG: Referencia para variación de precio = Lista de precio del proveedor

---

### 2.9 Período de análisis — categorías de proveedor
DESCRIPCION: Define el horizonte temporal que se considera al ejecutar la clasificación automática de proveedores. La fecha de inicio del análisis se calcula restando ese número de meses (a razón de 30 días por mes) a la fecha actual.
VARIABLES:
- M_s = meses configurados para categorías de proveedor (def: 12)
- F_ini = fecha de inicio del período de análisis
FORMULA: F_ini = hoy - M_s * 30 dias
LABEL: Horizonte temporal — categorías de proveedor
CONFIG: Período de análisis de proveedores = N meses (configurable, def: 12 meses)

---

### 2.10 Categoría de proveedor — Manual
DESCRIPCION: La categoría A–E del proveedor se asigna directamente por el usuario en la ficha del proveedor. No existe cálculo automático; el valor se mantiene hasta que el usuario lo modifique manualmente.
VARIABLES:
- ninguna
FORMULA: clasificación manual (sin cálculo automático)
LABEL: Categoría de proveedor — manual
CONFIG: Método de categoría de proveedor = Manual (asignación directa)

---

### 2.11 Categoría de proveedor — ABC por volumen
DESCRIPCION: Clasifica a los proveedores según el importe total de sus órdenes de compra en el período configurado. Los que concentran el mayor importe reciben la categoría más alta.
VARIABLES:
- V_j = importe total de OCs del proveedor j en el período
- V_tot = suma de V_j de todos los proveedores
- P_j = participación del proveedor j en el importe total (%)
- P_cum_j = participación acumulada ordenando de mayor a menor
FORMULA: P_j = V_j / V_tot * 100 ; P_cum_j = sum(P_k para todo k con V_k >= V_j)
LABEL: Pareto por importe — proveedores
CONFIG: Método de categoría de proveedor = ABC por volumen (importe de órdenes)
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

### 2.12 Categoría de proveedor — ABC por frecuencia
DESCRIPCION: Clasifica a los proveedores según la cantidad de órdenes de compra emitidas en el período configurado. Los que tienen más órdenes reciben la categoría más alta.
VARIABLES:
- F_j = cantidad de OCs del proveedor j en el período
- F_tot = suma de F_j de todos los proveedores
- P_j = participación del proveedor j en la frecuencia total (%)
- P_cum_j = participación acumulada ordenando de mayor a menor
FORMULA: P_j = F_j / F_tot * 100 ; P_cum_j = sum(P_k para todo k con F_k >= F_j)
LABEL: Pareto por frecuencia — proveedores
CONFIG: Método de categoría de proveedor = ABC por frecuencia (cantidad de órdenes)
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

### 2.13 Categoría de proveedor — ABC por RFM
DESCRIPCION: Clasifica a los proveedores combinando tres dimensiones: Recencia (cuándo fue el último pedido), Frecuencia (cuántos pedidos en el período) y Monto (importe total). Cada dimensión recibe 1 a 3 puntos; la suma de los tres determina la categoría final.
VARIABLES:
- R = puntuación de recencia (días desde la última OC)
- F_score = puntuación de frecuencia (cantidad de OCs en el período)
- M = puntuación de monto (percentil del importe vs. el grupo)
- T = puntaje total (R + F_score + M)
FORMULA: T = R + F_score + M
LABEL: Puntaje RFM — proveedor
CONFIG: Método de categoría de proveedor = ABC por RFM
CONDICIONES (los cortes son configurables en Ajustes → "Parámetros RFM"; entre paréntesis los valores por defecto):
- R: dias_ultima_OC < rfm_recency_recent_days (30) -> 3 pts ; < rfm_recency_medium_days (90) -> 2 pts ; resto -> 1 pt
- F_score: count_OCs > rfm_freq_high (10) -> 3 pts ; >= rfm_freq_medium (3) -> 2 pts ; resto -> 1 pt
- M: percentil >= 66 -> 3 pts ; percentil >= 33 -> 2 pts ; resto -> 1 pt
- T >= rfm_score_a (8) -> A ; T >= rfm_score_b (6) -> B ; T >= rfm_score_c (4) -> C ; T >= rfm_score_d (3) -> D
- sin datos (sin OCs en el período) -> E

---

### 2.14 Categoría de proveedor — ABC por entrega a tiempo
DESCRIPCION: Clasifica a los proveedores según el porcentaje de recepciones que llegaron en la fecha y hora programadas. La comparación es exacta a nivel de fecha y hora. Los que tienen mayor puntualidad reciben la categoría más alta.
VARIABLES:
- ot_j = recepciones del proveedor j donde fecha_cierre <= fecha_programada (exacto, fecha y hora)
- n_j = total de recepciones del proveedor j en el período
- OT_j = porcentaje a tiempo del proveedor j
- P_cum_j = participación acumulada ordenando de mayor OT a menor
FORMULA: OT_j = ot_j / n_j * 100 ; P_cum_j = sum(P_k para todo k con OT_k >= OT_j)
LABEL: Pareto por % a tiempo — proveedores
CONFIG: Método de categoría de proveedor = ABC por entrega a tiempo
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

### 2.15 Categoría de proveedor — ABC por variación de precio
DESCRIPCION: Clasifica a los proveedores según cuánto varía el precio que cobran para un mismo producto entre compras sucesivas. Cada compra del período se compara con el precio anterior pagado del mismo producto al mismo proveedor (tendencia de precio, independiente del costo estándar, que puede ser muy volátil). La clasificación es inversa: el proveedor con menor variación (más estable) recibe la categoría A.
VARIABLES:
- v_k = abs(precio_k - precio_anterior_k) / precio_anterior_k * 100, para cada compra k del proveedor j que tiene una compra previa del mismo producto
- n_j = cantidad de líneas de OC del proveedor j
- V_j = variación promedio del proveedor j
- pos_j = percentil de posición ordenando de menor V a mayor (reparto por cuotas fijas de proveedores, NO por participación acumulada del valor)
FORMULA: V_j = sum(v_k) / n_j ; pos_j = (índice_j + 1) / n_proveedores_con_datos
LABEL: Ranking por percentil por variación de precio — proveedores
CONFIG: Método de categoría de proveedor = ABC por variación de precio
CONDICIONES (los umbrales se interpretan como percentiles de posición, no como participación acumulada):
- pos_j <= umbral_A -> A (menor variación)
- pos_j <= umbral_B -> B
- pos_j <= umbral_C -> C
- pos_j <= umbral_D -> D
- pos_j > umbral_D -> E (mayor variación)

---

### 2.16 Categoría de proveedor — ABC por exactitud de cantidad
DESCRIPCION: Clasifica a los proveedores según el porcentaje de movimientos recibidos cuya cantidad coincide exactamente con la solicitada. Los que entregan cantidades exactas con mayor frecuencia reciben la categoría más alta.
VARIABLES:
- eq_j = movimientos del proveedor j donde abs(cantidad_recibida - cantidad_pedida) < 0.001
- n_j = total de movimientos del proveedor j en el período
- EX_j = porcentaje de exactitud del proveedor j
- P_cum_j = participación acumulada ordenando de mayor EX a menor
FORMULA: EX_j = eq_j / n_j * 100 ; P_cum_j = sum(P_k para todo k con EX_k >= EX_j)
LABEL: Pareto por exactitud de cantidad — proveedores
CONFIG: Método de categoría de proveedor = ABC por calidad — exactitud de cantidad
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

### 2.17 Categoría de proveedor — ABC por devoluciones
DESCRIPCION: Clasifica a los proveedores según la cantidad de recepciones que fueron revertidas (devueltas al proveedor). La clasificación es inversa: el proveedor con menos devoluciones recibe la categoría A. Los proveedores con compras en el período y cero devoluciones cuentan como 0 (mejor caso) y se clasifican como A; solo los proveedores sin actividad de compra en el período quedan como E (sin datos).
VARIABLES:
- dev_j = cantidad de recepciones revertidas del proveedor j en el período (0 si tuvo compras y ninguna devolución)
- pos_j = percentil de posición ordenando de menor dev a mayor (reparto por cuotas fijas, NO por participación acumulada)
FORMULA: pos_j = (índice_j + 1) / n_proveedores_con_actividad
LABEL: Ranking por percentil por devoluciones — proveedores
CONFIG: Método de categoría de proveedor = ABC por calidad — devoluciones
CONDICIONES (los umbrales se interpretan como percentiles de posición):
- pos_j <= umbral_A -> A (menos devoluciones)
- pos_j <= umbral_B -> B
- pos_j <= umbral_C -> C
- pos_j <= umbral_D -> D
- sin actividad de compra en el período -> E (sin datos)

---

### 2.18 Categoría de proveedor — ABC por calidad combinada
DESCRIPCION: Clasifica a los proveedores promediando dos métricas de calidad: el porcentaje de entregas a tiempo y el porcentaje de movimientos con cantidad exacta. El resultado es el índice de calidad compuesto sobre el que se aplica Pareto descendente.
VARIABLES:
- OT_j = porcentaje de recepciones a tiempo del proveedor j
- EX_j = porcentaje de movimientos con cantidad exacta del proveedor j
- Q_j = índice de calidad combinado del proveedor j
- P_cum_j = participación acumulada ordenando de mayor Q a menor
FORMULA: Q_j = (OT_j + EX_j) / 2 ; P_cum_j = sum(P_k para todo k con Q_k >= Q_j)
LABEL: Pareto por calidad combinada — proveedores
CONFIG: Método de categoría de proveedor = ABC por calidad — combinado
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

## Sección 3 — Panel de Ventas

---

### 3.1 Cantidad vendida y monto aproximado
DESCRIPCION: Agrega las unidades de salidas completadas en el período por producto base, sumando todas las variantes. El monto es una aproximación: usa el precio de lista vigente al momento del cálculo, no el precio real de cada venta.
VARIABLES:
- q_i = unidades de la salida i para el producto base p
- Q_p = cantidad total vendida del producto p en el período
- L_p = precio de lista actual del producto p
- M_p = monto aproximado del producto p
FORMULA: Q_p = sum(q_i para toda salida i del producto p en el período) ; M_p = Q_p * L_p
LABEL: Cantidad vendida y monto por producto

---

### 3.2 Categoría de venta — Rotación (fuente: entregas)
DESCRIPCION: Asigna una categoría A–E a cada artículo según sus días de cobertura, calculados a partir del stock actual y el promedio mensual de unidades entregadas en el período de análisis. Menor rotación corresponde a categoría más baja.
VARIABLES:
- sal = suma de unidades de salidas completadas del artículo en el período de análisis
- n_m = número de meses del período de análisis (configurable, def: 3)
- prom_m = promedio mensual de salidas
- S = stock actual en ubicaciones internas
- DIO = días de inventario
FORMULA: prom_m = sal / n_m ; DIO = (S / prom_m) * 30
LABEL: Días de inventario — rotación por entregas (categoría de venta)
CONFIG: Categorías de venta — Fuente del denominador de rotación = Entregas completadas
CONDICIONES:
- DIO <= umbral_A_dias -> A
- DIO <= umbral_B_dias -> B
- DIO <= umbral_C_dias -> C
- DIO <= umbral_D_dias -> D
- sin ventas OR DIO > umbral_D_dias -> E
- prom_m = 0 -> DIO = 999 (sin movimiento)

---

### 3.2b Categoría de venta — Rotación (fuente: demanda de pedidos)
DESCRIPCION: Igual que el bloque anterior, pero el denominador de la rotación son las unidades en órdenes de venta confirmadas del período en lugar de las entregas completadas.
VARIABLES:
- dem = suma de unidades en órdenes de venta confirmadas del artículo en el período
- n_m = número de meses del período de análisis
- prom_m = promedio mensual de demanda
- S = stock actual
- DIO = días de inventario
FORMULA: prom_m = dem / n_m ; DIO = (S / prom_m) * 30
LABEL: Días de inventario — rotación por demanda OV (categoría de venta)
CONFIG: Categorías de venta — Fuente del denominador de rotación = Demanda confirmada (órdenes de venta)
CONDICIONES:
- DIO <= umbral_A_dias -> A
- DIO <= umbral_B_dias -> B
- DIO <= umbral_C_dias -> C
- DIO <= umbral_D_dias -> D
- sin demanda OR DIO > umbral_D_dias -> E

---

### 3.3 Categoría de venta — Modo Demanda
DESCRIPCION: Asigna una categoría A–E según el promedio mensual de unidades salientes del artículo en el período configurado. Mayor demanda promedio corresponde a categoría más alta.
VARIABLES:
- sal = suma de unidades de salidas completadas del artículo en el período
- n_m = número de meses del período (configurable, def: 3)
- D_avg = promedio mensual de demanda en unidades por mes
FORMULA: D_avg = sal / n_m
LABEL: Demanda promedio mensual (categoría de venta)
CONFIG: Categorías de venta — Modo de asignación = Por demanda (promedio mensual de unidades)
CONDICIONES:
- D_avg >= umbral_A_upm -> A
- D_avg >= umbral_B_upm -> B
- D_avg >= umbral_C_upm -> C
- D_avg >= umbral_D_upm -> D
- D_avg < umbral_D_upm -> E

---

### 3.4 Categoría de venta — Pareto por unidades
DESCRIPCION: Clasifica los artículos según su participación acumulada en el total de unidades vendidas en el período. Los que concentran el mayor volumen reciben la categoría más alta.
VARIABLES:
- U_i = unidades vendidas del artículo i en el período
- U_tot = suma de U_i de todos los artículos
- P_i = participación del artículo i en el total de unidades (%)
- P_cum_i = participación acumulada ordenando de mayor a menor
FORMULA: P_i = U_i / U_tot * 100 ; P_cum_i = sum(P_k para todo k con U_k >= U_i)
LABEL: Participación acumulada por unidades (artículos)
CONFIG: Categorías de venta — Métrica de participación acumulada = Unidades entregadas
CONDICIONES:
- P_cum_i <= umbral_A -> A
- P_cum_i <= umbral_B -> B
- P_cum_i <= umbral_C -> C
- P_cum_i <= umbral_D -> D
- P_cum_i > umbral_D -> E

---

### 3.4b Categoría de venta — Pareto por importe
DESCRIPCION: Clasifica los artículos según su participación acumulada en el importe total de ventas, calculado como precio de lista actual por unidades vendidas. Los que concentran el mayor valor reciben la categoría más alta.
VARIABLES:
- I_i = unidades_i * precio_de_lista_i del artículo i en el período
- I_tot = suma de I_i de todos los artículos
- P_i = participación del artículo i en el importe total (%)
- P_cum_i = participación acumulada ordenando de mayor a menor
FORMULA: P_i = I_i / I_tot * 100 ; P_cum_i = sum(P_k para todo k con I_k >= I_i)
LABEL: Participación acumulada por importe (artículos)
CONFIG: Categorías de venta — Métrica de participación acumulada = Importe (precio de lista × cantidad)
CONDICIONES:
- P_cum_i <= umbral_A -> A
- P_cum_i <= umbral_B -> B
- P_cum_i <= umbral_C -> C
- P_cum_i <= umbral_D -> D
- P_cum_i > umbral_D -> E

---

### 3.5 Tasa de servicio — forecast global
DESCRIPCION: Mide qué fracción de la demanda total confirmada en órdenes de venta del período fue efectivamente entregada. Incluye solo los productos que tienen líneas de forecast asociadas.
VARIABLES:
- E_tot = suma de unidades entregadas (salidas completadas) del período, para productos con forecast
- OV_tot = suma de unidades en órdenes de venta confirmadas del período
- TS = tasa de servicio (%)
FORMULA: TS = E_tot / OV_tot * 100
LABEL: Tasa de servicio global (%)
CONDICIONES:
- TS >= 95 -> verde
- 80 <= TS < 95 -> amarillo
- TS < 80 -> rojo

---

### 3.6 Gap de demanda — forecast global
DESCRIPCION: Mide en qué porcentaje la demanda real de pedidos superó o quedó por debajo del forecast planificado en el período. Un valor positivo indica que la demanda superó las expectativas del plan.
VARIABLES:
- OV_tot = suma de unidades en órdenes de venta confirmadas del período
- FC_tot = suma de todas las cantidades de forecast del período
- gap_dem = gap de demanda (%)
FORMULA: gap_dem = (OV_tot - FC_tot) / FC_tot * 100
LABEL: Gap de demanda vs. forecast (%)
CONDICIONES:
- abs(gap_dem) <= 10 -> verde
- abs(gap_dem) <= 25 -> amarillo
- abs(gap_dem) > 25 -> rojo

---

### 3.7 Gap de OFs — forecast global
DESCRIPCION: Mide en qué porcentaje las órdenes de fabricación planificadas en el período cubren el forecast. Un valor negativo indica déficit de cobertura productiva.
VARIABLES:
- OF_tot = suma de cantidades de OFs del período (según criterio de asignación configurado)
- FC_tot = suma del forecast del período
- gap_OF = gap de cobertura por OFs (%)
FORMULA: gap_OF = (OF_tot - FC_tot) / FC_tot * 100
LABEL: Gap de OFs vs. forecast (%)
CONDICIONES:
- gap_OF >= 0 -> verde
- -10 <= gap_OF < 0 -> amarillo
- gap_OF < -10 -> rojo

---

### 3.8 % Cobertura de OFs — denominador: forecast planificado
DESCRIPCION: Para cada celda (producto × mes) de la tabla de forecast, mide qué porcentaje del forecast planificado está cubierto por órdenes de fabricación asignadas a ese mes.
VARIABLES:
- OF_m = suma de cantidades de OFs del producto asignadas al mes
- FC_m = forecast planificado del producto para el mes
- cob = porcentaje de cobertura
FORMULA: cob = OF_m / FC_m * 100
LABEL: % Cobertura OFs / forecast planificado
CONFIG: Forecast — Divisor del % de cobertura de OFs = Forecast planificado
CONDICIONES:
- cob >= 100 -> verde
- cob >= umbral_aviso_config -> amarillo
- cob < umbral_aviso_config -> rojo
- FC_m = 0 -> cob = 0

---

### 3.8b % Cobertura de OFs — denominador: demanda real (OV)
DESCRIPCION: Igual que el bloque anterior, pero el denominador es la demanda real confirmada en órdenes de venta del mes en lugar del forecast planificado.
VARIABLES:
- OF_m = suma de cantidades de OFs del producto asignadas al mes
- OV_m = unidades en órdenes de venta confirmadas del producto en el mes
- cob = porcentaje de cobertura
FORMULA: cob = OF_m / OV_m * 100
LABEL: % Cobertura OFs / demanda real (OV)
CONFIG: Forecast — Divisor del % de cobertura de OFs = Demanda real (pedidos SO)
CONDICIONES:
- cob >= 100 -> verde
- cob >= umbral_aviso_config -> amarillo
- cob < umbral_aviso_config -> rojo
- OV_m = 0 -> cob = 0

---

### 3.9 Rotación de inventario en forecast — por unidades
DESCRIPCION: Estima los meses o días de stock que quedan para el artículo, usando el promedio mensual de unidades entregadas en el rango del forecast y el stock promedio del período (promedio entre el stock al inicio y al fin del rango).
VARIABLES:
- E_per = suma de unidades entregadas del artículo en el rango del forecast
- n_m = número de meses del rango del forecast
- prom_m = promedio mensual de unidades entregadas
- S_ini = stock del artículo al inicio del rango (reconstruido desde stock.move)
- S_fin = stock del artículo al fin del rango (reconstruido desde stock.move)
- S = stock promedio del período = (S_ini + S_fin) / 2
- rot_m = rotación en meses
- rot_d = rotación en días
FORMULA: S = (S_ini + S_fin) / 2 ; prom_m = E_per / n_m ; rot_m = S / prom_m ; rot_d = rot_m * 30
LABEL: Rotación de inventario — por unidades (forecast)
CONFIG: Forecast — Método de rotación de inventario = Por unidades
CONDICIONES:
- rot_m <= 3 -> verde ; 4 <= rot_m <= 6 -> amarillo ; rot_m > 6 -> sin color
- rot_d <= 90 -> verde ; 91 <= rot_d <= 180 -> amarillo ; rot_d > 180 -> sin color

---

### 3.9b Rotación de inventario en forecast — por COGS
DESCRIPCION: Estima los días de inventario comparando el valor del stock promedio (a costo estándar) contra el costo de lo vendido en el rango del forecast.
VARIABLES:
- I_ini = stock inicial × costo estándar del producto
- I_fin = stock final × costo estándar del producto
- I_avg = inventario promedio valorizado a costo
- COGS = suma de (precio unitario a costo × cantidad) de salidas completadas en el rango
- D = días del rango del forecast
- DIO = días de inventario
FORMULA: I_avg = (I_ini + I_fin) / 2 ; DIO = D * I_avg / COGS
LABEL: Días de inventario — por COGS (forecast)
CONFIG: Forecast — Método de rotación de inventario = Por COGS (a costo)

---

### 3.9c Rotación de inventario en forecast — por ventas
DESCRIPCION: Estima los días de inventario comparando el valor del stock promedio (a precio de lista) contra las ventas netas en el rango del forecast valoradas a precio de lista.
VARIABLES:
- I_ini = stock inicial × precio de lista del producto
- I_fin = stock final × precio de lista del producto
- I_avg = inventario promedio valorizado a precio de lista
- V_net = suma de ventas netas del artículo en el rango (salidas valoradas a precio de lista)
- D = días del rango del forecast
- DIO = días de inventario
FORMULA: I_avg = (I_ini + I_fin) / 2 ; DIO = D * I_avg / V_net
LABEL: Días de inventario — por ventas (forecast)
CONFIG: Forecast — Método de rotación de inventario = Por ventas (a precio de lista)

---

### 3.10 Cobertura de inventario — fuente: forecast planificado
DESCRIPCION: Calcula cuántos días alcanza el stock actual si la demanda de referencia fuera el forecast planificado del período. Mide la autonomía del inventario frente al plan de ventas.
VARIABLES:
- S = stock actual del artículo en ubicaciones internas
- FC = total de forecast planificado del artículo en el período
- D = días del período del forecast
- cov_d = cobertura en días
FORMULA: cov_d = S * D / FC
LABEL: Días de cobertura — vs. forecast planificado
CONFIG: Forecast — Fuente de demanda para cobertura de inventario = Forecast planificado
CONDICIONES:
- FC = 0 -> cobertura indefinida (no se muestra)

---

### 3.10b Cobertura de inventario — fuente: demanda real (OV)
DESCRIPCION: Calcula cuántos días alcanza el stock actual si la demanda de referencia fueran las unidades en órdenes de venta confirmadas del período.
VARIABLES:
- S = stock actual
- OV = total de unidades en órdenes de venta confirmadas del artículo en el período
- D = días del período
- cov_d = cobertura en días
FORMULA: cov_d = S * D / OV
LABEL: Días de cobertura — vs. demanda real (OV)
CONFIG: Forecast — Fuente de demanda para cobertura de inventario = Demanda real (pedidos SO)
CONDICIONES:
- OV = 0 -> cobertura indefinida (no se muestra)

---

### 3.10c Cobertura de inventario — fuente: entregado histórico
DESCRIPCION: Calcula cuántos días alcanza el stock actual si la demanda de referencia fueran las unidades efectivamente entregadas (salidas completadas) del período.
VARIABLES:
- S = stock actual
- E = total de unidades entregadas del artículo en el período
- D = días del período
- cov_d = cobertura en días
FORMULA: cov_d = S * D / E
LABEL: Días de cobertura — vs. entregado histórico
CONFIG: Forecast — Fuente de demanda para cobertura de inventario = Entregado histórico
CONDICIONES:
- E = 0 -> cobertura indefinida (no se muestra)

---

### 3.11 Fuente del «real» para precisión — demanda confirmada
DESCRIPCION: Define qué se entiende por «real» en todos los cálculos de precisión de forecast: las unidades pedidas en órdenes de venta confirmadas o cerradas del período. Mide con qué precisión el forecast anticipó la demanda comercial registrada.
VARIABLES:
- real_t = suma de unidades en órdenes de venta confirmadas o cerradas del período t
FORMULA: real_t = sum(unidades en ordenes de venta confirmadas del período t)
LABEL: Fuente del real — demanda OV
CONFIG: Forecast — Fuente del «real» para precisión = Demanda confirmada (órdenes de venta)

---

### 3.11b Fuente del «real» para precisión — entregas completadas
DESCRIPCION: Define qué se entiende por «real» en todos los cálculos de precisión de forecast: las unidades efectivamente entregadas (salidas de stock completadas) del período. Mide con qué precisión el forecast anticipó los despachos reales.
VARIABLES:
- real_t = suma de unidades de salidas de stock completadas del período t
FORMULA: real_t = sum(unidades entregadas en salidas completadas del período t)
LABEL: Fuente del real — entregas completadas
CONFIG: Forecast — Fuente del «real» para precisión = Entregas completadas

---

### 3.12 Precisión de forecast — Simple
DESCRIPCION: Mide la precisión de cada celda como el cociente entre el volumen real y el forecast planificado. Un resultado del 100 % indica coincidencia exacta; más del 100 % indica que la demanda superó el forecast.
VARIABLES:
- FC_t = forecast planificado del producto para el período t
- real_t = volumen real del período t (según fuente configurada)
- prec_t = precisión del período t (%)
- prec_total = precisión global del producto
FORMULA: prec_t = real_t / FC_t * 100 ; prec_total = sum(real_t) / sum(FC_t) * 100
LABEL: Precisión Simple (%)
CONFIG: Forecast — Fórmula de precisión = Simple
CONDICIONES:
- prec >= 90 -> verde
- 70 <= prec < 90 -> amarillo
- prec < 70 -> rojo
- FC_t = 0 -> prec_t no se muestra

---

### 3.12b Precisión de forecast — MAPE
DESCRIPCION: Promedia el error porcentual absoluto de cada período individual. Es muy sensible cuando la demanda real es baja o cero, porque un pequeño error genera un porcentaje alto. El resultado se expresa como precisión (100 % menos el error medio).
VARIABLES:
- FC_t = forecast planificado del período t
- real_t = volumen real del período t
- prec_t = max(0, 100 - abs(real_t - FC_t) / real_t * 100)
- prec_total = promedio de prec_t para períodos con real_t > 0
FORMULA: prec_t = max(0, 100 - abs(real_t - FC_t) / real_t * 100) ; prec_total = avg(prec_t para todo t con real_t > 0)
LABEL: Precisión MAPE (%)
CONFIG: Forecast — Fórmula de precisión = MAPE (error porcentual absoluto medio)
CONDICIONES:
- prec >= 90 -> verde
- 70 <= prec < 90 -> amarillo
- prec < 70 -> rojo
- real_t = 0 -> período excluido del promedio

---

### 3.12c Precisión de forecast — WAPE
DESCRIPCION: Calcula el error absoluto total dividido por el volumen real total. Pondera automáticamente los períodos de mayor demanda y es robusto cuando hay períodos con forecast cero, porque el denominador es el real total.
VARIABLES:
- err_t = abs(real_t - FC_t) para el período t
- real_t = volumen real del período t
- prec_total = precisión global ponderada por demanda real
FORMULA: prec_total = max(0, 100 - sum(err_t) / sum(real_t) * 100)
LABEL: Precisión WAPE — ponderada por demanda real (%)
CONFIG: Forecast — Fórmula de precisión = WAPE (error ponderado por demanda real)
CONDICIONES:
- prec >= 90 -> verde
- 70 <= prec < 90 -> amarillo
- prec < 70 -> rojo

---

### 3.12d Precisión de forecast — WMAPE
DESCRIPCION: Similar a WAPE, pero el denominador es el volumen planificado (forecast) en lugar del real. Penaliza más los errores en períodos donde se esperaba mayor venta. Es el estándar más usado en supply chain.
VARIABLES:
- err_t = abs(real_t - FC_t) para el período t
- FC_t = forecast planificado del período t
- prec_total = precisión global ponderada por forecast
FORMULA: prec_total = max(0, 100 - sum(err_t) / sum(FC_t) * 100)
LABEL: Precisión WMAPE — ponderada por forecast (%)
CONFIG: Forecast — Fórmula de precisión = WMAPE (error ponderado por forecast)
CONDICIONES:
- prec >= 90 -> verde
- 70 <= prec < 90 -> amarillo
- prec < 70 -> rojo

---

### 3.12e Sesgo de forecast
DESCRIPCION: Mide si el forecast tiende sistemáticamente a sobreestimar o subestimar la demanda. Un valor positivo indica que la demanda superó el forecast en forma consistente (forecast conservador); uno negativo indica forecast optimista.
VARIABLES:
- FC_t = forecast planificado del período t
- real_t = volumen real del período t
- sesgo_t = sesgo del período t (%)
- sesgo_total = sesgo global del producto
FORMULA: sesgo_t = (real_t - FC_t) / FC_t * 100 ; sesgo_total = (sum(real_t) - sum(FC_t)) / sum(FC_t) * 100
LABEL: Sesgo de forecast — Bias (%)
CONFIG: Forecast — Fórmula de precisión = Sesgo (Bias)
CONDICIONES:
- abs(sesgo) <= 10 -> verde
- 10 < abs(sesgo) <= 20 -> amarillo
- abs(sesgo) > 20 -> rojo
- FC_t = 0 -> sesgo_t no se muestra

---

### 3.13 Período de análisis — categorías de cliente
DESCRIPCION: Define el horizonte temporal que se considera al ejecutar la clasificación automática de clientes. La fecha de inicio del análisis se calcula restando ese número de meses (a razón de 30 días por mes) a la fecha actual.
VARIABLES:
- M_c = meses configurados para categorías de cliente (def: 12)
- F_ini = fecha de inicio del período de análisis
FORMULA: F_ini = hoy - M_c * 30 dias
LABEL: Horizonte temporal — categorías de cliente
CONFIG: Período de análisis de clientes = N meses (configurable, def: 12 meses)

---

### 3.14 Categoría de cliente — Manual
DESCRIPCION: La categoría A–E del cliente se asigna directamente por el usuario en la ficha del cliente. No existe cálculo automático; el valor se mantiene hasta que el usuario lo modifique manualmente.
VARIABLES:
- ninguna
FORMULA: clasificación manual (sin cálculo automático)
LABEL: Categoría de cliente — manual
CONFIG: Método de categoría de cliente = Manual (asignación directa)

---

### 3.15 Categoría de cliente — ABC por volumen
DESCRIPCION: Clasifica a los clientes según el importe total de sus órdenes de venta en el período configurado. Los que concentran el mayor importe reciben la categoría más alta.
VARIABLES:
- V_j = importe total de OVs del cliente j en el período
- V_tot = suma de V_j de todos los clientes
- P_j = participación del cliente j en el importe total (%)
- P_cum_j = participación acumulada ordenando de mayor a menor
FORMULA: P_j = V_j / V_tot * 100 ; P_cum_j = sum(P_k para todo k con V_k >= V_j)
LABEL: Pareto por importe — clientes
CONFIG: Método de categoría de cliente = ABC por volumen (importe de pedidos)
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

### 3.16 Categoría de cliente — ABC por frecuencia
DESCRIPCION: Clasifica a los clientes según la cantidad de órdenes de venta confirmadas en el período configurado. Los que compran con mayor frecuencia reciben la categoría más alta.
VARIABLES:
- F_j = cantidad de OVs del cliente j en el período
- F_tot = suma de F_j de todos los clientes
- P_j = participación del cliente j en la frecuencia total (%)
- P_cum_j = participación acumulada ordenando de mayor a menor
FORMULA: P_j = F_j / F_tot * 100 ; P_cum_j = sum(P_k para todo k con F_k >= F_j)
LABEL: Pareto por frecuencia — clientes
CONFIG: Método de categoría de cliente = ABC por frecuencia (cantidad de pedidos)
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_B -> B
- P_cum_j <= umbral_C -> C
- P_cum_j <= umbral_D -> D
- P_cum_j > umbral_D -> E

---

### 3.17 Categoría de cliente — ABC por RFM
DESCRIPCION: Clasifica a los clientes combinando tres dimensiones: Recencia (cuándo fue el último pedido), Frecuencia (cuántos pedidos en el período) y Monto (importe total). Cada dimensión recibe 1 a 3 puntos; la suma de los tres determina la categoría.
VARIABLES:
- R = puntuación de recencia (días desde la última OV)
- F_score = puntuación de frecuencia (cantidad de OVs en el período)
- M = puntuación de monto (percentil del importe vs. el grupo)
- T = puntaje total (R + F_score + M)
FORMULA: T = R + F_score + M
LABEL: Puntaje RFM — cliente
CONFIG: Método de categoría de cliente = ABC por RFM
CONDICIONES (los cortes son configurables en Ajustes → "Parámetros RFM", compartidos con proveedores; entre paréntesis los valores por defecto):
- R: dias_ultima_OV < rfm_recency_recent_days (30) -> 3 pts ; < rfm_recency_medium_days (90) -> 2 pts ; resto -> 1 pt
- F_score: count_OVs > rfm_freq_high (10) -> 3 pts ; >= rfm_freq_medium (3) -> 2 pts ; resto -> 1 pt
- M: percentil >= 66 -> 3 pts ; percentil >= 33 -> 2 pts ; resto -> 1 pt
- T >= rfm_score_a (8) -> A ; T >= rfm_score_b (6) -> B ; T >= rfm_score_c (4) -> C ; T >= rfm_score_d (3) -> D
- sin datos en el período -> E

---

## Sección 4 — Análisis de clientes

---

### 4.1 % de entrega
DESCRIPCION: Mide qué fracción de las unidades pedidas en órdenes de venta confirmadas del período fue efectivamente entregada al cliente. Un valor del 100 % indica que todo lo solicitado fue despachado.
VARIABLES:
- Q_ped = suma de unidades en líneas de órdenes de venta confirmadas del período
- Q_entr = suma de unidades en salidas de stock completadas del período para ese cliente
- pct_entr = porcentaje de entrega
FORMULA: pct_entr = Q_entr / Q_ped * 100
LABEL: % de entrega (cliente)

---

### 4.2 % a tiempo — fecha compromiso del pedido
DESCRIPCION: Mide el porcentaje de envíos completados antes o en la fecha comprometida con el cliente al confirmar el pedido. Los envíos sin fecha de compromiso registrada se excluyen del cómputo.
VARIABLES:
- n_ot = cantidad de envíos del cliente donde fecha_cierre_envio <= fecha_compromiso_pedido
- n_tot = total de envíos del cliente con fecha de compromiso definida
- pct_ot = porcentaje a tiempo
FORMULA: pct_ot = n_ot / n_tot * 100
LABEL: % a tiempo — fecha compromiso (cliente)
CONFIG: Análisis de clientes — Definición de «a tiempo» = Fecha compromiso del pedido (predeterminado)

---

### 4.3 % a tiempo — fecha programada del envío
DESCRIPCION: Mide el porcentaje de envíos completados antes o en la fecha programada del picking de salida. Los envíos sin fecha programada se excluyen del cómputo.
VARIABLES:
- n_ot = cantidad de envíos del cliente donde fecha_cierre_envio <= fecha_programada_envio
- n_tot = total de envíos del cliente con fecha programada definida
- pct_ot = porcentaje a tiempo
FORMULA: pct_ot = n_ot / n_tot * 100
LABEL: % a tiempo — fecha programada del envío (cliente)
CONFIG: Análisis de clientes — Definición de «a tiempo» = Fecha programada del envío

---

### 4.4 % a tiempo — SLA en días desde confirmación
DESCRIPCION: Mide el porcentaje de envíos completados dentro del plazo SLA configurado, contado desde la fecha de confirmación del pedido. El número de días es un parámetro configurable.
VARIABLES:
- D_confirm = fecha de confirmación del pedido
- N = plazo SLA en días (configurable)
- D_limite = D_confirm + N dias
- n_ot = cantidad de envíos del cliente donde fecha_cierre_envio <= D_limite
- n_tot = total de envíos del cliente en el período
- pct_ot = porcentaje a tiempo
FORMULA: D_limite = D_confirm + N ; pct_ot = n_ot / n_tot * 100
LABEL: % a tiempo — SLA días desde confirmación (cliente)
CONFIG: Análisis de clientes — Definición de «a tiempo» = Días desde confirmación del pedido (SLA configurable)

---

### 4.5 Intervalos entre pedidos
DESCRIPCION: Mide la regularidad de compra de un cliente calculando el promedio de días entre pedidos consecutivos en el período. Un valor bajo indica compras frecuentes y regulares.
VARIABLES:
- D_i = fecha de confirmación del pedido i, ordenada cronológicamente
- g_i = gap en días entre el pedido i+1 y el pedido i
- n_gaps = cantidad de gaps (= cantidad de pedidos - 1)
- G_avg = promedio de intervalos en días
FORMULA: g_i = D_{i+1} - D_i ; G_avg = sum(g_i para i=1..n_gaps) / n_gaps
LABEL: Intervalo promedio entre pedidos (días)
CONDICIONES:
- n_gaps = 0 (solo 1 pedido en el período) -> G_avg no se muestra

---

### 4.6 Ticket promedio
DESCRIPCION: Calcula el importe promedio por pedido del cliente en el período. Refleja el valor típico de cada transacción.
VARIABLES:
- I_tot = suma de importes de todas las órdenes de venta del cliente en el período
- n_ped = cantidad de órdenes de venta del cliente en el período
- T_avg = ticket promedio
FORMULA: T_avg = I_tot / n_ped
LABEL: Ticket promedio (importe por pedido)

---

### 4.7 Tendencia de ventas
DESCRIPCION: Compara el importe total del cliente en el período seleccionado contra el mismo período desplazado un año hacia atrás. Un valor positivo indica crecimiento interanual.
VARIABLES:
- I_act = importe total de órdenes de venta del período actual
- I_ant = importe total de órdenes de venta del mismo rango de fechas, 1 año antes
- trend = variación porcentual interanual
FORMULA: trend = (I_act - I_ant) / I_ant * 100
LABEL: Tendencia de ventas (% interanual)
CONDICIONES:
- I_ant = 0 -> trend no se muestra (sin historial el año anterior)

---

### 4.8 ABC del período — clasificación en tiempo real
DESCRIPCION: Clasifica a los clientes activos en el período según su participación acumulada en el importe total de ventas del mismo período. Esta clasificación se calcula al vuelo para el widget y es independiente de la categoría permanente asignada por el proceso de categorización automática.
VARIABLES:
- I_j = importe total del cliente j en el período
- I_tot = suma de I_j de todos los clientes activos en el período
- P_j = participación del cliente j en el importe total (%)
- P_cum_j = participación acumulada, ordenada de mayor a menor
FORMULA: P_j = I_j / I_tot * 100 ; P_cum_j = sum(P_k para todo k con I_k >= I_j)
LABEL: ABC del período (clasificación en tiempo real)
CONDICIONES:
- P_cum_j <= umbral_A -> A
- P_cum_j <= umbral_A + umbral_B -> B
- P_cum_j > umbral_A + umbral_B -> C

---

### 4.9 Segmento de frecuencia
DESCRIPCION: Clasifica a cada cliente según la regularidad y recencia de sus pedidos. La condición «En riesgo» tiene precedencia sobre todas las demás: un cliente frecuente que no compra desde hace más del umbral configurado se clasifica como en riesgo de todos modos.
VARIABLES:
- d_ult = días desde el último pedido hasta hoy
- G_avg = promedio de intervalos entre pedidos (ver bloque 4.5)
- R_dias = umbral de riesgo en días (configurable, def: 90)
FORMULA: clasificación por reglas secuenciales (ver CONDICIONES)
LABEL: Segmento de frecuencia (cliente)
CONDICIONES:
- d_ult > R_dias -> En riesgo (tiene precedencia sobre las demás)
- G_avg <= 30 -> Frecuente
- G_avg <= 90 -> Ocasional
- G_avg > 90 -> Inactivo
