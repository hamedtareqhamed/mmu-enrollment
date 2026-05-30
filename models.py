# models.py
# Database schema for the MMU Student Enrollment System.
#
# Key structural changes from v1:
#   - Section now has a 'section_type' field: 'Lecture', 'Tutorial', or 'Lab'.
#   - Section has a self-referential FK 'parent_lecture_id' that links a
#     Tutorial/Lab to the Lecture it belongs to. Lecture sections have NULL here.
#   - max_capacity is now a free integer — no hard limit of 30 is enforced.
#   - Enrollment unique constraint is still at DB level (user_id, section_id).
#   - All higher-level business rules (time clash, lecture prerequisite) are
#     enforced at the application layer in app.py.

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# Valid section type values — used for validation in app.py
SECTION_TYPES = ('Lecture', 'Tutorial', 'Lab')


# ---------------------------------------------------------------------------
# User Model
# Represents both Students and Admin/Staff.
# role field is either 'student' or 'admin'.
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(120), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default='student')

    # A student can hold many enrollment records
    enrollments = db.relationship(
        'Enrollment', backref='student', lazy=True, cascade='all, delete-orphan'
    )

    def set_password(self, password):
        """Hash and store the user's password using Werkzeug."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Return True if the plain-text password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


# ---------------------------------------------------------------------------
# Course Model
# A course (e.g., CS101) owns multiple Section records.
# A course MUST have at least one Lecture section (enforced in app.py).
# ---------------------------------------------------------------------------
class Course(db.Model):
    __tablename__ = 'courses'

    id           = db.Column(db.Integer, primary_key=True)
    course_code  = db.Column(db.String(20), unique=True, nullable=False)
    course_name  = db.Column(db.String(150), nullable=False)
    credit_hours = db.Column(db.Integer, nullable=False, default=3)
    description  = db.Column(db.Text, nullable=True)

    # All sections (Lecture, Tutorial, Lab) that belong to this course
    sections = db.relationship(
        'Section', backref='course', lazy=True,
        foreign_keys='Section.course_id',
        cascade='all, delete-orphan'
    )

    @property
    def lecture_sections(self):
        """Return only the Lecture-type sections for this course."""
        return [s for s in self.sections if s.section_type == 'Lecture']

    @property
    def has_lecture(self):
        """True if this course has at least one Lecture section."""
        return len(self.lecture_sections) > 0

    def __repr__(self):
        return f'<Course {self.course_code}: {self.course_name}>'


# ---------------------------------------------------------------------------
# Section Model
# Represents one scheduled class slot — Lecture, Tutorial, or Lab.
#
# section_type:       'Lecture' | 'Tutorial' | 'Lab'
# parent_lecture_id:  NULL for Lecture rows.
#                     For Tutorial/Lab, the FK points to the Lecture section
#                     under which this slot sits. Students can only enroll in
#                     a Tutorial/Lab if they are already in its parent Lecture.
# max_capacity:       Admin-defined integer. No upper bound is enforced.
# ---------------------------------------------------------------------------
class Section(db.Model):
    __tablename__ = 'sections'

    id           = db.Column(db.Integer, primary_key=True)
    section_name = db.Column(db.String(40), nullable=False)   # e.g., "Lecture A" / "Lab Group 1"
    section_type = db.Column(db.String(20), nullable=False)   # 'Lecture', 'Tutorial', or 'Lab'
    day          = db.Column(db.String(20), nullable=False)   # e.g., "Monday"
    time         = db.Column(db.String(30), nullable=False)   # e.g., "10:00 - 12:00"
    venue        = db.Column(db.String(60), nullable=False)   # e.g., "Room B201"
    max_capacity = db.Column(db.Integer, nullable=False)      # No default — admin must set it

    # FK to the parent Course
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)

    # Self-referential FK: Tutorial/Lab rows point to their parent Lecture row.
    # Lecture rows have NULL here.
    parent_lecture_id = db.Column(
        db.Integer, db.ForeignKey('sections.id'), nullable=True
    )

    # ORM relationship: from a Lecture section, access its child Tutorial/Lab sections
    child_sections = db.relationship(
        'Section',
        backref=db.backref('parent_lecture', remote_side='Section.id'),
        foreign_keys=[parent_lecture_id],
        lazy=True
    )

    # All enrollments for this section
    enrollments = db.relationship(
        'Enrollment', backref='section', lazy=True, cascade='all, delete-orphan'
    )

    # ---- Computed properties ------------------------------------------------

    @property
    def enrolled_count(self):
        """Current number of students enrolled in this section."""
        return len(self.enrollments)

    @property
    def available_seats(self):
        """Remaining open seats (can go negative if capacity is lowered after enrollment)."""
        return self.max_capacity - self.enrolled_count

    @property
    def is_full(self):
        """True when no seats remain."""
        return self.enrolled_count >= self.max_capacity

    @property
    def is_lecture(self):
        return self.section_type == 'Lecture'

    @property
    def is_tutorial(self):
        return self.section_type == 'Tutorial'

    @property
    def is_lab(self):
        return self.section_type == 'Lab'

    def __repr__(self):
        return f'<Section [{self.section_type}] {self.section_name} — Course {self.course_id}>'


# ---------------------------------------------------------------------------
# Enrollment Model
# Join table: one row per (student, section) pair.
#
# DB-level constraint: UniqueConstraint on (user_id, section_id) prevents
# a student from enrolling in the same section twice.
#
# App-level rules enforced in app.py:
#   Rule 1 — A student must be enrolled in a Lecture before enrolling
#             in any of its child Tutorial/Lab sections.
#   Rule 2 — A student may only hold ONE Lecture per course.
#   Rule 3 — Time-clash check: no two enrolled sections may share the
#             same Day AND Time slot.
# ---------------------------------------------------------------------------
class Enrollment(db.Model):
    __tablename__ = 'enrollments'

    id          = db.Column(db.Integer, primary_key=True)
    enrolled_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)

    # Database-level guard against duplicate (student, section) pairs
    __table_args__ = (
        db.UniqueConstraint('user_id', 'section_id', name='uq_user_section'),
    )

    def __repr__(self):
        return f'<Enrollment User {self.user_id} -> Section {self.section_id}>'
