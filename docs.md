# Documentación de fórmulas de cálculo

## 1. Alertas — generación y severidad

### 1.1 OFs atrasadas
Se genera una alerta cuando una OF activa (Confirmada, En progreso o Por cerrar) tiene su fecha de fin planificada en el pasado. El sistema corre este chequeo periódicamente según el intervalo configurado en ajustes.

**Días de atraso:** diferencia en días entre hoy y la fecha de fin planificada de la OF. Si el resultado es negativo se muestra como cero.

**Severidad:**
- Amarilla si el atraso es menor a los días críticos configurados (default: 3 días)
- Roja si el atraso es igual o mayor a los días críticos configurados

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.2 OFs por vencer
Se genera una alerta cuando una OF activa tiene su fecha de fin planificada dentro del horizonte de aviso configurado en ajustes (default: próximos 7 días), pero aún no está vencida.

**Días hasta el vencimiento:** diferencia en días entre la fecha de fin planificada y hoy.

**Severidad:** siempre amarilla.

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.3 Cantidad diferente
Se genera una alerta cuando una OF recién cerrada (estado Terminada) produjo una cantidad que difiere de la planificada más allá de la tolerancia configurada.

**Cálculo de la diferencia:** valor absoluto de (cantidad producida menos cantidad planificada), dividido por la cantidad planificada. Si ese porcentaje supera la tolerancia configurada (default: 5%), se genera la alerta.

**Cantidad producida:** suma de las unidades registradas en los movimientos de salida completados de la OF, para el producto principal.

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.4 OFs canceladas
Se genera automáticamente cuando una OF pasa al estado Cancelada. No se resuelve sola — requiere acción manual del usuario.

**Severidad:** siempre amarilla.

No se generan alertas para OFs cuya LdM sea de tipo Subcontratación.

---

### 1.5 OCs vencidas
Se genera cuando una OC aprobada tiene su fecha de entrega estimada en el pasado.

**Fecha considerada:** fecha de entrega estimada de la OC (`date_planned`), no la fecha de emisión.

**Días de atraso:** diferencia en días entre hoy y la fecha de entrega estimada.

**Severidad:**
- Amarilla si el atraso es menor a los días críticos configurados (default: 5 días)
- Roja si el atraso es igual o mayor a los días críticos configurados

---

### 1.6 OCs por vencer
Se genera cuando una OC aprobada y no totalmente recibida tiene su fecha de entrega estimada dentro del horizonte de aviso configurado (default: próximos 10 días), pero aún no está vencida.

**Severidad:** siempre amarilla.

---

### 1.7 Recepciones atrasadas
Se genera cuando una recepción pendiente tiene su fecha programada en el pasado.

**Fecha considerada:** fecha programada del movimiento de stock (`scheduled_date`).

**Días de atraso:** diferencia en días entre hoy y la fecha programada de la recepción.

**Severidad:**
- Amarilla si el atraso es menor a los días críticos de recepción configurados (default: 3 días)
- Roja si el atraso es igual o mayor a los días críticos configurados

**Problema conocido (C4):** actualmente incluye movimientos internos además de recepciones de OCs.

---

### 1.8 Días de atraso por tipo de alerta (campo calculado)
El campo "días de atraso" se recalcula en tiempo real contra la fecha de referencia de cada tipo de alerta:

| Tipo de alerta                                            | Fecha de referencia                |
|-----------------------------------------------------------|------------------------------------|
| OFs atrasadas / por vencer / cant. diferente / canceladas | Fecha de fin planificada de la OF  |
| OCs vencidas / por vencer / canceladas                    | Fecha de entrega estimada de la OC |
| Recepciones atrasadas                                     | Fecha programada de la recepción   |

El valor siempre es cero o positivo — nunca negativo.

---

## 2. Panel de Producción — KPIs del widget OFs

| KPI              | Qué cuenta                                             |
|------------------|--------------------------------------------------------|
| Activas          | OFs que no están en estado Terminada ni Cancelada      |
| En progreso      | OFs activas en estado En progreso o Por cerrar         |
| Atrasadas        | OFs activas cuya fecha de fin planificada ya pasó      |
| Para reprogramar | OFs activas marcadas como "necesita reprogramación"    |
| Finalizadas      | OFs en estado Terminada                                |
| Por cerrar       | OFs activas en estado Por cerrar                       |

**Problema conocido (P1):** ninguno de estos conteos excluye OFs de subcontratación.

---

## 3. Panel de Producción — KPIs de alertas (tarjetas)

Cada tarjeta cuenta las alertas no resueltas de ese tipo, excluyendo las que corresponden a OFs con LdM de tipo Subcontratación. Si se aplica el filtro de estados, solo se cuentan alertas cuya OF esté en los estados seleccionados.

| Tarjeta          | Qué cuenta                                          |
|------------------|-----------------------------------------------------|
| OFs atrasadas    | Alertas activas de tipo "OF atrasada"               |
| OFs por vencer   | Alertas activas de tipo "OF por vencer"             |
| Cant. diferentes | Alertas activas de tipo "Cantidad diferente"        |
| OFs canceladas   | Alertas activas de tipo "OF cancelada"              |
| Badge críticas   | Alertas activas con severidad roja (cualquier tipo) |

---

## 4. Panel de Producción — Carga de centros de trabajo

### Horas disponibles
Se calculan a partir del calendario laboral del centro de trabajo para el período seleccionado, multiplicadas por el porcentaje de eficiencia configurado en el centro. Si el calendario no puede calcularse, se estima proporcionalmente a partir de las horas semanales de asistencia.

### Horas ejecutadas
Suma de las horas de las operaciones (work orders) ya terminadas que se solapan con el período. Cuando una operación se solapa parcialmente, se toma la proporción correspondiente al solapamiento.

### Horas pendientes
Suma de las horas de las operaciones en curso o planificadas que se solapan con el período, calculadas de la misma forma que las ejecutadas.

### Tiempo libre
Horas disponibles menos ejecutadas menos pendientes. Si el resultado es negativo se muestra como cero.

### Carga del centro (%)
(Horas ejecutadas + horas pendientes) dividido por las horas disponibles, multiplicado por 100.

**Colores:** verde si la carga es menor al 70%, amarillo entre 70% y 89%, rojo desde el 90%.

---

## 5. Panel de Producción — Producido vs programado

Para cada producto, se compara la cantidad total de OFs planificadas contra la cantidad realmente producida en el período:

- **Planificado:** suma de la cantidad planificada de todas las OFs del período para ese producto.
- **Producido:** suma de las unidades registradas en los movimientos de salida completados de esas OFs.
- **% de cumplimiento:** producido dividido por planificado, multiplicado por 100.

---

## 6. Panel de Compras — KPIs del widget OCs

| KPI                | Qué cuenta                                                                              |
|--------------------|-----------------------------------------------------------------------------------------|
| Cotizaciones (RFQ) | OCs en estado Borrador o Enviada                                                        |
| Por aprobar        | OCs en estado "Esperando aprobación"                                                    |
| Total aprobadas    | OCs aprobadas que aún no están totalmente recibidas                                     |
| A tiempo           | OCs aprobadas cuya fecha de entrega estimada aún no pasó                                |
| Vencidas           | OCs aprobadas cuya fecha de entrega estimada ya pasó                                    |
| Críticas           | OCs vencidas con más días de atraso que el umbral crítico configurado (default: 5 días) |

**Problema conocido (C1):** el filtro de fecha filtra por fecha de entrega estimada, no por fecha de emisión de la OC.

---

## 7. Panel de Compras — KPIs de alertas

Cada tarjeta cuenta las alertas no resueltas del tipo correspondiente:

| Tarjeta        | Qué cuenta                                                               |
|----------------|--------------------------------------------------------------------------|
| OCs vencidas   | Alertas activas de tipo "OC vencida"                                     |
| OCs por vencer | Alertas activas de tipo "OC por vencer"                                  |
| OCs canceladas | Siempre 0 — el tipo de alerta nunca se genera (ver C3)                   |
| Recepciones    | Alertas activas de tipo "Recepción atrasada" — incluye internas (ver C4) |

---

## 8. Panel de Compras — Disponibilidad de recepciones y entregas

Cada recepción o entrega muestra su estado de disponibilidad de materiales:

| Estado        | Criterio                                                                           |
|---------------|------------------------------------------------------------------------------------|
| Disponible    | Todos los productos tienen stock reservado suficiente para cubrir la demanda       |
| Parcialmente  | Algunos productos tienen stock reservado pero no alcanzan a cubrir toda la demanda |
| No disponible | Ningún producto tiene stock reservado, o la recepción está en estado de espera     |

La cantidad disponible por línea se toma como el mayor valor entre la cantidad reservada y la cantidad ya registrada como movida.

**Días de retraso de recepción:** diferencia entre hoy y la fecha programada del picking. Siempre cero o positivo.

---

## 9. Panel de Ventas — Gráfico de productos más vendidos

### Cantidad vendida
Se suman todas las unidades de movimientos de stock de salida completados (entregas físicas) en el período seleccionado, para productos marcados como vendibles. Los resultados se agrupan por producto base (sumando todas sus variantes).

El período es una ventana deslizante hacia atrás desde hoy: 1 mes, 3 meses, 6 meses o 12 meses.

### Importe
Cantidad vendida multiplicada por el precio de lista actual del producto. **No refleja el precio real de la venta** — es una aproximación basada en el precio de lista vigente.

**Problema conocido (V2):** no existe opción para cambiar la fuente de datos a líneas de órdenes de venta. Actualmente solo usa entregas físicas completadas.

---

## 10. Forecast — KPIs globales

| KPI                 | Cómo se calcula                                                                                                                                                    |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Forecast total      | Suma de las cantidades de todas las líneas de forecast del período seleccionado                                                                                    |
| OFs planificadas    | Suma de las cantidades planificadas de OFs con fecha de fin en el período y en los estados habilitados en ajustes (por defecto: Confirmada, En progreso, Por cerrar) |
| Gap                 | OFs planificadas menos forecast total. Negativo indica déficit de producción                                                                                       |
| Cobertura %         | OFs planificadas dividido por forecast total, multiplicado por 100                                                                                                 |
| Productos en riesgo | Cantidad de productos cuya cobertura es menor al umbral de aviso configurado (default: 70%)                                                                        |
| Entregado total     | Suma de unidades de entregas físicas completadas (movimientos de stock de salida) para los productos con forecast, en el período                                   |
| Demanda OV          | Suma de las cantidades de líneas de órdenes de venta confirmadas o cerradas, con fecha de pedido en el período                                                     |
| Tasa de servicio    | Entregado total dividido por demanda OV, multiplicado por 100                                                                                                      |
| Precisión forecast  | Según la fórmula configurada en ajustes (ver sección 11)                                                                                                           |

---

## 11. Forecast — Fórmulas de precisión

En todas las fórmulas se trabaja con tres valores por período y producto:
- **Forecast:** cantidad planificada en la línea de forecast
- **Entregado:** unidades entregadas físicamente (movimientos de stock completados)
- **Error:** diferencia absoluta entre entregado y forecast

### Simple
La precisión de cada período es el porcentaje que representan las entregas respecto al forecast. Un valor de 100% significa que se entregó exactamente lo planificado. Por encima de 100% indica sobreentrega.

### MAPE — Error porcentual absoluto medio
Para cada período donde hubo entregas: la precisión es 100 menos el error expresado como porcentaje del entregado. La precisión global es el promedio de esas precisiones por período. Solo se consideran períodos con entregas mayores a cero.

### WAPE — Error porcentual absoluto ponderado por entregado
La precisión global es 100 menos la suma total de errores absolutos dividida por la suma total de lo entregado, todo multiplicado por 100. Pondera más los períodos de mayor volumen real.

### WMAPE — Error porcentual absoluto ponderado por forecast
Similar al WAPE pero el denominador es la suma total del forecast en lugar de lo entregado. Pondera más los períodos de mayor volumen planificado.

### Sesgo (Bias)
Mide si el forecast tiende sistemáticamente a sobreestimar o subestimar. Para cada período: entregado menos forecast, dividido por forecast, multiplicado por 100. Positivo significa sobreentrega habitual; negativo significa que el forecast fue optimista.

### Colores de precisión
Para Simple, MAPE, WAPE y WMAPE: verde desde el 90%, amarillo entre 70% y 89%, rojo por debajo del 70%.  
Para Sesgo: verde si la desviación absoluta es menor al 10%, amarillo entre 10% y 20%, rojo por encima del 20%.

---

## 12. Forecast — Rotación de inventario

**Promedio mensual entregado:** total de unidades entregadas en el período dividido por la cantidad de meses del período.

**Rotación en meses:** stock actual dividido por el promedio mensual entregado. Indica cuántos meses de ventas cubre el stock disponible.

**Rotación en días:** stock actual dividido por el promedio mensual entregado, multiplicado por 30.

El stock actual es la suma de las cantidades en ubicaciones internas (opcionalmente filtrado por almacén).

**Colores:**

| Unidad | Verde      | Amarillo       | Sin color  |
|--------|------------|----------------|------------|
| Días   | 90 o menos | Entre 91 y 180 | Más de 180 |
| Meses  | 3 o menos  | Entre 4 y 6    | Más de 6   |

---

## 13. Forecast — Cobertura por celda (mes × producto)

Para cada combinación de mes y producto, la cobertura es la cantidad de OFs planificadas dividida por el forecast de ese mes, multiplicado por 100.

**Colores de celda:**
- Verde: cobertura del 100% o más
- Amarillo: cobertura entre el umbral de aviso configurado (default 70%) y el 99%
- Rojo: cobertura por debajo del umbral de aviso

---

## 14. Análisis de proveedores

| Métrica                         | Cómo se calcula                                                                                                                                   |
|---------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| % A tiempo                      | Recepciones donde la fecha real de cierre fue igual o anterior a la fecha programada, dividido por el total de recepciones completadas, multiplicado por 100 |
| Retraso promedio (días)         | Promedio de la diferencia entre fecha real y fecha programada, contando solo las recepciones que llegaron tarde                                    |
| % Recepciones completas         | Recepciones cerradas como totalmente recibidas, dividido por el total de recepciones, multiplicado por 100                                        |
| Lead time promedio (días)       | Promedio de la diferencia entre la fecha de cierre de la recepción y la fecha de emisión de la OC                                                 |
| Variación de precio promedio (%) | Promedio de la diferencia porcentual en valor absoluto entre el precio real pagado y el precio estimado al momento de la OC                       |

### Colores de clasificación de proveedores (umbrales configurables en ajustes)

| Métrica          | Verde                                                         | Amarillo                                           | Rojo                          |
|------------------|---------------------------------------------------------------|----------------------------------------------------|-------------------------------|
| % A tiempo       | Mayor o igual al umbral verde (default 90%)                   | Mayor o igual al umbral amarillo (default 70%)     | Por debajo del umbral amarillo |
| Retraso promedio | Menor o igual al umbral verde (default 1 día)                 | Menor o igual al umbral amarillo (default 3 días)  | Por encima del umbral amarillo |
| % Completas      | Mayor o igual al umbral verde (default 95%)                   | Mayor o igual al umbral amarillo (default 80%)     | Por debajo del umbral amarillo |
| Variación precio | Menor o igual al umbral verde en valor absoluto (default 3%)  | Menor o igual al umbral amarillo (default 10%)     | Por encima del umbral amarillo |

---

## 15. Categorías de venta (A / B / C / D / E)

La asignación usa como fuente las entregas físicas completadas del período configurado. Existen tres modos:

### Modo Rotación de inventario
Se calcula el promedio mensual de unidades entregadas para el producto. Con ese dato, se estima cuántos días de stock quedan:

**Días de rotación** = stock actual ÷ promedio mensual entregado × 30

El producto se asigna a la categoría según los umbrales de días configurados: la categoría A tiene la rotación más rápida (menos días de stock) y la E la más lenta o sin movimiento.

### Modo Demanda
Se calcula el promedio mensual de unidades entregadas. El producto se asigna según los umbrales de cantidad por mes configurados: A tiene la mayor demanda y E la menor.

### Modo Participación acumulada (Pareto)
Se ordena a todos los productos de mayor a menor por su métrica (cantidad o cantidad × precio de lista). Se va acumulando la participación de cada producto sobre el total. El producto se asigna a la categoría correspondiente al rango de participación acumulada donde cae (A cubre el primer tramo del acumulado, B el siguiente, y así hasta E).

---

## 16. Reprogramación en cascada

### Duración de una OF
1. Si la OF tiene operaciones (work orders) con tiempo esperado cargado: se suman los minutos esperados de todas las operaciones y se convierten a horas.
2. Si no tiene operaciones con tiempo cargado, pero sí fechas de inicio y fin: se calcula la diferencia entre ambas en horas.
3. Si ninguna de las anteriores aplica: se asume una duración de 8 horas (valor de seguridad).

### Delta de reprogramación
Diferencia entre la nueva fecha de fin propuesta y la fecha de fin original de la OF. Se muestra como "+Xd Yh" (se adelanta) o "−Xd Yh" (se atrasa).

### Secuenciación de operaciones por centro de trabajo
Cada operación se programa a partir del momento en que el centro de trabajo queda libre (último fin registrado para ese CT, o la fecha base de la reprogramación si el CT aún no tiene asignaciones). La siguiente operación no puede empezar antes de que el CT esté disponible.

Si se especifica un ajuste de duración total para la OF, cada operación se escala proporcionalmente para que la suma de todas siga siendo la duración total ajustada.

---

## 17. Quiebres de stock

Un producto tiene quiebre de stock cuando su stock actual es menor que la cantidad mínima configurada en su punto de reorden.

El stock actual se mide en la ubicación configurada en ajustes (o en todas las ubicaciones internas si no se configuró una).

| KPI         | Qué cuenta                                                                         |
|-------------|------------------------------------------------------------------------------------|
| Total       | Todos los productos relevantes (con forecast o con punto de reorden)               |
| Con quiebre | Productos con punto de reorden donde el stock actual está por debajo del mínimo    |
| OK          | Productos con punto de reorden donde el stock está en o por encima del mínimo      |
| Sin mínimo  | Productos sin punto de reorden configurado                                         |
