"""Validation report and database import for an ExtractionResult."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from importers.noun_exam_pdf import EXPECTED_DAYS, EXPECTED_PAGES, ExtractionResult

DATASET_NAME = "NOUN 2026_2 E-EXAM DRAFT TIMETABLE \u2014 TEST DATASET"
DRAFT_NOTICE = ("The source document is labelled DRAFT. This dataset is a draft source dataset used for testing; it is not an "
                "approved or final institutional timetable.")


def build_report(r: ExtractionResult) -> dict:
    entries = r.entries
    reasons = Counter(x for e in entries for x in e.review_reasons)
    per_day = Counter(e.day_no for e in entries)
    sessions = sum(len(d.sessions) for d in r.days)
    day_problems = {d.day_no: d.review for d in r.days if d.review}
    all_sessions_ok = all(len(d.sessions) == 3 for d in r.days)
    crosscheck_ok = (r.crosscheck_token_count == len(entries)) if r.crosscheck_token_count is not None else None
    coverage_ok = (r.pages_total == EXPECTED_PAGES and r.pages_processed == EXPECTED_PAGES and len(r.days) == EXPECTED_DAYS
                   and sorted(d.day_no for d in r.days) == list(range(1, EXPECTED_DAYS + 1)) and all_sessions_ok
                   and not r.page_problems and crosscheck_ok is not False)
    return {
        "source_document": r.source_name, "source_sha256": r.source_sha256, "draft_notice": DRAFT_NOTICE,
        "pages_expected": EXPECTED_PAGES, "pages_total": r.pages_total, "pages_processed": r.pages_processed,
        "page_problems": {str(k): v for k, v in r.page_problems.items()},
        "days_expected": EXPECTED_DAYS, "days_identified": len(r.days), "sessions_identified": sessions,
        "entries_extracted": len(entries), "unique_course_codes": len({e.course_code for e in entries if e.course_code}),
        "batch_a_entries": sum(e.batch == "A" for e in entries), "batch_b_entries": sum(e.batch == "B" for e in entries),
        "noun_prefixed_entries": sum(e.noun_prefixed for e in entries),
        "missing_course_codes": sum(not e.course_code for e in entries),
        "missing_course_titles": sum(not e.course_title for e in entries),
        "needs_manual_review": sum(e.needs_review for e in entries), "review_reason_counts": dict(reasons),
        "entries_by_page": {str(k): v for k, v in sorted(r.entries_by_page.items())},
        "entries_by_day": {str(k): v for k, v in sorted(per_day.items())},
        "session_labels_by_day": {str(d.day_no): [s.label for s in d.sessions] for d in r.days},
        "day_problems": {str(k): v for k, v in day_problems.items()},
        "independent_token_count": r.crosscheck_token_count, "independent_count_matches": crosscheck_ok,
        "coverage_ok": coverage_ok,
        "imported": None, "duplicates_prevented": 0, "skipped_for_review": 0,
    }


def validation_status_for(report: dict) -> str:
    if not report.get("coverage_ok"):
        return "INVALID"
    if report.get("needs_manual_review") or report.get("missing_course_codes") or report.get("missing_course_titles"):
        return "NEEDS_REVIEW"
    return "VALID"
