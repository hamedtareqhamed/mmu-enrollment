# MMU Student Enrollment System

A lightweight, robust web application built with Python (Flask), SQLite, and Bootstrap 5 for managing university course enrollments. Designed with strict academic hierarchies (Lecture -> Tutorial/Lab) and automatic time-clash prevention.

## Official Group Members
- hamed albazeli
- Mohamed Amer Hassan
- Gharawi, Muhannad Mohammed
- Basil Idris Ibrahim Idris

---

## How to Run the Project

Follow these steps to run the system locally on your machine.

### Prerequisites
Make sure you have **Python 3.8+** installed on your computer.

### Step 1: Open the Terminal
Open your command prompt or terminal and navigate to the project directory:
```bash
cd mmu-enrollment
```

### Step 2: Create a Virtual Environment
It is highly recommended to use a virtual environment to manage project dependencies.
*   **Mac/Linux:** `python3 -m venv venv`
*   **Windows:** `python -m venv venv`

### Step 3: Activate the Virtual Environment
*   **Mac/Linux:** `source venv/bin/activate`
*   **Windows (Command Prompt):** `venv\Scripts\activate`
*   **Windows (PowerShell):** `venv\Scripts\Activate.ps1`

### Step 4: Install Dependencies
Install Flask, SQLAlchemy, and other requirements:
```bash
pip install -r requirements.txt
```

### Step 5: Run the Application
Start the Flask development server:
```bash
python app.py
```
*Note: The database (`enrollment.db`) will be created automatically, and the default accounts and sample courses will be seeded into it on the very first run.*

### Step 6: Access the Application
Open your web browser and go to:
**http://127.0.0.1:5000**

---

## Demo Accounts

You can log in immediately using the following seeded test accounts:

**Admin Account**
- **Username:** `admin`
- **Password:** `admin123`

**Student Accounts**
- **Usernames:** `hamed`, `mohamed`, `muhannad`, `basil`
- **Password:** `student123` (for all students)

---

## Troubleshooting

**Database Schema Errors (e.g., Missing Columns):**
If you pull new updates that modify the database schema, SQLite does not automatically alter existing tables. You must delete the old database file to let the system generate a fresh one:
1. Stop the server (`Ctrl + C`).
2. Delete the database file: `rm instance/enrollment.db` (Mac/Linux) or `del instance\enrollment.db` (Windows).
3. Run `python app.py` again.