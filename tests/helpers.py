from algorithm.data import RoomInfo, SchedulingData, SessionReq, build_allowed, build_preferred


def make_data(sessions, rooms=None, lec_records=None, room_records=None, days=range(5), start=8, end=18):
    """sessions: list of dicts(assignment_id, lecturer_id, group_id, duration, [room_type, population, session_no])."""
    reqs = []
    for i, s in enumerate(sessions):
        reqs.append(SessionReq(i, s["assignment_id"], s.get("session_no", 1), s.get("course_id", s["assignment_id"]),
                               s.get("code", f"C{s['assignment_id']}"), s["lecturer_id"], s["group_id"], s["duration"],
                               s.get("room_type", "STANDARD_CLASSROOM"), s.get("population", 30)))
    rooms = rooms or [RoomInfo(1, "R1", 100, "STANDARD_CLASSROOM"), RoomInfo(2, "R2", 100, "STANDARD_CLASSROOM")]
    lec_ids = sorted({r.lecturer_id for r in reqs})
    if lec_records is None:
        lec_records = [(l, d, start * 60, end * 60, "AVAILABLE") for l in lec_ids for d in days]
    windows = {d: [(start * 60, end * 60)] for d in days}
    starts = {d: [h * 60 for h in range(start, end)] for d in days}
    data = SchedulingData(sessions=reqs, rooms={r.id: r for r in rooms},
                          lecturer_allowed=build_allowed(lec_records, False, lec_ids),
                          lecturer_preferred=build_preferred(lec_records, lec_ids),
                          room_allowed=build_allowed(room_records or [], True, [r.id for r in rooms]),
                          windows=windows, starts=starts)
    data.build_domains()
    return data
