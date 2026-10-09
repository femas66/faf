from __future__ import annotations

import asyncio
import datetime
import os
import tempfile
import time
import pytest

from src.tools.base import ToolContext
from src.tools.cronjob_mgr import (
    CronJobItem,
    CronJobStore,
    CronJobWorker,
    CronJobTool,
    parse_duration_to_seconds,
    parse_schedule_string,
)


def test_parse_duration_to_seconds():
    assert parse_duration_to_seconds("30s") == 30
    assert parse_duration_to_seconds("15m") == 900
    assert parse_duration_to_seconds("2h") == 7200
    assert parse_duration_to_seconds("1d") == 86400
    assert parse_duration_to_seconds("10 jam") == 36000


def test_parse_schedule_string():
    now = datetime.datetime(2026, 10, 9, 10, 0, 0).astimezone()

    # In 15 minutes
    ts_in = parse_schedule_string("in 15m", from_dt=now)
    assert ts_in is not None
    assert ts_in == (now + datetime.timedelta(minutes=15)).timestamp()

    # Every 6 hours
    ts_every = parse_schedule_string("every 6h", from_dt=now)
    assert ts_every is not None
    assert ts_every == (now + datetime.timedelta(hours=6)).timestamp()

    # Daily at 12:00
    ts_daily = parse_schedule_string("daily at 12:00", from_dt=now)
    assert ts_daily is not None
    target_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
    assert ts_daily == target_dt.timestamp()

    # Cron 5 fields: every 30 minutes
    ts_cron = parse_schedule_string("*/30 * * * *", from_dt=now)
    assert ts_cron is not None
    # Next match after 10:00:00 is 10:30:00
    cron_dt = datetime.datetime.fromtimestamp(ts_cron).astimezone()
    assert cron_dt.minute == 30


@pytest.mark.asyncio
async def test_cronjob_store():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name

    try:
        store = CronJobStore(file_path=temp_path)
        job = CronJobItem(
            id="job-1",
            chat_id=12345,
            title="Test Job",
            schedule="every 30m",
            next_run_timestamp=time.time() + 1800,
            next_run_readable="Soon",
        )
        await store.add(job)

        fetched = await store.get("job-1")
        assert fetched is not None
        assert fetched.title == "Test Job"

        # List
        all_jobs = await store.list_all(chat_id=12345)
        assert len(all_jobs) == 1

        # Remove
        removed = await store.remove("job-1")
        assert removed is not None
        assert await store.get("job-1") is None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
async def test_cronjob_tool_crud():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name

    try:
        store = CronJobStore(file_path=temp_path)
        worker = CronJobWorker(store)
        tool = CronJobTool(store=store, worker=worker)
        ctx = ToolContext(chat_id=9999, user_id=9999)

        # 1. Create
        res_create = await tool.execute(
            ctx,
            action="create",
            job_id="rain-watch",
            title="Pemantau Hujan",
            schedule="every 30m",
            execution_type="agent_prompt",
            prompt="Periksa apakah akan hujan",
            trigger_policy={"mode": "conditional", "condition_prompt": "Hujan > 50%"},
        )
        assert res_create.success is True
        assert "rain-watch" in res_create.output

        # 2. List
        res_list = await tool.execute(ctx, action="list")
        assert res_list.success is True
        assert "rain-watch" in res_list.output

        # 3. Status
        res_status = await tool.execute(ctx, action="status", job_id="rain-watch")
        assert res_status.success is True
        assert "Pemantau Hujan" in res_status.output

        # 4. Pause & Resume
        res_pause = await tool.execute(ctx, action="pause", job_id="rain-watch")
        assert res_pause.success is True
        item = await store.get("rain-watch")
        assert item.is_active is False

        res_resume = await tool.execute(ctx, action="resume", job_id="rain-watch")
        assert res_resume.success is True
        item = await store.get("rain-watch")
        assert item.is_active is True

        # 5. Delete
        res_del = await tool.execute(ctx, action="delete", job_id="rain-watch")
        assert res_del.success is True
        assert await store.get("rain-watch") is None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
async def test_cronjob_worker_execution_and_cooldown():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name

    try:
        store = CronJobStore(file_path=temp_path)
        worker = CronJobWorker(store)

        job = CronJobItem(
            id="test-python",
            chat_id=123,
            title="Python Calc",
            schedule="every 1m",
            execution_type="python_code",
            python_code="result = 10 * 20",
            trigger_policy={"mode": "always", "cooldown_after_trigger": "10s"},
        )
        await store.add(job)

        # First tick: should trigger
        should_deliver, payload = await worker.execute_job_tick(job)
        assert should_deliver is True
        assert payload == "200"
        assert job.last_status == "triggered"

        # Update last_trigger_timestamp
        job.last_trigger_timestamp = time.time()

        # Second tick immediately: should be blocked by cooldown
        should_deliver_2, payload_2 = await worker.execute_job_tick(job)
        assert should_deliver_2 is False
        assert job.last_status == "cooldown_active"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
