## 1. Configuración — extractor a modelo 8B

- [x] 1.1 En `.env`, cambiar `UNIFIED_EXTRACTOR_MODEL=llama-3.3-70b-versatile` →
      `UNIFIED_EXTRACTOR_MODEL=llama-3.1-8b-instant`.
- [x] 1.2 Añadir comentario en `.env` junto a la variable explicando que el extractor
      usa 8B para JSON T=0 y el LLM de respuesta usa 70B (conservar calidad conversacional).
- [x] 1.3 Verificar en logs del worker que aparece `Extractor model: llama-3.1-8b-instant`
      (o equivalente) tras rebuild. VERIFICADO: _EXTRACTOR_MODEL=llama-3.1-8b-instant.

## 2. Configuración — variables de historial y clave ORG2

- [x] 2.1 Añadir en `.env` (con valor y comentario): `GROQ_LLM_HISTORY_TURNS=6`
      (default conservador para no perder contexto del turno en curso).
- [x] 2.2 Añadir en `.env` la variable `GROQ_API_KEY_ORG2=` (vacía por defecto, con
      comentario indicando que debe ser de una organización Groq distinta a la primaria
      para obtener cuota TPD independiente).

## 3. Código — tercer nivel de fallback ORG2 en `app/indexer.py`

- [x] 3.1 En `_groq_with_fallback` (aprox. línea 740-773): añadir tercer bloque
      `except GroqRateLimitError` que intente con `org2_key` si está definida, antes
      de relanzar la excepción. Emitir log `[groq-fallback] BACKUP agotada, usando ORG2 — {fn_name}`.
- [x] 3.2 En `call_groq_llm` (aprox. línea 776): leer `GROQ_API_KEY_ORG2` del entorno
      y pasarlo a `_groq_with_fallback` como `org2_key`. Actualizar la llamada internamente
      sin cambiar la firma pública de `call_groq_llm`.
- [x] 3.3 En `call_groq_json` (aprox. línea 848): igual que 3.2 — leer `GROQ_API_KEY_ORG2`
      y pasarlo a `_groq_with_fallback`.
- [x] 3.4 Si existe `call_groq_with_system`, aplicar el mismo patrón que 3.2.
- [x] 3.5 Actualizar firma de `_groq_with_fallback` para aceptar `org2_key: str | None = None`
      como parámetro nuevo (al final, con default None para no romper callers existentes).

## 4. Código — truncado de historial en `call_groq_llm`

- [x] 4.1 Al inicio de `call_groq_llm`, leer `GROQ_LLM_HISTORY_TURNS` (int, default 6).
- [x] 4.2 El historial llega embebido en el string `prompt` como texto plano
      (el orquestador ya lo pre-formatea). El historial reciente en el orquestador ya
      está acotado a `messages[-4:]` (4 mensajes). Verificar si este tope es suficiente
      o si hay otro path que envíe historial más largo. Si el tope de 4 mensajes del
      orquestador ya es suficiente, documentar el hallazgo en un comentario en el código
      y marcar la tarea D3 como "reducida a documentación".
      RESULTADO: el orquestador acota a messages[-4:] con max 180 chars/msg. No hay
      historial creciente sin cota. Variable GROQ_LLM_HISTORY_TURNS documentada como
      disponible pero sin truncado adicional necesario.

## 5. Tests

- [x] 5.1 Añadir test `tests/test_groq_org2_fallback.py`:
      - Mockear `_groq_call`: primaria → `GroqRateLimitError`, backup → `GroqRateLimitError`,
        org2 → retorna `"ok"`. Verificar que `_groq_with_fallback` retorna `"ok"`.
      - Verificar que sin `org2_key` la excepción se propaga correctamente.
- [x] 5.2 Añadir test que verifica `call_groq_json` pasa `org2_key` desde el entorno a
      `_groq_with_fallback` (usar `mock.patch.dict(os.environ, {"GROQ_API_KEY_ORG2": "k3"})`).
- [x] 5.3 Test de regresión: `_groq_with_fallback` sin `org2_key` se comporta igual que
      antes (primaria ok → retorna; primaria falla + backup ok → retorna; ambas fallan → raise).
      8/8 tests passing.

## 6. Deploy

- [x] 6.1 `docker compose build worker api` — hornear cambios de `.env` y `app/indexer.py`.
- [x] 6.2 `docker compose up -d worker api`.
- [x] 6.3 Verificar en logs: `[groq] Extractor model: llama-3.1-8b-instant` (o equivalente).
      VERIFICADO en contenedor worker.
- [ ] 6.4 Enviar un turno de prueba y confirmar extracción correcta (ciudad, licencia, unidad)
      en la nota privada de Chatwoot.
- [ ] 6.5 Si la calidad de extracción es aceptable, cerrar el change. Si hay regresión,
      revertir `UNIFIED_EXTRACTOR_MODEL` a `llama-3.3-70b-versatile` en `.env` y rebuild.
