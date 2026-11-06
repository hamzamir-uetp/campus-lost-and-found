import sqlite3

DATABASE_NAME = "campus.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('STUDENT', 'CUSTODIAN', 'ADMIN')),
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Items Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL,
        report_type TEXT NOT NULL CHECK(report_type IN ('LOST', 'FOUND')),
        category TEXT NOT NULL,
        general_description TEXT NOT NULL,
        campus_location TEXT NOT NULL,
        event_date DATE NOT NULL,
        photo_url TEXT,
        current_state TEXT NOT NULL CHECK(current_state IN ('REPORTED', 'IN_CUSTODY', 'CLAIMED', 'RETURNED', 'UNCLAIMED_DISPOSED', 'ARCHIVED')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (reporter_id) REFERENCES users (user_id)
    );
    """)

    # Claims Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        claimant_id INTEGER NOT NULL,
        proof_answers TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING_REVIEW' CHECK(status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'HANDOVER_COMPLETED')),
        decision_reason TEXT,
        adjudicated_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items (item_id),
        FOREIGN KEY (claimant_id) REFERENCES users (user_id),
        FOREIGN KEY (adjudicated_by) REFERENCES users (user_id)
    );
    """)

    # Custodial Action Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custodial_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        custodian_id INTEGER NOT NULL,
        storage_location TEXT NOT NULL,
        action_type TEXT NOT NULL,
        action_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items (item_id),
        FOREIGN KEY (custodian_id) REFERENCES users (user_id)
    );
    """)

    # Handover Records
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS handover_records (
        handover_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        claim_id INTEGER NOT NULL,
        claimant_id INTEGER NOT NULL,
        custodian_id INTEGER NOT NULL,
        campus_id_verified INTEGER NOT NULL DEFAULT 0,
        handover_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items (item_id),
        FOREIGN KEY (claim_id) REFERENCES claims (claim_id),
        FOREIGN KEY (claimant_id) REFERENCES users (user_id),
        FOREIGN KEY (custodian_id) REFERENCES users (user_id)
    );
    """)

    # Audit Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER,
        action_type TEXT NOT NULL,
        target_record_id INTEGER,
        old_state TEXT,
        new_state TEXT,
        client_ip TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (actor_user_id) REFERENCES users (user_id)
    );
    """)

    # Inquiries & Contact Messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inquiries (
        inquiry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_name TEXT NOT NULL,
        sender_email TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        is_urgent INTEGER DEFAULT 0,
        status TEXT DEFAULT 'OPEN',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database tables initialized successfully.")