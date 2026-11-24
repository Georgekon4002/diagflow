"""
DiagFlow — Παμμακάριστος On-Call Scheduler

Manages the daily on-call rotation for Παμμακάριστος hospital.
On-call records are persisted in diagflow.db (availability table with
is_pamakristos_oncall=1).
"""

import asyncio
from datetime import date, timedelta

import structlog
import diagflow.db.diagflow_db as cfg_db

logger = structlog.get_logger(__name__)


class PamakristosScheduler:
    """
    Manages Παμμακάριστος on-call rotation.
    Reads/writes from diagflow.db — persists across server restarts.
    """

    def _get_oncall_sync(self, target_date: date | None = None) -> dict | None:
        target = target_date or date.today()
        record = cfg_db.get_oncall_diagnostician(target.isoformat())
        if record:
            return {
                "date": record["date"],
                "diagnostician_id": record["diagnostician_id"],
                "diagnostician_name": record["diagnostician_name"],
                "source": record.get("source", "override"),
            }
        logger.info("pamakristos_oncall_not_set", date=target.isoformat())
        return None

    async def get_oncall_diagnostician(self, target_date: date | None = None) -> dict | None:
        """Get the on-call diagnostician for Παμμακάριστος on a given date."""
        return await asyncio.to_thread(self._get_oncall_sync, target_date)

    def _set_oncall_sync(
        self,
        target_date: date,
        diagnostician_id: int,
        set_by: str = "system",
    ) -> dict:
        diag = cfg_db.get_diagnostician(diagnostician_id)
        if not diag:
            raise ValueError(f"Diagnostician {diagnostician_id} not found")

        rec = cfg_db.set_pamakristos_oncall_for_date(target_date.isoformat(), diagnostician_id)
        diag_name = rec.get("diagnostician_name") or diag["name"]

        logger.info(
            "pamakristos_oncall_set",
            date=target_date.isoformat(),
            diagnostician_id=diagnostician_id,
            diagnostician_name=diag_name,
            set_by=set_by,
        )

        return {
            "date": target_date.isoformat(),
            "diagnostician_id": diagnostician_id,
            "diagnostician_name": diag_name,
            "set_by": set_by,
            "status": "set",
        }

    async def set_oncall_diagnostician(
        self,
        target_date: date,
        diagnostician_id: int,
        set_by: str = "system",
    ) -> dict:
        """Atomically set the on-call diagnostician for a specific date."""
        return await asyncio.to_thread(self._set_oncall_sync, target_date, diagnostician_id, set_by)

    def set_manual_override_from_admin(self, override_data: dict):
        """Called by the admin route after writing to DB — no-op since we read from DB directly."""
        pass

    def _get_weekly_schedule_sync(self, start_date: date | None = None) -> list[dict]:
        start = start_date or date.today()
        overrides = {
            o["date"]: o
            for o in cfg_db.get_pamakristos_manual_overrides(from_date=start.isoformat())
        }
        weekly = {
            item["weekday"]: item
            for item in cfg_db.get_pamakristos_weekly_schedule_db()
        }
        schedule = []
        for i in range(7):
            day = start + timedelta(days=i)
            day_str = day.isoformat()
            if day_str in overrides:
                ov = overrides[day_str]
                schedule.append({
                    "date": day_str,
                    "diagnostician_id": ov["diagnostician_id"],
                    "diagnostician_name": ov["diagnostician_name"],
                    "source": "override",
                })
            elif day.weekday() not in (5, 6) and day.weekday() in weekly:
                wk = weekly[day.weekday()]
                schedule.append({
                    "date": day_str,
                    "diagnostician_id": wk["diagnostician_id"],
                    "diagnostician_name": wk["diagnostician_name"],
                    "source": "weekly_schedule",
                })
        return schedule

    async def get_weekly_schedule(self, start_date: date | None = None) -> list[dict]:
        """Get the on-call schedule for a full week in 2 batched queries instead of 14."""
        return await asyncio.to_thread(self._get_weekly_schedule_sync, start_date)
