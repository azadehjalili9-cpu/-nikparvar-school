
import os, sqlite3, secrets
from pathlib import Path
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, render_template_string, abort
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
DB = ROOT / "nikparvar.db"
app = Flask(__name__)
app.secret_key = os.environ.get("NIKPARVAR_SECRET_KEY", secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

SUBJECTS = ["فارسی", "ریاضی", "علوم", "مطالعات اجتماعی", "قرآن", "هدیه‌های آسمان", "زبان انگلیسی", "هنر", "ورزش", "کار و فناوری"]

def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, student_code TEXT NOT NULL UNIQUE,
          username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'student', status TEXT NOT NULL DEFAULT 'pending',
          class_name TEXT NOT NULL DEFAULT 'ششم', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS grades(
          id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          subject TEXT NOT NULL, score REAL NOT NULL CHECK(score>=0 AND score<=20),
          term TEXT NOT NULL, note TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attendance(
          id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL, status TEXT NOT NULL, note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS behavior(
          id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, description TEXT NOT NULL, day TEXT DEFAULT CURRENT_DATE
        );
        CREATE TABLE IF NOT EXISTS assignments(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL,
          description TEXT NOT NULL, due_date TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY, student_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

def current():
    uid = session.get("uid")
    if not uid: return None
    with connect() as c: return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

@app.context_processor
def globals_for_templates():
    if "_csrf" not in session: session["_csrf"] = secrets.token_urlsafe(24)
    return {"csrf": session["_csrf"], "me": current()}

@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "درخواست معتبر نیست. صفحه را تازه‌سازی کنید.")

def logged(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not current(): return redirect(url_for("login"))
        return fn(*a, **kw)
    return inner

def teacher(fn):
    @wraps(fn)
    def inner(*a, **kw):
        u = current()
        if not u or u["role"] != "teacher": abort(403)
        return fn(*a, **kw)
    return inner

SHELL = r"""
<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#2455d9">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<title>{{title}} | مدرسه هوشمند نیک‌پرور</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&display=swap');
:root{--blue:#2455d9;--navy:#183da6;--teal:#087f79;--bg:#f1f6ff;--ink:#18243c;--muted:#75829b;--line:#e3eaf4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Vazirmatn,Tahoma,sans-serif;color:var(--ink)}
header{background:linear-gradient(110deg,#245be2,#183b9e);color:white;padding:17px max(18px,calc((100% - 1120px)/2));display:flex;justify-content:space-between;align-items:center;box-shadow:0 12px 30px #214fb52b}
.brand{font-size:21px;font-weight:800}.sub{font-size:12px;opacity:.82}.wrap{max-width:1120px;margin:26px auto;padding:0 18px}
.hero{background:linear-gradient(120deg,#2056df,#087f79);color:white;border-radius:22px;padding:24px;box-shadow:0 16px 35px #2352b52b;margin-bottom:20px}
.hero h1{margin:0 0 5px;font-size:24px}.hero p{margin:0;opacity:.9}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:13px;margin:17px 0}
.stat,.card{background:white;border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 8px 25px #1d3e7510}
.stat strong{display:block;font-size:27px;color:var(--blue)}.stat span{color:var(--muted);font-size:13px}
.card{margin-bottom:16px}.card h2,.card h3{margin:0 0 14px}
label{display:block;font-weight:600;font-size:13px;margin:12px 0 6px}
input,select,textarea{width:100%;border:1px solid #dce4f0;border-radius:12px;padding:11px;font:inherit;background:#fbfdff;color:var(--ink)}
textarea{min-height:85px;resize:vertical}
button,.btn{border:0;border-radius:12px;padding:10px 17px;background:var(--blue);color:white;font:inherit;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}
.btn.secondary,button.secondary{background:#edf2ff;color:var(--blue)}.btn.teal,button.teal{background:var(--teal)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:17px}nav a{background:white;color:var(--blue);padding:9px 14px;border-radius:30px;text-decoration:none;border:1px solid var(--line);font-size:13px}
table{width:100%;border-collapse:collapse;min-width:560px}th{background:#2148b5;color:white}td,th{padding:11px 10px;border:1px solid var(--line);text-align:right;font-size:13px}tr:nth-child(even){background:#f7f9fd}.table-wrap{overflow:auto;border-radius:12px}
.badge{display:inline-block;border-radius:30px;padding:4px 10px;font-size:12px;background:#fff2d8;color:#956000}.ok{background:#e2fbef;color:#08794b}.no{background:#ffe8e9;color:#b42336}
.flash{padding:12px 15px;border-radius:12px;background:#e5f6ed;color:#08794b;margin:12px 0}.muted{color:var(--muted);font-size:13px}.empty{padding:22px;text-align:center;color:var(--muted)}
footer{text-align:center;color:#8794aa;font-size:12px;padding:25px}
@media(max-width:600px){header{padding:14px 16px}.brand{font-size:17px}.wrap{margin:17px auto}.hero h1{font-size:20px}.stat{padding:13px}}
</style></head><body>
<header><div><div class="brand">🎓 مدرسه هوشمند نیک‌پرور</div><div class="sub">سامانه آموزشی و کارنامه پایه ششم</div></div>
<div>{% if me %}<span class="sub">{{me['full_name']}}</span> · <a style="color:white" href="/logout">خروج</a>{% endif %}</div></header>
<main class="wrap">{% with msgs=get_flashed_messages() %}{% for m in msgs %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
{{content|safe}}</main><footer>مدرسه هوشمند نیک‌پرور · نسخه اولیه</footer>
<script>if ("serviceWorker" in navigator) { window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(err => console.log("PWA worker:", err))); }</script>
</body></html>
"""

def page(title, template, **data):
    inner = render_template_string(template, **data)
    return render_template_string(SHELL, title=title, content=inner)

@app.route("/")
def home():
    u=current()
    if not u: return redirect(url_for("login"))
    return redirect(url_for("teacher_home" if u["role"]=="teacher" else "student_home"))

@app.route("/setup", methods=["GET","POST"])
def setup():
    with connect() as c: exists=c.execute("SELECT id FROM users WHERE role='teacher'").fetchone()
    if exists: return page("راه‌اندازی", '<div class="card"><h2>حساب معلم قبلاً ساخته شده است.</h2><a class="btn" href="/login">ورود</a></div>')
    if request.method=="POST":
        name=request.form.get("name","").strip(); username=request.form.get("username","").strip(); pw=request.form.get("password","")
        if len(name)<3 or len(username)<4 or len(pw)<10: flash("نام و نام کاربری معتبر و رمز حداقل ۱۰ نویسه وارد کنید.")
        else:
            try:
                with connect() as c: c.execute("INSERT INTO users(full_name,student_code,username,password_hash,role,status,class_name) VALUES(?,?,?,?,?,?,?)",(name,"TEACHER-001",username,generate_password_hash(pw),"teacher","approved","مدیریت"))
                flash("حساب معلم ساخته شد. اکنون وارد شوید."); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("این نام کاربری قبلاً استفاده شده است.")
    return page("ساخت حساب معلم","""
    <div class="hero"><h1>راه‌اندازی اولیه سامانه</h1><p>فقط یک بار حساب معلم اصلی را ایجاد کنید.</p></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>نام و نام خانوادگی معلم</label><input name="name" required>
    <label>نام کاربری</label><input name="username" minlength="4" required>
    <label>رمز عبور قوی (حداقل ۱۰ نویسه)</label><input type="password" name="password" minlength="10" required>
    <div class="actions"><button>ایجاد حساب معلم</button></div></form></div>""")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name","").strip(); code=request.form.get("code","").strip(); username=request.form.get("username","").strip(); pw=request.form.get("password","")
        if len(name)<3 or len(code)<3 or len(username)<4 or len(pw)<8: flash("همه اطلاعات را کامل کنید؛ رمز حداقل ۸ نویسه باشد.")
        else:
            try:
                with connect() as c: c.execute("INSERT INTO users(full_name,student_code,username,password_hash,status,class_name) VALUES(?,?,?,?,?,?)",(name,code,username,generate_password_hash(pw),"pending","ششم"))
                flash("درخواست ثبت‌نام ارسال شد. پس از تأیید معلم حساب فعال می‌شود."); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("کد دانش‌آموزی یا نام کاربری تکراری است.")
    return page("ثبت‌نام دانش‌آموز","""
    <div class="hero"><h1>ثبت‌نام دانش‌آموز پایه ششم</h1><p>حساب پس از بررسی و تأیید معلم فعال می‌شود.</p></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>نام و نام خانوادگی</label><input name="name" required>
    <label>کد دانش‌آموزی مدرسه</label><input name="code" required>
    <label>نام کاربری دلخواه</label><input name="username" minlength="4" required>
    <label>رمز عبور</label><input type="password" name="password" minlength="8" required>
    <div class="actions"><button>ارسال درخواست ثبت‌نام</button><a class="btn secondary" href="/login">بازگشت</a></div></form></div>""")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form.get("username","").strip(); pw=request.form.get("password","")
        with connect() as c: u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        if u and check_password_hash(u["password_hash"],pw):
            if u["status"]!="approved": flash("حساب شما هنوز توسط معلم تأیید نشده است.")
            else:
                session.clear(); session["uid"]=u["id"]; session["_csrf"]=secrets.token_urlsafe(24)
                return redirect(url_for("home"))
        else: flash("نام کاربری یا رمز عبور اشتباه است.")
    return page("ورود","""
    <div class="hero"><h1>به نیک‌پرور خوش آمدید 👋</h1><p>ورود اختصاصی دانش‌آموزان و معلم</p></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>نام کاربری</label><input name="username" required>
    <label>رمز عبور</label><input type="password" name="password" required>
    <div class="actions"><button>ورود به سامانه</button><a class="btn secondary" href="/register">ثبت‌نام دانش‌آموز</a></div></form>
    <p class="muted">اولین اجرا؟ <a href="/setup">ساخت حساب معلم</a></p></div>""")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/teacher")
@logged
@teacher
def teacher_home():
    with connect() as c:
        pending=c.execute("SELECT * FROM users WHERE role='student' AND status='pending' ORDER BY created_at").fetchall()
        students=c.execute("SELECT * FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        ngrades=c.execute("SELECT COUNT(*) n FROM grades").fetchone()["n"]
    return page("پنل معلم","""
    <div class="hero"><h1>پنل مدیریت معلم 🧑‍🏫</h1><p>مدیریت دانش‌آموزان، نمرات، حضور و غیاب و فعالیت‌های آموزشی پایه ششم</p></div>
    <nav><a href="/teacher">داشبورد</a><a href="/teacher/grades">ثبت نمره</a><a href="/teacher/attendance">حضور و غیاب</a><a href="/teacher/behavior">انضباط و تشویق</a><a href="/teacher/assignments">تکالیف</a><a href="/teacher/messages">پیام‌ها</a></nav>
    <div class="grid"><div class="stat"><strong>{{pending|length}}</strong><span>درخواست در انتظار تأیید</span></div><div class="stat"><strong>{{students|length}}</strong><span>دانش‌آموز فعال</span></div><div class="stat"><strong>{{ngrades}}</strong><span>نمره ثبت‌شده</span></div></div>
    <div class="card"><h2>درخواست‌های ثبت‌نام</h2>{% if pending %}<div class="table-wrap"><table><tr><th>نام</th><th>کد دانش‌آموزی</th><th>نام کاربری</th><th>عملیات</th></tr>{% for s in pending %}<tr><td>{{s.full_name}}</td><td>{{s.student_code}}</td><td>{{s.username}}</td><td><form style="display:inline" method="post" action="/teacher/approve/{{s.id}}"><input type="hidden" name="_csrf" value="{{csrf}}"><button class="teal">تأیید</button></form> <form style="display:inline" method="post" action="/teacher/reject/{{s.id}}"><input type="hidden" name="_csrf" value="{{csrf}}"><button class="secondary">رد</button></form></td></tr>{% endfor %}</table></div>{% else %}<div class="empty">درخواست جدیدی وجود ندارد.</div>{% endif %}</div>
    <div class="card"><h2>دانش‌آموزان فعال</h2><div class="table-wrap"><table><tr><th>نام</th><th>کد</th><th>کلاس</th><th>پرونده</th></tr>{% for s in students %}<tr><td>{{s.full_name}}</td><td>{{s.student_code}}</td><td>{{s.class_name}}</td><td><a href="/teacher/student/{{s.id}}">مشاهده پرونده</a></td></tr>{% endfor %}</table></div></div>""",pending=pending,students=students,ngrades=ngrades)

@app.post("/teacher/approve/<int:sid>")
@logged
@teacher
def approve(sid):
    with connect() as c: c.execute("UPDATE users SET status='approved' WHERE id=? AND role='student' AND status='pending'",(sid,))
    flash("حساب دانش‌آموز تأیید شد."); return redirect(url_for("teacher_home"))

@app.post("/teacher/reject/<int:sid>")
@logged
@teacher
def reject(sid):
    with connect() as c: c.execute("DELETE FROM users WHERE id=? AND role='student' AND status='pending'",(sid,))
    flash("درخواست ثبت‌نام رد شد."); return redirect(url_for("teacher_home"))

@app.route("/teacher/grades", methods=["GET","POST"])
@logged
@teacher
def teacher_grades():
    if request.method=="POST":
        try: score=float(request.form.get("score","-1"))
        except ValueError: score=-1
        sid=request.form.get("student_id"); subject=request.form.get("subject"); term=request.form.get("term"); note=request.form.get("note","").strip()
        if not 0<=score<=20 or subject not in SUBJECTS: flash("درس یا نمره معتبر نیست.")
        else:
            with connect() as c:
                exists=c.execute("SELECT id FROM users WHERE id=? AND role='student' AND status='approved'",(sid,)).fetchone()
                if exists: c.execute("INSERT INTO grades(student_id,subject,score,term,note) VALUES(?,?,?,?,?)",(sid,subject,score,term,note)); flash("نمره ثبت شد.")
                else: flash("دانش‌آموز معتبر نیست.")
        return redirect(url_for("teacher_grades"))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        recent=c.execute("SELECT g.*,u.full_name FROM grades g JOIN users u ON u.id=g.student_id ORDER BY g.id DESC LIMIT 40").fetchall()
    return page("ثبت نمره","""
    <div class="hero"><h1>ثبت نمرات 📊</h1><p>نمره از صفر تا ۲۰؛ اطلاعات بلافاصله در کارنامه دانش‌آموز نمایش داده می‌شود.</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/grades">نمرات</a><a href="/teacher/attendance">حضور و غیاب</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>دانش‌آموز</label><select name="student_id" required>{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select>
    <label>درس</label><select name="subject">{% for x in subjects %}<option>{{x}}</option>{% endfor %}</select>
    <label>نوبت / نوع ارزیابی</label><select name="term">{% for x in terms %}<option>{{x}}</option>{% endfor %}</select>
    <label>نمره از ۲۰</label><input type="number" name="score" min="0" max="20" step="0.25" required>
    <label>توضیحات اختیاری</label><input name="note"><div class="actions"><button>ثبت نمره</button></div></form></div>
    <div class="card"><h2>آخرین نمرات</h2><div class="table-wrap"><table><tr><th>دانش‌آموز</th><th>درس</th><th>نمره</th><th>ارزیابی</th><th>توضیح</th></tr>{% for g in recent %}<tr><td>{{g.full_name}}</td><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.note}}</td></tr>{% endfor %}</table></div></div>""",students=students,subjects=SUBJECTS,terms=["مستمر مهر","مستمر آبان","مستمر آذر","نوبت اول","مستمر بهمن","مستمر اسفند","نوبت دوم","آزمون کلاسی"],recent=recent)

@app.route("/teacher/attendance", methods=["GET","POST"])
@logged
@teacher
def teacher_attendance():
    if request.method=="POST":
        with connect() as c: c.execute("INSERT INTO attendance(student_id,day,status,note) VALUES(?,?,?,?)",(request.form["student_id"],request.form["day"],request.form["status"],request.form.get("note","")))
        flash("حضور و غیاب ثبت شد."); return redirect(url_for("teacher_attendance"))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        rows=c.execute("SELECT a.*,u.full_name FROM attendance a JOIN users u ON u.id=a.student_id ORDER BY a.id DESC LIMIT 50").fetchall()
    return page("حضور و غیاب","""
    <div class="hero"><h1>حضور و غیاب</h1><p>وضعیت روزانه دانش‌آموزان را ثبت کنید.</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/grades">نمرات</a><a href="/teacher/attendance">حضور و غیاب</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>دانش‌آموز</label><select name="student_id">{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select><label>تاریخ</label><input type="date" name="day" required><label>وضعیت</label><select name="status"><option>حاضر</option><option>غایب</option><option>با تأخیر</option><option>با اجازه</option></select><label>توضیحات</label><input name="note"><div class="actions"><button>ثبت وضعیت</button></div></form></div>
    <div class="card"><h2>سوابق اخیر</h2><div class="table-wrap"><table><tr><th>نام</th><th>تاریخ</th><th>وضعیت</th><th>توضیح</th></tr>{% for r in rows %}<tr><td>{{r.full_name}}</td><td>{{r.day}}</td><td>{{r.status}}</td><td>{{r.note}}</td></tr>{% endfor %}</table></div></div>""",students=students,rows=rows)

@app.route("/teacher/behavior", methods=["GET","POST"])
@logged
@teacher
def teacher_behavior():
    if request.method=="POST":
        with connect() as c: c.execute("INSERT INTO behavior(student_id,kind,description) VALUES(?,?,?)",(request.form["student_id"],request.form["kind"],request.form["description"].strip()))
        flash("مورد انضباطی ثبت شد."); return redirect(url_for("teacher_behavior"))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        rows=c.execute("SELECT b.*,u.full_name FROM behavior b JOIN users u ON u.id=b.student_id ORDER BY b.id DESC LIMIT 40").fetchall()
    return page("انضباط و تشویق","""
    <div class="hero"><h1>انضباط و تشویق 🏅</h1><p>ثبت نکات مثبت و موارد نیازمند پیگیری</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/behavior">انضباط</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>دانش‌آموز</label><select name="student_id">{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select><label>نوع</label><select name="kind"><option>تشویق</option><option>تذکر</option><option>نکته مثبت</option><option>نیازمند پیگیری</option></select><label>شرح</label><textarea name="description" required></textarea><div class="actions"><button>ثبت</button></div></form></div>
    <div class="card"><h2>سوابق</h2><div class="table-wrap"><table><tr><th>نام</th><th>نوع</th><th>شرح</th><th>تاریخ</th></tr>{% for r in rows %}<tr><td>{{r.full_name}}</td><td>{{r.kind}}</td><td>{{r.description}}</td><td>{{r.day}}</td></tr>{% endfor %}</table></div></div>""",students=students,rows=rows)

@app.route("/teacher/assignments", methods=["GET","POST"])
@logged
@teacher
def teacher_assignments():
    if request.method=="POST":
        with connect() as c: c.execute("INSERT INTO assignments(title,subject,description,due_date) VALUES(?,?,?,?)",(request.form["title"].strip(),request.form["subject"],request.form["description"].strip(),request.form.get("due_date","")))
        flash("تکلیف منتشر شد."); return redirect(url_for("teacher_assignments"))
    with connect() as c: rows=c.execute("SELECT * FROM assignments ORDER BY id DESC").fetchall()
    return page("تکالیف","""
    <div class="hero"><h1>مدیریت تکالیف 📝</h1><p>تکلیف جدید برای همه دانش‌آموزان کلاس منتشر کنید.</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/assignments">تکالیف</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>عنوان</label><input name="title" required><label>درس</label><select name="subject">{% for s in subjects %}<option>{{s}}</option>{% endfor %}</select><label>شرح تکلیف</label><textarea name="description" required></textarea><label>مهلت تحویل</label><input type="date" name="due_date"><div class="actions"><button>انتشار تکلیف</button></div></form></div>
    <div class="card"><h2>تکالیف منتشرشده</h2>{% for a in rows %}<p><b>{{a.title}}</b> · {{a.subject}} · {{a.due_date}}<br>{{a.description}}</p><hr>{% else %}<div class="empty">هنوز تکلیفی ثبت نشده است.</div>{% endfor %}</div>""",rows=rows,subjects=SUBJECTS)

@app.route("/teacher/messages", methods=["GET","POST"])
@logged
@teacher
def teacher_messages():
    if request.method=="POST":
        sid=request.form.get("student_id") or None
        with connect() as c: c.execute("INSERT INTO messages(student_id,title,body) VALUES(?,?,?)",(sid,request.form["title"].strip(),request.form["body"].strip()))
        flash("پیام ارسال شد."); return redirect(url_for("teacher_messages"))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        msgs=c.execute("SELECT m.*,u.full_name FROM messages m LEFT JOIN users u ON u.id=m.student_id ORDER BY m.id DESC LIMIT 40").fetchall()
    return page("پیام‌ها","""
    <div class="hero"><h1>پیام‌رسان مدرسه 💬</h1><p>ارسال اطلاعیه برای همه یا یک دانش‌آموز</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/messages">پیام‌ها</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>گیرنده</label><select name="student_id"><option value="">همه دانش‌آموزان</option>{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select><label>عنوان</label><input name="title" required><label>متن پیام</label><textarea name="body" required></textarea><div class="actions"><button>ارسال پیام</button></div></form></div>
    <div class="card"><h2>پیام‌های ارسال‌شده</h2>{% for m in msgs %}<p><b>{{m.title}}</b> · {{m.full_name or 'همه دانش‌آموزان'}}<br>{{m.body}}</p><hr>{% else %}<div class="empty">پیامی وجود ندارد.</div>{% endfor %}</div>""",students=students,msgs=msgs)

@app.route("/teacher/student/<int:sid>")
@logged
@teacher
def teacher_student(sid):
    with connect() as c:
        s=c.execute("SELECT * FROM users WHERE id=? AND role='student'",(sid,)).fetchone()
        if not s: abort(404)
        grades=c.execute("SELECT * FROM grades WHERE student_id=? ORDER BY id DESC",(sid,)).fetchall()
        att=c.execute("SELECT * FROM attendance WHERE student_id=? ORDER BY id DESC",(sid,)).fetchall()
        beh=c.execute("SELECT * FROM behavior WHERE student_id=? ORDER BY id DESC",(sid,)).fetchall()
    avg=round(sum(g["score"] for g in grades)/len(grades),2) if grades else None
    return page("پرونده دانش‌آموز","""
    <div class="hero"><h1>پرونده {{s.full_name}}</h1><p>کد دانش‌آموزی: {{s.student_code}} · پایه ششم</p></div><nav><a href="/teacher">بازگشت به داشبورد</a></nav>
    <div class="grid"><div class="stat"><strong>{{avg if avg is not none else '—'}}</strong><span>میانگین نمرات ثبت‌شده</span></div><div class="stat"><strong>{{grades|length}}</strong><span>تعداد نمرات</span></div><div class="stat"><strong>{{att|length}}</strong><span>سوابق حضور و غیاب</span></div></div>
    <div class="card"><h2>نمرات</h2><div class="table-wrap"><table><tr><th>درس</th><th>نمره</th><th>ارزیابی</th><th>توضیح</th></tr>{% for g in grades %}<tr><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.note}}</td></tr>{% else %}<tr><td colspan="4">نمره‌ای ثبت نشده است.</td></tr>{% endfor %}</table></div></div>
    <div class="card"><h2>انضباط</h2>{% for b in beh %}<p>{{b.day}} · {{b.kind}}: {{b.description}}</p>{% else %}<p class="muted">موردی ثبت نشده است.</p>{% endfor %}</div>""",s=s,grades=grades,att=att,beh=beh,avg=avg)

@app.route("/student")
@logged
def student_home():
    u=current()
    if u["role"]!="student": return redirect(url_for("teacher_home"))
    if u["status"]!="approved": return redirect(url_for("login"))
    with connect() as c:
        grades=c.execute("SELECT * FROM grades WHERE student_id=? ORDER BY id DESC",(u["id"],)).fetchall()
        att=c.execute("SELECT * FROM attendance WHERE student_id=? ORDER BY id DESC LIMIT 30",(u["id"],)).fetchall()
        beh=c.execute("SELECT * FROM behavior WHERE student_id=? ORDER BY id DESC",(u["id"],)).fetchall()
        assignments=c.execute("SELECT * FROM assignments ORDER BY id DESC").fetchall()
        msgs=c.execute("SELECT * FROM messages WHERE student_id IS NULL OR student_id=? ORDER BY id DESC",(u["id"],)).fetchall()
    avg=round(sum(g["score"] for g in grades)/len(grades),2) if grades else None
    return page("پنل دانش‌آموز","""
    <div class="hero"><h1>سلام {{u.full_name}} 👋</h1><p>به پنل دانش‌آموزی مدرسه هوشمند نیک‌پرور خوش آمدی.</p></div>
    <nav><a href="/student">داشبورد</a><a href="#grades">کارنامه</a><a href="#attendance">حضور و غیاب</a><a href="#behavior">انضباط</a><a href="#assignments">تکالیف</a><a href="#messages">پیام‌ها</a></nav>
    <div class="grid"><div class="stat"><strong>{{avg if avg is not none else '—'}}</strong><span>میانگین نمرات ثبت‌شده</span></div><div class="stat"><strong>{{grades|length}}</strong><span>نمره ثبت‌شده</span></div><div class="stat"><strong>{{att|length}}</strong><span>سوابق حضور و غیاب</span></div></div>
    <div class="card" id="grades"><h2>📊 کارنامه و نمرات</h2><div class="table-wrap"><table><tr><th>درس</th><th>نمره</th><th>ارزیابی</th><th>توضیح</th></tr>{% for g in grades %}<tr><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.note}}</td></tr>{% else %}<tr><td colspan="4">هنوز نمره‌ای ثبت نشده است.</td></tr>{% endfor %}</table></div></div>
    <div class="card" id="attendance"><h2>📅 حضور و غیاب</h2>{% for a in att %}<p>{{a.day}} · {{a.status}} {% if a.note %}· {{a.note}}{% endif %}</p>{% else %}<p class="muted">سابقه‌ای ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="behavior"><h2>🏅 انضباط و تشویق</h2>{% for b in beh %}<p>{{b.day}} · {{b.kind}}: {{b.description}}</p>{% else %}<p class="muted">موردی ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="assignments"><h2>📝 تکالیف</h2>{% for a in assignments %}<p><b>{{a.title}}</b> · {{a.subject}} · مهلت: {{a.due_date or 'اعلام نشده'}}<br>{{a.description}}</p><hr>{% else %}<p class="muted">تکلیفی ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="messages"><h2>💬 پیام‌های معلم</h2>{% for m in msgs %}<p><b>{{m.title}}</b><br>{{m.body}}<br><span class="muted">{{m.created_at}}</span></p><hr>{% else %}<p class="muted">پیامی وجود ندارد.</p>{% endfor %}</div>""",u=u,grades=grades,att=att,beh=beh,assignments=assignments,msgs=msgs,avg=avg)


@app.route("/manifest.json")
def pwa_manifest():
    data = {"id":"/", "name":"مدرسه هوشمند نیک‌پرور", "short_name":"نیک‌پرور", "lang":"fa", "dir":"rtl", "start_url":"/", "scope":"/", "display":"standalone", "background_color":"#f1f6ff", "theme_color":"#2455d9", "icons":[{"src":"/icon-192.png", "sizes":"192x192", "type":"image/png", "purpose":"any maskable"},{"src":"/icon-512.png", "sizes":"512x512", "type":"image/png", "purpose":"any maskable"}]}
    from flask import jsonify
    return jsonify(data)

@app.route("/icon.svg")
def pwa_icon():
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'><rect width='512' height='512' rx='112' fill='#2455d9'/><path d='M100 190 256 105l156 85v28H100z' fill='#fff'/><path d='M130 220h252v160H130z' fill='#fff'/><path d='M220 275h72v105h-72z' fill='#2455d9'/><path d='M160 250h42v42h-42zm150 0h42v42h-42z' fill='#2455d9'/><path d='M90 395h332v25H90z' fill='#8fe3d5'/></svg>"""
    return app.response_class(svg, mimetype="image/svg+xml")

@app.route("/icon-192.png")
@app.route("/icon-512.png")
def pwa_png_icon():
    from flask import send_file
    size = 192 if request.path.endswith("192.png") else 512
    return send_file(ROOT / "static" / f"icon-{size}.png", mimetype="image/png")

@app.route("/sw.js")
def pwa_service_worker():
    # Authenticated pages and student records are deliberately not cached.
    js = """const CACHE='nikparvar-static-v1';
self.addEventListener('install', event => { self.skipWaiting(); });
self.addEventListener('activate', event => { event.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname === '/manifest.json' || url.pathname === '/icon.svg') {
    event.respondWith(caches.open(CACHE).then(async cache => {
      try { const response = await fetch(event.request); if (response.ok) cache.put(event.request, response.clone()); return response; }
      catch (_) { return (await cache.match(event.request)) || Response.error(); }
    }));
  }
});
"""
    return app.response_class(js, mimetype="application/javascript", headers={"Service-Worker-Allowed":"/"})

@app.errorhandler(403)
def forbidden(e): return page("دسترسی غیرمجاز",'<div class="card"><h2>دسترسی غیرمجاز</h2><p>این بخش فقط برای معلم است.</p><a class="btn" href="/">بازگشت</a></div>'),403

@app.errorhandler(404)
def missing(e): return page("یافت نشد",'<div class="card"><h2>صفحه پیدا نشد.</h2><a class="btn" href="/">بازگشت</a></div>'),404

if __name__ == "__main__":
    init_db()
    print("\\nمدرسه هوشمند نیک‌پرور اجرا شد: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
