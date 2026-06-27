"""Scheduler: dispara la ingesta automatica cada SYNC_INTERVAL_MIN minutos."""
from apscheduler.schedulers.background import BackgroundScheduler

from . import config, ingest

scheduler = BackgroundScheduler(daemon=True, timezone="America/Argentina/Buenos_Aires")


def _job():
    try:
        ingest.run_ingest(tipo="auto")
    except Exception:
        pass  # el error ya queda en sync_log y en ingest.status


def start():
    if scheduler.running:
        return
    scheduler.add_job(
        _job, "interval",
        minutes=config.SYNC_INTERVAL_MIN,
        id="ingest_auto", max_instances=1, coalesce=True,
    )
    scheduler.start()
