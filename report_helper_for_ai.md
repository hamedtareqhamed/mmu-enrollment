# AI Report Generation Helper - MMU Student Enrollment System

**Instructions for the AI generating the report:**
This document contains the exact technical details, business logic, architecture, and UI/UX design of the implemented system. Use these details to generate the "TSE6223 SOFTWARE ENGINEERING FUNDAMENTALS" project report. Ensure the generated report strictly reflects what is actually coded below to guarantee a high grade in the "System & Report Alignment" criteria. **Do not fabricate any features.**

## 1. System Overview
*   **Project Title:** MMU Student Enrollment System
*   **Type of Application:** Web Application
*   **Codebase Size:** Over 2000 lines of functional code (excluding auxiliary scripts).
*   **Technology Stack:**
    *   **Backend:** Python 3, Flask framework.
    *   **Database:** SQLite using Flask-SQLAlchemy (ORM).
    *   **Security:** Werkzeug (for robust password hashing: PBKDF2).
    *   **Frontend:** HTML5, CSS3, Jinja2 templating, Bootstrap 5, Bootstrap Icons, Vanilla JavaScript.

## 2. Functional Requirements (FR)
*Based exactly on the current codebase:*
*   **User Management & Authentication:**
    *   Users log in using unique usernames and securely hashed passwords.
    *   Role-Based Access Control (RBAC) separates 'Admin' and 'Student' dashboards and restricts route access using `@login_required` and `@admin_required` decorators.
*   **Admin Capabilities:**
    *   Add new courses (Course Code, Name, Credit Hours, Description).
    *   Add sections to courses (Lecture, Tutorial, Lab) with attributes: Day, Time, Venue, and Max Capacity.
    *   Manage structural integrity: The admin decides if a course uses 'Tutorials' or 'Labs'.
    *   View all enrolled students for any specific section.
*   **Student Capabilities:**
    *   Browse the course catalog containing all available courses and their corresponding sections (Lectures and Sub-sections).
    *   Enroll in a course: Students select a Lecture and a dynamically filtered Sub-section (Tutorial/Lab) simultaneously.
    *   View their personalized timetable with options to toggle between a "Grid View" (Calendar style) and a "List View".
    *   Drop a course (Dropping a Lecture).

## 3. Non-Functional Requirements (NFR)
*   **User Interface (UI) & User Experience (UX):**
    *   **Dynamic Forms:** In the enrollment catalog, selecting a Lecture uses JavaScript to instantly filter and display only the Tutorials/Labs associated with that specific Lecture.
    *   **Advanced Timetable Grid:** The timetable features a dynamic grid (Monday-Saturday, 08:00 to 18:00) matching modern calendar apps (e.g., Apple/Google Calendar). Events span multiple hours using calculated HTML `rowspan`.
    *   **Customizable View:** Students can use interactive checkboxes to toggle the display of Course Code, Course Name, Section Type, and Venue in real-time.
    *   **Print-Optimized Layout:** Using `@media print` CSS, the timetable automatically switches to landscape mode, hides non-essential UI elements (buttons, navbars), and ensures the grid fits perfectly on paper without cutoff.
*   **Security:** Passwords are never stored in plain text. Custom Python decorators prevent URL manipulation (e.g., a student forcing access to `/admin/dashboard`).
*   **Usability:** System uses Flask 'flash' messages to provide immediate, clear feedback on all actions (e.g., "Time clash detected", "Successfully enrolled", "Dropped from...").

## 4. Complex Business Logic (CRITICAL for "Functionality Accuracy" Marks)
*When writing the report, heavily emphasize these features as they show advanced software engineering understanding:*
1.  **Atomic Pair Enrollment:** The system forces students to enroll in both a Lecture and a Sub-section (Tutorial/Lab) in a single form submission. Database transactions ensure that either both are saved, or neither is, preventing data anomalies.
2.  **Time-Clash Validation (`check_time_clash`):** Before saving an enrollment, the backend actively parses the selected section's "Day" and "Time" (e.g., "10:00 - 12:00") and cross-references it with every existing class in the student's schedule to block overlapping enrollments.
3.  **Course Structure Lock (XOR constraint):** A course can have either (Lecture + Tutorial) OR (Lecture + Lab). The first time an admin adds a sub-section, the course's `sub_component_type` is permanently locked to that type at the database level.
4.  **Drop Cascade:** If a student drops a Lecture, the system automatically identifies and drops the dependent child sub-section (Tutorial/Lab) associated with that specific lecture to prevent orphaned enrollments.
5.  **Capacity Enforcement:** The system actively calculates `enrolled_count` against `max_capacity` dynamically. It rejects enrollments if `is_full` returns true.

## 5. Database Schema & Design Modelling (For UML / ERD)
*   **Users Table:** `id` (PK), `username` (Unique), `password_hash`, `full_name`, `role` (student/admin).
*   **Courses Table:** `id` (PK), `course_code` (Unique), `course_name`, `credit_hours`, `description`, `sub_component_type` (Locks to 'Tutorial' or 'Lab').
*   **Sections Table:** `id` (PK), `course_id` (FK to Courses.id), `parent_lecture_id` (FK to Sections.id - A Self-referential relationship used to link Tutorials/Labs strictly to their parent Lecture), `section_name`, `section_type`, `day`, `time`, `venue`, `max_capacity`.
*   **Enrollments Table:** `id` (PK), `user_id` (FK to Users.id), `section_id` (FK to Sections.id), `enrolled_at`. Contains a strict composite Unique Constraint on `(user_id, section_id)` to prevent double booking.

## 6. Testing Strategies
*   **End-to-End (E2E) Simulation:** The project utilizes automated testing scripts (`run_e2e_tests.py` logic) simulating full user journeys from Admin course creation to Student enrollment, time-clash provocation, and drop-cascade validation.
*   **Integration Testing:** Verifying that dropping a parent lecture successfully cascades the drop to the child tutorial via database relationships.
*   **Validation Testing:** Boundary and edge-case testing for capacity limits and overlapping time algorithms.