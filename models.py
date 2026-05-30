# models.py
# Defines all database tables (models) for the MMU Student Enrollment System.
# Uses Flask-SQLAlchemy for ORM and Werkzeug for password hashing.

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Create the SQLAlchemy extension instance.
# This will be initialized with the Flask app in app.py.
db = SQLAlchemy()


# ---------------------------------------------------------------------------
# User Model
# Represents both Students and Admin/Staff users.
# The 'role' field distinguishes between the two ('student' or 'admin').
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(120), nullable=False)
    # Role must be either 'student' or 'admin'
    role          = db.Column(db.String(20), nullable=False, default='student')

    # One user (student) can have many enrollments
    enrollments = db.relationship('Enrollment', backref='student', lazy=True,
                                  cascade='all, delete-orphan')

    def set_password(self, password):
        """Hash and store the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Return True if the provided password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        """Convenience method to check if this user is an admin."""
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


# ---------------------------------------------------------------------------
# Course Model
# Represents a university course (e.g., "Introduction to Programming").
# A course can have multiple sections (e.g., Section A, Section B).
# ---------------------------------------------------------------------------
class Course(db.Model):
    __tablename__ = 'courses'

    id           = db.Column(db.Integer, primary_key=True)
    course_code  = db.Column(db.String(20), unique=True, nullable=False)  # e.g., "CS101"
    course_name  = db.Column(db.String(150), nullable=False)              # e.g., "Intro to Programming"
    credit_hours = db.Column(db.Integer, nullable=False, default=3)
    description  = db.Column(db.Text, nullable=True)

    # One course can have many sections
    sections = db.relationship('Section', backref='course', lazy=True,
                               cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Course {self.course_code}: {self.course_name}>'


# ---------------------------------------------------------------------------
# Section Model
# Represents a specific class section of a course.
# Holds the schedule details (day, time, venue) and capacity limit.
# ---------------------------------------------------------------------------
class Section(db.Model):
    __tablename__ = 'sections'

    id           = db.Column(db.Integer, primary_key=True)
    section_name = db.Column(db.String(20), nullable=False)   # e.g., "Section A"
    day          = db.Column(db.String(20), nullable=False)   # e.g., "Monday"
    time         = db.Column(db.String(30), nullable=False)   # e.g., "10:00 - 12:00"
    venue        = db.Column(db.String(60), nullable=False)   # e.g., "Room B201"
    # Maximum number of students allowed — hard cap at 30
    max_capacity = db.Column(db.Integer, nullable=False, default=30)

    # Foreign key linking this section to its parent course
    course_id    = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)

    # One section can have many enrollment records
    enrollments  = db.relationship('Enrollment', backref='section', lazy=True,
                                   cascade='all, delete-orphan')

    @property
    def enrolled_count(self):
        """Returns the current number of students enrolled in this section."""
        return len(self.enrollments)

    @property
    def available_seats(self):
        """Returns the number of remaining open seats."""
        return self.max_capacity - self.enrolled_count

    @property
    def is_full(self):
        """Returns True if the section has reached its maximum capacity."""
        return self.enrolled_count >= self.max_capacity

    def __repr__(self):
        return f'<Section {self.section_name} of Course ID {self.course_id}>'


# ---------------------------------------------------------------------------
# Enrollment Model
# The join table linking a Student (User) to a Section.
# Business rules enforced here:
#   1. A student cannot enroll in the same section twice (unique constraint).
#   2. A student cannot enroll in two sections of the same course (enforced
#      at the application layer in app.py before inserting a record).
# ---------------------------------------------------------------------------
class Enrollment(db.Model):
    __tablename__ = 'enrollments'

    id          = db.Column(db.Integer, primary_key=True)
    enrolled_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Foreign keys
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)

    # Unique constraint: prevents a student from enrolling in the exact same
    # section more than once at the database level.
    __table_args__ = (
        db.UniqueConstraint('user_id', 'section_id', name='uq_user_section'),
    )

    def __repr__(self):
        return f'<Enrollment User {self.user_id} -> Section {self.section_id}>'
