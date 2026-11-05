import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from database import get_db_connection

app = Flask(__name__)
app.secret_key = "uet_se_lost_found_secret_key"
bcrypt = Bcrypt(app)

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Validates allowed image file extensions (FR-ITEM-04)."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def log_audit(actor_id, action, target_id, old_state, new_state):
    """Appends an immutable entry to the audit log (FR-ADM-04, FR-ADM-05)."""
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO audit_logs (actor_user_id, action_type, target_record_id, old_state, new_state, client_ip) VALUES (?, ?, ?, ?, ?, ?)",
        (actor_id, action, target_id, old_state, new_state, request.remote_addr)
    )
    conn.commit()
    conn.close()

# --- 1. Public Item Catalog (FR-AUTH-01, FR-ITEM-08, FR-ITEM-09) ---
@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    report_type = request.args.get("type", "").strip()

    sql = "SELECT * FROM items WHERE current_state NOT IN ('RETURNED', 'UNCLAIMED_DISPOSED', 'ARCHIVED')"
    params = []

    if query:
        sql += " AND (general_description LIKE ? OR category LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if category:
        sql += " AND category = ?"
        params.append(category)
    if report_type:
        sql += " AND report_type = ?"
        params.append(report_type)

    sql += " ORDER BY event_date DESC"

    conn = get_db_connection()
    items = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("index.html", items=items, query=query, category=category, report_type=report_type)

# --- 2. Authentication (FR-AUTH-02, FR-AUTH-03) ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]

        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (name, email, role, password_hash) VALUES (?, ?, ?, ?)",
                         (name, email, role, password_hash))
            conn.commit()
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except:
            flash("Email already registered. Try logging in.", "danger")
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user["password_hash"], password):
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            flash("Logged in successfully!", "success")
            return redirect(url_for("index"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

# --- 3. Item Reporting (FR-ITEM-01, FR-ITEM-02, FR-ITEM-04) ---
@app.route("/report", methods=["GET", "POST"])
def report_item():
    if "user_id" not in session:
        flash("Please log in to report an item.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        report_type = request.form["report_type"]
        category = request.form["category"]
        description = request.form["description"]
        location = request.form["location"]
        event_date = request.form["event_date"]
        photo_file = request.files.get("photo")

        photo_url = None
        if photo_file and allowed_file(photo_file.filename):
            filename = secure_filename(photo_file.filename)
            photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            photo_url = f"/static/uploads/{filename}"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO items (reporter_id, report_type, category, general_description, campus_location, event_date, photo_url, current_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'REPORTED')
        """, (session["user_id"], report_type, category, description, location, event_date, photo_url))
        new_item_id = cursor.lastrowid
        conn.commit()
        conn.close()

        log_audit(session["user_id"], "CREATE_REPORT", new_item_id, None, "REPORTED")
        flash("Item report filed successfully!", "success")
        return redirect(url_for("index"))

    return render_template("report.html")

# --- 4. Ownership Claim Submission (FR-CLM-01, FR-CLM-03, FR-CLM-04) ---
@app.route("/claim/<int:item_id>", methods=["POST"])
def submit_claim(item_id):
    if "user_id" not in session:
        flash("Please log in to claim an item.", "warning")
        return redirect(url_for("login"))

    proof_answers = request.form["proof_answers"]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO claims (item_id, claimant_id, proof_answers, status)
        VALUES (?, ?, ?, 'PENDING_REVIEW')
    """, (item_id, session["user_id"], proof_answers))
    claim_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log_audit(session["user_id"], "SUBMIT_CLAIM", claim_id, None, "PENDING_REVIEW")
    flash("Claim submitted. A custodian will review your proof.", "success")
    return redirect(url_for("index"))

# --- 5. Custodian Management & Verification (FR-CUS-01, FR-CLM-05, FR-HND-01) ---
@app.route("/custody")
def custody_dashboard():
    if session.get("role") not in ("CUSTODIAN", "ADMIN"):
        flash("Unauthorized. Custodian access required.", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    intake_items = conn.execute("SELECT * FROM items WHERE report_type = 'FOUND' AND current_state = 'REPORTED'").fetchall()
    held_items = conn.execute("SELECT * FROM items WHERE current_state = 'IN_CUSTODY'").fetchall()
    claims = conn.execute("""
        SELECT c.*, i.general_description, i.category, u.name as claimant_name, u.email as claimant_email
        FROM claims c
        JOIN items i ON c.item_id = i.item_id
        JOIN users u ON c.claimant_id = u.user_id
        WHERE c.status NOT IN ('HANDOVER_COMPLETED', 'REJECTED')
    """).fetchall()
    conn.close()

    return render_template("custody.html", intake_items=intake_items, held_items=held_items, claims=claims)

@app.route("/custody/intake", methods=["POST"])
def record_intake():
    if session.get("role") not in ("CUSTODIAN", "ADMIN"):
        return redirect(url_for("index"))

    item_id = request.form["item_id"]
    storage_loc = request.form["storage_location"]

    conn = get_db_connection()
    conn.execute("UPDATE items SET current_state = 'IN_CUSTODY' WHERE item_id = ?", (item_id,))
    conn.execute("INSERT INTO custodial_logs (item_id, custodian_id, storage_location, action_type) VALUES (?, ?, ?, 'INTAKE')",
                 (item_id, session["user_id"], storage_loc))
    conn.commit()
    conn.close()

    log_audit(session["user_id"], "CUSTODY_INTAKE", item_id, "REPORTED", "IN_CUSTODY")
    flash(f"Item #{item_id} logged into custody at {storage_loc}.", "success")
    return redirect(url_for("custody_dashboard"))

@app.route("/claims/adjudicate", methods=["POST"])
def adjudicate_claim():
    if session.get("role") not in ("CUSTODIAN", "ADMIN"):
        return redirect(url_for("index"))

    claim_id = request.form["claim_id"]
    decision = request.form["decision"]
    reason = request.form.get("reason", "")

    conn = get_db_connection()
    claim = conn.execute("SELECT status FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    old_status = claim["status"]

    conn.execute("""
        UPDATE claims 
        SET status = ?, decision_reason = ?, adjudicated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE claim_id = ?
    """, (decision, reason, session["user_id"], claim_id))
    conn.commit()
    conn.close()

    log_audit(session["user_id"], "ADJUDICATE_CLAIM", claim_id, old_status, decision)
    flash(f"Claim #{claim_id} updated to {decision}.", "info")
    return redirect(url_for("custody_dashboard"))

@app.route("/custody/handover", methods=["POST"])
def complete_handover():
    if session.get("role") not in ("CUSTODIAN", "ADMIN"):
        return redirect(url_for("index"))

    claim_id = request.form["claim_id"]
    item_id = request.form["item_id"]
    claimant_id = request.form["claimant_id"]
    id_verified = 1 if request.form.get("campus_id_verified") == "on" else 0

    if not id_verified:
        flash("Physical Campus ID verification is mandatory before release!", "danger")
        return redirect(url_for("custody_dashboard"))

    conn = get_db_connection()
    conn.execute("INSERT INTO handover_records (item_id, claim_id, claimant_id, custodian_id, campus_id_verified) VALUES (?, ?, ?, ?, ?)",
                 (item_id, claim_id, claimant_id, session["user_id"], id_verified))
    conn.execute("UPDATE items SET current_state = 'RETURNED' WHERE item_id = ?", (item_id,))
    conn.execute("UPDATE claims SET status = 'HANDOVER_COMPLETED' WHERE claim_id = ?", (claim_id,))
    conn.commit()
    conn.close()

    log_audit(session["user_id"], "EXECUTE_HANDOVER", item_id, "IN_CUSTODY", "RETURNED")
    flash("Handover successfully completed! Item marked as RETURNED.", "success")
    return redirect(url_for("custody_dashboard"))

# --- 6. Admin Dashboard & Metrics (FR-ADM-04, FR-ADM-06) ---
@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "ADMIN":
        flash("Administrator access required.", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    metrics = {
        "total_reported": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "in_custody": conn.execute("SELECT COUNT(*) FROM items WHERE current_state = 'IN_CUSTODY'").fetchone()[0],
        "pending_claims": conn.execute("SELECT COUNT(*) FROM claims WHERE status = 'PENDING_REVIEW'").fetchone()[0],
        "returned": conn.execute("SELECT COUNT(*) FROM items WHERE current_state = 'RETURNED'").fetchone()[0],
    }
    audit_trail = conn.execute("""
        SELECT a.*, u.name as actor_name 
        FROM audit_logs a 
        LEFT JOIN users u ON a.actor_user_id = u.user_id 
        ORDER BY a.timestamp DESC LIMIT 50
    """).fetchall()
    conn.close()

    return render_template("admin.html", metrics=metrics, audit_trail=audit_trail)

if __name__ == "__main__":
    app.run(debug=True, port=5000)