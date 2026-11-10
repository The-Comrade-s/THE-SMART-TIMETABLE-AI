"""Positional extractor for the NOUN 2026_2 E-EXAM draft timetable PDF.

Method: the PDF is a table of three (course code, course title) column pairs per examination day. Text is read with
pdfplumber WITH coordinates, then assigned to cells by x position (column borders at x = 165, 347, 389, 595, 640),
to examination days by the day label at the left edge, and to sessions by the time header printed above each day.
Plain text extraction is not used for assignment because reading order mixes the columns and misplaces the time rows.

Nothing is corrected or invented: course codes and titles are kept exactly as printed (only runs of whitespace are
collapsed). Anything unclear is flagged for manual review and stays linked to its PDF page.
"""
from __future__ import annotations

import calendar
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, time
from typing import Callable, Dict, List, Optional

import pdfplumber

EXPECTED_PAGES = 8
EXPECTED_DAYS = 16
COL_RANGES = ((0, 347), (347, 595), (595, 10_000))       # x ranges of the three column pairs
CODE_X = (120.0, 348.0, 597.0)                            # left edge of the code text in each column
CODE_TOL = 5.0
CLIP_MARGIN = (347 - 8, 595 - 8, 842 - 30)                # a title ending this close to the cell border may be clipped

TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(am|pm)$", re.I)
LABEL_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+day),\s+(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+),\s+(\d{4})$")
CODE_RE = re.compile(r"^(NOUN-)?[A-Z]{2,4}\d{3}(-[AB])?$")
BATCH_TITLE_RE = re.compile(r"\s-\s*Batch\s+([AB])\s*$")
BATCH_CODE_RE = re.compile(r"-([AB])$")
MONTHS = {m: i for i, m in enumerate(calendar.month_name) if m}
DAYNAMES = {n: i for i, n in enumerate(calendar.day_name)}


@dataclass
class ExtractedSession:
    slot: int                 # 1..3 (column order on the page)
    label: str                # exactly as printed, for example 8:30am
    start: time


@dataclass
class ExtractedDay:
    day_no: int
    weekday: str
    exam_date: Optional[date]
    date_text: str            # as printed
    page_no: int
    sessions: List[ExtractedSession] = field(default_factory=list)
    review: List[str] = field(default_factory=list)


@dataclass
class ExtractedEntry:
    page_no: int
    day_no: int
    slot: int
    session_label: str
    session_start: time
    column_index: int         # 0..2
    row_in_column: int        # 1-based order inside the cell column
    course_code: str          # exactly as printed ("" when missing)
    course_title: str         # exactly as printed ("" when missing)
    batch: Optional[str]      # "A", "B" or None (not a batch course)
    noun_prefixed: bool
    base_code: str            # code without the NOUN- prefix (reference only; records are never merged)
    review_reasons: List[str] = field(default_factory=list)
    informational: List[str] = field(default_factory=list)
    wrapped_lines: int = 0

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)

    def record_key(self, source_sha: str) -> str:
        raw = f"{source_sha}|{self.day_no}|{self.slot}|{self.column_index}|{self.row_in_column}|{self.course_code}|{self.course_title}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class ExtractionResult:
    source_name: str
    source_sha256: str
    pages_total: int
    pages_processed: int
    page_problems: Dict[int, str]
    days: List[ExtractedDay]
    entries: List[ExtractedEntry]
    legend: Dict[str, dict]           # DAYS_1_8 / DAYS_9_16 -> {"first_day", "last_day", "text"}
    header_lines: List[str]
    entries_by_page: Dict[int, int] = field(default_factory=dict)
    crosscheck_token_count: Optional[int] = None      # independent count of code-like tokens in the plain page text

    def group_for_day(self, day_no: int) -> Optional[str]:
        for code, g in self.legend.items():
            if g["first_day"] <= day_no <= g["last_day"]:
                return code
        return None


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_time(label: str) -> Optional[time]:
    m = TIME_RE.match(label.strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return time(hour, minute) if hour < 24 and minute < 60 else None


def _cluster_lines(words: List[dict], tol: float = 3.0) -> List[List[dict]]:
    lines: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lines]


def _col_of(x0: float) -> int:
    return 0 if x0 < COL_RANGES[0][1] else (1 if x0 < COL_RANGES[1][1] else 2)


def _clean(words: List[dict]) -> str:
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in words)).strip()


def extract_noun_exam_pdf(path: str, progress: Optional[Callable[[int, int, str], None]] = None) -> ExtractionResult:
    sha = sha256_of(path)
    days: List[ExtractedDay] = []
    entries: List[ExtractedEntry] = []
    problems: Dict[int, str] = {}
    legend: Dict[str, dict] = {}
    header_lines: List[str] = []
    by_page: Dict[int, int] = {}
    processed = 0
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, start=1):
            if progress:
                progress(page_no - 1, total, f"Reading page {page_no} of {total}")
            try:
                page_days, page_entries, page_legend, page_header = _extract_page(page, page_no)
                days.extend(page_days)
                entries.extend(page_entries)
                legend.update(page_legend)
                if page_no == 1:
                    header_lines = page_header
                by_page[page_no] = len(page_entries)
                if not page_days:
                    problems[page_no] = "No examination day was recognised on this page."
                else:
                    processed += 1
            except Exception as exc:  # noqa: BLE001 - reported per page, never hidden
                problems[page_no] = f"Page could not be processed ({type(exc).__name__}: {exc})"
        if progress:
            progress(total, total, "Extraction finished")
    result = ExtractionResult(path.replace("\\", "/").split("/")[-1], sha, total, processed, problems, days, entries,
                              legend, header_lines, by_page)
    _post_checks(result)
    try:
        result.crosscheck_token_count = crosscheck_token_count(path)
    except Exception:  # noqa: BLE001 - the cross-check is a verification aid only
        result.crosscheck_token_count = None
    return result


_TOKEN_RE = re.compile(r"(?<![\w-])((?:NOUN-)?[A-Z]{2,4}\d{3}(?:-[AB])?)(?![\w-])")


def crosscheck_token_count(path: str) -> int:
    """Independent verification: count code-shaped tokens in the plain text of every page (no geometry involved)."""
    with pdfplumber.open(path) as pdf:
        return sum(len(_TOKEN_RE.findall(page.extract_text() or "")) for page in pdf.pages)


def _extract_page(page, page_no: int):
    words = [w for w in page.extract_words(extra_attrs=["size", "fontname"]) if w["top"] > 50 or page_no >= 1]
    header = _clean([w for w in words if w["top"] < 50])
    body = [w for w in words if w["top"] >= 50 and w["size"] < 7.5]

    # ---- legend lines ("DAY 1 TO 8 ..." / "DAY 9 TO 16 ...") --------------------------------------------------
    legend: Dict[str, dict] = {}
    legend_ys: List[float] = []
    for line in _cluster_lines([w for w in body if w["x0"] < 112]):
        txt = _clean(line)
        m = re.match(r"^DAY (\d+) TO (\d+)$", txt)
        if m:
            y = line[0]["top"]
            legend_ys.append(y)
            first, last = int(m.group(1)), int(m.group(2))
            text = _clean([w for w in body if abs(w["top"] - y) <= 3 and w["x0"] >= 112])
            legend[f"DAYS_{first}_{last}"] = {"first_day": first, "last_day": last, "text": text, "page_no": page_no}
    body = [w for w in body if not any(abs(w["top"] - y) <= 3 for y in legend_ys)]

    # ---- time headers and day labels -------------------------------------------------------------------------
    time_rows: Dict[float, Dict[int, str]] = {}
    for w in body:
        if TIME_RE.match(w["text"]) and w["x0"] > 150:
            key = next((k for k in time_rows if abs(k - w["top"]) <= 2), w["top"])
            time_rows.setdefault(key, {})[_col_of(w["x0"])] = w["text"]
    labels = []
    for line in _cluster_lines([w for w in body if w["x0"] < 112 and not TIME_RE.match(w["text"])]):
        txt = _clean(line)
        m = LABEL_RE.match(txt)
        if m:
            labels.append((line[0]["top"], txt, m))
    day_blocks = []
    for ly, txt, m in sorted(labels, key=lambda t: t[0]):
        ty = max((k for k in time_rows if k <= ly + 1 and ly - k <= 20), default=None)
        day_blocks.append((ty if ty is not None else ly - 8, ly, txt, m, time_rows.get(ty, {})))
    page_days: List[ExtractedDay] = []
    page_entries: List[ExtractedEntry] = []
    for i, (ty, ly, txt, m, times) in enumerate(day_blocks):
        day_no, weekday, dnum, month, year = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4), int(m.group(5))
        review: List[str] = []
        try:
            d = date(year, MONTHS[month], dnum)
            if d.weekday() != DAYNAMES.get(weekday, -1):
                review.append(f"Printed weekday {weekday} does not match the calendar date")
        except (KeyError, ValueError):
            d = None
            review.append("Date could not be interpreted")
        ed = ExtractedDay(day_no, weekday, d, re.sub(r"^\d+\s+", "", txt), page_no, review=review)
        for col in sorted(times):
            t = parse_time(times[col])
            if t is None:
                ed.review.append(f"Session time {times[col]!r} could not be interpreted")
                continue
            ed.sessions.append(ExtractedSession(col + 1, times[col], t))
        if len(ed.sessions) != 3:
            ed.review.append(f"{len(ed.sessions)} session times found instead of 3")
        page_days.append(ed)
        y_end = day_blocks[i + 1][0] if i + 1 < len(day_blocks) else 10_000
        block = [w for w in body if ty + 1 < w["top"] < y_end - 1 and w["x0"] >= 112
                 and not (w["fontname"].endswith("Bold") and w["text"] in ("Course", "Code", "Title", "DayDate", "Day", "Date"))
                 and not TIME_RE.match(w["text"])]
        page_entries.extend(_entries_for_block(block, ed, page_no))
    return page_days, page_entries, legend, [header] if header else []


def _entries_for_block(block: List[dict], day: ExtractedDay, page_no: int) -> List[ExtractedEntry]:
    out: List[ExtractedEntry] = []
    sessions = {s.slot: s for s in day.sessions}
    for col in range(3):
        words = [w for w in block if _col_of(w["x0"]) == col]
        current: Optional[ExtractedEntry] = None
        last_top = None
        row = 0
        title_ends: Dict[int, float] = {}
        for line in _cluster_lines(words):
            code_word = next((w for w in line if abs(w["x0"] - CODE_X[col]) <= CODE_TOL), None)
            rest = [w for w in line if w is not code_word]
            sess = sessions.get(col + 1)
            if code_word is not None:
                row += 1
                code = code_word["text"]
                current = ExtractedEntry(page_no, day.day_no, col + 1, sess.label if sess else "", sess.start if sess else time(0), col,
                                         row, code, _clean(rest), None, code.startswith("NOUN-"), code[5:] if code.startswith("NOUN-") else code)
                if sess is None:
                    current.review_reasons.append("No session time is printed for this column")
                out.append(current)
                title_ends[id(current)] = max((w["x1"] for w in rest), default=0.0)
            elif current is not None and last_top is not None and line[0]["top"] - last_top <= 10:
                current.course_title = (current.course_title + " " + _clean(line)).strip()
                current.wrapped_lines += 1
                title_ends[id(current)] = max(title_ends.get(id(current), 0.0), max(w["x1"] for w in line))
                current.review_reasons.append("Title continues on a second line in the source")
            else:
                row += 1
                sess = sessions.get(col + 1)
                orphan = ExtractedEntry(page_no, day.day_no, col + 1, sess.label if sess else "", sess.start if sess else time(0), col, row,
                                        "", _clean(line), None, False, "")
                orphan.review_reasons.append("Course code is missing")
                out.append(orphan)
                current = orphan
            last_top = line[0]["top"]
        for e in out:
            if e.column_index == col and title_ends.get(id(e), 0) >= CLIP_MARGIN[col]:
                e.informational.append("Title reaches the cell border and may be clipped in the source")
    for e in out:
        _classify(e, day)
    return out


def _classify(e: ExtractedEntry, day: ExtractedDay) -> None:
    code, title = e.course_code, e.course_title
    if not code:
        if "Course code is missing" not in e.review_reasons:
            e.review_reasons.append("Course code is missing")
    elif not CODE_RE.match(code):
        e.review_reasons.append("Course code has an unusual format")
    if not title:
        e.review_reasons.append("Course title is missing")
    tb, cb = BATCH_TITLE_RE.search(title), BATCH_CODE_RE.search(code) if code else None
    batch = (tb.group(1) if tb else None) or (cb.group(1) if cb else None)
    if tb and cb and tb.group(1) != cb.group(1):
        e.review_reasons.append("Batch in the title differs from the batch suffix of the code")
    if (tb is None) != (cb is None) and code:
        e.review_reasons.append("Batch is shown in the title or in the code but not in both")
    e.batch = batch


def _post_checks(r: ExtractionResult) -> None:
    seen_days = Counter(d.day_no for d in r.days)
    for d in r.days:
        if seen_days[d.day_no] > 1:
            d.review.append("Day number appears more than once")
    # batch versus the legend's group of days
    for e in r.entries:
        g = r.group_for_day(e.day_no)
        if e.batch == "A" and g == "DAYS_9_16":
            e.review_reasons.append("Batch A course on a day listed for Batch B")
        if e.batch == "B" and g == "DAYS_1_8":
            e.review_reasons.append("Batch B course on a day listed for Batch A")
    # the same printed code appearing more than once inside one session
    seen = Counter((e.day_no, e.slot, e.course_code) for e in r.entries if e.course_code)
    for e in r.entries:
        if e.course_code and seen[(e.day_no, e.slot, e.course_code)] > 1:
            e.review_reasons.append("Same course code appears more than once in this session")
    # a title that another title in the same document continues in the middle of a word is probably clipped in the source
    titles = [e.course_title.lower() for e in r.entries if e.course_title]
    roman = {"i", "ii", "iii", "iv", "v", "vi", "1", "2", "3", "4"}
    for e in r.entries:
        t = e.course_title.lower()
        if len(t) < 25 or t.split()[-1] in roman:
            continue
        if any(o != t and o.startswith(t) and o[len(t)].isalnum() for o in titles):
            e.review_reasons.append("Title looks clipped in the source: another title in this document continues the same text")
    # identical code printed on different sessions or days (informational: may be intentional)
    codes = defaultdict(set)
    for e in r.entries:
        if e.course_code:
            codes[e.course_code].add((e.day_no, e.slot))
    for e in r.entries:
        if e.course_code and len(codes[e.course_code]) > 1:
            e.informational.append("Course code is scheduled in more than one session")
