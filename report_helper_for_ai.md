# AI Report Generation Helper - MMU Student Enrollment System

**Instructions for the AI generating the report:**
This document contains the exact technical details, business logic, and architecture of the implemented system. Use these details to generate the "TSE6223 SOFTWARE ENGINEERING FUNDAMENTALS" project report. Ensure the generated report strictly reflects what is actually coded below to guarantee a high grade in the "System & Report Alignment" criteria.

## 1. System Overview
*   **Project Title:** MMU Student Enrollment System
*   **Type of Application:** Web Application
*   **Technology Stack:**
    *   **Backend:** Python 3, Flask framework.
    *   **Database:** SQLite using Flask-SQLAlchemy (ORM).
    *   **Security:** Werkzeug (for password hashing/salting).
    *   **Frontend:** HTML5, CSS3, Jinja2 templating, Bootstrap 5 (for UI components).

## 2. Functional Requirements (FR)
Based on the code, the system implements the following:
*   **User Management & Authentication:**
    *   Users can log in using unique usernames and securely hashed passwords.
    *   Role-based access control separates 'Admin' and 'Student' dashboards and routes.
*   **Admin Capabilities:**
    *   Add new courses (Course Code, Name, Credit Hours, Description).
    *   Add sections to courses (Lecture, Tutorial, Lab) with attributes: Day, Time, Venue, and Max Capacity.
    *   Manage structural integrity: The admin decides if a course has a 'Tutorial' or 'Lab' sub-component.
    *   View all enrolled students for any specific section.
*   **Student Capabilities:**
    *   View all available courses and their corresponding sections (Lectures and Sub-sections).
    *   Enroll in a course: The student must select a Lecture AND its corresponding Sub-section (Tutorial/Lab) simultaneously.
    *   View their personalized timetable.
    *   Drop a course/lecture.

## 3. Non-Functional Requirements (NFR)
*   **Security:** Passwords are never stored in plain text (uses PBKDF2 hashing via `generate_password_hash`). Unauthorized access to admin routes is blocked using custom decorators.
*   **Data Integrity & Reliability:** Database transactions are used. If an error occurs during multi-step processes (like enrolling in two sections), the transaction rolls back.
*   **Usability:** Uses Flask 'flash' messages to provide immediate, clear feedback (e.g., "Time clash detected", "Successfully enrolled").

## 4. Complex Business Logic (CRITICAL for "Functionality Accuracy" Marks)
*When writing the report, heavily emphasize these features as they show advanced software engineering understanding:*
1.  **Atomic Pair Enrollment:** The system forces students to enroll in both a Lecture and a Sub-section (Tutorial/Lab) in a single form submission. They cannot be enrolled in one without the other.
2.  **Time-Clash Validation (`check_time_clash`):** Before saving an enrollment, the backend cross-references the selected section's "Day" and "Time" with the student's existing enrollments to ensure they do not overlap.
3.  **Course Structure Lock (XOR constraint):** A course can have either (Lecture + Tutorial) OR (Lecture + Lab). The first time an admin adds a sub-section, the course's `sub_component_type` is permanently locked to that type.
4.  **Drop Cascade:** If a student drops a Lecture, the system automatically identifies and drops the dependent child sub-section (Tutorial/Lab) to prevent orphaned enrollments.
5.  **Capacity Enforcement:** The system actively checks `enrolled_count` against `max_capacity`. It rejects enrollments if `is_full` is true.

## 5. Database Schema & Design Modelling (For UML / ERD)
*   **Users Table:** `id` (PK), `username` (Unique), `password_hash`, `full_name`, `role` (student/admin).
*   **Courses Table:** `id` (PK), `course_code` (Unique), `course_name`, `credit_hours`, `description`, `sub_component_type`.
*   **Sections Table:** `id` (PK), `course_id` (FK to Courses), `parent_lecture_id` (FK to Sections.id - Self-referential relationship for parent-child lectures/tutorials), `section_name`, `section_type`, `day`, `time`, `venue`, `max_capacity`.
*   **Enrollments Table:** `id` (PK), `user_id` (FK to Users), `section_id` (FK to Sections), `enrolled_at`. Contains a Unique Constraint on `(user_id, section_id)` to prevent double booking.

## 6. Testing Strategies Used (To be included in the report)
*   **Unit Testing (Conceptual):** Testing edge cases for capacity limits and time-clash algorithms.
*   **Integration Testing:** Verifying that the dropping of a parent lecture successfully cascades the drop to the child tutorial via the database relationships.
*   **Validation Testing:** Attempting to submit forms with missing data or bypassing HTML validation to ensure backend validation catches it.
