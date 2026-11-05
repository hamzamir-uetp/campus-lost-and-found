# Automated Campus Lost & Found System

A secure, role-based web application designed to streamline campus property intake, verification, custody tracking, and handover while preventing fraudulent claims and maintaining an immutable audit trail.

Built strictly according to Software Requirements Specification (SRS) standards using Python, Flask, SQLite, and Bootstrap 5.

---

## 📌 Architecture & Design Highlights

- **Multi-Role Access Control (RBAC):** Dedicated permissions for `STUDENT`, `CUSTODIAN`, and `ADMIN`.
- **Decoupled Fraud Prevention:** Public catalog displays only high-level details. Distinguishing identifiers (e.g., serial numbers, private marks) are held securely for ownership adjudication.
- **Physical Custody Tracking:** Custodians assign specific physical storage lockers/bins during intake.
- **Mandatory In-Person Handover:** Releasing property strictly enforces visual confirmation of a physical Campus ID Card.
- **Immutable Audit Trail:** Append-only ledger recording all actor actions, state transitions, timestamps, and client IP addresses.

---

## 🛠️ Tech Stack

- **Backend:** Python 3, Flask, Jinja2
- **Database / ORM:** SQLite 3, SQLAlchemy
- **Security:** Flask-Bcrypt (password hashing), HTTP Session Management
- **Frontend:** Bootstrap 5, Vanilla JavaScript

---

## 🚀 Setup & Local Execution

### 1. Clone the Repository
```bash
git clone [https://github.com/](https://github.com/)<your-username>/campus-lost-and-found.git
cd campus-lost-and-found