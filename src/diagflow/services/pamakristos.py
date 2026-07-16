"""
DiagFlow — Παμακάριστος On-Call Scheduler

Manages the daily on-call rotation for Παμακάριστος hospital urgent requests.
Each day, one diagnostician is designated as the on-call diagnostician for
Παμακάριστος — all urgent requests from that hospital go to them.

The rotation can be:
- Manual (set via the dashboard or API)
- Automatic (round-robin based on availability)
"""

from datetime import date, timedelta

import structlog

logger = structlog.get_logger(__name__)


class PamakristosScheduler:
    """
    Manages Παμακάριστος on-call rotation.

    TODO: Connect to diagnostician_availability table when DB access is available.
    Currently uses mock data.
    """

    # Mock on-call schedule (diagnostician_id per date)
    MOCK_ONCALL_SCHEDULE = {
        # Rotate through diagnosticians who accept LAB-PAM
        # (ids 3 and 5 have LAB-PAM in their accepted labs)
    }

    _manual_override: dict | None = None

    async def get_oncall_diagnostician(self, target_date: date | None = None) -> dict | None:
        """
        Get the on-call diagnostician for Παμακάριστος on a given date.

        Args:
            target_date: The date to check (defaults to today)

        Returns:
            Dict with diagnostician info, or None if not set
        """
        target = target_date or date.today()

        # Check for manual override first
        if self._manual_override and self._manual_override.get("date") == target.isoformat():
            return {
                "date": target.isoformat(),
                "diagnostician_id": self._manual_override["diagnostician_id"],
                "diagnostician_name": self._manual_override["diagnostician_name"],
                "source": "manual_override",
            }

        # TODO: Query diagnostician_availability where is_pamakristos_oncall = True
        # For now, use a simple round-robin between eligible diagnosticians

        # Mock: IDs 3 (Παπαδόπουλος) and 5 (Δημητρίου) accept LAB-PAM
        eligible_ids = [3, 5]
        day_index = (target - date(2026, 1, 1)).days
        oncall_id = eligible_ids[day_index % len(eligible_ids)]

        mock_names = {3: "Παπαδόπουλος Γ.", 5: "Δημητρίου Ε."}

        result = {
            "date": target.isoformat(),
            "diagnostician_id": oncall_id,
            "diagnostician_name": mock_names.get(oncall_id, "Unknown"),
            "source": "auto_rotation",  # or "manual_override"
        }

        logger.info(
            "pamakristos_oncall",
            date=target.isoformat(),
            diagnostician=result["diagnostician_name"],
        )

        return result

    async def set_oncall_diagnostician(
        self,
        target_date: date,
        diagnostician_id: int,
        set_by: str = "system",
    ) -> dict:
        """
        Manually set the on-call diagnostician for a specific date.

        Args:
            target_date: The date to set
            diagnostician_id: The diagnostician to assign
            set_by: Who set it (for audit)

        Returns:
            Confirmation dict
        """
        # TODO: Write to diagnostician_availability table

        logger.info(
            "pamakristos_oncall_set",
            date=target_date.isoformat(),
            diagnostician_id=diagnostician_id,
            set_by=set_by,
        )

        mock_names = {3: "Παπαδόπουλος Γ.", 5: "Δημητρίου Ε."}
        # In a real app we'd query the DB for the name
        self._manual_override = {
            "diagnostician_id": diagnostician_id,
            "diagnostician_name": mock_names.get(diagnostician_id, "Χειροκίνητη Ανάθεση"),
            "date": target_date.isoformat()
        }

        return {
            "date": target_date.isoformat(),
            "diagnostician_id": diagnostician_id,
            "set_by": set_by,
            "status": "set",
        }

    def set_manual_override_from_admin(self, override_data: dict):
        """Helper to sync admin state for mocks"""
        self._manual_override = override_data

    async def get_weekly_schedule(self, start_date: date | None = None) -> list[dict]:
        """
        Get the on-call schedule for a full week.

        Args:
            start_date: Start of the week (defaults to today)

        Returns:
            List of daily on-call assignments
        """
        start = start_date or date.today()
        schedule = []

        for i in range(7):
            day = start + timedelta(days=i)
            oncall = await self.get_oncall_diagnostician(day)
            if oncall:
                schedule.append(oncall)

        return schedule
