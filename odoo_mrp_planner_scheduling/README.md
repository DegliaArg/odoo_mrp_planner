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

## Despliegue (IMPORTANTE)

Cuando un deploy incluye **campos, modelos o vistas nuevos**, hay que
**UPGRADEAR el módulo** (`-u odoo_mrp_planner_scheduling`), no solo reiniciar el
servidor. Un simple reinicio deja el **código nuevo con el schema viejo** →
errores tipo `column "..." does not exist` al calcular/guardar.

- En Odoo.sh, verificar que el build de la rama corra el upgrade del módulo (no
  un mero restart). Si ya reinició sin upgradear, forzarlo desde
  **Aplicaciones → Actualizar**, o vía RPC
  `ir.module.module.button_immediate_upgrade`.
- Cambios solo de Python/JS/QWeb (sin campos/vistas nuevos) sí andan con
  reinicio.

Ya nos pasó (sesión 2026-09-02: el campo `used_alternative` no existía tras el
redeploy). Verificar SIEMPRE que el módulo quedó upgradeado cuando el commit
agrega `fields.*` o vistas.

## Autor

[Deglia](https://deglia.xyz) · Licencia OPL-1
