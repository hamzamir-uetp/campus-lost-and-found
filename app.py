import os
import re
import csv
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
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

STOP_WORDS = {"the", "a", "an", "with", "in", "on", "at", "to", "for", "of", "and", "or", "my"}

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

def find_potential_matches(item_id, report_type, category, description):
    """Auto-matching engine: finds opposing items in the same category with overlapping keywords."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", description.lower())
    keywords = [w for w in words if w not in STOP_WORDS]
    if not keywords:
        return []

    target_type = "FOUND" if report_type == "LOST" else "LOST"
    conn = get_db_connection()
    
    candidates = conn.execute("""
        SELECT item_id, general_description, campus_location, event_date, current_state
        FROM items
        WHERE report_type = ? 
          AND category = ? 
          AND current_state NOT IN ('RETURNED', 'UNCLAIMED_DISPOSED', 'ARCHIVED')
          AND item_id != ?
    """, (target_type, category, item_id)).fetchall()
    conn.close()

    matches = []
    for cand in candidates:
        cand_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", cand["general_description"].lower()))
        overlap = [kw for kw in keywords if kw in cand_words]
        if overlap:
            matches.append({
                "item_id": cand["item_id"],
                "description": cand["general_description"],
                "location": cand["campus_location"],
                "date": cand["event_date"],
                "state": cand["current_state"],
                "matched_words": overlap
            })
    return matches

# --- 1. Public Item Catalog ---
@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    report_type = request.args.get("type", "").strip()

    sql = "SELECT * FROM items WHERE 1=1"
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
    all_items = conn.execute(sql, params).fetchall()
    conn.close()

    active_items = [i for i in all_items if i["current_state"] in ("REPORTED", "IN_CUSTODY")]
    fulfilled_items = [i for i in all_items if i["current_state"] in ("RETURNED", "UNCLAIMED_DISPOSED", "ARCHIVED")]

    return render_template(
        "index.html", 
        active_items=active_items, 
        fulfilled_items=fulfilled_items,
        query=query, 
        category=category, 
        report_type=report_type
    )

# --- 2. Authentication ---
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

# --- 3. Item Reporting ---
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

        potential_matches = find_potential_matches(new_item_id, report_type, category, description)
        if potential_matches:
            flash(f"Report filed! We found {len(potential_matches)} potential match(es) in the inventory.", "info")
            if session.get("role") == "STUDENT":
                return redirect(url_for("my_claims"))
        else:
            flash("Item report filed successfully!", "success")

        return redirect(url_for("index"))

    return render_template("report.html")

# --- 4. Resolve Lost Notice ---
@app.route("/item/resolve/<int:item_id>", methods=["POST"])
def resolve_lost_item(item_id):
    if "user_id" not in session:
        flash("Please log in to manage your reports.", "warning")
        return redirect(url_for("login"))

    conn = get_db_connection()
    item = conn.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()

    if not item:
        conn.close()
        flash("Item not found.", "danger")
        return redirect(url_for("index"))

    if item["reporter_id"] != session["user_id"] and session.get("role") not in ("CUSTODIAN", "ADMIN"):
        conn.close()
        flash("Unauthorized to resolve this report.", "danger")
        return redirect(url_for("index"))

    conn.execute("UPDATE items SET current_state = 'RETURNED' WHERE item_id = ?", (item_id,))
    conn.commit()
    conn.close()

    log_audit(session["user_id"], "RESOLVE_LOST_REPORT", item_id, item["current_state"], "RETURNED")
    flash("Report marked as recovered and archived!", "success")
    return redirect(url_for("index"))

# --- 5. Claims & Student Dashboard ---
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
    return redirect(url_for("my_claims"))

@app.route("/my-claims")
def my_claims():
    if "user_id" not in session:
        flash("Please log in to view your claims.", "warning")
        return redirect(url_for("login"))

    conn = get_db_connection()
    claims = conn.execute("""
        SELECT 
            c.claim_id,
            c.proof_answers,
            c.status AS claim_status,
            i.item_id,
            i.general_description,
            i.category,
            i.campus_location,
            i.current_state AS item_status
        FROM claims c
        JOIN items i ON c.item_id = i.item_id
        WHERE c.claimant_id = ?
        ORDER BY c.claim_id DESC
    """, (session["user_id"],)).fetchall()

    lost_reports = conn.execute("""
        SELECT item_id, general_description, category, campus_location, event_date, current_state
        FROM items
        WHERE reporter_id = ? AND report_type = 'LOST' AND current_state = 'REPORTED'
        ORDER BY event_date DESC
    """, (session["user_id"],)).fetchall()

    matches_by_report = {}
    for r in lost_reports:
        matches = find_potential_matches(r["item_id"], "LOST", r["category"], r["general_description"])
        if matches:
            matches_by_report[r["item_id"]] = matches

    conn.close()

    return render_template(
        "my_claims.html", 
        claims=claims, 
        lost_reports=lost_reports, 
        matches_by_report=matches_by_report
    )

# --- 6. Custodian Desk ---
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
    inquiries = conn.execute("SELECT * FROM inquiries WHERE status = 'OPEN' ORDER BY is_urgent DESC, created_at DESC").fetchall()
    conn.close()

    return render_template("custody.html", intake_items=intake_items, held_items=held_items, claims=claims, inquiries=inquiries)

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
    conn.execute(
        "INSERT INTO handover_records (item_id, claim_id, claimant_id, custodian_id, campus_id_verified) VALUES (?, ?, ?, ?, ?)",
        (item_id, claim_id, claimant_id, session["user_id"], id_verified)
    )
    conn.execute("UPDATE items SET current_state = 'RETURNED' WHERE item_id = ?", (item_id,))
    conn.execute("UPDATE claims SET status = 'HANDOVER_COMPLETED' WHERE claim_id = ?", (claim_id,))
    
    item_info = conn.execute("SELECT category FROM items WHERE item_id = ?", (item_id,)).fetchone()
    if item_info:
        conn.execute("""
            UPDATE items 
            SET current_state = 'RETURNED' 
            WHERE reporter_id = ? 
              AND report_type = 'LOST' 
              AND category = ? 
              AND current_state = 'REPORTED'
        """, (claimant_id, item_info["category"]))

    conn.commit()
    conn.close()

    log_audit(session["user_id"], "EXECUTE_HANDOVER", item_id, "IN_CUSTODY", "RETURNED")
    flash("Handover successfully completed! Item and associated lost reports marked as RETURNED.", "success")
    return redirect(url_for("custody_dashboard"))

# --- 7. Inquiries ---
@app.route("/contact", methods=["POST"])
def submit_contact():
    sender_name = request.form.get("sender_name", "").strip()
    sender_email = request.form.get("sender_email", "").strip()
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()
    is_urgent = 1 if request.form.get("is_urgent") == "on" else 0

    if not (sender_name and sender_email and subject and message):
        flash("Please fill in all inquiry fields.", "warning")
        return redirect(url_for("index") + "#contact-us")

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO inquiries (sender_name, sender_email, subject, message, is_urgent) VALUES (?, ?, ?, ?, ?)",
        (sender_name, sender_email, subject, message, is_urgent)
    )
    conn.commit()
    conn.close()

    flash("Your inquiry has been submitted to the Custodian Desk. We will follow up shortly.", "success")
    return redirect(url_for("index") + "#contact-us")

@app.route("/inquiry/resolve/<int:inquiry_id>", methods=["POST"])
def resolve_inquiry(inquiry_id):
    if session.get("role") not in ("CUSTODIAN", "ADMIN"):
        return redirect(url_for("index"))

    conn = get_db_connection()
    conn.execute("UPDATE inquiries SET status = 'RESOLVED' WHERE inquiry_id = ?", (inquiry_id,))
    conn.commit()
    conn.close()

    flash(f"Inquiry #{inquiry_id} marked as resolved.", "info")
    return redirect(url_for("custody_dashboard"))

# --- 8. Admin Console & CSV Audit Export ---
@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "ADMIN":
        flash("Administrator access required.", "danger")
        return redirect(url_for("index"))

    action_filter = request.args.get("action", "").strip()
    
    conn = get_db_connection()
    metrics = {
        "total_reported": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "in_custody": conn.execute("SELECT COUNT(*) FROM items WHERE current_state = 'IN_CUSTODY'").fetchone()[0],
        "pending_claims": conn.execute("SELECT COUNT(*) FROM claims WHERE status = 'PENDING_REVIEW'").fetchone()[0],
        "returned": conn.execute("SELECT COUNT(*) FROM items WHERE current_state = 'RETURNED'").fetchone()[0],
    }

    sql = """
        SELECT a.*, u.name as actor_name, u.role as actor_role
        FROM audit_logs a 
        LEFT JOIN users u ON a.actor_user_id = u.user_id 
    """
    params = []
    if action_filter:
        sql += " WHERE a.action_type = ?"
        params.append(action_filter)
    sql += " ORDER BY a.timestamp DESC LIMIT 100"

    audit_trail = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template("admin.html", metrics=metrics, audit_trail=audit_trail, action_filter=action_filter)

@app.route("/admin/export-audit")
def export_audit_csv():
    """Generates and streams an official CSV export of immutable audit logs."""
    if session.get("role") != "ADMIN":
        flash("Unauthorized. Administrator credentials required.", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    records = conn.execute("""
        SELECT a.audit_id, a.timestamp, u.name as actor_name, u.role as actor_role, 
               a.action_type, a.target_record_id, a.old_state, a.new_state, a.client_ip
        FROM audit_logs a
        LEFT JOIN users u ON a.actor_user_id = u.user_id
        ORDER BY a.timestamp DESC
    """).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Audit ID", "Timestamp (UTC)", "Actor Name", "Actor Role", 
        "Action Type", "Target Record Ref", "Previous State", "New State", "Client IP"
    ])

    for r in records:
        writer.writerow([
            f"AUD-{r['audit_id']:05d}",
            r["timestamp"],
            r["actor_name"] or "System / Anonymous",
            r["actor_role"] or "N/A",
            r["action_type"],
            r["target_record_id"],
            r["old_state"] or "NULL",
            r["new_state"] or "NULL",
            r["client_ip"] or "127.0.0.1"
        ])

    output.seek(0)
    filename = f"campus_lost_found_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)