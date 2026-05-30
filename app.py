# app.py
# MMU Student Enrollment System — Flask Application (v3)
#
# Key changes from v2:
#
#  1. ATOMIC PAIR ENROLLMENT
#     /student/enroll  (POST) now accepts both lecture_id AND subsection_id
#     in the same form submission.  Both sections are validated and committed
#     together, or neither is.  A student cannot enroll in just a Lecture or
#     just a sub-section — both are required in one action.
#
#  2. TUTORIAL XOR LAB PER COURSE
#     Course.sub_component_type is locked the first time an admin adds a
#     sub-section.  Subsequent sub-sections must match the locked type.
#     add_section() enforces this and updates the course field.
#
#  3. TIME-CLASH VALIDATION
#     check_time_clash() checks Day + Time against ALL existing enrollments
#     for the student.  It is called for BOTH the Lecture and the sub-section
#     being enrolled atomically.
#
#  4. FORM BUG FIX
#     The day field is now submitted via a standard <select> element in the
#     templates (no hidden input / JS dependency).  The backend reads
#     request.form['day'] directly — no brittle JS-to-hidden-input bridge.
#
#  5. DROP CASCADE
#     Dropping a Lecture also drops all child sub-section enrollments the
#     student holds under that Lecture in the same transaction.

from functools import wraps
from flask import (Flask, render_template, redirect, url_for,
                   request, session, flash)
from models import db, User, Course, Section, Enrollment, SECTION_TYPES, SUB_COMPONENT_TYPES

# ---------------------------------------------------------------------------
# Configuration
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
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------

def get_student_enrollment_map(user_id):
    """
    Build lookup structures for a student's current enrollments.

    Returns:
        enrolled_section_ids (set)  — all section IDs the student holds
        lecture_by_course    (dict) — course_id -> lecture Section object
        subsection_by_lecture(dict) — parent_lecture_id -> sub-section Section object
    """
    records = Enrollment.query.filter_by(user_id=user_id).all()

    enrolled_section_ids  = {e.section_id for e in records}

    lecture_by_course = {}
    subsection_by_lecture = {}

    for e in records:
        sec = e.section
        if sec.section_type == 'Lecture':
            lecture_by_course[sec.course_id] = sec
        else:
            # sub-section (Tutorial or Lab)
            subsection_by_lecture[sec.parent_lecture_id] = sec

    return enrolled_section_ids, lecture_by_course, subsection_by_lecture


def check_time_clash(user_id, day, time, exclude_ids=None):
    """
    Return the first enrolled Section that clashes with (day, time),
    or None if no clash exists.

    exclude_ids: iterable of section IDs to ignore (used in drop-then-re-enroll).
    """
    exclude_ids = set(exclude_ids or [])
    clashes = (
        Enrollment.query
        .filter_by(user_id=user_id)
        .join(Section)
        .filter(Section.day == day, Section.time == time)
        .all()
    )
    for e in clashes:
        if e.section_id not in exclude_ids:
            return e.section
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

        flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Dashboard Router
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
    Render the course catalog.

    Template receives:
        courses              — all courses ordered by code
        enrolled_section_ids — set of section IDs student is currently in
        lecture_by_course    — course_id -> Lecture Section the student holds
        subsection_by_lecture— parent_lecture_id -> sub-section the student holds
    """
    student_id = session['user_id']
    courses    = Course.query.order_by(Course.course_code).all()

    enrolled_section_ids, lecture_by_course, subsection_by_lecture = \
        get_student_enrollment_map(student_id)

    return render_template(
        'student_dashboard.html',
        courses=courses,
        enrolled_section_ids=enrolled_section_ids,
        lecture_by_course=lecture_by_course,
        subsection_by_lecture=subsection_by_lecture,
    )


@app.route('/student/enroll', methods=['POST'])
@login_required
def enroll():
    """
    Atomic pair enrollment: enroll a student in BOTH a Lecture and one of its
    sub-sections (Tutorial or Lab) in a single transaction.

    Form fields expected:
        lecture_id    — int, ID of the chosen Lecture section
        subsection_id — int, ID of the chosen Tutorial or Lab section

    Validation order:
        1. Both IDs must be present and valid.
        2. The sub-section must be a direct child of the chosen Lecture.
        3. Student must not already be enrolled in a Lecture for this course.
        4. Capacity check for both sections.
        5. Time-clash check for both sections independently.
        6. Insert both Enrollment rows atomically.
    """
    student_id = session['user_id']

    # --- Parse IDs ---
    try:
        lecture_id    = int(request.form.get('lecture_id', 0))
        subsection_id = int(request.form.get('subsection_id', 0))
    except (TypeError, ValueError):
        flash('Invalid selection. Please choose a Lecture and a sub-section.', 'danger')
        return redirect(url_for('student_dashboard'))

    if not lecture_id or not subsection_id:
        flash(
            'You must select both a Lecture and a Tutorial/Lab to enroll.',
            'warning'
        )
        return redirect(url_for('student_dashboard'))

    lecture    = db.session.get(Section, lecture_id)
    subsection = db.session.get(Section, subsection_id)

    if not lecture or not subsection:
        flash('Selected section not found.', 'danger')
        return redirect(url_for('student_dashboard'))

    # --- Structural integrity checks ---
    if lecture.section_type != 'Lecture':
        flash('Invalid selection: the first section must be a Lecture.', 'danger')
        return redirect(url_for('student_dashboard'))

    if subsection.parent_lecture_id != lecture.id:
        flash(
            f'"{subsection.section_name}" does not belong to '
            f'"{lecture.section_name}". Please re-select.',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    enrolled_section_ids, lecture_by_course, subsection_by_lecture = \
        get_student_enrollment_map(student_id)

    # Rule 1: Already enrolled in this course's Lecture?
    if lecture.course_id in lecture_by_course:
        existing = lecture_by_course[lecture.course_id]
        flash(
            f'You are already enrolled in "{existing.section_name}" '
            f'for {lecture.course.course_name}. '
            f'Drop it first to switch.',
            'warning'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 2: Already enrolled in either of these exact sections?
    if lecture_id in enrolled_section_ids:
        flash('You are already enrolled in this Lecture.', 'warning')
        return redirect(url_for('student_dashboard'))
    if subsection_id in enrolled_section_ids:
        flash('You are already enrolled in this sub-section.', 'warning')
        return redirect(url_for('student_dashboard'))

    # Rule 3: Capacity — Lecture
    if lecture.is_full:
        flash(
            f'Lecture "{lecture.section_name}" is full '
            f'({lecture.max_capacity}/{lecture.max_capacity}).',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 4: Capacity — sub-section
    if subsection.is_full:
        flash(
            f'{subsection.section_type} "{subsection.section_name}" is full '
            f'({subsection.max_capacity}/{subsection.max_capacity}).',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 5: Time-clash — Lecture slot
    clash = check_time_clash(student_id, lecture.day, lecture.time)
    if clash:
        flash(
            f'Time clash: Lecture "{lecture.section_name}" '
            f'({lecture.day}, {lecture.time}) conflicts with '
            f'your enrolled "{clash.section_name}" '
            f'({clash.section_type}, {clash.day}, {clash.time}).',
            'danger'
        )
        return redirect(url_for('student_dashboard'))

    # Rule 6: Time-clash — sub-section slot (only if it differs from the Lecture slot)
    if not (subsection.day == lecture.day and subsection.time == lecture.time):
        clash = check_time_clash(student_id, subsection.day, subsection.time)
        if clash:
            flash(
                f'Time clash: {subsection.section_type} "{subsection.section_name}" '
                f'({subsection.day}, {subsection.time}) conflicts with '
                f'your enrolled "{clash.section_name}" '
                f'({clash.section_type}, {clash.day}, {clash.time}).',
                'danger'
            )
            return redirect(url_for('student_dashboard'))

    # --- Atomic insert: both enrollments or none ---
    db.session.add(Enrollment(user_id=student_id, section_id=lecture_id))
    db.session.add(Enrollment(user_id=student_id, section_id=subsection_id))
    db.session.commit()

    flash(
        f'Enrolled in {lecture.course.course_name}: '
        f'{lecture.section_name} (Lecture) + '
        f'{subsection.section_name} ({subsection.section_type}).',
        'success'
    )
    return redirect(url_for('student_dashboard'))


@app.route('/student/drop/<int:lecture_id>', methods=['POST'])
@login_required
def drop(lecture_id):
    """
    Drop a student's enrollment in a Lecture and all its child sub-sections
    in a single transaction.

    Only Lecture IDs are accepted here — dropping is always done at the
    Lecture level, which automatically removes linked Tutorial/Lab records.
    """
    student_id = session['user_id']

    lecture = db.session.get(Section, lecture_id)
    if not lecture or lecture.section_type != 'Lecture':
        flash('Invalid drop request: must target a Lecture section.', 'danger')
        return redirect(url_for('student_dashboard'))

    lec_enrollment = Enrollment.query.filter_by(
        user_id=student_id, section_id=lecture_id
    ).first()

    if not lec_enrollment:
        flash('You are not enrolled in this Lecture.', 'warning')
        return redirect(url_for('student_dashboard'))

    dropped = [f'{lecture.section_name} (Lecture)']
    db.session.delete(lec_enrollment)

    # Cascade: drop any child sub-section enrollments the student holds
    child_ids = [s.id for s in lecture.child_sections]
    if child_ids:
        child_records = Enrollment.query.filter(
            Enrollment.user_id    == student_id,
            Enrollment.section_id.in_(child_ids)
        ).all()
        for ce in child_records:
            dropped.append(
                f'{ce.section.section_name} ({ce.section.section_type})'
            )
            db.session.delete(ce)

    db.session.commit()

    flash(
        f'Dropped from {lecture.course.course_name}: '
        + ', '.join(dropped) + '.',
        'info'
    )
    return redirect(url_for('student_dashboard'))


@app.route('/student/timetable')
@login_required
def timetable():
    """All enrolled sections ordered by day then time."""
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
    courses = Course.query.order_by(Course.course_code).all()
    return render_template('admin_dashboard.html', courses=courses)


@app.route('/admin/course/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_course():
    """
    Create a new course with its first (mandatory) Lecture section.

    The day field is submitted via a plain <select> — no JS hidden input —
    which is the fix for the "All fields are required" bug caused by the
    previous JS-driven hidden input not firing before form submission.
    """
    # Days used by the <select> in the template
    DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

    if request.method == 'POST':
        # Course fields
        course_code  = request.form.get('course_code', '').strip().upper()
        course_name  = request.form.get('course_name', '').strip()
        credit_hours = request.form.get('credit_hours', '3').strip()
        description  = request.form.get('description', '').strip()

        # First Lecture section fields
        section_name = request.form.get('section_name', '').strip()
        day          = request.form.get('day', '').strip()       # comes from <select>
        time         = request.form.get('time', '').strip()
        venue        = request.form.get('venue', '').strip()
        max_capacity = request.form.get('max_capacity', '').strip()

        # Validate required fields
        missing = [
            f for f, v in {
                'Course Code': course_code,
                'Course Name': course_name,
                'Section Name': section_name,
                'Day': day,
                'Time': time,
                'Venue': venue,
                'Max Capacity': max_capacity,
            }.items() if not v
        ]
        if missing:
            flash(f'Missing required fields: {", ".join(missing)}.', 'danger')
            return render_template('add_course.html', days=DAYS)

        try:
            max_capacity = int(max_capacity)
            credit_hours = int(credit_hours)
            if max_capacity < 1 or credit_hours < 1:
                raise ValueError
        except ValueError:
            flash('Credit hours and max capacity must be positive integers.', 'danger')
            return render_template('add_course.html', days=DAYS)

        if day not in DAYS:
            flash('Please select a valid day.', 'danger')
            return render_template('add_course.html', days=DAYS)

        if Course.query.filter_by(course_code=course_code).first():
            flash(f'Course code "{course_code}" already exists.', 'danger')
            return render_template('add_course.html', days=DAYS)

        # Persist
        course = Course(
            course_code=course_code,
            course_name=course_name,
            credit_hours=credit_hours,
            description=description,
            sub_component_type=None   # set when first sub-section is added
        )
        db.session.add(course)
        db.session.flush()

        section = Section(
            section_name=section_name,
            section_type='Lecture',
            day=day,
            time=time,
            venue=venue,
            max_capacity=max_capacity,
            course_id=course.id,
            parent_lecture_id=None
        )
        db.session.add(section)
        db.session.commit()

        flash(
            f'Course "{course_name}" created with Lecture "{section_name}".',
            'success'
        )
        return redirect(url_for('admin_dashboard'))

    return render_template('add_course.html', days=DAYS)


@app.route('/admin/course/<int:course_id>/add_section', methods=['GET', 'POST'])
@login_required
@admin_required
def add_section(course_id):
    """
    Add a Lecture, Tutorial, or Lab section to an existing course.

    Tutorial/Lab rules:
      - Must select a parent Lecture that belongs to this course.
      - Course.sub_component_type is locked on the first sub-section added.
        All subsequent sub-sections must match the locked type.

    Day bug fix: day is submitted via <select>, not a JS-filled hidden input.
    """
    DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

    course = db.session.get(Course, course_id)
    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    lecture_sections = course.lecture_sections

    if request.method == 'POST':
        section_name      = request.form.get('section_name', '').strip()
        section_type      = request.form.get('section_type', '').strip()
        day               = request.form.get('day', '').strip()   # from <select>
        time              = request.form.get('time', '').strip()
        venue             = request.form.get('venue', '').strip()
        max_capacity      = request.form.get('max_capacity', '').strip()
        parent_lecture_id = request.form.get('parent_lecture_id', '').strip() or None

        def _render(msg, category='danger'):
            flash(msg, category)
            return render_template(
                'add_section.html', course=course,
                lecture_sections=lecture_sections, days=DAYS
            )

        # Required fields check
        missing = [
            f for f, v in {
                'Section Name': section_name,
                'Section Type': section_type,
                'Day': day,
                'Time': time,
                'Venue': venue,
                'Max Capacity': max_capacity,
            }.items() if not v
        ]
        if missing:
            return _render(f'Missing required fields: {", ".join(missing)}.')

        if section_type not in SECTION_TYPES:
            return _render(f'Invalid section type "{section_type}".')

        if day not in DAYS:
            return _render('Please select a valid day.')

        try:
            max_capacity = int(max_capacity)
            if max_capacity < 1:
                raise ValueError
        except ValueError:
            return _render('Max capacity must be a positive integer.')

        # ── Tutorial / Lab specific rules ────────────────────────────────────
        resolved_parent_id = None

        if section_type in ('Tutorial', 'Lab'):
            # (a) Course sub_component_type XOR check
            if course.sub_component_type and course.sub_component_type != section_type:
                return _render(
                    f'This course already uses {course.sub_component_type} sections. '
                    f'You cannot add a {section_type} section to it.'
                )

            # (b) Parent Lecture required
            if not parent_lecture_id:
                return _render(
                    f'A {section_type} section must be linked to a parent Lecture.'
                )

            try:
                parent_lec = db.session.get(Section, int(parent_lecture_id))
            except (TypeError, ValueError):
                return _render('Invalid parent Lecture ID.')

            if (not parent_lec
                    or parent_lec.course_id != course.id
                    or parent_lec.section_type != 'Lecture'):
                return _render('The selected parent is not a valid Lecture for this course.')

            resolved_parent_id = parent_lec.id

        # ── Schedule conflict within the course ──────────────────────────────
        conflict = next(
            (s for s in course.sections if s.day == day and s.time == time),
            None
        )
        if conflict:
            return _render(
                f'Schedule conflict: "{conflict.section_name}" '
                f'({conflict.section_type}) is already on {day} at {time}.'
            )

        # ── Persist ──────────────────────────────────────────────────────────
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

        # Lock the course's sub_component_type on first sub-section
        if section_type in ('Tutorial', 'Lab') and not course.sub_component_type:
            course.sub_component_type = section_type

        db.session.commit()

        flash(
            f'{section_type} "{section_name}" added to "{course.course_name}".',
            'success'
        )
        return redirect(url_for('admin_dashboard'))

    return render_template(
        'add_section.html', course=course,
        lecture_sections=lecture_sections, days=DAYS
    )


@app.route('/admin/section/<int:section_id>/students')
@login_required
@admin_required
def view_enrolled_students(section_id):
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
# Seed Function
# ---------------------------------------------------------------------------

def seed_database():
    """
    Populate on first run:
      - Admin account (admin / admin123)
      - 4 official group member student accounts (password: student123)
      - 3 MMU courses, each with Lectures and EITHER Tutorials OR Labs
        (never both) — enforcing the Tutorial XOR Lab per course rule.

    Idempotent: aborts silently if any User row already exists.
    """

    # ── Users ────────────────────────────────────────────────────────────────
    if not User.query.first():
        admin = User(username='admin', full_name='System Administrator', role='admin')
        admin.set_password('admin123')

        members = [
            ('hamed',    'hamed albazeli',                 'student123'),
            ('mohamed',  'Mohamed Amer Hassan',            'student123'),
            ('muhannad', 'Gharawi, Muhannad Mohammed',     'student123'),
            ('basil',    'Basil Idris Ibrahim Idris',      'student123'),
        ]
        users = [admin]
        for uname, fname, pwd in members:
            u = User(username=uname, full_name=fname, role='student')
            u.set_password(pwd)
            users.append(u)

        db.session.add_all(users)
        db.session.commit()
        print('[Seed] Admin + 4 student accounts created.')

    # ── Courses & Sections ───────────────────────────────────────────────────
    if not Course.query.first():
        #
        # Each course uses EITHER 'Tutorial' OR 'Lab' — never both.
        # parent key in sections data refers to the name of the parent Lecture.
        #
        courses_data = [
            {
                'code': 'CS101',
                'name': 'Introduction to Programming',
                'credits': 3,
                'description': 'Fundamentals of programming using Python.',
                'sub_type': 'Tutorial',   # this course uses Tutorials only
                'sections': [
                    # ── Lectures ──────────────────────────────────────────
                    {'name': 'Lecture A', 'type': 'Lecture', 'day': 'Monday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 1',
                     'capacity': 120, 'parent': None},
                    {'name': 'Lecture B', 'type': 'Lecture', 'day': 'Wednesday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 1',
                     'capacity': 120, 'parent': None},
                    # ── Tutorials under Lecture A ──────────────────────────
                    {'name': 'Tutorial A1', 'type': 'Tutorial', 'day': 'Monday',
                     'time': '10:00 - 11:00', 'venue': 'Room A101',
                     'capacity': 30, 'parent': 'Lecture A'},
                    {'name': 'Tutorial A2', 'type': 'Tutorial', 'day': 'Tuesday',
                     'time': '10:00 - 11:00', 'venue': 'Room A102',
                     'capacity': 30, 'parent': 'Lecture A'},
                    {'name': 'Tutorial A3', 'type': 'Tutorial', 'day': 'Thursday',
                     'time': '10:00 - 11:00', 'venue': 'Room A103',
                     'capacity': 30, 'parent': 'Lecture A'},
                    # ── Tutorials under Lecture B ──────────────────────────
                    {'name': 'Tutorial B1', 'type': 'Tutorial', 'day': 'Wednesday',
                     'time': '10:00 - 11:00', 'venue': 'Room A104',
                     'capacity': 30, 'parent': 'Lecture B'},
                    {'name': 'Tutorial B2', 'type': 'Tutorial', 'day': 'Friday',
                     'time': '10:00 - 11:00', 'venue': 'Room A105',
                     'capacity': 30, 'parent': 'Lecture B'},
                ]
            },
            {
                'code': 'SE301',
                'name': 'Software Engineering Principles',
                'credits': 3,
                'description': 'SDLC, agile methodologies, and software design patterns.',
                'sub_type': 'Lab',    # this course uses Labs only
                'sections': [
                    {'name': 'Lecture A', 'type': 'Lecture', 'day': 'Tuesday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 2',
                     'capacity': 100, 'parent': None},
                    {'name': 'Lecture B', 'type': 'Lecture', 'day': 'Thursday',
                     'time': '08:00 - 10:00', 'venue': 'Auditorium 2',
                     'capacity': 100, 'parent': None},
                    # ── Labs under Lecture A ───────────────────────────────
                    {'name': 'Lab A1', 'type': 'Lab', 'day': 'Tuesday',
                     'time': '14:00 - 16:00', 'venue': 'Lab B1',
                     'capacity': 25, 'parent': 'Lecture A'},
                    {'name': 'Lab A2', 'type': 'Lab', 'day': 'Wednesday',
                     'time': '14:00 - 16:00', 'venue': 'Lab B2',
                     'capacity': 25, 'parent': 'Lecture A'},
                    # ── Labs under Lecture B ───────────────────────────────
                    {'name': 'Lab B1', 'type': 'Lab', 'day': 'Thursday',
                     'time': '14:00 - 16:00', 'venue': 'Lab B3',
                     'capacity': 25, 'parent': 'Lecture B'},
                    {'name': 'Lab B2', 'type': 'Lab', 'day': 'Friday',
                     'time': '14:00 - 16:00', 'venue': 'Lab B4',
                     'capacity': 25, 'parent': 'Lecture B'},
                ]
            },
            {
                'code': 'DB401',
                'name': 'Database Systems',
                'credits': 3,
                'description': 'Relational databases, SQL, normalization, and transactions.',
                'sub_type': 'Tutorial',   # this course uses Tutorials only
                'sections': [
                    {'name': 'Lecture A', 'type': 'Lecture', 'day': 'Thursday',
                     'time': '10:00 - 12:00', 'venue': 'Auditorium 3',
                     'capacity': 90, 'parent': None},
                    # ── Tutorials under Lecture A ──────────────────────────
                    {'name': 'Tutorial A1', 'type': 'Tutorial', 'day': 'Friday',
                     'time': '08:00 - 09:00', 'venue': 'Room C101',
                     'capacity': 30, 'parent': 'Lecture A'},
                    {'name': 'Tutorial A2', 'type': 'Tutorial', 'day': 'Friday',
                     'time': '09:00 - 10:00', 'venue': 'Room C102',
                     'capacity': 30, 'parent': 'Lecture A'},
                    {'name': 'Tutorial A3', 'type': 'Tutorial', 'day': 'Saturday',
                     'time': '08:00 - 09:00', 'venue': 'Room C103',
                     'capacity': 30, 'parent': 'Lecture A'},
                ]
            },
        ]

        for data in courses_data:
            course = Course(
                course_code=data['code'],
                course_name=data['name'],
                credit_hours=data['credits'],
                description=data['description'],
                sub_component_type=data['sub_type']
            )
            db.session.add(course)
            db.session.flush()

            # Pass 1: create all sections
            name_map = {}
            for sec in data['sections']:
                s = Section(
                    section_name=sec['name'],
                    section_type=sec['type'],
                    day=sec['day'],
                    time=sec['time'],
                    venue=sec['venue'],
                    max_capacity=sec['capacity'],
                    course_id=course.id,
                    parent_lecture_id=None
                )
                db.session.add(s)
                db.session.flush()
                name_map[sec['name']] = s

            # Pass 2: wire up parent_lecture_id
            for sec in data['sections']:
                if sec['parent']:
                    name_map[sec['name']].parent_lecture_id = name_map[sec['parent']].id

        db.session.commit()
        print('[Seed] 3 courses with Lecture + Tutorial/Lab sections created.')


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(debug=True)
