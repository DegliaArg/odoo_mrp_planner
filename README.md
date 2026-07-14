# Planificador de producción

**Odoo 18 Enterprise · Fabricación · v18.0.1.0.0**  
Desarrollado por [Deglia](https://deglia.xyz)

Panel de control centralizado para la gestión operativa de producción: programación desde demanda, reprogramación en cascada, alertas proactivas, forecast de ventas, análisis de proveedores y monitoreo en tiempo real de órdenes de fabricación, compra y stock.

---

## Índice

- [Características principales](#características-principales)
- [Instalación](#instalación)
- [Configuración inicial](#configuración-inicial)
- [Panel del planificador](#panel-del-planificador)
  - [Alertas](#alertas)
  - [Órdenes de fabricación](#órdenes-de-fabricación)
  - [Carga de centros de trabajo](#carga-de-centros-de-trabajo)
  - [Órdenes de compra](#órdenes-de-compra)
  - [Quiebres de stock](#quiebres-de-stock)
  - [Forecast](#forecast)
  - [Análisis de proveedores](#análisis-de-proveedores)
  - [Gráfico de ventas](#gráfico-de-ventas)
  - [Análisis de clientes](#análisis-de-clientes)
- [Programación desde demanda](#programación-desde-demanda)
- [Reprogramación en cascada](#reprogramación-en-cascada)
- [Sistema de alertas](#sistema-de-alertas)
- [Permisos por usuario](#permisos-por-usuario)
- [Dependencias](#dependencias)
- [Licencia](#licencia)

---

## Características principales

| Pilar | Descripción |
|---|---|
| **Panel en tiempo real** | KPIs, widgets interactivos y drill-down para OFs, OCs, centros de trabajo y stock |
| **Alertas proactivas** | Detección automática de retrasos y vencimientos con severidad configurable |
| **Programación desde demanda** | Expansión de BOM, evaluación de stock y generación de OFs con un clic |
| **Reprogramación en cascada** | Recálculo de fechas respetando calendarios laborales y centros de trabajo |
| **Forecast** | Comparativo mensual entre plan de ventas, producción, entregas y stock con semáforo de cobertura |
| **Análisis de proveedores** | Scorecard de cumplimiento: % a tiempo, retraso promedio, lead time real y variación de precio |
| **Categorización de ventas** | Clasificación A–E de artículos por rotación, demanda o participación acumulada (Pareto) |
| **Análisis de clientes** | Clasificación A–E de clientes por volumen, frecuencia o RFM con drill-down a sus pedidos |
| **Permisos granulares** | Control por usuario de qué secciones ve y qué acciones puede ejecutar |

---

## Instalación

1. Copiar la carpeta `odoo_mrp_planner/` al directorio de addons del proyecto.
2. En Odoo: **Ajustes → Activar modo desarrollador**.
3. **Aplicaciones → Actualizar lista de aplicaciones**.
4. Buscar **Planificador de producción** e instalar.

**Requisitos:** Odoo 18 Enterprise con los módulos `mrp`, `mrp_workorder`, `purchase`, `stock`, `mail` y `sale` instalados.

---

## Configuración inicial

Acceder desde **Planificador → Configuración**.

### Pestaña General

| Campo | Descripción |
|---|---|
| Fallback de centro de trabajo | Qué hacer cuando una OF no tiene WC compatible: usar operaciones de la LdM o dejarla sin asignar |
| Criterio de prioridad | Orden de reprogramación: cronológico, más cortas primero (SPT) o manual |
| Frecuencia del cron | Cada cuántos minutos/horas se detectan alertas automáticamente |
| Heurística por centro de trabajo | Si está activo, incluye en la reprogramación OFs que comparten WC con el pivot (puede generar reprogramaciones masivas) |
| Pestaña de servicios en OCs | Separa OCs de tipo servicio en una pestaña propia dentro del widget |
| Ubicación de stock (quiebres) | Almacén interno desde el cual se lee el stock actual para el análisis de quiebres |

### Pestaña Alertas

Configura umbrales independientes para cada tipo de documento:

| Campo | Descripción |
|---|---|
| Días críticos OF | Días de retraso para que una OF pase de aviso a crítica |
| Días por vencer OF | Días de anticipación para generar alerta preventiva en OFs |
| Días críticos OC | Días de retraso para que una OC pase de aviso a crítica |
| Días por vencer OC | Días de anticipación para generar alerta preventiva en OCs |
| Días críticos recepción | Días de retraso para que una recepción pase de aviso a crítica |
| Tolerancia de cantidad | Diferencia porcentual máxima entre cantidad planificada y producida antes de alertar |

### Pestaña Forecast

| Campo | Descripción |
|---|---|
| Meses por defecto | Horizonte de meses que muestra el widget al abrirse |
| Cobertura mínima (aviso %) | Por debajo de este % la celda de cobertura se muestra en amarillo |
| Cobertura mínima (crítico %) | Por debajo de este % la celda de cobertura se muestra en rojo |
| Estados de OF incluidos | Qué estados de OFs se suman como producción planificada (borrador, confirmada, en progreso, etc.) |
| Unidad de rotación | Si el indicador de rotación de inventario se expresa en días o en meses |
| Fórmula de precisión | Método para calcular el % de precisión del forecast: Simple, MAPE, WAPE, WMAPE o Sesgo |
| Actualización automática | Si está activo, recalcula las categorías de venta automáticamente según el cron configurado |

### Pestaña Categoría de venta

Define cómo se clasifican los artículos en categorías A–E:

| Modo | Criterio |
|---|---|
| Manual | El usuario asigna la categoría desde la ficha del artículo |
| Automático por rotación | Días de stock ÷ promedio de ventas. Umbrales A/B/C/D configurables en días |
| Automático por demanda | Unidades vendidas promedio por mes. Umbrales A/B/C/D configurables en qty |
| Automático por participación | Ordena artículos por métrica (unidades o importe) y clasifica por % acumulado del total (Pareto A/B/C/D/E) |

### Pestaña Permisos por usuario

Define qué secciones puede ver cada usuario y qué acciones puede ejecutar. Ver [Permisos por usuario](#permisos-por-usuario).

### Pestaña Análisis de proveedores

| Campo | Descripción |
|---|---|
| % A tiempo — verde | Umbral mínimo de recepciones a tiempo para mostrar el indicador en verde |
| % A tiempo — amarillo | Umbral mínimo para mostrar el indicador en amarillo (por debajo → rojo) |
| Retraso — verde | Retraso promedio máximo (días) para semáforo verde |
| Retraso — amarillo | Retraso promedio máximo para semáforo amarillo |
| % Completas — verde | Umbral de recepciones completas (sin backorder) para semáforo verde |
| % Completas — amarillo | Umbral para semáforo amarillo |
| Var. precio — verde | Variación de precio máxima (%) para semáforo verde |
| Var. precio — amarillo | Variación de precio máxima para semáforo amarillo |

---

## Panel del planificador

Acceder desde **Planificador → Panel**.

El panel centraliza en una sola vista toda la información operativa de producción. Cada sección es un widget independiente con filtros, paginación y acceso directo a los registros de Odoo.

### Alertas

Resumen de alertas activas agrupadas por tipo. Desde cada tarjeta se accede directamente a la lista filtrada de alertas.

| Tarjeta | Contenido |
|---|---|
| Total | Todas las alertas sin resolver |
| Críticas | Alertas con severidad crítica |
| OFs atrasadas | OFs con fecha de fin vencida |
| OFs por vencer | OFs que vencen dentro de la ventana configurada |
| OCs vencidas | OCs con fecha de entrega vencida |
| OCs por vencer | OCs que vencen dentro de la ventana configurada |
| Recepciones | Recepciones de stock con fecha programada vencida |
| Cant. diferentes | OFs cerradas con desvío de cantidad superior a la tolerancia |

### Órdenes de fabricación

Widget con tres pestañas:

**OFs activas**
- KPIs: total activas, en progreso, atrasadas, para reprogramar, finalizadas, por cerrar
- Tabla paginada con filtros por fecha, sector (tag de WC) y columna de días de retraso
- Ordenamiento por cualquier columna, server-side

**Programaciones**
- Lista de solicitudes de programación activas con estado y OFs generadas
- KPIs: activas, calculadas, con reprogramación, OFs atrasadas

**Comparativo**
- Producción planificada vs. real por producto en el período seleccionado
- Porcentaje de cumplimiento con semáforo visual

### Carga de centros de trabajo

Gráfico de barras apiladas con la carga del período seleccionado:

- **Planificado** (azul) y **No planificado** (gris): horas disponibles por WC
- **Ejecutado** (verde) y **Pendiente** (amarillo): horas reales vs. programadas
- **Tiempo libre** (rojo suave): capacidad no utilizada

Al hacer clic en una barra del gráfico, se filtra la vista al centro de trabajo seleccionado. KPIs: disponible, planificado, carga %, ejecutado, pendiente, tiempo libre.

### Órdenes de compra

Widget con filtros por fecha, tipo (todas / compras / subcontratación) y estado OC. Incluye cuatro sub-pestañas:

**OCs**
- Lista de órdenes según el filtro de estado: Vencidas, Todas, A tiempo, Cotizaciones, Por aprobar
- KPIs: cotizaciones, por aprobar, aprobadas, a tiempo, vencidas, críticas (con umbral dinámico desde config)

**Recepciones**
- Recepciones pendientes vinculadas a OCs, con días de retraso y estado de disponibilidad
- Filas expandibles para ver líneas de movimiento con cantidad pedida y cantidad recibida por producto
- Columna Disponibilidad: Lista / Parcial / Sin iniciar

**Entregas**
- Envíos de componentes a subcontratistas con disponibilidad de stock
- Filas expandibles para ver líneas con cantidad demandada y cantidad reservada
- Columna Disponibilidad: Disponible / Parcialmente / No disponible

**Servicios** *(opcional)*
- OCs cuyos productos son todos de tipo servicio, separadas si está habilitado en configuración

### Quiebres de stock

Tabla de productos con stock actual por debajo del mínimo configurado:

- **Filtros**: por nombre o código interno del producto, por tipo (quiebres / de acuerdo / sin mínimo)
- **Selector de ubicación**: cambia el depósito analizado sin afectar la configuración global
- Paginado a 20 registros por página

| Columna | Descripción |
|---|---|
| Producto | Nombre y código interno |
| Stock actual | Unidades disponibles en la ubicación seleccionada |
| Mínimo | Punto de reorden configurado (ruta Fabricación) |
| Diferencia | Stock actual − mínimo (negativo = quiebre) |

### Forecast

Tabla mensual que compara plan de ventas, producción programada, entregas reales y stock disponible por producto.

- **Filtros**: período desde/hasta, depósito, búsqueda por producto
- **Columnas configurables**: forecast, OFs planificadas, entregado, stock, rotación, cobertura, precisión
- **Agrupación**: por categoría de venta (A–E), por categoría de producto o sin agrupar
- **Semáforo de cobertura**: verde / amarillo / rojo según los umbrales configurados
- **Exportación**: descarga la tabla actual a Excel
- **Edición de forecast**: los valores de forecast son editables directamente en la celda (requiere permiso)

| Columna | Descripción |
|---|---|
| Forecast | Cantidad planificada de ventas para el mes |
| OFs planificadas | Producción programada en OFs confirmadas/en progreso |
| Entregado | Cantidad real despachada en movimientos de salida |
| Stock | Stock disponible al cierre del período |
| Rotación | Stock ÷ ventas promedio (en días o meses según config) |
| Cobertura % | Entregado ÷ Forecast × 100 (o fórmula avanzada configurada) |
| Precisión % | Exactitud del forecast respecto a lo entregado |

### Análisis de proveedores

Scorecard de rendimiento de proveedores con columnas redimensionables y reordenables.

- **Filtros**: período desde/hasta, búsqueda por nombre de proveedor
- **Ordenamiento**: por cualquier columna, ascendente/descendente
- **Drill-down**: expandir un proveedor muestra sus OCs del período con estado de recepción

| Columna | Descripción |
|---|---|
| Proveedor | Nombre del proveedor |
| OCs | Cantidad de OCs confirmadas en el período |
| Artículos | Productos distintos comprados |
| Monto | Suma del importe total de OCs confirmadas |
| % A tiempo | Porcentaje de recepciones completadas en la fecha acordada |
| Retraso (d) | Promedio de días de retraso en recepciones tardías |
| % Completas | Porcentaje de recepciones completadas sin backorder |
| Lead time (d) | Lead time real promedio: días entre aprobación y recepción |
| Var. precio | Variación promedio de precio OC vs. costo estándar del producto |
| Fact. pend. | Total de facturas de proveedor pendientes de pago |

Los indicadores de cumplimiento muestran semáforo verde / amarillo / rojo según los umbrales configurados en la pestaña Análisis de proveedores de Configuración.

### Gráfico de ventas

Gráfico de barras de ventas por producto con clasificación por categoría (A–E).

- **Período**: últimos 30 días, 3 meses, 6 meses, 12 meses o año en curso
- **Métrica**: unidades o importe
- **Top N**: muestra los N productos más vendidos (configurable)
- **Filtros**: por categoría de venta (A–E) y por categoría de producto
- Las barras se colorean según la categoría de venta: A (verde), B (azul), C (amarillo), D (gris), E (gris claro)

### Análisis de clientes

Clasificación A–E de clientes con drill-down a sus pedidos de venta del período.

- **Filtros**: período desde/hasta, búsqueda por nombre de cliente
- **Método de clasificación**: Pareto por volumen o importe, frecuencia de compra, o RFM (Recencia, Frecuencia, Monetario)
- **Ordenamiento**: por cualquier columna, ascendente/descendente
- **Drill-down**: expandir un cliente muestra sus pedidos de venta del período con importe y estado

| Columna | Descripción |
|---|---|
| Cliente | Nombre del cliente |
| Categoría | Clasificación A–E calculada automáticamente |
| OVs | Cantidad de pedidos de venta en el período |
| Artículos | Productos distintos comprados |
| Monto | Importe total de pedidos confirmados |
| Última compra | Días desde el último pedido de venta |
| Puntaje RFM | Puntos de Recencia + Frecuencia + Monetario (solo en modo RFM) |

Los umbrales de Pareto y los criterios de RFM se configuran en la pestaña Análisis de proveedores de Configuración (aplican también a clientes).

---

## Programación desde demanda

Acceder desde **Planificador → Nueva programación** o desde el botón en el panel.

El asistente de programación recibe una lista de productos a fabricar y genera el plan completo:

1. **Expansión de BOM**: desglosa cada producto por su lista de materiales, respetando variantes y factores de cantidad.
2. **Evaluación de stock**: compara demanda vs. disponible. Detecta nodos con stock suficiente (verde), parcial (amarillo) o sin stock (rojo).
3. **Evaluación de rutas**: clasifica cada componente como Fabricar, Comprar, Subcontratar o tomar de Stock.
4. **Detección de reabastecimiento automático**: identifica ítems con reglas min/max activas.
5. **Scheduling bottom-up**: calcula fechas de inicio y fin respetando el calendario laboral y los centros de trabajo compatibles por producto.
6. **Generación de OFs**: crea las órdenes madre y las hijas de forma recursiva, planificando órdenes de trabajo al confirmar.

### Estados de la solicitud

| Estado | Significado |
|---|---|
| Borrador | En edición, sin OFs generadas |
| Calculada | Plan calculado, listo para confirmar |
| Confirmada | OFs creadas en Odoo |

---

## Reprogramación en cascada

Acceder desde **Planificador → Reprogramar OF**, desde una alerta, o desde el menú Acción en la lista de OFs.

Cuando una OF termina antes o después de lo planificado, el plan de reprogramación recalcula todas las OFs subsecuentes afectadas:

1. Seleccionar la OF "pivot" (la que cambió de fecha).
2. Indicar la nueva fecha de fin.
3. **Calcular**: el sistema busca todas las OFs y OCs dependientes en el mismo centro de trabajo, aplica el desplazamiento respetando el calendario laboral.
4. **Revisar** la tabla de cambios propuestos — se pueden editar fechas individuales y excluir filas.
5. **Aplicar**: las fechas se escriben en Odoo y las órdenes de trabajo se replanifican.

### Tabla de cambios

| Color | Significado |
|---|---|
| Azul | OF directamente subsecuente en el mismo WC |
| Naranja | OF hija o descendiente (nivel 1+) |
| Gris | Orden de compra vinculada |
| Amarillo | Advertencia: OC confirmada o hijo ajustado fuera del margen |

### Criterios de prioridad (configurables)

| Criterio | Comportamiento |
|---|---|
| Cronológico | Respeta el orden de fecha de inicio actual |
| Más cortas primero (SPT) | Prioriza OFs de menor duración para maximizar throughput |
| Manual | El usuario arrastra el orden en el asistente |

---

## Sistema de alertas

El cron se ejecuta automáticamente con la frecuencia configurada y detecta:

| Tipo de alerta | Condición |
|---|---|
| OF atrasada | OF en estado activo con fecha de fin pasada |
| OF por vencer | OF activa que vence dentro de los próximos N días (configurable) |
| OC vencida | OC aprobada con fecha de entrega pasada y recepción pendiente |
| OC por vencer | OC activa que vence dentro de los próximos N días (configurable) |
| OC cancelada | OC que pasó a estado cancelado |
| Recepción atrasada | Picking entrante con fecha programada pasada |
| Cantidad diferente | OF cerrada con producción real que difiere de la planificada más de la tolerancia |
| OF cancelada | OF que pasó a estado cancelado |

### Severidad

- **Aviso** (amarillo): el retraso existe pero no supera el umbral crítico
- **Crítico** (rojo): el retraso supera el umbral configurado para ese tipo de documento

Las alertas se resuelven automáticamente cuando el registro vuelve a estado normal (OF cerrada, OC recibida, etc.). También se pueden resolver manualmente o generar un plan de reprogramación desde la propia alerta.

---

## Permisos por usuario

En **Planificador → Configuración → Permisos por usuario** se define, para cada usuario interno, qué puede ver y hacer:

| Permiso | Descripción |
|---|---|
| Alertas | Ver la sección de alertas en el panel |
| OFs | Ver el widget de órdenes de fabricación |
| OCs | Ver el widget de órdenes de compra |
| Quiebres | Ver el widget de quiebres de stock |
| Forecast | Ver el widget de forecast |
| Programar | Crear nuevas solicitudes de programación |
| Reprogramar | Crear planes de reprogramación |
| Editar forecast | Modificar los valores de forecast directamente en la tabla |
| Depósitos | Filtrar todos los datos a los depósitos asignados |

Los usuarios sin registro en esta tabla tienen **acceso completo** a todas las secciones por defecto.

---

## Dependencias

| Módulo | Uso |
|---|---|
| `mrp` | Órdenes de fabricación, listas de materiales, órdenes de trabajo |
| `mrp_workorder` | Planificación de órdenes de trabajo en centros de trabajo |
| `purchase` | Órdenes de compra, recepciones, subcontratación |
| `stock` | Ubicaciones, pickings, stock disponible |
| `mail` | Chatter y notificaciones en planes y alertas |
| `sale` | Pedidos de venta, análisis de forecast y categorización de artículos |

---

## Soporte

**Deglia**  
administracion@deglia.xyz  
https://deglia.xyz

---

## Licencia

[Odoo Proprietary License v1.0 (OPL-1)](LICENSE)  
Copyright © 2026 Deglia
