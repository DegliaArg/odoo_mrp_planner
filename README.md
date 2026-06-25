# Planificador de producción

**Odoo 18 Enterprise · Fabricación**  
Desarrollado por [Deglia](https://deglia.xyz)

Panel de control centralizado para la gestión operativa de producción: programación desde demanda, reprogramación en cascada, alertas proactivas y monitoreo en tiempo real de órdenes de fabricación, compra y stock.

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
| **Permisos granulares** | Control por usuario de qué secciones ve y qué acciones puede ejecutar |

---

## Instalación

1. Copiar la carpeta `odoo_mrp_reschedule/` al directorio de addons del proyecto.
2. En Odoo: **Ajustes → Activar modo desarrollador**.
3. **Aplicaciones → Actualizar lista de aplicaciones**.
4. Buscar **Planificador de producción** e instalar.

**Requisitos:** Odoo 18 Enterprise con los módulos `mrp`, `mrp_workorder`, `purchase` y `stock` instalados.

---

## Configuración inicial

Acceder desde **Planificador → Configuración**.

### Pestaña General

| Campo | Descripción |
|---|---|
| Fallback de centro de trabajo | Qué hacer cuando una OF no tiene WC compatible: usar operaciones de la LdM o dejarla sin asignar |
| Criterio de prioridad | Orden de reprogramación: cronológico, más cortas primero (SPT) o manual |
| Frecuencia del cron | Cada cuántos minutos/horas se detectan alertas automáticamente |

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

### Pestaña Panel

| Campo | Descripción |
|---|---|
| Pestaña de servicios en OCs | Separa OCs de tipo servicio en una pestaña propia dentro del widget |
| Ubicación de stock (quiebres) | Almacén interno desde el cual se lee el stock actual para el análisis de quiebres |

### Pestaña Permisos por usuario

Define qué secciones puede ver cada usuario y qué acciones puede ejecutar. Ver [Permisos por usuario](#permisos-por-usuario).

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
| CTs | Ver el gráfico de carga de centros de trabajo |
| OCs | Ver el widget de órdenes de compra |
| Quiebres | Ver el widget de quiebres de stock |
| Programar | Crear nuevas solicitudes de programación |
| Reprogramar | Crear planes de reprogramación |
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

---

## Soporte

**Deglia**  
administracion@deglia.xyz  
https://deglia.xyz

---

## Licencia

[Odoo Proprietary License v1.0 (OPL-1)](LICENSE)  
Copyright © 2026 Deglia
