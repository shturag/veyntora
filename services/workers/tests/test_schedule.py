from datetime import timedelta

from veyntora_workers.app import app


def test_phase0_jobs_are_scheduled() -> None:
    schedule = app.conf.beat_schedule
    assert schedule["identity-sync"]["schedule"] == timedelta(minutes=15)
    assert schedule["heartbeat"]["schedule"] < timedelta(seconds=90), "must refresh before TTL"
    assert {"veyntora.heartbeat", "veyntora.relay_outbox", "veyntora.identity_sync"} <= set(
        app.tasks.keys()
    )
