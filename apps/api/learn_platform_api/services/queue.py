from datetime import timedelta

from redis import Redis
from rq import Queue

from learn_platform_api.settings import Settings


def enqueue_ingestion_job(settings: Settings, job_id: str, delay_seconds: int = 0) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        queue = Queue(settings.ingestion_queue_name, connection=connection)
        if delay_seconds > 0:
            queue.enqueue_in(
                timedelta(seconds=delay_seconds),
                "learn_platform_api.workers.run_ingestion_job",
                job_id,
            )
        else:
            queue.enqueue("learn_platform_api.workers.run_ingestion_job", job_id)
    finally:
        connection.close()


def enqueue_course_generation_job(settings: Settings, job_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.course_generation_queue_name, connection=connection).enqueue(
            "learn_platform_api.course_workers.run_course_generation_job", job_id
        )
    finally:
        connection.close()


def enqueue_workspace_deletion_job(settings: Settings, job_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.workspace_deletion_queue_name, connection=connection).enqueue(
            "learn_platform_api.workspace_workers.run_workspace_deletion_job", job_id
        )
    finally:
        connection.close()


def enqueue_tutor_turn(settings: Settings, turn_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.tutor_queue_name, connection=connection).enqueue(
            "learn_platform_api.tutor_workers.run_tutor_turn", turn_id
        )
    finally:
        connection.close()


def enqueue_tutor_session_deletion(settings: Settings, session_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.tutor_queue_name, connection=connection).enqueue(
            "learn_platform_api.tutor_workers.cleanup_tutor_session", session_id
        )
    finally:
        connection.close()


def enqueue_practice_job(settings: Settings, job_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.practice_queue_name, connection=connection).enqueue(
            "learn_platform_api.practice_workers.run_practice_job",
            job_id,
            # RQ defaults to 180 seconds, but one Practice generation may
            # legitimately span several bounded provider/tool attempts. The
            # worker's own wall budget remains authoritative; RQ only gets a
            # small grace period to persist the controlled terminal state.
            job_timeout=max(
                settings.practice_generation_max_wall_seconds,
                settings.practice_grading_max_wall_seconds,
            ) + 60,
        )
    finally:
        connection.close()


def enqueue_practice_set_deletion(settings: Settings, set_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.practice_queue_name, connection=connection).enqueue(
            "learn_platform_api.practice_workers.cleanup_practice_set", set_id
        )
    finally:
        connection.close()


def enqueue_learning_recompute(settings: Settings, job_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.practice_queue_name, connection=connection).enqueue(
            "learn_platform_api.practice_workers.run_learning_recompute", job_id
        )
    finally:
        connection.close()


# Slice 4: Code lab queue


def enqueue_code_lab_job(settings: Settings, job_id: str) -> None:
    connection = Redis.from_url(settings.redis_url)
    try:
        Queue(settings.code_lab_queue_name, connection=connection).enqueue(
            "learn_platform_api.code_lab_workers.run_code_lab_job", job_id
        )
    finally:
        connection.close()
