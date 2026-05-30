# app.py
# MMU Student Enrollment System — Main Flask Application
#
# Structural changes from v1:
#   - Section type architecture: Lecture / Tutorial / Lab
#   - Lecture-prerequisite rule: students must hold a Lecture enrollment before
#     they can enroll in any child Tutorial/Lab of that Lecture.
#   - Dropping a Lecture automatically cascades: all child Tutorial/Lab
#     enrollments under that Lecture are dropped simultaneously.
#   - Time-clash validation: applied to both student enrollment and admin
#     section creation (prevents two sections of any type sharing the same
#     Day + Time slot across the entire timetable).
#   - max_capacity: no hard upper limit; admin supplies any integer.
#   - Seed data: 4 official group members + admin, with realistic Lecture /
#     Tutorial / Lab sections per course.

from functools import wraps
from flask import (Flask, render_template, redirect, url_for,
                   request, session, flash)
from models import db, User, Course, Section, Enrollment, SECTION_TYPES

# ---------------------------------------------------------------------------
# Application Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config['SECRET_KEY']                  = 'mmu-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI']     = 'sqlite:///enrollment.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ---------------------------------------------------------------------------
# Access-Control Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Redirect unauthenticated users to the login page."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Allow access only to users with role == 'admin'."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Shared Business-Logic Helpers
# ---------------------------------------------------------------------------

def get_student_enrollments(user_id):
    """
    Return a dict with three pre-built lookup structures for a given student:
      enrolled_section_ids  : set of section IDs the student is in
      enrolled_lecture_ids  : set of section IDs that are Lectures
      enrolled_course_ids   : set of course IDs the student has a Lecture in
    These are used by both the student dashboard route and the enroll route.
    """
    my_enrollments = Enrollment.query.filter_by(user_id=user_id).all()
    enrolled_section_ids = {e.section_id for e in my_enrollments}
    enrolled_lecture_ids = {
        e.section_id for e in my_enrollments
        if e.section.section_type == 'Lecture'
    }
    # Map course_id -> lecture section_id the student holds (at most one per course)
    lecture_by_course = {
        e.section.course_id: e.section_id
        for e in my_enrollments
        if e.section.section_type == 'Lecture'
    }
    return enrolled_section_ids, enrolled_lecture_ids, lecture_by_course


def check_time_clash(user_id, new_day, new_time, exclude_section_id=None):
    """
    Return the conflicting Section if the student already has an enrollment
    on the same Day + Time slot, otherwise return None.

    `exclude_section_id` lets the caller skip a specific section (used when
    checking a section the student is about to drop-and-re-enroll).
    """
    existing = (
        Enrollment.query
        .filter_by(user_id=user_id)
        .join(Section)
        .filter(Section.day == new_day, Section.time == new_time)
        .all()
    )
    for e in existing:
        if e.section_id != exclude_section_id:
            return e.section   # return the clashing section
    return None


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Authenticate the user and store role info in the session."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
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
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Shared Router
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
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
    Course catalog for students.
    Passes enrollment lookup structures to the template so it can
    render the correct action button (Enroll / Drop / locked states).
    """
    student_id = session['user_id']
    courses    = Course.query.order_by(Course.course_code).all()

    enrolled_section_ids, enrolled_lecture_ids, lecture_by_course = \
        get_student_enrollments(student_id)

    return render_template(
        'student_dashboard.html',
        courses=courses,
        enrolled_section_ids=enrolled_section_ids,
        enrolled_lecture_ids=enrolled_lecture_ids,
        lecture_by_course=lecture_by_course,
    )


@app.route('/student/enroll/<int:section_id>', methods=['POST'])
@login_required
def enroll(section_id):
    """
    Enroll the current student in a section.

    Business rules checked in order:
      1. Duplicate — already enrolled in this exact section.
      2. Capacity  — section is full.
      3. Time clash — Day + Time conflicts with an existing enrollment.
      4. Lecture prerequisite (Tutorial/Lab only) — student must already
         hold an enrollment in the parent Lecture of this section.
      5. One Lecture per course — a student cannot hold two Lecture
         enrollments for the same course.
    """
    student_id = session['user_id']
    section    = db.session.get(Section, section_id)
    if not section:
        flash('Section not found.', 'danger')
        return redirect(url_for('student_dashboard'))

    enrolled_section_ids, enrolled_lecture_ids, lecture_by_course = \
        get_student_enrollments(student_id)

    # Rule 1: Duplicate enrollment
    if section_id in enrolled_section_ids:
        flash('You are already enrolled in this section.', 'warning')
        return redirect(url_for('student_dashboard'))

    # Rule 2: Capacity check
    if section.is_full:
        flash(
            f'{section.section_type} "{section.section_name}" of '
            f'"{section.course.course_name}" is full '
            f'({section.max_capacity} / {section.max_capacity} students).',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 3: Time-clash validation
    clash = check_time_clash(student_id, section.day, section.time)
    if clash:
        flash(
            f'Time clash detected: you already have '
            f'"{clash.section_name}" ({clash.section_type}) '
            f'on {clash.day} at {clash.time}. '
            f'Please drop it before enrolling here.',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 4: Tutorial/Lab prerequisite — must be in the parent Lecture first
    if section.section_type in ('Tutorial', 'Lab'):
        if section.parent_lecture_id not in enrolled_lecture_ids:
            parent = db.session.get(Section, section.parent_lecture_id)
            parent_name = parent.section_name if parent else 'the required Lecture'
            flash(
                f'You must enroll in "{parent_name}" (Lecture) before '
                f'enrolling in this {section.section_type}.',
                'warning'
            )
            return redirect(url_for('student_dashboard'))

    # Rule 5: One Lecture per course
    if section.section_type == 'Lecture':
        if section.course_id in lecture_by_course:
            existing_lec = db.session.get(Section, lecture_by_course[section.course_id])
            flash(
                f'You are already enrolled in Lecture '
                f'"{existing_lec.section_name}" for '
                f'"{section.course.course_name}". '
                f'Drop it first if you want to switch.',
                'warning'
            )
            return redirect(url_for('student_dashboard'))

    # All rules passed — create enrollment
    db.session.add(Enrollment(user_id=student_id, section_id=section_id))
    db.session.commit()
    flash(
        f'Successfully enrolled in {section.section_type} '
        f'"{section.section_name}" of "{section.course.course_name}".',
        'success'
    )
    return redirect(url_for('student_dashboard'))


@app.route('/student/drop/<int:section_id>', methods=['POST'])
@login_required
def drop(section_id):
    """
    Drop the student's enrollment in a section.

    Cascade rule: if the section being dropped is a Lecture, all child
    Tutorial/Lab enrollments the student holds under that Lecture are
    also automatically dropped. This prevents orphaned Tutorial/Lab
    enrollments without a parent Lecture.
    """
    student_id = session['user_id']
    section    = db.session.get(Section, section_id)

    if not section:
        flash('Section not found.', 'danger')
        return redirect(url_for('student_dashboard'))

    enrollment = Enrollment.query.filter_by(
        user_id=student_id, section_id=section_id
    ).first()

    if not enrollment:
        flash('You are not enrolled in this section.', 'warning')
        return redirect(url_for('student_dashboard'))

    dropped_names = [f'{section.section_type} "{section.section_name}"']
    db.session.delete(enrollment)

    # Cascade: if dropping a Lecture, also drop child Tutorial/Lab enrollments
    if section.section_type == 'Lecture':
        child_ids = [s.id for s in section.child_sections]
        child_enrollments = Enrollment.query.filter(
            Enrollment.user_id == student_id,
            Enrollment.section_id.in_(child_ids)
        ).all()
        for ce in child_enrollments:
            dropped_names.append(
                f'{ce.section.section_type} "{ce.section.section_name}"'
            )
            db.session.delete(ce)

    db.session.commit()

    if len(dropped_names) > 1:
        flash(
            f'Dropped: {", ".join(dropped_names)} from '
            f'"{section.course.course_name}". '
            f'(Linked Tutorial/Lab sections were also removed.)',
            'info'
        )
    else:
        flash(
            f'Dropped {dropped_names[0]} from '
            f'"{section.course.course_name}".',
            'info'
        )
    return redirect(url_for('student_dashboard'))


@app.route('/student/timetable')
@login_required
def timetable():
    """Weekly timetable: all enrolled sections ordered by day then time."""
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
    """Overview of all courses and their sections."""
    courses = Course.query.order_by(Course.course_code).all()
    return render_template('admin_dashboard.html', courses=courses)


@app.route('/admin/course/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_course():
    """
    Create a new course with its mandatory first Lecture section.
    The first section created for a course MUST be a Lecture; this is
    enforced here by locking the section_type to 'Lecture' on first creation.
    """
    if request.method == 'POST':
        course_code  = request.form.get('course_code', '').strip().upper()
        course_name  = request.form.get('course_name', '').strip()
        credit_hours = request.form.get('credit_hours', '3')
        description  = request.form.get('description', '').strip()

        section_name = request.form.get('section_name', '').strip()
        day          = request.form.get('day', '').strip()
        time         = request.form.get('time', '').strip()
        venue        = request.form.get('venue', '').strip()
        max_capacity = request.form.get('max_capacity', '').strip()

        # --- Field validation ---
        if not all([course_code, course_name, section_name, day, time, venue, max_capacity]):
            flash('All fields are required. Please complete the form.', 'danger')
            return render_template('add_course.html')

        try:
            max_capacity = int(max_capacity)
            if max_capacity < 1:
                raise ValueError
        except ValueError:
            flash('Max capacity must be a positive integer.', 'danger')
            return render_template('add_course.html')

        if Course.query.filter_by(course_code=course_code).first():
            flash(f'Course code "{course_code}" already exists.', 'danger')
            return render_template('add_course.html')

        # --- Persist course ---
        course = Course(
            course_code=course_code,
            course_name=course_name,
            credit_hours=int(credit_hours),
            description=description
        )
        db.session.add(course)
        db.session.flush()

        # First section is always a Lecture (enforced — no UI choice for this form)
        section = Section(
            section_name=section_name,
            section_type='Lecture',
            day=day,
            time=time,
            venue=venue,
            max_capacity=max_capacity,
            course_id=course.id,
            parent_lecture_id=None   # Lecture sections have no parent
        )
        db.session.add(section)
        db.session.commit()

        flash(
            f'Course "{course_name}" created with Lecture '
            f'"{section_name}" successfully.',
            'success'
        )
        return redirect(url_for('admin_dashboard'))

    return render_template('add_course.html')


@app.route('/admin/course/<int:course_id>/add_section', methods=['GET', 'POST'])
@login_required
@admin_required
def add_section(course_id):
    """
    Add a Lecture, Tutorial, or Lab section to an existing course.

    Validation:
      - section_type must be one of the three valid values.
      - Tutorial/Lab must declare a parent_lecture_id pointing to an
        existing Lecture section of the same course.
      - Time-clash check: the new section's Day + Time must not already
        exist as another section of the same course (prevents accidental
        duplicates at scheduling level).
    """
    course = db.session.get(Course, course_id)
    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    # Existing lectures of this course — needed to populate parent dropdown
    lecture_sections = [s for s in course.sections if s.section_type == 'Lecture']

    if request.method == 'POST':
        section_name      = request.form.get('section_name', '').strip()
        section_type      = request.form.get('section_type', '').strip()
        day               = request.form.get('day', '').strip()
        time              = request.form.get('time', '').strip()
        venue             = request.form.get('venue', '').strip()
        max_capacity      = request.form.get('max_capacity', '').strip()
        parent_lecture_id = request.form.get('parent_lecture_id', '').strip() or None

        # --- Field validation ---
        if not all([section_name, section_type, day, time, venue, max_capacity]):
            flash('All fields are required.', 'danger')
            return render_template('add_section.html', course=course,
                                   lecture_sections=lecture_sections)

        if section_type not in SECTION_TYPES:
            flash(f'Invalid section type. Must be one of: {", ".join(SECTION_TYPES)}.', 'danger')
            return render_template('add_section.html', course=course,
                                   lecture_sections=lecture_sections)

        try:
            max_capacity = int(max_capacity)
            if max_capacity < 1:
                raise ValueError
        except ValueError:
            flash('Max capacity must be a positive integer.', 'danger')
            return render_template('add_section.html', course=course,
                                   lecture_sections=lecture_sections)

        # --- Tutorial/Lab must have a parent Lecture ---
        resolved_parent_id = None
        if section_type in ('Tutorial', 'Lab'):
            if not parent_lecture_id:
                flash(
                    f'A {section_type} section must be linked to a parent Lecture. '
                    f'Please select one from the dropdown.',
                    'danger'
                )
                return render_template('add_section.html', course=course,
                                       lecture_sections=lecture_sections)

            parent_lec = db.session.get(Section, int(parent_lecture_id))
            if not parent_lec or parent_lec.course_id != course.id \
                    or parent_lec.section_type != 'Lecture':
                flash('Invalid parent Lecture selected.', 'danger')
                return render_template('add_section.html', course=course,
                                       lecture_sections=lecture_sections)
            resolved_parent_id = parent_lec.id

        # --- Time-clash check within the course (same course, same slot) ---
        clash = next(
            (s for s in course.sections if s.day == day and s.time == time),
            None
        )
        if clash:
            flash(
                f'Schedule conflict: "{clash.section_name}" ({clash.section_type}) '
                f'of this course is already scheduled on {day} at {time}.',
                'danger'
            )
            return render_template('add_section.html', course=course,
                                   lecture_sections=lecture_sections)

        # --- Persist ---
        section = Section(
            section_name=section_name,
            section_type=section_type,
            day=day,
            time=time,
            venue=venue,
            max_capacity=max_capacity,
            course_id=course.id,
            parent_lecture_id=resolved_parent_id
        )
        db.session.add(section)
        db.session.commit()

        flash(
            f'{section_type} "{section_name}" added to "{course.course_name}" successfully.',
            'success'
        )
        return redirect(url_for('admin_dashboard'))

    return render_template('add_section.html', course=course,
                           lecture_sections=lecture_sections)


@app.route('/admin/section/<int:section_id>/students')
@login_required
@admin_required
def view_enrolled_students(section_id):
    """List all students enrolled in a specific section."""
    section = db.session.get(Section, section_id)
    if not section:
        flash('Section not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

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
# Database Seed Function
# ---------------------------------------------------------------------------

def seed_database():
    """
    Populate the database on first run with:
      - 1 admin account
      - 4 official project group member student accounts
      - 3 MMU courses, each with Lecture + Tutorial + Lab sections
        structured under the new Lecture-subordinate architecture.

    Idempotent: checks User table before inserting anything.
    """

    # ── Users ──────────────────────────────────────────────────────────────
    if not User.query.first():
        admin = User(username='admin', full_name='System Administrator', role='admin')
        admin.set_password('admin123')

        group_members = [
            ('hamed',    'hamed albazeli',                    'student123'),
            ('mohamed',  'Mohamed Amer Hassan',               'student123'),
            ('muhannad', 'Gharawi, Muhannad Mohammed',        'student123'),
            ('basil',    'Basil Idris Ibrahim Idris',         'student123'),
        ]
        users = [admin]
        for username, full_name, password in group_members:
            u = User(username=username, full_name=full_name, role='student')
            u.set_password(password)
            users.append(u)

        db.session.add_all(users)
        db.session.commit()
        print('[Seed] Created admin + 4 group member student accounts.')

    # ── Courses & Sections ─────────────────────────────────────────────────
    if not Course.query.first():
        # Each entry defines a course and its sections.
        # Sections list order matters: Lectures come first so their IDs are
        # available when building Tutorial/Lab parent references.
        courses_data = [
            {
                'course_code': 'CS101',
                'course_name': 'Introduction to Programming',
                'credit_hours': 3,
                'description': 'Fundamentals of programming using Python.',
                'sections': [
                    # Lectures
                    {'name': 'Lecture A',    'type': 'Lecture',  'day': 'Monday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 1',  'capacity': 120,
                     'parent': None},
                    {'name': 'Lecture B',    'type': 'Lecture',  'day': 'Wednesday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 1',  'capacity': 120,
                     'parent': None},
                    # Tutorials — parent key references the section name above
                    {'name': 'Tutorial 1',   'type': 'Tutorial', 'day': 'Monday',
                     'time': '10:00 - 11:00', 'venue': 'Room A101', 'capacity': 30,
                     'parent': 'Lecture A'},
                    {'name': 'Tutorial 2',   'type': 'Tutorial', 'day': 'Wednesday',
                     'time': '10:00 - 11:00', 'venue': 'Room A102', 'capacity': 30,
                     'parent': 'Lecture A'},
                    {'name': 'Tutorial 3',   'type': 'Tutorial', 'day': 'Thursday',
                     'time': '10:00 - 11:00', 'venue': 'Room A103', 'capacity': 30,
                     'parent': 'Lecture B'},
                    # Labs
                    {'name': 'Lab Group 1',  'type': 'Lab',      'day': 'Tuesday',
                     'time': '14:00 - 16:00', 'venue': 'Lab A1', 'capacity': 20,
                     'parent': 'Lecture A'},
                    {'name': 'Lab Group 2',  'type': 'Lab',      'day': 'Thursday',
                     'time': '14:00 - 16:00', 'venue': 'Lab A2', 'capacity': 20,
                     'parent': 'Lecture B'},
                ]
            },
            {
                'course_code': 'SE301',
                'course_name': 'Software Engineering Principles',
                'credit_hours': 3,
                'description': 'SDLC, agile methodologies, and software design patterns.',
                'sections': [
                    {'name': 'Lecture A',    'type': 'Lecture',  'day': 'Tuesday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 2',  'capacity': 100,
                     'parent': None},
                    {'name': 'Tutorial 1',   'type': 'Tutorial', 'day': 'Tuesday',
                     'time': '10:00 - 11:00', 'venue': 'Room B201', 'capacity': 25,
                     'parent': 'Lecture A'},
                    {'name': 'Tutorial 2',   'type': 'Tutorial', 'day': 'Friday',
                     'time': '10:00 - 11:00', 'venue': 'Room B202', 'capacity': 25,
                     'parent': 'Lecture A'},
                    {'name': 'Lab Group 1',  'type': 'Lab',      'day': 'Wednesday',
                     'time': '14:00 - 16:00', 'venue': 'Lab B1', 'capacity': 20,
                     'parent': 'Lecture A'},
                ]
            },
            {
                'course_code': 'DB401',
                'course_name': 'Database Systems',
                'credit_hours': 3,
                'description': 'Relational databases, SQL, normalization, and transactions.',
                'sections': [
                    {'name': 'Lecture A',    'type': 'Lecture',  'day': 'Thursday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 3',  'capacity': 90,
                     'parent': None},
                    {'name': 'Tutorial 1',   'type': 'Tutorial', 'day': 'Friday',
                     'time': '08:00 - 09:00', 'venue': 'Room C101', 'capacity': 30,
                     'parent': 'Lecture A'},
                    {'name': 'Tutorial 2',   'type': 'Tutorial', 'day': 'Friday',
                     'time': '09:00 - 10:00', 'venue': 'Room C102', 'capacity': 30,
                     'parent': 'Lecture A'},
                    {'name': 'Lab Group 1',  'type': 'Lab',      'day': 'Monday',
                     'time': '14:00 - 16:00', 'venue': 'Lab D1', 'capacity': 20,
                     'parent': 'Lecture A'},
                    {'name': 'Lab Group 2',  'type': 'Lab',      'day': 'Wednesday',
                     'time': '14:00 - 16:00', 'venue': 'Lab D2', 'capacity': 20,
                     'parent': 'Lecture A'},
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
            db.session.flush()   # get course.id

            # First pass: create all sections; track name -> Section object
            name_to_section = {}
            for sec in data['sections']:
                s = Section(
                    section_name=sec['name'],
                    section_type=sec['type'],
                    day=sec['day'],
                    time=sec['time'],
                    venue=sec['venue'],
                    max_capacity=sec['capacity'],
                    course_id=course.id,
                    parent_lecture_id=None   # resolved in second pass
                )
                db.session.add(s)
                db.session.flush()   # get s.id
                name_to_section[sec['name']] = s

            # Second pass: resolve parent_lecture_id for Tutorial/Lab rows
            for sec in data['sections']:
                if sec['parent'] is not None:
                    child  = name_to_section[sec['name']]
                    parent = name_to_section[sec['parent']]
                    child.parent_lecture_id = parent.id

        db.session.commit()
        print('[Seed] Created 3 courses with Lecture / Tutorial / Lab sections.')


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(debug=True)
