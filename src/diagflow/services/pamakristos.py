"""
DiagFlow — Παμμακάριστος On-Call Scheduler

Manages the daily on-call rotation for Παμμακάριστος hospital.
On-call records are persisted in diagflow.db (availability table with
is_pamakristos_oncall=1).
"""

from datetime import date, timedelta

import structlog
import diagflow.db.diagflow_db as cfg_db

logger = structlog.get_logger(__name__)


class PamakristosScheduler:
    """
    Manages Παμμακάριστος on-call rotation.
    Reads/writes from diagflow.db — persists across server restarts.
    """

    async def get_oncall_diagnostician(self, target_date: date | None = None) -> dict | None:
        """Get the on-call diagnostician for Παμμακάριστος on a given date."""
        target = target_date or date.today()
        record = cfg_db.get_oncall_diagnostician(target.isoformat())

        if record:
            return {
                "date": record["date"],
                "diagnostician_id": record["diagnostician_id"],
                "diagnostician_name": record["diagnostician_name"],
                "source": "db",
            }

        # Hardcoded weekly schedule fallback
        weekday = target.weekday()
        schedule = {
            0: {"id": 59, "name": "Μπερέτης"},
            1: {"id": 61, "name": "Ανθίμου"},
            2: {"id": 97, "name": "Τριανταφύλλου"},
            3: {"id": 189, "name": "Λιόντος"},
            4: {"id": 14, "name": "Νάτσικα"}
        }

        if weekday in schedule:
            diag = schedule[weekday]
            return {
                "date": target.isoformat(),
                "diagnostician_id": diag["id"],
                "diagnostician_name": diag["name"],
                "source": "hardcoded_rule",
            }

        logger.info("pamakristos_oncall_not_set", date=target.isoformat())
        return None

    async def set_oncall_diagnostician(
        self,
        target_date: date,
        diagnostician_id: int,
        set_by: str = "system",
    ) -> dict:
        """Manually set the on-call diagnostician for a specific date."""
        # Clear existing on-call for this date
        for a in cfg_db.get_all_availability():
            if a["date"] == target_date.isoformat() and a["is_pamakristos_oncall"]:
                cfg_db.upsert_availability(
                    diagnostician_id=a["diagnostician_id"],
                    date=target_date.isoformat(),
                    status=a["status"],
                    is_pamakristos_oncall=False,
                    notes=a["notes"] or "",
                )

        cfg_db.upsert_availability(
            diagnostician_id=diagnostician_id,
            date=target_date.isoformat(),
            status="available",
            is_pamakristos_oncall=True,
        )

        diag = cfg_db.get_diagnostician(diagnostician_id)
        diag_name = diag["name"] if diag else "Άγνωστος"

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

    def set_manual_override_from_admin(self, override_data: dict):
        """Called by the admin route after writing to DB — no-op since we read from DB directly."""
        pass

    async def get_weekly_schedule(self, start_date: date | None = None) -> list[dict]:
        """Get the on-call schedule for a full week."""
        start = start_date or date.today()
        schedule = []
        for i in range(7):
            day = start + timedelta(days=i)
            oncall = await self.get_oncall_diagnostician(day)
            if oncall:
                schedule.append(oncall)
        return schedule
