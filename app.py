# app.py
# Main entry point for the MMU Student Enrollment System.
# This file handles:
#   - Flask application creation and configuration
#   - Database initialization via Flask-SQLAlchemy
#   - All route definitions (authentication, student, admin)
#   - A seed function to populate the DB with default data for testing

import os
from flask import (Flask, render_template, redirect, url_for,
                   request, session, flash)
from models import db, User, Course, Section, Enrollment

# ---------------------------------------------------------------------------
# App Factory & Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Secret key for session signing — in production, load this from an
# environment variable. For this university project a hardcoded key is fine.
app.config['SECRET_KEY'] = 'mmu-secret-key-change-in-production'

# SQLite database stored in the 'instance/' folder (Flask default location).
# The 'instance' folder is gitignored so the DB file is not committed.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///enrollment.db'

# Suppress unnecessary SQLAlchemy modification tracking overhead.
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Bind the SQLAlchemy db instance (from models.py) to this Flask app.
db.init_app(app)


# ---------------------------------------------------------------------------
# Helper: Login Required Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """
    A simple decorator that redirects unauthenticated users to the login page.
    Usage: @login_required above any route function.
    """
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """
    A decorator that allows access only to admin users.
    Must be used AFTER @login_required.
    """
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Root route — redirect to dashboard if logged in, else to login."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    GET:  Render the login form.
    POST: Validate credentials. On success, store user info in session
          and redirect to the appropriate dashboard.
    """
    # If already logged in, go straight to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Look up the user by username
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            # Store minimal user info in the server-side session
            session['user_id']   = user.id
            session['username']  = user.username
            session['full_name'] = user.full_name
            session['role']      = user.role
            flash(f'Welcome back, {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password. Please try again.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Clear the session and redirect to login."""
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Shared Dashboard Route
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    """
    Central dashboard that routes the user to the correct view
    based on their role (student or admin).
    """
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('student_dashboard'))


# ---------------------------------------------------------------------------
# Student Routes
# ---------------------------------------------------------------------------

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    """
    Student home page: shows all courses with their sections,
    available seats, and enrollment status for the logged-in student.
    """
    student_id = session['user_id']

    # Fetch all courses and their sections to display in the catalog
    courses = Course.query.order_by(Course.course_code).all()

    # Fetch the student's current enrollments for status checking in the template
    my_enrollments = Enrollment.query.filter_by(user_id=student_id).all()
    # Build a set of course IDs the student is already enrolled in (any section)
    enrolled_course_ids  = {e.section.course_id for e in my_enrollments}
    # Build a set of section IDs the student is enrolled in (for button logic)
    enrolled_section_ids = {e.section_id for e in my_enrollments}

    return render_template(
        'student_dashboard.html',
        courses=courses,
        enrolled_course_ids=enrolled_course_ids,
        enrolled_section_ids=enrolled_section_ids
    )


@app.route('/student/enroll/<int:section_id>', methods=['POST'])
@login_required
def enroll(section_id):
    """
    Enroll the current student in the given section.
    Enforces:
      1. Section must exist.
      2. Section must not be full (max 30).
      3. Student must not already be in this section.
      4. Student must not already be enrolled in ANOTHER section of this course.
    """
    student_id = session['user_id']
    section    = Section.query.get_or_404(section_id)
    course_id  = section.course_id

    # Rule 3: Check for duplicate enrollment in the same section
    already_enrolled = Enrollment.query.filter_by(
        user_id=student_id, section_id=section_id
    ).first()
    if already_enrolled:
        flash('You are already enrolled in this section.', 'warning')
        return redirect(url_for('student_dashboard'))

    # Rule 4: Check if student is enrolled in another section of the same course
    conflict = (
        Enrollment.query
        .join(Section)
        .filter(
            Enrollment.user_id == student_id,
            Section.course_id  == course_id
        )
        .first()
    )
    if conflict:
        flash(
            f'You are already enrolled in a section of '
            f'"{section.course.course_name}". '
            f'Drop it first before switching sections.',
            'warning'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 2: Check capacity
    if section.is_full:
        flash(
            f'Sorry, {section.section_name} of "{section.course.course_name}" '
            f'is full (max {section.max_capacity} students).',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    # All checks passed — create the enrollment record
    enrollment = Enrollment(user_id=student_id, section_id=section_id)
    db.session.add(enrollment)
    db.session.commit()

    flash(
        f'Successfully enrolled in {section.section_name} of '
        f'"{section.course.course_name}"!',
        'success'
    )
    return redirect(url_for('student_dashboard'))


@app.route('/student/drop/<int:section_id>', methods=['POST'])
@login_required
def drop(section_id):
    """
    Drop the current student's enrollment in the given section.
    Only deletes the record if it actually belongs to this student.
    """
    student_id = session['user_id']

    enrollment = Enrollment.query.filter_by(
        user_id=student_id, section_id=section_id
    ).first()

    if not enrollment:
        flash('You are not enrolled in this section.', 'warning')
        return redirect(url_for('student_dashboard'))

    section = Section.query.get(section_id)
    db.session.delete(enrollment)
    db.session.commit()

    flash(
        f'You have dropped {section.section_name} of '
        f'"{section.course.course_name}".',
        'info'
    )
    return redirect(url_for('student_dashboard'))


@app.route('/student/timetable')
@login_required
def timetable():
    """
    Display a simple table of all sections the student is enrolled in,
    ordered by day for easy reading.
    """
    student_id  = session['user_id']
    enrollments = (
        Enrollment.query
        .filter_by(user_id=student_id)
        .join(Section)
        .order_by(Section.day, Section.time)
        .all()
    )
    return render_template('timetable.html', enrollments=enrollments)


# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    """
    Admin home page: shows all courses with section counts
    and total enrollment numbers at a glance.
    """
    courses = Course.query.order_by(Course.course_code).all()
    return render_template('admin_dashboard.html', courses=courses)


@app.route('/admin/course/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_course():
    """
    GET:  Show the form to add a new course + section.
    POST: Validate and save the new course and its first section to the DB.
    """
    if request.method == 'POST':
        course_code  = request.form.get('course_code', '').strip().upper()
        course_name  = request.form.get('course_name', '').strip()
        credit_hours = request.form.get('credit_hours', 3)
        description  = request.form.get('description', '').strip()

        # Section details
        section_name = request.form.get('section_name', '').strip()
        day          = request.form.get('day', '').strip()
        time         = request.form.get('time', '').strip()
        venue        = request.form.get('venue', '').strip()
        max_capacity = request.form.get('max_capacity', 30)

        # Basic validation
        if not all([course_code, course_name, section_name, day, time, venue]):
            flash('All fields are required. Please fill in the form completely.', 'danger')
            return render_template('add_course.html')

        # Check for duplicate course code
        if Course.query.filter_by(course_code=course_code).first():
            flash(f'Course code "{course_code}" already exists.', 'danger')
            return render_template('add_course.html')

        # Create the course
        course = Course(
            course_code=course_code,
            course_name=course_name,
            credit_hours=int(credit_hours),
            description=description
        )
        db.session.add(course)
        db.session.flush()  # Get course.id before committing

        # Create the first section for this course
        section = Section(
            section_name=section_name,
            day=day,
            time=time,
            venue=venue,
            max_capacity=int(max_capacity),
            course_id=course.id
        )
        db.session.add(section)
        db.session.commit()

        flash(
            f'Course "{course_name}" with {section_name} added successfully!',
            'success'
        )
        return redirect(url_for('admin_dashboard'))

    return render_template('add_course.html')


@app.route('/admin/course/<int:course_id>/add_section', methods=['GET', 'POST'])
@login_required
@admin_required
def add_section(course_id):
    """
    Add an additional section to an existing course.
    """
    course = Course.query.get_or_404(course_id)

    if request.method == 'POST':
        section_name = request.form.get('section_name', '').strip()
        day          = request.form.get('day', '').strip()
        time         = request.form.get('time', '').strip()
        venue        = request.form.get('venue', '').strip()
        max_capacity = request.form.get('max_capacity', 30)

        if not all([section_name, day, time, venue]):
            flash('All section fields are required.', 'danger')
            return render_template('add_section.html', course=course)

        section = Section(
            section_name=section_name,
            day=day,
            time=time,
            venue=venue,
            max_capacity=int(max_capacity),
            course_id=course.id
        )
        db.session.add(section)
        db.session.commit()

        flash(f'{section_name} added to "{course.course_name}"!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('add_section.html', course=course)


@app.route('/admin/section/<int:section_id>/students')
@login_required
@admin_required
def view_enrolled_students(section_id):
    """
    Show the admin a list of all students enrolled in a specific section.
    """
    section     = Section.query.get_or_404(section_id)
    enrollments = (
        Enrollment.query
        .filter_by(section_id=section_id)
        .join(User)
        .order_by(User.full_name)
        .all()
    )
    return render_template(
        'enrolled_students.html',
        section=section,
        enrollments=enrollments
    )


# ---------------------------------------------------------------------------
# Database Seeding Function
# ---------------------------------------------------------------------------

def seed_database():
    """
    Populate the database with:
      - 1 default admin account
      - 1 default student account (for testing)
      - 4 sample MMU courses with sections
    This function only runs if the database is empty (idempotent).
    """

    # --- Users ---
    if not User.query.first():
        admin = User(username='admin', full_name='System Administrator', role='admin')
        admin.set_password('admin123')

        student = User(username='student1', full_name='Ali Hassan', role='student')
        student.set_password('student123')

        db.session.add_all([admin, student])
        db.session.commit()
        print('[Seed] Created default admin and student accounts.')

    # --- Courses and Sections ---
    if not Course.query.first():
        courses_data = [
            {
                'course_code': 'CS101',
                'course_name': 'Introduction to Programming',
                'credit_hours': 3,
                'description': 'Fundamentals of programming using Python.',
                'sections': [
                    {'name': 'Section A', 'day': 'Monday',    'time': '08:00 - 10:00', 'venue': 'Lab A1'},
                    {'name': 'Section B', 'day': 'Wednesday', 'time': '10:00 - 12:00', 'venue': 'Lab A2'},
                ]
            },
            {
                'course_code': 'CS201',
                'course_name': 'Data Structures & Algorithms',
                'credit_hours': 3,
                'description': 'Core data structures: arrays, linked lists, trees, and graphs.',
                'sections': [
                    {'name': 'Section A', 'day': 'Tuesday',  'time': '10:00 - 12:00', 'venue': 'Room B301'},
                    {'name': 'Section B', 'day': 'Thursday', 'time': '14:00 - 16:00', 'venue': 'Room B302'},
                ]
            },
            {
                'course_code': 'SE301',
                'course_name': 'Software Engineering Principles',
                'credit_hours': 3,
                'description': 'SDLC, agile methodologies, and software design patterns.',
                'sections': [
                    {'name': 'Section A', 'day': 'Monday',  'time': '14:00 - 16:00', 'venue': 'Room C101'},
                    {'name': 'Section B', 'day': 'Friday',  'time': '08:00 - 10:00', 'venue': 'Room C102'},
                ]
            },
            {
                'course_code': 'DB401',
                'course_name': 'Database Systems',
                'credit_hours': 3,
                'description': 'Relational databases, SQL, normalization, and transactions.',
                'sections': [
                    {'name': 'Section A', 'day': 'Wednesday', 'time': '14:00 - 16:00', 'venue': 'Lab D1'},
                    {'name': 'Section B', 'day': 'Friday',    'time': '10:00 - 12:00', 'venue': 'Lab D2'},
                ]
            },
        ]

        for data in courses_data:
            course = Course(
                course_code=data['course_code'],
                course_name=data['course_name'],
                credit_hours=data['credit_hours'],
                description=data['description']
            )
            db.session.add(course)
            db.session.flush()  # Get course.id

            for sec in data['sections']:
                section = Section(
                    section_name=sec['name'],
                    day=sec['day'],
                    time=sec['time'],
                    venue=sec['venue'],
                    max_capacity=30,
                    course_id=course.id
                )
                db.session.add(section)

        db.session.commit()
        print('[Seed] Created 4 sample courses with sections.')


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        # Create all tables defined in models.py if they don't exist
        db.create_all()
        # Populate with default data for development/testing
        seed_database()
    # Run the Flask development server
    # debug=True enables auto-reload and detailed error pages
    app.run(debug=True)
