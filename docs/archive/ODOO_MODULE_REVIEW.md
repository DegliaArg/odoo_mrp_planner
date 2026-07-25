> ⚠️ DOCUMENTO HISTÓRICO — snapshot de una revisión pasada; NO refleja el estado actual del código. Conservado solo como referencia.

# ODOO_MODULE_REVIEW.md
# Checklist de revisión completa — Módulos Odoo 18

Instrucciones para Claude Code: ejecutá esta revisión completa sobre cualquier módulo
Odoo 18. Leé el CLAUDE.md del módulo antes de empezar. Ejecutá cada fase en orden.
No saltees secciones. Al finalizar creá o actualizá REVIEW.md con los resultados.

---

## FASE 1 — INVENTARIO INICIAL

Antes de cualquier análisis:

```bash
find . -type f \( -name "*.py" -o -name "*.xml" -o -name "*.js" -o -name "*.csv" -o -name "*.scss" \) \
  | grep -v __pycache__ | grep -v node_modules | sort
```

Para cada archivo listado:
- Una línea describiendo qué hace
- Confirmar si su descripción en CLAUDE.md es correcta o está desactualizada
- Marcar archivos que no aparecen en el manifest (candidatos a estar huérfanos)

---

## FASE 2 — SEGURIDAD

### 2.1 Acceso ORM (`security/ir.model.access.csv`)

- [ ] Cada modelo en `models/` tiene su línea de acceso
- [ ] Cada modelo en `wizard/` tiene su línea de acceso
- [ ] Ningún modelo con datos sensibles tiene CRUD completo para `base.group_user`
- [ ] Los modelos de configuración global (singletons) solo son editables por managers
- [ ] Los modelos de permisos de usuario solo son gestionables por managers
  - **Patrón correcto**: dos líneas por modelo — read para `group_user`, CRUD para el grupo manager

### 2.2 Uso de `sudo()`

Para cada `sudo()` encontrado:
```bash
grep -rn "sudo()" models/ wizard/
```
- [ ] Cada uso tiene un comentario `# sudo: razón justificada`
- [ ] No hay `sudo()` en métodos accesibles desde la UI sin validación previa
- [ ] No hay `sudo()` dentro de loops (riesgo de escalada masiva)

### 2.3 Métodos destructivos

```bash
grep -rn "button_apply\|button_confirm\|action_validate\|unlink\|write" models/ | grep "def "
```
- [ ] Cada método que escribe/borra muchos registros valida el grupo del usuario
  - Patrón: `if not self.env.user.has_group('modulo.group_manager'): raise UserError(...)`
- [ ] Los métodos de cron ejecutables manualmente están protegidos con check de grupo
- [ ] Las acciones en masa muestran confirmación antes de ejecutar

### 2.4 Inputs y datos externos

```bash
grep -rn "browse([0-9]\|\.search(\[\|ir\.config_parameter\|int(param" models/ wizard/
```
- [ ] No hay IDs de base de datos hardcodeados (ej: `browse(518)`)
  - **Patrón correcto**: `search([('code','=','mrp_operation'), ('company_id','=',...)], limit=1)`
- [ ] Los parámetros de sistema (`ir.config_parameter`) tienen try/except con fallback
- [ ] Los domains dinámicos construidos con input del usuario están sanitizados
- [ ] No hay SQL raw sin parámetros preparados

### 2.5 Singletons

```bash
grep -rn "_rec_name\|get_singleton\|ensure_singleton" models/
```
- [ ] Cada modelo singleton tiene `create()` sobreescrito que lanza `UserError` si ya existe un registro
  - Patrón:
    ```python
    @api.model
    def create(self, vals):
        if self.search_count([]) > 0:
            raise UserError(_("Ya existe una configuración. Editá el registro existente."))
        return super().create(vals)
    ```

### 2.6 Record rules

- [ ] Los modelos con datos por empresa tienen `company_id` en sus record rules
- [ ] Los modelos con datos por usuario/almacén tienen reglas que restringen visibilidad
- [ ] No hay reglas demasiado permisivas que expongan datos entre empresas

---

## FASE 3 — ESTRUCTURA DE ARCHIVOS

### 3.1 Manifest (`__manifest__.py`)

```bash
# Verificar archivos XML declarados vs existentes
diff <(grep -o "'[^']*\.xml'" __manifest__.py | tr -d "'" | sort) \
     <(find views/ data/ security/ -name "*.xml" | sed 's|^\./||' | sort)
```
- [ ] Todos los `.xml` en `views/`, `data/`, `security/` están declarados
- [ ] Todos los `.py` en `models/` están importados en `models/__init__.py`
- [ ] Los archivos de `data/` están en orden correcto (dependencias primero: groups → cron → data)
- [ ] Los assets JS/CSS están declarados bajo la clave correcta (`web.assets_backend`)
- [ ] La versión sigue el formato `18.0.X.Y.Z`
- [ ] Las dependencias en `depends` son las mínimas necesarias (sin dependencias fantasma)

### 3.2 Organización de modelos

- [ ] Un modelo principal por archivo Python
- [ ] Nombre del archivo refleja el `_name` del modelo (ej: `mrp_reschedule_plan.py` → `mrp.reschedule.plan`)
- [ ] Los wizards están en `wizard/`, no en `models/`
- [ ] Los mixins tienen sufijo `_mixin.py` y su `_name` incluye `mixin`
- [ ] No hay lógica de negocio en archivos de vistas XML (todo en Python)

### 3.3 Orden dentro de archivos Python

Cada archivo de modelo debe seguir este orden:
```
1. imports stdlib
2. imports odoo
3. _logger = logging.getLogger(__name__)
4. constantes de módulo (MAYÚSCULAS)
5. class Model(models.Model):
   a. _name, _description, _inherit, _order
   b. _sql_constraints
   c. campos (agrupados: básicos → relacionales → compute → técnicos)
   d. @api.depends / @api.constrains / @api.onchange
   e. métodos CRUD sobreescritos (create, write, unlink)
   f. métodos de negocio (privados _método primero, públicos después)
   g. métodos de acción (button_*, action_*)
   h. métodos @api.model
```
- [ ] Cada archivo sigue este orden o documenta por qué se desvía

---

## FASE 4 — CÓDIGO OBSOLETO Y DUPLICADO

### 4.1 Código muerto

```bash
# prints olvidados
grep -rn "print(" models/ wizard/ static/src/js/

# logger de debug de desarrollo
grep -rn "_logger\.debug\|_logger\.info" models/ wizard/

# imports no usados (revisar manualmente los que liste)
python3 -m py_compile models/*.py 2>&1 | grep "imported but unused"
```
- [ ] No hay `print()` en código Python
- [ ] Los `_logger.debug` son intencionales y necesarios en producción
- [ ] No hay imports no usados
- [ ] No hay métodos definidos y nunca llamados (`grep -rn "def _" models/ | cut -d: -f3 | sed 's/def //' | sed 's/(.*//'` vs usados)
- [ ] No hay campos definidos pero no usados en vistas ni lógica

### 4.2 Código comentado

```bash
grep -rn "^#.*=\|^#.*def \|^#.*class " models/ wizard/
```
- [ ] No hay bloques de código comentado (`# old_method`, `# TODO: remove`)
- [ ] Los `# TODO` tienen fecha y responsable, o se eliminan si están resueltos

### 4.3 Lógica duplicada

- [ ] Lógica repetida en más de 2 archivos está en un mixin o método utilitario
- [ ] No hay cálculos de fechas/scheduling duplicados fuera del mixin
- [ ] No hay construcción de dominios duplicada (centralizar en método `_build_domain_X()`)

### 4.4 Magic numbers y strings

```bash
grep -rn "[^a-zA-Z_][0-9]\{2,\}[^0-9]" models/ | grep -v "18\.0\|\.xml\|_id\|size\|limit\|#"
```
- [ ] Constantes numéricas repetidas están definidas como constante de módulo con comentario
  - Patrón: `MAX_DEPTH = 30  # Límite de recursión en árbol de sub-ÓFs (evita RecursionError)`
- [ ] No hay strings de estado hardcodeados fuera de la definición del campo `selection`

---

## FASE 5 — OPTIMIZACIÓN PYTHON

### 5.1 Queries N+1

```bash
grep -n "\.search\|\.browse\|\.read\|search_count" models/*.py
```
Revisar manualmente cada búsqueda dentro de un loop (`for record in recordset:`):
- [ ] No hay `search()` dentro de loops → usar `read_group()` o `filtered()`
- [ ] No hay `search_count()` dentro de loops → un solo `read_group` con `['__count']`
- [ ] No hay `record.field_id.other_field` en loops sobre recordsets grandes → usar `mapped()`
- [ ] Los hooks `write()` en modelos base (purchase.order, stock.picking) filtran `vals` antes de ejecutar
  - Patrón: `if not any(f in vals for f in ['date_planned', 'state']): return result`

### 5.2 Uso correcto de la ORM

- [ ] `search()` + `len()` → reemplazar con `search_count()`
- [ ] `search()` cuando solo se necesitan IDs → usar `search().ids` o `_search()`
- [ ] `browse()` con ID conocido en lugar de `search([('id','=',id)])`
- [ ] `read_group()` para conteos y agregaciones en lugar de `search()` + Python
- [ ] `ensure_one()` al inicio de métodos que asumen un solo registro
- [ ] `mapped('field')` en lugar de list comprehension `[r.field for r in records]`
- [ ] `filtered(lambda r: r.state == 'done')` en lugar de loop + append

### 5.3 Campos compute

```bash
grep -n "compute=" models/*.py
```
- [ ] Campos compute con `store=False` NO usados en `domain=`, `order=`, `group_by=` en XML
- [ ] Campos compute con `store=True` tienen `@api.depends` con todas las dependencias reales
- [ ] Los `@api.depends` no tienen dependencias innecesarias (recalculos innecesarios)
- [ ] Los campos compute pesados tienen `store=True` si se usan en listas con muchos registros

### 5.4 Crons y procesos masivos

```bash
grep -rn "_cron_\|ir\.cron" models/
```
- [ ] Cada cron tiene límite de registros (`limit=N`) o procesa por lotes
- [ ] Los dominios de búsqueda en crons son restrictivos (no `[(1,'=',1)]`)
- [ ] Los crons usan `with_context(prefetch_fields=False)` si solo leen pocos campos
- [ ] Hay `_logger.info` al inicio y fin del cron con métricas (N registros procesados)

### 5.5 Recursión

```bash
grep -rn "def.*self\." models/ | xargs grep -l "return.*self\."
```
- [ ] No hay recursión sin límite de profundidad
- [ ] Las funciones recursivas profundas están convertidas a iterativo con `collections.deque`
  - Patrón:
    ```python
    from collections import deque
    MAX_DEPTH = 30  # comentario explicativo
    stack = deque([(root, 0)])
    while stack:
        node, depth = stack.popleft()
        if depth >= MAX_DEPTH:
            _logger.warning("MAX_DEPTH alcanzado en nodo %s", node.id)
            continue
        # procesar node
        stack.extend((child, depth + 1) for child in node.children)
    ```

---

## FASE 6 — OPTIMIZACIÓN JAVASCRIPT / OWL

### 6.1 RPC calls

```bash
grep -rn "rpc\|call_kw\|useService" static/src/js/
```
- [ ] RPC calls independientes entre sí se ejecutan en paralelo con `Promise.all([...])`
- [ ] No hay RPC calls dentro de loops (`for ... await rpc(...)`) → un solo RPC con lista de IDs
- [ ] Los métodos Python llamados por RPC están decorados con `@api.model` (no de instancia)

### 6.2 Lifecycle de componentes OWL

```bash
grep -rn "setTimeout\|setInterval\|addEventListener" static/src/js/
```
- [ ] Cada `setTimeout`/`setInterval` tiene su `clearTimeout`/`clearInterval` en `onWillUnmount`
- [ ] Cada `addEventListener` tiene su `removeEventListener` en `onWillUnmount`
- [ ] Los componentes con subscripciones a eventos tienen cleanup completo

### 6.3 Apertura de vistas

```bash
grep -rn "do_action\|action_open\|view_mode" static/src/js/
```
- [ ] No hay `domain` + `res_id` simultáneos en `do_action` (abre lista filtrada en lugar de form)
  - **Incorrecto**: `{ res_id: 5, domain: [...], view_mode: 'list,form' }`
  - **Correcto para form**: `{ res_id: 5, view_mode: 'form' }`
  - **Correcto para lista filtrada**: `{ domain: [...], view_mode: 'list' }`
- [ ] Los `view_mode` son los mínimos necesarios (no siempre `list,form,kanban,...`)

### 6.4 Componentes OWL

- [ ] Cada componente tiene `static props` definidos con tipos
- [ ] Los componentes no modifican props directamente (usan eventos para comunicar al padre)
- [ ] Los filtros/inputs que disparan RPCs tienen debounce (mínimo 300ms)
- [ ] Los estados de carga (`isLoading`) están implementados para evitar UI vacía

---

## FASE 7 — OPTIMIZACIÓN XML

### 7.1 Vistas

```bash
# Campos duplicados en misma vista
grep -c "name=" views/*.xml
```
- [ ] No hay campos declarados dos veces en la misma vista
- [ ] No hay `<field>` con el mismo `name` y diferente `widget` en la misma vista
- [ ] Los `attrs` complejos con múltiples condiciones están comentados explicando la lógica
- [ ] Los `domain` en Many2one reflejan todos los estados válidos del modelo target

### 7.2 Acciones

```bash
grep -rn "ir.actions.act_window\|ir.actions.server" views/
```
- [ ] No hay dos botones que deberían abrir filtros distintos pero llaman a la misma acción
- [ ] Los `domain` en acciones de ventana no tienen valores hardcodeados que deberían ser dinámicos
- [ ] Las acciones de servidor tienen `binding_model_id` solo si deben aparecer en el action menu

### 7.3 Manifest vs archivos

```bash
diff <(grep "'views/\|'data/\|'security/\|'wizard/" __manifest__.py | grep -o "'[^']*'" | tr -d "'" | sort) \
     <(find views/ data/ security/ wizard/ -name "*.xml" 2>/dev/null | sort)
```
- [ ] No hay archivos XML sin declarar en el manifest
- [ ] No hay entradas en el manifest que apunten a archivos inexistentes

---

## FASE 8 — COMENTARIOS Y DOCUMENTACIÓN

### 8.1 Docstrings Python

Formato obligatorio para métodos públicos:
```python
def method_name(self, param1, param2):
    """
    Descripción de qué hace el método en una línea.

    Descripción extendida si aplica: qué proceso representa,
    cuándo se llama, qué efectos secundarios tiene.

    :param param1: descripción y tipo esperado
    :param param2: descripción y tipo esperado
    :returns: descripción de qué devuelve y su tipo
    :raises UserError: cuándo y por qué
    :raises ValidationError: cuándo y por qué
    """
```

- [ ] Docstring de módulo al inicio de cada archivo Python (1-2 líneas de qué hace el archivo)
- [ ] Todos los métodos públicos tienen docstring completo
- [ ] Los métodos privados (`_método`) tienen al menos una línea de descripción
- [ ] Los métodos sobreescritos (`create`, `write`, `unlink`) documentan qué agregan al comportamiento base

### 8.2 Comentarios inline Python

- [ ] Los comentarios explican **por qué**, no **qué** (el qué se lee en el código)
  - ❌ `# Buscar OFs confirmadas`
  - ✅ `# Solo OFs confirmadas: las en borrador no tienen fechas confiables aún`
- [ ] Los cálculos de fechas/calendarios tienen comentario de timezone
  - Ej: `# Las fechas en Odoo son UTC; el calendario trabaja en TZ local del WC`
- [ ] Las fórmulas matemáticas no triviales tienen comentario con la fórmula en lenguaje natural
- [ ] Los magic numbers que no pudieron extraerse como constantes tienen comentario inline

### 8.3 Comentarios XML

- [ ] Los bloques de campos agrupados tienen `<!-- Sección: nombre -->`
- [ ] Los `attrs`/`invisible`/`readonly` complejos tienen comentario antes del campo
  - Ej: `<!-- Solo editable en borrador y por managers; en confirmado es solo lectura -->`
- [ ] Los `domain` con múltiples condiciones tienen comentario explicando la intención

### 8.4 JSDoc en widgets OWL

Formato obligatorio para cada widget:
```javascript
/**
 * @description Nombre del widget — qué muestra y para qué sirve.
 *
 * @fires RPC {string} nombre_metodo_python — descripción de qué retorna.
 *   Estructura de respuesta esperada:
 *   { campo1: tipo, campo2: tipo, lista: [{...}] }
 *
 * @listens OWL {EventName} — cuándo se dispara y qué hace el widget al recibirlo
 *
 * @example
 *   <WidgetName record="record" />
 */
```

- [ ] Cada widget tiene JSDoc completo al inicio de la clase
- [ ] Cada método tiene JSDoc con `@param`, `@returns`
- [ ] Los métodos que llaman RPCs documentan la estructura JSON esperada de respuesta
- [ ] `static props` definidos con tipos básicos (`{ record: Object }`)

---

## FASE 9 — CALIDAD GENERAL

### 9.1 Constraints y validaciones

```bash
grep -rn "_sql_constraints\|@api.constrains\|ValidationError" models/
```
- [ ] Combinaciones de campos que deben ser únicas tienen `_sql_constraints`
  - Patrón: `[('unique_user_config', 'unique(user_id, config_id)', 'Ya existe un permiso para este usuario')]`
- [ ] Las validaciones de negocio están en `@api.constrains`, no solo en `write()`
- [ ] Los mensajes de `ValidationError` y `UserError` explican qué está mal Y qué debe hacer el usuario

### 9.2 Campos y defaults

```bash
grep -rn "required=True" models/ | grep -v "default="
```
- [ ] Los campos `required=True` sin `default` son realmente obligatorios en todos los flujos
- [ ] Los campos `selection` tienen los mismos valores en Python y en filtros XML
- [ ] Los campos que usan `@api.onchange` deberían considerar si `@api.depends` + compute es más apropiado
- [ ] Los campos con `tracking=True` son los que realmente importa auditar en el chatter

### 9.3 Herencia y extensiones

- [ ] Los `_inherit` de modelos Odoo base (`mrp.production`, `purchase.order`, etc.) tienen prefijo `x_` en campos propios
- [ ] Los hooks `write()` en modelos base llaman `super()` antes de la lógica propia (salvo excepciones documentadas)
- [ ] Los `create()` sobreescritos no omiten `super()` por accidente

### 9.4 Migraciones (documentar, no aplicar)

- [ ] Documentar en REVIEW.md cualquier cambio que requeriría migración en base existente:
  - Agregar `store=True` a campo compute existente
  - Cambiar `_name` de modelo
  - Eliminar o renombrar valor de `selection`
  - Cambiar tipo de campo existente

---

## FASE 10 — UX/UI — VISTAS Y FORMULARIOS

### 10.1 Estructura visual de formularios

- [ ] Los campos están agrupados lógicamente con `<group string="Nombre de sección">`
- [ ] El orden de campos refleja el flujo de trabajo (se completa de arriba hacia abajo)
- [ ] Los campos de solo lectura usan el widget correcto para su tipo (monetary, date, many2one)
- [ ] Los campos técnicos o internos están en un `<group>` colapsado o en tab separado

### 10.2 Barra de estado

- [ ] La barra de estado tiene colores semánticos declarados en el field o via CSS:
  - `draft` → gris (neutral)
  - `confirmed`/`in_progress` → azul (activo)
  - `done` → verde (completado)
  - `cancel` → rojo (cancelado)
  - `warning`/`critical` → amarillo/rojo
- [ ] Los estados tienen labels en español (o el idioma del módulo) claros para el usuario final

### 10.3 Botones de acción

- [ ] Los botones tienen `icon="fa-nombre"` apropiado para la acción
- [ ] Los labels están en imperativo: "Calcular", "Confirmar", "Aplicar", no "Cálculo", "Confirmación"
- [ ] Las acciones destructivas o que afectan muchos registros tienen `confirm="¿Mensaje de confirmación?"`:
  ```xml
  <button name="button_apply" type="object" string="Aplicar"
          confirm="¿Aplicar reprogramación a X órdenes de fabricación? Esta acción no se puede deshacer."
          groups="mrp.group_mrp_manager"/>
  ```
- [ ] Los botones que requieren grupo específico tienen `groups="..."` en el XML (doble protección)

### 10.4 Vistas de lista

- [ ] Las columnas son las mínimas útiles (no más de 7-8 en pantalla normal)
- [ ] Las columnas más importantes están primero y son ordenables
- [ ] Hay `optional="show"/"hide"` en columnas secundarias para no sobrecargar la vista default
- [ ] Los colores de fila (`decoration-danger`, `decoration-warning`, `decoration-success`) están implementados para estados críticos

### 10.5 Vistas de búsqueda

- [ ] Hay filtros predefinidos para los casos de uso más frecuentes (ej: "Mis alertas", "Críticas", "Sin resolver")
- [ ] Hay `group_by` predefinidos útiles (ej: por estado, por tipo, por responsable)
- [ ] El campo de búsqueda por defecto es el más natural para el usuario (nombre, referencia)
- [ ] Los filtros tienen labels claros en el idioma del módulo

### 10.6 Smart buttons

- [ ] Los smart buttons muestran conteo cuando hay registros relacionados
- [ ] El conteo usa `invisible="count == 0"` para no mostrar botones vacíos (o es intencional mostrarlo)
- [ ] El click navega directamente al modelo relacionado con el filtro correcto

---

## FASE 11 — UX/UI — MENSAJES Y FEEDBACK

### 11.1 Errores y validaciones

- [ ] Los `UserError` tienen dos partes: qué salió mal + qué debe hacer el usuario
  - ❌ `raise UserError(_("Error de validación"))`
  - ✅ `raise UserError(_("No se puede confirmar: la fecha límite es anterior a hoy. Modificá la fecha antes de confirmar."))`
- [ ] Los `ValidationError` de `@api.constrains` identifican el campo problemático y el valor inválido
- [ ] Los errores de permisos tienen mensaje específico: "Esta acción requiere el rol X. Contactá al administrador."

### 11.2 Confirmaciones y feedback positivo

- [ ] Los flujos importantes (confirmar solicitud, aplicar reprogramación) tienen `message_post` en el chatter
  - Patrón: `self.message_post(body=_("Plan aplicado por %s. Se reprogramaron %d órdenes.") % (self.env.user.name, len(lines)))`
- [ ] Los modelos donde el historial importa tienen `_inherit = ['mail.thread', 'mail.activity.mixin']`
- [ ] Los campos clave tienen `tracking=True` para registro automático en chatter:
  - Fechas, estados, responsables, cantidades críticas

### 11.3 Notificaciones del cron

- [ ] Si el cron detecta alertas críticas nuevas, ¿notifica a alguien? Documentar el comportamiento esperado
- [ ] Los resultados del cron se loguean con `_logger.info` para diagnóstico

### 11.4 Banners informativos

- [ ] Los formularios con estados que requieren atención tienen banner con `alert-warning` o `alert-danger`
  ```xml
  <div class="alert alert-warning" role="alert"
       invisible="x_reschedule_needed == False">
      <strong>Reprogramación sugerida:</strong>
      Esta OF tiene dependencias afectadas. Revisá el plan de reprogramación.
  </div>
  ```

---

## FASE 12 — TOOLTIPS Y AYUDA CONTEXTUAL

### 12.1 Atributo `help` en campos Python

Formato estándar para el atributo `help`:
```python
# Para campos de configuración:
mo_critical_days = fields.Integer(
    string="Días críticos (ÓF)",
    default=3,
    help="Cantidad de días de atraso a partir de los cuales una Orden de Fabricación "
         "se marca como CRÍTICA (rojo) en el dashboard y genera alerta de severidad alta. "
         "Valor por defecto: 3 días."
)

# Para campos computados:
x_earliest_date = fields.Datetime(
    string="Fecha más temprana posible",
    compute="_compute_earliest_date",
    store=True,
    help="Fecha más temprana en que esta línea podría iniciar su producción, considerando: "
         "stock disponible, capacidad de centros de trabajo y calendario laboral. "
         "Se recalcula al ejecutar 'Calcular' en la solicitud de programación."
)
```

- [ ] Cada campo de configuración tiene `help` explicando impacto del valor y unidades
- [ ] Cada campo computed tiene `help` explicando de dónde viene el valor y cuándo se actualiza
- [ ] Los campos Many2one con domain restrictivo tienen `help` explicando qué opciones aparecen y por qué
- [ ] Los campos booleanos técnicos tienen `help` que explica qué activa/desactiva el flag

### 12.2 Tooltips en vistas XML

- [ ] Los botones de acción no obvios tienen `help` en el XML:
  ```xml
  <button name="button_calculate" type="object" string="Calcular"
          help="Propaga el delta de fechas desde el pivot hacia todas las ÓFs dependientes. No modifica la base de datos hasta que se aplique el plan."/>
  ```
- [ ] Los widgets especiales tienen `help` explicando su interacción
- [ ] Los campos con `widget="statusbar"` tienen los estados bien ordenados y con labels claros

### 12.3 Texto introductorio en wizards y formularios complejos

- [ ] Los wizards tienen un párrafo introductorio explicando qué hace cada paso:
  ```xml
  <div class="alert alert-info" role="status">
      <p><strong>Cómo funciona la reprogramación:</strong></p>
      <p>1. Seleccioná la ÓF de referencia (pivot) y su nueva fecha fin.</p>
      <p>2. Hacé clic en "Calcular" para ver el impacto en cascada.</p>
      <p>3. Revisá y ajustá las fechas propuestas si es necesario.</p>
      <p>4. Hacé clic en "Aplicar" para confirmar los cambios (requiere rol Manager).</p>
  </div>
  ```
- [ ] Los formularios de configuración tienen descripción de cada sección

---

## FASE 13 — EXPLICACIÓN DE FÓRMULAS Y CÁLCULOS

### 13.1 Documentación de fórmulas en Python

Formato para métodos de cálculo:
```python
def _compute_earliest_date(self):
    """
    Calcula la fecha más temprana de inicio para cada línea de solicitud.

    Algoritmo (bottom-up):
    1. Para componentes sin sub-LdM: fecha = hoy + lead_time del proveedor
    2. Para subproductos: fecha = max(fechas de componentes) + tiempo de fabricación
    3. Para el producto raíz: fecha = max(fechas de subproductos) + tiempo de fabricación

    El tiempo de fabricación se calcula respetando el calendario del centro de trabajo:
    - Se usa _schedule_backward() del mixin para restar horas hábiles desde la deadline
    - Las horas se convierten de UTC a TZ local del WC antes del cálculo
    - Resultado final se convierte de vuelta a UTC para almacenar en Odoo

    Unidades: todas las fechas en UTC (estándar Odoo). Los días de lead_time
    son días naturales (no hábiles).
    """
```

- [ ] Cada método compute no trivial documenta el algoritmo paso a paso
- [ ] Las fórmulas de scheduling documentan explícitamente el manejo de timezone (UTC vs local)
- [ ] Los cálculos de capacidad/carga documentan las unidades (horas, días, %)
- [ ] Los algoritmos de propagación en cascada documentan el orden de procesamiento

### 13.2 Comentarios inline en cálculos

```python
# Convertir a TZ local del WC antes de calcular con el calendario
# (el calendario usa horas locales, Odoo almacena en UTC)
local_dt = fields.Datetime.context_timestamp(self, deadline_utc)

# Restar la duración en horas hábiles (no cronológicas)
# _schedule_backward devuelve la fecha en TZ local; reconvertir a UTC
start_local = self._schedule_backward(local_dt, duration_hours, calendar)
start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)

# Agregar 10% de buffer sobre la duración estimada
# (factor empírico para absorber variabilidad en tiempos de operación)
buffered_duration = duration_hours * 1.10
```

- [ ] Los cálculos de tiempo con timezone tienen comentario en cada conversión
- [ ] Los factores de ajuste o tolerancias tienen comentario explicando de dónde viene el valor
- [ ] Las decisiones de redondeo tienen comentario (ej: "ceil para no subestimar la carga")

### 13.3 KPIs del dashboard

- [ ] Cada KPI tiene `help` en el campo Python explicando exactamente qué incluye:
  - Qué registros cuenta/suma
  - En qué rango de fechas
  - Qué estados incluye/excluye
  - Si es en tiempo real o del último refresh
- [ ] Los métodos `get_X_dashboard_data()` tienen docstring con la estructura JSON de respuesta:
  ```python
  def get_mo_dashboard_data(self, record_id):
      """
      Retorna KPIs de órdenes de fabricación para el dashboard.

      :returns: dict con estructura:
          {
              'total': int,           # ÓFs en estado confirmed + progress
              'on_time': int,         # ÓFs con scheduled_date_finished >= hoy
              'delayed': int,         # ÓFs con scheduled_date_finished < hoy
              'critical': int,        # ÓFs retrasadas más de config.mo_critical_days
              'items': [              # Lista de ÓFs para la tabla paginada
                  {
                      'id': int,
                      'name': str,
                      'product': str,
                      'qty': float,
                      'date_finish': str (ISO),
                      'days_late': int,
                      'state': str
                  }
              ]
          }
      """
  ```

---

## ENTREGABLE FINAL — REVIEW.md

Al terminar todas las fases, creá o actualizá `REVIEW.md` con este formato:

```markdown
# Review — [nombre_módulo] v[versión]
Fecha: [fecha]
Revisor: Claude Code

## Resumen ejecutivo
[3-5 líneas: cuántos issues encontrados por severidad, qué se corrigió, qué queda pendiente]

## 🔴 Crítico (seguridad / bugs bloqueantes)
| # | Archivo | Línea | Descripción | Estado |
|---|---------|-------|-------------|--------|
| 1 | `archivo.py` | 123 | Descripción del problema y del fix | Corregido / Requiere decisión |

## 🟡 Importante (performance / lógica incorrecta / UX bloqueante)
[misma tabla]

## 🟢 Mejoras (docs / estructura / UX / tooltips)
[misma tabla]

## Cambios aplicados
| Archivo | Descripción del cambio |
|---------|----------------------|
| `models/archivo.py` | Fix: descripción |

## Decisiones pendientes para el equipo
1. **Título del issue** (`archivo.py:línea`): descripción del problema, opciones posibles,
   y recomendación del revisor con justificación.

## Notas de migración
[Lista de cambios que requieren script de migración en bases existentes]
```

---

## USO DE ESTE ARCHIVO

### Para revisión completa (módulo nuevo o release mayor):
```
Leé CLAUDE.md y ODOO_MODULE_REVIEW.md.
Ejecutá todas las fases de ODOO_MODULE_REVIEW.md en orden sobre este módulo.
Aplicá directamente todos los fixes con severidad 🔴 y 🟡.
Para 🟢 aplicá docs y tooltips; marcá como "Requiere decisión" los cambios de lógica.
Generá REVIEW.md al finalizar.
```

### Para revisión rápida (hotfix o feature puntual):
```
Leé CLAUDE.md y ODOO_MODULE_REVIEW.md.
Ejecutá solo las fases 2 (Seguridad), 5 (Optimización Python) y 9 (Calidad General)
sobre los archivos modificados en este commit: [lista de archivos].
Reportá solo issues nuevos no presentes en REVIEW.md existente.
```

### Para revisión de UX antes de demo con cliente:
```
Leé CLAUDE.md y ODOO_MODULE_REVIEW.md.
Ejecutá solo las fases 10, 11, 12 y 13 (UX/UI, mensajes, tooltips, fórmulas).
Foco en: mensajes de error claros, tooltips en campos de configuración,
confirmaciones antes de acciones destructivas, y banners informativos.
```
