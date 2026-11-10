"""Import every model so that Base.metadata is complete (needed by Alembic)."""
from database.models.algorithm_configuration import AlgorithmConfiguration
from database.models.availability import LecturerAvailability, RoomAvailability
from database.models.classroom import Classroom
from database.models.course import Course, CourseSession
from database.models.course_assignment import CourseAssignment
from database.models.dataset import Dataset, DatasetMember, ExamDay, ExamEntry, ExamSession
from database.models.department import Department
from database.models.generation_history import GenerationHistory
from database.models.lecturer import Lecturer
from database.models.student_group import StudentGroup
from database.models.time_slot import TimeSlot
from database.models.timetable import Timetable, TimetableAudit, TimetableEntry
from database.models.user import AppSetting, User, UserSession

__all__ = [
    "AlgorithmConfiguration", "LecturerAvailability", "RoomAvailability", "Classroom", "Course", "CourseSession",
    "CourseAssignment", "Department", "GenerationHistory", "Lecturer", "StudentGroup", "TimeSlot", "Timetable",
    "TimetableAudit", "TimetableEntry", "AppSetting", "User", "UserSession", "Dataset", "DatasetMember", "ExamDay",
    "ExamEntry", "ExamSession",
]
