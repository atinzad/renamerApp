from __future__ import annotations

from app.services.report_service import ReportService


class ReportFacade:
    def __init__(self, report_service: ReportService) -> None:
        self._report_service = report_service

    def preview(self, job_id: str) -> tuple[str | None, str | None]:
        try:
            return self._report_service.preview_report(job_id), None
        except RuntimeError as exc:
            return None, str(exc)

    def write(self, job_id: str) -> tuple[str | None, str | None]:
        try:
            return self._report_service.write_report(job_id), None
        except RuntimeError as exc:
            return None, str(exc)
