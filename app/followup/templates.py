"""Plantillas de mensajes de seguimiento por etapa e intento."""
from __future__ import annotations

from app.knowledge.business_hours import is_business_hours

# ---------------------------------------------------------------------------
# Etiquetas en español para Chatwoot
# ---------------------------------------------------------------------------

TEMPERATURA_DISPLAY: dict[str, str] = {
    "caliente":  "🔥 Caliente",
    "tibio":     "😊 Tibio",
    "enfriando": "🌤 Enfriando",
    "frio":      "❄️ Frío",
    "perdido":   "💤 Perdido",
}

ETAPA_DISPLAY: dict[str, str] = {
    "new":                    "Nuevo lead",
    "interested":             "Interesado",
    "vacancy_info_shared":    "Info de vacante compartida",
    "profile_hint_collected": "Perfil en captura",
    "documents_pending":      "Documentos pendientes",
    "documents_received":     "Documentos recibidos",
    "apto_pending_update":    "Apto médico por actualizar",
    "safety_review":          "Revisión de seguridad",
    "followup_pending":       "Seguimiento pendiente",
    "human_review":           "Revisión humana",
    "profile_ready":          "Perfil listo",
    "lost":                   "Perdido",
    "closed":                 "Cerrado",
}

ESTADO_TAREA_DISPLAY: dict[str, str] = {
    "pendiente":  "⏳ Pendiente",
    "enviado":    "✅ Enviado",
    "omitido":    "⏭ Omitido",
    "cancelado":  "🚫 Cancelado",
}

# Campos faltantes de perfil → texto natural para el candidato
_CAMPO_DISPLAY: dict[str, str] = {
    "ciudad":                    "ciudad o estado de residencia",
    "tipo de licencia":          "tipo de licencia federal (B o E)",
    "vigencia de licencia":      "vigencia de su licencia federal",
    "apto médico":               "apto médico vigente",
    "tipo de unidad: tracto full o sencillo": "tipo de unidad (tracto full o sencillo)",
    "cartas laborales":          "cartas laborales",
}

# ---------------------------------------------------------------------------
# Plantillas por etapa (lista indexada por intento, 0-based internamente)
# Placeholders: {nombre}, {campo_faltante}
# ---------------------------------------------------------------------------

_PLANTILLAS: dict[str, list[str]] = {
    "new": [
        "Hola {nombre}, ¿tuvo oportunidad de revisar la vacante de operador de tracto full o sencillo? "
        "Con gusto le cuento más sobre el proceso.",

        "Hola {nombre}, seguimos con la vacante disponible. "
        "¿Le interesa que continuemos con su registro?",

        "Hola {nombre}, este es nuestro último mensaje automático. "
        "Cuando guste retomar el proceso, aquí seguimos con gusto.",
    ],
    "interested": [
        "Hola {nombre}, ¿tuvo oportunidad de revisar la información que le compartimos? "
        "Para avanzar solo necesitamos unos datos.",

        "Hola {nombre}, para continuar su proceso de reclutamiento, "
        "¿me puede compartir un momento para terminar su perfil?",

        "Hola {nombre}, es nuestra última consulta automática. "
        "Si desea retomar su proceso, aquí le atendemos.",
    ],
    "vacancy_info_shared": [
        "Hola {nombre}, para avanzar su proceso solo necesito un par de datos. "
        "¿Me puede decir desde qué ciudad o estado nos escribe?",

        "Hola {nombre}, seguimos disponibles para continuar con su perfil. "
        "¿Tiene un momento para compartir sus datos?",

        "Hola {nombre}, último mensaje automático. "
        "Cuando guste retomar, aquí seguimos.",
    ],
    "profile_hint_collected": [
        "Hola {nombre}, quedamos pendientes de su {campo_faltante}. "
        "¿Le es posible compartirlo cuando tenga un momento?",

        "Hola {nombre}, para completar su perfil aún necesitamos su {campo_faltante}. "
        "¿Puede ayudarnos con ese dato?",

        "Hola {nombre}, último recordatorio automático sobre su {campo_faltante}. "
        "Cuando pueda, aquí le esperamos.",
    ],
    "documents_pending": [
        "Hola {nombre}, cuando tenga oportunidad, ¿puede compartir sus documentos "
        "para continuar con su proceso?",

        "Hola {nombre}, su perfil está casi listo. "
        "Solo necesitamos sus documentos para avanzar a la siguiente etapa.",

        "Hola {nombre}, último recordatorio automático sobre sus documentos. "
        "Cuando pueda, aquí le esperamos.",
    ],
    "apto_pending_update": [
        "Hola {nombre}, ¿ya pudo renovar su apto médico? "
        "Con eso podemos avanzar su proceso.",

        "Hola {nombre}, ¿hay alguna novedad con su apto médico? "
        "Estamos listos para continuar cuando lo tenga.",

        "Hola {nombre}, último aviso sobre el apto médico. "
        "Cuando lo renueve, con gusto retomamos.",
    ],
    "followup_pending": [
        "Hola {nombre}, aquí seguimos cuando guste retomar el proceso. Sin prisa.",

        "Hola {nombre}, solo pasamos a saludar. "
        "Si desea continuar su proceso, con gusto le atendemos.",

        "Hola {nombre}, este es nuestro último mensaje automático. "
        "Cuando quiera retomar, aquí seguimos.",
    ],
    # Flujo especial: profile_ready / human_review → coordinar llamada
    "profile_ready": [
        "Hola {nombre}, su información ya está lista para revisión. "
        "¿Le parece si le hacemos una llamada para platicar los detalles? "
        "¿En qué horario de lunes a sábado le viene mejor contestar?",

        "Hola {nombre}, seguimos pendientes de coordinar su llamada. "
        "¿Tiene disponibilidad esta semana para que le marquemos?",
    ],
    "human_review": [
        "Hola {nombre}, su perfil está listo para revisión. "
        "Para coordinar, ¿le parece si le hacemos una llamada? "
        "¿En qué horario de lunes a sábado está disponible para contestar?",

        "Hola {nombre}, aún tenemos su caso pendiente de llamada. "
        "¿Podría indicarnos un horario disponible esta semana para contactarle?",
    ],
}

# [NOTA] Las siguientes etapas existen en ETAPA_DISPLAY pero NO están en _PLANTILLAS:
#   - documents_received
#   - safety_review
# Cuando un lead llega a estas etapas, get_template() cae al fallback "followup_pending",
# que envía un mensaje genérico en lugar de uno apropiado para esa etapa.
# [MEJORA] Agregar plantillas específicas o excluirlas explícitamente del scheduler.

# Política de horario (decisión #15): dentro del horario de oficina hay personal,
# así que el equipo contacta al candidato — NO se le pide coordinar/agendar una
# llamada. Sólo fuera del horario aplica el copy de coordinación de llamada (que
# vive en _PLANTILLAS arriba). Variantes "en horario" para profile_ready/human_review:
_PLANTILLAS_EN_HORARIO: dict[str, list[str]] = {
    "profile_ready": [
        "Hola {nombre}, su información ya está lista para revisión. "
        "Nuestro equipo la revisa y se pondrá en contacto con usted dentro del "
        "horario de atención. No necesita hacer nada más por ahora.",

        "Hola {nombre}, seguimos con su proceso. Nuestro equipo le contactará "
        "dentro del horario de atención en cuanto avance la revisión.",
    ],
    "human_review": [
        "Hola {nombre}, su perfil está listo para revisión. Nuestro equipo lo "
        "revisa y se pondrá en contacto con usted dentro del horario de atención.",

        "Hola {nombre}, su caso sigue en revisión con nuestro equipo, que le "
        "contactará dentro del horario de atención. Gracias por su paciencia.",
    ],
}


def get_template(etapa: str, intento: int) -> str | None:
    """Devuelve el texto de plantilla para la etapa e intento dados (intento 1-based).

    Para las etapas de llamada (profile_ready / human_review), el copy depende del
    horario de oficina: dentro de horario el equipo contacta al candidato; fuera de
    horario se coordina una llamada (variantes en _PLANTILLAS).
    """
    if etapa in _PLANTILLAS_EN_HORARIO and is_business_hours():
        variantes = _PLANTILLAS_EN_HORARIO[etapa]
    else:
        variantes = _PLANTILLAS.get(etapa) or _PLANTILLAS.get("followup_pending", [])
    if not variantes:
        return None
    idx = min(intento - 1, len(variantes) - 1)
    return variantes[idx]


def render_template(
    plantilla: str,
    nombre: str | None,
    campo_faltante: str | None = None,
) -> str:
    """Interpola los placeholders de la plantilla."""
    nombre_display = nombre or "candidato"
    campo_display = _CAMPO_DISPLAY.get(campo_faltante or "", campo_faltante or "dato pendiente")
    return (
        plantilla
        .replace("{nombre}", nombre_display)
        .replace("{campo_faltante}", campo_display)
    )


def nota_horario_llamada(nombre: str | None, mensaje_candidato: str, etapa: str, telefono: str | None) -> str:
    """Nota interna para Chatwoot cuando el candidato indica su horario de disponibilidad."""
    etapa_label = ETAPA_DISPLAY.get(etapa, etapa)
    nombre_display = nombre or "Candidato"
    telefono_display = telefono or "No disponible"
    mensaje_seguro = (mensaje_candidato or "").strip()[:400]

    return (
        "📞 Disponibilidad para llamada\n\n"
        f"Candidato: {nombre_display}\n"
        f"Teléfono: {telefono_display}\n"
        f"Disponibilidad indicada: \"{mensaje_seguro}\"\n"
        f"Etapa: {etapa_label}\n\n"
        "Por favor coordinar llamada del equipo en el horario indicado."
    )
