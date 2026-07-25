# Planificador de producción

**Odoo 18 Enterprise · Fabricación · v18.0.3.0.0**  
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
- [Permisos](#permisos)
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

**Requisitos:** Odoo 18 Enterprise con los módulos `mrp`, `mrp_subcontracting`, `purchase`, `stock`, `mail` y `sale` instalados.

---

## Configuración inicial

Acceder desde **Planificador → Configuración**. La configuración es un registro único por empresa, organizado en cinco pestañas. Cada pestaña es visible solo para el grupo de seguridad correspondiente (ver [Permisos](#permisos)).

### Pestaña General *(Administrador)*

Frecuencia del cron de detección de alertas, activación global de las funciones de **programación y reprogramación** (al desactivar se ocultan menús, botones y KPIs asociados) y acceso a las **preferencias por usuario** (depósitos visibles y secciones del panel).

### Pestaña Producción

Umbrales de alertas de OFs (días críticos, días por vencer, tolerancia de cantidad) y ajustes de producción:

- **Quiebres de stock**: ubicación desde la que se mide el stock y columna de rotación opcional (método, meses de historial y alertas por color).
- **Estados de OF incluidos** como "Programado" en la comparativa y el forecast (borrador / confirmada / en progreso / por cerrar / terminada).
- **Criterio de fechas de la comparativa** Producido vs. Programado: por fecha de cierre, por fecha de inicio, por solapamiento o proporcional por duración.

### Pestaña Programación *(visible solo con programación activa)*

Fallback de centro de trabajo (usar operaciones de la LdM o dejar sin asignar), criterio de prioridad de reprogramación (cronológico / SPT / manual) y heurística por centro de trabajo (puede generar reprogramaciones masivas).

### Pestaña Compras

- Umbrales de alertas de OCs y recepciones (días críticos y por vencer).
- Panel de compras: pestaña de servicios separada, exclusión de OCs de solo servicios en KPIs y campo de fecha del análisis de proveedores.
- **Referencia para variación de precio**: costo estándar, lista de precio del proveedor o precio anterior pagado (default). Se usa tanto en la columna del análisis de proveedores como en la clasificación ABC por variación de precio.
- Umbrales de semáforo del análisis de proveedores (% a tiempo, retraso, % completas, variación de precio).
- **Categorías de proveedor A–E**: método (manual, Pareto por importe o cantidad de OCs, RFM, % entrega a tiempo, variación de precio, calidad), período de análisis, umbrales Pareto, parámetros RFM y cron de actualización automática.

### Pestaña Ventas

- **Categorías de venta A–E** de artículos: manual, por rotación de inventario (stock promedio del período ÷ promedio mensual de entregas o demanda, configurable), por volumen de demanda o por participación acumulada (Pareto), con umbrales y cron propios.
- **Categorías de cliente A–E**: manual, Pareto por importe o cantidad de pedidos, o RFM (parámetros RFM compartidos con proveedores).
- **Análisis de clientes**: método de entrega a tiempo (fecha pactada, fecha del picking o SLA en días), umbrales del ranking ABC del período, semáforos de % Cumplim. / % Físico y % A tiempo, y días para clasificar un cliente "en riesgo".
- **Forecast**: umbrales de cobertura (aviso/crítico), método y unidad de rotación (unidades / COGS / ventas), cobertura de inventario (fuente de demanda y alertas), cobertura de OFs (denominador: forecast o demanda OV) y fuente/fórmula de precisión (Simple, MAPE, WAPE, WMAPE, Sesgo).

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
- Un badge indica el criterio de fechas activo (fecha de cierre, fecha de inicio, solapamiento o proporcional; configurable en Ajustes → Producción)
- Porcentaje de cumplimiento con semáforo visual; cuando hubo producción sin nada programado se muestra el estado **"s/plan"** (producido sin plan) en lugar de 0%

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
| Rotación *(opcional)* | Rotación de inventario según el método y los meses de historial configurados; con alertas de color amarillo/rojo por umbrales de días (configurable en Ajustes → Producción) |

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
| Rotación | Stock promedio del período ÷ promedio mensual (en días o meses según config; método por unidades, COGS o ventas) |
| Cobertura % | OFs planificadas ÷ Forecast (o demanda OV, configurable) × 100 |
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
| Var. precio | Variación promedio de precio OC vs. la referencia configurada: costo estándar, lista de precio del proveedor o precio anterior pagado (default). Ver "Referencia para variación de precio" en Ajustes → Compras |
| Fact. pend. | Total de facturas de proveedor pendientes de pago |

Los indicadores de cumplimiento muestran semáforo verde / amarillo / rojo según los umbrales configurados en la pestaña Compras de Configuración.

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
| ABC período | Clasificación A/B/C calculada **al vuelo** por participación en el monto del período visible (no altera la categoría permanente del contacto) |
| OVs | Cantidad de pedidos de venta en el período |
| Artículos | Productos distintos comprados |
| Monto | Importe total de pedidos confirmados |
| % Cumplim. | Entregado de los pedidos del período ÷ pedido × 100 |
| % Físico | Despachado dentro del período (de cualquier pedido) ÷ pedido × 100 — puede superar 100% |
| Última compra | Días desde el último pedido de venta |
| Puntaje RFM | Puntos de Recencia + Frecuencia + Monetario (solo en modo RFM) |

Los umbrales de Pareto se configuran en las pestañas Compras y Ventas de Configuración; los criterios de RFM son configurables en **Ajustes → Parámetros RFM** (compartidos entre clientes y proveedores).

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

## Permisos

El control de acceso combina tres niveles:

### 1. Grupos de seguridad

Ocho grupos definidos en la categoría **Planificador MRP** (`security/groups.xml`), asignables desde la ficha del usuario:

| Grupo | Alcance |
|---|---|
| Producción - Lectura | Ve el panel de producción, alertas de OFs, quiebres de stock y carga de centros de trabajo |
| Producción - Administrador | Lo anterior + configuración de alertas y quiebres (pestaña Producción) |
| Compras - Lectura | Ve el panel de compras: alertas de OCs y recepciones, órdenes de compra y análisis de proveedores |
| Compras - Administrador | Lo anterior + configuración de compras, análisis y categorías de proveedor |
| Ventas - Lectura | Ve el panel de ventas, el forecast y el análisis de clientes, sin editar ni importar datos |
| Ventas - Administrador | Lo anterior + edición e importación de forecast y configuración de ventas |
| Programación | Habilita programación y reprogramación (menús, botones en OFs, KPIs) y su configuración |
| Administrador | Acceso completo: implica todos los grupos anteriores |

Los grupos controlan menús, pestañas de configuración y botones, y además se verifican **en el servidor** en los métodos RPC del dashboard.

### 2. Visibilidad de secciones por usuario

En la ficha del usuario (pestaña del planificador) — o desde **Configuración → General → "Gestionar preferencias por usuario"** — se puede ocultar individualmente cada sección de los paneles: alertas de producción, OFs, centros de trabajo, quiebres, alertas de compras, OCs, análisis de proveedores, gráfico de ventas, forecast y análisis de clientes.

### 3. Restricción por depósitos

Cada usuario puede limitarse a un conjunto de depósitos: todos los datos del panel (OFs, OCs, alertas, stock) se filtran automáticamente a los depósitos asignados. Por defecto el usuario ve todos los depósitos.

---

## Dependencias

| Módulo | Uso |
|---|---|
| `mrp` | Órdenes de fabricación, listas de materiales, órdenes de trabajo |
| `mrp_subcontracting` | Subcontratación: envíos de componentes y recepciones de subcontratistas |
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
