# models.py
# Database Schema for MMU Student Enrollment System

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# Allowed values for Section.section_type
SECTION_TYPES = ('Lecture', 'Tutorial', 'Lab')

# Allowed values for Course.sub_component_type  (None means not yet decided)
SUB_COMPONENT_TYPES = ('Tutorial', 'Lab')



# User

class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(120), nullable=False)
    # 'student' or 'admin'
    role          = db.Column(db.String(20), nullable=False, default='student')

    enrollments = db.relationship(
        'Enrollment', backref='student', lazy=True, cascade='all, delete-orphan'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'



# Course

class Course(db.Model):
    __tablename__ = 'courses'

    id           = db.Column(db.Integer, primary_key=True)
    course_code  = db.Column(db.String(20), unique=True, nullable=False)
    course_name  = db.Column(db.String(150), nullable=False)
    credit_hours = db.Column(db.Integer, nullable=False, default=3)
    description  = db.Column(db.Text, nullable=True)

    # Locked to 'Tutorial' or 'Lab' the first time a sub-section is added.
    # NULL until then.  Once set, only sections of that type may be added.
    sub_component_type = db.Column(db.String(20), nullable=True, default=None)

    # All sections for this course (Lecture + sub-sections)
    sections = db.relationship(
        'Section', backref='course', lazy=True,
        foreign_keys='Section.course_id',
        cascade='all, delete-orphan'
    )

    

    @property
    def lecture_sections(self):
        return [s for s in self.sections if s.section_type == 'Lecture']

    @property
    def sub_sections(self):
        """All Tutorial or Lab sections (non-Lecture)."""
        return [s for s in self.sections if s.section_type != 'Lecture']

    @property
    def has_lecture(self):
        return bool(self.lecture_sections)

    def __repr__(self):
        return f'<Course {self.course_code}: {self.course_name}>'



# Section

class Section(db.Model):
    __tablename__ = 'sections'

    id           = db.Column(db.Integer, primary_key=True)
    section_name = db.Column(db.String(40), nullable=False)
    section_type = db.Column(db.String(20), nullable=False)   # Lecture | Tutorial | Lab
    day          = db.Column(db.String(20), nullable=False)   # e.g. "Monday"
    time         = db.Column(db.String(30), nullable=False)   # e.g. "10:00 - 12:00"
    venue        = db.Column(db.String(60), nullable=False)
    max_capacity = db.Column(db.Integer, nullable=False)      # Admin-defined; no upper limit

    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)

    # NULL for Lecture rows; points to parent Lecture for Tutorial/Lab rows
    parent_lecture_id = db.Column(
        db.Integer, db.ForeignKey('sections.id'), nullable=True
    )

    # Navigate from a Lecture to its child sub-sections
    child_sections = db.relationship(
        'Section',
        backref=db.backref('parent_lecture', remote_side='Section.id'),
        foreign_keys=[parent_lecture_id],
        lazy=True
    )

    enrollments = db.relationship(
        'Enrollment', backref='section', lazy=True, cascade='all, delete-orphan'
    )

    

    @property
    def enrolled_count(self):
        return len(self.enrollments)

    @property
    def available_seats(self):
        return self.max_capacity - self.enrolled_count

    @property
    def is_full(self):
        return self.enrolled_count >= self.max_capacity

    @property
    def is_lecture(self):
        return self.section_type == 'Lecture'

    def __repr__(self):
        return (f'<Section [{self.section_type}] '
                f'{self.section_name} — Course {self.course_id}>')



# Enrollment

class Enrollment(db.Model):
    __tablename__ = 'enrollments'

    id          = db.Column(db.Integer, primary_key=True)
    enrolled_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)

    # DB-level guard: a student cannot enroll in the same section twice
    __table_args__ = (
        db.UniqueConstraint('user_id', 'section_id', name='uq_user_section'),
    )

    def __repr__(self):
        return f'<Enrollment User {self.user_id} -> Section {self.section_id}>'
