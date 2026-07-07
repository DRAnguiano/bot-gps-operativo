## REMOVED Requirements

> Capability completa SUPERSEDED (decisión del usuario 2026-07-07, open question 2
> del design resuelta): el clasificador shadow era código huérfano (ningún caller en
> el camino vivo) y el entendimiento del turno se consolida en el extractor unificado
> (`turn_intent_classifier` + `conversational_purpose`, capability
> `conversational-purpose-extraction`). Las reglas de NEGOCIO que estos requirements
> mencionan (B1→humano, reingreso, escuelita/CECATI, léxico de vigencia, no-OCR,
> ZML por catálogo) NO se des-contratan: siguen vigentes en `message-orchestration`,
> `profile-extraction` y `chatwoot-label-taxonomy`, y en el código determinista de
> overrides. El harness QA de la matriz de 72 casos se repunta al extractor
> unificado (gate 4.2 de este change). `business_route_schema` (catálogo
> VALID_VEHICLE_TYPES) se conserva — lo consume chatwoot_note_sync.

### Requirement: El clasificador separa intent conversacional de ruta de negocio

### Requirement: Extracción explícita de vehicle_type solo cuando es literal

### Requirement: Jerga ambigua de quinta rueda NO produce vehicle_type

### Requirement: Experiencia no objetivo (torton/rabón/reparto) → señal escuelita

### Requirement: Sin experiencia en carretera → señal CECATI solamente

### Requirement: Vacante B1 / Estados Unidos requiere humano

### Requirement: Reingreso requiere verificación humana

### Requirement: El shadow classifier no muta estado productivo

### Requirement: Todo fact y señal requiere evidencia literal

### Requirement: Lenguaje de vigencia — prohibición de "caduca"/"caducidad"

### Requirement: Documentos/imágenes — sin OCR, sin inferir facts

### Requirement: Multi-intent — pago + pagarés + rutas en un solo mensaje

### Requirement: Queja con interés laboral → señal complaint_with_candidate_interest

### Requirement: Referido — candidato que menciona a un tercero

### Requirement: Policy router SHALL producir resultados deterministas

### Requirement: El clasificador acepta contexto de perfil sin mutar estado

### Requirement: Solicitud genérica de información sobre vacante → vacante_info_general

### Requirement: Pregunta logística con multimedia → travel_logistics + multimedia_no_ocr, sin vehicle_type_ambiguous

### Requirement: vehicle_type_ambiguous solo para términos vehiculares del catálogo

### Requirement: Pregunta contextual pendiente → answer_or_clarify_current_question_first

### Requirement: Validación general de catálogos sobre el output del LLM

### Requirement: business_shadow_status independiente de la validación semántica

### Requirement: is_local_laguna deriva del catálogo ZML, no de lista hardcodeada
