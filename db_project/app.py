from flask import Flask, render_template, request, redirect, url_for, flash, session
from db import get_connection 
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "secretkey" 

def get_pagination_pages(current_page, total_pages, delta=2):
    pages = []
    for p in range(1, total_pages + 1):
        if p == 1 or p == total_pages or abs(p - current_page) <= delta:
            pages.append(p)
        elif pages[-1] != '...':
            pages.append('...')
    return pages

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            flash("Please do not leave the email and password fields blank.", "warning")
            return render_template("login.html")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = "SELECT * FROM user WHERE Email = %s AND PasswordHash = %s"
        cursor.execute(query, (email, password))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user:
            session["user_id"] = user["UserID"]
            session["user_type"] = user["UserType"]
            session["user_name"] = user["FullName"].split()[0]

            user_type = user["UserType"].lower()

            if user_type == "citizen":
                return redirect(url_for("citizen_dashboard"))
            elif user_type == "worker":
                return redirect(url_for("worker_dashboard"))
            elif user_type == "official":
                return redirect(url_for("official_dashboard"))
            else:
                flash("Unidentified user type.", "danger")
                return redirect(url_for("login"))

        else:
            flash("Email or password is incorrect.", "danger")

    return render_template("login.html")

@app.route("/citizen", methods=["GET", "POST"])
def citizen_dashboard():
    if session.get("user_type") != "Citizen":
        flash("Unauthorized access!", "danger")
        return redirect(url_for("login"))
    
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        try:
            if form_type == 'waste_report':
                waste_type = request.form.get('type')
                weight = request.form.get('weight')
                date = request.form.get('date')
                collection_point = request.form.get('collection_point')

                if not all([waste_type, weight, date, collection_point]):
                    flash("Make sure you fill in all fields.", "warning")
                else:
                    weight = float(weight)
                    collection_point = int(collection_point)

                    cursor.execute(
                        "INSERT INTO Waste (Type, WeightKg, WasteDate, UserID, CollectionPointID) VALUES (%s, %s, %s, %s, %s)",
                        (waste_type, weight, date, session['user_id'], collection_point)
                    )
                    new_waste_id = cursor.lastrowid
                    conn.commit()
                    flash("Your waste notification has been saved successfully.", "success")
                    session['new_waste_id'] = new_waste_id

            elif form_type == 'update_password':
                current_password = request.form.get('current_password')
                new_password = request.form.get('new_password')
                confirm_password = request.form.get('confirm_password')

                if not current_password or not new_password or not confirm_password:
                    flash("Please fill in all password fields.", "warning")
                elif new_password != confirm_password:
                    flash("The new password and the re-entered password do not match.", "danger")
                else:
                    cursor.execute("SELECT PasswordHash FROM User WHERE UserID = %s", (session['user_id'],))
                    user = cursor.fetchone()
                    
                    if not user:
                        flash("User not found.", "danger")
                    elif not user['PasswordHash']:
                        flash("User password information not found.", "danger")
                    else:
                        print("DB hash:", user['PasswordHash'])
                        print("Girilen şifre:", current_password)

                    if user and user['PasswordHash'] == current_password:
                        new_hash = new_password 
                        cursor.execute("UPDATE User SET PasswordHash = %s WHERE UserID = %s", (new_hash, session['user_id']))
                        conn.commit()
                        flash("Your password has been updated successfully..", "success")
                    else:
                        flash("Your current password is incorrect.", "danger")

            elif form_type == 'delete_account':
                try:
                    cursor.execute("DELETE FROM waste WHERE UserID = %s", (session['user_id'],))
                    cursor.execute("DELETE FROM User WHERE UserID = %s", (session['user_id'],))
                    conn.commit()
                    flash("Your account has been deleted successfully.", "success")
                    cursor.close()
                    conn.close()
                    session.clear()
                    return redirect(url_for('login'))
                except Exception as e:
                    conn.rollback()
                    flash(f"An error occurred during account deletion: {str(e)}", "danger")

        except ValueError:
            flash("Please enter a valid value.", "danger")
        except Exception as e:
            conn.rollback()
            flash(f"An error occurred: {str(e)}", "danger")

    cursor.execute("""
        SELECT Waste.WasteID, Waste.Type, Waste.WeightKg, Waste.WasteDate, CollectionPoint.Name as CollectionPointName,
               RecyclingResult.RecycledWeightKg
        FROM Waste
        LEFT JOIN CollectionPoint ON Waste.CollectionPointID = CollectionPoint.CollectionPointID
        LEFT JOIN RecyclingResult ON Waste.WasteID = RecyclingResult.WasteID
        WHERE Waste.UserID = %s
        ORDER BY Waste.WasteDate DESC
    """, (session['user_id'],))
    wastes = cursor.fetchall()

    cursor.execute("SELECT * FROM CollectionPoint")
    collection_points = cursor.fetchall()

    new_waste_id = session.pop('new_waste_id', None)

    cursor.close()
    conn.close()

    return render_template('citizen.html', user_name=session['user_name'], wastes=wastes, collection_points=collection_points, new_waste_id=new_waste_id)
@app.route("/worker", methods=["GET"])
def worker_dashboard():
    if session.get("user_type") != "Worker":
        flash("Unauthorized access!", "danger")
        return redirect(url_for("login"))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT cp.Name AS CollectionPointName, cp.CollectionPointID
        FROM WorkerAssignment wa
        JOIN CollectionPoint cp ON wa.CollectionPointID = cp.CollectionPointID
        WHERE wa.UserID = %s
    """, (session['user_id'],))
    assignments = cursor.fetchall()

    wastes = []
    total_records = 0
    page = request.args.get('page', 1, type=int)
    per_page = 10  
    total_pages = 1

    collection_point_ids = [a['CollectionPointID'] for a in assignments]

    if collection_point_ids:
        placeholders = ', '.join(['%s'] * len(collection_point_ids))

        count_query = f"""
            SELECT COUNT(*) as total
            FROM Waste w
            WHERE w.CollectionPointID IN ({placeholders})
        """
        cursor.execute(count_query, collection_point_ids)
        total_records = cursor.fetchone()['total']
        total_pages = (total_records + per_page - 1) // per_page 

        data_query = f"""
            SELECT w.WasteID, w.Type, w.WeightKg, w.WasteDate, cp.Name AS CollectionPointName
            FROM Waste w
            JOIN CollectionPoint cp ON w.CollectionPointID = cp.CollectionPointID
            WHERE w.CollectionPointID IN ({placeholders})
            ORDER BY w.WasteDate DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(data_query, collection_point_ids + [per_page, (page - 1) * per_page])
        wastes = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('worker.html',
                           user_name=session['user_name'],
                           assignments=assignments,
                           wastes=wastes,
                           page=page,
                           total_pages=total_pages,pagination_pages=get_pagination_pages(page, total_pages))



@app.route("/official")
def official_dashboard():
    if session.get("user_type") != "Official":
        flash("Unauthorized access!", "danger")
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT CollectionPointID FROM ManagerRegion WHERE UserID = %s", (user_id,))
    points = cursor.fetchall()
    if not points:
        flash("There is no collection point assigned to you.", "warning")
        cursor.close()
        conn.close()
        return redirect(url_for("login"))

    collection_point_ids = [p["CollectionPointID"] for p in points]
    placeholders = ','.join(['%s'] * len(collection_point_ids))

    cursor.execute(f"SELECT * FROM CollectionPoint WHERE CollectionPointID IN ({placeholders})", tuple(collection_point_ids))
    collection_points = cursor.fetchall()

    cursor.execute(f"""
        SELECT u.UserID, u.FullName, cp.Name AS CollectionPointName
        FROM WorkerAssignment wa
        JOIN User u ON wa.UserID = u.UserID
        JOIN CollectionPoint cp ON wa.CollectionPointID = cp.CollectionPointID
        WHERE wa.CollectionPointID IN ({placeholders}) AND u.UserType = 'Worker'
    """, tuple(collection_point_ids))
    workers = cursor.fetchall()

    cursor.execute(f"""
        SELECT w.WasteID, w.Type, w.WeightKg, w.WasteDate, cp.Name AS CollectionPointName, u.FullName AS UserName
        FROM Waste w
        JOIN CollectionPoint cp ON w.CollectionPointID = cp.CollectionPointID
        JOIN User u ON w.UserID = u.UserID
        WHERE w.CollectionPointID IN ({placeholders})
        ORDER BY w.WasteDate DESC
    """, tuple(collection_point_ids))
    wastes = cursor.fetchall()

    today = datetime.today().date()
    start_of_tomorrow = today + timedelta(days=1)

    cursor.execute(f"""
        SELECT SUM(w.WeightKg) AS DailyTotal
        FROM Waste w
        WHERE w.CollectionPointID IN ({placeholders})
          AND w.WasteDate >= %s AND w.WasteDate < %s
    """, tuple(collection_point_ids) + (today, start_of_tomorrow))
    daily_result = cursor.fetchone()
    daily_total = daily_result['DailyTotal'] or 0

    first_day_of_month = today.replace(day=1)
    first_day_of_next_month = first_day_of_month + relativedelta(months=1)

    cursor.execute(f"""
        SELECT SUM(w.WeightKg) AS MonthlyTotal
        FROM Waste w
        WHERE w.CollectionPointID IN ({placeholders})
          AND w.WasteDate >= %s AND w.WasteDate < %s
    """, tuple(collection_point_ids) + (first_day_of_month, first_day_of_next_month))
    monthly_result = cursor.fetchone()
    monthly_total = monthly_result['MonthlyTotal'] or 0

    for w in wastes:
        w['UserName'] = "Anonim"

    cursor.close()
    conn.close()

    analysis_text = f"Daily waste amount: {daily_total:.2f} kg\nMonthly waste amount: {monthly_total:.2f} kg"

    return render_template("manager.html",
                           collection_points=collection_points,
                           workers=workers,
                           wastes=wastes,
                           daily_total=daily_total,
                           monthly_total=monthly_total,
                           user_name=session.get("user_name"),
                           analysis_text=analysis_text)

@app.route("/official/remove_worker", methods=["POST"])
def remove_worker():
    if session.get("user_type") != "Official":
        flash("Unauthorized access!", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    worker_id = request.form.get("worker_id")
    collection_point_id = request.form.get("collection_point")

    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM ManagerRegion WHERE UserID = %s AND CollectionPointID = %s", (user_id, collection_point_id))
    if not cursor.fetchone():
        flash("You are not authorized to this collection point.", "danger")
        cursor.close()
        conn.close()
        return redirect(url_for("official_dashboard"))

    cursor.execute("DELETE FROM WorkerAssignment WHERE UserID = %s AND CollectionPointID = %s", (worker_id, collection_point_id))
    conn.commit()
    cursor.close()
    conn.close()

    flash("The employee was removed successfully.", "success")
    return redirect(url_for("official_dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        password = request.form.get("password")
        user_type = request.form.get("user_type")

        if not all([full_name, email, password, user_type]):
            flash("Please fill in all fields.", "warning")
            return render_template("register.html")

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM user WHERE Email = %s", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            flash("This email has already been registered.", "danger")
            cursor.close()
            conn.close()
            return render_template("register.html")

        cursor.execute("""
            INSERT INTO user (FullName, Email, PasswordHash, UserType)
            VALUES (%s, %s, %s, %s)
        """, (full_name, email, password, user_type))

        conn.commit()
        cursor.close()
        conn.close()

        flash("Registration successful! You can log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout", methods=["","POST"])
def logout():
    session.clear()
    flash("You have successfully logged out.", "success")
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
