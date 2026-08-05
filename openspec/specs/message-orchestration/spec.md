# message-orchestration Specification

## Purpose

Resolver cada mensaje de candidato en una respuesta. Es el "cerebro" actual
(`app/orchestrators/knowledge_orchestrator.handle_message`): clasifica el mensaje vía
Neo4j, aplica guardas deterministas, elige cómo responder (RAG / LLM amistoso /
plantilla controlada / acuse de perfil), agrega una pregunta del funnel cuando
corresponde, y persiste el resultado. Respeta la prioridad de fuentes de verdad y la
política de conversación (`app/policies/conversation_policy.md`).
## Requirements
### Requirement: Resolución de ruta vía contrato de conocimiento

El sistema SHALL resolver cada mensaje a un contrato con `route`, `intent`, `risk_level`
y banderas (`requires_rag`, `requires_human`, `requires_clarification`), usando Neo4j
para reconocer términos y luego aplicar guardas de perfil y overrides deterministas. El
LLM no decide políticas de ruteo.

#### Scenario: Pregunta informativa durante una etapa de perfil
- **WHEN** hay una etapa de perfil pendiente y el candidato pregunta por pago/rutas/documentos
- **THEN** el contrato resuelve `route=rag` (responder la pregunta) y la etapa de perfil sigue pendiente, sin forzar la siguiente pregunta del formulario

#### Scenario: Respuesta directa a la pregunta de perfil pendiente
- **WHEN** el candidato responde directamente el dato pendiente del perfil
- **THEN** el contrato resuelve hacia perfil y el dato se registra

#### Scenario: Tema sensible o admisión
- **WHEN** el mensaje toca sustancias/antidoping o admite conducta inhabilitante
- **THEN** el contrato marca `requires_human` y la conversación se rutea a revisión humana, sin continuar extracción de perfil en ese turno

### Requirement: Selección de modo de respuesta

El sistema SHALL elegir exactamente un modo de respuesta por turno según el contrato, en
este orden: hora local (template), RAG (`requires_rag`), LLM amistoso (smalltalk seguro),
acuse de señal de perfil, o respuesta controlada por plantilla.

#### Scenario: Ruta RAG
- **WHEN** el contrato tiene `requires_rag=true`
- **THEN** el sistema recupera contexto de ChromaDB y genera la respuesta con el LLM acotada a ese contexto

#### Scenario: Smalltalk seguro
- **WHEN** el contrato es smalltalk/amistoso y el mensaje es seguro para el LLM
- **THEN** el sistema responde con el LLM amistoso (voz de equipo), sin inventar facts del candidato

#### Scenario: Sin generación aplicable
- **WHEN** ninguna ruta de generación aplica
- **THEN** el sistema responde con una plantilla controlada derivada del contrato

### Requirement: Pregunta del funnel agregada por el sistema

Después de una respuesta RAG, amistosa o de acuse de perfil, el sistema SHALL agregar a
lo sumo una pregunta del funnel de perfilamiento, emitida por el sistema (no por el LLM)
y solo si aún hay un campo núcleo faltante. Nunca debe encimar una pregunta de perfil en
un saludo inicial ni repetir agresivamente una pregunta pendiente.

#### Scenario: Hay campo faltante tras responder
- **WHEN** se respondió una pregunta lateral y queda un campo de perfil sin completar
- **THEN** el sistema añade una sola pregunta del funnel para el siguiente campo faltante

#### Scenario: Núcleo de perfil completo
- **WHEN** todos los campos núcleo ya están completos
- **THEN** el sistema no añade pregunta de funnel

### Requirement: Persistencia del turno y trazabilidad

El sistema SHALL persistir el turno completo: mensaje de usuario y respuesta del
asistente, actualización de etapa de conversación y de lead, facts extraídos, y un evento
`knowledge_contract_resolved` con metadata de routing, fuentes RAG, costos y timings.

#### Scenario: Turno resuelto
- **WHEN** un mensaje se resuelve en una respuesta
- **THEN** el sistema guarda mensaje+respuesta, actualiza stage y lead memory, y registra el evento con su metadata

### Requirement: Grounding del comentario conversacional

El comentario conversacional del sistema (modo friendly/reacción corta) SHALL basarse
únicamente en lo que el candidato expresó en su mensaje. El sistema SHALL NOT introducir
números, años, experiencia, ciudad, licencia, apto médico, documentos ni condiciones que el
candidato no haya dicho, ni reutilizar valores de ejemplos internos del prompt.

> Nota de implementación: requirement doc-only. La adaptación del flujo vivo
> (`_answer_friendly_message`, few-shots del prompt) queda para una fase posterior y no se
> implementa en este cambio.

#### Scenario: Candidato pide esperar y el sistema no inventa cifras
- **WHEN** el candidato dice "ahorita le respondo", "espéreme" o "luego le digo"
- **THEN** el sistema responde sin mencionar años ni ninguna cifra
- **AND** no afirma datos de experiencia que el candidato no dio

### Requirement: Escritor único de facts por turno

En el camino worker, el sistema SHALL persistir los facts del turno exactamente una vez
por turno, desde `_store_lead_memory_updates` usando los `pre_validated_facts` producidos
por `validate_extraction`. SHALL NOT existir una segunda escritura de facts (guard o funnel
nudge no persisten directamente). El guard y el funnel nudge consumen los facts validados
del turno para tomar decisiones, sin re-extraer ni re-persistir.

#### Scenario: Guard + orquestador sin escritura doble
- **WHEN** en un turno el guard dispara y reemplaza la respuesta del orquestador
- **THEN** los facts del turno se persisten una sola vez (por `_store_lead_memory_updates`)
- **AND** no se persisten facts adicionales por el camino del guard

#### Scenario: Funnel nudge consume facts del turno, no re-extrae
- **WHEN** `_build_funnel_nudge` decide la siguiente pregunta del funnel
- **THEN** lee los facts del turno de `pre_validated_facts`, no lanza un nuevo extractor

### Requirement: Respuesta de cara al candidato sin instrucciones internas

El sistema SHALL responder al candidato con lenguaje de cara al usuario y SHALL NOT exponer
reglas o instrucciones internas de operación (p. ej. "Mundo debe...", "Si no conoce el
circuito... debe pedir... antes de dar una cifra").

> Nota de implementación: requirement doc-only; no se implementa en este cambio.

#### Scenario: Pregunta de pago no expone reglas internas
- **WHEN** el candidato pregunta por pago o circuitos
- **THEN** el sistema responde con información de cara al candidato, o pide ciudad/circuito de forma natural
- **AND** la respuesta no incluye frases de instrucción interna

### Requirement: Respuesta enfocada sin mezcla de temas

Ante una pregunta específica, el sistema SHALL responder enfocado en ese tema y SHALL NOT
ensamblar contenido de temas no relacionados (p. ej. mezclar pago con paradas autorizadas o
con el proceso documental de una ciudad).

> Nota de implementación: requirement doc-only; no se implementa en este cambio.

#### Scenario: Pregunta de pago para sencillo no mezcla temas
- **WHEN** el candidato pregunta "¿por ejemplo para sencillo?" en el contexto de pago/circuito
- **THEN** la respuesta se mantiene en pago/tipo de unidad
- **AND** no incluye paradas autorizadas ni el proceso documental de otra ciudad

### Requirement: Acuse del funnel sin eco de datos

Al registrar datos de perfil aportados por el candidato, el sistema SHALL responder con un
conector breve y VARIADO (p. ej. "Va." / "Perfecto." / "Listo.") seguido de la siguiente
pregunta del funnel, y SHALL NOT repetir (eco) el valor de los datos recién aportados
("licencia tipo E vigente", "20 años de experiencia, anotado"). Esto subsume la regla
anti-duplicación previa: sin eco no hay dato repetido en dos formas.

Excepción única: la primera vez que se conoce el nombre del candidato
(`name_just_learned`), el acuse SHALL ser el saludo con nombre de pila ("Gracias,
<nombre>.") más la siguiente pregunta — única confirmación que menciona un dato.

Cuando el perfil conversacional queda completo, el cierre SHALL ser ligero: acusar el
avance e indicar el siguiente paso (documentos) una sola vez, SHALL NOT repetir
recordatorios de proceso ni condicionar el contacto ("siempre que sigas interesado").

#### Scenario: Dato registrado sin eco
- **WHEN** el candidato aporta un dato del funnel (unidad, licencia, años, ciudad…)
- **THEN** el reply es un conector breve + la siguiente pregunta del funnel
- **AND** el reply NO contiene el valor del dato recién aportado

#### Scenario: Saludo con nombre la primera vez
- **WHEN** el sistema conoce el nombre del candidato por primera vez en el turno
- **THEN** el acuse es "Gracias, <nombre de pila>." + la siguiente pregunta del funnel

#### Scenario: Conector variado, no enlatado
- **WHEN** se generan acuses en turnos consecutivos
- **THEN** el conector varía (no es una frase fija repetida turno a turno)

### Requirement: Confirmación contextual corta resuelve el campo según la última pregunta

El sistema SHALL resolver de forma determinista (sin LLM) el campo de perfil
correspondiente a la última pregunta cerrada del bot cuando el candidato responde con una
confirmación o negación corta ("Sí", "ya tengo", "no", "todavía no"). Esto incluye apto
médico, vigencia de licencia, cartas laborales y el comprobante de pago de renovación o
trámite (la alternativa vigente cuando licencia/apto no están vigentes).

En particular, cuando la última pregunta del bot fue por el comprobante de pago de la
renovación/trámite, una confirmación corta SHALL fijar `documents.renewal_proof = "si"` y
una negación corta SHALL fijar `documents.renewal_proof = "no"` (cierre suave por
vencido-sin-trámite en lugar de re-preguntar).

#### Scenario: Confirmación al comprobante de pago
- **WHEN** el bot preguntó por el comprobante de pago de la renovación y el candidato
  responde "Sí" o "ya tengo el comprobante"
- **THEN** el sistema fija `documents.renewal_proof = "si"` y el funnel no re-pregunta

#### Scenario: Negación al comprobante de pago
- **WHEN** el bot preguntó por el comprobante de pago y el candidato responde "no" o
  "todavía no"
- **THEN** el sistema fija `documents.renewal_proof = "no"` y aplica el cierre suave por
  vencido-sin-trámite

### Requirement: Reconocimiento de correcciones explícitas

El sistema SHALL reconocer una corrección explícita del candidato sobre un dato previo (por
ejemplo "en realidad es sencillo" o "me equivoqué, son 10 años"), SHALL actualizar el valor
corregido y SHALL NOT repetir el valor anterior ni una interpretación que el candidato ya
rechazó.

> Nota de implementación: la mecánica de detección/persistencia de correcciones está cubierta
> por tasks pendientes de `multi-intent-migration` (6.3, 7.2, 7.4, 9.3.3, 9.3.11). Esta
> requirement fija el comportamiento conversacional esperado en el camino vivo, sin duplicar
> esa lógica; doc-only.

#### Scenario: Corrección de tipo de unidad
- **WHEN** el candidato dice "creo que le había dicho full, en realidad es sencillo"
- **THEN** el sistema registra `experience.vehicle_type=sencillo`
- **AND** no vuelve a afirmar full ni etiquetar "(escuelita)"

#### Scenario: Corrección de años de experiencia
- **WHEN** el candidato dice "no quiero escuelita, sé manejar sencillo, y tengo 10 años"
- **THEN** el sistema toma 10 años y sencillo
- **AND** no reintroduce "escuelita"

### Requirement: Cierre de perfil y política de seguimiento por llamada

Al completar el perfil o cuando el candidato declara documentos listos, el sistema SHALL
indicar un siguiente paso claro y, ante una solicitud de llamada, SHALL fijar el estado/label
de lead correspondiente. La política de contacto SHALL evaluarse contra el horario de oficina
documentado **8:00–17:30, lunes a viernes**, en la zona canónica **`America/Mexico_City`**:
dentro del horario, el sistema SHALL indicar que el equipo puede dar seguimiento; fuera del
horario, SHALL indicar que el perfil quedó tomado en cuenta y ofrecer seguimiento dentro del
horario. El sistema SHALL NOT prometer una agenda real mientras no exista sistema de
agendación: SHALL usar "lo dejo registrado para que el equipo te contacte en horario de
atención" y SHALL NOT afirmar "ya quedó agendada tu llamada".

> Nota de implementación: doc-only. El horario operativo (8:00–17:30) vive hoy en
> `current_turn._profile_complete_closing` y en `app/knowledge/business_hours.py`. La ventana de
> `followup/ventana.py` (08:30–20:30, lunes–sábado) es para el **envío async de seguimientos**
> y NO debe confundirse con el horario de oficina. El label `llamada_pendiente` ya existe en
> el catálogo oficial; lo pendiente es emitirlo desde una decisión determinista y registrar
> `scheduling.call_requested`, `scheduling.call_status`, `scheduling.call_window_text` y
> `scheduling.call_window_valid`. El sistema NO debe afirmar que la llamada ya quedó agendada.

#### Scenario: Solicitud de llamada en horario de oficina
- **WHEN** el perfil está completo y el candidato pide una llamada dentro de 8:00–17:30 (`America/Mexico_City`, lunes a viernes)
- **THEN** el sistema indica que el equipo puede dar seguimiento por llamada
- **AND** deja registrado el estado/label de lead para contacto, sin afirmar que la llamada ya quedó agendada

#### Scenario: Solicitud de llamada fuera de horario
- **WHEN** el candidato pide una llamada fuera de 8:00–17:30 (`America/Mexico_City`)
- **THEN** el sistema indica que el perfil quedó tomado en cuenta y ofrece seguimiento dentro del horario
- **AND** no promete una hora agendada

### Requirement: Registro de documentos sin OCR

Cuando el candidato declara que ya subió o enviará documentos, el sistema SHALL agradecer y
registrar para revisión humana, SHALL dejar claro que la validación final la realiza el
equipo, y SHALL NOT afirmar que verificó o validó documentos de forma automática.

> Nota de implementación: requirement doc-only; consistente con la regla de media sin OCR.

#### Scenario: Candidato dice que ya subió todo
- **WHEN** el candidato dice "ya subí todo"
- **THEN** el sistema agradece y registra para revisión humana
- **AND** no afirma haber verificado los documentos automáticamente

### Requirement: No solicitar pagos ni datos sensibles fuera de flujo autorizado

El sistema SHALL NOT solicitar al candidato pagos, depósitos, números de cuenta bancaria,
CURP o NSS completos, comprobantes de pago ni otros datos administrativos sensibles fuera de
un flujo oficial autorizado, y SHALL NOT inventar trámites ni costos. Ante preguntas sobre
trámites con costo, comprobantes, cuentas o datos sensibles, el sistema SHALL derivar a
revisión humana o indicar que el equipo lo confirma por el canal autorizado.

> Nota de implementación: requirement doc-only; no se implementa en este cambio.

#### Scenario: Candidato pregunta por trámite con costo o datos sensibles
- **WHEN** el candidato pregunta por un trámite con costo, comprobante de pago, cuenta bancaria o CURP/NSS
- **THEN** el sistema no pide depósitos ni datos sensibles ni inventa trámites
- **AND** deriva a revisión humana o indica que el equipo lo confirma por el canal autorizado

### Requirement: Decisión operativa unificada (respuesta, nota y labels)

El sistema SHALL derivar la respuesta visible, la nota interna y las labels de una misma
decisión operativa por turno, calculada desde Postgres/lead_memory. La decisión SHALL
considerar el estado del perfil, la intención del candidato, el horario operativo, la
necesidad de llamada, la necesidad de humano y el bloqueo actual. La respuesta visible, la
acción sugerida, el bloqueo actual y las labels SHALL NOT contradecirse entre sí.

> Nota de implementación: doc-only; consistente con `postgres-truth-and-label-sync` y
> `candidate-profile-label-planner` de `multi-intent-migration`.

#### Scenario: Respuesta corta no desalinea la nota ni los labels
- **WHEN** el último mensaje es "5" y el campo pendiente era experiencia
- **THEN** la nota interna no dice "preguntó por documentos"
- **AND** la acción sugerida, el bloqueo actual y las labels son consistentes con "registró experiencia"

### Requirement: Voz de equipo — no referirse a Capital Humano como tercero

El sistema SHALL responder siempre con voz de equipo (primera persona plural: "nuestro
equipo", "aquí lo revisamos", "llámenos") y SHALL NOT referirse a "Capital Humano" como una
entidad o tercero separado, en cualquier modo de respuesta (plantilla, RAG o LLM amistoso).
Las instrucciones y ejemplos del prompt del sistema SHALL NOT inducir ese uso (sus ejemplos
no deben mostrar "Capital Humano" como tercero).

#### Scenario: Derivación a revisión humana usa voz de equipo
- **WHEN** el sistema deriva un tema a revisión humana o aclara que algo se valida después
- **THEN** la respuesta usa "nuestro equipo" / "aquí lo revisamos" / "llámenos"
- **AND** la respuesta no contiene "Capital Humano" como tercero

#### Scenario: El prompt del sistema no induce "Capital Humano"
- **WHEN** se construye el prompt del LLM (persona y/o contexto RAG)
- **THEN** las instrucciones y ejemplos del prompt no usan "Capital Humano" como tercero separado

### Requirement: Ciclo de vida de la revisión humana

El sistema SHALL NOT salir automáticamente del estado de revisión humana
(`HUMAN_REVIEW_REQUIRED`) por mensajes del candidato. Una conversación en revisión humana
SHALL permanecer en ese estado hasta una acción humana u operativa explícita que la libere,
tras lo cual el procesamiento normal MAY reanudarse. El sistema SHALL NOT dejar la
conversación en un bloqueo permanente sin ninguna vía de liberación.

#### Scenario: Mensaje del candidato no reactiva el bot durante revisión humana
- **WHEN** una conversación está en `HUMAN_REVIEW_REQUIRED` y el candidato envía un mensaje
- **THEN** el sistema mantiene el estado de revisión humana (no auto-reanuda el bot)

#### Scenario: Liberación explícita por acción humana
- **WHEN** un agente u operación libera explícitamente la conversación de la revisión humana
- **THEN** el sistema permite reanudar el procesamiento normal en los turnos posteriores

#### Scenario: No hay bloqueo permanente
- **WHEN** una conversación entra en `HUMAN_REVIEW_REQUIRED`
- **THEN** existe al menos una vía explícita (acción humana/operativa) para liberarla

### Requirement: Edad temprana con descarte desde 57 años

El funnel vivo SHALL preguntar la edad inmediatamente después de la ciudad. La
edad SHALL ser menor a 57 años; con 57 años o más, el sistema SHALL responder
el guion de descarte cortés aprobado y NO SHALL continuar el perfilamiento.

#### Scenario: 57 o más se descarta
- **WHEN** el candidato responde "tengo 57 años"
- **THEN** el bot responde el guion de descarte y no emite más preguntas del funnel

#### Scenario: Frontera exacta
- **WHEN** el candidato responde "tengo 57"
- **THEN** aplica el descarte (la regla es estrictamente menor a 57)

#### Scenario: Menor de 57 continúa
- **WHEN** el candidato responde "tengo 56 años"
- **THEN** el funnel continúa con la siguiente pregunta (tipo de unidad)

### Requirement: Preguntas de vencimiento en lugar de vigencia

El funnel SHALL preguntar "¿Cuándo vence su licencia?" y "¿Cuándo vence su apto
médico?" (no "¿está vigente?"), en turnos SEPARADOS: una pregunta de vigencia
por turno, nunca dos documentos en la misma pregunta. Un "sí" del candidato
NO SHALL validar más de un documento. Si el candidato afirma vigencia sin dar
fecha, el sistema SHALL repreguntar "¿En cuánto tiempo se le vence?" referida
al documento en cuestión.

#### Scenario: Vigente sin fecha provoca repregunta
- **WHEN** el bot preguntó cuándo vence la licencia y el candidato responde "sí, está vigente"
- **THEN** el bot repregunta "¿En cuánto tiempo se le vence su licencia?"

#### Scenario: Un sí no valida dos documentos
- **WHEN** el candidato responde "sí" a una pregunta que mencionara licencia y apto a la vez
- **THEN** el sistema no marca vigente ninguno de los dos sin su fecha/confirmación individual
  (el paso doble queda eliminado: la pregunta de apto llega en el turno siguiente)

### Requirement: Guion fijo de trámite para vencimiento corto

El sistema SHALL preguntar "¿Ya tiene el papel donde lo tramitó?" cuando la
licencia o el apto vence en menos de 3 meses o está vencido. Regla de negocio
(2026-06-12): con la renovación YA en proceso (papel de trámite), el documento
puede considerarse apto y el proceso continúa con `aclaracion_pendiente` para
validación de Capital Humano; SIN trámite en proceso, el documento NO es válido
y el sistema SHALL responder el guion fijo "Por el momento no podemos seguir
con su solicitud; en cuanto tenga el papel de trámite, continuamos", sin
desviarse ante la insistencia del candidato. La regla aplica igual a licencia
y a apto médico, cada uno evaluado por separado.

#### Scenario: Vence pronto sin trámite
- **WHEN** el apto vence en 18 días y el candidato dice que no ha tramitado la renovación
- **THEN** el bot responde el guion fijo y no avanza el funnel

#### Scenario: Vence pronto con trámite
- **WHEN** el candidato confirma que tiene el papel del trámite
- **THEN** el funnel continúa y se marca `aclaracion_pendiente`

#### Scenario: Insistencia no rompe el guion
- **WHEN** el candidato insiste en continuar sin documentos vigentes ni trámite
- **THEN** el bot repite el guion fijo sin ofrecer alternativas

### Requirement: Puente suave tras responder dudas

Cuando el candidato hace preguntas a media precalificación, el sistema SHALL
responder la duda completa y retomar el funnel con un puente suave ("Cuando
guste continuamos con su registro — me decía, ¿...?"), con máximo una pregunta
de funnel por turno.

#### Scenario: Duda de pago no interrumpe con brusquedad
- **WHEN** el candidato pregunta cuánto pagan en medio del perfilamiento
- **THEN** la respuesta resuelve la duda y retoma la pregunta pendiente con puente suave

### Requirement: El camino vivo aplica handoff ante vacante B1 / Estados Unidos

El camino vivo (`knowledge_orchestrator.handle_message`) SHALL marcar `requires_human` y
rutear a revisión humana cuando el candidato menciona una vacante B1, Estados Unidos,
cruce a EUA o ruta americana, mediante un guard determinista que NO depende del seed de
Neo4j. El bot SHALL NOT continuar perfilando como vacante estándar ni emitir juicio
("no es problema", aprobar o descartar). La regla aplica aunque Neo4j esté en fallback.

#### Scenario: Mención de vacante B1 → handoff vivo
- **WHEN** el candidato indica interés en una vacante B1 o para Estados Unidos
- **THEN** el contrato vivo resuelve `requires_human=true`
- **AND** el sistema no añade pregunta de funnel de perfilamiento estándar en ese turno

#### Scenario: Mención de cruce / ruta americana → handoff vivo
- **WHEN** el candidato menciona cruce a EUA, visa o ruta americana
- **THEN** el contrato vivo resuelve `requires_human=true`
- **AND** la respuesta canaliza a un reclutador humano sin emitir juicio de elegibilidad

#### Scenario: Handoff B1 sobrevive a Neo4j en fallback
- **WHEN** Neo4j no resuelve (fallback) y el candidato menciona vacante B1
- **THEN** el guard determinista igual marca `requires_human=true`

### Requirement: El camino vivo aplica handoff ante reingreso

El camino vivo SHALL marcar `requires_human` cuando el candidato indica haber trabajado
previamente con la empresa, mediante un guard determinista. El bot SHALL NOT aprobar ni
rechazar el reingreso automáticamente; solo registra y canaliza, pidiendo nombre completo
y motivo de salida. La señal de reingreso es distinta de "ya conseguí otro trabajo"
(dropoff), que no es reingreso.

#### Scenario: Candidato indica que ya trabajó en la empresa → handoff vivo
- **WHEN** el candidato indica que trabajó antes con la empresa o que quiere volver
- **THEN** el contrato vivo resuelve `requires_human=true`
- **AND** la respuesta no aprueba ni descarta el reingreso

#### Scenario: "Ya conseguí otro trabajo" no es reingreso
- **WHEN** el candidato dice que ya consiguió otro empleo (señal de abandono)
- **THEN** el contrato vivo NO lo trata como reingreso

### Requirement: El camino vivo marca experiencia no objetivo como escuelita

El camino vivo SHALL identificar torton, rabón, reparto local/interurbano y similares como
experiencia no-objetivo para la vacante principal. SHALL NOT confirmarlos como `full` ni
como `sencillo`. La experiencia no-objetivo SHALL canalizarse a valoración de Capital
Humano (señal de escuelita), no tomarse como experiencia directa en full/sencillo.

#### Scenario: Experiencia en torton → no confirma vehicle_type
- **WHEN** el candidato declara experiencia en torton/rabón/reparto
- **THEN** el sistema NO persiste `experience.vehicle_type` como `full` ni `sencillo`
- **AND** marca la experiencia como no-objetivo (escuelita / valoración humana)

### Requirement: El sistema no emite "caduca"/"caducidad" en la respuesta

El sistema SHALL usar `vence`/`vigencia`/`vencimiento` para referirse al vencimiento de
documentos médicos o de licencia, en cualquier modo de respuesta del camino vivo
(plantilla, RAG o LLM amistoso). SHALL NOT emitir `caduca` ni `caducidad` en la respuesta
al candidato.

#### Scenario: Respuesta sobre vigencia usa "vence", no "caduca"
- **WHEN** el sistema genera una respuesta sobre el vencimiento de licencia o apto médico
- **THEN** la respuesta usa `vence`, `vencimiento` o `vigencia`
- **AND** la respuesta no contiene `caduca` ni `caducidad`

### Requirement: Saludo oficial obligatorio en primer contacto

El sistema SHALL responder con el saludo oficial de Mundo (`GREETING_REPLY`) en
el primer contacto de una conversación (sin mensaje previo del asistente) cuando
el mensaje entrante es un saludo o una entrada de campaña/interés (p. ej. el
mensaje default de la publicación de Facebook "Me interesa la vacante de
operador de quinta rueda"). El current-turn guard NO SHALL aplicar su ack
("Perfecto, lo dejo registrado...") en ese turno.

#### Scenario: Entrada de campaña de Facebook
- **WHEN** el primer mensaje de la conversación es "Me interesa la vacante de operador de quinta rueda"
- **THEN** la respuesta es el saludo oficial de Mundo
- **AND** no contiene "lo dejo registrado"

#### Scenario: Primer mensaje con pregunta no usa el saludo forzado
- **WHEN** el primer mensaje es "me interesa la vacante, cuanto pagan?"
- **THEN** la entrada NO se trata como apertura de campaña (es pregunta) y sigue el flujo normal de respuesta

### Requirement: El interés en la vacante no es señal de perfil

El sistema NO SHALL tratar `candidate.vacancy_accepted` como señal de perfil del
current-turn guard: un mensaje cuyo único fact es el interés en la vacante no
dispara el ack de registro.

#### Scenario: Interés puro no dispara el guard
- **WHEN** el mensaje solo expresa interés ("me interesa la vacante de operador")
- **THEN** `has_current_turn_profile_signal` es falso y el guard no reemplaza la respuesta

### Requirement: Funnel como ciclo sobre la request completa

El sistema SHALL tratar el funnel como un ciclo: cada turno SHALL re-evaluar TODA la información
provista por el candidato (incluido lo enviado de golpe o fuera de orden) contra los campos
núcleo, y SHALL emitir únicamente la siguiente pregunta de un campo **no respondido o ambiguo**,
respetando lo ya confirmado y los turnos previos. SHALL NOT re-preguntar un dato ya dado ni
re-saludar. El orden de los campos es una guía, no una secuencia estricta.

#### Scenario: Mensaje con varios datos de golpe
- **WHEN** el candidato escribe "soy Juan, 35 años, operador full 10 años, todo en regla"
- **THEN** el sistema no re-pregunta nombre, edad, unidad ni experiencia
- **AND** pregunta solo lo pendiente/ambiguo (tipo de licencia, ciudad y la vigencia)

#### Scenario: No re-saludar
- **WHEN** el candidato saluda de nuevo en un turno posterior al primero
- **THEN** el sistema no repite la bienvenida y continúa con el campo pendiente

### Requirement: "Todo en regla" marca la vigencia como ambigua

El sistema SHALL tratar afirmaciones globales no específicas ("tengo todo en regla", "todo bien")
como **ambiguas** respecto a la vigencia de licencia y apto: SHALL NOT confirmar vigencia y SHALL
emitir la pregunta de vencimiento correspondiente.

#### Scenario: Afirmación global no confirma vigencia
- **WHEN** el candidato dice "tengo todo en regla"
- **THEN** el sistema no marca licencia ni apto como vigentes
- **AND** pregunta cuándo vence la licencia (o el apto) en turnos separados

### Requirement: Inferencia de unidad desde el tipo de licencia

El sistema SHALL usar el tipo de licencia para orientar la vacante: con licencia **B** SHALL
ofrecer sencillo ("¿quiere una vacante de sencillo?"); con licencia **E** SHALL ofrecer ambas
("¿le interesa una vacante de full o sencillo?"). Si el candidato pide full teniendo solo licencia
B, el sistema SHALL aclarar amablemente que con licencia B la vacante aplicable es sencillo.

#### Scenario: Licencia B ofrece sencillo
- **WHEN** el candidato confirma licencia tipo B
- **THEN** el sistema pregunta si quiere una vacante de sencillo

#### Scenario: Licencia E ofrece ambas
- **WHEN** el candidato confirma licencia tipo E
- **THEN** el sistema pregunta si le interesa full o sencillo

#### Scenario: B pidiendo full se aclara
- **WHEN** el candidato con licencia B dice que quiere full
- **THEN** el sistema aclara que con licencia B la vacante aplicable es sencillo

### Requirement: Documento laboral solicitado según residencia

El sistema SHALL ajustar la pregunta de documento laboral según la ciudad: para candidato local de
la ZM Laguna SHALL aceptar "cartas laborales o semanas cotizadas del IMSS"; para foráneo SHALL
exigir "2 cartas laborales membretadas". SHALL NOT pedir Infonavit. En la etapa de perfilamiento
SHALL pedir solo el documento laboral (INE/RFC/CURP/NSS se piden después de la validación).

#### Scenario: Local acepta IMSS
- **WHEN** el candidato es local de la ZM Laguna y se pregunta el documento
- **THEN** el sistema acepta cartas laborales o semanas cotizadas del IMSS

#### Scenario: Foráneo exige cartas membretadas
- **WHEN** el candidato es foráneo y se pregunta el documento
- **THEN** el sistema exige 2 cartas laborales membretadas

### Requirement: Bienvenida en la primera interacción

El sistema SHALL, solo en la primera interacción del candidato, dar la bienvenida, resolver una
duda si la trae, explicar que se hará una serie de preguntas para evaluar su candidatura (SHALL
NOT pedir documentación en este punto) y pedir el nombre por cortesía. Si el candidato trae una
duda, SHALL resolverla antes de iniciar el perfilamiento; resuelta, SHALL ofrecer continuar
("si le interesa la vacante, ¿podría…?").

#### Scenario: Primera interacción pide nombre
- **WHEN** es el primer mensaje del candidato
- **THEN** el sistema da la bienvenida, anuncia que hará preguntas y pide el nombre
- **AND** no pide documentación

#### Scenario: Duda inicial se resuelve antes de perfilar
- **WHEN** el primer mensaje del candidato es una duda del empleo
- **THEN** el sistema responde la duda y luego ofrece continuar con el perfilamiento

### Requirement: Cierre suave por vencimiento sin trámite

El sistema SHALL, cuando la licencia o el apto están vencidos y el candidato no cuenta con
comprobante de trámite/cita, dar un mensaje amable invitando a retomar cuando tenga el trámite,
detener el perfilamiento automático y canalizar a Capital Humano. El bot SHALL dejar de responder
sin anunciarlo, y la nota SHALL reflejar el motivo. Con comprobante de trámite, SHALL continuar
con `aclaracion_pendiente`.

#### Scenario: Vencido sin trámite cierra suave
- **WHEN** el candidato indica que su licencia está vencida y no la está tramitando
- **THEN** el sistema da el mensaje de retomar a futuro, deja de responder y canaliza a Capital Humano

#### Scenario: Vencido en trámite continúa
- **WHEN** el candidato indica licencia vencida pero con comprobante de cita/trámite
- **THEN** el sistema continúa el perfilamiento con `aclaracion_pendiente`

### Requirement: Canalización a Capital Humano entrega acuse específico por motivo

El sistema SHALL enviar al candidato un acuse público específico según el motivo de la
canalización a Capital Humano (handoff), y SHALL NOT dejar al candidato sin respuesta. Tras el
acuse el bot detiene el perfilamiento; el humano toma el caso. SHALL NOT suprimir la respuesta
pública solo por `requires_human`.

Mensajes por motivo (al menos):
- **reingreso**: solicita nombre completo y motivo de salida;
- **B1 / EUA**: indica que es una vía distinta a la vacante publicada (operador full/sencillo);
- **escuelita** (experiencia no-objetivo): indica que Capital Humano revisará si hay generación
  disponible;
- **cecati** (sin experiencia): orientación al CECATI;
- conducta grosera/riesgo o fuera de alcance: acuse de canalización.

#### Scenario: Handoff no deja al candidato en silencio
- **WHEN** un turno resulta en canalización a Capital Humano (`requires_human`)
- **THEN** el sistema envía un acuse público al candidato
- **AND** no suprime la respuesta por el solo hecho de `requires_human`

#### Scenario: Acuse de reingreso
- **WHEN** el motivo de canalización es reingreso
- **THEN** el acuse solicita nombre completo y motivo de salida

#### Scenario: Acuse de B1
- **WHEN** el motivo de canalización es B1/EUA
- **THEN** el acuse indica que es una vía distinta a la vacante publicada

### Requirement: Punto único de extracción antes de bifurcar

El sistema SHALL computar el `TurnExtraction` del mensaje **una sola vez al inicio del turno**,
antes de bifurcar entre el orquestador y el guard del worker, y ambos caminos SHALL consumir
ese mismo objeto. SHALL NOT re-extraer el mismo texto en múltiples puntos del turno.

#### Scenario: Una extracción por turno
- **WHEN** llega un mensaje del candidato
- **THEN** la extracción del turno se realiza una vez y su resultado alimenta funnel, nudge, ack, labels y persistencia

### Requirement: Autoridad única sobre la respuesta

El reply de cara al candidato SHALL decidirse sobre el `TurnExtraction` único, no por el orden
de ejecución de dos caminos. SHALL NOT existir un camino (guard) que pise incondicionalmente
el reply ya producido por otro (orquestador) tras una segunda extracción del mismo turno.

#### Scenario: Reply no depende de quién corre último
- **WHEN** un turno produce facts y una posible duda embebida
- **THEN** el reply se determina a partir del `TurnExtraction` único, de forma estable e independiente del orden interno de los componentes

### Requirement: Disponibilidad del LLM durante el procesamiento de un turno

El sistema SHALL procesar cada turno de candidato sin error de LLM siempre que al menos una
clave Groq válida esté disponible (`GROQ_API_KEY` o `GROQ_API_KEY_BACKUP`). Si la clave
primaria tiene la cuota agotada, el sistema SHALL recuperarse automáticamente usando la clave
de respaldo, sin retornar un error al candidato ni dejar el turno sin procesar.

#### Scenario: Turno procesado con clave primaria activa

- **WHEN** el worker procesa un turno y la clave primaria de Groq tiene cuota disponible
- **THEN** el turno se resuelve normalmente con la clave primaria; no hay impacto observable

#### Scenario: Turno procesado con fallback a clave de respaldo

- **WHEN** el worker procesa un turno y la clave primaria tiene cuota agotada
- **THEN** el sistema usa automáticamente la clave de respaldo y entrega la respuesta al
  candidato sin error visible; el turno se completa con `status: ok`

#### Scenario: Sin claves disponibles

- **WHEN** ambas claves Groq tienen la cuota agotada o no están configuradas
- **THEN** el worker registra el error en el log y la tarea Celery falla; el candidato no
  recibe respuesta en ese turno (comportamiento de fallo actual, sin degradación adicional)

### Requirement: Saludo único en primer contacto con pregunta embebida

En el primer contacto, cuando el mensaje del candidato trae una pregunta embebida (p. ej. "hola, me interesa la vacante, ¿qué necesito?"), la respuesta ensamblada SHALL contener el intro de saludo de Mundo **una sola vez**. El sistema MUST NOT concatenar la respuesta a la pregunta (que ya saluda) con el `GREETING_REPLY` completo (que vuelve a saludar): el nudge del funnel para un candidato sin nombre debe ser solo la pregunta del siguiente dato, sin repetir el intro.

#### Scenario: Primer mensaje con saludo y pregunta
- **WHEN** un candidato nuevo escribe "Hola buen día, me interesa la vacante, ¿qué necesito para que me contraten?"
- **THEN** la respuesta incluye el intro "Hola, soy Mundo del equipo de reclutamiento de Transmontes…" exactamente una vez
- **AND** cierra con una sola pregunta del funnel (p. ej. el nombre), sin un segundo bloque de saludo

#### Scenario: Nudge del funnel tras responder la pregunta embebida
- **WHEN** la respuesta a la pregunta embebida ya contiene el saludo y el sistema agrega el nudge del siguiente dato
- **THEN** el nudge es solo la pregunta faltante, no el `GREETING_REPLY` con intro

### Requirement: Respuesta de primer contacto concisa

La respuesta de primer contacto SHALL ser concisa y MUST NOT repetir la misma promesa (p. ej. "nuestro equipo lo contactará") múltiples veces en el mismo mensaje.

#### Scenario: Respuesta de bienvenida verbosa
- **WHEN** se compone la respuesta de primer contacto
- **THEN** la promesa de contacto del equipo aparece a lo sumo una vez
- **AND** el mensaje no repite frases equivalentes de cierre

### Requirement: Respuesta empática y personalizada ante negativa u objeción de un paso del funnel

El orquestador SHALL responder con un acuse empático y personalizado cuando el
candidato declina, dice no tener, o propone una alternativa a un requisito de un campo
núcleo del funnel (documento laboral, licencia, apto médico, experiencia, etc.), en
lugar de re-preguntar el mismo campo en seco o cerrar la conversación abruptamente.

El acuse MUST:
- Dirigirse al candidato por su **nombre de pila** derivado de `candidate.name`
  (primer token; "Joaquín Ramos" → "Joaquín"); si no hay nombre, omitir el vocativo
  sin fallar.
- Validar empáticamente la situación o la alternativa que el candidato aporta.
- Encuadrar el documento como requisito de **protocolo para su expediente**, sin
  presentarlo como un rechazo.
- Aclarar que **por lo pronto no se le exige** como condición bloqueante.
- Invitar a **retomar el proceso** en cuanto lo suba o resuelva su situación.

El acuse MUST NOT inventar umbrales (p. ej. un mínimo de años de experiencia), MUST
NOT prometer la vacante, y SHALL usar la voz "nuestro equipo" (nunca "Capital
Humano" como tercero). La pregunta de funnel correspondiente NO se repite en el
mismo turno; el sistema MAY marcar el campo como pendiente de envío
(`documents.submission_status = pending_candidate_will_send`, que deriva el label
`seguimiento`) y avanzar al siguiente paso del funnel.

Esta rama SHALL respetar las salidas terminales de dominio: una negativa que implique
no-aptitud (cecati/escuelita/reingreso/B1) cierra el funnel y canaliza, no entra en
esta rama de "retomar cuando suba el documento".

#### Scenario: No tiene cartas pero ofrece una alternativa
- **WHEN** el candidato (nombre "Joaquín Ramos") responde "no tengo cartas laborales, pero tengo videos de mis rutas en TikTok"
- **THEN** la respuesta lo nombra "Joaquín", valida su experiencia comprobable, explica que por protocolo los documentos del expediente deben ser los indicados, aclara que por lo pronto no se le piden como bloqueo, e invita a continuar en cuanto los suba
- **AND** no se repite la pregunta del documento en seco ni se promete la vacante

#### Scenario: Negativa simple a un requisito no bloquea el funnel
- **WHEN** el candidato dice no contar (todavía) con un documento de un paso del funnel, sin implicar no-aptitud
- **THEN** el campo se marca como pendiente de envío (`seguimiento`) y el funnel avanza al siguiente paso en lugar de quedarse en bucle

#### Scenario: Negativa que implica no-aptitud cierra y canaliza
- **WHEN** la negativa corresponde a una salida terminal de dominio (p. ej. sin experiencia en carretera → cecati/escuelita)
- **THEN** se cierra el perfilamiento y se canaliza con acuse específico, en lugar de la rama empática de "retomar cuando suba el documento"

#### Scenario: Sin nombre conocido, omite el vocativo
- **WHEN** el candidato objeta un requisito y aún no se conoce `candidate.name`
- **THEN** el acuse mantiene el tono empático pero sin nombre de pila, sin texto roto ni placeholder

### Requirement: Una no-respuesta de vencimiento se trata como dato faltante y no como confirmación de vigencia

El orquestador MUST NOT confirmar un documento como vigente ni eco-imprimir el
literal cuando el candidato responde a la pregunta de vencimiento de licencia o apto
médico con una no-respuesta o evasiva (por ejemplo: no sabría decirle, no sé, no me
acuerdo, al rato le digo). El sistema SHALL tratar ese vencimiento como dato
faltante: volver a pedirlo de forma breve, o —si la no-respuesta es una evasiva de
aplazamiento— aplicar la rama empática de objeción (marcar pendiente y avanzar) sin
re-preguntar en seco. Un texto de vencimiento que sí denota una fecha o plazo
(incluido uno aproximado como en dos años) o un estado de vigencia SHALL aceptarse
como válido y MUST NOT meter al candidato en bucle.

#### Scenario: "No sabría decirle" no se confirma como vigente
- **WHEN** el candidato responde al vencimiento del apto médico con "no sabría decirle"
- **THEN** la respuesta NO dice "apto médico vigente (no sabría decirle)" ni eco-imprime el literal, y el vencimiento del apto queda como dato faltante (se vuelve a pedir o se difiere por la rama de objeción)

#### Scenario: Vencimiento aproximado real se acepta
- **WHEN** el candidato responde "se me vence aproximadamente en dos años"
- **THEN** el vencimiento se acepta como válido (no se re-pregunta en bucle) y no se convierte en una fecha exacta inventada


### Requirement: Respuesta empática y personalizada ante negativa u objeción de un paso del funnel

El orquestador SHALL responder con un acuse empático y personalizado cuando el
candidato declina, dice no tener, o propone una alternativa a un requisito de un campo
núcleo del funnel (documento laboral, licencia, apto médico, experiencia, etc.), en
lugar de re-preguntar el mismo campo en seco o cerrar la conversación abruptamente.

El acuse MUST:
- Dirigirse al candidato por su **nombre de pila** derivado de `candidate.name`
  (primer token; "Joaquín Ramos" → "Joaquín"); si no hay nombre, omitir el vocativo
  sin fallar.
- Validar empáticamente la situación o la alternativa que el candidato aporta.
- Encuadrar el documento como requisito de **protocolo para su expediente**, sin
  presentarlo como un rechazo.
- Aclarar que **por lo pronto no se le exige** como condición bloqueante.
- Invitar a **retomar el proceso** en cuanto lo suba o resuelva su situación.

El acuse MUST NOT inventar umbrales (p. ej. un mínimo de años de experiencia), MUST
NOT prometer la vacante, y SHALL usar la voz "nuestro equipo" (nunca "Capital
Humano" como tercero). La pregunta de funnel correspondiente NO se repite en el
mismo turno; el sistema MAY marcar el campo como pendiente de envío
(`documents.submission_status = pending_candidate_will_send`, que deriva el label
`seguimiento`) y avanzar al siguiente paso del funnel.

Esta rama SHALL respetar las salidas terminales de dominio: una negativa que implique
no-aptitud (cecati/escuelita/reingreso/B1) cierra el funnel y canaliza, no entra en
esta rama de "retomar cuando suba el documento".

#### Scenario: No tiene cartas pero ofrece una alternativa
- **WHEN** el candidato (nombre "Joaquín Ramos") responde "no tengo cartas laborales, pero tengo videos de mis rutas en TikTok"
- **THEN** la respuesta lo nombra "Joaquín", valida su experiencia comprobable, explica que por protocolo los documentos del expediente deben ser los indicados, aclara que por lo pronto no se le piden como bloqueo, e invita a continuar en cuanto los suba
- **AND** no se repite la pregunta del documento en seco ni se promete la vacante

#### Scenario: Negativa simple a un requisito no bloquea el funnel
- **WHEN** el candidato dice no contar (todavía) con un documento de un paso del funnel, sin implicar no-aptitud
- **THEN** el campo se marca como pendiente de envío (`seguimiento`) y el funnel avanza al siguiente paso en lugar de quedarse en bucle

#### Scenario: Negativa que implica no-aptitud cierra y canaliza
- **WHEN** la negativa corresponde a una salida terminal de dominio (p. ej. sin experiencia en carretera → cecati/escuelita)
- **THEN** se cierra el perfilamiento y se canaliza con acuse específico, en lugar de la rama empática de "retomar cuando suba el documento"

#### Scenario: Sin nombre conocido, omite el vocativo
- **WHEN** el candidato objeta un requisito y aún no se conoce `candidate.name`
- **THEN** el acuse mantiene el tono empático pero sin nombre de pila, sin texto roto ni placeholder

### Requirement: Una no-respuesta de vencimiento se trata como dato faltante y no como confirmación de vigencia

El orquestador MUST NOT confirmar un documento como vigente ni eco-imprimir el
literal cuando el candidato responde a la pregunta de vencimiento de licencia o apto
médico con una no-respuesta o evasiva (por ejemplo: no sabría decirle, no sé, no me
acuerdo, al rato le digo). El sistema SHALL tratar ese vencimiento como dato
faltante: volver a pedirlo de forma breve, o —si la no-respuesta es una evasiva de
aplazamiento— aplicar la rama empática de objeción (marcar pendiente y avanzar) sin
re-preguntar en seco. Un texto de vencimiento que sí denota una fecha o plazo
(incluido uno aproximado como en dos años) o un estado de vigencia SHALL aceptarse
como válido y MUST NOT meter al candidato en bucle.

#### Scenario: "No sabría decirle" no se confirma como vigente
- **WHEN** el candidato responde al vencimiento del apto médico con "no sabría decirle"
- **THEN** la respuesta NO dice "apto médico vigente (no sabría decirle)" ni eco-imprime el literal, y el vencimiento del apto queda como dato faltante (se vuelve a pedir o se difiere por la rama de objeción)

#### Scenario: Vencimiento aproximado real se acepta
- **WHEN** el candidato responde "se me vence aproximadamente en dos años"
- **THEN** el vencimiento se acepta como válido (no se re-pregunta en bucle) y no se convierte en una fecha exacta inventada

### Requirement: Acuse personalizado por nombre de pila la primera vez
Cuando el nombre del candidato se conoce por primera vez en el turno (extraído de un documento por visión o respondido al funnel), el acuse del turno SHALL saludar con "Gracias, <nombre de pila>." una sola vez. En turnos posteriores, ya conocido el nombre, NO SHALL repetir el vocativo. Si no hay nombre disponible, el acuse SHALL omitir el vocativo sin fallar.

#### Scenario: Primera vez que se conoce el nombre
- **WHEN** el nombre es nuevo de este turno y hay un nombre de pila válido
- **THEN** el acuse comienza con "Gracias, <nombre>." seguido de la siguiente pregunta del funnel

#### Scenario: Nombre ya conocido en turnos posteriores
- **WHEN** el nombre ya estaba establecido antes de este turno
- **THEN** el acuse NO incluye el vocativo "Gracias, <nombre>."

#### Scenario: Sin nombre disponible
- **WHEN** no hay `candidate.name` disponible
- **THEN** el acuse usa el texto genérico sin vocativo y no falla

### Requirement: Pregunta de unidad sin redundancia
La pregunta del funnel para el tipo de unidad (cuando aún no se conoce la licencia) SHALL mencionar la disponibilidad de vacantes una sola vez y luego preguntar, sin repetir "full o sencillo" dos veces.

#### Scenario: Copy de unidad
- **WHEN** el funnel pregunta el tipo de unidad sin licencia conocida
- **THEN** el texto es "Le comento, actualmente tenemos vacantes para operador de tracto full y de sencillo. ¿En cuál tiene experiencia?" (una sola mención de full/sencillo)

### Requirement: Mundo no se presenta como Capital Humano
El system message del LLM de respuesta SHALL instruir a Mundo a hablar como parte del equipo de reclutamiento de Transmontes y a NUNCA presentarse al candidato como "Capital Humano". Las notas internas dirigidas al equipo ("Para Capital Humano") quedan fuera de este requisito.

#### Scenario: Saludo del LLM
- **WHEN** el LLM genera una respuesta de presentación o saludo
- **THEN** se identifica como Mundo del equipo de Transmontes y no como "asistente de Capital Humano"

#### Scenario: Intro público del primer reply
- **WHEN** se antepone el intro de presentación (`ASSISTANT_PUBLIC_INTRO`) al primer reply de una conversación
- **THEN** el texto identifica a Mundo como parte del equipo de Transmontes y NO como "asistente de Capital Humano"

### Requirement: Generación sin razonamiento truncado
Cuando el modelo de generación de respuestas es un modelo qwen *reasoning*, el sistema SHALL suprimir su modo de razonamiento (interruptor `/no_think`) para que la respuesta al candidato sea directa y completa, sin bloques de pensamiento ni respuestas truncadas dentro del razonamiento. La supresión SHALL estar condicionada al modelo (sin efecto en modelos no-qwen).

#### Scenario: Respuesta directa con qwen
- **WHEN** el generador es qwen y se produce una respuesta (friendly, RAG o embebida)
- **THEN** el candidato recibe la respuesta directa, sin `<think>` ni contenido de razonamiento, y sin truncarse

#### Scenario: Modelo no-qwen sin cambios
- **WHEN** el generador NO es un modelo qwen reasoning
- **THEN** no se aplica la supresión de razonamiento y el comportamiento no cambia

### Requirement: Respuesta embebida limpia
Cuando se produce una respuesta a la pregunta embebida de un mensaje compuesto (multi-intención), esta SHALL pasar por el mismo limpiador unificado que el resto de rutas, de modo que llegue sin artefactos de generación (bloque de razonamiento vacío, marcadores de blockquote).

#### Scenario: Sin artefactos en la respuesta embebida
- **WHEN** el generador emite un bloque de razonamiento vacío o marcadores de blockquote en la respuesta embebida
- **THEN** el limpiador unificado los elimina antes de enviar al candidato
