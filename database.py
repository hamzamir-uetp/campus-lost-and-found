import sqlite3

DATABASE_NAME = "campus_lost_found.db"

def get_db_connection():
    """Connects to the database and allows accessing columns by name."""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes tables matching the SRS conceptual data model."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users table (Student, Custodian, Admin)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        role TEXT CHECK(role IN ('STUDENT', 'CUSTODIAN', 'ADMIN')) NOT NULL,
        password_hash TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Items table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER REFERENCES users(user_id),
        report_type TEXT CHECK(report_type IN ('LOST', 'FOUND')) NOT NULL,
        category TEXT NOT NULL,
        general_description TEXT NOT NULL,
        campus_location TEXT NOT NULL,
        event_date DATE NOT NULL,
        photo_url TEXT,
        current_state TEXT CHECK(current_state IN ('REPORTED', 'IN_CUSTODY', 'RETURNED', 'UNCLAIMED_DISPOSED', 'ARCHIVED')) DEFAULT 'REPORTED',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Claims table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER REFERENCES items(item_id),
        claimant_id INTEGER REFERENCES users(user_id),
        proof_answers TEXT NOT NULL,
        custodian_prompt TEXT,
        claimant_reply TEXT,
        status TEXT CHECK(status IN ('PENDING_REVIEW', 'NEEDS_MORE_INFO', 'APPROVED', 'REJECTED', 'HANDOVER_COMPLETED')) DEFAULT 'PENDING_REVIEW',
        decision_reason TEXT,
        adjudicated_by INTEGER REFERENCES users(user_id),
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Custodial Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custodial_logs (
        custody_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER REFERENCES items(item_id),
        custodian_id INTEGER REFERENCES users(user_id),
        storage_location TEXT NOT NULL,
        action_type TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 5. Handover Records table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS handover_records (
        handover_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER UNIQUE REFERENCES items(item_id),
        claim_id INTEGER UNIQUE REFERENCES claims(claim_id),
        claimant_id INTEGER REFERENCES users(user_id),
        custodian_id INTEGER REFERENCES users(user_id),
        campus_id_verified INTEGER NOT NULL DEFAULT 0,
        handover_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 6. Immutable Audit Log table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER REFERENCES users(user_id),
        action_type TEXT NOT NULL,
        target_record_id INTEGER NOT NULL,
        old_state TEXT,
        new_state TEXT,
        client_ip TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()