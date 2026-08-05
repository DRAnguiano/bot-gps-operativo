import os

from celery import Celery
from celery.schedules import crontab


def _redis_url() -> str:
    return (
        os.getenv("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://chatwoot_redis:6379/1"
    )


celery_app = Celery(
    "hr_capital_humano",
    broker=_redis_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND", _redis_url()),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=os.getenv("TZ", "America/Monterrey"),
    enable_utc=True,
    task_default_queue="inbound",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Programación periódica
    beat_schedule={
        # Crea tareas para leads enfriando/fríos — cada 15 min
        "programar-seguimientos": {
            "task": "seguimiento.programar_tareas",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "inbound"},
        },
        # Despacha mensajes pendientes dentro de la ventana — cada 5 min
        "enviar-seguimientos-pendientes": {
            "task": "seguimiento.enviar_pendientes",
            "schedule": crontab(minute="*/5"),
            "options": {"queue": "inbound"},
        },
        # Purga de expedientes por retención (LFPDPPP, expediente B2) — diaria 03:00
        "purgar-expedientes-retencion": {
            "task": "expediente.purga_retencion",
            "schedule": crontab(hour="3", minute="0"),
            "options": {"queue": "inbound"},
        },
    },
    # El beat guarda su estado en Redis para sobrevivir reinicios
    beat_scheduler="celery.beat:PersistentScheduler",
)
