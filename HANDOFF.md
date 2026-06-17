# eventcal — Handoff para Code

Brief para continuar el proyecto. Léelo entero antes de tocar nada: muchas de las
decisiones parecen menores pero protegen propiedades del sistema que conviene no
romper (idempotencia del re-sync, seguridad de los adaptadores, evolución del
estándar). Donde digo "no toques esto" hay una razón, no es preferencia.


## 1. Qué es esto en una frase

Un estándar JSON para calendarios de eventos estructurados (`eventcal/v1`) más la
fontanería que lo hace útil: validador, adaptadores declarativos para ingerir
fuentes existentes (OpenF1, etc.) y proyecciones (`.ics` ya en producción, web
pendiente). La visión a largo plazo es un hub comunitario tipo "Hugging Face de
calendarios" sobre Rails. Hoy estamos en la fase 0: probar demanda antes de
construir la plataforma.


## 2. Estado actual (qué funciona ya)

Repo público en GitHub con GitHub Actions corriendo cada 6h:

  OpenF1 (red real) → adaptador declarativo → eventcal/v1 → validación → .ics
  → publicado en GitHub Pages

URL en vivo: `https://sergiovaleromiacade.github.io/eventcal/f1-2026.ics`
(temporada 2026 entera, 26 GP + sesiones, con `STATUS:CANCELLED` derivado del
campo `is_cancelled` de OpenF1: los GP de Bahréin y Arabia 2026 salen cancelados
automáticamente, no se metió a mano).

Lo que NO existe todavía:
- Página web/landing (este es el siguiente paso, ver §7).
- Plataforma Rails (fase 1, no toca aún).
- Segundo adaptador de otra fuente (pendiente; sirve para estresar el estándar).
- Analítica/medición (limitación de GitHub Pages, ver §7).


## 3. Arquitectura

Tres piezas con responsabilidades muy separadas. **No las mezcles**, esa
separación es el diseño.

```
                       ┌──────────────────────┐
                       │  eventcal/v1 (JSON)  │  ← fuente de verdad
                       │   = el estándar      │
                       └──────────┬───────────┘
                                  │
       ┌──────────────────────────┼──────────────────────────┐
       │ entrada                  │                   salida │
       ▼                          ▼                          ▼
  Adaptador declarativo     Editor visual              Proyecciones
  (de fuentes ajenas)       (publicar a mano)        .ics · web · app
```

- **Estándar**: el contrato. Núcleo agnóstico + extensiones por tipo via
  registro. Validación en dos fases.
- **Adaptadores declarativos**: vocabulario cerrado de mapeadores (datos, no
  código) que convierten fuentes externas a `eventcal/v1`.
- **Proyecciones**: el `eventcal` se reproyecta a formatos consumibles. El `.ics`
  ya existe; la web es lo siguiente.


## 4. El estándar `eventcal/v1`

### 4.1. Núcleo (`eventcal.schema.json`)

JSON Schema draft 2020-12. Valida el esqueleto común a TODOS los calendarios y
eventos. No conoce ningún tipo concreto — `details` es un objeto genérico aquí.

Decisiones que conviene NO cambiar:

- **`schema: "eventcal/v1"`** es un `const`, no un `string`. Permite evolucionar
  a v2 sin romper consumidores. Si necesitas un cambio incompatible, no lo
  cueles en v1: empieza una v2.
- **`id` del calendario es slug obligatorio** (`^[a-z0-9][a-z0-9._-]*$`). Es la
  clave estable de la que depende todo el re-sync idempotente. Sin esto, cada
  re-ejecución duplicaría eventos en vez de actualizarlos.
- **`id` del evento es opcional en el esquema, obligatorio en la plataforma**.
  Distinción intencionada: el editor puede ir construyendo un evento sin id, pero
  al publicar la plataforma debe exigirlo. Nunca lo derives del título (los
  títulos cambian, los ids no deben).
- **`start`/`end` usa un patrón propio, no `format: date-time`**. Esto es la
  parte más sutil del estándar:
  - Con offset (`Z` o `+01:00`) = instante absoluto. Para carreras, conciertos,
    cualquier evento de hora global.
  - Sin offset = hora local "flotante", interpretada según `timezone` del
    calendario. Para itinerarios: "10:00 en Roma" da igual en qué huso esté el
    lector. `format: date-time` rechazaría este caso, por eso no lo usamos.
- **`additionalProperties: false`** en el núcleo. Es la red que caza erratas
  (`titel` en vez de `title` salta). No la quites para "ser permisivo".
- **`partOf`** modela sub-eventos manteniendo la lista plana. El padre y los
  hijos viven al mismo nivel; el hijo apunta al padre por id. Esto preserva la
  jerarquía sin romper la exportación a `.ics`.
- **`status`** distingue `confirmed`, `tentative`, `cancelled`, `postponed`.
  Esto es lo que hace que sea un calendario "vivo" y no una foto. Los GP
  cancelados de 2026 que salen en producción demuestran que funciona.

### 4.2. Extensiones tipadas (`types/*.schema.json`)

Cada tipo de evento (`motorsport.event`, `music.concert`, `travel.activity`,
etc.) vive en su propio archivo. Solo describe la forma de su `details`.
Decisión clave: **núcleo agnóstico, extensiones autónomas, sin `$ref` entre
archivos**. Esto se llamó "validación en dos fases" (§4.3) y se eligió frente a
componer todo con `$ref` por dos motivos:

1. El núcleo no necesita conocer la lista de tipos. Añadir un tipo nuevo es
   publicar un archivo + entrada en el registro, sin tocar el núcleo.
2. La validación profunda de un tipo desconocido se salta limpiamente (el
   esqueleto se valida igual); cuando aparece el archivo, la validación se
   vuelve estricta sin romper nada anterior.

Cada extensión declara `x-eventcal-type` (campo informativo `x-`, ignorado por
validadores) para autodeclararse.

### 4.3. Registro (`registry.json`)

Mapa `type → archivo de extensión`. Es el directorio de tipos disponibles. La
comunidad amplía la taxonomía publicando aquí.

### 4.4. Validación en dos fases (ver `validate.py` / `validate.rb`)

```
Fase 1: documento completo contra el núcleo            → esqueleto válido
Fase 2: para cada evento con type registrado,
        details contra el esquema de su extensión      → details válidos
```

Tipo no registrado: pasa la fase 1, se salta la fase 2. Es deliberado.

**Validador en Ruby**: usar la gema `json_schemer` (con guion bajo), NO
`json-schema`. La segunda usa Draft 4 por defecto y nuestro esquema está en
2020-12. Ya está escrito en `validate.rb`, listo para `app/services/eventcal/`.

### 4.5. Lo que NO está en el esquema, a propósito

- **`end >= start`** vive en el validador de plataforma, no en el esquema. JSON
  Schema no compara dos campos entre sí.
- **Recurrencia (`RRULE`)** está aparcada. La mayoría de calendarios reales son
  listas explícitas. Se añadiría como campo opcional cuando aparezca un caso que
  lo necesite, no antes.


## 5. Adaptadores declarativos

### 5.1. Por qué declarativos

Tres motivos, en orden de importancia:

1. **Seguridad**: la plataforma va a ejecutar adaptadores que escribe la
   comunidad. Un lenguaje de expresiones tipo JSONata es código arbitrario y
   peligroso. Un vocabulario cerrado de operaciones fijas se ejecuta en caja de
   arena por construcción. Esto no es opcional, es la única forma de aceptar
   adaptadores externos sin riesgo.
2. **Auditabilidad**: un adaptador es datos; se diffea, se revisa, se versiona.
3. **Interfaz visual posible**: el vocabulario cerrado mapea 1:1 a un
   constructor visual de mapeos. Mientras es pequeño, cabe en un desplegable.

### 5.2. Vocabulario actual

Cinco operaciones, ninguna más sin caso real que lo justifique:

- `const`: valor fijo.
- `from`: copia un campo del origen. Con `map` opcional para traducir valores.
- `template`: interpolación de campos en una cadena (`f1-{session_key}`).
- `cases`: condicional sobre un campo (`is_cancelled` → `"cancelled"`).
- Objetos anidados: recursión, descartando `None`.

**No añadas un sexto sin documentar el caso real**. La tentación de meter
"transform" o "eval" rompe la propiedad de caja de arena.

### 5.3. Cómo es un adaptador

Mira `openf1.adapter.json`. Estructura:

- `params`: lo que la plataforma le pasará (`year`, etc.).
- `calendar`: bloque que produce los campos del calendario (1 sola vez).
- `streams[]`: cada uno con `fetch` (url + query con interpolación de params) y
  `mapping` (qué hacer con cada registro de ese stream).

El intérprete (`apply_adapter.py`) son ~40 líneas. Si necesitas escribir uno más
grande, probablemente estás metiendo lógica que no debería estar ahí.

### 5.4. Idempotencia del re-sync

El re-sync funciona porque los `id` se derivan de claves naturales de la fuente
(`f1-{session_key}`), no del contenido. Al re-ejecutar, los mismos `id` se
actualizan en vez de duplicarse, y un `is_cancelled: true` viaja por el `cases`
hasta convertirse en `status: "cancelled"`. **No derives ids de campos
mutables** (título, descripción): rompes el re-sync.

### 5.5. Lo que el vocabulario AÚN no cubre

Filtrar registros (skip_if). Apareció cuando OpenF1 nos dio sesiones "Day 1/2/3"
de pretemporada: en ese momento mapeamos a `practice` (decisión de producto),
pero si en otra fuente surge la necesidad de descartar, habrá que añadir
`skip_if` con el mismo patrón cerrado (`{from, equals|in, ...}`). Documentado
para no improvisarlo.


## 6. Estructura de archivos

```
eventcal/
├── eventcal.schema.json          núcleo del estándar (agnóstico)
├── registry.json                 type → archivo de extensión
├── types/
│   ├── motorsport.event.schema.json
│   ├── motorsport.session.schema.json
│   ├── music.concert.schema.json
│   └── travel.activity.schema.json
├── openf1.adapter.json           adaptador declarativo OpenF1 → eventcal
├── apply_adapter.py              intérprete del adaptador (~40 líneas)
├── eventcal_to_ics.py            conversor genérico eventcal → .ics (RFC 5545)
├── build_f1.py                   pipeline F1 que ejecuta el cron
├── validate.py                   validador 2 fases en Python (referencia)
├── validate.rb                   equivalente en Ruby para la plataforma
├── public/                       lo que GitHub Pages publica (se regenera)
│   ├── f1-2026.ics
│   └── f1-2026.json
└── .github/workflows/sync-f1.yml workflow que ejecuta build_f1.py cada 6h
```

Notas importantes:

- **GitHub Pages** publica el contenido de `public/` como raíz del sitio (por el
  `path: public` en `upload-pages-artifact`). Por eso la URL pública NO lleva
  `/public/` delante.
- **Solo se publica lo que cae en `public/`**. El resto del repo es código
  fuente, no es accesible por web.


## 7. Siguiente paso: la página web (lo que ahora estoy abriendo en Code)

### 7.1. Por qué es crítica ahora, no opcional

Una URL `.ics` suelta no la usa nadie. La página es la puerta de entrada y la
superficie que de verdad se comparte. El `.ics` es el motor detrás del botón.

### 7.2. Qué tiene que hacer la página

- Titular claro ("Calendario F1 2026, siempre actualizado").
- Botón grande de **Suscribir** con el truco del protocolo `webcal://`: enlace
  con `webcal://sergiovaleromiacade.github.io/eventcal/f1-2026.ics` (no
  `https://`) → al pulsarlo se abre directamente la app de calendario del
  usuario con el diálogo de suscripción. Esto convierte "URL random" en "botón
  que se entiende".
- Próximos eventos leídos del `f1-2026.json` en vivo (demuestra que está vivo
  y enseña la riqueza que el `.ics` no captura: imágenes, enlaces, filtros).
- Filtro "solo carreras" para probar la tesis de la riqueza: el JSON tiene los
  metadatos para filtrar (`details.session`), el `.ics` no.

### 7.3. Dónde alojarla

Mismo GitHub Pages. La página es un `index.html` (más opcional CSS/JS) dentro
de `public/`. El workflow ya publica esa carpeta entera.

### 7.4. Medición — el agujero a resolver

GitHub Pages no da logs de acceso. Sin métricas, el "test de demanda" no mide
nada. Opciones:

- Servir la página con analítica ligera respetuosa (Plausible, Umami,
  GoatCounter). Con un script externo basta.
- Más adelante, servir el `.ics` a través de un Cloudflare Worker para contar
  suscriptores únicos por fingerprint de cliente. No urgente.

Decidir esto antes de promocionar nada. Promocionar sin medir es desperdiciar
la señal.

### 7.5. Honestidad sobre F1 como test

f1calendar.com ya existe y resuelve esto razonablemente. F1 fue ideal como
prueba técnica (datos gratis, escala manejable, complejidad real), pero como
test de demanda está contaminado: si no hay tracción, no sabremos si es por la
idea o porque la gente ya tiene su solución. Para señal limpia, conviene un
segundo adaptador de un nicho donde no exista buen calendario (esports
concreto, serie de motor menor, festivales locales). No urgente, pero
considéralo antes de invertir mucho en promoción de F1.


## 8. Decisiones de producto pendientes (no técnicas)

- **Segundo dominio**: ¿qué fuente añadimos después de F1 para estresar el
  estándar y abrir el test de demanda? Pendiente de elegir.
- **Editor visual de calendarios**: la idea era que un grupo de música pudiera
  publicar su gira sin tocar JSON. No es fase 0; entra cuando exista la
  plataforma Rails. Por ahora, calendarios "a mano" se hacen escribiendo el
  JSON directamente (ok para sembrar).
- **Constructor visual de adaptadores**: mismo caso. La forma del adaptador
  declarativo ya soporta esa capa visual cuando llegue, no hace falta cambiar
  nada del estándar.


## 9. Reglas de oro para no romper el diseño

1. El estándar (`eventcal.schema.json`) cambia con extrema cautela. Si crees
   que hace falta tocarlo, considera primero si la necesidad cabe en una
   extensión nueva.
2. Los adaptadores son datos, no código. Ninguna operación nueva del
   vocabulario sin justificación documentada.
3. Los `id` se derivan de claves naturales estables, nunca de contenido
   mutable. El re-sync depende de esto.
4. `additionalProperties: false` se queda. Es la red de erratas.
5. Antes de añadir una dependencia "porque iría bien", recuerda que el
   intérprete entero son 40 líneas. La simplicidad del motor es la prueba de
   que el formato está bien pensado.

---

Cualquier duda concreta sobre por qué algo es como es, casi seguro está en la
conversación de la que sale este handoff. Pregunta antes de cambiar algo que
parezca raro: lo raro suele ser intencionado.
