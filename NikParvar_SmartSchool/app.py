
import os, sqlite3, secrets, uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, render_template_string, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import send_from_directory

ROOT = Path(__file__).resolve().parent
DB = ROOT / "nikparvar.db"
app = Flask(__name__)
app.secret_key = os.environ.get("NIKPARVAR_SECRET_KEY", secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=12 * 1024 * 1024)
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}

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
        CREATE TABLE IF NOT EXISTS parent_links(
          id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          status TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(parent_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS stories(
          id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES users(id),
          title TEXT NOT NULL, body TEXT DEFAULT '', image_path TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS story_replies(
          id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
          student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          body TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notifications(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT DEFAULT 'general',
          is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS calendar_events(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, event_date TEXT NOT NULL,
          description TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quizzes(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL,
          description TEXT DEFAULT '', is_published INTEGER DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quiz_questions(
          id INTEGER PRIMARY KEY, quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
          question TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL, c TEXT NOT NULL, d TEXT NOT NULL,
          correct TEXT NOT NULL CHECK(correct IN ('a','b','c','d'))
        );
        CREATE TABLE IF NOT EXISTS quiz_attempts(
          id INTEGER PRIMARY KEY, quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
          student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          score REAL NOT NULL, total INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS birthday_notices(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          birthday_year INTEGER NOT NULL, UNIQUE(user_id,birthday_year)
        );
        CREATE TABLE IF NOT EXISTS polls(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, option_a TEXT NOT NULL, option_b TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS poll_votes(
          id INTEGER PRIMARY KEY, poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, choice TEXT NOT NULL CHECK(choice IN ('a','b')),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(poll_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS library_files(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '', stored_name TEXT NOT NULL,
          original_name TEXT NOT NULL, uploaded_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS awards(
          id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL, description TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # Additive migrations keep existing school records intact.
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        for name, typ in [("birthdate", "TEXT"), ("photo_path", "TEXT"), ("phone", "TEXT")]:
            if name not in cols: c.execute(f"ALTER TABLE users ADD COLUMN {name} {typ}")
        gcols = {r[1] for r in c.execute("PRAGMA table_info(grades)").fetchall()}
        if "assessment" not in gcols: c.execute("ALTER TABLE grades ADD COLUMN assessment TEXT DEFAULT ''")

def assessment_for(score):
    # Suggested labels are editable by the teacher; schools should adjust bands to their policy.
    if score < 10: return "نیاز به تلاش"
    if score < 14: return "قابل قبول"
    if score < 18: return "خوب"
    return "خیلی خوب"

def notify(user_id, title, body, kind="general"):
    with connect() as c:
        c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)", (user_id,title,body,kind))

def image_upload(file):
    if not file or not file.filename: return None
    ext = Path(file.filename).suffix.lower().lstrip('.')
    if ext not in ALLOWED_IMAGE_EXT: raise ValueError("فقط تصویر PNG، JPG یا WEBP مجاز است.")
    # Check file signature rather than trusting the extension alone.
    file.seek(0, 2); size=file.tell(); file.seek(0)
    if size > 3 * 1024 * 1024: raise ValueError("حجم تصویر باید کمتر از ۳ مگابایت باشد.")
    data = file.read(16); file.seek(0)
    signatures = (data.startswith(b'\x89PNG\r\n\x1a\n'), data.startswith(b'\xff\xd8\xff'), data.startswith(b'RIFF') and data[8:12] == b'WEBP')
    if not any(signatures): raise ValueError("قالب تصویر معتبر نیست.")
    filename = uuid.uuid4().hex + '.' + ext
    file.save(UPLOAD_DIR / filename)
    return filename

def document_upload(file):
    if not file or not file.filename: raise ValueError("فایلی انتخاب نشده است.")
    ext=Path(file.filename).suffix.lower().lstrip('.')
    original=secure_filename(file.filename) or ("file."+ext)
    allowed={"pdf","docx","pptx","xlsx","txt","png","jpg","jpeg"}
    if ext not in allowed: raise ValueError("نوع فایل مجاز نیست. PDF، Office، TXT یا تصویر انتخاب کنید.")
    data=file.read(8); file.seek(0)
    if ext=='pdf' and not data.startswith(b'%PDF-'): raise ValueError("فایل PDF معتبر نیست.")
    if ext in {'docx','pptx','xlsx'} and not data.startswith(b'PK'): raise ValueError("فایل Office معتبر نیست.")
    stored=uuid.uuid4().hex+'.'+ext
    file.save(UPLOAD_DIR/stored)
    return stored, original

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

def parent(fn):
    @wraps(fn)
    def inner(*a, **kw):
        u = current()
        if not u or u["role"] != "parent" or u["status"] != "approved": abort(403)
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
nav{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:22px 0 24px}
nav a{background:#fff;color:var(--ink);min-height:72px;padding:16px 18px;border-radius:16px;text-decoration:none;border:1px solid var(--line);border-right:4px solid var(--blue);font-size:15px;font-weight:700;display:flex;align-items:center;box-shadow:0 7px 20px #1d3e750d;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
nav a:hover{transform:translateY(-2px);box-shadow:0 12px 24px #1d3e7518;border-color:#c9d7f3;border-right-color:var(--teal);color:var(--blue)}
nav a:focus-visible{outline:3px solid #8eb3ff;outline-offset:2px}
table{width:100%;border-collapse:collapse;min-width:560px}th{background:#2148b5;color:white}td,th{padding:11px 10px;border:1px solid var(--line);text-align:right;font-size:13px}tr:nth-child(even){background:#f7f9fd}.table-wrap{overflow:auto;border-radius:12px}
.badge{display:inline-block;border-radius:30px;padding:4px 10px;font-size:12px;background:#fff2d8;color:#956000}.ok{background:#e2fbef;color:#08794b}.no{background:#ffe8e9;color:#b42336}
.flash{padding:12px 15px;border-radius:12px;background:#e5f6ed;color:#08794b;margin:12px 0}.muted{color:var(--muted);font-size:13px}.empty{padding:22px;text-align:center;color:var(--muted)}
footer{text-align:center;color:#8794aa;font-size:12px;padding:25px}
@media(max-width:600px){header{padding:14px 16px}.brand{font-size:17px}.wrap{margin:17px auto}.hero h1{font-size:20px}.stat{padding:13px}nav{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}nav a{min-height:68px;padding:12px;font-size:13px;border-radius:13px}}@media(max-width:390px){nav{grid-template-columns:1fr}}
</style></head><body>
<header><div><div class="brand"> مدرسه هوشمند نیک‌پرور</div><div class="sub">سامانه یکپارچه آموزشی مدرسه</div></div>
<div>{% if me %}<span class="sub">{{me['full_name']}}</span> · <a style="color:white" href="/profile">پروفایل</a> · <a style="color:white" href="/notifications">اعلان‌ها</a> · <a style="color:white" href="/logout">خروج</a>{% endif %}</div></header>
<main class="wrap">{% with msgs=get_flashed_messages() %}{% for m in msgs %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
{{content|safe}}</main><footer>مدرسه هوشمند نیک‌پرور · سامانه آموزشی</footer>
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
    return redirect(url_for("teacher_home" if u["role"]=="teacher" else ("parent_home" if u["role"]=="parent" else "student_home")))

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
            class_name=request.form.get("class_name", "هشتم").strip()
            if class_name not in ["اول", "دوم", "سوم", "چهارم", "پنجم", "ششم", "هفتم", "هشتم", "نهم", "دهم", "یازدهم", "دوازدهم"]: class_name="هشتم"
            try:
                with connect() as c: c.execute("INSERT INTO users(full_name,student_code,username,password_hash,status,class_name) VALUES(?,?,?,?,?,?)",(name,code,username,generate_password_hash(pw),"pending",class_name))
                flash("درخواست ثبت‌نام ارسال شد. پس از تأیید معلم حساب فعال می‌شود."); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("کد دانش‌آموزی یا نام کاربری تکراری است.")
    return page("ثبت‌نام دانش‌آموز","""
    <div class="hero"><h1>ثبت‌نام دانش‌آموز</h1><p>حساب پس از بررسی و تأیید معلم فعال می‌شود.</p></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>نام و نام خانوادگی</label><input name="name" required>
    <label>کد دانش‌آموزی مدرسه</label><input name="code" required>
    <label>پایه تحصیلی</label><select name="class_name">{% for c in ["اول","دوم","سوم","چهارم","پنجم","ششم","هفتم","هشتم","نهم","دهم","یازدهم","دوازدهم"] %}<option value="{{c}}" {% if c=="هشتم" %}selected{% endif %}>پایه {{c}}</option>{% endfor %}</select>
    <label>نام کاربری دلخواه</label><input name="username" minlength="4" required>
    <label>رمز عبور</label><input type="password" name="password" minlength="8" required>
    <div class="actions"><button>ارسال درخواست ثبت‌نام</button><a class="btn secondary" href="/login">بازگشت</a></div></form></div>""")

@app.route("/parent-register", methods=["GET", "POST"])
def parent_register():
    if request.method == "POST":
        name=request.form.get("name", "").strip(); code=request.form.get("child_code", "").strip()
        username=request.form.get("username", "").strip(); pw=request.form.get("password", "")
        with connect() as c: child=c.execute("SELECT * FROM users WHERE student_code=? AND role='student' AND status='approved'", (code,)).fetchone()
        if not child: flash("کد دانش‌آموزی معتبر و فعال پیدا نشد.")
        elif len(name)<3 or len(username)<4 or len(pw)<8: flash("اطلاعات را کامل کنید؛ رمز حداقل ۸ نویسه باشد.")
        else:
            try:
                with connect() as c:
                    cur=c.execute("INSERT INTO users(full_name,student_code,username,password_hash,role,status,class_name) VALUES(?,?,?,?,?,?,?)", (name,"PARENT-"+uuid.uuid4().hex[:10],username,generate_password_hash(pw),"parent","pending","والدین"))
                    c.execute("INSERT INTO parent_links(parent_id,student_id,status) VALUES(?,?,?)", (cur.lastrowid,child["id"],"pending"))
                flash("درخواست اتصال والد به دانش‌آموز برای تأیید مدرسه ارسال شد."); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("این نام کاربری قبلاً ثبت شده است.")
    return page("ثبت‌نام والد", """<div class="hero"><h1>ایجاد حساب والدین</h1><p>پس از بررسی و تأیید مدرسه، دسترسی به پرونده فرزند فعال می‌شود.</p></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>نام و نام خانوادگی والد</label><input name="name" required>
    <label>کد دانش‌آموزی فرزند</label><input name="child_code" required><label>نام کاربری</label><input name="username" required minlength="4">
    <label>رمز عبور</label><input type="password" name="password" required minlength="8"><div class="actions"><button>ارسال درخواست</button><a class="btn secondary" href="/login">بازگشت</a></div></form></div>""")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form.get("username","").strip(); pw=request.form.get("password","")
        with connect() as c: u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        if u and check_password_hash(u["password_hash"],pw):
            if u["status"]!="approved": flash("حساب شما هنوز توسط معلم تأیید نشده است.")
            else:
                session.clear(); session["uid"]=u["id"]; session["_csrf"]=secrets.token_urlsafe(24)
                # Birthday greetings are generated once per calendar year when the account is used.
                if u["role"] == "student" and u["birthdate"]:
                    try:
                        bd=date.fromisoformat(u["birthdate"])
                        today=date.today()
                        if (bd.month,bd.day)==(today.month,today.day):
                            with connect() as c:
                                cur=c.execute("INSERT OR IGNORE INTO birthday_notices(user_id,birthday_year) VALUES(?,?)",(u["id"],today.year))
                                if cur.rowcount:
                                    c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'birthday')",(u["id"],"تولدت مبارک!","مدرسه نیک‌پرور برایت سالی سرشار از یادگیری و موفقیت آرزو می‌کند."))
                                    parents=c.execute("SELECT parent_id FROM parent_links WHERE student_id=? AND status='approved'",(u["id"],)).fetchall()
                                    for pr in parents: c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'birthday')",(pr['parent_id'],"تولد فرزندتان","امروز روز تولد فرزند شماست. برای او سالی پربار آرزو می‌کنیم."))
                    except Exception: pass
                return redirect(url_for("home"))
        else: flash("نام کاربری یا رمز عبور اشتباه است.")
    return page("ورود","""
    <div class="hero"><h1>به نیک‌پرور خوش آمدید </h1><p>ورود اختصاصی دانش‌آموزان و معلم</p></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>نام کاربری</label><input name="username" required>
    <label>رمز عبور</label><input type="password" name="password" required>
    <div class="actions"><button>ورود به سامانه</button><a class="btn secondary" href="/register">ثبت‌نام دانش‌آموز</a> <a class="btn secondary" href="/parent-register">ورود والدین</a></div></form>
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
        pending_parents=c.execute("SELECT p.id,l.id link_id,p.full_name,s.full_name child_name FROM parent_links l JOIN users p ON p.id=l.parent_id JOIN users s ON s.id=l.student_id WHERE l.status='pending'").fetchall()
    return page("پنل معلم","""
    <div class="hero"><h1>پنل مدیریت معلم</h1><p>مدیریت دانش‌آموزان، نمرات، حضور و غیاب و فعالیت‌های آموزشی مدرسه</p></div>
    <nav><a href="/teacher">داشبورد</a><a href="/teacher/grades">ثبت نمره</a><a href="/teacher/attendance">حضور و غیاب</a><a href="/teacher/behavior">انضباط و تشویق</a><a href="/teacher/assignments">تکالیف</a><a href="/teacher/messages">پیام‌ها</a><a href="/teacher/stories">وضعیت‌ها</a><a href="/teacher/calendar">تقویم</a><a href="/teacher/quizzes">آزمون‌ها</a><a href="/teacher/library">کتابخانه</a><a href="/teacher/polls">نظرسنجی</a><a href="/teacher/awards">افتخارات</a></nav>
    <div class="grid"><div class="stat"><strong>{{pending|length}}</strong><span>درخواست در انتظار تأیید</span></div><div class="stat"><strong>{{students|length}}</strong><span>دانش‌آموز فعال</span></div><div class="stat"><strong>{{ngrades}}</strong><span>نمره ثبت‌شده</span></div></div>
    <div class="card"><h2>درخواست اتصال والدین</h2>{% for p in pending_parents %}<p>{{p.full_name}} · والدِ {{p.child_name}} <form style="display:inline" method="post" action="/teacher/parent-approve/{{p.link_id}}"><input type="hidden" name="_csrf" value="{{csrf}}"><button class="teal">تأیید</button></form></p>{% else %}<p class="muted">درخواستی وجود ندارد.</p>{% endfor %}</div>
    <div class="card"><h2>درخواست‌های ثبت‌نام</h2>{% if pending %}<div class="table-wrap"><table><tr><th>نام</th><th>کد دانش‌آموزی</th><th>نام کاربری</th><th>عملیات</th></tr>{% for s in pending %}<tr><td>{{s.full_name}}</td><td>{{s.student_code}}</td><td>{{s.username}}</td><td><form style="display:inline" method="post" action="/teacher/approve/{{s.id}}"><input type="hidden" name="_csrf" value="{{csrf}}"><button class="teal">تأیید</button></form> <form style="display:inline" method="post" action="/teacher/reject/{{s.id}}"><input type="hidden" name="_csrf" value="{{csrf}}"><button class="secondary">رد</button></form></td></tr>{% endfor %}</table></div>{% else %}<div class="empty">درخواست جدیدی وجود ندارد.</div>{% endif %}</div>
    <div class="card"><h2>دانش‌آموزان فعال</h2><div class="table-wrap"><table><tr><th>تصویر</th><th>نام</th><th>کد</th><th>کلاس</th><th>پرونده</th></tr>{% for s in students %}<tr><td>{% if s.photo_path %}<img src="/uploads/{{s.photo_path}}" style="width:38px;height:38px;object-fit:cover;border-radius:50%">{% else %}—{% endif %}</td><td>{{s.full_name}}</td><td>{{s.student_code}}</td><td>{{s.class_name}}</td><td><a href="/teacher/student/{{s.id}}">مشاهده پرونده</a></td></tr>{% endfor %}</table></div></div>""",pending=pending,students=students,ngrades=ngrades,pending_parents=pending_parents)

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

@app.post("/teacher/parent-approve/<int:link_id>")
@logged
@teacher
def approve_parent(link_id):
    with connect() as c:
        link=c.execute("SELECT parent_id FROM parent_links WHERE id=?",(link_id,)).fetchone()
        if link:
            c.execute("UPDATE parent_links SET status='approved' WHERE id=?",(link_id,))
            c.execute("UPDATE users SET status='approved' WHERE id=? AND role='parent'",(link['parent_id'],))
            c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'account')",(link['parent_id'],"حساب والدین تأیید شد","اکنون می‌توانید وارد پنل والدین شوید."))
    flash("درخواست والدین تأیید شد."); return redirect(url_for("teacher_home"))

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
                if exists:
                    assessment=request.form.get("assessment", "").strip() or assessment_for(score)
                    if assessment not in ["نیاز به تلاش","قابل قبول","خوب","خیلی خوب"]: assessment=assessment_for(score)
                    c.execute("INSERT INTO grades(student_id,subject,score,term,note,assessment) VALUES(?,?,?,?,?,?)",(sid,subject,score,term,note,assessment))
                    c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'grade')",(int(sid),"نمره جدید ثبت شد",f"درس {subject}: {score} از ۲۰ · {assessment}"))
                    parents=c.execute("SELECT parent_id FROM parent_links WHERE student_id=? AND status='approved'",(sid,)).fetchall()
                    for pr in parents: c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'grade')",(pr['parent_id'],"نمره جدید فرزند",f"درس {subject}: {score} از ۲۰ · برای مشاهده جزئیات وارد پنل شوید."))
                    flash("نمره و ارزیابی توصیفی ثبت شد.")
                else: flash("دانش‌آموز معتبر نیست.")
        return redirect(url_for("teacher_grades"))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        recent=c.execute("SELECT g.*,u.full_name FROM grades g JOIN users u ON u.id=g.student_id ORDER BY g.id DESC LIMIT 40").fetchall()
    return page("ثبت نمره","""
    <div class="hero"><h1>ثبت نمرات </h1><p>نمره از صفر تا ۲۰؛ اطلاعات بلافاصله در کارنامه دانش‌آموز نمایش داده می‌شود.</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/grades">نمرات</a><a href="/teacher/attendance">حضور و غیاب</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">
    <label>دانش‌آموز</label><select name="student_id" required>{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select>
    <label>درس</label><select name="subject">{% for x in subjects %}<option>{{x}}</option>{% endfor %}</select>
    <label>نوبت / نوع ارزیابی</label><select name="term">{% for x in terms %}<option>{{x}}</option>{% endfor %}</select>
    <label>نمره از ۲۰</label><input type="number" name="score" min="0" max="20" step="0.25" required>
    <label>ارزیابی توصیفی پیشنهادی (قابل تغییر)</label><select name="assessment"><option value="">پیشنهاد خودکار بر اساس نمره</option><option>نیاز به تلاش</option><option>قابل قبول</option><option>خوب</option><option>خیلی خوب</option></select><label>توضیحات اختیاری</label><input name="note"><div class="actions"><button>ثبت نمره</button></div></form></div>
    <div class="card"><h2>آخرین نمرات</h2><div class="table-wrap"><table><tr><th>دانش‌آموز</th><th>درس</th><th>نمره</th><th>نوبت</th><th>ارزیابی توصیفی</th><th>توضیح</th></tr>{% for g in recent %}<tr><td>{{g.full_name}}</td><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.assessment or "ثبت نشده"}}</td><td>{{g.note}}</td></tr>{% endfor %}</table></div></div>""",students=students,subjects=SUBJECTS,terms=["مستمر مهر","مستمر آبان","مستمر آذر","نوبت اول","مستمر بهمن","مستمر اسفند","نوبت دوم","آزمون کلاسی"],recent=recent)

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
    <div class="hero"><h1>انضباط و تشویق </h1><p>ثبت نکات مثبت و موارد نیازمند پیگیری</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/behavior">انضباط</a></nav>
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
    <div class="hero"><h1>مدیریت تکالیف </h1><p>تکلیف جدید برای همه دانش‌آموزان کلاس منتشر کنید.</p></div><nav><a href="/teacher">داشبورد</a><a href="/teacher/assignments">تکالیف</a></nav>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>عنوان</label><input name="title" required><label>درس</label><select name="subject">{% for s in subjects %}<option>{{s}}</option>{% endfor %}</select><label>شرح تکلیف</label><textarea name="description" required></textarea><label>مهلت تحویل</label><input type="date" name="due_date"><div class="actions"><button>انتشار تکلیف</button></div></form></div>
    <div class="card"><h2>تکالیف منتشرشده</h2>{% for a in rows %}<p><b>{{a.title}}</b> · {{a.subject}} · {{a.due_date}}<br>{{a.description}}</p><hr>{% else %}<div class="empty">هنوز تکلیفی ثبت نشده است.</div>{% endfor %}</div>""",rows=rows,subjects=SUBJECTS)

@app.route("/teacher/messages", methods=["GET","POST"])
@logged
@teacher
def teacher_messages():
    if request.method=="POST":
        sid=request.form.get("student_id") or None
        title=request.form.get("title","").strip()
        body=request.form.get("body","").strip()
        if not title or not body:
            flash("عنوان و متن پیام را وارد کنید.")
            return redirect(url_for("teacher_messages"))
        with connect() as c:
            if sid:
                target=c.execute("SELECT id FROM users WHERE id=? AND role='student' AND status='approved'",(sid,)).fetchone()
                if not target:
                    flash("دانش‌آموز انتخاب‌شده معتبر نیست.")
                    return redirect(url_for("teacher_messages"))
                c.execute("INSERT INTO messages(student_id,title,body) VALUES(?,?,?)",(target["id"],title,body))
                recipients=[target["id"]]
            else:
                c.execute("INSERT INTO messages(student_id,title,body) VALUES(NULL,?,?)",(title,body))
                recipients=[r["id"] for r in c.execute("SELECT id FROM users WHERE role='student' AND status='approved'").fetchall()]
            for student_id in recipients:
                c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'teacher_message')",(student_id,title,body))
                linked_parents=c.execute("SELECT parent_id FROM parent_links WHERE student_id=? AND status='approved'",(student_id,)).fetchall()
                for linked_parent in linked_parents:
                    c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'teacher_message')",(linked_parent["parent_id"],"پیام جدید از مدرسه",title+" — "+body))
        flash("پیام در صندوق پیام‌ها ثبت شد و اعلان درون‌برنامه‌ای برای گیرندگان ارسال شد؛ پیامک تلفنی ارسال نشده است.")
        return redirect(url_for("teacher_messages"))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        msgs=c.execute("SELECT m.*,u.full_name FROM messages m LEFT JOIN users u ON u.id=m.student_id ORDER BY m.id DESC LIMIT 40").fetchall()
    return page("پیام‌ها","""
    <div class="hero"><h1>ارسال پیام و اعلان داخلی</h1><p>ارسال اطلاعیه برای همه دانش‌آموزان یا یک دانش‌آموز مشخص</p></div>
    <nav><a href="/teacher">داشبورد</a><a href="/teacher/messages">پیام‌ها و اعلان‌ها</a><a href="/teacher/stories">وضعیت‌ها</a><a href="/teacher/calendar">تقویم</a><a href="/teacher/quizzes">آزمون‌ها</a><a href="/teacher/library">کتابخانه</a><a href="/teacher/polls">نظرسنجی</a><a href="/teacher/awards">افتخارات</a></nav>
    <div class="card"><h2>نوشتن پیام جدید</h2><p class="muted">این بخش پیام را داخل سامانه ثبت می‌کند و اعلان داخل برنامه برای دانش‌آموز و والدِ متصل می‌فرستد. برای ارسال SMS واقعی باید پنل و اعتبار یک شرکت پیامکی جداگانه متصل شود.</p>
    <form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>گیرنده</label><select name="student_id"><option value="">همه دانش‌آموزان</option>{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select><label>عنوان</label><input name="title" required><label>متن پیام</label><textarea name="body" required></textarea><div class="actions"><button>ارسال پیام و اعلان</button></div></form></div>
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
    <div class="hero">{% if s.photo_path %}<img src="/uploads/{{s.photo_path}}" style="width:76px;height:76px;object-fit:cover;border-radius:50%;float:right;margin-left:14px">{% endif %}<h1>پرونده {{s.full_name}}</h1><p>کد دانش‌آموزی: {{s.student_code}} · پایه ششم</p></div><nav><a href="/teacher">بازگشت به داشبورد</a></nav>
    <div class="grid"><div class="stat"><strong>{{avg if avg is not none else '—'}}</strong><span>میانگین نمرات ثبت‌شده</span></div><div class="stat"><strong>{{grades|length}}</strong><span>تعداد نمرات</span></div><div class="stat"><strong>{{att|length}}</strong><span>سوابق حضور و غیاب</span></div></div>
    <div class="card"><h2>نمرات</h2><div class="table-wrap"><table><tr><th>درس</th><th>نمره</th><th>نوبت</th><th>ارزیابی توصیفی</th><th>توضیح</th></tr>{% for g in grades %}<tr><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.assessment or "ثبت نشده"}}</td><td>{{g.note}}</td></tr>{% else %}<tr><td colspan="5">نمره‌ای ثبت نشده است.</td></tr>{% endfor %}</table></div></div>
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
    <div class="hero"><h1>سلام {{u.full_name}} </h1><p>به پنل دانش‌آموزی مدرسه هوشمند نیک‌پرور خوش آمدی.</p></div>
    <nav><a href="/student">داشبورد</a><a href="#grades">کارنامه</a><a href="#attendance">حضور و غیاب</a><a href="#behavior">انضباط</a><a href="#assignments">تکالیف</a><a href="#messages">پیام‌ها</a><a href="/stories">وضعیت‌ها</a><a href="/quizzes">آزمون‌ها</a><a href="/calendar">تقویم</a><a href="/notifications">اعلان‌ها</a><a href="/profile">پروفایل</a><a href="/student/report">گزارش کارنامه</a><a href="/library">کتابخانه</a><a href="/polls">نظرسنجی</a><a href="/awards">افتخارات</a></nav>
    <div class="grid"><div class="stat"><strong>{{avg if avg is not none else '—'}}</strong><span>میانگین نمرات ثبت‌شده</span></div><div class="stat"><strong>{{grades|length}}</strong><span>نمره ثبت‌شده</span></div><div class="stat"><strong>{{att|length}}</strong><span>سوابق حضور و غیاب</span></div></div>
    <div class="card"><h2>نمودار پیشرفت نمرات اخیر</h2>{% for g in grades[:8] %}<div style="display:grid;grid-template-columns:110px 1fr 42px;gap:10px;align-items:center;margin:10px 0;font-size:13px"><span>{{g.subject}}</span><div style="height:11px;background:#edf1f7;border-radius:20px;overflow:hidden"><div style="height:100%;width:{{g.score*5}}%;background:linear-gradient(90deg,#2455d9,#087f79);border-radius:20px"></div></div><b>{{g.score}}</b></div>{% else %}<p class="muted">برای نمایش نمودار هنوز نمره‌ای ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="grades"><h2> کارنامه و نمرات</h2><div class="table-wrap"><table><tr><th>درس</th><th>نمره</th><th>نوبت</th><th>ارزیابی توصیفی</th><th>توضیح</th></tr>{% for g in grades %}<tr><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.assessment or "ثبت نشده"}}</td><td>{{g.note}}</td></tr>{% else %}<tr><td colspan="5">هنوز نمره‌ای ثبت نشده است.</td></tr>{% endfor %}</table></div></div>
    <div class="card" id="attendance"><h2> حضور و غیاب</h2>{% for a in att %}<p>{{a.day}} · {{a.status}} {% if a.note %}· {{a.note}}{% endif %}</p>{% else %}<p class="muted">سابقه‌ای ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="behavior"><h2> انضباط و تشویق</h2>{% for b in beh %}<p>{{b.day}} · {{b.kind}}: {{b.description}}</p>{% else %}<p class="muted">موردی ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="assignments"><h2> تکالیف</h2>{% for a in assignments %}<p><b>{{a.title}}</b> · {{a.subject}} · مهلت: {{a.due_date or 'اعلام نشده'}}<br>{{a.description}}</p><hr>{% else %}<p class="muted">تکلیفی ثبت نشده است.</p>{% endfor %}</div>
    <div class="card" id="messages"><h2> پیام‌های معلم</h2>{% for m in msgs %}<p><b>{{m.title}}</b><br>{{m.body}}<br><span class="muted">{{m.created_at}}</span></p><hr>{% else %}<p class="muted">پیامی وجود ندارد.</p>{% endfor %}</div>""",u=u,grades=grades,att=att,beh=beh,assignments=assignments,msgs=msgs,avg=avg)


@app.route("/profile", methods=["GET", "POST"])
@logged
def profile():
    u=current()
    if request.method=="POST":
        birth=request.form.get("birthdate") or None; phone=request.form.get("phone", "").strip()
        try:
            photo=image_upload(request.files.get("photo"))
            with connect() as c:
                if photo: c.execute("UPDATE users SET birthdate=?,phone=?,photo_path=? WHERE id=?",(birth,phone,photo,u['id']))
                else: c.execute("UPDATE users SET birthdate=?,phone=? WHERE id=?",(birth,phone,u['id']))
            flash("اطلاعات پروفایل ذخیره شد.")
        except ValueError as e: flash(str(e))
        return redirect(url_for("profile"))
    return page("پروفایل", """<div class="hero"><h1>پروفایل کاربری</h1><p>اطلاعات تماس و تاریخ تولد را مدیریت کنید.</p></div><div class="card">
    {% if me.photo_path %}<img src="/uploads/{{me.photo_path}}" style="width:100px;height:100px;object-fit:cover;border-radius:50%">{% endif %}
    <form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf}}"><label>تاریخ تولد (اختیاری)</label><input type="date" name="birthdate" value="{{me.birthdate or ''}}"><label>شماره تماس (اختیاری)</label><input name="phone" value="{{me.phone or ''}}"><label>تصویر پروفایل (PNG/JPG/WEBP، حداکثر ۳ مگابایت)</label><input type="file" name="photo" accept="image/png,image/jpeg,image/webp"><div class="actions"><button>ذخیره تغییرات</button></div></form></div>""")

@app.route("/uploads/<path:filename>")
@logged
def uploaded_file(filename):
    # Uploaded files are private to their owner, teachers, linked parents, or active story viewers.
    filename=secure_filename(filename)
    if not (UPLOAD_DIR / filename).is_file(): abort(404)
    u=current()
    allowed = u['role']=='teacher' or u['photo_path']==filename
    if not allowed:
        with connect() as c:
            if u['role']=='parent':
                allowed=bool(c.execute("SELECT 1 FROM parent_links l JOIN users s ON s.id=l.student_id WHERE l.parent_id=? AND l.status='approved' AND s.photo_path=?",(u['id'],filename)).fetchone())
            if not allowed:
                allowed=bool(c.execute("SELECT 1 FROM stories WHERE image_path=? AND expires_at>?",(filename,datetime.now().isoformat(timespec='seconds'))).fetchone())
    if not allowed: abort(403)
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/notifications")
@logged
def notifications_page():
    u=current()
    with connect() as c:
        rows=c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100",(u['id'],)).fetchall()
        c.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(u['id'],))
    return page("اعلان‌ها", """<div class="hero"><h1>اعلان‌های شما</h1><p>پیام‌های سامانه و تغییرات آموزشی</p></div><div class="card">{% for n in rows %}<div style="padding:12px 0;border-bottom:1px solid var(--line)"><b>{{n.title}}</b><p>{{n.body}}</p><span class="muted">{{n.created_at}}</span></div>{% else %}<p class="muted">اعلانی ندارید.</p>{% endfor %}</div>""",rows=rows)

@app.route("/teacher/stories", methods=["GET", "POST"])
@logged
@teacher
def teacher_stories():
    if request.method=="POST":
        title=request.form.get("title", "").strip(); body=request.form.get("body", "").strip()
        try:
            photo=image_upload(request.files.get("photo"))
            if not title and not body and not photo: raise ValueError("عنوان، متن یا تصویر وارد کنید.")
            expires=(datetime.now()+timedelta(hours=24)).isoformat(timespec='seconds')
            with connect() as c:
                c.execute("INSERT INTO stories(teacher_id,title,body,image_path,expires_at) VALUES(?,?,?,?,?)",(current()['id'],title or "وضعیت جدید",body,photo or "",expires))
                students=c.execute("SELECT id FROM users WHERE role='student' AND status='approved'").fetchall()
                for st in students: c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'story')",(st['id'],"وضعیت جدید مدرسه",title or "یک وضعیت جدید منتشر شده است."))
            flash("وضعیت برای ۲۴ ساعت منتشر شد.")
        except ValueError as e: flash(str(e))
        return redirect(url_for("teacher_stories"))
    with connect() as c: rows=c.execute("SELECT * FROM stories WHERE expires_at>? ORDER BY id DESC",(datetime.now().isoformat(timespec='seconds'),)).fetchall()
    return page("وضعیت‌ها", """<div class="hero"><h1>وضعیت‌ها و اطلاعیه‌های کوتاه</h1><p>وضعیت‌ها پس از ۲۴ ساعت از فهرست فعال خارج می‌شوند.</p></div><nav><a href="/teacher">داشبورد</a></nav>
    <div class="card"><form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf}}"><label>عنوان</label><input name="title"><label>متن</label><textarea name="body"></textarea><label>تصویر اختیاری</label><input type="file" name="photo" accept="image/png,image/jpeg,image/webp"><div class="actions"><button>انتشار وضعیت</button></div></form></div>
    <div class="card"><h2>وضعیت‌های فعال</h2>{% for st in rows %}<h3>{{st.title}}</h3><p>{{st.body}}</p>{% if st.image_path %}<img src="/uploads/{{st.image_path}}" style="max-width:100%;max-height:300px;border-radius:14px">{% endif %}<p class="muted">{{st.created_at}} · انقضا: {{st.expires_at}}</p><hr>{% else %}<p class="muted">وضعیت فعالی نیست.</p>{% endfor %}</div>""",rows=rows)

@app.route("/stories", methods=["GET", "POST"])
@logged
def stories_view():
    u=current()
    if u['role'] not in ('student','parent'): abort(403)
    if request.method=="POST":
        sid=request.form.get("story_id", type=int); body=request.form.get("body", "").strip()
        if u['role']!='student' or not body: flash("فقط دانش‌آموز می‌تواند پاسخ متنی ارسال کند.")
        else:
            with connect() as c:
                st=c.execute("SELECT id FROM stories WHERE id=? AND expires_at>?",(sid,datetime.now().isoformat(timespec='seconds'))).fetchone()
                if st: c.execute("INSERT INTO story_replies(story_id,student_id,body) VALUES(?,?,?)",(sid,u['id'],body)); flash("پاسخ شما ثبت شد.")
        return redirect(url_for("stories_view"))
    with connect() as c:
        rows=c.execute("SELECT * FROM stories WHERE expires_at>? ORDER BY id DESC",(datetime.now().isoformat(timespec='seconds'),)).fetchall()
        replies={r['id']:c.execute("SELECT sr.*,u.full_name FROM story_replies sr JOIN users u ON u.id=sr.student_id WHERE sr.story_id=? ORDER BY sr.id DESC",(r['id'],)).fetchall() for r in rows}
    return page("وضعیت‌های مدرسه", """<div class="hero"><h1>وضعیت‌های مدرسه</h1><p>اطلاعیه‌ها و پیام‌های کوتاه معلم</p></div>{% for st in rows %}<div class="card"><h3>{{st.title}}</h3><p>{{st.body}}</p>{% if st.image_path %}<img src="/uploads/{{st.image_path}}" style="max-width:100%;max-height:300px;border-radius:14px">{% endif %}<span class="muted">{{st.created_at}}</span>
    {% for r in replies[st.id] %}<p><b>{{r.full_name}}:</b> {{r.body}}</p>{% endfor %}{% if me.role=='student' %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><input type="hidden" name="story_id" value="{{st.id}}"><label>پاسخ</label><input name="body" maxlength="500" required><button>ارسال پاسخ</button></form>{% endif %}</div>{% else %}<div class="card">وضعیت فعالی وجود ندارد.</div>{% endfor %}""",rows=rows,replies=replies)

@app.route("/parent")
@logged
@parent
def parent_home():
    u=current()
    with connect() as c:
        kids=c.execute("SELECT s.* FROM parent_links l JOIN users s ON s.id=l.student_id WHERE l.parent_id=? AND l.status='approved'",(u['id'],)).fetchall()
        details=[]
        for kid in kids:
            grades=c.execute("SELECT * FROM grades WHERE student_id=? ORDER BY id DESC",(kid['id'],)).fetchall()
            att=c.execute("SELECT * FROM attendance WHERE student_id=? ORDER BY id DESC LIMIT 20",(kid['id'],)).fetchall()
            msgs=c.execute("SELECT * FROM messages WHERE student_id IS NULL OR student_id=? ORDER BY id DESC LIMIT 20",(kid['id'],)).fetchall()
            details.append((kid,grades,att,msgs))
    return page("پنل والدین", """<div class="hero"><h1>پنل والدین</h1><p>اطلاعات آموزشی فرزندانی که اتصال آن‌ها توسط مدرسه تأیید شده است.</p></div><nav><a href="/notifications">اعلان‌ها</a><a href="/profile">پروفایل</a><a href="/stories">وضعیت‌ها</a></nav>
    {% for kid,grades,att,msgs in details %}<div class="card">{% if kid.photo_path %}<img src="/uploads/{{kid.photo_path}}" style="width:65px;height:65px;object-fit:cover;border-radius:50%">{% endif %}<h2>{{kid.full_name}} · {{kid.class_name}}</h2><h3>نمرات و ارزیابی توصیفی</h3><div class="table-wrap"><table><tr><th>درس</th><th>نمره</th><th>نوبت</th><th>ارزیابی</th></tr>{% for g in grades %}<tr><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.assessment or 'ثبت نشده'}}</td></tr>{% else %}<tr><td colspan="5">هنوز نمره‌ای ثبت نشده است.</td></tr>{% endfor %}</table></div><h3>حضور و غیاب</h3>{% for a in att %}<p>{{a.day}} · {{a.status}}</p>{% else %}<p class="muted">سابقه‌ای نیست.</p>{% endfor %}<h3>پیام‌های معلم</h3>{% for m in msgs %}<p><b>{{m.title}}</b> · {{m.body}}</p>{% else %}<p class="muted">پیامی نیست.</p>{% endfor %}</div>{% else %}<div class="card">هنوز فرزندی به حساب شما متصل نشده است.</div>{% endfor %}""",details=details)

@app.route("/teacher/calendar", methods=["GET", "POST"])
@logged
@teacher
def teacher_calendar():
    if request.method=="POST":
        with connect() as c: c.execute("INSERT INTO calendar_events(title,event_date,description) VALUES(?,?,?)",(request.form['title'].strip(),request.form['event_date'],request.form.get('description','').strip()))
        flash("رویداد تقویم ثبت شد."); return redirect(url_for('teacher_calendar'))
    with connect() as c: rows=c.execute("SELECT * FROM calendar_events ORDER BY event_date").fetchall()
    return page("تقویم مدرسه", """<div class="hero"><h1>تقویم آموزشی مدرسه</h1><p>رویدادها، آزمون‌ها و مناسبت‌ها</p></div><nav><a href="/teacher">داشبورد</a></nav><div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>عنوان رویداد</label><input name="title" required><label>تاریخ</label><input type="date" name="event_date" required><label>توضیحات</label><textarea name="description"></textarea><button>ثبت رویداد</button></form></div><div class="card">{% for r in rows %}<p><b>{{r.event_date}} · {{r.title}}</b><br>{{r.description}}</p>{% else %}<p class="muted">رویدادی ثبت نشده است.</p>{% endfor %}</div>""",rows=rows)

@app.route("/calendar")
@logged
def calendar_view():
    with connect() as c: rows=c.execute("SELECT * FROM calendar_events ORDER BY event_date").fetchall()
    return page("تقویم", """<div class="hero"><h1>تقویم مدرسه</h1></div><div class="card">{% for r in rows %}<p><b>{{r.event_date}} · {{r.title}}</b><br>{{r.description}}</p>{% else %}<p>رویدادی ثبت نشده است.</p>{% endfor %}</div>""",rows=rows)

@app.route("/teacher/quizzes", methods=["GET", "POST"])
@logged
@teacher
def teacher_quizzes():
    if request.method=="POST":
        title=request.form.get('title','').strip(); subject=request.form.get('subject',''); qs=[]
        for i in range(1,6):
            q=request.form.get(f'q{i}','').strip()
            if q: qs.append((q,request.form.get(f'a{i}','').strip(),request.form.get(f'b{i}','').strip(),request.form.get(f'c{i}','').strip(),request.form.get(f'd{i}','').strip(),request.form.get(f'correct{i}','a')))
        if not title or not qs or any(not all(x[:5]) for x in qs): flash("عنوان و دست‌کم یک سؤال کامل لازم است.")
        else:
            with connect() as c:
                cur=c.execute("INSERT INTO quizzes(title,subject,description,is_published) VALUES(?,?,?,1)",(title,subject,request.form.get('description','')))
                for q in qs: c.execute("INSERT INTO quiz_questions(quiz_id,question,a,b,c,d,correct) VALUES(?,?,?,?,?,?,?)",(cur.lastrowid,*q))
                students=c.execute("SELECT id FROM users WHERE role='student' AND status='approved'").fetchall()
                for st in students: c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'quiz')",(st['id'],"آزمون جدید منتشر شد",title))
            flash("آزمون منتشر شد."); return redirect(url_for('teacher_quizzes'))
    with connect() as c:
        rows=c.execute("SELECT q.*, (SELECT COUNT(*) FROM quiz_questions x WHERE x.quiz_id=q.id) n FROM quizzes q ORDER BY q.id DESC").fetchall()
        results=c.execute("SELECT a.*,u.full_name,q.title FROM quiz_attempts a JOIN users u ON u.id=a.student_id JOIN quizzes q ON q.id=a.quiz_id ORDER BY a.id DESC LIMIT 30").fetchall()
    return page("آزمون آنلاین", """<div class="hero"><h1>ساخت آزمون آنلاین</h1><p>پنج سؤال چهارگزینه‌ای با تصحیح خودکار</p></div><nav><a href="/teacher">داشبورد</a></nav><div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>عنوان آزمون</label><input name="title" required><label>درس</label><select name="subject">{% for x in subjects %}<option>{{x}}</option>{% endfor %}</select><label>توضیحات</label><input name="description">{% for i in range(1,6) %}<hr><h3>سؤال {{i}}</h3><input name="q{{i}}" placeholder="متن سؤال"><label>گزینه الف</label><input name="a{{i}}"><label>گزینه ب</label><input name="b{{i}}"><label>گزینه ج</label><input name="c{{i}}"><label>گزینه د</label><input name="d{{i}}"><label>پاسخ صحیح</label><select name="correct{{i}}"><option value="a">الف</option><option value="b">ب</option><option value="c">ج</option><option value="d">د</option></select>{% endfor %}<button>انتشار آزمون</button></form></div><div class="card"><h2>آزمون‌های منتشرشده</h2>{% for q in rows %}<p>{{q.title}} · {{q.subject}} · {{q.n}} سؤال</p>{% else %}<p>آزمونی نیست.</p>{% endfor %}<h3>نتایج اخیر</h3>{% for r in results %}<p>{{r.full_name}} · {{r.title}} · {{r.score}} از {{r.total}}</p>{% endfor %}</div>""",rows=rows,results=results,subjects=SUBJECTS)

@app.route("/quizzes")
@logged
def quizzes_view():
    if current()['role']!='student': abort(403)
    with connect() as c: rows=c.execute("SELECT * FROM quizzes WHERE is_published=1 ORDER BY id DESC").fetchall()
    return page("آزمون‌ها", """<div class="hero"><h1>آزمون‌های آنلاین</h1><p>پاسخ‌ها پس از ارسال به‌صورت خودکار تصحیح می‌شوند.</p></div><div class="card">{% for q in rows %}<p><b>{{q.title}}</b> · {{q.subject}} · <a href="/quiz/{{q.id}}">شروع آزمون</a></p>{% else %}<p>آزمون فعالی وجود ندارد.</p>{% endfor %}</div>""",rows=rows)

@app.route("/quiz/<int:qid>", methods=["GET", "POST"])
@logged
def take_quiz(qid):
    u=current()
    if u['role']!='student': abort(403)
    with connect() as c:
        quiz=c.execute("SELECT * FROM quizzes WHERE id=? AND is_published=1",(qid,)).fetchone()
        if not quiz: abort(404)
        qs=c.execute("SELECT * FROM quiz_questions WHERE quiz_id=?",(qid,)).fetchall()
        if request.method=='POST':
            score=sum(1 for q in qs if request.form.get(str(q['id']))==q['correct'])
            c.execute("INSERT INTO quiz_attempts(quiz_id,student_id,score,total) VALUES(?,?,?,?)",(qid,u['id'],score,len(qs)))
            c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'quiz')",(u['id'],"نتیجه آزمون",f"{quiz['title']}: {score} از {len(qs)} پاسخ درست"))
            flash(f"آزمون ثبت شد. نتیجه: {score} از {len(qs)}")
            return redirect(url_for('quizzes_view'))
    return page("شرکت در آزمون", """<div class="hero"><h1>{{quiz.title}}</h1><p>{{quiz.subject}}</p></div><div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}">{% for q in qs %}<h3>{{loop.index}}. {{q.question}}</h3>{% for key,label in [('a','الف'),('b','ب'),('c','ج'),('d','د')] %}<label style="font-weight:400"><input style="width:auto" type="radio" name="{{q.id}}" value="{{key}}" required> {{label}}) {{q[key]}}</label>{% endfor %}<hr>{% endfor %}<button>ثبت پاسخ‌ها و مشاهده نتیجه</button></form></div>""",quiz=quiz,qs=qs)

@app.route("/teacher/library", methods=["GET", "POST"])
@logged
@teacher
def teacher_library():
    if request.method=='POST':
        try:
            stored,original=document_upload(request.files.get('file'))
            with connect() as c: c.execute("INSERT INTO library_files(title,description,stored_name,original_name,uploaded_by) VALUES(?,?,?,?,?)",(request.form.get('title','').strip() or original,request.form.get('description','').strip(),stored,original,current()['id']))
            flash("فایل آموزشی به کتابخانه اضافه شد.")
        except ValueError as e: flash(str(e))
        return redirect(url_for('teacher_library'))
    with connect() as c: rows=c.execute("SELECT * FROM library_files ORDER BY id DESC").fetchall()
    return page("کتابخانه", """<div class="hero"><h1>کتابخانه و منابع آموزشی</h1><p>فایل‌های کمک‌آموزشی را برای دانش‌آموزان منتشر کنید.</p></div><nav><a href="/teacher">داشبورد</a></nav><div class="card"><form method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf}}"><label>عنوان منبع</label><input name="title"><label>توضیحات</label><textarea name="description"></textarea><label>انتخاب فایل (حداکثر ۱۲ مگابایت)</label><input type="file" name="file" required><button>افزودن به کتابخانه</button></form></div><div class="card"><h2>منابع منتشرشده</h2>{% for f in rows %}<p><b>{{f.title}}</b> · {{f.original_name}}<br>{{f.description}}<br><a href="/library/download/{{f.id}}">دریافت فایل</a></p><hr>{% else %}<p>فایلی ثبت نشده است.</p>{% endfor %}</div>""",rows=rows)

@app.route("/library")
@logged
def library_view():
    with connect() as c: rows=c.execute("SELECT * FROM library_files ORDER BY id DESC").fetchall()
    return page("کتابخانه", """<div class="hero"><h1>کتابخانه آموزشی</h1><p>منابع منتشرشده توسط مدرسه</p></div><div class="card">{% for f in rows %}<p><b>{{f.title}}</b><br>{{f.description}}<br><a href="/library/download/{{f.id}}">دریافت فایل</a></p><hr>{% else %}<p>هنوز منبعی منتشر نشده است.</p>{% endfor %}</div>""",rows=rows)

@app.route("/library/download/<int:file_id>")
@logged
def library_download(file_id):
    with connect() as c: f=c.execute("SELECT * FROM library_files WHERE id=?",(file_id,)).fetchone()
    if not f: abort(404)
    return send_from_directory(UPLOAD_DIR,f['stored_name'],as_attachment=True,download_name=f['original_name'])

@app.route("/teacher/polls", methods=["GET", "POST"])
@logged
@teacher
def teacher_polls():
    if request.method=='POST':
        title=request.form.get('title','').strip(); a=request.form.get('a','').strip(); b=request.form.get('b','').strip()
        if not all((title,a,b)): flash("عنوان و هر دو گزینه را وارد کنید.")
        else:
            with connect() as c:
                cur=c.execute("INSERT INTO polls(title,option_a,option_b) VALUES(?,?,?)",(title,a,b))
                students=c.execute("SELECT id FROM users WHERE role='student' AND status='approved'").fetchall()
                for st in students: c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'poll')",(st['id'],"نظرسنجی جدید",title))
            flash("نظرسنجی منتشر شد.")
        return redirect(url_for('teacher_polls'))
    with connect() as c: rows=c.execute("SELECT p.*,SUM(v.choice='a') ca,SUM(v.choice='b') cb,COUNT(v.id) total FROM polls p LEFT JOIN poll_votes v ON v.poll_id=p.id GROUP BY p.id ORDER BY p.id DESC").fetchall()
    return page("نظرسنجی", """<div class="hero"><h1>نظرسنجی مدرسه</h1><p>یک پرسش با دو گزینه برای دانش‌آموزان منتشر کنید.</p></div><nav><a href="/teacher">داشبورد</a></nav><div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>پرسش</label><input name="title" required><label>گزینه اول</label><input name="a" required><label>گزینه دوم</label><input name="b" required><button>انتشار نظرسنجی</button></form></div><div class="card">{% for p in rows %}<p><b>{{p.title}}</b><br>{{p.option_a}}: {{p.ca or 0}} · {{p.option_b}}: {{p.cb or 0}} · مجموع رأی: {{p.total}}</p>{% endfor %}</div>""",rows=rows)

@app.route("/polls", methods=["GET", "POST"])
@logged
def polls_view():
    u=current()
    if u['role']!='student': abort(403)
    if request.method=='POST':
        pid=request.form.get('poll_id',type=int); choice=request.form.get('choice')
        if choice not in ('a','b'): flash("گزینه معتبر نیست.")
        else:
            try:
                with connect() as c: c.execute("INSERT INTO poll_votes(poll_id,user_id,choice) VALUES(?,?,?)",(pid,u['id'],choice))
                flash("رأی شما ثبت شد.")
            except sqlite3.IntegrityError: flash("برای این نظرسنجی قبلاً رأی داده‌اید.")
        return redirect(url_for('polls_view'))
    with connect() as c:
        rows=c.execute("SELECT p.*,v.choice my_vote,SUM(v2.choice='a') ca,SUM(v2.choice='b') cb FROM polls p LEFT JOIN poll_votes v ON v.poll_id=p.id AND v.user_id=? LEFT JOIN poll_votes v2 ON v2.poll_id=p.id GROUP BY p.id ORDER BY p.id DESC",(u['id'],)).fetchall()
    return page("نظرسنجی‌ها", """<div class="hero"><h1>نظرسنجی‌های مدرسه</h1></div>{% for p in rows %}<div class="card"><h3>{{p.title}}</h3>{% if p.my_vote %}<p>رأی شما ثبت شده است.</p><p>{{p.option_a}}: {{p.ca or 0}} · {{p.option_b}}: {{p.cb or 0}}</p>{% else %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><input type="hidden" name="poll_id" value="{{p.id}}"><label><input type="radio" name="choice" value="a" required style="width:auto"> {{p.option_a}}</label><label><input type="radio" name="choice" value="b" style="width:auto"> {{p.option_b}}</label><button>ثبت رأی</button></form>{% endif %}</div>{% else %}<div class="card">نظرسنجی فعالی نیست.</div>{% endfor %}""",rows=rows)

@app.route("/teacher/awards", methods=["GET", "POST"])
@logged
@teacher
def teacher_awards():
    if request.method=='POST':
        sid=request.form.get('student_id',type=int); title=request.form.get('title','').strip(); desc=request.form.get('description','').strip()
        if not sid or not title: flash("دانش‌آموز و عنوان افتخار را انتخاب کنید.")
        else:
            with connect() as c:
                c.execute("INSERT INTO awards(student_id,title,description) VALUES(?,?,?)",(sid,title,desc))
                c.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,'award')",(sid,"افتخار جدید برای شما ثبت شد",title))
            flash("افتخار دانش‌آموز ثبت شد.")
        return redirect(url_for('teacher_awards'))
    with connect() as c:
        students=c.execute("SELECT id,full_name FROM users WHERE role='student' AND status='approved' ORDER BY full_name").fetchall()
        rows=c.execute("SELECT a.*,u.full_name FROM awards a JOIN users u ON u.id=a.student_id ORDER BY a.id DESC").fetchall()
    return page("افتخارات", """<div class="hero"><h1>افتخارات و گواهی‌های تشویقی</h1><p>ثبت دستاوردهای آموزشی و اخلاقی دانش‌آموزان</p></div><nav><a href="/teacher">داشبورد</a></nav><div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{csrf}}"><label>دانش‌آموز</label><select name="student_id">{% for s in students %}<option value="{{s.id}}">{{s.full_name}}</option>{% endfor %}</select><label>عنوان افتخار</label><input name="title" required><label>توضیحات</label><textarea name="description"></textarea><button>ثبت افتخار</button></form></div><div class="card">{% for a in rows %}<p><b>{{a.full_name}}</b> · {{a.title}}<br>{{a.description}}</p>{% endfor %}</div>""",students=students,rows=rows)

@app.route("/awards")
@logged
def awards_view():
    u=current()
    if u['role']=='student': sid=u['id']
    elif u['role']=='parent':
        with connect() as c: kids=c.execute("SELECT student_id FROM parent_links WHERE parent_id=? AND status='approved'",(u['id'],)).fetchall()
        ids=[k['student_id'] for k in kids]
        if not ids: rows=[]; return page("افتخارات",'<div class="card">افتخاری ثبت نشده است.</div>')
        marks=','.join('?' for _ in ids); query=f"SELECT a.*,u.full_name FROM awards a JOIN users u ON u.id=a.student_id WHERE a.student_id IN ({marks}) ORDER BY a.id DESC"
        with connect() as c: rows=c.execute(query,ids).fetchall()
        return page("افتخارات", """<div class="hero"><h1>افتخارات فرزند</h1></div><div class="card">{% for a in rows %}<p><b>{{a.title}}</b> · {{a.full_name}}<br>{{a.description}}</p>{% else %}<p>افتخاری ثبت نشده است.</p>{% endfor %}</div>""",rows=rows)
    else: abort(403)
    with connect() as c: rows=c.execute("SELECT * FROM awards WHERE student_id=? ORDER BY id DESC",(sid,)).fetchall()
    return page("افتخارات", """<div class="hero"><h1>افتخارات من</h1><p>دستاوردهای ثبت‌شده توسط مدرسه</p></div><div class="card">{% for a in rows %}<h3>{{a.title}}</h3><p>{{a.description}}</p><span class="muted">{{a.created_at}}</span><hr>{% else %}<p>هنوز افتخاری ثبت نشده است.</p>{% endfor %}</div>""",rows=rows)

@app.route("/student/report")
@logged
def student_report():
    u=current()
    if u['role']!='student': abort(403)
    with connect() as c:
        grades=c.execute("SELECT * FROM grades WHERE student_id=? ORDER BY subject,term",(u['id'],)).fetchall()
        att=c.execute("SELECT * FROM attendance WHERE student_id=? ORDER BY day DESC",(u['id'],)).fetchall()
    avg=round(sum(g['score'] for g in grades)/len(grades),2) if grades else None
    return page("گزارش کارنامه", """<style>@media print{header,nav,.no-print,footer{display:none!important}body{background:white}.wrap{max-width:none;margin:0;padding:0}.card{box-shadow:none;border:1px solid #ddd;break-inside:avoid}}</style>
    <div class="hero"><h1>گزارش آموزشی دانش‌آموز</h1><p>{{u.full_name}} · {{u.class_name}} · کد: {{u.student_code}}</p></div><div class="card"><p>میانگین نمرات ثبت‌شده: <b>{{avg if avg is not none else '—'}}</b></p><h2>کارنامه</h2><div class="table-wrap"><table><tr><th>درس</th><th>نمره</th><th>نوبت</th><th>ارزیابی توصیفی</th><th>توضیح</th></tr>{% for g in grades %}<tr><td>{{g.subject}}</td><td>{{g.score}}</td><td>{{g.term}}</td><td>{{g.assessment or 'ثبت نشده'}}</td><td>{{g.note}}</td></tr>{% else %}<tr><td colspan="5">نمره‌ای ثبت نشده است.</td></tr>{% endfor %}</table></div><h2>حضور و غیاب</h2>{% for a in att %}<p>{{a.day}} · {{a.status}} · {{a.note}}</p>{% else %}<p>سابقه‌ای ثبت نشده است.</p>{% endfor %}<p class="muted">این گزارش بر اساس داده‌های ثبت‌شده در سامانه تهیه شده است.</p><button class="no-print" onclick="window.print()">چاپ / ذخیره به‌صورت PDF</button></div>""",u=u,grades=grades,att=att,avg=avg)

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

# Initialize schema on import as well, so Gunicorn/Render workers have tables.
init_db()

if __name__ == "__main__":
    init_db()
    print("\\nمدرسه هوشمند نیک‌پرور اجرا شد: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
