# Planificación — Módulo de programación para Odoo 18

Extensión de programación del módulo KPIs de Deglia. Agrega un app independiente con dos circuitos: planificación desde demanda y reprogramación en cascada.

## Funcionalidades

### Planificación desde demanda
- Expansión automática de BOM con rutas, lead times y stock disponible.
- Detección de faltantes y reabastecimiento automático (min/max).
- Creación de OFs desde una solicitud de programación.

### Reprogramación en cascada
- Recalcula fechas de OFs encadenadas respetando el calendario laboral.
- Soporte multi-WC con prioridad configurable: cronológico, SPT o manual.
- Planes persistentes con historial, Gantt y auditoría completa.
- Creación de planes desde las alertas del módulo KPIs.

## Activación

La instalación **no habilita** las funciones automáticamente. Se activan desde:

**Planificación → Configuración**

Desde ahí también se controla qué usuarios ven los botones y KPIs asociados.

## Instalación

Requiere: `odoo_mrp_planner`.

## Autor

[Deglia](https://deglia.xyz) · Licencia OPL-1
