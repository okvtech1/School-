#!/usr/bin/env python3
"""
School Result and Accounting Management System - LAN-based, for KG, nursery, primary and secondary schools.
OKV Technology Consults | www.okvtechnology.com | technologyokv@gmail.com | WhatsApp +234 810 414 1138

One file: database, API, server and interface. Python 3.8+, standard library only.
Run:  python school_system.py        (PORT=9000 python school_system.py to change the port)
"""
import base64, hashlib, hmac, json, os, re, secrets, socket, sqlite3, sys, tempfile, threading, time, traceback, webbrowser
import urllib.error, urllib.request
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

FROZEN = bool(getattr(sys, 'frozen', False))
RES_DIR = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))          # bundled files (manuals, config.json)
BASE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))


def default_data_dir():
    if not FROZEN:
        return BASE
    if sys.platform.startswith('win'):
        return os.path.join(os.environ.get('PROGRAMDATA') or os.path.expanduser('~'), 'SchoolSystem')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/SchoolSystem')
    return os.path.expanduser('~/.school_system')
DATA_DIR = os.environ.get('SCHOOL_DATA_DIR') or default_data_dir()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    DATA_DIR = BASE
DB = os.environ.get('DB') or os.path.join(DATA_DIR, 'school_system.db')
if not os.environ.get('DB') and not os.path.exists(DB) and os.path.exists(os.path.join(BASE, 'okv_results.db')):
    DB = os.path.join(BASE, 'okv_results.db')   # upgrade: keep using the earlier database
VERSION = '2.0'
if sys.stdout is None or sys.stderr is None:      # started without a console (pythonw): write a log file instead
    try:
        _log = open(os.path.join(DATA_DIR, 'server.log'), 'a', buffering=1, encoding='utf-8')
        sys.stdout = sys.stderr = _log
    except OSError:
        pass
PORT = int(os.environ.get('PORT', '8080'))
SESSION_TTL = 12 * 3600
MAX_BODY = 8 * 1024 * 1024
PBKDF2_ROUNDS = 100000

SUBJECTS = ['MATHEMATICS', 'ENGLISH LANGUAGE', 'IGBO LANGUAGE', 'SOCIAL HABIT', 'HEALTH HABIT', 'GENERAL SCIENCE',
            'C. R. S', 'FOOD & NUTRITION', 'WRITING', 'POEM', 'DRAWING / COLOURING', 'DICTATION']
DOMAINS = ['PUNCTUALITY', 'ATTENDANCE', 'SELF-CONTROL', 'NEATNESS', 'RESPONSIBILITY', 'DILIGENCE',
           'ATTENTIVENESS', 'LEGIBILITY', 'ACCURACY', 'SPORTS & GAMES']
FEES = [('TUITION FEE', 50000), ('EXAMINATION FEE', 1000), ('SPORT WEAR FEE', 233), ('LESSON FEE', 1300),
        ('', 4500), ('', 0), ('', 3500), ('', 0)]
REM = {'A': 'EXCELLENT', 'B': 'VERY GOOD', 'C': 'GOOD', 'D': 'FAIR', 'E': 'POOR', 'F': 'FAIL'}

SCHEMA = """
create table if not exists classes(
  id integer primary key, name text unique not null, category text default 'NURSERY', fees text default '[]',
  assess text default '', grading text default '', teacher_name text default '', teacher_sig text default '');
create table if not exists users(
  id integer primary key, username text unique not null collate nocase, name text not null,
  role text not null, salt text not null, pw text not null,
  class_id integer references classes(id), gender text default '', dob text default '', photo text default '',
  outstanding real default 0, created text default (datetime('now')), phone text default '',
  status text default 'active', last_login text default '');
create table if not exists subjects(
  id integer primary key, class_id integer not null references classes(id) on delete cascade,
  name text not null, pos integer default 0, unique(class_id, name));
create table if not exists scores(
  id integer primary key, student_id integer not null references users(id) on delete cascade,
  session text not null, term integer not null, subject_id integer not null references subjects(id) on delete cascade,
  ca1 real, ca2 real, exam real, ca3 real, unique(student_id, session, term, subject_id));
create table if not exists records(
  student_id integer not null references users(id) on delete cascade, session text not null, term integer not null,
  present integer, domains text default '{}', ct text default '', ht text default '', rdate text default '',
  primary key(student_id, session, term));
create table if not exists terms(
  session text not null, term integer not null, opened integer, closing text default '', resumption text default '',
  primary key(session, term));
create table if not exists sessions(
  token text primary key, user_id integer not null references users(id) on delete cascade, created real);
create table if not exists settings(k text primary key, v text);
create table if not exists counters(kind text not null, yr integer not null, n integer not null default 0, primary key(kind, yr));
create table if not exists accounts(id integer primary key, name text unique not null, kind text default 'cash', opening real default 0);
create table if not exists invoices(
  id integer primary key, no text unique not null, student_id integer not null references users(id),
  session text not null, term integer not null default 0, idate text not null, due text default '', items text not null,
  discount real default 0, total real not null, notes text default '', kind text default 'fees', status text default 'open',
  void_note text default '', created_by text default '', created text default (datetime('now')));
create table if not exists receipts(
  id integer primary key, no text unique not null, kind text not null default 'fee', student_id integer references users(id),
  payer text default '', category text default '', amount real not null, method text default 'CASH',
  account_id integer references accounts(id), ref text default '', rdate text not null, note text default '',
  status text default 'ok', void_note text default '', created_by text default '', created text default (datetime('now')));
create table if not exists allocations(
  receipt_id integer not null references receipts(id) on delete cascade, invoice_id integer not null references invoices(id) on delete cascade,
  amount real not null);
create table if not exists expenses(
  id integer primary key, no text unique not null, edate text not null, category text not null, payee text default '',
  description text default '', amount real not null, method text default 'CASH', account_id integer references accounts(id),
  ref text default '', status text default 'ok', void_note text default '', created_by text default '', created text default (datetime('now')));
create table if not exists msgs(
  id integer primary key, sender_id integer, sender_name text default '', sender_role text default '', to_kind text not null,
  to_user_id integer, to_role text, to_class_id integer, subject text default '', body text not null,
  created text default (datetime('now')), deleted integer default 0);
create table if not exists msg_state(
  msg_id integer not null references msgs(id) on delete cascade, user_id integer not null references users(id) on delete cascade,
  read integer default 0, hidden integer default 0, primary key(msg_id, user_id));
create table if not exists recov_used(nonce text primary key, used text default (datetime('now')));
create index if not exists ix_msgs_to on msgs(to_kind, to_user_id);
create table if not exists fee_types(id integer primary key, name text unique not null, amount real default 0, custom integer default 0, active integer default 1);
create table if not exists clearances(
  id integer primary key, no text unique not null, student_id integer not null references users(id), session text, term integer default 0,
  issued text, provisional integer default 0, note text default '', issued_by text default '');
create table if not exists applicants(
  id integer primary key, no text unique not null, name text not null, gender text default '', dob text default '', class_id integer references classes(id),
  parent_name text default '', phone text default '', email text default '', address text default '', prev_school text default '', status text default 'Applied',
  notes text default '', created text default (datetime('now')), student_id integer references users(id), source text default 'Office', session text default '', reg_no text default '');
create table if not exists lic_log(id integer primary key, kind text, ref text, summary text, created text default (datetime('now')));
create index if not exists ix_inv_student on invoices(student_id);
create index if not exists ix_alloc_inv on allocations(invoice_id);
create index if not exists ix_rcpt_student on receipts(student_id);
"""

# ----------------------------------------------------------------------------- plumbing
class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class Raw:
    def __init__(self, data, ctype, headers=()):
        self.data, self.ctype, self.headers = data, ctype, list(headers)


class Ctx:
    pass


ROUTES = {}


def route(method, path, roles=None):
    """Register a function. roles=None is public; otherwise a tuple of allowed roles."""
    def deco(fn):
        ROUTES[(method, path)] = (roles, fn)
        return fn
    return deco


STAFF = ('admin', 'staff')
ANY = ('admin', 'staff', 'accountant', 'student')


def hpw(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def mkpw(pw):
    salt = secrets.token_hex(16)
    return salt, hpw(pw, salt)


def settings(con):
    return {r['k']: r['v'] for r in con.execute('select k, v from settings')}


def setv(con, k, v):
    con.execute('insert into settings(k, v) values(?, ?) on conflict(k) do update set v = excluded.v', (k, str(v)))


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def n(v):
    return float(v) if v is not None else 0.0


def clean(x):
    x = round(x, 2)
    return int(x) if x == int(x) else x


def grade(t):
    return 'A' if t >= 70 else 'B' if t >= 60 else 'C' if t >= 50 else 'D' if t >= 45 else 'E' if t >= 40 else 'F'


def ordinal(k):
    if 10 <= k % 100 <= 20:
        return '%dth' % k
    return '%d%s' % (k, {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th'))


def ival(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiError('Invalid request')


def term_arg(v):
    if v == 'Y':
        return 'Y'
    t = ival(v)
    if t not in (1, 2, 3):
        raise ApiError('Term must be 1, 2, 3 or Y')
    return t


def current_session(c):
    return c.q.get('session') or c.body.get('session') or settings(c.con)['session']


def pub_user(u):
    return {'id': u['id'], 'username': u['username'], 'name': u['name'], 'role': u['role'], 'class_id': u['class_id']}


def user_from_cookie(con, cookie):
    jar = SimpleCookie()
    try:
        jar.load(cookie)
    except Exception:
        return None
    if 'sid' not in jar:
        return None
    row = con.execute('select u.*, s.created as sess_created from sessions s join users u on u.id = s.user_id '
                      'where s.token = ?', (jar['sid'].value,)).fetchone()
    if not row or time.time() - row['sess_created'] > SESSION_TTL or (row['status'] or 'active') != 'active':
        return None
    return row


FAILS = {}
FAILS_LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def send_out(self, code, body, ctype='application/json', headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self, method):
        u = urlparse(self.path)
        if method == 'GET' and u.path in ('/', '/index.html'):
            return self.send_out(200, INDEX_HTML, 'text/html; charset=utf-8')
        if method == 'GET' and u.path == '/apply':
            con0 = sqlite3.connect(DB)
            con0.row_factory = sqlite3.Row
            try:
                return self.send_out(200, apply_html(con0), 'text/html; charset=utf-8')
            finally:
                con0.close()
        if method == 'GET' and u.path.startswith('/legal/') and u.path[7:] in LEGAL:
            return self.send_out(200, legal_html(u.path[7:]), 'text/html; charset=utf-8')
        entry = ROUTES.get((method, u.path))
        if not entry:
            return self.send_out(404, {'error': 'Not found'})
        roles, fn = entry
        con = sqlite3.connect(DB, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('pragma foreign_keys = on')
        try:
            c = Ctx()
            c.con, c.headers, c.body, c.user, c.ip = con, [], {}, None, self.client_address[0]
            c.q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if method == 'POST':
                size = int(self.headers.get('Content-Length') or 0)
                if size > MAX_BODY:
                    self.rfile.read(size)
                    raise ApiError('That upload is too large')
                data = self.rfile.read(size)
                if data:
                    if 'application/json' not in (self.headers.get('Content-Type') or ''):
                        raise ApiError('Unsupported request')
                    try:
                        c.body = json.loads(data)
                    except ValueError:
                        raise ApiError('Invalid request')
            c.user = user_from_cookie(con, self.headers.get('Cookie', ''))
            if roles is not None:
                if not c.user:
                    raise ApiError('Please sign in', 401)
                if c.user['role'] not in roles:
                    raise ApiError('You are not allowed to do that', 403)
            if (method, u.path) not in LIC_OPEN and lic_status(con)['state'] == 'expired':
                raise ApiError('The free trial has ended. The administrator can activate the system from the License page.', 402)
            out = fn(c)
            con.commit()
            if isinstance(out, Raw):
                return self.send_out(200, out.data, out.ctype, out.headers + c.headers)
            return self.send_out(200, out if out is not None else {'ok': 1}, headers=c.headers)
        except ApiError as e:
            con.rollback()
            self.send_out(e.status, {'error': str(e)}, headers=c.headers)
        except sqlite3.IntegrityError:
            con.rollback()
            self.send_out(400, {'error': 'That name or number is already in use'})
        except Exception:
            con.rollback()
            traceback.print_exc()
            self.send_out(500, {'error': 'Server error. Check the server window for details.'})
        finally:
            con.close()

    def do_GET(self):
        self.handle_any('GET')

    def do_POST(self):
        self.handle_any('POST')


# ----------------------------------------------------------------------------- auth
@route('GET', '/api/public')
def r_public(c):
    s = settings(c.con)
    return {'school': s['school_name'], 'logo': s['logo'], 'version': VERSION, 'theme': theme_of(s)}


@route('POST', '/api/login')
def r_login(c):
    now = time.time()
    with FAILS_LOCK:
        recent = [t for t in FAILS.get(c.ip, []) if now - t < 300]
        FAILS[c.ip] = recent
        if len(recent) >= 8:
            raise ApiError('Too many wrong attempts. Wait five minutes and try again.', 429)
    u = c.con.execute('select * from users where username = ?', (str(c.body.get('username', '')).strip(),)).fetchone()
    if not u or not hmac.compare_digest(u['pw'], hpw(str(c.body.get('password', '')), u['salt'])):
        with FAILS_LOCK:
            FAILS[c.ip].append(now)
        raise ApiError('Wrong username or password', 401)
    if (u['status'] or 'active') != 'active':
        raise ApiError('This account has been suspended. Please contact the administrator.', 403)
    c.con.execute("update users set last_login = datetime('now', 'localtime') where id = ?", (u['id'],))
    c.con.execute('delete from sessions where created < ?', (now - SESSION_TTL,))
    tok = secrets.token_urlsafe(32)
    c.con.execute('insert into sessions(token, user_id, created) values(?, ?, ?)', (tok, u['id'], now))
    c.headers.append(('Set-Cookie', 'sid=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d' % (tok, SESSION_TTL)))
    return {'ok': 1}


@route('POST', '/api/logout', ANY)
def r_logout(c):
    c.con.execute('delete from sessions where user_id = ?', (c.user['id'],))
    c.headers.append(('Set-Cookie', 'sid=; Path=/; Max-Age=0'))


def known_sessions(con, current):
    found = {current}
    for r in con.execute('select distinct session from scores union select distinct session from terms'):
        found.add(r[0])
    return sorted(found, reverse=True)


@route('GET', '/api/me', ANY)
def r_me(c):
    s = settings(c.con)
    return {'user': pub_user(c.user), 'school': s['school_name'], 'session': s['session'],
            'sessions': known_sessions(c.con, s['session']), 'students_view': s['students_view'] == '1',
            'domains': domains_of(c.con), 'theme': theme_of(s), 'presets': {k: {'category': v['category'], 'label': v['label'], 'subjects': v['subjects']} for k, v in PRESETS.items()},
            'info': school_info(c.con) if c.user['role'] in ('admin', 'accountant') else None,
            'lic': {k: lic_status(c.con).get(k) for k in ('state', 'days_left', 'expires', 'reason')},
            'unread': unread_count(c.con, c.user), 'recovery_pending': bool(settings(c.con).get('recovery_pending')) and c.user['role'] == 'admin',
            'version': VERSION}


@route('POST', '/api/password', ANY)
def r_password(c):
    old, new = str(c.body.get('old', '')), str(c.body.get('new', ''))
    if not hmac.compare_digest(c.user['pw'], hpw(old, c.user['salt'])):
        raise ApiError('Your current password is not correct')
    if len(new) < 4:
        raise ApiError('Use at least 4 characters for the new password')
    salt, h = mkpw(new)
    c.con.execute('update users set salt = ?, pw = ? where id = ?', (salt, h, c.user['id']))


# ----------------------------------------------------------------------------- classes and subjects
def get_subjects(con, cid):
    return [dict(r) for r in con.execute('select id, name from subjects where class_id = ? order by pos, id', (cid,))]


def fees_of(cl):
    try:
        f = json.loads(cl['fees'])
    except ValueError:
        f = []
    f = [{'l': str(x.get('l', '')), 'a': num(x.get('a'))} for x in f][:8]
    return f + [{'l': '', 'a': 0}] * (8 - len(f))


@route('GET', '/api/classes', ('admin', 'staff', 'accountant'))
def r_classes(c):
    out = []
    for cl in c.con.execute('select * from classes order by name'):
        cnt = c.con.execute("select count(*) from users where role = 'student' and class_id = ?", (cl['id'],)).fetchone()[0]
        out.append({'id': cl['id'], 'name': cl['name'], 'category': cl['category'], 'fees': fees_of(cl),
                    'subjects': get_subjects(c.con, cl['id']), 'pupils': cnt, 'assess': assess_of(cl), 'grading': cl['grading'] or '',
                    'teacher_name': cl['teacher_name'] or '', 'has_sig': bool(cl['teacher_sig'])})
    out.sort(key=class_key)
    return out


@route('POST', '/api/classes', STAFF)
def r_class_save(c):
    b = c.body
    name = str(b.get('name', '')).strip().upper()
    if not name:
        raise ApiError('Enter a class name')
    subs, seen = [], set()
    for x in b.get('subjects', []):
        x = str(x).strip().upper()
        if x and x not in seen:
            seen.add(x)
            subs.append(x)
    if not subs:
        raise ApiError('Add at least one subject')
    fees = json.dumps([{'l': l, 'a': a} for l, a in BLANK_FEES])
    category = str(b.get('category', '')).strip().upper() or 'NURSERY'
    cid = b.get('id')
    if cid:
        c.con.execute('update classes set name = ?, category = ? where id = ?', (name, category, ival(cid)))
    else:
        cid = c.con.execute('insert into classes(name, category, fees) values(?, ?, ?)', (name, category, fees)).lastrowid
    if 'assess' in b:
        c.con.execute('update classes set assess = ? where id = ?', (json.dumps(clean_assess(b['assess'] or {})), cid))
    if 'grading' in b:
        g = str(b['grading'] or '')
        if g not in ('', 'standard', 'waec', 'custom'):
            raise ApiError('Unknown grading format')
        c.con.execute('update classes set grading = ? where id = ?', (g, cid))
    if 'teacher_name' in b:
        c.con.execute('update classes set teacher_name = ? where id = ?', (str(b['teacher_name'] or '').strip()[:80], cid))
    if 'teacher_sig' in b:
        sg = str(b['teacher_sig'] or '')
        if sg and (not sg.startswith('data:image/') or len(sg) > 250000):
            raise ApiError('The signature image is too large. Use a smaller picture.')
        c.con.execute('update classes set teacher_sig = ? where id = ?', (sg, cid))
    existing = {r['name']: r['id'] for r in c.con.execute('select id, name from subjects where class_id = ?', (cid,))}
    for i, s in enumerate(subs):
        if s in existing:
            c.con.execute('update subjects set pos = ? where id = ?', (i, existing[s]))
        else:
            c.con.execute('insert into subjects(class_id, name, pos) values(?, ?, ?)', (cid, s, i))
    for s, sid in existing.items():
        if s not in seen:
            c.con.execute('delete from subjects where id = ?', (sid,))
    return {'id': cid}


@route('POST', '/api/classes/delete', STAFF)
def r_class_delete(c):
    cid = ival(c.body.get('id'))
    if c.con.execute("select 1 from users where role = 'student' and class_id = ?", (cid,)).fetchone():
        raise ApiError('Move or delete the pupils in this class first')
    c.con.execute('delete from classes where id = ?', (cid,))


# ----------------------------------------------------------------------------- pupils
def pupil_dict(r):
    return {'id': r['id'], 'reg_no': r['username'], 'name': r['name'], 'class_id': r['class_id'], 'gender': r['gender'],
            'dob': r['dob'], 'photo': r['photo'], 'outstanding': r['outstanding'] or 0, 'phone': r['phone'] or ''}


@route('GET', '/api/students', ('admin', 'staff', 'accountant'))
def r_students(c):
    cid = ival(c.q.get('class'))
    rows = c.con.execute("select * from users where role = 'student' and class_id = ? order by name", (cid,))
    return [pupil_dict(r) for r in rows]


def next_reg(con):
    prefix = re.sub(r'[^A-Za-z0-9]', '', settings(con).get('reg_prefix', 'GA'))[:8].upper() or 'GA'
    yy = date.today().strftime('%y')
    k = con.execute("select count(*) from users where role = 'student'").fetchone()[0] + 1
    while True:
        reg = '%s%s%04d' % (prefix, yy, k)
        if not con.execute('select 1 from users where username = ?', (reg,)).fetchone():
            return reg
        k += 1


def check_photo(p):
    if p and (not str(p).startswith('data:image/') or len(p) > 400000):
        raise ApiError('Photo is too large. Use a smaller picture.')


@route('POST', '/api/students', STAFF)
def r_student_save(c):
    b = c.body
    name = str(b.get('name', '')).strip().upper()
    if not name:
        raise ApiError('Enter the pupil\'s name')
    cid = ival(b.get('class_id'))
    if not c.con.execute('select 1 from classes where id = ?', (cid,)).fetchone():
        raise ApiError('Choose a class')
    gender = str(b.get('gender', '')).upper()
    gender = gender if gender in ('MALE', 'FEMALE') else ''
    vals = (name, cid, gender, str(b.get('dob', ''))[:10], num(b.get('outstanding')))
    if b.get('id'):
        sid = ival(b['id'])
        reg = str(b.get('reg_no', '')).strip()
        if reg:
            c.con.execute("update users set username = ? where id = ? and role = 'student'", (reg, sid))
        c.con.execute("update users set name = ?, class_id = ?, gender = ?, dob = ?, outstanding = ? "
                      "where id = ? and role = 'student'", vals + (sid,))
        if 'photo' in b:
            check_photo(b['photo'])
            c.con.execute('update users set photo = ? where id = ?', (b['photo'] or '', sid))
    else:
        reg = str(b.get('reg_no', '')).strip() or next_reg(c.con)
        salt, h = mkpw(reg)
        check_photo(b.get('photo'))
        sid = c.con.execute("insert into users(username, name, role, salt, pw, class_id, gender, dob, outstanding, photo) "
                            "values(?, ?, 'student', ?, ?, ?, ?, ?, ?, ?)",
                            (reg, name, salt, h, cid, gender, vals[3], vals[4], b.get('photo') or '')).lastrowid
    c.con.execute("update users set phone = ? where id = ? and role = 'student'", (str(b.get('phone', ''))[:30], sid))
    return {'id': sid}


@route('POST', '/api/students/delete', STAFF)
def r_student_delete(c):
    sid = ival(c.body.get('id'))
    if c.con.execute('select 1 from invoices where student_id = ? union all select 1 from receipts where student_id = ?', (sid, sid)).fetchone():
        raise ApiError('This pupil has invoices or receipts. Financial records are kept, so the pupil cannot be deleted. Move the pupil to another class instead.')
    c.con.execute("delete from users where id = ? and role = 'student'", (sid,))


@route('POST', '/api/students/resetpw', STAFF)
def r_student_reset(c):
    u = c.con.execute("select * from users where id = ? and role = 'student'", (ival(c.body.get('id')),)).fetchone()
    if not u:
        raise ApiError('Pupil not found')
    salt, h = mkpw(u['username'])
    c.con.execute('update users set salt = ?, pw = ? where id = ?', (salt, h, u['id']))
    return {'reg_no': u['username']}


@route('POST', '/api/students/import', STAFF)
def r_student_import(c):
    cid = ival(c.body.get('class_id'))
    if not c.con.execute('select 1 from classes where id = ?', (cid,)).fetchone():
        raise ApiError('Choose a class')
    added, skipped = 0, 0
    for row in c.body.get('rows', [])[:1000]:
        name = str(row.get('name', '')).strip().upper()
        if not name:
            continue
        reg = str(row.get('reg_no', '')).strip() or next_reg(c.con)
        if c.con.execute('select 1 from users where username = ?', (reg,)).fetchone():
            skipped += 1
            continue
        g = str(row.get('gender', '')).strip().upper()
        g = {'M': 'MALE', 'F': 'FEMALE'}.get(g, g)
        g = g if g in ('MALE', 'FEMALE') else ''
        salt, h = mkpw(reg)
        c.con.execute("insert into users(username, name, role, salt, pw, class_id, gender, dob) "
                      "values(?, ?, 'student', ?, ?, ?, ?, ?)", (reg, name, salt, h, cid, g, str(row.get('dob', ''))[:10]))
        added += 1
    return {'added': added, 'skipped': skipped}


# ----------------------------------------------------------------------------- scores, attendance, remarks
FIELD = {'a': 'ca1', 'b': 'ca2', 'c': 'ca3', 'e': 'exam'}


def field_max(cl, f):
    a = assess_of(cl)
    if f == 'e':
        return a['exam']
    i = 'abc'.index(f)
    return a['ca'][i] if i < len(a['ca']) else None


@route('GET', '/api/scores', STAFF)
def r_scores(c):
    cid, term, ss = ival(c.q.get('class')), term_arg(c.q.get('term')), current_session(c)
    cl = c.con.execute('select * from classes where id = ?', (cid,)).fetchone()
    if not cl:
        raise ApiError('Class not found')
    studs = [{'id': r['id'], 'name': r['name'], 'reg_no': r['username']} for r in c.con.execute(
        "select id, name, username from users where role = 'student' and class_id = ? order by name", (cid,))]
    sc = {}
    for r in c.con.execute('select s.* from scores s join users u on u.id = s.student_id '
                           'where u.class_id = ? and s.session = ? and s.term = ?', (cid, ss, term)):
        sc.setdefault(r['student_id'], {})[r['subject_id']] = [r['ca1'], r['ca2'], r['ca3'], r['exam']]
    scheme = scheme_of(settings(c.con), cl)
    return {'subjects': get_subjects(c.con, cid), 'students': studs, 'scores': sc, 'assess': assess_of(cl),
            'scheme': {'key': scheme['key'], 'bands': [list(b) for b in scheme['bands']]}}


@route('POST', '/api/scores', STAFF)
def r_scores_save(c):
    items = c.body.get('items', [])
    classes = {}
    for it in items[:500]:
        col = FIELD.get(it.get('field'))
        if not col:
            raise ApiError('Invalid score field')
        sid, subid, term = ival(it.get('student_id')), ival(it.get('subject_id')), term_arg(it.get('term'))
        if term == 'Y':
            raise ApiError('Choose a term')
        ss = str(it.get('session') or settings(c.con)['session'])
        ok = c.con.execute("select u.class_id from users u join subjects s on s.class_id = u.class_id "
                           "where u.id = ? and u.role = 'student' and s.id = ?", (sid, subid)).fetchone()
        if not ok:
            raise ApiError('That subject does not belong to the pupil\'s class')
        if ok['class_id'] not in classes:
            classes[ok['class_id']] = c.con.execute('select * from classes where id = ?', (ok['class_id'],)).fetchone()
        mx = field_max(classes[ok['class_id']], it['field'])
        if mx is None:
            raise ApiError('This class does not use that assessment column')
        v = it.get('value')
        v = None if v in (None, '') else max(0.0, min(float(mx), num(v)))
        c.con.execute('insert into scores(student_id, session, term, subject_id, %s) values(?, ?, ?, ?, ?) '
                      'on conflict(student_id, session, term, subject_id) do update set %s = excluded.%s' % (col, col, col),
                      (sid, ss, term, subid, v))
    return {'saved': len(items)}


@route('GET', '/api/records', STAFF)
def r_records(c):
    cid, term, ss = ival(c.q.get('class')), ival(c.q.get('term')), current_session(c)
    studs = [{'id': r['id'], 'name': r['name']} for r in c.con.execute(
        "select id, name from users where role = 'student' and class_id = ? order by name", (cid,))]
    recs = {}
    for r in c.con.execute('select r.* from records r join users u on u.id = r.student_id '
                           'where u.class_id = ? and r.session = ? and r.term = ?', (cid, ss, term)):
        recs[r['student_id']] = {'present': r['present'], 'domains': json.loads(r['domains'] or '{}'),
                                 'ct': r['ct'], 'ht': r['ht'], 'date': r['rdate']}
    m = c.con.execute('select * from terms where session = ? and term = ?', (ss, term)).fetchone()
    meta = {'opened': m['opened'], 'closing': m['closing'], 'resumption': m['resumption']} if m else \
        {'opened': None, 'closing': '', 'resumption': ''}
    return {'students': studs, 'records': recs, 'meta': meta}


@route('POST', '/api/record', STAFF)
def r_record_save(c):
    b = c.body
    sid, term, ss = ival(b.get('student_id')), ival(b.get('term')), str(b.get('session') or settings(c.con)['session'])
    c.con.execute('insert or ignore into records(student_id, session, term) values(?, ?, ?)', (sid, ss, term))
    f = b.get('field')
    if f == 'present':
        v = None if b.get('value') in (None, '') else max(0, ival(b['value']))
        c.con.execute('update records set present = ? where student_id = ? and session = ? and term = ?', (v, sid, ss, term))
    elif f in ('ct', 'ht', 'rdate'):
        c.con.execute('update records set %s = ? where student_id = ? and session = ? and term = ?' % f,
                      (str(b.get('value', ''))[:400], sid, ss, term))
    elif f == 'domain':
        name = b.get('name')
        if name not in domains_of(c.con):
            raise ApiError('Unknown domain')
        row = c.con.execute('select domains from records where student_id = ? and session = ? and term = ?',
                            (sid, ss, term)).fetchone()
        d = json.loads(row['domains'] or '{}')
        v = str(b.get('value', ''))
        if v in ('1', '2', '3', '4', '5'):
            d[name] = v
        else:
            d.pop(name, None)
        c.con.execute('update records set domains = ? where student_id = ? and session = ? and term = ?',
                      (json.dumps(d), sid, ss, term))
    else:
        raise ApiError('Invalid field')


@route('POST', '/api/term', STAFF)
def r_term_save(c):
    b = c.body
    term, ss, f = ival(b.get('term')), str(b.get('session') or settings(c.con)['session']), b.get('field')
    if f not in ('opened', 'closing', 'resumption') or term not in (1, 2, 3):
        raise ApiError('Invalid field')
    c.con.execute('insert or ignore into terms(session, term) values(?, ?)', (ss, term))
    v = b.get('value')
    if f == 'opened':
        v = None if v in (None, '') else max(0, ival(v))
    else:
        v = str(v or '')[:10]
    c.con.execute('update terms set %s = ? where session = ? and term = ?' % f, (v, ss, term))


# ----------------------------------------------------------------------------- results engine
class Sheeter:
    """Loads one class for one session and builds report sheets, positions and broadsheets."""

    def __init__(self, con, cid, ss):
        self.con, self.ss, self.set = con, ss, settings(con)
        self.cl = con.execute('select * from classes where id = ?', (cid,)).fetchone()
        if not self.cl:
            raise ApiError('Class not found')
        self.subj = get_subjects(con, cid)
        self.scheme, self.assess, self.layout = scheme_of(self.set, self.cl), assess_of(self.cl), layout_of(self.set)
        self.fees = fees_of(self.cl)
        self.students = list(con.execute("select * from users where role = 'student' and class_id = ? order by name", (cid,)))
        self.sc = {1: {}, 2: {}, 3: {}}
        for r in con.execute('select s.* from scores s join users u on u.id = s.student_id '
                             'where u.class_id = ? and s.session = ?', (cid, ss)):
            self.sc[r['term']].setdefault(r['student_id'], {})[r['subject_id']] = r
        self.rec = {(r['student_id'], r['term']): r for r in con.execute(
            'select r.* from records r join users u on u.id = r.student_id where u.class_id = ? and r.session = ?', (cid, ss))}
        self.terms = {r['term']: r for r in con.execute('select * from terms where session = ?', (ss,))}
        self._tot = {}
        self.bal = {r['sid']: max(0.0, round(r['billed'] - r['paid'], 2)) for r in con.execute(
            "select i.student_id as sid, sum(i.total) as billed, sum(coalesce(p.paid, 0)) as paid from invoices i "
            "left join (select invoice_id, sum(amount) as paid from allocations group by invoice_id) p on p.invoice_id = i.id "
            "where i.status = 'open' and i.student_id in (select id from users where class_id = ?) group by i.student_id", (cid,))}

    def rows_term(self, sid, t):
        d, out = self.sc[t].get(sid, {}), []
        for sub in self.subj:
            r = d.get(sub['id'])
            a, b, c3, e = (r['ca1'], r['ca2'], r['ca3'], r['exam']) if r else (None, None, None, None)
            tot = n(a) + n(b) + n(c3) + n(e)
            g, rm = grade_in(self.scheme['bands'], tot)
            out.append({'s': sub['name'], 'a': a, 'b': b, 'c': c3, 'e': e, 'tot': clean(tot), 'g': g, 'rem': rm})
        return out

    def rows_year(self, sid):
        out = []
        for sub in self.subj:
            ts = []
            for t in (1, 2, 3):
                r = self.sc[t].get(sid, {}).get(sub['id'])
                ts.append(n(r['ca1']) + n(r['ca2']) + n(r['ca3']) + n(r['exam']) if r else 0.0)
            total = sum(ts)
            out.append({'s': sub['name'], 'a': [clean(x) for x in ts], 'tot': clean(total),
                        'avg': round(total / 3, 2), 'g': grade_in(self.scheme['bands'], total / 3)[0]})
        return out

    def total_of(self, sid, t):
        key = (sid, t)
        if key not in self._tot:
            rows = self.rows_year(sid) if t == 'Y' else self.rows_term(sid, t)
            self._tot[key] = sum(n(r['tot']) for r in rows)
        return self._tot[key]

    def has_scores(self, sid, t):
        for x in ((1, 2, 3) if t == 'Y' else (t,)):
            for r in self.sc[x].get(sid, {}).values():
                if r['ca1'] is not None or r['ca2'] is not None or r['ca3'] is not None or r['exam'] is not None:
                    return True
        return False

    def position(self, sid, t):
        if not self.has_scores(sid, t):
            return ''
        me = self.total_of(sid, t)
        return ordinal(1 + sum(1 for s in self.students if self.total_of(s['id'], t) > me))

    def sheet(self, st, t):
        Y = t == 'Y'
        sid, nsub = st['id'], len(self.subj) or 1
        rows = self.rows_year(sid) if Y else self.rows_term(sid, t)
        total = sum(n(r['tot']) for r in rows)
        if Y:
            avg = total / nsub if self.set.get('yearly_method', 'sample') == 'sample' else total / (3 * nsub)
        else:
            avg = total / nsub
        tn = 3 if Y else t
        r = self.rec.get((sid, tn))
        mt = self.terms.get(tn)
        if Y:
            opened_l = [self.terms[x]['opened'] for x in (1, 2, 3) if x in self.terms and self.terms[x]['opened'] is not None]
            present_l = [self.rec[(sid, x)]['present'] for x in (1, 2, 3) if (sid, x) in self.rec and self.rec[(sid, x)]['present'] is not None]
            opened = sum(opened_l) if opened_l else None
            present = sum(present_l) if present_l else None
        else:
            opened = mt['opened'] if mt else None
            present = r['present'] if r else None
        doms = json.loads(r['domains'] or '{}') if r else {}
        has = self.has_scores(sid, t)
        norm = total / (3 * nsub) if Y else total / nsub
        ct, ht = (r['ct'] if r and r['ct'] else ''), (r['ht'] if r and r['ht'] else '')
        if self.set.get('remarks_mode', 'manual') == 'auto' and has:
            ct = ct or auto_remark(jload(self.set.get('remarks_bank'), DEFAULT_CT_BANK), norm)
            ht = ht or auto_remark(jload(self.set.get('head_bank'), DEFAULT_HT_BANK), norm)
        rdate = r['rdate'] if r and r['rdate'] else ''
        if not rdate and self.set.get('date_mode', 'manual') == 'auto' and has:
            rdate = (mt['closing'] if mt and mt['closing'] else date.today().isoformat())
        auto_sig = self.set.get('sig_mode', 'manual') == 'auto'
        sig = {'show': auto_sig, 'head_name': self.set.get('head_name', '') if auto_sig else '', 'head_sig': self.set.get('head_sig', '') if auto_sig else '',
               'teacher_name': (self.cl['teacher_name'] or '') if auto_sig else '', 'teacher_sig': (self.cl['teacher_sig'] or '') if auto_sig else ''}
        out_bal = self.bal.get(sid, st['outstanding'] or 0)
        bill = sum(f['a'] for f in self.fees) + out_bal
        return {
            'school': {'name': self.set['school_name'], 'address': self.set['address'], 'contact': self.set['contact'],
                       'motto': self.set['motto'], 'logo': self.set['logo']},
            'student': {'id': sid, 'name': st['name'], 'reg_no': st['username'], 'gender': st['gender'],
                        'dob': st['dob'], 'photo': st['photo']},
            'cls': {'name': self.cl['name'], 'category': self.cl['category']},
            'session': self.ss, 'term': t, 'Y': Y, 'n_in_class': len(self.students),
            'opened': opened, 'present': present,
            'absent': (opened - present) if (opened is not None and present is not None) else None,
            'closing': mt['closing'] if mt else '', 'resumption': mt['resumption'] if mt else '',
            'total': clean(total), 'avg': round(avg, 2), 'pct': int(avg + 0.5), 'position': self.position(sid, t),
            'rows': rows, 'domains': [[d, doms.get(d, '')] for d in self.layout['domains']], 'fees': self.fees,
            'assess': self.assess, 'scheme': {'key': self.scheme['key'], 'keys': self.scheme['keys']}, 'layout': self.layout, 'sig': sig,
            'outstanding': out_bal, 'bill_total': clean(bill),
            'ct': ct, 'ht': ht, 'date': rdate}


def student_row(con, sid):
    return con.execute("select * from users where id = ? and role = 'student'", (sid,)).fetchone()


@route('GET', '/api/sheet', ANY)
def r_sheet(c):
    t, ss = term_arg(c.q.get('term', '1')), current_session(c)
    if c.user['role'] == 'student':
        if settings(c.con)['students_view'] != '1':
            raise ApiError('Results have not been released yet', 403)
        st = c.user
    else:
        st = student_row(c.con, ival(c.q.get('student')))
    if not st or not st['class_id']:
        raise ApiError('Pupil not found')
    return Sheeter(c.con, st['class_id'], ss).sheet(st, t)


@route('GET', '/api/sheets', STAFF)
def r_sheets(c):
    sh = Sheeter(c.con, ival(c.q.get('class')), current_session(c))
    t = term_arg(c.q.get('term', '1'))
    return [sh.sheet(s, t) for s in sh.students]


@route('GET', '/api/broadsheet', STAFF)
def r_broadsheet(c):
    sh = Sheeter(c.con, ival(c.q.get('class')), current_session(c))
    t = term_arg(c.q.get('term', '1'))
    rows = []
    for st in sh.students:
        d = sh.sheet(st, t)
        rows.append({'name': st['name'], 'reg_no': st['username'], 'vals': [r['tot'] for r in d['rows']],
                     'total': d['total'], 'avg': d['avg'], 'pos': d['position']})
    return {'subjects': [s['name'] for s in sh.subj], 'rows': rows, 'cls': sh.cl['name'], 'session': sh.ss}


@route('GET', '/api/dashboard', STAFF)
def r_dashboard(c):
    ss = current_session(c)
    out = {'pupils': c.con.execute("select count(*) from users where role = 'student'").fetchone()[0],
           'classes': c.con.execute('select count(*) from classes').fetchone()[0],
           'staff': c.con.execute("select count(*) from users where role in ('admin','staff','accountant')").fetchone()[0],
           'progress': []}
    for cl in sorted(c.con.execute('select * from classes').fetchall(), key=class_key):
        row = {'class': cl['name'], 'pupils': c.con.execute(
            "select count(*) from users where role = 'student' and class_id = ?", (cl['id'],)).fetchone()[0]}
        for t in (1, 2, 3):
            row['t%d' % t] = c.con.execute(
                'select count(distinct s.student_id) from scores s join users u on u.id = s.student_id '
                'where u.class_id = ? and s.session = ? and s.term = ? and (s.ca1 is not null or s.ca2 is not null or s.ca3 is not null or s.exam is not null)',
                (cl['id'], ss, t)).fetchone()[0]
        out['progress'].append(row)
    return out


@route('POST', '/api/demo', STAFF)
def r_demo(c):
    """Adds one pupil whose scores reproduce the sample report sheets (Mathematics 44, 64, 84; bill 65,533)."""
    cl = c.con.execute('select * from classes order by id limit 1').fetchone()
    if not cl:
        raise ApiError('Add a class first')
    ss = settings(c.con)['session']
    reg = 'SAMPLE001'
    if c.con.execute('select 1 from users where username = ?', (reg,)).fetchone():
        raise ApiError('The sample pupil already exists')
    salt, h = mkpw(reg)
    sid = c.con.execute("insert into users(username, name, role, salt, pw, class_id, outstanding) "
                        "values(?, 'SAMPLE PUPIL', 'student', ?, ?, ?, 0)", (reg, salt, h, cl['id'])).lastrowid
    math = get_subjects(c.con, cl['id'])[0]['id']
    for t, a, b, e in ((1, None, 20, 24), (2, 20, 20, 24), (3, 20, 20, 44)):
        c.con.execute('insert into scores(student_id, session, term, subject_id, ca1, ca2, exam) values(?, ?, ?, ?, ?, ?, ?)',
                      (sid, ss, t, math, a, b, e))
        c.con.execute('insert into records(student_id, session, term, present) values(?, ?, ?, 4)', (sid, ss, t))
        c.con.execute('insert into terms(session, term, opened) values(?, ?, 16) '
                      'on conflict(session, term) do update set opened = 16', (ss, t))
    make_invoice(c.con, c.user['name'], sid, ss, 0, date.today().isoformat(), '', [{'l': 'BALANCE BROUGHT FORWARD', 'a': 5000}], 0, '', 'custom')
    return {'id': sid}


# ----------------------------------------------------------------------------- staff and settings (admin)
@route('GET', '/api/staff', ('admin',))
def r_staff(c):
    return [{'id': r['id'], 'username': r['username'], 'name': r['name'], 'role': r['role']} for r in
            c.con.execute("select * from users where role in ('admin','staff','accountant') order by role, name")]


@route('POST', '/api/staff', ('admin',))
def r_staff_save(c):
    b = c.body
    name, un = str(b.get('name', '')).strip(), str(b.get('username', '')).strip()
    role = b.get('role') if b.get('role') in ('admin', 'staff', 'accountant') else 'staff'
    if not name or not un:
        raise ApiError('Enter the name and username')
    pw = str(b.get('password', ''))
    if b.get('id'):
        sid = ival(b['id'])
        if sid == c.user['id'] and role != 'admin':
            raise ApiError('You cannot remove your own admin access')
        c.con.execute("update users set name = ?, username = ?, role = ? where id = ? and role in ('admin','staff','accountant')",
                      (name, un, role, sid))
        if pw:
            if len(pw) < 4:
                raise ApiError('Use at least 4 characters for the password')
            salt, h = mkpw(pw)
            c.con.execute('update users set salt = ?, pw = ? where id = ?', (salt, h, sid))
    else:
        if len(pw) < 4:
            raise ApiError('Use at least 4 characters for the password')
        salt, h = mkpw(pw)
        c.con.execute('insert into users(username, name, role, salt, pw) values(?, ?, ?, ?, ?)', (un, name, role, salt, h))


@route('POST', '/api/staff/delete', ('admin',))
def r_staff_delete(c):
    sid = ival(c.body.get('id'))
    if sid == c.user['id']:
        raise ApiError('You cannot delete your own account')
    c.con.execute("delete from users where id = ? and role in ('admin','staff','accountant')", (sid,))


def lan_urls():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    return ['http://%s:%d' % (ip, PORT) for ip in sorted(ips) if not ip.startswith('127.')]


SETTING_KEYS = ('school_name', 'address', 'contact', 'motto', 'logo', 'session', 'yearly_method', 'students_view', 'bank_details', 'invoice_note',
                'reg_prefix', 'admissions_open', 'admission_letter', 'grading_default', 'grading_custom', 'remarks_mode', 'remarks_bank', 'head_bank', 'head_name', 'head_sig', 'sig_mode', 'date_mode', 'layout', 'theme')


@route('GET', '/api/settings', ('admin',))
def r_settings(c):
    s = settings(c.con)
    out = {k: s.get(k, '') for k in SETTING_KEYS}
    out['urls'] = lan_urls()
    out['port'] = PORT
    return out


@route('POST', '/api/settings', ('admin',))
def r_settings_save(c):
    for k, v in c.body.items():
        if k not in SETTING_KEYS:
            continue
        v = str(v).strip() if k not in ('logo', 'head_sig') else str(v)
        if k in JSON_KEYS:
            try:
                json.loads(v)
            except ValueError:
                raise ApiError('Invalid settings data')
            if len(v) > 40000:
                raise ApiError('That setting is too large')
        if k == 'head_sig' and v and (not v.startswith('data:image/') or len(v) > 250000):
            raise ApiError('The signature image is too large. Use a smaller picture.')
        if k == 'grading_default' and v not in ('standard', 'waec', 'custom'):
            raise ApiError('Unknown grading format')
        if k == 'admissions_open':
            v = '1' if v in ('1', 'true', 'True') else '0'
        if k == 'reg_prefix':
            v = re.sub(r'[^A-Za-z0-9]', '', v)[:8].upper() or 'GA'
        if k == 'remarks_mode' and v not in ('manual', 'auto'):
            raise ApiError('Invalid option')
        if k == 'sig_mode' and v not in ('manual', 'auto'):
            raise ApiError('Invalid option')
        if k == 'date_mode' and v not in ('manual', 'auto'):
            raise ApiError('Invalid option')
        if k == 'logo' and v and (not v.startswith('data:image/') or len(v) > 600000):
            raise ApiError('The crest image is too large')
        if k == 'session' and not v:
            raise ApiError('Enter the session, for example 2026/2027')
        if k == 'yearly_method' and v not in ('sample', 'true'):
            raise ApiError('Invalid option')
        if k == 'students_view':
            v = '1' if v in ('1', 'true', 'True') else '0'
        setv(c.con, k, v)


@route('GET', '/api/backup', ('admin',))
def r_backup(c):
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        dst = sqlite3.connect(path)
        c.con.backup(dst)
        dst.close()
        with open(path, 'rb') as f:
            data = f.read()
    finally:
        os.remove(path)
    name = 'school_system_backup_%s.db' % date.today().strftime('%Y%m%d')
    return Raw(data, 'application/octet-stream', [('Content-Disposition', 'attachment; filename="%s"' % name)])


# ----------------------------------------------------------------------------- class presets (KG, nursery, primary, secondary)
PRESETS = {
    'KG': {'category': 'KG', 'label': 'KG', 'subjects': [
        'NUMBER WORK', 'LETTER WORK', 'READING', 'RHYMES', 'SOCIAL HABIT', 'HEALTH HABIT', 'IGBO LANGUAGE',
        'C. R. S', 'WRITING', 'DRAWING / COLOURING']},
    'NURSERY': {'category': 'NURSERY', 'label': 'Nursery', 'subjects': list(SUBJECTS)},
    'PRIMARY': {'category': 'PRIMARY', 'label': 'Primary', 'subjects': [
        'MATHEMATICS', 'ENGLISH LANGUAGE', 'IGBO LANGUAGE', 'BASIC SCIENCE', 'SOCIAL STUDIES', 'C. R. S',
        'CIVIC EDUCATION', 'COMPUTER STUDIES', 'AGRICULTURAL SCIENCE', 'HOME ECONOMICS',
        'PHYSICAL & HEALTH EDUCATION', 'CULTURAL & CREATIVE ARTS', 'VERBAL REASONING', 'HANDWRITING']},
    'JSS': {'category': 'SECONDARY', 'label': 'Secondary (JSS)', 'subjects': [
        'MATHEMATICS', 'ENGLISH LANGUAGE', 'IGBO LANGUAGE', 'BASIC SCIENCE', 'BASIC TECHNOLOGY', 'SOCIAL STUDIES',
        'CIVIC EDUCATION', 'C. R. S', 'BUSINESS STUDIES', 'COMPUTER STUDIES', 'AGRICULTURAL SCIENCE',
        'HOME ECONOMICS', 'PHYSICAL & HEALTH EDUCATION', 'CULTURAL & CREATIVE ARTS', 'FRENCH']},
    'SSS': {'category': 'SECONDARY', 'label': 'Secondary (SSS)', 'subjects': [
        'MATHEMATICS', 'ENGLISH LANGUAGE', 'CIVIC EDUCATION', 'BIOLOGY', 'CHEMISTRY', 'PHYSICS', 'ECONOMICS',
        'GOVERNMENT', 'LITERATURE-IN-ENGLISH', 'COMMERCE', 'FINANCIAL ACCOUNTING', 'AGRICULTURAL SCIENCE',
        'C. R. S', 'GEOGRAPHY', 'COMPUTER STUDIES', 'IGBO LANGUAGE']},
}
STANDARD_CLASSES = ([('KG %d' % i, 'KG') for i in (1, 2)] + [('NURSERY %d' % i, 'NURSERY') for i in (1, 2)] +
                    [('PRIMARY %d' % i, 'PRIMARY') for i in range(1, 7)] + [('JSS %d' % i, 'JSS') for i in (1, 2, 3)] +
                    [('SS %d' % i, 'SSS') for i in (1, 2, 3)])
CAT_RANK = {'KG': 0, 'NURSERY': 1, 'PRIMARY': 2, 'SECONDARY': 3}
BLANK_FEES = [('TUITION FEE', 0), ('EXAMINATION FEE', 0), ('', 0), ('', 0), ('', 0), ('', 0), ('', 0), ('', 0)]


def class_key(c):
    return (CAT_RANK.get(c['category'], 9), re.sub(r'\d+', lambda m: m.group().zfill(4), c['name']))


@route('POST', '/api/classes/standard', STAFF)
def r_classes_standard(c):
    made = 0
    for name, key in STANDARD_CLASSES:
        if c.con.execute('select 1 from classes where name = ?', (name,)).fetchone():
            continue
        p = PRESETS[key]
        cid = c.con.execute('insert into classes(name, category, fees) values(?, ?, ?)',
                            (name, p['category'], json.dumps([{'l': l, 'a': a} for l, a in BLANK_FEES]))).lastrowid
        for i, s in enumerate(p['subjects']):
            c.con.execute('insert into subjects(class_id, name, pos) values(?, ?, ?)', (cid, s, i))
        made += 1
    return {'made': made}


@route('POST', '/api/students/move', STAFF)
def r_students_move(c):
    cid = ival(c.body.get('class_id'))
    if not c.con.execute('select 1 from classes where id = ?', (cid,)).fetchone():
        raise ApiError('Choose the class to move to')
    ids = [ival(x) for x in c.body.get('ids', [])][:1000]
    for i in ids:
        c.con.execute("update users set class_id = ? where id = ? and role = 'student'", (cid, i))
    return {'moved': len(ids)}


# ----------------------------------------------------------------------------- accounting
FIN = ('admin', 'accountant')
METHODS = ('CASH', 'TRANSFER', 'POS', 'CHEQUE')


def dstr(v):
    v = str(v or '')[:10]
    try:
        date.fromisoformat(v)
    except ValueError:
        return date.today().isoformat()
    return v


def amt(v):
    x = round(num(v), 2)
    if x <= 0:
        raise ApiError('Enter an amount greater than zero')
    return x


def next_no(con, kind, dt):
    yr = int(dt[:4])
    con.execute('insert or ignore into counters(kind, yr, n) values(?, ?, 0)', (kind, yr))
    con.execute('update counters set n = n + 1 where kind = ? and yr = ?', (kind, yr))
    k = con.execute('select n from counters where kind = ? and yr = ?', (kind, yr)).fetchone()[0]
    return '%s-%d-%04d' % (kind, yr, k)


def school_info(con):
    s = settings(con)
    return {'name': s['school_name'], 'address': s['address'], 'contact': s['contact'], 'motto': s['motto'],
            'logo': s['logo'], 'bank': s.get('bank_details', ''), 'note': s.get('invoice_note', '')}


INV_SQL = ("select i.*, u.name as sname, u.username as reg, u.phone as phone, u.class_id as cid, c.name as cname, "
           "coalesce(p.paid, 0) as paid from invoices i join users u on u.id = i.student_id "
           "left join classes c on c.id = u.class_id "
           "left join (select invoice_id, sum(amount) as paid from allocations group by invoice_id) p on p.invoice_id = i.id ")


def inv_dict(r):
    paid = round(r['paid'], 2)
    return {'id': r['id'], 'no': r['no'], 'student_id': r['student_id'], 'sname': r['sname'], 'reg': r['reg'],
            'phone': r['phone'], 'cid': r['cid'], 'cname': r['cname'] or '', 'session': r['session'], 'term': r['term'],
            'idate': r['idate'], 'due': r['due'], 'total': r['total'], 'discount': r['discount'], 'paid': paid,
            'balance': round(r['total'] - paid, 2), 'status': r['status'], 'kind': r['kind'], 'notes': r['notes'],
            'items': json.loads(r['items'] or '[]')}


def apply_credit(con, sid):
    """Use any unallocated part of a pupil's fee receipts to clear their oldest unpaid invoices."""
    creds = con.execute("select r.id, r.amount - coalesce((select sum(amount) from allocations where receipt_id = r.id), 0) as rem "
                        "from receipts r where r.student_id = ? and r.kind = 'fee' and r.status = 'ok' "
                        "order by r.rdate, r.id", (sid,)).fetchall()
    invs = con.execute("select i.id, i.total - coalesce((select sum(amount) from allocations where invoice_id = i.id), 0) as due "
                       "from invoices i where i.student_id = ? and i.status = 'open' order by i.idate, i.id", (sid,)).fetchall()
    dues = [[r['id'], round(r['due'], 2)] for r in invs]
    for cr in creds:
        rem = round(cr['rem'], 2)
        for d in dues:
            if rem <= 0:
                break
            if d[1] <= 0:
                continue
            x = min(rem, d[1])
            con.execute('insert into allocations(receipt_id, invoice_id, amount) values(?, ?, ?)', (cr['id'], d[0], x))
            rem = round(rem - x, 2)
            d[1] = round(d[1] - x, 2)


def student_fin(con, sid):
    billed, paid = con.execute("select coalesce(sum(i.total), 0), coalesce(sum((select coalesce(sum(amount), 0) from allocations "
                               "where invoice_id = i.id)), 0) from invoices i where i.student_id = ? and i.status = 'open'", (sid,)).fetchone()
    rec = con.execute("select coalesce(sum(amount), 0) from receipts where student_id = ? and kind = 'fee' and status = 'ok'", (sid,)).fetchone()[0]
    alloc = con.execute("select coalesce(sum(a.amount), 0) from allocations a join receipts r on r.id = a.receipt_id "
                        "where r.student_id = ? and r.status = 'ok'", (sid,)).fetchone()[0]
    return {'billed': round(billed, 2), 'paid': round(paid, 2), 'balance': round(billed - paid, 2),
            'credit': round(rec - alloc, 2)}


def make_invoice(con, by, sid, ss, term, idate, due, items, discount, notes, kind):
    items = [{'l': (str(i.get('l', '')).strip().upper() or 'OTHER FEE'), 'a': round(num(i.get('a')), 2)}
             for i in items if num(i.get('a')) > 0]
    if not items:
        raise ApiError('Add at least one fee line with an amount')
    sub = round(sum(i['a'] for i in items), 2)
    disc = round(min(max(num(discount), 0.0), sub), 2)
    no = next_no(con, 'INV', idate)
    iid = con.execute('insert into invoices(no, student_id, session, term, idate, due, items, discount, total, notes, kind, created_by) '
                      'values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (no, sid, ss, term, idate, due, json.dumps(items), disc, round(sub - disc, 2), notes, kind, by)).lastrowid
    apply_credit(con, sid)
    return iid, no


def need_student(con, sid):
    st = con.execute("select * from users where id = ? and role = 'student'", (sid,)).fetchone()
    if not st:
        raise ApiError('Pupil not found')
    return st


@route('POST', '/api/fees', FIN)
def r_fees(c):
    cid = ival(c.body.get('class_id'))
    fees = [{'l': str(f.get('l', '')).strip().upper(), 'a': max(0.0, round(num(f.get('a')), 2))}
            for f in c.body.get('fees', [])][:8]
    fees += [{'l': '', 'a': 0}] * (8 - len(fees))
    c.con.execute('update classes set fees = ? where id = ?', (json.dumps(fees), cid))


@route('GET', '/api/invoices', FIN)
def r_invoices(c):
    w, p = ['1 = 1'], []
    if c.q.get('session'):
        w.append('i.session = ?'); p.append(c.q['session'])
    if c.q.get('term') not in (None, ''):
        w.append('i.term = ?'); p.append(ival(c.q['term']))
    if c.q.get('class'):
        w.append('u.class_id = ?'); p.append(ival(c.q['class']))
    if c.q.get('student'):
        w.append('i.student_id = ?'); p.append(ival(c.q['student']))
    st = c.q.get('status', '')
    if st == 'void':
        w.append("i.status = 'void'")
    else:
        w.append("i.status = 'open'")
    if c.q.get('q'):
        w.append('(u.name like ? or u.username like ? or i.no like ?)'); p += ['%' + c.q['q'] + '%'] * 3
    rows = [inv_dict(r) for r in c.con.execute(INV_SQL + 'where ' + ' and '.join(w) + ' order by i.idate desc, i.id desc limit 1000', p)]
    if st == 'unpaid':
        rows = [r for r in rows if r['balance'] > 0.004]
    elif st == 'paid':
        rows = [r for r in rows if r['balance'] <= 0.004]
    return {'rows': rows, 'billed': round(sum(r['total'] for r in rows if r['status'] == 'open'), 2),
            'paid': round(sum(r['paid'] for r in rows if r['status'] == 'open'), 2)}


@route('POST', '/api/invoices/generate', FIN)
def r_inv_generate(c):
    b = c.body
    cid, term = ival(b.get('class_id')), ival(b.get('term'))
    if term not in (1, 2, 3):
        raise ApiError('Choose a term')
    ss = str(b.get('session') or settings(c.con)['session'])
    cl = c.con.execute('select * from classes where id = ?', (cid,)).fetchone()
    if not cl:
        raise ApiError('Choose a class')
    items = [{'l': f['l'] or 'OTHER FEE', 'a': f['a']} for f in fees_of(cl) if f['a'] > 0]
    if not items:
        raise ApiError('Set the fee schedule for this class first (Fees page)')
    idate, due = dstr(b.get('idate')), str(b.get('due') or '')[:10]
    studs = c.con.execute("select * from users where role = 'student' and class_id = ? order by name", (cid,)).fetchall()
    made = skipped = 0
    for st in studs:
        if c.con.execute("select 1 from invoices where student_id = ? and session = ? and term = ? and kind = 'fees' and status = 'open'",
                         (st['id'], ss, term)).fetchone():
            skipped += 1
            continue
        make_invoice(c.con, c.user['name'], st['id'], ss, term, idate, due, items, 0, '', 'fees')
        made += 1
    return {'made': made, 'skipped': skipped}


@route('POST', '/api/invoices', FIN)
def r_inv_custom(c):
    b = c.body
    st = need_student(c.con, ival(b.get('student_id')))
    term = ival(b.get('term') or 0)
    if term not in (0, 1, 2, 3):
        raise ApiError('Invalid term')
    iid, no = make_invoice(c.con, c.user['name'], st['id'], str(b.get('session') or settings(c.con)['session']), term,
                           dstr(b.get('idate')), str(b.get('due') or '')[:10], b.get('items', []), b.get('discount'),
                           str(b.get('notes', ''))[:300], 'custom')
    return {'id': iid, 'no': no}


@route('GET', '/api/invoice', FIN)
def r_invoice(c):
    r = c.con.execute(INV_SQL + 'where i.id = ?', (ival(c.q.get('id')),)).fetchone()
    if not r:
        raise ApiError('Invoice not found')
    d = inv_dict(r)
    d['school'] = school_info(c.con)
    d['receipts'] = [{'no': x['no'], 'rdate': x['rdate'], 'amount': x['amount'], 'method': x['method']} for x in c.con.execute(
        "select r.no, r.rdate, a.amount, r.method from allocations a join receipts r on r.id = a.receipt_id "
        "where a.invoice_id = ? order by r.rdate, r.id", (d['id'],))]
    d['fin'] = student_fin(c.con, d['student_id'])
    return d


@route('POST', '/api/invoices/void', FIN)
def r_inv_void(c):
    iid = ival(c.body.get('id'))
    r = c.con.execute('select * from invoices where id = ?', (iid,)).fetchone()
    if not r or r['status'] == 'void':
        raise ApiError('Invoice not found')
    c.con.execute('delete from allocations where invoice_id = ?', (iid,))
    c.con.execute("update invoices set status = 'void', void_note = ? where id = ?", (str(c.body.get('note', ''))[:200], iid))
    apply_credit(c.con, r['student_id'])


def check_account(con, v):
    a = con.execute('select id from accounts where id = ?', (ival(v),)).fetchone() if v not in (None, '') else None
    if not a:
        a = con.execute('select id from accounts order by id limit 1').fetchone()
    return a['id']


@route('POST', '/api/receipts', FIN)
def r_receipt_save(c):
    b = c.body
    kind = 'other' if b.get('kind') == 'other' else 'fee'
    amount, rdate = amt(b.get('amount')), dstr(b.get('rdate'))
    method = str(b.get('method', 'CASH')).upper()
    method = method if method in METHODS else 'CASH'
    acc = check_account(c.con, b.get('account_id'))
    sid, payer, category = None, '', ''
    if kind == 'fee':
        st = need_student(c.con, ival(b.get('student_id')))
        sid, payer = st['id'], st['name']
    else:
        payer = str(b.get('payer', '')).strip().upper()
        category = str(b.get('category', '')).strip().upper()
        if not category:
            raise ApiError('Enter the income category, for example UNIFORM SALES')
    no = next_no(c.con, 'RCT', rdate)
    rid = c.con.execute('insert into receipts(no, kind, student_id, payer, category, amount, method, account_id, ref, rdate, note, created_by) '
                        'values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (no, kind, sid, payer, category, amount, method, acc, str(b.get('ref', ''))[:60], rdate,
                         str(b.get('note', ''))[:300], c.user['name'])).lastrowid
    if kind == 'fee':
        if b.get('invoice_id'):
            inv = c.con.execute(INV_SQL + "where i.id = ? and i.student_id = ? and i.status = 'open'", (ival(b['invoice_id']), sid)).fetchone()
            if inv:
                x = min(amount, round(inv['total'] - inv['paid'], 2))
                if x > 0:
                    c.con.execute('insert into allocations(receipt_id, invoice_id, amount) values(?, ?, ?)', (rid, inv['id'], x))
        apply_credit(c.con, sid)
    return {'id': rid, 'no': no}


@route('GET', '/api/receipt', FIN)
def r_receipt(c):
    r = c.con.execute('select r.*, u.name as sname, u.username as reg, c.name as cname, a.name as aname from receipts r '
                      'left join users u on u.id = r.student_id left join classes c on c.id = u.class_id '
                      'left join accounts a on a.id = r.account_id where r.id = ?', (ival(c.q.get('id')),)).fetchone()
    if not r:
        raise ApiError('Receipt not found')
    d = {k: r[k] for k in ('id', 'no', 'kind', 'student_id', 'payer', 'category', 'amount', 'method', 'ref', 'rdate',
                           'note', 'status', 'created_by', 'sname', 'reg', 'cname', 'aname')}
    d['school'] = school_info(c.con)
    d['allocs'] = [{'no': x['no'], 'session': x['session'], 'term': x['term'], 'amount': x['amount'],
                    'balance': round(x['total'] - x['paid'], 2)} for x in c.con.execute(
        "select a.amount, i.no, i.session, i.term, i.total, (select coalesce(sum(amount), 0) from allocations where invoice_id = i.id) as paid "
        "from allocations a join invoices i on i.id = a.invoice_id where a.receipt_id = ? order by i.idate, i.id", (d['id'],))]
    d['fin'] = student_fin(c.con, r['student_id']) if r['student_id'] else None
    return d


@route('GET', '/api/receipts', FIN)
def r_receipts(c):
    w, p = ['1 = 1'], []
    if c.q.get('from'):
        w.append('r.rdate >= ?'); p.append(c.q['from'])
    if c.q.get('to'):
        w.append('r.rdate <= ?'); p.append(c.q['to'])
    if c.q.get('kind') in ('fee', 'other'):
        w.append('r.kind = ?'); p.append(c.q['kind'])
    if c.q.get('q'):
        w.append('(u.name like ? or r.payer like ? or r.no like ? or r.category like ?)'); p += ['%' + c.q['q'] + '%'] * 4
    rows = [dict(x) for x in c.con.execute(
        'select r.id, r.no, r.kind, r.rdate, r.amount, r.method, r.status, r.category, r.payer, u.name as sname, c.name as cname, a.name as aname '
        'from receipts r left join users u on u.id = r.student_id left join classes c on c.id = u.class_id '
        'left join accounts a on a.id = r.account_id where ' + ' and '.join(w) + ' order by r.rdate desc, r.id desc limit 1000', p)]
    return {'rows': rows, 'total': round(sum(r['amount'] for r in rows if r['status'] == 'ok'), 2)}


@route('POST', '/api/receipts/void', FIN)
def r_receipt_void(c):
    rid = ival(c.body.get('id'))
    r = c.con.execute('select * from receipts where id = ?', (rid,)).fetchone()
    if not r or r['status'] == 'void':
        raise ApiError('Receipt not found')
    c.con.execute('delete from allocations where receipt_id = ?', (rid,))
    c.con.execute("update receipts set status = 'void', void_note = ? where id = ?", (str(c.body.get('note', ''))[:200], rid))
    if r['student_id']:
        apply_credit(c.con, r['student_id'])


@route('POST', '/api/expenses', FIN)
def r_expense_save(c):
    b = c.body
    amount, edate = amt(b.get('amount')), dstr(b.get('edate'))
    category = str(b.get('category', '')).strip().upper()
    if not category:
        raise ApiError('Enter the expense category, for example SALARIES')
    method = str(b.get('method', 'CASH')).upper()
    method = method if method in METHODS else 'CASH'
    no = next_no(c.con, 'PV', edate)
    eid = c.con.execute('insert into expenses(no, edate, category, payee, description, amount, method, account_id, ref, created_by) '
                        'values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (no, edate, category, str(b.get('payee', '')).strip().upper(), str(b.get('description', ''))[:300], amount,
                         method, check_account(c.con, b.get('account_id')), str(b.get('ref', ''))[:60], c.user['name'])).lastrowid
    return {'id': eid, 'no': no}


@route('GET', '/api/expenses', FIN)
def r_expenses(c):
    w, p = ['1 = 1'], []
    if c.q.get('from'):
        w.append('e.edate >= ?'); p.append(c.q['from'])
    if c.q.get('to'):
        w.append('e.edate <= ?'); p.append(c.q['to'])
    if c.q.get('category'):
        w.append('e.category = ?'); p.append(c.q['category'].upper())
    rows = [dict(x) for x in c.con.execute('select e.*, a.name as aname from expenses e left join accounts a on a.id = e.account_id '
                                           'where ' + ' and '.join(w) + ' order by e.edate desc, e.id desc limit 1000', p)]
    cats = [r[0] for r in c.con.execute('select distinct category from expenses order by category')]
    return {'rows': rows, 'total': round(sum(r['amount'] for r in rows if r['status'] == 'ok'), 2), 'categories': cats}


@route('POST', '/api/expenses/void', FIN)
def r_expense_void(c):
    c.con.execute("update expenses set status = 'void', void_note = ? where id = ?",
                  (str(c.body.get('note', ''))[:200], ival(c.body.get('id'))))


@route('GET', '/api/income/categories', FIN)
def r_income_cats(c):
    return [r[0] for r in c.con.execute("select distinct category from receipts where kind = 'other' order by category")]


def account_balances(con):
    out = []
    for a in con.execute('select * from accounts order by id'):
        rin = con.execute("select coalesce(sum(amount), 0) from receipts where account_id = ? and status = 'ok'", (a['id'],)).fetchone()[0]
        rout = con.execute("select coalesce(sum(amount), 0) from expenses where account_id = ? and status = 'ok'", (a['id'],)).fetchone()[0]
        out.append({'id': a['id'], 'name': a['name'], 'kind': a['kind'], 'opening': a['opening'], 'in': round(rin, 2),
                    'out': round(rout, 2), 'balance': round(a['opening'] + rin - rout, 2)})
    return out


@route('GET', '/api/accounts', FIN)
def r_accounts(c):
    return account_balances(c.con)


@route('POST', '/api/accounts', ('admin',))
def r_account_save(c):
    b = c.body
    name = str(b.get('name', '')).strip().upper()
    if not name:
        raise ApiError('Enter an account name')
    kind = 'bank' if b.get('kind') == 'bank' else 'cash'
    opening = round(num(b.get('opening')), 2)
    if b.get('id'):
        c.con.execute('update accounts set name = ?, kind = ?, opening = ? where id = ?', (name, kind, opening, ival(b['id'])))
    else:
        c.con.execute('insert into accounts(name, kind, opening) values(?, ?, ?)', (name, kind, opening))


@route('POST', '/api/accounts/delete', ('admin',))
def r_account_delete(c):
    aid = ival(c.body.get('id'))
    if c.con.execute('select count(*) from accounts').fetchone()[0] < 2:
        raise ApiError('Keep at least one account')
    if c.con.execute('select 1 from receipts where account_id = ? union all select 1 from expenses where account_id = ?', (aid, aid)).fetchone():
        raise ApiError('This account has transactions and cannot be deleted')
    c.con.execute('delete from accounts where id = ?', (aid,))


@route('GET', '/api/fin/summary', FIN)
def r_fin_summary(c):
    ss = current_session(c)
    w, p = "where i.status = 'open' and i.session = ?", [ss]
    if c.q.get('term') in ('1', '2', '3'):
        w += ' and i.term = ?'
        p.append(int(c.q['term']))
    rows = c.con.execute(INV_SQL + w, p).fetchall()
    billed = round(sum(r['total'] for r in rows), 2)
    paid = round(sum(r['paid'] for r in rows), 2)
    month = date.today().isoformat()[:7] + '%'
    m_in = c.con.execute("select coalesce(sum(amount), 0) from receipts where status = 'ok' and rdate like ?", (month,)).fetchone()[0]
    m_out = c.con.execute("select coalesce(sum(amount), 0) from expenses where status = 'ok' and edate like ?", (month,)).fetchone()[0]
    recent = [dict(x) for x in c.con.execute(
        "select r.id, r.no, r.rdate, r.amount, r.kind, r.category, r.payer, u.name as sname from receipts r left join users u on u.id = r.student_id "
        "where r.status = 'ok' order by r.rdate desc, r.id desc limit 6")]
    return {'billed': billed, 'paid': paid, 'balance': round(billed - paid, 2), 'invoices': len(rows),
            'accounts': account_balances(c.con), 'month_in': round(m_in, 2), 'month_out': round(m_out, 2), 'recent': recent}


@route('GET', '/api/debtors', FIN)
def r_debtors(c):
    w, p = ["i.status = 'open'"], []
    if c.q.get('session'):
        w.append('i.session = ?'); p.append(c.q['session'])
    if c.q.get('term') in ('0', '1', '2', '3'):
        w.append('i.term = ?'); p.append(int(c.q['term']))
    if c.q.get('class'):
        w.append('u.class_id = ?'); p.append(ival(c.q['class']))
    agg = {}
    for r in c.con.execute(INV_SQL + 'where ' + ' and '.join(w), p):
        a = agg.setdefault(r['student_id'], {'id': r['student_id'], 'name': r['sname'], 'reg': r['reg'], 'phone': r['phone'],
                                             'cname': r['cname'] or '', 'billed': 0.0, 'paid': 0.0})
        a['billed'] += r['total']
        a['paid'] += r['paid']
    rows = []
    for a in agg.values():
        a['billed'], a['paid'] = round(a['billed'], 2), round(a['paid'], 2)
        a['balance'] = round(a['billed'] - a['paid'], 2)
        if a['balance'] > 0.004:
            rows.append(a)
    rows.sort(key=lambda a: -a['balance'])
    return {'rows': rows, 'total': round(sum(a['balance'] for a in rows), 2), 'school': school_info(c.con)}


@route('GET', '/api/statement', FIN)
def r_statement(c):
    st = need_student(c.con, ival(c.q.get('student')))
    cl = c.con.execute('select name from classes where id = ?', (st['class_id'],)).fetchone()
    invs = [inv_dict(r) for r in c.con.execute(INV_SQL + "where i.student_id = ? and i.status = 'open' order by i.idate, i.id", (st['id'],))]
    recs = [dict(r) for r in c.con.execute("select id, no, rdate, amount, method from receipts where student_id = ? and kind = 'fee' "
                                           "and status = 'ok' order by rdate, id", (st['id'],))]
    ledger = [{'date': i['idate'], 'k': 0, 'id': i['id'], 'type': 'INVOICE', 'no': i['no'],
               'text': ' / '.join(x['l'] for x in i['items']), 'dr': i['total'], 'cr': 0} for i in invs]
    ledger += [{'date': r['rdate'], 'k': 1, 'id': r['id'], 'type': 'RECEIPT', 'no': r['no'],
                'text': 'PAYMENT BY ' + r['method'], 'dr': 0, 'cr': r['amount']} for r in recs]
    ledger.sort(key=lambda e: (e['date'], e['k'], e['id']))
    run = 0.0
    for e in ledger:
        run = round(run + e['dr'] - e['cr'], 2)
        e['bal'] = run
    return {'student': {'id': st['id'], 'name': st['name'], 'reg': st['username'], 'phone': st['phone'],
                        'class_id': st['class_id'], 'cname': cl['name'] if cl else ''},
            'invoices': invs, 'ledger': ledger, 'fin': student_fin(c.con, st['id']), 'school': school_info(c.con)}


@route('GET', '/api/cashbook', FIN)
def r_cashbook(c):
    aid = check_account(c.con, c.q.get('account'))
    acc = c.con.execute('select * from accounts where id = ?', (aid,)).fetchone()
    ents = []
    for r in c.con.execute("select r.id, r.no, r.rdate, r.amount, r.kind, r.category, r.payer, u.name as sname from receipts r "
                           "left join users u on u.id = r.student_id where r.account_id = ? and r.status = 'ok'", (aid,)):
        who = r['sname'] or r['payer'] or ''
        ents.append({'date': r['rdate'], 'k': 0, 'id': r['id'], 'no': r['no'],
                     'text': (who + ' - school fees') if r['kind'] == 'fee' else ((who + ' - ' if who else '') + r['category']),
                     'in': r['amount'], 'out': 0})
    for e in c.con.execute("select id, no, edate, category, payee, description, amount from expenses where account_id = ? and status = 'ok'", (aid,)):
        ents.append({'date': e['edate'], 'k': 1, 'id': e['id'], 'no': e['no'],
                     'text': e['category'] + (' - ' + e['payee'] if e['payee'] else '') + (' (' + e['description'] + ')' if e['description'] else ''),
                     'in': 0, 'out': e['amount']})
    ents.sort(key=lambda e: (e['date'], e['k'], e['id']))
    run, rows, frm, to = acc['opening'], [], c.q.get('from') or '', c.q.get('to') or '9999-12-31'
    opening = None
    for e in ents:
        if e['date'] < frm:
            run = round(run + e['in'] - e['out'], 2)
            continue
        if opening is None:
            opening = run
        if e['date'] > to:
            break
        run = round(run + e['in'] - e['out'], 2)
        e['bal'] = run
        rows.append(e)
    if opening is None:
        opening = run
    return {'account': {'id': aid, 'name': acc['name']}, 'opening': round(opening, 2), 'rows': rows,
            'in': round(sum(e['in'] for e in rows), 2), 'out': round(sum(e['out'] for e in rows), 2),
            'closing': rows[-1]['bal'] if rows else round(opening, 2), 'school': school_info(c.con)}


@route('GET', '/api/fin/ie', FIN)
def r_fin_ie(c):
    frm, to = c.q.get('from') or '0000-01-01', c.q.get('to') or '9999-12-31'
    fees = c.con.execute("select coalesce(sum(amount), 0) from receipts where kind = 'fee' and status = 'ok' and rdate between ? and ?", (frm, to)).fetchone()[0]
    other = [dict(r) for r in c.con.execute("select category, sum(amount) as total from receipts where kind = 'other' and status = 'ok' "
                                            "and rdate between ? and ? group by category order by category", (frm, to))]
    exp = [dict(r) for r in c.con.execute("select category, sum(amount) as total from expenses where status = 'ok' "
                                          "and edate between ? and ? group by category order by category", (frm, to))]
    income = round(fees + sum(o['total'] for o in other), 2)
    spent = round(sum(e['total'] for e in exp), 2)
    return {'fees': round(fees, 2), 'other': other, 'expenses': exp, 'income': income, 'spent': spent,
            'net': round(income - spent, 2), 'school': school_info(c.con)}


@route('GET', '/api/fin/collection', FIN)
def r_fin_collection(c):
    w, p = ["i.status = 'open'", 'i.session = ?'], [current_session(c)]
    if c.q.get('term') in ('0', '1', '2', '3'):
        w.append('i.term = ?'); p.append(int(c.q['term']))
    agg = {}
    for r in c.con.execute(INV_SQL + 'where ' + ' and '.join(w), p):
        a = agg.setdefault(r['cname'] or '-', {'cname': r['cname'] or '-', 'cid': r['cid'], 'pupils': set(), 'billed': 0.0, 'paid': 0.0})
        a['pupils'].add(r['student_id'])
        a['billed'] += r['total']
        a['paid'] += r['paid']
    rows = []
    for a in agg.values():
        rows.append({'cname': a['cname'], 'pupils': len(a['pupils']), 'billed': round(a['billed'], 2), 'paid': round(a['paid'], 2),
                     'balance': round(a['billed'] - a['paid'], 2)})
    rows.sort(key=lambda r: r['cname'])
    return {'rows': rows, 'school': school_info(c.con)}



# ----------------------------------------------------------------------------- licence: 12-day trial, then activation code
LIC_N = int('A2E105C8FC97426B544F695CC62CBA72EACE80573F9921BC0FDF976F171925B333B539E75FA58C5DB2B1106B7DEE6E7428E873AA670EEB8BAA9F4ED5A27E68CB89CE8AB7D7FCBD318E693724FCB6A398EB38FDFB81C9CD81226826CBD804B460DEBA1AC6B67772C29B8D9F261207612B0A81F30282AAEAB9CFA81DBC599E3AC5403725DDE111C2EC29573865238D96CE6B877C76FD56126548483FC65D3D22F8D8D0721E87759319E5B0725144326747D0F9B8BE090433A96AF33EF881888A66614C13FD3387FE99C20C164D189BD38DB67E444E0F7B88843626F109EA148EAE326FDD391F73224F193ECA7A45B77033593AD99E51835E58B23CB1B132C9C6C1', 16)
LIC_E = 65537
TRIAL_DAYS = 12
_SHA256_PREFIX = bytes.fromhex('3031300d060960864801650304020105000420')


def load_config():
    cfg = {'endpoint': '', 'price': 120000, 'support_email': 'technologyokv@gmail.com', 'whatsapp': '+2348104141138',
           'website': 'www.okvtechnology.com', 'payment': 'Ask OKV Technology Consults for the payment account details.'}
    for folder in (RES_DIR, BASE, DATA_DIR):          # later files override earlier ones
        try:
            with open(os.path.join(folder, 'config.json'), encoding='utf-8') as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
    if os.environ.get('OKV_ENDPOINT'):
        cfg['endpoint'] = os.environ['OKV_ENDPOINT']
    return cfg


CFG = load_config()


def rsa_verify(msg, sig_b64):
    try:
        k = (LIC_N.bit_length() + 7) // 8
        sig = int.from_bytes(base64.b64decode(sig_b64), 'big')
        if sig >= LIC_N:
            return False
        em = pow(sig, LIC_E, LIC_N).to_bytes(k, 'big')
    except Exception:
        return False
    t = _SHA256_PREFIX + hashlib.sha256(msg).digest()
    return hmac.compare_digest(em, b'\x00\x01' + b'\xff' * (k - len(t) - 3) + b'\x00' + t)


def lic_status(con):
    s = settings(con)
    today = date.today()
    iid = s.get('installation_id', '')
    out = {'installation_id': iid, 'state': 'trial', 'days_left': 0, 'reason': ''}
    tok = s.get('license_token', '')
    if tok:
        try:
            t = json.loads(tok)
            parts = t['p'].split('|')
            if parts[0] == 'OKV1' and parts[1] == iid and rsa_verify(t['p'].encode(), t['s']):
                out.update(state='licensed', code=parts[2], issued=parts[3], licensee=parts[4] if len(parts) > 4 else '')
                return out
        except Exception:
            pass
    try:
        start = date.fromisoformat(s.get('trial_start', ''))
    except ValueError:
        start = today
    try:
        seen = date.fromisoformat(s.get('last_seen', ''))
    except ValueError:
        seen = today
    if (seen - today).days > 2:
        out.update(state='expired', reason='clock')
        return out
    if today > seen:
        setv(con, 'last_seen', today.isoformat())
    left = TRIAL_DAYS - (today - start).days
    out.update(days_left=max(0, left), expires=(start + timedelta(days=TRIAL_DAYS)).isoformat(),
               state='trial' if left > 0 else 'expired')
    return out


def endpoint_ready():
    ep = str(CFG.get('endpoint', ''))
    return (ep.startswith('https://') or ep.startswith('http://127.0.0.1')) and 'YOUR_' not in ep


def okv_call(payload, method='POST', timeout=30):
    """Talk to the OKV Technology Google Apps Script web app."""
    if not endpoint_ready():
        raise ApiError('The OKV activation server address is not set in config.json yet. Contact OKV Technology Consults.')
    try:
        if method == 'GET':
            sep = '&' if '?' in CFG['endpoint'] else '?'
            req = urllib.request.Request(CFG['endpoint'] + sep + urlencode(payload))
        else:
            req = urllib.request.Request(CFG['endpoint'], data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'text/plain;charset=utf-8'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except (urllib.error.URLError, OSError):
        raise ApiError('Could not reach the OKV server. Check that this computer is online and try again.')
    try:
        out = json.loads(data)
    except ValueError:
        raise ApiError('Unexpected reply from the OKV server. Try again in a moment.')
    if not out.get('ok'):
        raise ApiError(out.get('error') or 'The OKV server could not complete the request')
    return out


EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@route('GET', '/api/license', ANY)
def r_license(c):
    st = lic_status(c.con)
    out = {k: st.get(k) for k in ('state', 'days_left', 'expires', 'licensee', 'issued', 'reason')}
    out.update(price=CFG.get('price'), support_email=CFG.get('support_email'), whatsapp=CFG.get('whatsapp'),
               website=CFG.get('website'), payment=CFG.get('payment'), online=endpoint_ready())
    out['pricing_url'] = pricing_url(st['installation_id'] if c.user['role'] == 'admin' else '')
    if c.user['role'] == 'admin':
        out['installation_id'] = st['installation_id']
        out['log'] = [dict(r) for r in c.con.execute('select kind, ref, summary, created from lic_log order by id desc limit 10')]
    return out


@route('GET', '/api/license/info', ('admin',))
def r_license_info(c):
    try:
        r = okv_call({'action': 'info'}, 'GET', 8)
        return {'price': r.get('price'), 'payment': r.get('payment')}
    except ApiError:
        return {}


@route('POST', '/api/license/activate', ('admin',))
def r_license_activate(c):
    code = re.sub(r'\s+', '', str(c.body.get('code', ''))).upper()
    if len(code) < 8:
        raise ApiError('Enter the activation code from your email')
    iid = lic_status(c.con)['installation_id']
    tok = okv_call({'action': 'redeem', 'code': code, 'iid': iid}, 'GET').get('token') or {}
    try:
        ok = tok['p'].split('|')[1] == iid and rsa_verify(tok['p'].encode(), tok['s'])
    except Exception:
        ok = False
    if not ok:
        raise ApiError('The reply could not be verified. Contact OKV Technology Consults.')
    setv(c.con, 'license_token', json.dumps({'p': tok['p'], 's': tok['s']}))
    return {'ok': 1}


def lic_log(con, kind, ref, summary):
    con.execute('insert into lic_log(kind, ref, summary) values(?, ?, ?)', (kind, ref or '', summary))


@route('POST', '/api/license/request', ('admin',))
def r_license_request(c):
    b = c.body
    need = {'school': 'school name', 'name': 'your name', 'email': 'email address', 'phone': 'phone number',
            'amount': 'amount paid', 'paid_on': 'payment date', 'receipt_data': 'payment receipt'}
    for k, label in need.items():
        if not str(b.get(k, '')).strip():
            raise ApiError('Please enter the %s' % label)
    if not EMAIL_RE.match(str(b['email']).strip()):
        raise ApiError('Enter a valid email address')
    rd = str(b['receipt_data'])
    if not rd.startswith('data:') or len(rd) > 6 * 1024 * 1024:
        raise ApiError('The receipt file must be a picture or PDF smaller than 4 MB')
    payload = {k: str(b.get(k, ''))[:300] for k in ('school', 'name', 'email', 'phone', 'amount', 'paid_on', 'bank', 'reference', 'notes', 'receipt_name', 'address')}
    payload.update(action='activation_request', iid=lic_status(c.con)['installation_id'], receipt_data=rd)
    r = okv_call(payload, 'POST', 90)
    lic_log(c.con, 'activation request', r.get('ref'), 'Receipt submitted by %s' % payload['email'])
    return {'ref': r.get('ref', '')}


@route('POST', '/api/license/contact', ('admin',))
def r_license_contact(c):
    b = c.body
    kind = 'register' if b.get('kind') == 'register' else 'message'
    for k, label in {'name': 'your name', 'email': 'email address', 'school': 'school name'}.items():
        if not str(b.get(k, '')).strip():
            raise ApiError('Please enter the %s' % label)
    if not EMAIL_RE.match(str(b['email']).strip()):
        raise ApiError('Enter a valid email address')
    payload = {k: str(b.get(k, ''))[:1000] for k in ('name', 'email', 'phone', 'school', 'message', 'address')}
    payload.update(action='register_install' if kind == 'register' else 'contact', iid=lic_status(c.con)['installation_id'])
    r = okv_call(payload, 'POST', 40)
    lic_log(c.con, 'registration' if kind == 'register' else 'message', r.get('ref'), 'Sent to OKV Technology Consults')
    return {'ref': r.get('ref', '')}


MANUALS = {'admin': 'manual_admin.pdf', 'accountant': 'manual_accountant.pdf', 'staff': 'manual_teacher.pdf', 'student': 'manual_pupil.pdf'}


@route('GET', '/api/manual', ANY)
def r_manual(c):
    role = c.q.get('role') if (c.user['role'] == 'admin' and c.q.get('role') in MANUALS) else c.user['role']
    path = os.path.join(RES_DIR, 'manuals', MANUALS[role])
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        raise ApiError('The manual file is missing from the manuals folder')
    return Raw(data, 'application/pdf', [('Content-Disposition', 'attachment; filename="%s"' % MANUALS[role])])


LIC_OPEN = {('POST', '/api/login'), ('POST', '/api/logout'), ('GET', '/api/me'), ('POST', '/api/password'),
            ('GET', '/api/public'), ('GET', '/api/license'), ('GET', '/api/license/info'), ('POST', '/api/license/activate'),
            ('POST', '/api/license/request'), ('POST', '/api/license/contact'), ('GET', '/api/backup'), ('GET', '/api/manual')}



# ----------------------------------------------------------------------------- users, recovery, messaging, statistics, legal
def active_admins(con):
    return con.execute("select count(*) from users where role = 'admin' and coalesce(status, 'active') = 'active'").fetchone()[0]


def temp_pw():
    return ''.join(secrets.choice('abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))


def user_row(r):
    return {'id': r['id'], 'username': r['username'], 'name': r['name'], 'role': r['role'], 'status': r['status'] or 'active',
            'class_id': r['class_id'], 'cname': r['cname'] or '', 'phone': r['phone'] or '', 'last_login': r['last_login'] or '',
            'created': r['created'] or ''}


@route('GET', '/api/users', ('admin',))
def r_users(c):
    w, p = ['1 = 1'], []
    if c.q.get('role') in ('admin', 'staff', 'accountant', 'student'):
        w.append('u.role = ?'); p.append(c.q['role'])
    if c.q.get('status') in ('active', 'suspended'):
        w.append("coalesce(u.status, 'active') = ?"); p.append(c.q['status'])
    if c.q.get('q'):
        w.append('(u.name like ? or u.username like ?)'); p += ['%' + c.q['q'] + '%'] * 2
    rows = c.con.execute('select u.*, c.name as cname from users u left join classes c on c.id = u.class_id where ' + ' and '.join(w) +
                         " order by case u.role when 'admin' then 0 when 'accountant' then 1 when 'staff' then 2 else 3 end, u.name limit 1500", p)
    counts = {r[0]: r[1] for r in c.con.execute('select role, count(*) from users group by role')}
    return {'rows': [user_row(r) for r in rows], 'counts': counts, 'me': c.user['id']}


@route('POST', '/api/users/status', ('admin',))
def r_user_status(c):
    uid, st = ival(c.body.get('id')), 'suspended' if c.body.get('status') == 'suspended' else 'active'
    u = c.con.execute('select * from users where id = ?', (uid,)).fetchone()
    if not u:
        raise ApiError('User not found')
    if st == 'suspended':
        if uid == c.user['id']:
            raise ApiError('You cannot suspend your own account')
        if u['role'] == 'admin' and active_admins(c.con) < 2:
            raise ApiError('At least one administrator must stay active')
    c.con.execute('update users set status = ? where id = ?', (st, uid))
    if st == 'suspended':
        c.con.execute('delete from sessions where user_id = ?', (uid,))


@route('POST', '/api/users/resetpw', ('admin',))
def r_user_resetpw(c):
    u = c.con.execute('select * from users where id = ?', (ival(c.body.get('id')),)).fetchone()
    if not u:
        raise ApiError('User not found')
    pw = str(c.body.get('password') or '')
    if not pw:
        pw = u['username'] if u['role'] == 'student' else temp_pw()
    if len(pw) < 4:
        raise ApiError('Use at least 4 characters for the password')
    salt, h = mkpw(pw)
    c.con.execute('update users set salt = ?, pw = ? where id = ?', (salt, h, u['id']))
    if u['id'] != c.user['id']:
        c.con.execute('delete from sessions where user_id = ?', (u['id'],))
    return {'password': pw, 'username': u['username'], 'name': u['name']}


@route('POST', '/api/users/delete', ('admin',))
def r_user_delete(c):
    uid = ival(c.body.get('id'))
    u = c.con.execute('select * from users where id = ?', (uid,)).fetchone()
    if not u:
        raise ApiError('User not found')
    if uid == c.user['id']:
        raise ApiError('You cannot delete your own account')
    if u['role'] == 'admin' and active_admins(c.con) < 2 and (u['status'] or 'active') == 'active':
        raise ApiError('At least one administrator must stay active')
    if u['role'] == 'student' and c.con.execute('select 1 from invoices where student_id = ? union all select 1 from receipts where student_id = ?', (uid, uid)).fetchone():
        raise ApiError('This pupil has invoices or receipts. Financial records are kept, so the pupil cannot be deleted. Suspend the account instead.')
    c.con.execute('delete from sessions where user_id = ?', (uid,))
    c.con.execute('delete from users where id = ?', (uid,))


# ---- password recovery
RK_ALPHA = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def new_recovery_key(con):
    key = 'RK-' + '-'.join(''.join(secrets.choice(RK_ALPHA) for _ in range(4)) for _ in range(4))
    salt = secrets.token_hex(16)
    setv(con, 'recovery_salt', salt)
    setv(con, 'recovery_hash', hpw(key, salt))
    setv(con, 'recovery_pending', key)
    return key


@route('GET', '/api/recovery/pending', ('admin',))
def r_recovery_pending(c):
    return {'key': settings(c.con).get('recovery_pending', '')}


@route('POST', '/api/recovery/ack', ('admin',))
def r_recovery_ack(c):
    setv(c.con, 'recovery_pending', '')


@route('POST', '/api/recovery/regenerate', ('admin',))
def r_recovery_regen(c):
    if not hmac.compare_digest(c.user['pw'], hpw(str(c.body.get('password', '')), c.user['salt'])):
        raise ApiError('Your password is not correct')
    return {'key': new_recovery_key(c.con)}


@route('GET', '/api/recover/info')
def r_recover_info(c):
    s = settings(c.con)
    return {'iid': s.get('installation_id', ''), 'email': CFG.get('support_email'), 'whatsapp': CFG.get('whatsapp')}


def parse_reset_code(code, iid, con):
    s = re.sub(r'\s+', '', code)
    if s.upper().startswith('OKVR-'):
        s = s[5:]
    try:
        t = json.loads(base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)))
        p = t['p']
        parts = p.split('|')
        ok = parts[0] == 'OKV1R' and parts[1] == iid and parts[2] >= date.today().isoformat() and rsa_verify(p.encode(), t['s'])
    except Exception:
        return None
    if not ok or con.execute('select 1 from recov_used where nonce = ?', (parts[3],)).fetchone():
        return None
    return parts[3]


@route('POST', '/api/recover')
def r_recover(c):
    now = time.time()
    key = 'rec_' + c.ip
    with FAILS_LOCK:
        recent = [t for t in FAILS.get(key, []) if now - t < 600]
        FAILS[key] = recent
        if len(recent) >= 6:
            raise ApiError('Too many attempts. Wait ten minutes and try again.', 429)
        FAILS[key].append(now)
    b = c.body
    u = c.con.execute("select * from users where username = ? and role = 'admin'", (str(b.get('username', '')).strip(),)).fetchone()
    newpw = str(b.get('password', ''))
    if len(newpw) < 6:
        raise ApiError('Choose a new password of at least 6 characters')
    s = settings(c.con)
    ok, nonce = False, None
    if u and b.get('method') == 'key':
        k = re.sub(r'\s+', '', str(b.get('secret', ''))).upper()
        ok = bool(s.get('recovery_hash')) and hmac.compare_digest(s['recovery_hash'], hpw(k, s.get('recovery_salt', '00')))
    elif u and b.get('method') == 'okv':
        nonce = parse_reset_code(str(b.get('secret', '')), s.get('installation_id', ''), c.con)
        ok = nonce is not None
    if not ok:
        raise ApiError('The username or the recovery key / reset code is not correct')
    salt, h = mkpw(newpw)
    c.con.execute("update users set salt = ?, pw = ?, status = 'active' where id = ?", (salt, h, u['id']))
    c.con.execute('delete from sessions where user_id = ?', (u['id'],))
    if nonce:
        c.con.execute('insert into recov_used(nonce) values(?)', (nonce,))
    else:
        new_recovery_key(c.con)
    with FAILS_LOCK:
        FAILS[key] = []
    return {'ok': 1}


# ---- messaging between users
ROLE_LABEL = {'staff': 'All teachers', 'admin': 'Administrators', 'accountant': 'Accountants', 'student': 'All pupils'}


def unread_count(con, u):
    return con.execute(
        "select count(*) from msgs m left join msg_state s on s.msg_id = m.id and s.user_id = ? where m.deleted = 0 and coalesce(s.hidden, 0) = 0 "
        "and coalesce(s.read, 0) = 0 and coalesce(m.sender_id, 0) != ? and (m.to_kind = 'all' or (m.to_kind = 'user' and m.to_user_id = ?) "
        "or (m.to_kind = 'role' and m.to_role = ?) or (m.to_kind = 'class' and m.to_class_id = ?))",
        (u['id'], u['id'], u['id'], u['role'], u['class_id'] or -1)).fetchone()[0]


def msg_target(con, m):
    k = m['to_kind']
    if k == 'all':
        return 'Everyone'
    if k == 'role':
        return ROLE_LABEL.get(m['to_role'], m['to_role'])
    if k == 'class':
        r = con.execute('select name from classes where id = ?', (m['to_class_id'],)).fetchone()
        return 'Class ' + (r['name'] if r else '')
    r = con.execute('select name from users where id = ?', (m['to_user_id'],)).fetchone()
    return r['name'] if r else '(removed user)'


@route('GET', '/api/messages/directory', ANY)
def r_msg_directory(c):
    me = c.user
    if me['role'] == 'student':
        rows = c.con.execute("select u.id, u.name, u.role, c.name as cname from users u left join classes c on c.id = u.class_id "
                             "where coalesce(u.status, 'active') = 'active' and u.id != ? and (u.role != 'student' or u.class_id = ?) order by u.role, u.name",
                             (me['id'], me['class_id'] or -1))
        classes = []
    else:
        rows = c.con.execute("select u.id, u.name, u.role, c.name as cname from users u left join classes c on c.id = u.class_id "
                             "where coalesce(u.status, 'active') = 'active' and u.id != ? order by u.role, u.name limit 2500", (me['id'],))
        classes = sorted([{'id': r['id'], 'name': r['name'], 'category': r['category']} for r in c.con.execute('select * from classes')], key=class_key)
    return {'users': [{'id': r['id'], 'name': r['name'], 'role': r['role'], 'cname': r['cname'] or ''} for r in rows], 'classes': classes}


@route('POST', '/api/messages', ANY)
def r_msg_send(c):
    me, b = c.user, c.body
    subject, body = str(b.get('subject', '')).strip()[:150], str(b.get('body', '')).strip()[:4000]
    if not body:
        raise ApiError('Write a message first')
    to = str(b.get('to', ''))
    kind, uid, role, cid = None, None, None, None
    if to == 'all':
        kind = 'all'
    elif to.startswith('user:'):
        kind, uid = 'user', ival(to[5:])
        t = c.con.execute("select 1 from users where id = ? and coalesce(status, 'active') = 'active'", (uid,)).fetchone()
        if not t or uid == me['id']:
            raise ApiError('Choose someone else to send the message to')
    elif to.startswith('role:') and me['role'] != 'student' and to[5:] in ROLE_LABEL:
        kind, role = 'role', to[5:]
    elif to.startswith('class:') and me['role'] != 'student':
        kind, cid = 'class', ival(to[6:])
        if not c.con.execute('select 1 from classes where id = ?', (cid,)).fetchone():
            raise ApiError('Class not found')
    else:
        raise ApiError('Choose who the message is for')
    n = c.con.execute("select count(*) from msgs where sender_id = ? and created > datetime('now', '-1 hour')", (me['id'],)).fetchone()[0]
    nb = c.con.execute("select count(*) from msgs where sender_id = ? and to_kind != 'user' and created > datetime('now', '-1 hour')", (me['id'],)).fetchone()[0]
    if n >= 60 or (kind != 'user' and nb >= 10):
        raise ApiError('You are sending messages too quickly. Please wait a little and try again.', 429)
    mid = c.con.execute('insert into msgs(sender_id, sender_name, sender_role, to_kind, to_user_id, to_role, to_class_id, subject, body) '
                        'values(?, ?, ?, ?, ?, ?, ?, ?, ?)', (me['id'], me['name'], me['role'], kind, uid, role, cid, subject, body)).lastrowid
    return {'id': mid}


@route('GET', '/api/messages', ANY)
def r_msg_list(c):
    me, box = c.user, c.q.get('box', 'inbox')
    q = '%' + c.q.get('q', '') + '%'
    page = max(1, ival(c.q.get('page') or 1))
    if box == 'sent':
        rows = c.con.execute("select m.*, 1 as isread from msgs m left join msg_state s on s.msg_id = m.id and s.user_id = ? where m.sender_id = ? and m.deleted = 0 "
                             "and coalesce(s.hidden, 0) = 0 and (m.subject like ? or m.body like ?) order by m.id desc limit 30 offset ?",
                             (me['id'], me['id'], q, q, (page - 1) * 30)).fetchall()
    else:
        rows = c.con.execute("select m.*, coalesce(s.read, 0) as isread from msgs m left join msg_state s on s.msg_id = m.id and s.user_id = ? where m.deleted = 0 "
                             "and coalesce(s.hidden, 0) = 0 and coalesce(m.sender_id, 0) != ? and (m.to_kind = 'all' or (m.to_kind = 'user' and m.to_user_id = ?) "
                             "or (m.to_kind = 'role' and m.to_role = ?) or (m.to_kind = 'class' and m.to_class_id = ?)) and (m.subject like ? or m.body like ?) "
                             "order by m.id desc limit 30 offset ?", (me['id'], me['id'], me['id'], me['role'], me['class_id'] or -1, q, q, (page - 1) * 30)).fetchall()
    return {'rows': [{'id': m['id'], 'from': m['sender_name'], 'role': m['sender_role'], 'to': msg_target(c.con, m), 'subject': m['subject'] or '(no subject)',
                      'preview': m['body'][:90], 'created': m['created'], 'read': bool(m['isread'])} for m in rows],
            'unread': unread_count(c.con, me), 'page': page}


@route('GET', '/api/messages/get', ANY)
def r_msg_get(c):
    me = c.user
    m = c.con.execute('select * from msgs where id = ? and deleted = 0', (ival(c.q.get('id')),)).fetchone()
    if not m:
        raise ApiError('Message not found')
    mine = m['sender_id'] == me['id']
    for_me = (m['to_kind'] == 'all' or (m['to_kind'] == 'user' and m['to_user_id'] == me['id']) or (m['to_kind'] == 'role' and m['to_role'] == me['role'])
              or (m['to_kind'] == 'class' and m['to_class_id'] == me['class_id']))
    if not (mine or for_me or me['role'] == 'admin'):
        raise ApiError('You are not allowed to open that message', 403)
    if for_me and not mine:
        c.con.execute('insert into msg_state(msg_id, user_id, read) values(?, ?, 1) on conflict(msg_id, user_id) do update set read = 1', (m['id'], me['id']))
    return {'id': m['id'], 'from': m['sender_name'], 'role': m['sender_role'], 'sender_id': m['sender_id'], 'to': msg_target(c.con, m), 'subject': m['subject'] or '(no subject)',
            'body': m['body'], 'created': m['created'], 'mine': mine}


@route('GET', '/api/messages/unread', ANY)
def r_msg_unread(c):
    return {'unread': unread_count(c.con, c.user)}


@route('POST', '/api/messages/delete', ANY)
def r_msg_delete(c):
    mid = ival(c.body.get('id'))
    if c.body.get('everyone') and c.user['role'] == 'admin':
        c.con.execute('update msgs set deleted = 1 where id = ?', (mid,))
    else:
        c.con.execute('insert into msg_state(msg_id, user_id, hidden) values(?, ?, 1) on conflict(msg_id, user_id) do update set hidden = 1', (mid, c.user['id']))


@route('POST', '/api/messages/readall', ANY)
def r_msg_readall(c):
    me = c.user
    ids = [r[0] for r in c.con.execute(
        "select m.id from msgs m where m.deleted = 0 and coalesce(m.sender_id, 0) != ? and (m.to_kind = 'all' or (m.to_kind = 'user' and m.to_user_id = ?) "
        "or (m.to_kind = 'role' and m.to_role = ?) or (m.to_kind = 'class' and m.to_class_id = ?))", (me['id'], me['id'], me['role'], me['class_id'] or -1))]
    for i in ids:
        c.con.execute('insert into msg_state(msg_id, user_id, read) values(?, ?, 1) on conflict(msg_id, user_id) do update set read = 1', (i, me['id']))


# ---- dashboard statistics
def pupil_avgs(con, ss, term):
    """{student_id: (name, class_id, total, average)} for one term."""
    nsub = {r['class_id']: r['n'] for r in con.execute('select class_id, count(*) as n from subjects group by class_id')}
    out = {}
    for r in con.execute("select s.student_id as sid, u.name as name, u.class_id as cid, sum(coalesce(s.ca1, 0) + coalesce(s.ca2, 0) + coalesce(s.ca3, 0) + coalesce(s.exam, 0)) as tot "
                         "from scores s join users u on u.id = s.student_id where s.session = ? and s.term = ? group by s.student_id", (ss, term)):
        out[r['sid']] = (r['name'], r['cid'], r['tot'], r['tot'] / (nsub.get(r['cid']) or 1))
    return out


@route('GET', '/api/stats/academic', ('admin', 'staff'))
def r_stats_academic(c):
    ss, con = current_session(c), c.con
    term = ival(c.q.get('term') or 1)
    term = term if term in (1, 2, 3) else 1
    classes = sorted(con.execute('select * from classes').fetchall(), key=class_key)
    cname = {x['id']: x['name'] for x in classes}
    counts = {r[0]: r[1] for r in con.execute("select class_id, count(*) from users where role = 'student' group by class_id")}
    per_class = [{'name': x['name'], 'pupils': counts.get(x['id'], 0)} for x in classes]
    gender = {(r[0] or 'NOT SET'): r[1] for r in con.execute("select gender, count(*) from users where role = 'student' group by gender")}
    roles = {r[0]: r[1] for r in con.execute('select role, count(*) from users group by role')}
    avgs = pupil_avgs(con, ss, term)
    pupils = roles.get('student', 0)
    by_class = {}
    for sid, (name, cid, tot, av) in avgs.items():
        by_class.setdefault(cid, []).append(av)
    class_avg = [{'name': cname[k], 'avg': round(sum(v) / len(v), 2)} for k, v in by_class.items() if k in cname]
    class_avg.sort(key=lambda x: x['name'])
    class_avg = [x for x in sorted(class_avg, key=lambda x: next((i for i, cl in enumerate(classes) if cl['name'] == x['name']), 99))]
    sch = scheme_of(settings(con))
    order = [b[1] for b in sch['bands']]
    dist = {g: 0 for g in order}
    for r in con.execute('select coalesce(ca1, 0) + coalesce(ca2, 0) + coalesce(ca3, 0) + coalesce(exam, 0) as t from scores where session = ? and term = ?', (ss, term)):
        dist[grade_in(sch['bands'], r['t'])[0]] += 1
    trend = []
    for t in (1, 2, 3):
        a = pupil_avgs(con, ss, t)
        trend.append({'term': t, 'avg': round(sum(v[3] for v in a.values()) / len(a), 2) if a else None, 'pupils': len(a)})
    cid = ival(c.q.get('class')) if c.q.get('class') else (next(iter(by_class)) if by_class else (classes[0]['id'] if classes else 0))
    subj = []
    for s in get_subjects(con, cid):
        r = con.execute('select avg(coalesce(ca1, 0) + coalesce(ca2, 0) + coalesce(ca3, 0) + coalesce(exam, 0)) from scores where session = ? and term = ? and subject_id = ?', (ss, term, s['id'])).fetchone()[0]
        subj.append({'name': s['name'], 'avg': round(r, 2) if r is not None else 0})
    top = sorted(avgs.values(), key=lambda v: -v[3])[:5]
    opened = con.execute('select opened from terms where session = ? and term = ?', (ss, term)).fetchone()
    pres = [r[0] for r in con.execute('select present from records where session = ? and term = ? and present is not null', (ss, term))]
    att = round(sum(pres) / (opened['opened'] * len(pres)) * 100, 1) if (opened and opened['opened'] and pres) else None
    return {'term': term, 'pupils': pupils, 'staff': roles.get('staff', 0) + roles.get('accountant', 0) + roles.get('admin', 0), 'classes': len(classes),
            'per_class': per_class, 'gender': gender, 'class_avg': class_avg, 'dist': dist, 'trend': trend, 'class_id': cid,
            'class_options': [{'id': x['id'], 'name': x['name']} for x in classes], 'dist_order': order, 'subjects': subj,
            'top': [{'name': v[0], 'class': cname.get(v[1], ''), 'avg': round(v[3], 2), 'total': v[2]} for v in top],
            'completion': round(len(avgs) / pupils * 100) if pupils else 0, 'scored': len(avgs), 'attendance': att,
            'overall_avg': round(sum(v[3] for v in avgs.values()) / len(avgs), 2) if avgs else None,
            'unread': unread_count(con, c.user)}


@route('GET', '/api/stats/finance', FIN)
def r_stats_finance(c):
    ss, con = current_session(c), c.con
    rows = [inv_dict(r) for r in con.execute(INV_SQL + "where i.status = 'open' and i.session = ?", (ss,))]
    billed, paid = sum(r['total'] for r in rows), sum(r['paid'] for r in rows)
    today = date.today().isoformat()
    overdue = sum(1 for r in rows if r['balance'] > 0.004 and r['due'] and r['due'] < today)
    per_term = []
    for t in (0, 1, 2, 3):
        sub = [r for r in rows if r['term'] == t]
        if sub:
            per_term.append({'name': 'No term' if t == 0 else TERM_NAMES[t], 'billed': round(sum(r['total'] for r in sub), 2), 'paid': round(sum(r['paid'] for r in sub), 2)})
    by_class, debtor = {}, {}
    for r in rows:
        if r['balance'] > 0.004:
            by_class[r['cname'] or '-'] = by_class.get(r['cname'] or '-', 0) + r['balance']
            d = debtor.setdefault(r['student_id'], {'name': r['sname'], 'cname': r['cname'], 'phone': r['phone'], 'balance': 0.0})
            d['balance'] += r['balance']
    months = []
    y, m = date.today().year, date.today().month
    for i in range(11, -1, -1):
        mm = m - i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        months.append('%04d-%02d' % (yy, mm))
    rin = {r[0]: r[1] for r in con.execute("select substr(rdate, 1, 7), sum(amount) from receipts where status = 'ok' group by 1")}
    rout = {r[0]: r[1] for r in con.execute("select substr(edate, 1, 7), sum(amount) from expenses where status = 'ok' group by 1")}
    methods = [{'name': r[0], 'total': round(r[1], 2)} for r in con.execute("select method, sum(amount) from receipts where status = 'ok' group by method order by 2 desc")]
    cats = [{'name': r[0], 'total': round(r[1], 2)} for r in con.execute("select category, sum(amount) from expenses where status = 'ok' group by category order by 2 desc limit 6")]
    tot_in = con.execute("select coalesce(sum(amount), 0) from receipts where status = 'ok'").fetchone()[0]
    tot_out = con.execute("select coalesce(sum(amount), 0) from expenses where status = 'ok'").fetchone()[0]
    return {'billed': round(billed, 2), 'paid': round(paid, 2), 'balance': round(billed - paid, 2), 'rate': round(paid / billed * 100) if billed else 0,
            'invoices': len(rows), 'overdue': overdue, 'debtors': len(debtor), 'avg_invoice': round(billed / len(rows), 2) if rows else 0,
            'per_term': per_term, 'debtors_by_class': [{'name': k, 'total': round(v, 2)} for k, v in sorted(by_class.items())],
            'top_debtors': sorted(({'name': d['name'], 'cname': d['cname'], 'phone': d['phone'], 'balance': round(d['balance'], 2)} for d in debtor.values()), key=lambda d: -d['balance'])[:5],
            'months': [{'m': k, 'in': round(rin.get(k, 0), 2), 'out': round(rout.get(k, 0), 2)} for k in months], 'methods': methods, 'expense_cats': cats,
            'income_total': round(tot_in, 2), 'expense_total': round(tot_out, 2), 'net': round(tot_in - tot_out, 2),
            'accounts': account_balances(con), 'unread': unread_count(con, c.user)}


TERM_NAMES = {1: 'First term', 2: 'Second term', 3: 'Third term'}


@route('GET', '/api/stats/pupil', ('student',))
def r_stats_pupil(c):
    st, ss = c.user, current_session(c)
    out = {'released': settings(c.con)['students_view'] == '1', 'fin': student_fin(c.con, st['id']), 'unread': unread_count(c.con, st)}
    if not out['released'] or not st['class_id']:
        return out
    sh = Sheeter(c.con, st['class_id'], ss)
    terms, latest = [], None
    for t in (1, 2, 3):
        d = sh.sheet(st, t)
        has = sh.has_scores(st['id'], t)
        terms.append({'term': t, 'has': has, 'total': d['total'], 'avg': d['avg'], 'position': d['position'], 'present': d['present'], 'opened': d['opened']})
        if has:
            latest = (t, d)
    out.update(terms=terms, n_in_class=len(sh.students), session=ss, cname=sh.cl['name'])
    if latest:
        out['latest'] = {'term': latest[0], 'subjects': [{'name': r['s'], 'total': r['tot'], 'grade': r['g']} for r in latest[1]['rows']],
                         'avg': latest[1]['avg'], 'position': latest[1]['position'], 'total': latest[1]['total']}
    return out


# ----------------------------------------------------------------------------- legal pages (served at /legal/<name>)
LEGAL_CSS = ("body{font:15px/1.65 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#1d2433;background:#f5f6fa;margin:0}"
             "main{max-width:820px;margin:0 auto;padding:28px 18px 60px}article{background:#fff;border:1px solid #e1e5ee;border-radius:12px;padding:26px 30px}"
             "h1{font:700 28px Georgia,serif;color:#16213e;margin:0 0 4px}h2{font:700 18px Georgia,serif;color:#16213e;margin:24px 0 6px}a{color:#8b6a1b}"
             ".t{color:#667085;font-size:13px;margin-bottom:12px}nav{max-width:820px;margin:0 auto;padding:16px 18px 0;font-size:14px}nav a{margin-right:14px}")
LEGAL = {
    'privacy': ('Privacy Policy', [
        ('Who we are', 'This system is provided by OKV Technology Consults ("OKV", "we"). It runs on a computer owned by your school. <b>Your school is the controller of the pupil, parent, staff and accounting data you enter</b>. OKV does not host that data and cannot see it.'),
        ('What is stored on the school computer', 'Names, class, gender, date of birth, passport photos, parent phone numbers, scores, attendance, remarks, fee invoices, receipts, expenses, user accounts (passwords are stored only as salted hashes), and messages sent between users. All of it stays in the database file on the school computer or in backups the administrator downloads.'),
        ('What is sent to OKV', 'Nothing is sent automatically. Data reaches OKV only when your administrator chooses to submit a form from the License page: registration, a message, or an activation request (school name, contact details, installation ID, payment details and the receipt image). During activation the installation ID and activation code are checked against our licence server.'),
        ('Cookies', 'The system uses one strictly necessary session cookie to keep you signed in. See the Cookie Policy.'),
        ('How we use information you send us', 'To answer your message, confirm payment, issue your activation code, send support and product updates you asked for, and keep business records. We use Google Workspace services (Google Sheets, Gmail, Drive) to handle these submissions.'),
        ('Children\'s data', 'The system holds information about children. Schools should enter only what they need, restrict administrator and teacher accounts to trusted staff, and follow the Nigeria Data Protection Act 2023 and any guidance from the Nigeria Data Protection Commission.'),
        ('Security', 'Use strong passwords, keep the recovery key safe, download backups regularly and store them securely, and keep Windows updated. Anyone on your school network can reach the sign-in page, so do not expose the system to the internet without extra protection.'),
        ('Retention and deletion', 'Data stays on your computer until you delete it. Deleting a pupil removes their results; records with financial entries are kept for accounting integrity. Submissions to OKV are kept for as long as needed for support and legal records.'),
        ('Your rights', 'Under the Nigeria Data Protection Act you may ask for access, correction or deletion of your personal data. For data in your school\'s system contact the school. For data you sent to OKV write to technologyokv@gmail.com.'),
        ('Contact', 'OKV Technology Consults, technologyokv@gmail.com, WhatsApp +234 810 414 1138, www.okvtechnology.com.')]),
    'terms': ('Terms of Use', [
        ('Acceptance', 'By installing or using the School Result and Accounting Management System you accept these terms and the Software Licence Agreement.'),
        ('Use of the system', 'You are responsible for the accuracy of the data you enter, for keeping passwords private and for the actions of the users you create. Use the system only for lawful school administration. The administrator may suspend or delete users.'),
        ('Messaging', 'Messages are visible to their recipients and to the administrator. Do not send abusive, unlawful or private information about others. The administrator may remove messages and suspend accounts.'),
        ('Results and accounts', 'Results, grades, positions, invoices and receipts are calculated from the data you enter. You must check them before issuing them. Your school is responsible for official records.'),
        ('Backups', 'You are responsible for downloading backups regularly. OKV is not responsible for data lost through hardware failure, deletion or lack of backups.'),
        ('Availability and updates', 'The system runs on your computer, so its availability depends on your computer and network. We may release updates and will tell you how to install them.'),
        ('Limitation of liability', 'To the fullest extent permitted by law, OKV is not liable for indirect or consequential loss. Our total liability is limited to the amount you paid for the licence.'),
        ('Governing law', 'These terms are governed by the laws of the Federal Republic of Nigeria.')]),
    'cookies': ('Cookie Policy', [
        ('What this system stores in your browser', 'A single <b>session cookie</b> named <code>sid</code>. It is set when you sign in, is HttpOnly (page scripts cannot read it) and expires after 12 hours or when you sign out.'),
        ('Why', 'It is strictly necessary to keep you signed in. Without it the system cannot work, so it does not need consent and cannot be switched off.'),
        ('What we do not use', 'No advertising cookies, no tracking or analytics cookies, and no third-party cookies in the school system.'),
        ('Local settings', 'Your browser may remember that you dismissed the cookie notice. This stays on your device.'),
        ('Control', 'You can delete the cookie at any time in your browser settings or by signing out. You will then need to sign in again.')]),
    'eula': ('Software Licence Agreement', [
        ('Grant', 'OKV grants your school a non-exclusive, non-transferable licence to install and use the System on the school\'s computers for its own administration. During the 12-day trial you may evaluate all features. After activation the licence has no time limit.'),
        ('One licence, one school', 'One activation covers one school installation. Using the same code for another school or reselling the System is not allowed. Contact us for additional schools or branches.'),
        ('Restrictions', 'You may not copy the System to distribute it, remove or bypass the licence checks, reverse engineer it except where the law allows, or remove OKV\'s notices.'),
        ('Ownership', 'OKV keeps all rights in the software, documents and branding. Your school keeps ownership of its data.'),
        ('Payment', 'The licence fee is paid once. Fees are non-refundable once an activation code has been delivered, unless the website refund policy says otherwise.'),
        ('Support', 'We provide help by email and WhatsApp. Installation and training services are available on request and are quoted separately.'),
        ('Warranty', 'The System is provided as is. We try to keep it accurate and reliable, but do not warrant that it is error-free or fits every school\'s requirements.'),
        ('Ending', 'The licence ends if you break this agreement. You may stop using the System at any time. Your data remains in your database file.')])}
LEGAL_PAGES_HTML = {}


def legal_html(slug):
    title, secs = LEGAL[slug]
    links = ''.join('<a href="/legal/%s">%s</a>' % (k, v[0]) for k, v in LEGAL.items())
    body = ''.join('<h2>%s</h2><p>%s</p>' % (h, t) for h, t in secs)
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>%s</style></head>'
            '<body><nav><a href="/">&larr; Back to the system</a>%s</nav><main><article><h1>%s</h1><div class="t">School Result and Accounting Management System &middot; OKV Technology Consults &middot; Last updated 5 October 2026</div>%s</article></main></body></html>'
            % (title, LEGAL_CSS, links, title, body))



# ----------------------------------------------------------------------------- fee types, clearance, vouchers
FEE_TYPES = ['TUITION FEE', 'REGISTRATION FEE', 'ADMISSION FORM', 'ADMISSION FEE', 'EXAMINATION FEE', 'LESSON FEE', 'SPORT WEAR FEE', 'SCHOOL UNIFORM',
             'TEXT BOOKS', 'EXERCISE BOOKS', 'PTA LEVY', 'DEVELOPMENT LEVY', 'TRANSPORT FEE', 'FEEDING / MEALS', 'EXCURSION / FIELD TRIP', 'ID CARD',
             'COMPUTER / ICT FEE', 'LIBRARY FEE', 'LABORATORY FEE', 'BOARDING FEE', 'GRADUATION FEE', 'CERTIFICATE FEE', 'CLUBS / EXTRA-CURRICULAR',
             'MEDICAL / CLINIC FEE', 'INSURANCE', 'CAUTION DEPOSIT', 'LATE PAYMENT FINE', 'OTHER FEE']


def seed_fee_types(con):
    if not con.execute('select 1 from fee_types limit 1').fetchone():
        for n_ in FEE_TYPES:
            con.execute('insert into fee_types(name, custom) values(?, 0)', (n_,))


@route('GET', '/api/fee-types', FIN)
def r_fee_types(c):
    return [dict(r) for r in c.con.execute('select id, name, amount, custom, active from fee_types order by custom, name')]


@route('POST', '/api/fee-types', FIN)
def r_fee_type_save(c):
    b = c.body
    name = str(b.get('name', '')).strip().upper()
    if not name:
        raise ApiError('Enter the fee name')
    amount = max(0.0, round(num(b.get('amount')), 2))
    if b.get('id'):
        c.con.execute('update fee_types set name = ?, amount = ?, active = ? where id = ?', (name, amount, 0 if b.get('active') is False else 1, ival(b['id'])))
    else:
        ex = c.con.execute('select id from fee_types where name = ?', (name,)).fetchone()
        if ex:
            c.con.execute('update fee_types set amount = ?, active = 1 where id = ?', (amount, ex['id']))
        else:
            c.con.execute('insert into fee_types(name, amount, custom) values(?, ?, 1)', (name, amount))


@route('POST', '/api/fee-types/delete', FIN)
def r_fee_type_delete(c):
    c.con.execute('delete from fee_types where id = ? and custom = 1', (ival(c.body.get('id')),))


def clearance_data(con, st, ss, term):
    w, p = "i.status = 'open' and i.student_id = ? and i.session = ?", [st['id'], ss]
    if term:
        w += ' and i.term = ?'
        p.append(term)
    invs = [inv_dict(r) for r in con.execute(INV_SQL + 'where ' + w + ' order by i.idate', p)]
    billed, paid = sum(i['total'] for i in invs), sum(i['paid'] for i in invs)
    other = student_fin(con, st['id'])['balance']
    cl = con.execute('select name from classes where id = ?', (st['class_id'],)).fetchone()
    return {'school': school_info(con), 'student': {'id': st['id'], 'name': st['name'], 'reg': st['username'], 'cname': cl['name'] if cl else ''},
            'session': ss, 'term': term, 'invoices': invs, 'billed': round(billed, 2), 'paid': round(paid, 2), 'balance': round(billed - paid, 2),
            'all_balance': other, 'cleared': billed - paid <= 0.004 and other <= 0.004, 'n_invoices': len(invs)}


@route('GET', '/api/clearance/check', FIN)
def r_clearance_check(c):
    st = need_student(c.con, ival(c.q.get('student')))
    t = ival(c.q.get('term') or 0)
    return clearance_data(c.con, st, current_session(c), t if t in (1, 2, 3) else 0)


@route('POST', '/api/clearance', FIN)
def r_clearance_issue(c):
    b = c.body
    st = need_student(c.con, ival(b.get('student_id')))
    t = ival(b.get('term') or 0)
    t = t if t in (1, 2, 3) else 0
    ss = str(b.get('session') or settings(c.con)['session'])
    d = clearance_data(c.con, st, ss, t)
    prov = 1 if b.get('provisional') else 0
    if not d['cleared'] and not prov:
        raise ApiError('This pupil still owes N%s. Collect the payment first, or issue a provisional clearance with a reason.' % money_py(d['all_balance'] if d['all_balance'] > d['balance'] else d['balance']))
    if prov and not str(b.get('note', '')).strip():
        raise ApiError('Enter the reason for the provisional clearance')
    today = date.today().isoformat()
    no = next_no(c.con, 'CLR', today)
    c.con.execute('insert into clearances(no, student_id, session, term, issued, provisional, note, issued_by) values(?, ?, ?, ?, ?, ?, ?, ?)',
                  (no, st['id'], ss, t, today, prov, str(b.get('note', ''))[:300], c.user['name']))
    d.update(no=no, issued=today, provisional=bool(prov), note=str(b.get('note', ''))[:300], issued_by=c.user['name'])
    return d


def money_py(x):
    return '{:,.2f}'.format(x)


@route('GET', '/api/clearances', FIN)
def r_clearances(c):
    return [dict(r) for r in c.con.execute(
        'select k.id, k.no, k.issued, k.session, k.term, k.provisional, u.name as sname, u.username as reg, cl.name as cname from clearances k '
        'join users u on u.id = k.student_id left join classes cl on cl.id = u.class_id order by k.id desc limit 100')]


@route('GET', '/api/clearance/doc', FIN)
def r_clearance_doc(c):
    k = c.con.execute('select * from clearances where id = ?', (ival(c.q.get('id')),)).fetchone()
    if not k:
        raise ApiError('Clearance not found')
    st = need_student(c.con, k['student_id'])
    d = clearance_data(c.con, st, k['session'], k['term'])
    d.update(no=k['no'], issued=k['issued'], provisional=bool(k['provisional']), note=k['note'], issued_by=k['issued_by'])
    return d


@route('GET', '/api/expense', FIN)
def r_expense_get(c):
    e = c.con.execute('select e.*, a.name as aname from expenses e left join accounts a on a.id = e.account_id where e.id = ?', (ival(c.q.get('id')),)).fetchone()
    if not e:
        raise ApiError('Expense not found')
    d = {k: e[k] for k in ('id', 'no', 'edate', 'category', 'payee', 'description', 'amount', 'method', 'ref', 'status', 'created_by', 'aname')}
    d['school'] = school_info(c.con)
    return d


def pricing_url(iid=''):
    base = str(CFG.get('pricing_url') or '')
    if not base and endpoint_ready():
        base = str(CFG['endpoint']).split('?')[0] + '?page=pricing'
    return base + ('&iid=' + iid if base and iid else '')



# ----------------------------------------------------------------------------- assessment structure, grading schemes, remarks, layout, theme
STANDARD_BANDS = [(70, 'A', 'EXCELLENT'), (60, 'B', 'VERY GOOD'), (50, 'C', 'GOOD'), (45, 'D', 'FAIR'), (40, 'E', 'POOR'), (0, 'F', 'FAIL')]
STANDARD_KEYS = ['70& Above -A=Excellent', '60-69-B= Very Good,', '50-59-C=Good', '45-49- D=Fair,', '40-44-E=Poor,', '0-39-F=Fail']
WAEC_BANDS = [(75, 'A1', 'EXCELLENT'), (70, 'B2', 'VERY GOOD'), (65, 'B3', 'GOOD'), (60, 'C4', 'CREDIT'), (55, 'C5', 'CREDIT'),
              (50, 'C6', 'CREDIT'), (45, 'D7', 'PASS'), (40, 'E8', 'PASS'), (0, 'F9', 'FAIL')]
DEFAULT_ASSESS = {'ca': [20, 20], 'exam': 60}
ASSESS_PRESETS = {1: {'ca': [40], 'exam': 60}, 2: {'ca': [20, 20], 'exam': 60}, 3: {'ca': [10, 10, 10], 'exam': 70}}
DEFAULT_LAYOUT = {'accent': '#c4161c', 'font': 'calibri', 'show_photo': 1, 'show_domains': 1, 'show_bill': 1, 'show_position': 1,
                  'show_attendance': 1, 'show_keys': 1, 'title_suffix': 'REPORT SHEET', 'perf_title': "PUPIL'S ACADEMIC PERFORMANCE",
                  'ct_label': "CLASS TEACHER'S REMARK", 'ht_label': "HEAD TEACHER'S REMARK", 'domains': list(DOMAINS),
                  'rating_key': ['5= EXCELLENT, 4= VERY GOOD', '3= GOOD, 2= POOR', '1= VERY POOR'], 'footer': ''}
DEFAULT_THEME = {'name': 'navy', 'primary': '#16213e', 'accent': '#b58a2c', 'bg': '#eef0f4', 'dark': 0}
DEFAULT_CT_BANK = [{'min': 70, 'text': 'An excellent result. Keep up the good work.'}, {'min': 60, 'text': 'A very good performance. Aim even higher next term.'},
                   {'min': 50, 'text': 'A good result. More effort will bring further improvement.'}, {'min': 45, 'text': 'A fair result. You can do better with more effort.'},
                   {'min': 40, 'text': 'A weak result. Work harder and ask for help in the difficult subjects.'}, {'min': 0, 'text': 'A poor result. Serious improvement is needed.'}]
DEFAULT_HT_BANK = [{'min': 70, 'text': 'Excellent. Congratulations.'}, {'min': 60, 'text': 'Very good. Keep it up.'}, {'min': 50, 'text': 'Good. Aim higher.'},
                   {'min': 45, 'text': 'Fair. More effort is needed.'}, {'min': 40, 'text': 'Weak. Please improve.'}, {'min': 0, 'text': 'Poor. Parents should meet the class teacher.'}]
JSON_KEYS = ('layout', 'theme', 'remarks_bank', 'head_bank', 'grading_custom')


def jload(text, default):
    try:
        v = json.loads(text) if text else None
        return v if v is not None else default
    except ValueError:
        return default


def assess_of(cl):
    a = jload((cl['assess'] if cl is not None and 'assess' in cl.keys() else ''), None)
    if isinstance(a, dict) and isinstance(a.get('ca'), list) and a['ca'] and a.get('exam'):
        return {'ca': [int(x) for x in a['ca']][:3], 'exam': int(a['exam'])}
    return dict(DEFAULT_ASSESS)


def clean_assess(b):
    try:
        ca = [int(num(x)) for x in (b.get('ca') or [])]
    except (TypeError, ValueError):
        raise ApiError('Enter whole numbers for the marks')
    ca = [x for x in ca][:3]
    ex = int(num(b.get('exam')))
    if not 1 <= len(ca) <= 3:
        raise ApiError('Choose 1, 2 or 3 continuous assessments (C.A)')
    if any(x < 1 or x > 60 for x in ca) or ex < 1 or ex > 90:
        raise ApiError('Each C.A must be 1 to 60 marks and the exam 1 to 90 marks')
    if sum(ca) + ex != 100:
        raise ApiError('The C.A and exam marks must add up to 100 (they add up to %d)' % (sum(ca) + ex))
    return {'ca': ca, 'exam': ex}


def bands_text(bands):
    out = []
    for i, (mn, g, rm) in enumerate(bands):
        up = 100 if i == 0 else bands[i - 1][0] - 1
        out.append(('%d and above = %s (%s)' % (mn, g, rm.title())) if i == 0 else ('%d-%d = %s (%s)' % (mn, up, g, rm.title())))
    return out


def scheme_of(st, cl=None):
    key = cl['grading'] if (cl is not None and 'grading' in cl.keys() and cl['grading'] in ('standard', 'waec', 'custom')) else st.get('grading_default', 'standard')
    bands, keys = STANDARD_BANDS, STANDARD_KEYS
    if key == 'waec':
        bands = WAEC_BANDS
        keys = ['75-100 = A1 (Excellent)'] + bands_text(WAEC_BANDS)[1:]
    elif key == 'custom':
        raw = jload(st.get('grading_custom'), [])
        try:
            b = sorted(((int(x['min']), str(x['grade'])[:4].upper(), str(x['remark'])[:20].upper()) for x in raw), key=lambda x: -x[0])
            if b and b[-1][0] == 0:
                bands, keys = b, bands_text(b)
            else:
                key = 'standard'
        except (KeyError, TypeError, ValueError):
            key = 'standard'
    else:
        key = 'standard'
    return {'key': key, 'bands': bands, 'keys': keys}


def grade_in(bands, t):
    for mn, g, rm in bands:
        if t >= mn:
            return g, rm
    return bands[-1][1], bands[-1][2]


def layout_of(st):
    lay = dict(DEFAULT_LAYOUT)
    lay.update({k: v for k, v in jload(st.get('layout'), {}).items() if k in DEFAULT_LAYOUT})
    doms = [str(d).strip().upper()[:30] for d in (lay.get('domains') or []) if str(d).strip()][:14]
    lay['domains'] = doms or list(DOMAINS)
    return lay


def domains_of(con):
    return layout_of(settings(con))['domains']


def theme_of(st):
    t = dict(DEFAULT_THEME)
    t.update({k: v for k, v in jload(st.get('theme'), {}).items() if k in DEFAULT_THEME})
    return t


def auto_remark(bank, avg):
    for b in sorted(bank, key=lambda x: -int(x.get('min', 0))):
        if avg >= int(b.get('min', 0)):
            return str(b.get('text', ''))[:300]
    return ''


# ---- QR code and network addresses (public: they only reveal how to reach this server)
@route('GET', '/api/qr')
def r_qr(c):
    text = str(c.q.get('text', ''))
    if not re.match(r'^https?://[\w\-\.:/\?=&%#]{3,150}$', text):
        raise ApiError('Only web addresses can be turned into a QR code')
    return Raw(qr_svg(text, 6, 3).encode(), 'image/svg+xml')


@route('GET', '/api/lan')
def r_lan(c):
    return {'urls': lan_urls(), 'port': PORT}


# ----------------------------------------------------------------------------- QR code (byte mode, error correction M), no libraries
_QR_ECC_PER_BLOCK_M = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_QR_BLOCKS_M = (-1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5)


def _qr_raw_modules(ver):
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        na = ver // 7 + 2
        r -= (25 * na - 10) * na - 55
        if ver >= 7:
            r -= 36
    return r


def _qr_data_codewords(ver):
    return _qr_raw_modules(ver) // 8 - _QR_ECC_PER_BLOCK_M[ver] * _QR_BLOCKS_M[ver]


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(deg):
    res = [0] * (deg - 1) + [1]
    root = 1
    for _ in range(deg):
        for j in range(deg):
            res[j] = _gf_mul(res[j], root)
            if j + 1 < deg:
                res[j] ^= res[j + 1]
        root = _gf_mul(root, 2)
    return res


def _rs_remainder(data, divisor):
    res = [0] * len(divisor)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, c in enumerate(divisor):
            res[i] ^= _gf_mul(c, f)
    return res


def make_qr(text):
    """Returns a square list of rows of booleans (True = dark) for the text."""
    data = text.encode('utf-8')
    ver = None
    for v in range(1, 11):
        cc = 8 if v < 10 else 16
        if 4 + cc + 8 * len(data) <= _qr_data_codewords(v) * 8:
            ver = v
            break
    if ver is None:
        raise ValueError('Text is too long for the QR code')
    bits = [0, 1, 0, 0]
    cc = 8 if ver < 10 else 16
    bits += [(len(data) >> i) & 1 for i in range(cc - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    cap = _qr_data_codewords(ver) * 8
    bits += [0] * min(4, cap - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    nb, eb = _QR_BLOCKS_M[ver], _QR_ECC_PER_BLOCK_M[ver]
    raw = _qr_raw_modules(ver) // 8
    short = nb - raw % nb
    blen = raw // nb
    div = _rs_divisor(eb)
    blocks, k = [], 0
    for i in range(nb):
        d = words[k:k + blen - eb + (0 if i < short else 1)]
        k += len(d)
        e = _rs_remainder(d, div)
        if i < short:
            d = d + [None]
        blocks.append(d + e)
    final = []
    for i in range(len(blocks[0])):
        for j, b in enumerate(blocks):
            if i != blen - eb or j >= short:
                final.append(b[i])
    final = [x for x in final if x is not None]
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        if 0 <= x < size and 0 <= y < size:
            mod[y][x] = bool(dark)
            fn[y][x] = True
    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                dist = max(abs(dx), abs(dy))
                setf(cx + dx, cy + dy, dist not in (2, 4))
    if ver > 1:
        na = ver // 7 + 2
        step = 26 if ver == 32 else (ver * 4 + na * 2 + 1) // (na * 2 - 2) * 2
        pos = [6] + [size - 7 - i * step for i in range(na - 2, -1, -1)]
        for i, px in enumerate(pos):
            for j, py in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == na - 1) or (i == na - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setf(px + dx, py + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(mask):
        d = (0 << 3) | mask            # error correction level M = 0b00
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        return ((d << 10) | r) ^ 0x5412

    def draw_format(mask):
        bits_ = format_bits(mask)
        g = lambda i: (bits_ >> i) & 1
        for i in range(0, 6):
            setf(8, i, g(i))
        setf(8, 7, g(6)); setf(8, 8, g(7)); setf(7, 8, g(8))
        for i in range(9, 15):
            setf(14 - i, 8, g(i))
        for i in range(0, 8):
            setf(size - 1 - i, 8, g(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, g(i))
        setf(8, size - 8, 1)
    draw_format(0)
    if ver >= 7:
        r = ver
        for _ in range(12):
            r = (r << 1) ^ ((r >> 11) * 0x1F25)
        vb = (ver << 12) | r
        for i in range(18):
            b = (vb >> i) & 1
            a, c = size - 11 + i % 3, i // 3
            setf(a, c, b)
            setf(c, a, b)
    # place data
    bitsdata = []
    for w in final:
        bitsdata += [(w >> i) & 1 for i in range(7, -1, -1)]
    i = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not fn[y][x] and i < len(bitsdata):
                    mod[y][x] = bool(bitsdata[i])
                    i += 1
        right -= 2
    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
             lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
             lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def penalty(m):
        sc = 0
        for rows in (m, [list(c) for c in zip(*m)]):
            for row in rows:
                run, prev = 1, row[0]
                for v in row[1:]:
                    if v == prev:
                        run += 1
                    else:
                        if run >= 5:
                            sc += run - 2
                        run, prev = 1, v
                if run >= 5:
                    sc += run - 2
        for y in range(size - 1):
            for x in range(size - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    sc += 3
        dark = sum(v for row in m for v in row)
        sc += (abs(dark * 20 - size * size * 10) // (size * size)) * 10
        return sc
    best, best_m, best_mask = None, None, 0
    for mk in range(8):
        m = [row[:] for row in mod]
        for y in range(size):
            for x in range(size):
                if not fn[y][x] and masks[mk](x, y):
                    m[y][x] = not m[y][x]
        mod_backup = mod
        # draw format for this mask on the copy
        saved = [row[:] for row in mod]
        for y in range(size):
            mod[y] = m[y]
        draw_format(mk)
        p = penalty(mod)
        if best is None or p < best:
            best, best_m, best_mask = p, [row[:] for row in mod], mk
        for y in range(size):
            mod[y] = saved[y]
    return best_m


def qr_svg(text, scale=6, border=3):
    m = make_qr(text)
    n = len(m)
    d = ''.join('M%d,%dh1v1h-1z' % (x + border, y + border) for y in range(n) for x in range(n) if m[y][x])
    s = (n + 2 * border)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="#fff"/><path d="%s" fill="#000"/></svg>' % (s, s, s * scale, s * scale, d))



# ----------------------------------------------------------------------------- admissions and registration
APPLICANT_STATUSES = ('Applied', 'Screening', 'Waiting list', 'Rejected')
DEFAULT_ADMISSION_LETTER = ('Dear {parent},\n\nWe are pleased to inform you that {name} has been offered admission into {class} at {school}. '
                            'The pupil\'s registration number is {reg}.\n\nPlease complete payment of the admission fees, bring the required documents and '
                            'meet the head teacher on resumption.\n\nWelcome to our school family.')


def norm_date(v):
    v = str(v or '').strip()
    if not v:
        return ''
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', v)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.match(r'^(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{4})$', v)
        if not m:
            raise ApiError('Date "%s" is not valid. Use DD/MM/YYYY or YYYY-MM-DD' % v)
        d, mo, y = map(int, m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        raise ApiError('Date "%s" is not a real date' % v)


def applicant_dict(r):
    return {k: r[k] for k in ('id', 'no', 'name', 'gender', 'dob', 'class_id', 'parent_name', 'phone', 'email', 'address', 'prev_school', 'status',
                              'notes', 'created', 'student_id', 'source', 'reg_no', 'cname')}


APP_SQL = 'select a.*, c.name as cname from applicants a left join classes c on c.id = a.class_id '


@route('GET', '/api/applicants', STAFF)
def r_applicants(c):
    w, p = ['1 = 1'], []
    if c.q.get('status'):
        w.append('a.status = ?'); p.append(c.q['status'])
    if c.q.get('class'):
        w.append('a.class_id = ?'); p.append(ival(c.q['class']))
    if c.q.get('q'):
        w.append('(a.name like ? or a.no like ? or a.phone like ? or a.parent_name like ?)'); p += ['%' + c.q['q'] + '%'] * 4
    rows = [applicant_dict(r) for r in c.con.execute(APP_SQL + 'where ' + ' and '.join(w) + ' order by a.id desc limit 1000', p)]
    counts = {r[0]: r[1] for r in c.con.execute('select status, count(*) from applicants group by status')}
    return {'rows': rows, 'counts': counts, 'open': settings(c.con).get('admissions_open') == '1'}


def clean_applicant(b):
    name = str(b.get('name', '')).strip().upper()
    if not name:
        raise ApiError('Enter the applicant\'s name')
    g = str(b.get('gender', '')).strip().upper()
    g = {'M': 'MALE', 'F': 'FEMALE'}.get(g, g)
    return {'name': name[:120], 'gender': g if g in ('MALE', 'FEMALE') else '', 'dob': norm_date(b.get('dob')),
            'parent_name': str(b.get('parent_name', '')).strip()[:120], 'phone': str(b.get('phone', '')).strip()[:30],
            'email': str(b.get('email', '')).strip()[:120], 'address': str(b.get('address', '')).strip()[:250],
            'prev_school': str(b.get('prev_school', '')).strip()[:150], 'notes': str(b.get('notes', '')).strip()[:500]}


def insert_applicant(con, a, class_id, source, session):
    no = next_no(con, 'APP', date.today().isoformat())
    return con.execute('insert into applicants(no, name, gender, dob, class_id, parent_name, phone, email, address, prev_school, notes, source, session) '
                       'values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (no, a['name'], a['gender'], a['dob'], class_id, a['parent_name'], a['phone'], a['email'], a['address'], a['prev_school'],
                        a['notes'], source, session)).lastrowid, no


@route('POST', '/api/applicants', STAFF)
def r_applicant_save(c):
    b = c.body
    a = clean_applicant(b)
    cid = ival(b['class_id']) if b.get('class_id') else None
    if b.get('id'):
        st = str(b.get('status') or 'Applied')
        row = c.con.execute('select status from applicants where id = ?', (ival(b['id']),)).fetchone()
        if not row:
            raise ApiError('Applicant not found')
        if row['status'] != 'Admitted' and st in APPLICANT_STATUSES:
            c.con.execute('update applicants set status = ? where id = ?', (st, ival(b['id'])))
        c.con.execute('update applicants set name = ?, gender = ?, dob = ?, class_id = ?, parent_name = ?, phone = ?, email = ?, address = ?, '
                      'prev_school = ?, notes = ? where id = ?', (a['name'], a['gender'], a['dob'], cid, a['parent_name'], a['phone'], a['email'],
                                                                    a['address'], a['prev_school'], a['notes'], ival(b['id'])))
        return {'id': ival(b['id'])}
    iid, no = insert_applicant(c.con, a, cid, 'Office', settings(c.con)['session'])
    return {'id': iid, 'no': no}


@route('POST', '/api/applicants/status', STAFF)
def r_applicant_status(c):
    st = str(c.body.get('status', ''))
    if st not in APPLICANT_STATUSES:
        raise ApiError('Invalid status')
    c.con.execute("update applicants set status = ? where id = ? and status != 'Admitted'", (st, ival(c.body.get('id'))))


@route('POST', '/api/applicants/delete', STAFF)
def r_applicant_delete(c):
    c.con.execute('delete from applicants where id = ?', (ival(c.body.get('id')),))


@route('POST', '/api/applicants/admit', STAFF)
def r_applicant_admit(c):
    b = c.body
    a = c.con.execute('select * from applicants where id = ?', (ival(b.get('id')),)).fetchone()
    if not a:
        raise ApiError('Applicant not found')
    if a['status'] == 'Admitted':
        raise ApiError('This applicant has already been admitted (Reg No %s)' % a['reg_no'])
    cid = ival(b.get('class_id') or a['class_id'])
    if not c.con.execute('select 1 from classes where id = ?', (cid,)).fetchone():
        raise ApiError('Choose the class to admit the pupil into')
    reg = str(b.get('reg_no') or '').strip() or next_reg(c.con)
    if c.con.execute('select 1 from users where username = ?', (reg,)).fetchone():
        raise ApiError('That Reg No is already in use')
    salt, h = mkpw(reg)
    sid = c.con.execute("insert into users(username, name, role, salt, pw, class_id, gender, dob, phone) values(?, ?, 'student', ?, ?, ?, ?, ?, ?)",
                        (reg, a['name'], salt, h, cid, a['gender'], a['dob'], a['phone'])).lastrowid
    c.con.execute("update applicants set status = 'Admitted', student_id = ?, reg_no = ?, class_id = ? where id = ?", (sid, reg, cid, a['id']))
    inv = None
    if b.get('invoice', True):
        items = [{'l': r['name'], 'a': r['amount']} for r in c.con.execute(
            "select name, amount from fee_types where name in ('ADMISSION FORM', 'ADMISSION FEE', 'REGISTRATION FEE') and amount > 0 and active = 1")]
        if items:
            iid, no = make_invoice(c.con, c.user['name'], sid, settings(c.con)['session'], 0, date.today().isoformat(), '', items, 0, 'Admission', 'custom')
            inv = {'id': iid, 'no': no}
    return {'student_id': sid, 'reg_no': reg, 'invoice': inv}


@route('GET', '/api/applicants/doc', STAFF)
def r_applicant_doc(c):
    r = c.con.execute(APP_SQL + 'where a.id = ?', (ival(c.q.get('id')),)).fetchone()
    if not r:
        raise ApiError('Applicant not found')
    d = applicant_dict(r)
    d['school'] = school_info(c.con)
    d['letter'] = settings(c.con).get('admission_letter') or DEFAULT_ADMISSION_LETTER
    d['session'] = settings(c.con)['session']
    return d


@route('GET', '/api/apply/info')
def r_apply_info(c):
    s = settings(c.con)
    return {'open': s.get('admissions_open') == '1', 'school': s['school_name'],
            'classes': [x['name'] for x in sorted(c.con.execute('select * from classes').fetchall(), key=class_key)]}


@route('POST', '/api/apply')
def r_apply(c):
    s = settings(c.con)
    if s.get('admissions_open') != '1':
        raise ApiError('Online admission is closed')
    if c.body.get('website'):
        return {'ok': 1}
    now = time.time()
    key = 'apply_' + c.ip
    with FAILS_LOCK:
        recent = [t for t in FAILS.get(key, []) if now - t < 3600]
        if len(recent) >= 6:
            raise ApiError('Too many applications from this device. Please try again later.', 429)
        recent.append(now)
        FAILS[key] = recent
    a = clean_applicant(c.body)
    if not a['parent_name'] or not a['phone']:
        raise ApiError('Enter the parent or guardian name and phone number')
    cl = c.con.execute('select id from classes where name = ?', (str(c.body.get('class', '')).strip().upper(),)).fetchone()
    iid, no = insert_applicant(c.con, a, cl['id'] if cl else None, 'Online', s['session'])
    return {'ok': 1, 'no': no}


def apply_html(con):
    s = settings(con)
    name = s['school_name']
    th = theme_of(s)
    opts = ''.join('<option>%s</option>' % x['name'] for x in sorted(con.execute('select * from classes').fetchall(), key=class_key))
    esc_ = lambda t: (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    if s.get('admissions_open') != '1':
        body = '<h1>Admissions are closed</h1><p>Please contact the school office.</p>'
    else:
        body = ('<h1>Admission application</h1><p class="t">Fill in the form. The school will contact you.</p><form id="f">'
                '<label>Child\'s full name<input name="name" required></label><div class="g"><label>Gender<select name="gender"><option value="">Choose</option><option>MALE</option><option>FEMALE</option></select></label>'
                '<label>Date of birth<input type="date" name="dob"></label></div><label>Class applying for<select name="class">%s</select></label>'
                '<label>Parent / guardian name<input name="parent_name" required></label><div class="g"><label>Phone<input name="phone" required></label><label>Email<input name="email" type="email"></label></div>'
                '<label>Home address<input name="address"></label><label>Previous school (if any)<input name="prev_school"></label><input name="website" style="display:none" tabindex="-1">'
                '<button>Submit application</button><p id="m"></p></form>'
                '<script>document.getElementById("f").onsubmit=function(e){e.preventDefault();var o={};new FormData(this).forEach(function(v,k){o[k]=v});'
                'fetch("/api/apply",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)}).then(function(r){return r.json().then(function(d){return[r.ok,d]})}).then(function(x){'
                'var m=document.getElementById("m");if(x[0]){document.getElementById("f").innerHTML="<h2>Thank you!</h2><p>Your application number is <b>"+x[1].no+"</b>. Keep it safe. The school will contact you.</p>"}else{m.textContent=x[1].error||"Something went wrong";m.style.color="#a4262c"}})}</script>') % opts
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admission - %s</title><style>'
            'body{margin:0;background:%s;font:16px/1.5 system-ui,sans-serif;color:#1d2433}main{max-width:560px;margin:0 auto;padding:18px}.card{background:#fff;border-radius:12px;padding:22px;border:1px solid #d5d9e2}'
            'h1{font:700 24px Georgia,serif;color:%s;margin:0 0 4px}h2{color:%s}.t{color:#667085;margin-top:0}label{display:block;margin-top:12px;font-size:13px;color:#667085}input,select{width:100%%;box-sizing:border-box;margin-top:4px;padding:10px;border:1px solid #d5d9e2;border-radius:8px;font:inherit;color:#1d2433;background:#fff}'
            '.g{display:grid;grid-template-columns:1fr 1fr;gap:10px}button{margin-top:18px;width:100%%;background:%s;color:#fff;border:0;border-radius:8px;padding:13px;font:600 16px system-ui;cursor:pointer}.s{text-align:center;font-weight:700;color:%s;margin-bottom:10px}</style></head>'
            '<body><main><div class="s">%s</div><div class="card">%s</div></main></body></html>' % (esc_(name), th['bg'], th['primary'], th['primary'], th['primary'], th['accent'], esc_(name), body))


# ----------------------------------------------------------------------------- CSV import (with templates) and multi-format export
IMPORT_DEFS = {
    'pupils': {'label': 'Pupils', 'roles': ('admin', 'staff'), 'cols': [
        ('name', True, 'Full name', 'CHIOMA OKAFOR'), ('class', True, 'Class name exactly as in the system', 'NURSERY 1'), ('reg_no', False, 'Leave empty to create one', ''),
        ('gender', False, 'MALE or FEMALE (M or F)', 'FEMALE'), ('dob', False, 'DD/MM/YYYY or YYYY-MM-DD', '12/05/2021'), ('parent_phone', False, 'Parent phone number', '08031234567'),
        ('opening_balance', False, 'Fees owed before using the system (a balance invoice is created)', '0')],
        'note': 'Existing Reg Nos are skipped. A new pupil\'s first password is the Reg No.'},
    'staff': {'label': 'Staff users', 'roles': ('admin',), 'cols': [
        ('name', True, 'Full name', 'Mrs Ada Okeke'), ('username', True, 'Login name', 'ada'), ('role', True, 'teacher, accountant or admin', 'teacher'),
        ('password', False, 'Leave empty to generate one (shown after import)', '')], 'note': 'Existing usernames are skipped.'},
    'subjects': {'label': 'Subjects', 'roles': ('admin', 'staff'), 'cols': [('class', True, 'Class name', 'PRIMARY 1'), ('subject', True, 'Subject name', 'MATHEMATICS')],
                 'note': 'Adds subjects to the end of the class list. Existing subjects are skipped.'},
    'scores': {'label': 'Scores', 'roles': ('admin', 'staff'), 'cols': [
        ('reg_no', True, 'Pupil Reg No', 'GA0001'), ('subject', True, 'Subject name in the pupil\'s class', 'MATHEMATICS'), ('term', True, '1, 2 or 3', '1'),
        ('ca1', False, '1st C.A mark', '15'), ('ca2', False, '2nd C.A mark', '16'), ('ca3', False, '3rd C.A mark (classes with 3 C.A)', ''), ('exam', False, 'Exam mark', '44')],
        'note': 'Imports into the current session. Marks above the class maximum are rejected. Empty cells keep the existing mark.'},
    'attendance': {'label': 'Attendance (days present)', 'roles': ('admin', 'staff'), 'cols': [('reg_no', True, 'Pupil Reg No', 'GA0001'), ('term', True, '1, 2 or 3', '1'),
                   ('days_present', True, 'Number of days present', '55')], 'note': 'Set the days school opened under Attendance & remarks.'},
    'fees': {'label': 'Class fee schedule', 'roles': ('admin', 'accountant'), 'cols': [('class', True, 'Class name', 'NURSERY 1'), ('fee', True, 'Fee name', 'TUITION FEE'),
             ('amount', True, 'Amount in naira', '50000')], 'note': 'Up to 8 lines per class. Importing a class replaces its schedule.'},
    'fee_types': {'label': 'Fee types', 'roles': ('admin', 'accountant'), 'cols': [('name', True, 'Fee name', 'EXCURSION TO ABUJA'), ('amount', False, 'Default amount', '7500')],
                  'note': 'Adds or updates fee types you can pick when raising invoices.'},
    'invoices': {'label': 'Invoices and opening balances', 'roles': ('admin', 'accountant'), 'cols': [
        ('reg_no', True, 'Pupil Reg No', 'GA0001'), ('description', True, 'Fee description', 'TUITION FEE'), ('amount', True, 'Amount', '50000'),
        ('term', False, '1, 2, 3 or 0 for no term', '1'), ('date', False, 'Invoice date', '14/09/2026')],
        'note': 'Rows with the same Reg No, term and date become one invoice with several lines.'},
    'payments': {'label': 'School fee payments (receipts)', 'roles': ('admin', 'accountant'), 'cols': [
        ('reg_no', True, 'Pupil Reg No', 'GA0001'), ('amount', True, 'Amount paid', '30000'), ('method', False, 'CASH, TRANSFER, POS or CHEQUE', 'TRANSFER'),
        ('date', False, 'Payment date', '20/09/2026'), ('reference', False, 'Teller or transfer reference', 'TX1234')],
        'note': 'Each row creates a numbered receipt and is applied to the pupil\'s oldest unpaid invoice.'},
    'expenses': {'label': 'Expenses', 'roles': ('admin', 'accountant'), 'cols': [
        ('date', True, 'Date', '26/09/2026'), ('category', True, 'For example SALARIES', 'SALARIES'), ('payee', False, 'Paid to', 'Teaching staff'),
        ('description', False, 'Details', 'September salaries'), ('amount', True, 'Amount', '85000'), ('method', False, 'CASH, TRANSFER, POS or CHEQUE', 'TRANSFER'),
        ('reference', False, 'Reference', '')], 'note': 'Paid from the first account (CASH). Each row gets a voucher number.'},
    'income': {'label': 'Other income', 'roles': ('admin', 'accountant'), 'cols': [
        ('date', True, 'Date', '25/09/2026'), ('payer', False, 'Received from', 'Parent'), ('category', True, 'For example UNIFORM SALES', 'UNIFORM SALES'),
        ('amount', True, 'Amount', '12000'), ('method', False, 'CASH, TRANSFER, POS or CHEQUE', 'CASH')], 'note': 'Each row creates a numbered receipt.'},
    'applicants': {'label': 'Admission applicants', 'roles': ('admin', 'staff'), 'cols': [
        ('name', True, 'Child\'s full name', 'TOCHI NWOSU'), ('class', False, 'Class applied for', 'NURSERY 1'), ('gender', False, 'MALE or FEMALE', 'MALE'),
        ('dob', False, 'Date of birth', '03/03/2022'), ('parent_name', False, 'Parent or guardian', 'Mr Nwosu'), ('phone', False, 'Phone', '08030000000'),
        ('email', False, 'Email', ''), ('address', False, 'Address', ''), ('previous_school', False, 'Previous school', '')], 'note': 'New applicants get status Applied.'},
}


@route('GET', '/api/import/defs', ANY)
def r_import_defs(c):
    out = []
    for k, d in IMPORT_DEFS.items():
        if c.user['role'] in d['roles']:
            out.append({'kind': k, 'label': d['label'], 'note': d['note'],
                        'cols': [{'name': n_, 'required': req, 'help': h, 'example': ex} for n_, req, h, ex in d['cols']]})
    return out


def _class_by_name(con, name):
    r = con.execute('select * from classes where upper(name) = ?', (str(name or '').strip().upper(),)).fetchone()
    if not r:
        raise ApiError('Class "%s" was not found. Spell it exactly as under Classes & subjects' % name)
    return r


def _student_by_reg(con, reg):
    r = con.execute("select * from users where role = 'student' and username = ?", (str(reg or '').strip(),)).fetchone()
    if not r:
        raise ApiError('No pupil with Reg No "%s"' % reg)
    return r


def _amount(v, allow_zero=False):
    s_ = str(v or '').replace(',', '').replace('N', '').replace('₦', '').strip()
    try:
        x = round(float(s_), 2)
    except ValueError:
        raise ApiError('"%s" is not a valid amount' % v)
    if x < 0 or (x == 0 and not allow_zero):
        raise ApiError('The amount must be greater than zero')
    return x


def _method(v):
    v = str(v or 'CASH').strip().upper()
    return v if v in METHODS else 'CASH'


def _imp_row(c, kind, r, ss, gen):
    con = c.con
    g = lambda k: str(r.get(k, '') if r.get(k) is not None else '').strip()
    if kind == 'pupils':
        if not g('name') or not g('class'):
            raise ApiError('Name and class are required')
        cl = _class_by_name(con, g('class'))
        reg = g('reg_no') or next_reg(con)
        if con.execute('select 1 from users where username = ?', (reg,)).fetchone():
            return 'skipped'
        gd = g('gender').upper()
        gd = {'M': 'MALE', 'F': 'FEMALE'}.get(gd, gd)
        salt, h = mkpw(reg)
        sid = con.execute("insert into users(username, name, role, salt, pw, class_id, gender, dob, phone) values(?, ?, 'student', ?, ?, ?, ?, ?, ?)",
                          (reg, g('name').upper()[:120], salt, h, cl['id'], gd if gd in ('MALE', 'FEMALE') else '', norm_date(g('dob')), g('parent_phone')[:30])).lastrowid
        if g('opening_balance') and _amount(g('opening_balance'), True) > 0:
            make_invoice(con, c.user['name'], sid, ss, 0, date.today().isoformat(), '', [{'l': 'BALANCE BROUGHT FORWARD', 'a': _amount(g('opening_balance'))}], 0, '', 'custom')
        return 'added'
    if kind == 'staff':
        if c.user['role'] != 'admin':
            raise ApiError('Only the administrator can import staff')
        role = {'teacher': 'staff', 'staff': 'staff', 'accountant': 'accountant', 'admin': 'admin', 'administrator': 'admin'}.get(g('role').lower())
        if not g('name') or not g('username') or not role:
            raise ApiError('Name, username and a role (teacher, accountant or admin) are required')
        if con.execute('select 1 from users where username = ?', (g('username'),)).fetchone():
            return 'skipped'
        pw = g('password') or temp_pw()
        if len(pw) < 4:
            raise ApiError('The password must have at least 4 characters')
        salt, h = mkpw(pw)
        con.execute('insert into users(username, name, role, salt, pw) values(?, ?, ?, ?, ?)', (g('username'), g('name')[:120], role, salt, h))
        gen.append({'username': g('username'), 'name': g('name'), 'password': pw})
        return 'added'
    if kind == 'subjects':
        cl = _class_by_name(con, g('class'))
        sj = g('subject').upper()
        if not sj:
            raise ApiError('Subject name is required')
        if con.execute('select 1 from subjects where class_id = ? and name = ?', (cl['id'], sj)).fetchone():
            return 'skipped'
        pos = con.execute('select coalesce(max(pos), -1) + 1 from subjects where class_id = ?', (cl['id'],)).fetchone()[0]
        con.execute('insert into subjects(class_id, name, pos) values(?, ?, ?)', (cl['id'], sj, pos))
        return 'added'
    if kind == 'scores':
        st = _student_by_reg(con, g('reg_no'))
        t = ival(g('term'))
        if t not in (1, 2, 3):
            raise ApiError('Term must be 1, 2 or 3')
        sub = con.execute('select id from subjects where class_id = ? and upper(name) = ?', (st['class_id'], g('subject').upper())).fetchone()
        if not sub:
            raise ApiError('Subject "%s" is not in the pupil\'s class' % g('subject'))
        cl = con.execute('select * from classes where id = ?', (st['class_id'],)).fetchone()
        any_ = False
        for key, col, f in (('ca1', 'ca1', 'a'), ('ca2', 'ca2', 'b'), ('ca3', 'ca3', 'c'), ('exam', 'exam', 'e')):
            if g(key) == '':
                continue
            mx = field_max(cl, f)
            if mx is None:
                raise ApiError('This class does not use %s' % key.upper())
            v = num(g(key), None)
            if v is None or v < 0 or v > mx:
                raise ApiError('%s "%s" must be a number from 0 to %d' % (key.upper(), g(key), mx))
            con.execute('insert into scores(student_id, session, term, subject_id, %s) values(?, ?, ?, ?, ?) '
                        'on conflict(student_id, session, term, subject_id) do update set %s = excluded.%s' % (col, col, col), (st['id'], ss, t, sub['id'], v))
            any_ = True
        if not any_:
            raise ApiError('No marks in this row')
        return 'updated'
    if kind == 'attendance':
        st = _student_by_reg(con, g('reg_no'))
        t = ival(g('term'))
        if t not in (1, 2, 3):
            raise ApiError('Term must be 1, 2 or 3')
        v = max(0, ival(g('days_present')))
        con.execute('insert or ignore into records(student_id, session, term) values(?, ?, ?)', (st['id'], ss, t))
        con.execute('update records set present = ? where student_id = ? and session = ? and term = ?', (v, st['id'], ss, t))
        return 'updated'
    if kind == 'fees':
        cl = _class_by_name(con, g('class'))
        gen.append((cl['id'], g('fee').upper(), _amount(g('amount'), True)))
        return 'queued'
    if kind == 'fee_types':
        nm = g('name').upper()
        if not nm:
            raise ApiError('Fee name is required')
        am = _amount(g('amount'), True) if g('amount') else 0
        ex = con.execute('select id from fee_types where name = ?', (nm,)).fetchone()
        if ex:
            con.execute('update fee_types set amount = ? where id = ?', (am, ex['id']))
            return 'updated'
        con.execute('insert into fee_types(name, amount, custom) values(?, ?, 1)', (nm, am))
        return 'added'
    if kind == 'invoices':
        st = _student_by_reg(con, g('reg_no'))
        t = ival(g('term') or 0)
        if t not in (0, 1, 2, 3):
            raise ApiError('Term must be 0, 1, 2 or 3')
        gen.append((st['id'], t, norm_date(g('date')) or date.today().isoformat(), g('description').upper() or 'OTHER FEE', _amount(g('amount'))))
        return 'queued'
    if kind == 'payments':
        st = _student_by_reg(con, g('reg_no'))
        amount, rdate = _amount(g('amount')), norm_date(g('date')) or date.today().isoformat()
        no = next_no(con, 'RCT', rdate)
        rid = con.execute("insert into receipts(no, kind, student_id, payer, amount, method, account_id, ref, rdate, created_by) values(?, 'fee', ?, ?, ?, ?, ?, ?, ?, ?)",
                          (no, st['id'], st['name'], amount, _method(g('method')), check_account(con, None), g('reference')[:60], rdate, c.user['name'])).lastrowid
        apply_credit(con, st['id'])
        return 'added'
    if kind == 'expenses':
        if not g('category'):
            raise ApiError('Category is required')
        edate = norm_date(g('date')) or date.today().isoformat()
        con.execute('insert into expenses(no, edate, category, payee, description, amount, method, account_id, ref, created_by) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (next_no(con, 'PV', edate), edate, g('category').upper()[:60], g('payee').upper()[:100], g('description')[:300], _amount(g('amount')), _method(g('method')),
                     check_account(con, None), g('reference')[:60], c.user['name']))
        return 'added'
    if kind == 'income':
        if not g('category'):
            raise ApiError('Category is required')
        rdate = norm_date(g('date')) or date.today().isoformat()
        con.execute("insert into receipts(no, kind, payer, category, amount, method, account_id, rdate, created_by) values(?, 'other', ?, ?, ?, ?, ?, ?, ?)",
                    (next_no(con, 'RCT', rdate), g('payer').upper()[:100], g('category').upper()[:60], _amount(g('amount')), _method(g('method')), check_account(con, None), rdate, c.user['name']))
        return 'added'
    if kind == 'applicants':
        a = clean_applicant({'name': g('name'), 'gender': g('gender'), 'dob': g('dob'), 'parent_name': g('parent_name'), 'phone': g('phone'),
                             'email': g('email'), 'address': g('address'), 'prev_school': g('previous_school')})
        cl = con.execute('select id from classes where upper(name) = ?', (g('class').upper(),)).fetchone() if g('class') else None
        insert_applicant(con, a, cl['id'] if cl else None, 'Import', ss)
        return 'added'
    raise ApiError('Unknown import type')


@route('POST', '/api/import', ANY)
def r_import(c):
    kind = str(c.body.get('kind', ''))
    d = IMPORT_DEFS.get(kind)
    if not d or c.user['role'] not in d['roles']:
        raise ApiError('You are not allowed to import that', 403)
    rows = c.body.get('rows') or []
    if len(rows) > 5000:
        raise ApiError('Import at most 5,000 rows at a time')
    ss = str(c.body.get('session') or settings(c.con)['session'])
    c.con.execute('savepoint imp')
    res = {'added': 0, 'updated': 0, 'skipped': 0, 'errors': [], 'generated': []}
    gen = res['generated'] if kind == 'staff' else []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            res['skipped'] += 1
            res['errors'].append({'row': i + 2, 'error': 'Each row must have column names and values'})
            continue
        r = {re.sub(r'[^a-z0-9]+', '_', str(k).strip().lower()).strip('_'): v for k, v in r.items()}
        c.con.execute('savepoint rw')
        try:
            out = _imp_row(c, kind, r, ss, gen)
            if out in res:
                res[out] += 1
            c.con.execute('release rw')
        except ApiError as e:
            c.con.execute('rollback to rw')
            c.con.execute('release rw')
            res['errors'].append({'row': i + 2, 'error': str(e)})
    if kind == 'fees':
        by = {}
        for cid, label, amt in gen:
            by.setdefault(cid, []).append({'l': label, 'a': amt})
        for cid, lines in by.items():
            lines = (lines + [{'l': '', 'a': 0}] * 8)[:8]
            c.con.execute('update classes set fees = ? where id = ?', (json.dumps(lines), cid))
            res['updated'] += 1
    elif kind == 'invoices':
        grp = {}
        for sid, t, dt, desc, amt in gen:
            grp.setdefault((sid, t, dt), []).append({'l': desc, 'a': amt})
        for (sid, t, dt), items in grp.items():
            make_invoice(c.con, c.user['name'], sid, ss, t, dt, '', items, 0, 'Imported', 'custom')
            res['added'] += 1
    if c.body.get('dry_run'):
        c.con.execute('rollback to imp')
    c.con.execute('release imp')
    res['dry_run'] = bool(c.body.get('dry_run'))
    return res


def _xml(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _col(i):
    s_ = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s_ = chr(65 + r) + s_
    return s_


def xlsx_bytes(title, headers, rows):
    import io, zipfile
    def cell(ref, v, style=0):
        if isinstance(v, bool) or v is None:
            v = '' if v is None else str(v)
        if isinstance(v, (int, float)):
            return '<c r="%s"%s><v>%s</v></c>' % (ref, ' s="%d"' % style if style else '', v)
        return '<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (ref, ' s="%d"' % style if style else '', _xml(v))
    body = '<row r="1">' + ''.join(cell(_col(i) + '1', h, 1) for i, h in enumerate(headers)) + '</row>'
    for ri, row in enumerate(rows, 2):
        body += '<row r="%d">' % ri + ''.join(cell('%s%d' % (_col(i), ri), v) for i, v in enumerate(row)) + '</row>'
    widths = ''.join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, min(48, max(10, max([len(str(h))] + [len(str(r[i])) for r in rows[:200] if i < len(r)]) + 2)))
                     for i, h in enumerate(headers))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
             '<cols>%s</cols><sheetData>%s</sheetData></worksheet>' % (widths, body))
    name = re.sub(r'[\[\]\*\?/\\:]', ' ', title)[:31] or 'Sheet1'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % _xml(name))
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE9ECF3"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    return buf.getvalue()


def to_format(title, headers, rows, fmt):
    import csv, io
    safe = re.sub(r'[^A-Za-z0-9_\-]+', '_', title).strip('_') or 'export'
    stamp = date.today().strftime('%Y%m%d')
    if fmt == 'xlsx':
        return Raw(xlsx_bytes(title, headers, rows), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                   [('Content-Disposition', 'attachment; filename="%s_%s.xlsx"' % (safe, stamp))])
    if fmt == 'json':
        data = json.dumps([dict(zip(headers, r)) for r in rows], indent=1, ensure_ascii=False)
        return Raw(data.encode('utf-8'), 'application/json', [('Content-Disposition', 'attachment; filename="%s_%s.json"' % (safe, stamp))])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter='\t' if fmt == 'tsv' else ',', lineterminator='\r\n')
    w.writerow(headers)
    w.writerows(rows)
    ext = 'txt' if fmt == 'tsv' else 'csv'
    return Raw(('\ufeff' + buf.getvalue()).encode('utf-8'), 'text/%s; charset=utf-8' % ('plain' if fmt == 'tsv' else 'csv'),
               [('Content-Disposition', 'attachment; filename="%s_%s.%s"' % (safe, stamp, ext))])


EXPORT_ROLES = {'pupils': ('admin', 'staff', 'accountant'), 'staff': ('admin',), 'classes': ('admin', 'staff', 'accountant'), 'scores': ('admin', 'staff'),
                'attendance': ('admin', 'staff'), 'invoices': FIN, 'receipts': FIN, 'expenses': FIN, 'debtors': FIN, 'fee_types': FIN, 'fee_schedule': FIN,
                'applicants': ('admin', 'staff')}
EXPORT_LABELS = {'pupils': 'Pupils', 'staff': 'Staff users', 'classes': 'Classes and subjects', 'scores': 'Scores (choose a term)', 'attendance': 'Attendance',
                 'invoices': 'Invoices', 'receipts': 'Receipts and other income', 'expenses': 'Expenses', 'debtors': 'Debtors', 'fee_types': 'Fee types',
                 'fee_schedule': 'Class fee schedule', 'applicants': 'Admission applicants'}


def dataset(con, name, ss, term):
    if name == 'pupils':
        h = ['reg_no', 'name', 'class', 'gender', 'dob', 'parent_phone', 'status']
        rows = [[r['username'], r['name'], r['cname'] or '', r['gender'], r['dob'], r['phone'], r['status'] or 'active'] for r in con.execute(
            "select u.*, c.name as cname from users u left join classes c on c.id = u.class_id where u.role = 'student' order by c.name, u.name")]
    elif name == 'staff':
        h = ['username', 'name', 'role', 'status', 'last_sign_in']
        rows = [[r['username'], r['name'], r['role'], r['status'] or 'active', r['last_login'] or ''] for r in con.execute("select * from users where role != 'student' order by role, name")]
    elif name == 'classes':
        h = ['class', 'category', 'pupils', 'subjects', 'assessment', 'grading']
        rows = []
        for cl in sorted(con.execute('select * from classes').fetchall(), key=class_key):
            a = assess_of(cl)
            rows.append([cl['name'], cl['category'], con.execute("select count(*) from users where role = 'student' and class_id = ?", (cl['id'],)).fetchone()[0],
                         '; '.join(x['name'] for x in get_subjects(con, cl['id'])), '%s + exam %d' % (' + '.join('CA %d' % x for x in a['ca']), a['exam']), cl['grading'] or 'default'])
    elif name == 'scores':
        h = ['class', 'reg_no', 'pupil', 'subject', 'ca1', 'ca2', 'ca3', 'exam', 'total', 'grade']
        rows = []
        for cl in sorted(con.execute('select * from classes').fetchall(), key=class_key):
            sch = scheme_of(settings(con), cl)
            for r in con.execute('select s.*, u.name as pname, u.username as reg, sb.name as sname from scores s join users u on u.id = s.student_id join subjects sb on sb.id = s.subject_id '
                                 'where u.class_id = ? and s.session = ? and s.term = ? order by u.name, sb.pos', (cl['id'], ss, term)):
                t_ = n(r['ca1']) + n(r['ca2']) + n(r['ca3']) + n(r['exam'])
                rows.append([cl['name'], r['reg'], r['pname'], r['sname'], r['ca1'], r['ca2'], r['ca3'], r['exam'], clean(t_), grade_in(sch['bands'], t_)[0]])
    elif name == 'attendance':
        h = ['class', 'reg_no', 'pupil', 'term', 'days_present']
        rows = [[r['cname'] or '', r['username'], r['name'], r['term'], r['present']] for r in con.execute(
            "select r.*, u.name, u.username, c.name as cname from records r join users u on u.id = r.student_id left join classes c on c.id = u.class_id "
            "where r.session = ? and r.present is not null order by c.name, u.name, r.term", (ss,))]
    elif name == 'invoices':
        h = ['invoice_no', 'date', 'reg_no', 'pupil', 'class', 'session', 'term', 'total', 'paid', 'balance', 'status']
        rows = [[i['no'], i['idate'], i['reg'], i['sname'], i['cname'], i['session'], i['term'], i['total'], i['paid'], i['balance'], i['status']]
                for i in (inv_dict(r) for r in con.execute(INV_SQL + 'order by i.idate, i.id'))]
    elif name == 'receipts':
        h = ['receipt_no', 'date', 'type', 'reg_no', 'from', 'category', 'amount', 'method', 'account', 'reference', 'status']
        rows = [[r['no'], r['rdate'], r['kind'], r['reg'] or '', r['sname'] or r['payer'], r['category'], r['amount'], r['method'], r['aname'], r['ref'], r['status']] for r in con.execute(
            'select r.*, u.name as sname, u.username as reg, a.name as aname from receipts r left join users u on u.id = r.student_id left join accounts a on a.id = r.account_id order by r.rdate, r.id')]
    elif name == 'expenses':
        h = ['voucher_no', 'date', 'category', 'paid_to', 'description', 'amount', 'method', 'account', 'reference', 'status']
        rows = [[r['no'], r['edate'], r['category'], r['payee'], r['description'], r['amount'], r['method'], r['aname'], r['ref'], r['status']] for r in con.execute(
            'select e.*, a.name as aname from expenses e left join accounts a on a.id = e.account_id order by e.edate, e.id')]
    elif name == 'debtors':
        h = ['reg_no', 'pupil', 'class', 'parent_phone', 'billed', 'paid', 'balance']
        agg = {}
        for r in con.execute(INV_SQL + "where i.status = 'open'"):
            a = agg.setdefault(r['student_id'], [r['reg'], r['sname'], r['cname'] or '', r['phone'], 0.0, 0.0])
            a[4] += r['total']; a[5] += r['paid']
        rows = sorted(([a[0], a[1], a[2], a[3], round(a[4], 2), round(a[5], 2), round(a[4] - a[5], 2)] for a in agg.values() if a[4] - a[5] > 0.004), key=lambda x: -x[6])
    elif name == 'fee_types':
        h = ['name', 'amount', 'custom']
        rows = [[r['name'], r['amount'], 'yes' if r['custom'] else 'no'] for r in con.execute('select * from fee_types order by custom, name')]
    elif name == 'fee_schedule':
        h = ['class', 'fee', 'amount']
        rows = [[cl['name'], f['l'] or '(blank label)', f['a']] for cl in sorted(con.execute('select * from classes').fetchall(), key=class_key) for f in fees_of(cl) if f['a'] > 0]
    elif name == 'applicants':
        h = ['application_no', 'name', 'gender', 'dob', 'class', 'parent', 'phone', 'email', 'address', 'previous_school', 'status', 'reg_no', 'applied_on']
        rows = [[r['no'], r['name'], r['gender'], r['dob'], r['cname'] or '', r['parent_name'], r['phone'], r['email'], r['address'], r['prev_school'], r['status'], r['reg_no'], r['created']]
                for r in con.execute(APP_SQL + 'order by a.id')]
    else:
        raise ApiError('Unknown data set')
    return h, rows


@route('GET', '/api/export', ('admin', 'staff', 'accountant'))
def r_export(c):
    name = c.q.get('name', '')
    if name not in EXPORT_ROLES or c.user['role'] not in EXPORT_ROLES[name]:
        raise ApiError('You are not allowed to export that', 403)
    fmt = c.q.get('format', 'csv') if c.q.get('format') in ('csv', 'xlsx', 'json', 'tsv') else 'csv'
    h, rows = dataset(c.con, name, current_session(c), term_arg(c.q.get('term', '1')) if c.q.get('term') != 'Y' else 1)
    return to_format(name, h, rows, fmt)


@route('POST', '/api/export/table', ('admin', 'staff', 'accountant'))
def r_export_table(c):
    rows = c.body.get('rows') or []
    if not rows or len(rows) > 20000:
        raise ApiError('Nothing to export')
    fmt = c.body.get('format') if c.body.get('format') in ('csv', 'xlsx', 'json', 'tsv') else 'csv'
    return to_format(str(c.body.get('title') or 'export')[:60], [str(x) for x in rows[0]], [[('' if v is None else v) for v in r] for r in rows[1:]], fmt)


@route('GET', '/api/export/all', ('admin',))
def r_export_all(c):
    import io, zipfile
    buf = io.BytesIO()
    ss = current_session(c)
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in EXPORT_ROLES:
            for term in ((1, 2, 3) if name == 'scores' else (1,)):
                h, rows = dataset(c.con, name, ss, term)
                r = to_format(name, h, rows, 'csv')
                z.writestr('%s%s.csv' % (name, '_term%d' % term if name == 'scores' else ''), r.data)
        z.writestr('README.txt', 'Full data export from the School Result and Accounting Management System on %s.\nOpen the CSV files in Excel or Google Sheets.\n' % date.today().isoformat())
    return Raw(buf.getvalue(), 'application/zip', [('Content-Disposition', 'attachment; filename="school_data_%s.zip"' % date.today().strftime('%Y%m%d'))])


@route('GET', '/api/export/datasets', ('admin', 'staff', 'accountant'))
def r_export_datasets(c):
    return [{'name': k, 'label': EXPORT_LABELS[k]} for k in EXPORT_ROLES if c.user['role'] in EXPORT_ROLES[k]]



# ----------------------------------------------------------------------------- startup
USERS_DDL = ("create table users_new(id integer primary key, username text unique not null collate nocase, name text not null, "
             "role text not null, salt text not null, pw text not null, class_id integer references classes(id), gender text default '', "
             "dob text default '', photo text default '', outstanding real default 0, created text default (datetime('now')), phone text default '', "
             "status text default 'active', last_login text default '')")
USER_COLS = ('id', 'username', 'name', 'role', 'salt', 'pw', 'class_id', 'gender', 'dob', 'photo', 'outstanding', 'created', 'phone', 'status', 'last_login')


def migrate(con):
    """Upgrade a database made by an earlier version."""
    sql = (con.execute("select sql from sqlite_master where type = 'table' and name = 'users'").fetchone() or [''])[0] or ''
    if 'check(rolein' in sql.lower().replace(' ', ''):
        old = [r[1] for r in con.execute('pragma table_info(users)')]
        cols = [x for x in USER_COLS if x in old]
        con.commit()
        con.executescript('begin; ' + USERS_DDL + '; insert into users_new(%s) select %s from users; drop table users; '
                          'alter table users_new rename to users; commit;' % (','.join(cols), ','.join(cols)))
    for tbl, cols in (('scores', (('ca3', 'real'),)), ('classes', (('assess', "text default ''"), ('grading', "text default ''"),
                                                                   ('teacher_name', "text default ''"), ('teacher_sig', "text default ''")))):
        existing = [r[1] for r in con.execute('pragma table_info(%s)' % tbl)]
        for col, ddl in cols:
            if col not in existing:
                con.execute('alter table %s add column %s %s' % (tbl, col, ddl))
    have = [r[1] for r in con.execute('pragma table_info(users)')]
    for col, ddl in (('phone', "text default ''"), ('status', "text default 'active'"), ('last_login', "text default ''")):
        if col not in have:
            con.execute('alter table users add column %s %s' % (col, ddl))
    con.commit()


def init_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('pragma journal_mode = wal')
    con.execute('pragma foreign_keys = off')
    con.executescript(SCHEMA)
    migrate(con)
    if True:
        yr = date.today().year
        first = {'school_name': 'GRACELAND ACADEMY NANDO',
                 'address': 'ALONG ISINYI/IGBARIAM ROAD BESIDE OYE MARKET ANAMBRA EAST L.G , ANAMBRA STATE',
                 'contact': 'gracelandacademy950@gmail.com , 07036183613, 07032440593',
                 'motto': 'EDUCATION FOR EXCELLENCE', 'logo': '', 'session': '%d/%d' % (yr, yr + 1),
                 'yearly_method': 'sample', 'students_view': '1', 'bank_details': '', 'invoice_note': 'Thank you for choosing us.',
                 'reg_prefix': 'GA', 'admissions_open': '0', 'admission_letter': DEFAULT_ADMISSION_LETTER, 'grading_default': 'standard', 'grading_custom': '[]', 'remarks_mode': 'manual', 'remarks_bank': json.dumps(DEFAULT_CT_BANK),
                 'head_bank': json.dumps(DEFAULT_HT_BANK), 'head_name': '', 'head_sig': '', 'sig_mode': 'manual', 'date_mode': 'manual',
                 'layout': json.dumps(DEFAULT_LAYOUT), 'theme': json.dumps(DEFAULT_THEME),
                 'installation_id': '-'.join(secrets.token_hex(2).upper() for _ in range(4)),
                 'trial_start': date.today().isoformat(), 'last_seen': date.today().isoformat()}
        have = settings(con)
        for k, v in first.items():
            if k not in have:
                setv(con, k, v)
    seed_fee_types(con)
    if not con.execute('select 1 from accounts limit 1').fetchone():
        con.execute("insert into accounts(name, kind) values('CASH', 'cash')")
        con.execute("insert into accounts(name, kind) values('BANK', 'bank')")
    if not settings(con).get('recovery_hash'):
        new_recovery_key(con)
    if not con.execute("select 1 from users where role = 'admin'").fetchone():
        salt, h = mkpw('admin123')
        con.execute("insert into users(username, name, role, salt, pw) values('admin', 'Administrator', 'admin', ?, ?)", (salt, h))
        print('First run: sign in as  admin / admin123  and change the password from the menu.')
    if not con.execute('select 1 from classes limit 1').fetchone():
        cid = con.execute('insert into classes(name, category, fees) values(?, ?, ?)',
                          ('NURSERY 1', 'NURSERY', json.dumps([{'l': l, 'a': a} for l, a in FEES]))).lastrowid
        for i, s in enumerate(SUBJECTS):
            con.execute('insert into subjects(class_id, name, pos) values(?, ?, ?)', (cid, s, i))
    con.commit()
    con.close()


def already_running(port):
    """True when this same program already answers on the port (so a second launch just opens the browser)."""
    try:
        import urllib.request as _u
        with _u.urlopen('http://127.0.0.1:%d/api/public' % port, timeout=1.5) as r:
            return 'school' in json.loads(r.read())
    except Exception:
        return False


def main():
    init_db()
    global PORT
    opener = (FROZEN or '--open' in sys.argv) and '--no-browser' not in sys.argv
    srv = None
    for port in range(PORT, PORT + 10):
        if already_running(port):
            print('The system is already running: open http://localhost:%d' % port)
            if opener:
                webbrowser.open('http://localhost:%d' % port)
            return
        try:
            srv = ThreadingHTTPServer(('0.0.0.0', port), H)
            PORT = port
            break
        except OSError:
            continue
    if srv is None:
        print('Could not start: ports %d to %d are all in use by other programs.' % (PORT, PORT + 9))
        return
    if opener:
        threading.Timer(1.2, lambda: webbrowser.open('http://localhost:%d' % PORT)).start()
    srv.daemon_threads = True
    print('School Result and Accounting Management System is running.')
    print('  On this computer:      http://localhost:%d' % PORT)
    for u in lan_urls():
        print('  On other computers:    %s' % u)
    print('Phones and tablets on the same Wi-Fi can open the same addresses in a browser.')
    print('Keep this window open. Press Ctrl+C to stop.')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ----------------------------------------------------------------------------- interface
INDEX_HTML = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>School Result and Accounting Management System</title>
<style>
:root{--navy:#16213e;--gold:#b58a2c;--bg:#eef0f4;--line:#d5d9e2;--red:#c4161c;--ink:#1d2433;--mute:#667085}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1,h2,h3{font-family:Georgia,serif;margin:0;color:var(--navy)}
button,input,select,textarea{font:inherit}
:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
.top{background:var(--navy);color:#fff;padding:10px 16px 0;position:sticky;top:0;z-index:5}
.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{font:700 18px Georgia,serif}.brand small{display:block;font:12px system-ui;color:#c9cfdd;font-weight:400}
.who{display:flex;align-items:center;gap:8px;font-size:13px;color:#c9cfdd;flex-wrap:wrap}
.who select{padding:5px 8px;border-radius:6px;border:1px solid #3a4770;background:#1f2c52;color:#fff}
.who button{background:none;border:1px solid #3a4770;color:#fff;border-radius:6px;padding:5px 10px;cursor:pointer}
nav{display:flex;gap:2px;overflow-x:auto;margin-top:8px}
nav button{background:none;border:0;color:#c9cfdd;padding:9px 14px;cursor:pointer;border-bottom:3px solid transparent;white-space:nowrap}
nav button.on{color:#fff;border-bottom-color:var(--gold);font-weight:600}
main{max-width:1100px;margin:0 auto;padding:18px 14px 30px}
footer{text-align:center;color:var(--mute);font-size:12px;padding:0 12px 24px}
.panel{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:16px}
.tools{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:14px}
.tools label,.fld label{display:flex;flex-direction:column;font-size:12px;color:var(--mute);gap:3px}
select,input[type=text],input[type=password],input[type=number],input[type=date],textarea{padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);min-width:0}
textarea{width:100%}
.btn{background:var(--navy);color:#fff;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;text-decoration:none;display:inline-block}
.btn.alt{background:#fff;color:var(--navy);border:1px solid var(--navy)}
.btn.gold{background:var(--gold)}.btn.danger{background:#a4262c}.btn.sm{padding:4px 9px;font-size:12px}
.btn:disabled{opacity:.45;cursor:default}
.grid{display:grid;gap:12px}.g3{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.stat{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px}
.stat b{display:block;font:700 28px Georgia,serif;color:var(--navy)}
.tw{overflow-x:auto}
table.t{border-collapse:collapse;width:100%;font-size:13px}
table.t th{background:#f3f4f8;text-align:left;font-weight:600;padding:8px;border-bottom:1px solid var(--line)}
table.t td{padding:6px 8px;border-bottom:1px solid #eceef3;vertical-align:middle}
table.t input[type=number]{width:70px}
.empty{padding:30px;text-align:center;color:var(--mute)}
.thumb{width:34px;height:38px;object-fit:cover;border:1px solid var(--line);border-radius:4px;background:#f3f4f8;display:block}
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.fld input,.fld select{width:100%}
#modal{position:fixed;inset:0;background:rgba(10,15,30,.55);display:none;align-items:flex-start;justify-content:center;padding:24px 12px;overflow:auto;z-index:20}
#modal.on{display:flex}
.mbox{background:#fff;border-radius:10px;padding:20px;width:100%;max-width:640px}
.mbox h2{margin-bottom:12px}.mact{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.prevwrap{background:#dfe3ea;border-radius:8px;padding:12px;overflow:hidden}
.prevwrap .sheet{margin:0 auto;box-shadow:0 2px 12px rgba(0,0,0,.2)}
.note{font-size:12px;color:var(--mute);margin-top:6px}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#a4262c;color:#fff;padding:10px 16px;border-radius:8px;display:none;z-index:30;max-width:90vw}
#login{display:none;min-height:100vh;align-items:center;justify-content:center;padding:16px}
.lbox{background:#fff;border:1px solid var(--line);border-radius:10px;padding:26px;width:100%;max-width:380px}
.lbox h1{font-size:22px;margin-bottom:4px}.lbox .fld{margin-top:12px}
.lbox img{height:64px;display:block;margin-bottom:10px}
.err{color:#a4262c;font-size:13px;min-height:18px;margin-top:10px}
/* ===== Report sheet (mirrors the Graceland Academy sample) ===== */
.sheet{width:794px;min-height:1123px;background:#fff;color:#000;font-family:Calibri,Carlito,Arial,sans-serif;font-size:11px;padding:26px 34px;position:relative}
.sheet *{box-sizing:border-box}
.sh-head{display:grid;grid-template-columns:96px 1fr 96px;align-items:center;gap:6px}
.sh-head .mid{text-align:center}
.sh-name{color:var(--red);font:900 27px Arial,Helvetica,sans-serif;letter-spacing:.2px;line-height:1.05}
.sh-addr{font-size:9px;font-weight:700;margin-top:3px}
.sh-con{font-size:11px;margin-top:2px}
.sh-motto{color:var(--red);font-weight:700;font-size:12px;margin-top:3px}
.logo{width:92px;height:80px;object-fit:contain}
.pphoto{width:84px;height:92px;border:1px solid #000;border-radius:6px;object-fit:cover;justify-self:end;background:#fff}
.sh-title{border:1px solid #000;width:76%;margin:10px auto 8px;text-align:center;font-weight:700;font-size:15px;padding:3px 0;letter-spacing:.3px}
.ibox{border:1px solid #000;padding:9px 8px 7px;display:grid;gap:10px}
.irow{display:flex;gap:14px}
.f{display:flex;align-items:flex-end;gap:6px;min-width:0}
.f b{white-space:nowrap;font-size:10.5px}
.f i{flex:1;min-width:20px;border-bottom:1px solid #000;font-style:normal;text-align:center;min-height:14px;font-weight:700;font-size:11px;overflow:hidden;white-space:nowrap}
.ptitle{border:1px solid #000;border-bottom:0;text-align:center;font-weight:700;color:#8b1a1a;font-size:10px;padding:2px;margin:12px 6px 0}
.sheet table{border-collapse:collapse;width:100%}
.sheet th,.sheet td{border:1px solid #000;padding:0 4px;height:20.5px;font-size:10.5px}
.sheet th{font-weight:700;text-align:center;line-height:1.05;font-size:9.5px}
.sheet td.c{text-align:center;font-weight:700}.sheet td.s{font-weight:700}
.ptab{margin:0 6px;width:calc(100% - 12px)!important}
.bot{display:grid;grid-template-columns:1.05fr 1fr 1.05fr;gap:14px;margin-top:16px}
.kb{border:1px solid #000;margin-bottom:10px}
.kb h6{margin:0;color:var(--red);font-size:10px;text-align:center;text-decoration:underline;padding:1px;border-bottom:1px solid #000}
.kb div{font-size:9px;font-weight:700;padding:2px 4px;line-height:1.35}
td.bl{font-weight:700;font-size:10px}
td.bn{font-weight:700}td.bn span:first-child{float:left}td.bn span:last-child{float:right}
.rm{display:flex;align-items:flex-end;gap:8px;margin-top:20px}
.rm b{white-space:nowrap;font-size:11px}
.rm i{flex:1;border-bottom:1px solid #000;font-style:normal;min-height:15px;font-size:11px}
#printRoot{display:none}
:root{--gold2:var(--gold);--card:#fff}
.gnav button,.tnav button{display:inline-flex;align-items:center;gap:6px}
.gnav svg,.tnav svg,.who svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
.who button,.who a.mlink{display:inline-flex;align-items:center;gap:6px}
.sheet .sh-name,.sheet .sh-motto,.sheet .kb h6{color:var(--acc,#c4161c)}
.sheet .ptitle{color:var(--acc,#8b1a1a)}
.sigimg{height:26px;vertical-align:bottom;margin-left:8px;max-width:120px;object-fit:contain}
.qrbox{display:flex;align-items:center;gap:16px;flex-wrap:wrap;border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
.qrbox img{width:176px;height:176px;border:1px solid var(--line);border-radius:6px;background:#fff}
.themes{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.tile{border:2px solid var(--line);border-radius:10px;padding:8px;cursor:pointer;background:var(--card)}.tile.on{border-color:var(--gold)}
.tile i{display:flex;height:26px;border-radius:6px;overflow:hidden}.tile i b{flex:1}.tile span{display:block;font-size:12px;margin-top:6px;color:var(--ink)}
h3>svg,.panel h3 svg,.note svg,.btn svg{width:18px;height:18px;vertical-align:-3px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
.cust h3{margin-bottom:6px}.cust .fgrid{margin-top:8px}
.chk{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink)}.chk input{width:auto}
.stepbox{border-left:4px solid var(--gold);background:#fff9e8;padding:10px 14px;border-radius:6px;font-size:13px;margin:10px 0}
body.dark{--bg:#0e1320;--line:#2b3552;--ink:#e8ebf5;--mute:#9aa4bd;--card:#172033}
body.dark .panel,body.dark .card,body.dark .kpi,body.dark .stat,body.dark .mbox,body.dark .lbox,body.dark .tile{background:var(--card);border-color:var(--line)}
body.dark select,body.dark input,body.dark textarea{background:#0f1626;color:var(--ink);border-color:var(--line)}
body.dark table.t th{background:#1d2740;color:var(--ink);border-color:var(--line)}body.dark table.t td{border-color:var(--line)}
body.dark h1,body.dark h2,body.dark h3,body.dark h4,body.dark .kpi b,body.dark .stat b{color:#fff}
body.dark .btn.alt{background:transparent;color:#fff;border-color:#5b6b95}body.dark .ib{background:var(--card);color:#fff;border-color:var(--line)}
body.dark .trial,body.dark .svc,body.dark .stepbox{background:#2a2411;color:#f3e3a6}body.dark .note{color:var(--mute)}
body.dark .legend,body.dark .hb{color:var(--mute)}body.dark .hb .bar{background:#222d46}
@media(max-width:900px){table.t{display:block;overflow-x:auto;max-width:100%}.tnav button{padding:9px 10px;font-size:13px}}
@media(max-width:700px){
 .top{padding-bottom:0}.gnav{position:fixed;left:0;right:0;bottom:0;background:var(--navy);z-index:30;margin:0;justify-content:space-around;border-top:1px solid rgba(255,255,255,.18);padding-bottom:env(safe-area-inset-bottom)}
 .gnav button{flex-direction:column;gap:1px;font-size:10px;padding:7px 2px 6px;flex:1;text-transform:none;letter-spacing:0;border-bottom:0;border-top:3px solid transparent;opacity:.85;min-width:0}
 .gnav button.on{border-top-color:var(--gold);border-bottom:0;opacity:1;color:#fff}.gnav svg{width:20px;height:20px}
 .tnav button .tl{display:none}.tnav button.on .tl{display:inline}.tnav button{padding:9px 12px}.tnav svg{width:18px;height:18px}
 main{padding-bottom:86px}footer{padding-bottom:84px}.who .bt{display:none}.who button,.who a.mlink{padding:6px 8px}.who{gap:6px}
 .brand{max-width:100%}.cookiebar{bottom:66px}.qrbox img{width:150px;height:150px}.themes{grid-template-columns:repeat(2,1fr)}
 .badge{position:absolute;margin:-6px 0 0 8px}.gnav button{position:relative}
}
@media(max-width:380px){.kpis{grid-template-columns:1fr}.brand small{display:none}#sessSel{max-width:92px}}
@media(min-width:1500px){main{max-width:1380px}}
.ib{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;padding:0;border-radius:6px;border:1px solid var(--line);background:#fff;color:var(--navy);cursor:pointer;vertical-align:middle;margin:0 2px 2px 0}
.ib:hover{background:#f3f4f8}.ib.danger{color:#a4262c;border-color:#e3b5b8}.ib.gold{color:#8b6a1b;border-color:#e5c76b}
.ib svg,.kpi .ico svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:13px;display:flex;gap:11px;align-items:center;min-width:0}
.kpi .ico{width:40px;height:40px;border-radius:10px;display:grid;place-items:center;flex:none}.kpi .ico svg{width:20px;height:20px}
.kpi b{display:block;font:700 21px Georgia,serif;color:var(--navy);line-height:1.1;overflow-wrap:anywhere}.kpi small{color:var(--mute);font-size:12px;line-height:1.2;display:block}
.cgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:14px;margin-bottom:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;min-width:0}.card h4{margin:0 0 8px;font:700 14px Georgia,serif;color:var(--navy);display:flex;justify-content:space-between;gap:8px;align-items:center}
.card h4 select{font-size:12px;padding:3px 6px}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--mute);margin-top:6px}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}
.donut{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.donut svg{width:150px;height:150px;flex:none}
.hb{display:grid;grid-template-columns:minmax(80px,38%) 1fr 52px;gap:8px;align-items:center;font-size:12px;margin:5px 0}.hb .bar{background:#eef1f8;border-radius:5px;height:12px}.hb .bar i{display:block;height:100%;border-radius:5px;background:var(--navy)}
.hb span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hb span:last-child{text-align:right;font-weight:600}
.empty-chart{color:var(--mute);font-size:13px;padding:30px 0;text-align:center}
.msgrow{cursor:pointer}.msgrow.unread td{font-weight:700;background:#fffaf0}
.badge{background:#c4161c;color:#fff;border-radius:99px;font-size:11px;padding:1px 7px;margin-left:6px}
.pill{display:inline-block;border-radius:99px;padding:1px 9px;font-size:11px;font-weight:600;background:#e9ecf3;color:#445}.pill.ok{background:#d6f1de;color:#146c2e}.pill.bad{background:#fbdada;color:#8a1c1c}.pill.gold{background:#fff0c9;color:#7a5a00}
.msgbody{white-space:pre-wrap;background:#f7f8fb;border:1px solid var(--line);border-radius:8px;padding:12px;margin-top:10px;max-height:50vh;overflow:auto}
.pwshow{font:700 26px ui-monospace,Menlo,Consolas,monospace;letter-spacing:1px;background:#f3ecda;border:1px dashed var(--gold);border-radius:8px;padding:14px;text-align:center;margin:10px 0;user-select:all}
.cookiebar{position:fixed;left:0;right:0;bottom:0;background:#16213e;color:#e5e9f5;padding:10px 14px;font-size:13px;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;z-index:40}
.cookiebar a{color:#f1d594}.cookiebar button{background:var(--gold);color:#fff;border:0;border-radius:6px;padding:6px 14px;cursor:pointer}
.lfoot{font-size:12px;color:var(--mute);margin-top:12px;text-align:center}.lfoot a{color:var(--mute);margin:0 5px}
footer a{color:var(--mute)}
.svc{border:1px solid #e5c76b;background:#fff9e8;border-radius:8px;padding:12px 14px;font-size:13px}
@media(max-width:700px){
 body{font-size:14px}main{padding:12px 10px 24px}.panel{padding:12px}.top{padding:8px 10px 0}.brand{font-size:15px}.brand small{font-size:11px}
 .who{width:100%;justify-content:space-between}.who .mlink{display:none}
 nav button{padding:8px 11px;font-size:13px}.gnav button{padding:6px 10px!important}
 .tools>*{flex:1 1 130px}.tools .btn{text-align:center}
 .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.kpi{padding:10px;gap:8px}.kpi .ico{width:32px;height:32px}.kpi b{font-size:17px}
 .cgrid{grid-template-columns:1fr}.donut svg{width:120px;height:120px}
 #modal{padding:8px 4px}.mbox{padding:14px;border-radius:8px}.mbox.wide{max-width:100%}.mact{flex-wrap:wrap}.mact .btn{flex:1}
 table.t th,table.t td{padding:6px 6px;font-size:12.5px}.hb{grid-template-columns:90px 1fr 46px}
 .lbox{padding:20px}
}

nav{display:block}.gnav,.tnav{display:flex;gap:2px;overflow-x:auto}
.gnav button{font-size:12px;text-transform:uppercase;letter-spacing:.5px;padding:6px 14px;opacity:.8}
.gnav button.on{opacity:1;color:var(--gold);border-bottom-color:var(--gold)}
.tnav button.on{border-bottom-color:#fff}
.who a.mlink{color:#fff;border:1px solid #3a4770;border-radius:6px;padding:5px 10px;text-decoration:none;font-size:13px}
/* ---- left side menu: laptops, desktops and tablets ---- */
.shell{display:block}#side{display:none}
@media(min-width:701px){
 #nav{display:none}
 .top{padding-bottom:10px}
 .shell{display:flex;align-items:flex-start}
 #side{display:block;flex:0 0 218px;width:218px;position:sticky;top:var(--hh,64px);height:calc(100vh - var(--hh,64px));overflow-y:auto;background:var(--navy);color:#fff;padding:10px 8px 24px;box-sizing:border-box}
 #side .sg{margin-bottom:8px}
 #side .sh{display:flex;align-items:center;gap:8px;font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--gold);padding:10px 10px 4px}
 #side .sh svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
 #side button{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:none;border:0;border-left:3px solid transparent;color:#d3d9e8;padding:9px 10px;border-radius:0 8px 8px 0;font-size:13.5px;cursor:pointer;position:relative}
 #side button svg{width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
 #side button:hover{background:rgba(255,255,255,.08);color:#fff}
 #side button.on{background:rgba(255,255,255,.14);color:#fff;border-left-color:var(--gold);font-weight:600}
 #side .badge{margin-left:auto}
 .shell main{flex:1;min-width:0;margin:0 auto}
 main{padding-bottom:30px}footer{padding-bottom:16px}
}
@media(min-width:701px) and (max-width:1000px){#side{flex-basis:184px;width:184px;padding:8px 6px}#side button{font-size:13px;padding:8px 8px;gap:8px}}
@media(max-width:700px){#side{display:none!important}}
@media print{#side{display:none!important}.shell{display:block}}

.trial{background:#fff4d6;border:1px solid #e5c76b;color:#5c4400;border-radius:8px;padding:9px 14px;margin-bottom:14px}
.trial.warn{background:#fde8e8;border-color:#e59b9b;color:#7a1414}.trial a{color:inherit;font-weight:700}
.mbox.wide{max-width:900px}
.sheet.d1 th,.sheet.d1 td{height:18px}.sheet.d2 th,.sheet.d2 td{height:15.5px}
.doc{width:794px;min-height:600px;background:#fff;color:#000;font:12px/1.4 Arial,Helvetica,sans-serif;padding:34px 40px;position:relative}
.doc.rep{width:794px;min-height:0}
.dh{display:flex;gap:14px;align-items:center;border-bottom:2px solid #8b1a1a;padding-bottom:10px;margin-bottom:12px}
.dh img,.dh svg{width:84px;height:72px;object-fit:contain}
.dn{color:var(--red);font:900 22px Arial,sans-serif;line-height:1.1}.da{font-size:10.5px;font-weight:700}
.dt{font:700 18px Georgia,serif;text-align:center;letter-spacing:1px;margin:6px 0 12px;border:1px solid #000;padding:4px}
.doc table{border-collapse:collapse;width:100%}
.doc th,.doc td{border:1px solid #000;padding:4px 6px;text-align:left}.doc th{background:#f0f0f0}
.doc td.r,.doc th.r{text-align:right}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:4px 24px;margin-bottom:10px}.meta b{display:inline-block;min-width:96px}
.stamp{position:absolute;right:60px;top:210px;border:4px solid #1a7a3a;color:#1a7a3a;font:900 34px Arial;padding:2px 14px;transform:rotate(-14deg);opacity:.35}
.stamp.void{border-color:#a4262c;color:#a4262c}
.sig{display:flex;justify-content:space-between;margin-top:46px}.sig div{border-top:1px solid #000;width:36%;text-align:center;padding-top:3px;font-size:11px}
@media print{
  @page{size:A4;margin:0}
  body{background:#fff}
  #app,#login,#modal,#toast{display:none!important}
  #printRoot{display:block}
  #printRoot .page{width:210mm;height:297mm;overflow:hidden;page-break-after:always}
  #printRoot .page:last-child{page-break-after:auto}
  #printRoot .free{height:auto;padding:6mm;font:11px Arial}
  #printRoot .free .doc.rep{width:auto}
  .sheet{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
</style></head>
<body>
<div id="login"><form class="lbox" onsubmit="doLogin(event)">
  <div id="lgLogo"></div><h1 id="lgName">School</h1><div class="note">School Result and Accounting Management System</div>
  <div class="fld"><label>Username or Reg No<input type="text" id="lu" autocomplete="username" autofocus></label></div>
  <div class="fld"><label>Password<input type="password" id="lp" autocomplete="current-password"></label></div>
  <div class="err" id="lerr"></div>
  <button class="btn" style="width:100%;margin-top:6px">Sign in</button>
  <p class="note">Pupils: your first password is your Reg No.</p>
  <p class="note"><a href="#" onclick="forgotModal();return false">Forgot password?</a> &middot; <a href="#" onclick="showQR();return false">Connect a phone (QR code)</a></p>
  <div class="lfoot"><a href="/legal/privacy" target="_blank">Privacy</a>&middot;<a href="/legal/terms" target="_blank">Terms</a>&middot;<a href="/legal/cookies" target="_blank">Cookies</a>&middot;<a href="/legal/eula" target="_blank">Licence</a></div>
</form></div>
<div id="app" style="display:none">
  <div class="top"><div class="bar"><div class="brand">School Result and Accounting System<small id="schoolLine"></small></div>
    <div class="who"><span id="whoName"></span><select id="sessSel" title="Session" onchange="S.session=this.value;render()"></select><span id="hdrBtns" style="display:contents"></span></div></div>
    <nav id="nav"></nav></div>
  <div class="shell"><aside id="side" aria-label="Main menu"></aside>
  <main id="view"></main></div>
  <footer>OKV Technology Consults &middot; www.okvtechnology.com &middot; technologyokv@gmail.com &middot; WhatsApp +234 810 414 1138<br>Need help installing or training your staff? OKV offers installation services. <a href="mailto:technologyokv@gmail.com?subject=Installation%20service">Ask for a quote</a><br><a href="/legal/privacy" target="_blank">Privacy</a> &middot; <a href="/legal/terms" target="_blank">Terms</a> &middot; <a href="/legal/cookies" target="_blank">Cookies</a> &middot; <a href="/legal/eula" target="_blank">Licence agreement</a></footer>
</div>
<div id="modal"></div><div id="toast"></div><div id="printRoot"></div>

<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const enc=encodeURIComponent;
const nz=v=>v==null?'':v;
const TN=['','FIRST','SECOND','THIRD'];
const MAX={a:20,b:20,e:60};
const money=n=>Number(n).toLocaleString('en-NG');
const fdate=d=>{if(!d)return'';const a=d.split('-');return a.length===3?a[2]+'/'+a[1]+'/'+a[0]:d};
let S={user:null,session:'',sessions:[],domains:[],page:'dash',classes:[],cid:null,t:1,sid:null,mode:'subj',si:null};
let D={};

/* ---------- api ---------- */
async function api(path,body){
  const o=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  const r=await fetch('/api/'+path,o);let d={};try{d=await r.json()}catch(e){}
  if(!r.ok){if(r.status===401&&path!=='login'){showLogin();throw new Error('')}if(r.status===402&&S.lic&&S.lic.state!=='expired'){S.lic.state='expired';render();throw new Error('')}throw new Error(d.error||'Request failed')}
  return d;
}
function toast(m,ok){const t=$('#toast');t.style.background=ok?'#16213e':'#a4262c';t.textContent=m;t.style.display='block';clearTimeout(toast.t);toast.t=setTimeout(()=>t.style.display='none',4500)}
window.addEventListener('unhandledrejection',e=>{e.preventDefault();if(e.reason&&e.reason.message)toast(e.reason.message)});

/* ---------- login / boot ---------- */
async function showLogin(){
  $('#app').style.display='none';$('#login').style.display='flex';cookieBar();
  try{const p=await api('public');S.theme=p.theme;applyTheme();$('#lgName').textContent=p.school;$('#lgLogo').innerHTML=p.logo?`<img src="${p.logo}">`:''}catch(e){}
}
async function doLogin(e){
  e.preventDefault();$('#lerr').textContent='';
  try{await api('login',{username:$('#lu').value,password:$('#lp').value});$('#lp').value='';await boot()}
  catch(x){$('#lerr').textContent=x.message}
}
async function logout(){try{await api('logout',{})}catch(e){}S.user=null;showLogin()}
async function boot(){
  let m;try{m=await api('me')}catch(e){return}
  S.user=m.user;S.session=m.session;S.sessions=m.sessions;S.domains=m.domains;S.release=m.students_view;S.lic=m.lic;S.info=m.info;S.presets=m.presets;S.unread=m.unread;lastUnread=m.unread;S.theme=m.theme;applyTheme();buildHeader();if(m.recovery_pending)setTimeout(recoveryModal,700);if(!window._poll)window._poll=setInterval(pollMsgs,30000);$('#upg').style.display=(m.user.role==='admin'&&m.lic&&m.lic.state==='trial')?'':'none';setTimeout(trialModal,1500);
  $('#login').style.display='none';$('#app').style.display='block';document.querySelectorAll('.cookiebar').forEach(e=>e.remove());
  $('#schoolLine').textContent=m.school;$('#whoName').textContent=m.user.name;
  $('#sessSel').innerHTML=m.sessions.map(x=>`<option ${x===S.session?'selected':''}>${esc(x)}</option>`).join('');
  $('#sessSel').style.display=m.user.role==='student'?'none':'';
  S.page={student:'results',accountant:'fdash'}[m.user.role]||'dash';S.t=m.user.role==='student'?1:S.t;
  render();
}

/* ---------- shell ---------- */
const PAGES={admissions:pAdmissions,data:pData,customize:pCustomize,dash:pDash,students:pStudents,classes:pClasses,scores:pScores,details:pDetails,reports:pReports,board:pBoard,settings:pSettings,results:pResults,users:pUsers,msgs:pMsgs,
  fdash:pFDash,clearance:pClearance,fees:pFees,invoices:pInvoices,receipts:pReceipts,expenses:pExpenses,debtors:pDebtors,cash:pCash,freports:pFReports,license:pLicense};
function go(p){S.page=p;render()}
function openModal(h,wide){$('#modal').innerHTML=`<div class="mbox${wide?' wide':''}">${h}</div>`;$('#modal').classList.add('on');decorateActions(document.getElementById('modal'))}
function closeModal(){$('#modal').classList.remove('on')}
function ask(msg,fn){window._ask=fn;openModal(`<h2>Please confirm</h2><p>${esc(msg)}</p><div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn danger" onclick="closeModal();window._ask()">Yes, continue</button></div>`)}
async function loadClasses(){S.classes=await api('classes');if(!S.classes.find(c=>c.id===S.cid))S.cid=S.classes[0]&&S.classes[0].id;return S.classes.find(c=>c.id===S.cid)}
const classSel=()=>`<label>Class<select onchange="S.cid=+this.value;S.sid=null;render()">${S.classes.map(c=>`<option value="${c.id}" ${c.id===S.cid?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>`;
const termSel=y=>`<label>Term<select onchange="S.t=this.value==='Y'?'Y':+this.value;render()">${[1,2,3].map(x=>`<option value="${x}" ${S.t===x?'selected':''}>${TN[x]} term</option>`).join('')}${y?`<option value="Y" ${S.t==='Y'?'selected':''}>Yearly cumulative</option>`:''}</select></label>`;
const noClass='<div class="panel empty">Add a class first.</div>';
function imgToData(file,max,type,cb){if(!file)return;const fr=new FileReader();fr.onload=()=>{const im=new Image();im.onload=()=>{const k=Math.min(1,max/Math.max(im.width,im.height)),c=document.createElement('canvas');c.width=im.width*k;c.height=im.height*k;c.getContext('2d').drawImage(im,0,0,c.width,c.height);cb(c.toDataURL(type,.85))};im.src=fr.result};fr.readAsDataURL(file)}
function pwForm(){openModal(`<h2>Change password</h2><div class="fgrid"><div class="fld"><label>Current password<input type="password" id="p0"></label></div><div class="fld"><label>New password<input type="password" id="p1"></label></div></div><div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="savePw()">Save password</button></div>`)}
async function savePw(){await api('password',{old:$('#p0').value,new:$('#p1').value});closeModal();toast('Password changed',true)}

/* ---------- report sheet ---------- */
const SIL='<svg viewBox="0 0 84 92" class="pphoto" xmlns="http://www.w3.org/2000/svg"><rect x=".5" y=".5" width="83" height="91" rx="6" fill="#fff" stroke="#000"/><circle cx="42" cy="34" r="17" fill="#000"/><path d="M10 88c2-22 16-30 32-30s30 8 32 30z" fill="#000"/></svg>';
const CREST='<svg viewBox="0 0 92 80" class="logo" xmlns="http://www.w3.org/2000/svg"><path d="M46 4 84 14v28c0 18-16 30-38 36C24 72 8 60 8 42V14z" fill="#fff" stroke="#8b1a1a" stroke-width="3"/><path d="M46 20v38M28 34h36" stroke="#8b1a1a" stroke-width="4"/></svg>';
function printHTML(h){$('#printRoot').innerHTML=h;setTimeout(()=>window.print(),60)}
function fitPreview(){document.querySelectorAll('.prevwrap').forEach(w=>{const e=w.firstElementChild;if(e)e.style.zoom=Math.min(1,(w.clientWidth-24)/794)})}
window.addEventListener('resize',fitPreview);

/* ---------- dashboard ---------- */
/* ---------- pupils ---------- */
async function pStudents(){
  const cl=await loadClasses();if(!cl)return noClass;
  D.students=await api('students?class='+cl.id);const fin=S.user.role==='admin';
  return `<div class="panel"><div class="tools">${classSel()}<button class="btn" onclick="studForm()">Add pupil</button><button class="btn alt" onclick="importForm()">Import list</button>
  <label>Move selected pupils to<select id="mvc"><option value="">Choose class</option>${S.classes.filter(c=>c.id!==cl.id).map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label><button class="btn alt" onclick="moveSel()">Move</button></div>
  ${D.students.length?`<div class="tw"><table class="t"><tr><th></th><th></th><th>Reg No</th><th>Name</th><th>Gender</th><th>Date of birth</th><th>Parent phone</th><th></th></tr>${D.students.map(s=>`<tr><td><input type="checkbox" class="mv" value="${s.id}"></td><td>${s.photo?`<img class="thumb" src="${s.photo}">`:'<div class="thumb"></div>'}</td><td>${esc(s.reg_no)}</td><td>${esc(s.name)}</td><td>${esc(s.gender)}</td><td>${esc(fdate(s.dob))}</td><td>${esc(s.phone)}</td><td style="white-space:nowrap"><button class="btn alt sm" onclick="studForm(${s.id})">Edit</button> <button class="btn alt sm" onclick="S.sid=${s.id};S.t=1;go('reports')">Sheet</button>${fin?` <button class="btn alt sm" onclick="stmt(${s.id})">Statement</button>`:''} <button class="btn alt sm" onclick="resetPw(${s.id})">Reset password</button> <button class="btn danger sm" onclick="delStud(${s.id})">Delete</button></td></tr>`).join('')}</table></div>`:'<div class="empty">No pupils in this class yet.</div>'}</div>`;
}
async function moveSel(){const ids=[...document.querySelectorAll('.mv:checked')].map(x=>+x.value),to=$('#mvc').value;if(!ids.length)throw new Error('Tick the pupils to move');if(!to)throw new Error('Choose the class to move to');await api('students/move',{ids,class_id:+to});toast(ids.length+' pupils moved',true);render()}
let tmpPhoto=null;
function studForm(id){
  const s=id?D.students.find(x=>x.id===id):{name:'',reg_no:'',gender:'',dob:'',outstanding:'',phone:'',class_id:S.cid};tmpPhoto=null;
  openModal(`<h2>${id?'Edit pupil':'Add pupil'}</h2><div class="fgrid">
  <div class="fld"><label>Full name<input type="text" id="sn" value="${esc(s.name)}"></label></div>
  <div class="fld"><label>Reg No ${id?'':'(leave empty to generate)'}<input type="text" id="sr" value="${esc(s.reg_no)}"></label></div>
  <div class="fld"><label>Class<select id="sc">${S.classes.map(c=>`<option value="${c.id}" ${c.id===s.class_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Gender<select id="sg"><option value=""></option><option ${s.gender==='MALE'?'selected':''}>MALE</option><option ${s.gender==='FEMALE'?'selected':''}>FEMALE</option></select></label></div>
  <div class="fld"><label>Date of birth<input type="date" id="sd" value="${esc(s.dob)}"></label></div>
  <div class="fld"><label>Parent phone<input type="text" id="sp" value="${esc(s.phone||'')}"></label></div>
  <div class="fld"><label>Outstanding bill (₦), used only until the pupil has invoices<input type="number" id="so" min="0" value="${esc(s.outstanding||'')}"></label></div>
  <div class="fld"><label>Passport photo<input type="file" accept="image/*" onchange="imgToData(this.files[0],220,'image/jpeg',d=>tmpPhoto=d)"></label></div></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="saveStud(${id||0})">Save pupil</button></div>`);
}
async function saveStud(id){
  const b={name:$('#sn').value,reg_no:$('#sr').value,class_id:+$('#sc').value,gender:$('#sg').value,dob:$('#sd').value,outstanding:$('#so').value,phone:$('#sp').value};
  if(id)b.id=id;if(tmpPhoto!==null)b.photo=tmpPhoto;
  await api('students',b);S.cid=b.class_id;closeModal();render();
}
function delStud(id){ask('Delete this pupil and all of their results?',async()=>{await api('students/delete',{id});render()})}
async function resetPw(id){const r=await api('students/resetpw',{id});openModal(`<h2>Password reset</h2><p>The password is now the Reg No: <b>${esc(r.reg_no)}</b></p><div class="mact"><button class="btn" onclick="closeModal()">OK</button></div>`)}
/* ---------- classes & subjects ---------- */
async function pClasses(){
  await loadClasses();
  return `<div class="panel"><div class="tools"><button class="btn" onclick="classForm()">Add class</button><button class="btn alt" onclick="stdClasses()">Add standard classes (KG to SS 3)</button></div>
  <div class="tw"><table class="t"><tr><th>Class</th><th>Category on sheet</th><th>Subjects</th><th>Pupils</th><th></th></tr>${S.classes.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.category)}</td><td>${c.subjects.length}</td><td>${c.pupils}</td><td><button class="btn alt sm" onclick="classForm(${c.id})">Edit</button> <button class="btn danger sm" onclick="delClass(${c.id})">Delete</button></td></tr>`).join('')}</table></div>
  <p class="note">School fees for each class are set under Accounting, Fee schedule.</p></div>`;
}
function stdClasses(){ask('Create KG 1-2, Nursery 1-2, Primary 1-6, JSS 1-3 and SS 1-3 with a starter subject list each? Classes that already exist are left alone.',async()=>{const r=await api('classes/standard',{});toast(r.made+' classes added',true);render()})}
function delClass(id){ask('Delete this class and its subjects?',async()=>{await api('classes/delete',{id});render()})}

/* ---------- score entry ---------- */
const pend={};let tmr=null;
/* ---------- attendance & remarks ---------- */
async function pDetails(){
  if(S.t==='Y')S.t=3;
  const cl=await loadClasses();if(!cl)return noClass;
  const d=await api(`records?class=${cl.id}&term=${S.t}&session=${enc(S.session)}`);D=d;
  const m=d.meta;
  let h=`<div class="panel"><div class="tools">${classSel()}${termSel(false)}</div><h3>Term dates, ${TN[S.t].toLowerCase()} term ${esc(S.session)}</h3><div class="fgrid" style="margin-top:10px">
  <div class="fld"><label>No of times school opened<input type="number" min="0" value="${nz(m.opened)}" onchange="setMeta('opened',this.value)"></label></div>
  <div class="fld"><label>Closing date<input type="date" value="${esc(m.closing)}" onchange="setMeta('closing',this.value)"></label></div>
  <div class="fld"><label>Resumption date<input type="date" value="${esc(m.resumption)}" onchange="setMeta('resumption',this.value)"></label></div></div><p class="note">These apply to every class in the school for this term.</p></div>`;
  if(!d.students.length)return h+'<div class="panel empty">No pupils in this class yet.</div>';
  if(!d.students.find(s=>s.id===S.sid))S.sid=d.students[0].id;
  const l=d.students,i=l.findIndex(s=>s.id===S.sid),r=d.records[S.sid]||{present:null,domains:{},ct:'',ht:'',date:''};
  h+=`<div class="panel"><div class="tools"><label>Pupil<select onchange="S.sid=+this.value;render()">${l.map(s=>`<option value="${s.id}" ${s.id===S.sid?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
  <button class="btn alt" ${i?'':'disabled'} onclick="S.sid=${(l[i-1]||{}).id};render()">Previous</button><button class="btn alt" ${i<l.length-1?'':'disabled'} onclick="S.sid=${(l[i+1]||{}).id};render()">Next</button></div>
  <div class="fgrid"><div class="fld"><label>No of times present<input type="number" min="0" value="${nz(r.present)}" onchange="setRec('present',this.value)"></label></div>
  <div class="fld"><label>Date on sheet<input type="date" value="${esc(r.date)}" onchange="setRec('rdate',this.value)"></label></div></div>
  <h3 style="margin:16px 0 8px">Domains (5 excellent to 1 very poor)</h3><div class="fgrid">${S.domains.map((x,k)=>`<div class="fld"><label>${esc(x)}<select onchange="setDom(${k},this.value)">${['',5,4,3,2,1].map(v=>`<option ${String(v)===String(r.domains[x]||'')?'selected':''}>${v}</option>`).join('')}</select></label></div>`).join('')}</div>
  <div class="fld" style="margin-top:14px"><label>Class teacher's remark<textarea rows="2" onchange="setRec('ct',this.value)">${esc(r.ct)}</textarea></label></div>
  <div class="fld" style="margin-top:10px"><label>Head teacher's remark<textarea rows="2" onchange="setRec('ht',this.value)">${esc(r.ht)}</textarea></label></div></div>`;
  return h;
}
async function setMeta(f,v){await api('term',{term:S.t,session:S.session,field:f,value:v})}
async function setRec(f,v){await api('record',{student_id:S.sid,term:S.t,session:S.session,field:f,value:v})}
async function setDom(k,v){await api('record',{student_id:S.sid,term:S.t,session:S.session,field:'domain',name:S.domains[k],value:v})}

/* ---------- report sheets ---------- */
async function pReports(){
  const cl=await loadClasses();if(!cl)return noClass;
  const l=await api('students?class='+cl.id);
  if(!l.length)return `<div class="panel"><div class="tools">${classSel()}</div><div class="empty">Add pupils to this class to see their report sheets.</div></div>`;
  if(!l.find(s=>s.id===S.sid))S.sid=l[0].id;
  const i=l.findIndex(s=>s.id===S.sid);
  const d=await api(`sheet?student=${S.sid}&term=${S.t}&session=${enc(S.session)}`);
  return `<div class="panel"><div class="tools">${classSel()}${termSel(true)}<label>Pupil<select onchange="S.sid=+this.value;render()">${l.map(s=>`<option value="${s.id}" ${s.id===S.sid?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
  <button class="btn alt" ${i?'':'disabled'} onclick="S.sid=${(l[i-1]||{}).id};render()">Previous</button><button class="btn alt" ${i<l.length-1?'':'disabled'} onclick="S.sid=${(l[i+1]||{}).id};render()">Next</button>
  <button class="btn gold" onclick="printOne()">Print or save as PDF</button><button class="btn" onclick="printClass()">Print whole class</button></div>
  <div class="prevwrap" id="pw">${sheetHTML(d)}</div><p class="note">In the print window choose A4, margins none, and turn on background graphics. Pick "Save as PDF" as the printer to get a file.</p></div>`;
}
async function printOne(){const d=await api(`sheet?student=${S.sid}&term=${S.t}&session=${enc(S.session)}`);printHTML(`<div class="page">${sheetHTML(d)}</div>`)}
async function printClass(){const a=await api(`sheets?class=${S.cid}&term=${S.t}&session=${enc(S.session)}`);printHTML(a.map(d=>`<div class="page">${sheetHTML(d)}</div>`).join(''))}

/* ---------- broadsheet ---------- */
async function pBoard(){
  const cl=await loadClasses();if(!cl)return noClass;
  const d=await api(`broadsheet?class=${cl.id}&term=${S.t}&session=${enc(S.session)}`);
  const table=`<table class="t" style="min-width:700px"><tr><th>Pupil</th>${d.subjects.map(s=>`<th style="text-align:center;font-size:11px">${esc(s)}</th>`).join('')}<th>Total</th><th>Avg</th><th>Pos</th></tr>${d.rows.map(r=>`<tr><td>${esc(r.name)}</td>${r.vals.map(v=>`<td style="text-align:center">${v}</td>`).join('')}<td style="text-align:center"><b>${r.total}</b></td><td style="text-align:center">${r.avg.toFixed(2)}</td><td style="text-align:center">${esc(r.pos)}</td></tr>`).join('')}</table>`;
  window._board=`<div class="free"><h2 style="font-family:Georgia">${esc($('#schoolLine').textContent)}</h2><p>${esc(d.cls)} broadsheet, ${S.t==='Y'?'yearly cumulative':TN[S.t]+' term'}, ${esc(d.session)}</p>${table.replace('class="t"','style="border-collapse:collapse;width:100%;font-size:9px" border="1"')}</div>`;
  return `<div class="panel"><div class="tools">${classSel()}${termSel(true)}<button class="btn alt" onclick="printHTML(window._board)">Print</button></div>${d.rows.length?`<div class="tw">${table}</div>`:'<div class="empty">No pupils in this class yet.</div>'}</div>`;
}

/* ---------- settings (admin) ---------- */
async function pSettings(){
  const s=await api('settings');
  const f=(k,l)=>`<div class="fld"><label>${l}<input type="text" value="${esc(s[k])}" onchange="saveSet('${k}',this.value)"></label></div>`;
  return `<div class="panel"><h3>School details on the sheet</h3><div class="fgrid" style="margin-top:10px">${f('school_name','School name')}${f('address','Address line')}${f('contact','Email and phone line')}${f('motto','Motto (MOTTO: is added for you)')}
  <div class="fld"><label>School crest<input type="file" accept="image/*" onchange="imgToData(this.files[0],300,'image/png',d=>saveSet('logo',d,true))"></label></div></div>
  ${s.logo?`<p><img src="${s.logo}" style="height:60px"> <button class="btn alt sm" onclick="saveSet('logo','',true)">Remove crest</button></p>`:''}</div>
  <div class="panel"><h3>Session and results</h3><div class="fgrid" style="margin-top:10px">${f('session','Current session, for example 2026/2027')}
  <div class="fld"><label>Pupils can see their results<select onchange="saveSet('students_view',this.value)"><option value="1" ${s.students_view==='1'?'selected':''}>Yes</option><option value="0" ${s.students_view!=='1'?'selected':''}>No, hold results back</option></select></label></div>
  <div class="fld"><label>Yearly sheet overall average<select onchange="saveSet('yearly_method',this.value)"><option value="sample" ${s.yearly_method==='sample'?'selected':''}>Same as your sample (overall total ÷ subjects)</option><option value="true" ${s.yearly_method==='true'?'selected':''}>Out of 100 (overall total ÷ subjects ÷ 3)</option></select></label></div></div>
  <p class="note">Your sample yearly sheet shows 192 total and 16.00 average, which is the total divided by 12 subjects.</p></div>
  <div class="panel"><h3>Invoices and receipts</h3><div class="fld" style="margin-top:10px"><label>Bank details printed on invoices<textarea rows="3" onchange="saveSet('bank_details',this.value)">${esc(s.bank_details)}</textarea></label></div><div class="fld" style="margin-top:10px"><label>Note at the bottom of invoices<input type="text" value="${esc(s.invoice_note)}" onchange="saveSet('invoice_note',this.value)"></label></div></div>
  <div class="panel"><h3>Open on phones and other computers</h3><p class="note" style="font-size:13px">Staff, parents and pupils open one of these addresses in a browser on the same Wi-Fi or network. Phones and tablets work the same way. The QR code only opens the web address; everyone still signs in with their own username and password.</p><p><b>${s.urls.length?s.urls.map(esc).join('<br>'):'Connect this computer to the school network to see the address.'}</b></p><div class="tools"><button class="btn gold" onclick="showQR()">Show QR code</button><button class="btn alt" onclick="showQR('/apply')">QR for the online admission form</button></div></div>
  <div class="panel"><h3>Administrator recovery key</h3><p class="note" style="margin-bottom:10px">If you forget the administrator password, the recovery key lets you set a new one from the sign-in page (Forgot password). Create a new key if the old one is lost.</p><button class="btn alt" onclick="regenKey()">Create a new recovery key</button></div>
  <div class="panel"><h3>Backup</h3><p class="note" style="margin-bottom:10px">Download the database regularly. To restore, stop the server and replace school_system.db with the backup file (renamed).</p><a class="btn" href="/api/backup">Download backup</a></div>`;
}
async function saveSet(k,v,rerender){const b={};b[k]=v;await api('settings',b);if(k==='session'||k==='school_name'){const m=await api('me');S.session=m.session;S.sessions=m.sessions;$('#schoolLine').textContent=m.school;$('#sessSel').innerHTML=m.sessions.map(x=>`<option ${x===S.session?'selected':''}>${esc(x)}</option>`).join('')}if(rerender||k==='session')render()}

/* ======================= accounting ======================= */
const F={};
const NF=n=>Number(n||0).toLocaleString('en-NG',{minimumFractionDigits:2,maximumFractionDigits:2});
const termLbl=t=>t?TN[t].charAt(0)+TN[t].slice(1).toLowerCase()+' term':'No term';
const today=()=>{const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')};
const monthStart=()=>today().slice(0,8)+'01';
const EXP_CATS=['SALARIES','UTILITIES','MAINTENANCE','STATIONERY','TRANSPORT','FUEL','EXAMINATION','FEEDING','OTHER'];
const INC_CATS=['UNIFORM SALES','BOOK SALES','FORM SALES','DONATION','OTHER'];
const ONES=['','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen'];
const TENS=['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety'];
function w3(n){let s='';if(n>=100){s+=ONES[Math.floor(n/100)]+' hundred';n%=100;if(n)s+=' and '}if(n>=20){s+=TENS[Math.floor(n/10)];if(n%10)s+='-'+ONES[n%10]}else if(n)s+=ONES[n];return s}
function words(x){const t=Math.round(x*100),nr=Math.floor(t/100),k=t%100,sc=['',' thousand',' million',' billion'];let p=[],n=nr,i=0;if(n===0)p.push('zero');while(n>0){const c=n%1000;if(c)p.unshift(w3(c)+sc[i]);n=Math.floor(n/1000);i++}let s=p.join(', ');s=s.charAt(0).toUpperCase()+s.slice(1)+' naira';if(k)s+=' and '+w3(k)+' kobo';return s+' only'}
const stOf=i=>i.status==='void'?'VOID':i.balance<=0.004?'PAID':i.paid>0?'PART':'UNPAID';

function docHead(sc){return `<div class="dh">${sc.logo?`<img src="${sc.logo}">`:CREST}<div><div class="dn">${esc(sc.name)}</div><div class="da">${esc(sc.address)}</div><div class="da">${esc(sc.contact)}</div></div></div>`}
function repDoc(title,sub,body){return `<div class="doc rep">${docHead(S.info||{name:'',address:'',contact:''})}<div class="dt">${title}</div><p>${sub}</p>${body}</div>`}
function showDoc(html,rep){window._doc=html;window._rep=!!rep;openModal(`<div class="mact" style="margin:0 0 10px"><button class="btn alt" onclick="closeModal()">Close</button><button class="btn gold" onclick="printHTML((window._rep?'<div class=free>':'<div class=page>')+window._doc+'</div>')">Print or save as PDF</button></div><div class="prevwrap">${html}</div>`,true);fitPreview()}

function invoiceHTML(d){
  const sc=d.school,sub=d.items.reduce((a,x)=>a+x.a,0);
  const stamp=d.status==='void'?'<div class="stamp void">VOID</div>':d.balance<=0.004?'<div class="stamp">PAID</div>':'';
  return `<div class="doc">${stamp}${docHead(sc)}<div class="dt">INVOICE</div>
  <div class="meta"><div><b>Invoice No:</b> ${esc(d.no)}</div><div><b>Date:</b> ${fdate(d.idate)}</div>
  <div><b>Pupil:</b> ${esc(d.sname)}</div><div><b>Due date:</b> ${d.due?fdate(d.due):'On receipt'}</div>
  <div><b>Reg No:</b> ${esc(d.reg)}</div><div><b>Session:</b> ${esc(d.session)}${d.term?' - '+termLbl(d.term):''}</div>
  <div><b>Class:</b> ${esc(d.cname)}</div><div><b>Parent phone:</b> ${esc(d.phone)}</div></div>
  <table><tr><th style="width:44px">S/N</th><th>Description</th><th class="r" style="width:150px">Amount (₦)</th></tr>
  ${d.items.map((x,i)=>`<tr><td>${i+1}</td><td>${esc(x.l)}</td><td class="r">${NF(x.a)}</td></tr>`).join('')}
  <tr><td colspan="2" class="r"><b>Sub-total</b></td><td class="r">${NF(sub)}</td></tr>
  ${d.discount?`<tr><td colspan="2" class="r"><b>Discount</b></td><td class="r">-${NF(d.discount)}</td></tr>`:''}
  <tr><td colspan="2" class="r"><b>Total</b></td><td class="r"><b>${NF(d.total)}</b></td></tr>
  <tr><td colspan="2" class="r"><b>Amount paid</b></td><td class="r">${NF(d.paid)}</td></tr>
  <tr><td colspan="2" class="r"><b>Balance due</b></td><td class="r"><b>${NF(d.balance)}</b></td></tr></table>
  ${d.receipts.length?`<p style="margin:12px 0 4px"><b>Payments received</b></p><table><tr><th>Receipt No</th><th>Date</th><th>Method</th><th class="r">Amount (₦)</th></tr>${d.receipts.map(r=>`<tr><td>${esc(r.no)}</td><td>${fdate(r.rdate)}</td><td>${esc(r.method)}</td><td class="r">${NF(r.amount)}</td></tr>`).join('')}</table>`:''}
  ${sc.bank?`<p style="margin-top:14px"><b>Pay to:</b><br>${esc(sc.bank).replace(/\n/g,'<br>')}</p>`:''}
  ${d.notes?`<p><b>Note:</b> ${esc(d.notes)}</p>`:''}${sc.note?`<p>${esc(sc.note)}</p>`:''}
  <div class="sig"><div>Parent / Guardian</div><div>Bursar / Authorised signature</div></div></div>`;
}
function receiptHTML(d){
  const sc=d.school,who=d.kind==='fee'?d.sname:(d.payer||'-');
  return `<div class="doc">${d.status==='void'?'<div class="stamp void">VOID</div>':''}${docHead(sc)}<div class="dt">OFFICIAL RECEIPT</div>
  <div class="meta"><div><b>Receipt No:</b> ${esc(d.no)}</div><div><b>Date:</b> ${fdate(d.rdate)}</div>
  <div><b>Received from:</b> ${esc(who)}</div><div><b>Method:</b> ${esc(d.method)}${d.ref?' ('+esc(d.ref)+')':''}</div>
  ${d.kind==='fee'?`<div><b>Reg No:</b> ${esc(d.reg)}</div><div><b>Class:</b> ${esc(d.cname)}</div>`:`<div><b>Category:</b> ${esc(d.category)}</div><div><b>Paid into:</b> ${esc(d.aname)}</div>`}</div>
  <table><tr><th style="width:190px">Amount received</th><td style="font:700 18px Arial">₦${NF(d.amount)}</td></tr><tr><th>The sum of</th><td>${esc(words(d.amount))}</td></tr>
  <tr><th>Being payment for</th><td>${d.kind==='fee'?(d.allocs.length?d.allocs.map(a=>`${esc(a.no)} (${esc(a.session)} ${a.term?termLbl(a.term):''}), balance after: ₦${NF(a.balance)}`).join('<br>'):'School fees (credit on account)'):esc(d.category)+(d.note?' - '+esc(d.note):'')}</td></tr></table>
  ${d.fin?`<p style="margin-top:10px"><b>Total outstanding after this payment:</b> ₦${NF(d.fin.balance)}${d.fin.credit>0?' &nbsp; <b>Credit on account:</b> ₦'+NF(d.fin.credit):''}</p>`:''}
  <p style="margin-top:8px;font-size:11px">Received by: ${esc(d.created_by)}</p>
  <div class="sig"><div>Payer</div><div>Bursar / Authorised signature</div></div></div>`;
}
function statementHTML(d){
  const rows=d.ledger.map(e=>`<tr><td>${fdate(e.date)}</td><td>${e.type}</td><td>${esc(e.no)}</td><td>${esc(e.text)}</td><td class="r">${e.dr?NF(e.dr):''}</td><td class="r">${e.cr?NF(e.cr):''}</td><td class="r">${NF(e.bal)}</td></tr>`).join('');
  return `<div class="doc rep">${docHead(d.school)}<div class="dt">STATEMENT OF ACCOUNT</div>
  <div class="meta"><div><b>Pupil:</b> ${esc(d.student.name)}</div><div><b>Reg No:</b> ${esc(d.student.reg)}</div><div><b>Class:</b> ${esc(d.student.cname)}</div><div><b>Parent phone:</b> ${esc(d.student.phone)}</div></div>
  <table><tr><th>Date</th><th>Type</th><th>No</th><th>Details</th><th class="r">Debit</th><th class="r">Credit</th><th class="r">Balance</th></tr>${rows||'<tr><td colspan="7">No transactions yet.</td></tr>'}</table>
  <p style="margin-top:10px"><b>Total billed:</b> ₦${NF(d.fin.billed)} &nbsp; <b>Paid:</b> ₦${NF(d.fin.paid)} &nbsp; <b>Balance due:</b> ₦${NF(d.fin.balance)}</p></div>`;
}
async function viewInv(id){showDoc(invoiceHTML(await api('invoice?id='+id)))}
async function viewRcpt(id){showDoc(receiptHTML(await api('receipt?id='+id)))}
async function stmt(id){showDoc(statementHTML(await api('statement?student='+id)),true)}

/* ---------- fee schedule ---------- */
async function pFees(){
  const cl=await loadClasses();if(!cl)return noClass;await loadFeeTypes();
  const tot=cl.fees.reduce((a,f)=>a+(+f.a||0),0);
  return `<div class="panel"><div class="tools">${classSel()}</div><p class="note" style="margin-bottom:10px">These lines print as the school bill on every report sheet for ${esc(cl.name)} and are used to create its invoices. An empty label prints a blank label, and an amount of 0 leaves the line out.</p>
  ${cl.fees.map((f,i)=>`<div class="fgrid" style="margin-bottom:6px;grid-template-columns:2fr 1fr"><input type="text" id="fl${i}" list="ftl" value="${esc(f.l)}" placeholder="Label, for example TUITION FEE" onchange="feeAuto('f',${i})"><input type="number" min="0" id="fa${i}" value="${f.a||''}"></div>`).join('')}
  <p style="margin:10px 0"><b>Total per term: ₦${NF(tot)}</b></p>${feeList()}<div class="tools"><button class="btn" onclick="saveFees()">Save fee schedule</button><button class="btn alt" onclick="feeTypesForm()">Fee types (common and custom)</button><button class="btn alt" onclick="copyFees()">Copy to all ${esc(cl.category)} classes</button></div></div>`;
}
const feeBody=()=>[0,1,2,3,4,5,6,7].map(i=>({l:$('#fl'+i).value,a:$('#fa'+i).value}));
async function saveFees(){await api('fees',{class_id:S.cid,fees:feeBody()});toast('Fee schedule saved',true);render()}
async function copyFees(){const cat=S.classes.find(c=>c.id===S.cid).category,f=feeBody();for(const c of S.classes.filter(c=>c.category===cat))await api('fees',{class_id:c.id,fees:f});toast('Copied to all '+cat+' classes',true);render()}

/* ---------- invoices ---------- */
async function pInvoices(){
  await loadClasses();const f=F.inv=F.inv||{term:'',status:'',cls:'',q:''};
  const d=await api(`invoices?session=${enc(S.session)}&term=${f.term}&class=${f.cls}&status=${f.status}&q=${enc(f.q)}`);
  return `<div class="panel"><div class="tools">
  <label>Term<select onchange="F.inv.term=this.value;render()"><option value="">All</option><option value="0" ${f.term==='0'?'selected':''}>No term</option>${[1,2,3].map(x=>`<option value="${x}" ${f.term==x?'selected':''}>${TN[x]}</option>`).join('')}</select></label>
  <label>Class<select onchange="F.inv.cls=this.value;render()"><option value="">All</option>${S.classes.map(c=>`<option value="${c.id}" ${f.cls==c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>
  <label>Show<select onchange="F.inv.status=this.value;render()">${[['','All'],['unpaid','Unpaid'],['paid','Paid'],['void','Voided']].map(o=>`<option value="${o[0]}" ${f.status===o[0]?'selected':''}>${o[1]}</option>`).join('')}</select></label>
  <label>Search<input type="text" value="${esc(f.q)}" placeholder="Name, Reg No or invoice no" onchange="F.inv.q=this.value;render()"></label>
  <button class="btn gold" onclick="genForm()">Generate for a class</button><button class="btn alt" onclick="newInvForm()">New invoice</button></div>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>Invoice</th><th>Date</th><th>Pupil</th><th>Class</th><th>Term</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th><th></th></tr>${d.rows.map(i=>`<tr><td>${esc(i.no)}</td><td>${fdate(i.idate)}</td><td>${esc(i.sname)}</td><td>${esc(i.cname)}</td><td>${i.term?TN[i.term]:'-'}</td><td>${NF(i.total)}</td><td>${NF(i.paid)}</td><td>${NF(i.balance)}</td><td>${stOf(i)}</td><td style="white-space:nowrap"><button class="btn alt sm" onclick="viewInv(${i.id})">View</button>${i.status==='open'&&i.balance>0.004?` <button class="btn alt sm" onclick="payForm(${i.student_id},${i.id})">Receive</button>`:''}${i.status==='open'?` <button class="btn danger sm" onclick="voidInv(${i.id})">Void</button>`:''}</td></tr>`).join('')}</table></div><p class="note">Billed ₦${NF(d.billed)} · Paid ₦${NF(d.paid)} · Balance ₦${NF(d.billed-d.paid)}</p>`:'<div class="empty">No invoices match.</div>'}</div>`;
}
function voidInv(id){ask('Void this invoice? Payments applied to it are released and move to other unpaid invoices or stay as credit.',async()=>{await api('invoices/void',{id});render()})}
const clsOpts=cid=>S.classes.map(c=>`<option value="${c.id}" ${c.id===cid?'selected':''}>${esc(c.name)}</option>`).join('');
const termOpts=(zero)=>(zero?'<option value="0">No term (admission, balance b/f, other)</option>':'')+[1,2,3].map(x=>`<option value="${x}">${TN[x]} term</option>`).join('');
async function genForm(){
  await loadClasses();
  openModal(`<h2>Generate invoices for a class</h2><p class="note">Creates one invoice per pupil from the class fee schedule. Pupils who already have an invoice for the same term are skipped.</p><div class="fgrid" style="margin-top:10px">
  <div class="fld"><label>Class<select id="gc">${clsOpts(S.cid)}</select></label></div><div class="fld"><label>Term<select id="gt">${termOpts(false)}</select></label></div>
  <div class="fld"><label>Invoice date<input type="date" id="gd" value="${today()}"></label></div><div class="fld"><label>Due date<input type="date" id="gu"></label></div></div>
  <p class="note">Session: ${esc(S.session)}</p><div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="doGen()">Generate</button></div>`);
}
async function doGen(){const r=await api('invoices/generate',{class_id:+$('#gc').value,term:+$('#gt').value,session:S.session,idate:$('#gd').value,due:$('#gu').value});closeModal();toast(r.made+' invoices created'+(r.skipped?', '+r.skipped+' skipped (already invoiced)':''),true);if(S.page!=='invoices')go('invoices');else render()}
async function newInvForm(){
  await loadClasses();await loadFeeTypes();
  openModal(`<h2>New invoice</h2><div class="fgrid"><div class="fld"><label>Class<select id="nc" onchange="newInvClass(this.value)">${clsOpts(S.cid)}</select></label></div><div class="fld"><label>Pupil<select id="np"></select></label></div>
  <div class="fld"><label>Term<select id="nt">${termOpts(true)}</select></label></div><div class="fld"><label>Invoice date<input type="date" id="nd" value="${today()}"></label></div><div class="fld"><label>Due date<input type="date" id="nu"></label></div></div>
  ${feeList()}<h3 style="margin:12px 0 6px">Fee lines</h3>${[0,1,2,3,4,5].map(i=>`<div class="fgrid" style="margin-bottom:6px;grid-template-columns:2fr 1fr"><input type="text" id="il${i}" list="ftl" placeholder="Fee (pick or type your own)" onchange="feeAuto('i',${i})"><input type="number" min="0" id="ia${i}" placeholder="Amount"></div>`).join('')}
  <div class="fgrid"><div class="fld"><label>Discount (₦)<input type="number" min="0" id="ndis"></label></div><div class="fld"><label>Note on invoice<input type="text" id="nn"></label></div></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="saveNewInv()">Create invoice</button></div>`);
  await newInvClass(S.cid);
}
async function newInvClass(cid){const l=await api('students?class='+cid);$('#np').innerHTML=l.map(s=>`<option value="${s.id}">${esc(s.name)} (${esc(s.reg_no)})</option>`).join('')}
async function saveNewInv(){
  const items=[0,1,2,3,4,5].map(i=>({l:$('#il'+i).value,a:$('#ia'+i).value})).filter(x=>+x.a>0);
  const r=await api('invoices',{student_id:+$('#np').value,session:S.session,term:+$('#nt').value,idate:$('#nd').value,due:$('#nu').value,items,discount:$('#ndis').value,notes:$('#nn').value});
  closeModal();await viewInv(r.id);if(S.page==='invoices')render()
}

/* ---------- receipts and payments ---------- */
async function payForm(sid,invId){
  await loadClasses();S.accounts=await api('accounts');
  let cid=S.cid;if(sid){const st=await api('statement?student='+sid);cid=st.student.class_id}
  openModal(`<h2>Receive school fees</h2><div class="fgrid">
  <div class="fld"><label>Class<select id="pc" onchange="payClass(this.value)">${clsOpts(cid)}</select></label></div>
  <div class="fld"><label>Pupil<select id="pp" onchange="payPupil()"></select></label></div></div>
  <div id="pinfo" class="note" style="margin:10px 0"></div>
  <div class="fgrid"><div class="fld"><label>Amount (₦)<input type="number" id="pa" min="0"></label></div>
  <div class="fld"><label>Method<select id="pm">${['CASH','TRANSFER','POS','CHEQUE'].map(m=>`<option>${m}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Paid into<select id="pacc">${S.accounts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Date<input type="date" id="pd" value="${today()}"></label></div>
  <div class="fld"><label>Reference (teller or transfer no)<input type="text" id="pr"></label></div>
  <div class="fld"><label>Apply to invoice<select id="pi"><option value="">Oldest unpaid first</option></select></label></div></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn gold" onclick="savePay()">Save and show receipt</button></div>`);
  await payClass(cid,sid,invId);
}
async function payClass(cid,sid,invId){const l=await api('students?class='+cid);$('#pp').innerHTML=l.map(s=>`<option value="${s.id}" ${s.id===sid?'selected':''}>${esc(s.name)} (${esc(s.reg_no)})</option>`).join('');await payPupil(invId)}
async function payPupil(invId){
  const id=$('#pp').value;if(!id){$('#pinfo').textContent='No pupils in this class.';$('#pi').innerHTML='';return}
  const st=await api('statement?student='+id),open=st.invoices.filter(i=>i.balance>0.004);
  $('#pinfo').innerHTML=`Outstanding: <b>₦${NF(st.fin.balance)}</b>${st.fin.credit>0?` · Credit on account: <b>₦${NF(st.fin.credit)}</b>`:''}`;
  $('#pi').innerHTML='<option value="">Oldest unpaid first</option>'+open.map(i=>`<option value="${i.id}" ${i.id===invId?'selected':''}>${esc(i.no)} · ${i.term?termLbl(i.term):'No term'} · balance ₦${NF(i.balance)}</option>`).join('');
  if(invId){const x=open.find(i=>i.id===invId);if(x)$('#pa').value=x.balance}
}
async function savePay(){const r=await api('receipts',{kind:'fee',student_id:+$('#pp').value,amount:$('#pa').value,method:$('#pm').value,account_id:+$('#pacc').value,rdate:$('#pd').value,ref:$('#pr').value,invoice_id:$('#pi').value||null});closeModal();if(S.page==='receipts'||S.page==='invoices'||S.page==='fdash'||S.page==='debtors')render();await viewRcpt(r.id)}
async function incomeForm(){
  S.accounts=await api('accounts');const cats=await api('income/categories');
  openModal(`<h2>Other income</h2><p class="note">For money that is not school fees, such as uniform or book sales.</p><div class="fgrid" style="margin-top:10px">
  <div class="fld"><label>Received from<input type="text" id="oy"></label></div><div class="fld"><label>Category<input type="text" id="oc" list="oct" placeholder="UNIFORM SALES"></label><datalist id="oct">${[...new Set([...INC_CATS,...cats])].map(x=>`<option>${esc(x)}</option>`).join('')}</datalist></div>
  <div class="fld"><label>Amount (₦)<input type="number" id="oa" min="0"></label></div><div class="fld"><label>Method<select id="om">${['CASH','TRANSFER','POS','CHEQUE'].map(m=>`<option>${m}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Paid into<select id="oac">${S.accounts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label></div><div class="fld"><label>Date<input type="date" id="od" value="${today()}"></label></div>
  <div class="fld"><label>Reference<input type="text" id="or"></label></div><div class="fld"><label>Note<input type="text" id="on"></label></div></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn gold" onclick="saveIncome()">Save and show receipt</button></div>`);
}
async function saveIncome(){const r=await api('receipts',{kind:'other',payer:$('#oy').value,category:$('#oc').value,amount:$('#oa').value,method:$('#om').value,account_id:+$('#oac').value,rdate:$('#od').value,ref:$('#or').value,note:$('#on').value});closeModal();if(S.page==='receipts')render();await viewRcpt(r.id)}
async function pReceipts(){
  const f=F.rc=F.rc||{from:monthStart(),to:today(),kind:'',q:''};
  const d=await api(`receipts?from=${f.from}&to=${f.to}&kind=${f.kind}&q=${enc(f.q)}`);
  return `<div class="panel"><div class="tools"><label>From<input type="date" value="${f.from}" onchange="F.rc.from=this.value;render()"></label><label>To<input type="date" value="${f.to}" onchange="F.rc.to=this.value;render()"></label>
  <label>Type<select onchange="F.rc.kind=this.value;render()">${[['','All'],['fee','School fees'],['other','Other income']].map(o=>`<option value="${o[0]}" ${f.kind===o[0]?'selected':''}>${o[1]}</option>`).join('')}</select></label>
  <label>Search<input type="text" value="${esc(f.q)}" placeholder="Name or receipt no" onchange="F.rc.q=this.value;render()"></label>
  <button class="btn gold" onclick="payForm()">Receive school fees</button><button class="btn alt" onclick="incomeForm()">Other income</button></div>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>Receipt</th><th>Date</th><th>From</th><th>Class / category</th><th>Method</th><th>Account</th><th>Amount</th><th></th></tr>${d.rows.map(r=>`<tr style="${r.status==='void'?'opacity:.5;text-decoration:line-through':''}"><td>${esc(r.no)}</td><td>${fdate(r.rdate)}</td><td>${esc(r.sname||r.payer)}</td><td>${esc(r.kind==='fee'?r.cname:r.category)}</td><td>${esc(r.method)}</td><td>${esc(r.aname)}</td><td>${NF(r.amount)}</td><td style="white-space:nowrap"><button class="btn alt sm" onclick="viewRcpt(${r.id})">View</button>${r.status==='ok'?` <button class="btn danger sm" onclick="voidRcpt(${r.id})">Void</button>`:''}</td></tr>`).join('')}</table></div><p class="note">Total received: ₦${NF(d.total)}</p>`:'<div class="empty">No receipts in this period.</div>'}</div>`;
}
function voidRcpt(id){ask('Void this receipt? The money will no longer count as received.',async()=>{await api('receipts/void',{id});render()})}

/* ---------- expenses ---------- */
async function expForm(){
  S.accounts=await api('accounts');const e=await api('expenses?from=2000-01-01');
  openModal(`<h2>Record expense</h2><div class="fgrid"><div class="fld"><label>Date<input type="date" id="ed" value="${today()}"></label></div><div class="fld"><label>Category<input type="text" id="ec" list="ect" placeholder="SALARIES"></label><datalist id="ect">${[...new Set([...EXP_CATS,...e.categories])].map(x=>`<option>${esc(x)}</option>`).join('')}</datalist></div>
  <div class="fld"><label>Paid to<input type="text" id="ep"></label></div><div class="fld"><label>Amount (₦)<input type="number" id="ea" min="0"></label></div>
  <div class="fld"><label>Method<select id="em">${['CASH','TRANSFER','POS','CHEQUE'].map(m=>`<option>${m}</option>`).join('')}</select></label></div><div class="fld"><label>Paid from<select id="eac">${S.accounts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Reference<input type="text" id="er"></label></div><div class="fld"><label>Description<input type="text" id="en"></label></div></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="saveExp()">Save expense</button></div>`);
}
async function saveExp(){const r=await api('expenses',{edate:$('#ed').value,category:$('#ec').value,payee:$('#ep').value,amount:$('#ea').value,method:$('#em').value,account_id:+$('#eac').value,ref:$('#er').value,description:$('#en').value});closeModal();toast('Saved as '+r.no,true);if(S.page==='expenses'||S.page==='fdash')render()}
async function pExpenses(){
  const f=F.ex=F.ex||{from:monthStart(),to:today(),category:''};
  const d=await api(`expenses?from=${f.from}&to=${f.to}&category=${enc(f.category)}`);
  return `<div class="panel"><div class="tools"><label>From<input type="date" value="${f.from}" onchange="F.ex.from=this.value;render()"></label><label>To<input type="date" value="${f.to}" onchange="F.ex.to=this.value;render()"></label>
  <label>Category<select onchange="F.ex.category=this.value;render()"><option value="">All</option>${d.categories.map(x=>`<option ${f.category===x?'selected':''}>${esc(x)}</option>`).join('')}</select></label><button class="btn gold" onclick="expForm()">Record expense</button></div>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>Voucher</th><th>Date</th><th>Category</th><th>Paid to</th><th>Description</th><th>Account</th><th>Amount</th><th></th></tr>${d.rows.map(r=>`<tr style="${r.status==='void'?'opacity:.5;text-decoration:line-through':''}"><td>${esc(r.no)}</td><td>${fdate(r.edate)}</td><td>${esc(r.category)}</td><td>${esc(r.payee)}</td><td>${esc(r.description)}</td><td>${esc(r.aname)}</td><td>${NF(r.amount)}</td><td><button class="btn alt sm" onclick="viewVoucher(${r.id})">Voucher</button> ${r.status==='ok'?`<button class="btn danger sm" onclick="voidExp(${r.id})">Void</button>`:''}</td></tr>`).join('')}</table></div><p class="note">Total spent: ₦${NF(d.total)}</p>`:'<div class="empty">No expenses in this period.</div>'}</div>`;
}
function voidExp(id){ask('Void this expense?',async()=>{await api('expenses/void',{id});render()})}

/* ---------- debtors, cash book, reports ---------- */
async function pDebtors(){
  await loadClasses();const f=F.db=F.db||{term:'',cls:''};
  const d=await api(`debtors?session=${enc(S.session)}&term=${f.term}&class=${f.cls}`);
  window._debt=d;
  return `<div class="panel"><div class="tools"><label>Term<select onchange="F.db.term=this.value;render()"><option value="">All terms</option>${[1,2,3].map(x=>`<option value="${x}" ${f.term==x?'selected':''}>${TN[x]}</option>`).join('')}</select></label>
  <label>Class<select onchange="F.db.cls=this.value;render()"><option value="">All classes</option>${S.classes.map(c=>`<option value="${c.id}" ${f.cls==c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><button class="btn alt" onclick="printDebtors()">Print list</button></div>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>Pupil</th><th>Reg No</th><th>Class</th><th>Parent phone</th><th>Billed</th><th>Paid</th><th>Balance</th><th></th></tr>${d.rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.reg)}</td><td>${esc(r.cname)}</td><td>${r.phone?`<a href="tel:${esc(r.phone)}">${esc(r.phone)}</a>`:''}</td><td>${NF(r.billed)}</td><td>${NF(r.paid)}</td><td><b>${NF(r.balance)}</b></td><td style="white-space:nowrap"><button class="btn alt sm" onclick="stmt(${r.id})">Statement</button> <button class="btn alt sm" onclick="reminder(${r.id})">Reminder</button> <button class="btn alt sm" onclick="payForm(${r.id})">Receive</button></td></tr>`).join('')}</table></div><p class="note">${d.rows.length} pupils owe ₦${NF(d.total)} in total.</p>`:'<div class="empty">No outstanding balances.</div>'}</div>`;
}
function printDebtors(){const d=window._debt;showDoc(repDoc('DEBTORS LIST',`Session ${esc(S.session)} · ${d.rows.length} pupils · Total ₦${NF(d.total)}`,`<table><tr><th>#</th><th>Pupil</th><th>Class</th><th>Phone</th><th class="r">Billed</th><th class="r">Paid</th><th class="r">Balance</th></tr>${d.rows.map((r,i)=>`<tr><td>${i+1}</td><td>${esc(r.name)}</td><td>${esc(r.cname)}</td><td>${esc(r.phone)}</td><td class="r">${NF(r.billed)}</td><td class="r">${NF(r.paid)}</td><td class="r">${NF(r.balance)}</td></tr>`).join('')}</table>`),true)}
async function pCash(){
  S.accounts=await api('accounts');const f=F.cb=F.cb||{acc:S.accounts[0].id,from:monthStart(),to:today()};
  if(!S.accounts.find(a=>a.id==f.acc))f.acc=S.accounts[0].id;
  const d=await api(`cashbook?account=${f.acc}&from=${f.from}&to=${f.to}`);window._cb=d;
  return `<div class="panel"><div class="tools"><label>Account<select onchange="F.cb.acc=this.value;render()">${S.accounts.map(a=>`<option value="${a.id}" ${f.acc==a.id?'selected':''}>${esc(a.name)} (₦${NF(a.balance)})</option>`).join('')}</select></label>
  <label>From<input type="date" value="${f.from}" onchange="F.cb.from=this.value;render()"></label><label>To<input type="date" value="${f.to}" onchange="F.cb.to=this.value;render()"></label><button class="btn alt" onclick="printCash()">Print</button>${S.user.role==='admin'?'<button class="btn alt" onclick="acctForm()">Manage accounts</button>':''}</div>
  <div class="tw"><table class="t"><tr><th>Date</th><th>Ref</th><th>Details</th><th>In</th><th>Out</th><th>Balance</th></tr><tr><td colspan="5"><i>Opening balance</i></td><td>${NF(d.opening)}</td></tr>${d.rows.map(r=>`<tr><td>${fdate(r.date)}</td><td>${esc(r.no)}</td><td>${esc(r.text)}</td><td>${r.in?NF(r.in):''}</td><td>${r.out?NF(r.out):''}</td><td>${NF(r.bal)}</td></tr>`).join('')}</table></div>
  <p class="note">Money in ₦${NF(d.in)} · Money out ₦${NF(d.out)} · Closing balance ₦${NF(d.closing)}</p></div>`;
}
function printCash(){const d=window._cb,f=F.cb;showDoc(repDoc('CASH BOOK - '+esc(d.account.name),`${fdate(f.from)} to ${fdate(f.to)}`,`<table><tr><th>Date</th><th>Ref</th><th>Details</th><th class="r">In</th><th class="r">Out</th><th class="r">Balance</th></tr><tr><td colspan="5">Opening balance</td><td class="r">${NF(d.opening)}</td></tr>${d.rows.map(r=>`<tr><td>${fdate(r.date)}</td><td>${esc(r.no)}</td><td>${esc(r.text)}</td><td class="r">${r.in?NF(r.in):''}</td><td class="r">${r.out?NF(r.out):''}</td><td class="r">${NF(r.bal)}</td></tr>`).join('')}<tr><th colspan="3">Totals</th><th class="r">${NF(d.in)}</th><th class="r">${NF(d.out)}</th><th class="r">${NF(d.closing)}</th></tr></table>`),true)}
function acctForm(id){
  const rows=S.accounts.map(a=>`<tr><td>${esc(a.name)}</td><td>${esc(a.kind)}</td><td>${NF(a.opening)}</td><td><button class="btn alt sm" onclick="acctEdit(${a.id})">Edit</button> <button class="btn danger sm" onclick="acctDel(${a.id})">Delete</button></td></tr>`).join('');
  openModal(`<h2>Cash and bank accounts</h2><table class="t"><tr><th>Name</th><th>Type</th><th>Opening balance</th><th></th></tr>${rows}</table><div class="mact"><button class="btn alt" onclick="acctEdit(0)">Add account</button><button class="btn" onclick="closeModal();render()">Done</button></div>`);
}
function acctEdit(id){
  const a=id?S.accounts.find(x=>x.id===id):{name:'',kind:'bank',opening:0};
  openModal(`<h2>${id?'Edit account':'Add account'}</h2><div class="fgrid"><div class="fld"><label>Name<input type="text" id="an" value="${esc(a.name)}"></label></div><div class="fld"><label>Type<select id="ak"><option value="cash" ${a.kind==='cash'?'selected':''}>Cash</option><option value="bank" ${a.kind==='bank'?'selected':''}>Bank</option></select></label></div><div class="fld"><label>Opening balance (₦)<input type="number" id="ao" value="${a.opening||0}"></label></div></div><div class="mact"><button class="btn alt" onclick="acctForm()">Back</button><button class="btn" onclick="acctSave(${id})">Save</button></div>`);
}
async function acctSave(id){const b={name:$('#an').value,kind:$('#ak').value,opening:$('#ao').value};if(id)b.id=id;await api('accounts',b);S.accounts=await api('accounts');acctForm()}
function acctDel(id){ask('Delete this account?',async()=>{await api('accounts/delete',{id});S.accounts=await api('accounts');acctForm()})}
async function pFReports(){
  const f=F.fr=F.fr||{tab:'ie',from:today().slice(0,4)+'-01-01',to:today(),term:''};
  let body;
  if(f.tab==='ie'){
    const d=await api(`fin/ie?from=${f.from}&to=${f.to}`);window._ie=d;
    body=`<div class="tools"><label>From<input type="date" value="${f.from}" onchange="F.fr.from=this.value;render()"></label><label>To<input type="date" value="${f.to}" onchange="F.fr.to=this.value;render()"></label><button class="btn alt" onclick="printIE()">Print</button></div>${ieTable(d)}`;
  }else{
    const d=await api(`fin/collection?session=${enc(S.session)}&term=${f.term}`);window._col=d;
    body=`<div class="tools"><label>Term<select onchange="F.fr.term=this.value;render()"><option value="">Whole session</option><option value="0" ${f.term==='0'?'selected':''}>No term</option>${[1,2,3].map(x=>`<option value="${x}" ${f.term==x?'selected':''}>${TN[x]}</option>`).join('')}</select></label><button class="btn alt" onclick="printCol()">Print</button></div>${colTable(d)}`;
  }
  return `<div class="panel"><div class="tools"><button class="btn ${f.tab==='ie'?'':'alt'}" onclick="F.fr.tab='ie';render()">Income and expenditure</button><button class="btn ${f.tab==='col'?'':'alt'}" onclick="F.fr.tab='col';render()">Fee collection by class</button></div>${body}</div>`;
}
const ieTable=d=>`<div class="tw"><table class="t"><tr><th colspan="2">INCOME</th></tr><tr><td>School fees received</td><td style="text-align:right">${NF(d.fees)}</td></tr>${d.other.map(o=>`<tr><td>${esc(o.category)}</td><td style="text-align:right">${NF(o.total)}</td></tr>`).join('')}<tr><th>Total income</th><th style="text-align:right">${NF(d.income)}</th></tr><tr><th colspan="2">EXPENDITURE</th></tr>${d.expenses.map(o=>`<tr><td>${esc(o.category)}</td><td style="text-align:right">${NF(o.total)}</td></tr>`).join('')}<tr><th>Total expenditure</th><th style="text-align:right">${NF(d.spent)}</th></tr><tr><th>${d.net>=0?'SURPLUS':'DEFICIT'}</th><th style="text-align:right">${NF(Math.abs(d.net))}</th></tr></table></div>`;
const colTable=d=>`<div class="tw"><table class="t"><tr><th>Class</th><th>Pupils billed</th><th>Billed</th><th>Collected</th><th>Outstanding</th><th>Rate</th></tr>${d.rows.map(r=>`<tr><td>${esc(r.cname)}</td><td>${r.pupils}</td><td>${NF(r.billed)}</td><td>${NF(r.paid)}</td><td>${NF(r.balance)}</td><td>${r.billed?Math.round(r.paid/r.billed*100):0}%</td></tr>`).join('')}<tr><th>Total</th><th>${d.rows.reduce((a,r)=>a+r.pupils,0)}</th><th>${NF(d.rows.reduce((a,r)=>a+r.billed,0))}</th><th>${NF(d.rows.reduce((a,r)=>a+r.paid,0))}</th><th>${NF(d.rows.reduce((a,r)=>a+r.balance,0))}</th><th></th></tr></table></div>`;
function printIE(){showDoc(repDoc('INCOME AND EXPENDITURE',`${fdate(F.fr.from)} to ${fdate(F.fr.to)}`,ieTable(window._ie).replace(/class="t"/,'')),true)}
function printCol(){showDoc(repDoc('FEE COLLECTION BY CLASS',`Session ${esc(S.session)}`,colTable(window._col).replace(/class="t"/,'')),true)}

/* ======================= licence ======================= */
async function refreshMe(){const m=await api('me');S.lic=m.lic;{const u=$('#upg');if(u)u.style.display=(S.user.role==='admin'&&m.lic&&m.lic.state==='trial')?'':'none'}S.release=m.students_view;S.session=m.session;S.sessions=m.sessions;if(m.info)S.info=m.info}
const rd=file=>new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=()=>rej(new Error('Could not read the file'));r.readAsDataURL(file)});
/* ======================= icons, charts, KPI cards ======================= */
const ICO={
 eye:'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
 edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
 trash:'<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
 key:'<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M16 7l3 3"/>',
 ban:'<circle cx="12" cy="12" r="10"/><path d="M4.9 4.9l14.2 14.2"/>',
 check:'<path d="M20 6L9 17l-5-5"/>',
 file:'<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
 list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
 wallet:'<rect x="2" y="6" width="20" height="14" rx="2"/><path d="M2 10h20M16 15h2"/>',
 printer:'<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
 mail:'<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 6l-10 7L2 6"/>',
 reply:'<path d="M9 17l-5-5 5-5"/><path d="M20 18v-2a4 4 0 00-4-4H4"/>',
 x:'<path d="M18 6L6 18M6 6l12 12"/>',
 users:'<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8"/>',
 book:'<path d="M4 19.5A2.5 2.5 0 016.5 17H20V2H6.5A2.5 2.5 0 004 4.5z"/><path d="M4 19.5V4.5"/>',
 trend:'<path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/>',
 inbox:'<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.5-6.9A2 2 0 0016.8 4H7.2a2 2 0 00-1.7 1.1z"/>',
 cal:'<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
 award:'<circle cx="12" cy="8" r="7"/><path d="M8.2 13.9L7 23l5-3 5 3-1.2-9.1"/>',
 dollar:'<path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>',
 alert:'<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
 school:'<path d="M2 9l10-6 10 6-10 6z"/><path d="M6 11.5V17c0 1.5 3 3 6 3s6-1.5 6-3v-5.5"/>',
 pct:'<path d="M19 5L5 19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
 clock:'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'};
const ic=n=>`<svg viewBox="0 0 24 24" aria-hidden="true">${ICO[n]||''}</svg>`;
const ACT={'Clearance':'award','Reminder':'mail','Voucher':'file','Edit':'edit','Delete':'trash','View':'eye','Void':'x','Sheet':'file','Statement':'list','Receive':'wallet','Reset password':'key','Reset':'key','Suspend':'ban','Activate':'check','Reply':'reply','Print':'printer','Remove':'trash'};
function decorateActions(root){
  (root||document).querySelectorAll('table.t button.sm,table.t a.sm,table button.sm').forEach(b=>{
    const t=(b.dataset.label||b.textContent).trim();const k=ACT[t];if(!k||b.classList.contains('ib'))return;
    b.dataset.label=t;b.title=t;b.setAttribute('aria-label',t);b.className='ib'+(b.classList.contains('danger')?' danger':'')+(b.classList.contains('gold')?' gold':'');b.innerHTML=ic(k);
  });
}
const iconBtn=(k,title,on,cls)=>`<button class="ib ${cls||''}" title="${esc(title)}" aria-label="${esc(title)}" onclick="${on}">${ic(k)}</button>`;
const PAL=['#16213e','#b58a2c','#2f7d6d','#c4161c','#5b7db1','#8e6bbf','#d97a2b','#6b7280'];
const shortN=n=>{n=+n||0;const a=Math.abs(n);return a>=1e6?(n/1e6).toFixed(1).replace(/\.0$/,'')+'M':a>=1e4?Math.round(n/1e3)+'k':a>=1e3?(n/1e3).toFixed(1).replace(/\.0$/,'')+'k':(Math.round(n*10)/10)+''};
const kpi=(icon,val,label,color)=>`<div class="kpi"><div class="ico" style="background:${color||'#eef1f8'}22;color:${color||'#16213e'}">${ic(icon)}</div><div style="min-width:0"><b>${val}</b><small>${label}</small></div></div>`;
const card=(title,body,extra)=>`<div class="card"><h4><span>${title}</span>${extra||''}</h4>${body}</div>`;
function chartBar(items,o){
  o=o||{};if(!items.length||items.every(i=>!i.value))return '<div class="empty-chart">No data yet</div>';
  const W=440,H=o.h||200,l=36,r=8,t=14,b=o.rot?60:30,max=Math.max(1,...items.map(i=>i.value))*1.12,iw=W-l-r,ih=H-t-b,bw=iw/items.length;let g='';
  for(let k=0;k<=4;k++){const y=t+ih-ih*k/4;g+=`<line x1="${l}" x2="${W-r}" y1="${y}" y2="${y}" stroke="#e6e9f0"/><text x="${l-5}" y="${y+4}" font-size="10" fill="#667085" text-anchor="end">${shortN(max*k/4)}</text>`}
  items.forEach((it,i)=>{const h=ih*it.value/max,x=l+i*bw+bw*.17,y=t+ih-h,cx=l+i*bw+bw/2;
    g+=`<rect x="${x}" y="${y}" width="${bw*.66}" height="${Math.max(h,0)}" rx="3" fill="${it.color||o.color||PAL[0]}"><title>${esc(it.label)}: ${it.value}</title></rect>`;
    if(it.value&&items.length<=14)g+=`<text x="${cx}" y="${y-3}" font-size="10" fill="#1d2433" text-anchor="middle" font-weight="600">${shortN(it.value)}</text>`;
    const lab=String(it.label).length>11&&!o.rot?String(it.label).slice(0,10)+'…':it.label;
    g+=o.rot?`<text transform="translate(${cx},${H-b+12}) rotate(-40)" font-size="10" fill="#667085" text-anchor="end">${esc(lab)}</text>`:`<text x="${cx}" y="${H-b+15}" font-size="10" fill="#667085" text-anchor="middle">${esc(lab)}</text>`});
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">${g}</svg>`;
}
function chartGroup(labels,series,o){
  o=o||{};if(!labels.length||series.every(s=>s.values.every(v=>!v)))return '<div class="empty-chart">No data yet</div>';
  const W=440,H=o.h||200,l=40,r=8,t=14,b=34,max=Math.max(1,...series.flatMap(s=>s.values))*1.12,iw=W-l-r,ih=H-t-b,gw=iw/labels.length,n=series.length,bw=gw*.78/n;let g='';
  for(let k=0;k<=4;k++){const y=t+ih-ih*k/4;g+=`<line x1="${l}" x2="${W-r}" y1="${y}" y2="${y}" stroke="#e6e9f0"/><text x="${l-5}" y="${y+4}" font-size="10" fill="#667085" text-anchor="end">${shortN(max*k/4)}</text>`}
  labels.forEach((lb,i)=>{series.forEach((s,j)=>{const v=s.values[i]||0,h=ih*v/max;g+=`<rect x="${l+i*gw+gw*.11+j*bw}" y="${t+ih-h}" width="${bw*.92}" height="${h}" rx="2" fill="${s.color}"><title>${esc(s.name)} ${esc(lb)}: ${NF(v)}</title></rect>`});g+=`<text x="${l+i*gw+gw/2}" y="${H-b+15}" font-size="10" fill="#667085" text-anchor="middle">${esc(lb)}</text>`});
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">${g}</svg><div class="legend">${series.map(s=>`<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>`;
}
function chartLine(labels,series,o){
  o=o||{};const pts=series.flatMap(s=>s.values.filter(v=>v!=null));if(!pts.length)return '<div class="empty-chart">No data yet</div>';
  const W=440,H=o.h||190,l=38,r=14,t=14,b=30,max=Math.max(1,...pts)*1.12,min=0,iw=W-l-r,ih=H-t-b,step=labels.length>1?iw/(labels.length-1):0;let g='';
  for(let k=0;k<=4;k++){const y=t+ih-ih*k/4;g+=`<line x1="${l}" x2="${W-r}" y1="${y}" y2="${y}" stroke="#e6e9f0"/><text x="${l-5}" y="${y+4}" font-size="10" fill="#667085" text-anchor="end">${shortN(max*k/4)}</text>`}
  labels.forEach((lb,i)=>{g+=`<text x="${l+i*step}" y="${H-b+16}" font-size="10" fill="#667085" text-anchor="middle">${esc(lb)}</text>`});
  series.forEach(s=>{let d='',dots='';s.values.forEach((v,i)=>{if(v==null)return;const x=l+i*step,y=t+ih-ih*(v-min)/(max-min);d+=(d?'L':'M')+x.toFixed(1)+' '+y.toFixed(1);dots+=`<circle cx="${x}" cy="${y}" r="3.5" fill="${s.color}"><title>${esc(s.name)} ${esc(labels[i])}: ${v}</title></circle>`});g+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.4" stroke-linejoin="round"/>${dots}`});
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">${g}</svg>${series.length>1?`<div class="legend">${series.map(s=>`<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>`:''}`;
}
function chartDonut(items,o){
  o=o||{};items=items.filter(i=>i.value>0);const tot=items.reduce((a,i)=>a+i.value,0);if(!tot)return '<div class="empty-chart">No data yet</div>';
  let off=25,segs='';items.forEach((it,i)=>{const p=it.value/tot*100;segs+=`<circle cx="21" cy="21" r="15.9155" fill="none" stroke="${it.color||PAL[i%PAL.length]}" stroke-width="6" stroke-dasharray="${p} ${100-p}" stroke-dashoffset="${off}"><title>${esc(it.label)}: ${it.value}</title></circle>`;off-=p});
  return `<div class="donut"><svg viewBox="0 0 42 42" role="img"><circle cx="21" cy="21" r="15.9155" fill="none" stroke="#eef1f8" stroke-width="6"/>${segs}<text x="21" y="22.5" text-anchor="middle" font-size="6.5" font-weight="700" fill="#16213e">${o.center||shortN(tot)}</text><text x="21" y="28" text-anchor="middle" font-size="3.2" fill="#667085">${o.sub||'total'}</text></svg><div class="legend" style="flex-direction:column;gap:5px">${items.map((it,i)=>`<span><i style="background:${it.color||PAL[i%PAL.length]}"></i>${esc(it.label)}: <b>${o.money?'₦'+shortN(it.value):it.value}</b> (${Math.round(it.value/tot*100)}%)</span>`).join('')}</div></div>`;
}
function chartHBar(items,o){
  o=o||{};if(!items.length)return '<div class="empty-chart">No data yet</div>';const max=Math.max(1,...items.map(i=>i.value));
  return items.map(i=>`<div class="hb"><span title="${esc(i.label)}">${esc(i.label)}</span><span class="bar"><i style="width:${i.value/max*100}%;background:${i.color||o.color||PAL[0]}"></i></span><span>${o.money?'₦'+shortN(i.value):i.value}${o.suffix||''}</span></div>`).join('');
}
const GRAD=['#2f7d6d','#5b9d6d','#8aa84f','#b58a2c','#d97a2b','#c4161c','#a01b1b','#8a1c1c','#6d1111'];
const GCOL={A:'#2f7d6d',B:'#5b9d6d',C:'#b58a2c',D:'#d97a2b',E:'#c4161c',F:'#8a1c1c'};

/* ======================= dashboards ======================= */
async function pDash(){
  if(S.t==='Y')S.t=3;
  const isA=S.user.role==='admin',q=`session=${enc(S.session)}`;
  const a=await api(`stats/academic?${q}&term=${S.t}${S.dc?'&class='+S.dc:''}`);S.dc=a.class_id;
  const f=isA?await api(`stats/finance?${q}`):null,prog=await api('dashboard?'+q);
  const kp=[kpi('users',a.pupils,'Pupils enrolled','#16213e'),kpi('users',a.staff,'Staff accounts','#5b7db1'),kpi('school',a.classes,'Classes','#8e6bbf'),
    kpi('check',a.completion+'%',`Results entered (${a.scored} of ${a.pupils})`,'#2f7d6d'),kpi('cal',a.attendance==null?'-':a.attendance+'%','Attendance this term','#d97a2b'),
    kpi('trend',a.overall_avg==null?'-':a.overall_avg,'Average score per subject','#b58a2c'),kpi('inbox',a.unread,'Unread messages','#c4161c')];
  if(f)kp.push(kpi('dollar','₦'+shortN(f.paid),'Fees collected','#2f7d6d'),kpi('alert','₦'+shortN(f.balance),'Fees outstanding','#c4161c'),kpi('pct',f.rate+'%','Collection rate','#16213e'));
  const g=a.gender,gi=[{label:'Female',value:g.FEMALE||0,color:'#c4161c'},{label:'Male',value:g.MALE||0,color:'#16213e'},{label:'Not set',value:g['NOT SET']||0,color:'#9aa3b5'}];
  const ch=[
    card('Pupils per class',chartBar(a.per_class.filter(x=>x.pupils>0||a.per_class.length<8).map(x=>({label:x.name,value:x.pupils})),{rot:true,h:210})),
    card('Gender split',chartDonut(gi,{sub:'pupils'})),
    card('Grades awarded, '+TN[a.term].toLowerCase()+' term',chartBar(a.dist_order.map((k,i)=>({label:k,value:a.dist[k],color:GRAD[Math.min(i,GRAD.length-1)]})))),
    card('Average score by term',chartLine(a.trend.map(x=>'Term '+x.term),[{name:'School average',color:'#b58a2c',values:a.trend.map(x=>x.avg)}])),
    card('Average score by class',chartHBar(a.class_avg.map(x=>({label:x.name,value:x.avg})),{suffix:''})),
    card('Subject averages',chartHBar(a.subjects.map(x=>({label:x.name,value:x.avg,color:x.avg>=50?'#2f7d6d':x.avg>=40?'#b58a2c':'#c4161c'}))),`<select onchange="S.dc=+this.value;render()">${a.class_options.map(c=>`<option value="${c.id}" ${c.id===a.class_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select>`),
    card('Top pupils',a.top.length?`<table class="t"><tr><th>#</th><th>Pupil</th><th>Class</th><th>Avg</th></tr>${a.top.map((p,i)=>`<tr><td>${i+1}</td><td>${esc(p.name)}</td><td>${esc(p.class)}</td><td><b>${p.avg}</b></td></tr>`).join('')}</table>`:'<div class="empty-chart">No results yet</div>')];
  if(f)ch.push(card('Billed vs collected',chartGroup(f.per_term.map(x=>x.name.replace(' term','')),[{name:'Billed',color:'#16213e',values:f.per_term.map(x=>x.billed)},{name:'Collected',color:'#2f7d6d',values:f.per_term.map(x=>x.paid)}])),
    card('Money in and out (12 months)',chartLine(f.months.map(m=>m.m.slice(5)),[{name:'Received',color:'#2f7d6d',values:f.months.map(m=>m.in)},{name:'Spent',color:'#c4161c',values:f.months.map(m=>m.out)}])));
  return `${trialCTA()}<div class="tools" style="margin-bottom:12px">${termSel(false)}</div><div class="kpis">${kp.join('')}</div><div class="cgrid">${ch.join('')}</div>
  <div class="panel"><div class="tools"><button class="btn gold" onclick="go('students')">Add pupils</button><button class="btn alt" onclick="go('scores')">Enter scores</button><button class="btn alt" onclick="go('reports')">Report sheets</button><button class="btn alt" onclick="go('msgs')">Messages</button></div>
  <h3 style="margin-bottom:8px">Results entered, ${esc(S.session)}</h3><div class="tw"><table class="t"><tr><th>Class</th><th>Pupils</th><th>1st term</th><th>2nd term</th><th>3rd term</th></tr>${prog.progress.map(r=>`<tr><td>${esc(r.class)}</td><td>${r.pupils}</td><td>${r.t1} of ${r.pupils}</td><td>${r.t2} of ${r.pupils}</td><td>${r.t3} of ${r.pupils}</td></tr>`).join('')}</table></div></div>
  ${isA?`<div class="panel"><h3>Compare with your sample sheets</h3><p class="note" style="font-size:13px">Adds one pupil whose scores reproduce the sample sheets (Mathematics 44, 64 and 84; school bill ₦65,533). Delete the pupil when you are done.</p><button class="btn" onclick="addDemo()">Add sample pupil</button></div>`:''}`;
}
async function addDemo(){const r=await api('demo',{});await loadClasses();S.sid=r.id;S.t=3;go('reports')}
async function pFDash(){
  const [f,d]=await Promise.all([api(`stats/finance?session=${enc(S.session)}`),api(`fin/summary?session=${enc(S.session)}&term=`)]);
  const kp=[kpi('dollar','₦'+shortN(f.billed),`Billed (${f.invoices} invoices)`,'#16213e'),kpi('check','₦'+shortN(f.paid),'Collected','#2f7d6d'),kpi('alert','₦'+shortN(f.balance),'Outstanding','#c4161c'),kpi('pct',f.rate+'%','Collection rate','#b58a2c'),
    kpi('clock',f.overdue,'Overdue invoices','#d97a2b'),kpi('users',f.debtors,'Pupils who owe','#8e6bbf'),kpi('trend','₦'+shortN(f.income_total),'Total income received','#2f7d6d'),kpi('wallet','₦'+shortN(f.expense_total),'Total expenses','#c4161c'),
    kpi('award',(f.net<0?'-':'')+'₦'+shortN(Math.abs(f.net)),f.net>=0?'Surplus':'Deficit','#16213e'),kpi('inbox',f.unread,'Unread messages','#c4161c')];
  const ch=[card('Money in and out (12 months)',chartLine(f.months.map(m=>m.m.slice(5)),[{name:'Received',color:'#2f7d6d',values:f.months.map(m=>m.in)},{name:'Spent',color:'#c4161c',values:f.months.map(m=>m.out)}])),
    card('Billed vs collected by term',chartGroup(f.per_term.map(x=>x.name.replace(' term','')),[{name:'Billed',color:'#16213e',values:f.per_term.map(x=>x.billed)},{name:'Collected',color:'#2f7d6d',values:f.per_term.map(x=>x.paid)}])),
    card('Fee collection',chartDonut([{label:'Collected',value:f.paid,color:'#2f7d6d'},{label:'Outstanding',value:f.balance,color:'#c4161c'}],{center:f.rate+'%',sub:'collected',money:true})),
    card('Payment methods',chartDonut(f.methods.map(m=>({label:m.name,value:m.total})),{money:true,sub:'received'})),
    card('Expenses by category',chartDonut(f.expense_cats.map(m=>({label:m.name,value:m.total})),{money:true,sub:'spent'})),
    card('Debts by class',chartHBar(f.debtors_by_class.map(x=>({label:x.name,value:x.total,color:'#c4161c'})),{money:true})),
    card('Largest debtors',f.top_debtors.length?`<table class="t"><tr><th>Pupil</th><th>Class</th><th>Owes</th></tr>${f.top_debtors.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.cname)}</td><td><b>₦${NF(x.balance)}</b></td></tr>`).join('')}</table>`:'<div class="empty-chart">Nobody owes money</div>'),
    card('Cash and bank balances',chartHBar(f.accounts.map(a=>({label:a.name,value:Math.max(0,a.balance),color:'#16213e'})),{money:true}))];
  return `<div class="tools"><button class="btn gold" onclick="payForm()">Receive payment</button><button class="btn alt" onclick="genForm()">Generate invoices</button><button class="btn alt" onclick="expForm()">Record expense</button><button class="btn alt" onclick="go('msgs')">Messages</button></div>
  <div class="kpis">${kp.join('')}</div><div class="cgrid">${ch.join('')}</div>
  <div class="panel"><h3 style="margin-bottom:8px">Recent receipts</h3>${d.recent.length?`<div class="tw"><table class="t"><tr><th>Receipt</th><th>Date</th><th>From</th><th>Amount</th><th></th></tr>${d.recent.map(r=>`<tr><td>${esc(r.no)}</td><td>${fdate(r.rdate)}</td><td>${esc(r.sname||r.payer||r.category)}</td><td>₦${NF(r.amount)}</td><td><button class="btn alt sm" onclick="viewRcpt(${r.id})">View</button></td></tr>`).join('')}</table></div>`:'<div class="empty">No receipts yet.</div>'}</div>`;
}
/* ---------- pupil dashboard + results ---------- */
async function pResults(){
  const st=await api('stats/pupil'),f=st.fin;
  const kp=[kpi('inbox',st.unread,'Unread messages','#c4161c'),kpi('wallet','₦'+NF(f.balance),'School fees balance',f.balance>0?'#c4161c':'#2f7d6d')];
  let ch=[];
  if(st.released&&st.terms){
    const lt=st.latest;
    if(lt)kp.unshift(kpi('award',lt.position||'-',`Position, ${TN[lt.term].toLowerCase()} term (of ${st.n_in_class})`,'#b58a2c'),kpi('trend',lt.avg,'Average score','#16213e'),kpi('book',lt.total,'Total score','#2f7d6d'));
    const att=st.terms.filter(t=>t.opened);if(att.length){const t=att[att.length-1];kp.push(kpi('cal',Math.round(t.present/t.opened*100)+'%','Attendance, latest term','#d97a2b'))}
    ch=[card('My average by term',chartBar(st.terms.map(t=>({label:'Term '+t.term,value:t.has?t.avg:0,color:'#b58a2c'})))),
      card('Subject scores'+(lt?', '+TN[lt.term].toLowerCase()+' term':''),lt?chartHBar(lt.subjects.map(x=>({label:x.name,value:x.total,color:GCOL[String(x.grade||'F').charAt(0)]}))):'<div class="empty-chart">No scores yet</div>')];
  }
  const head=`<div class="kpis">${kp.join('')}</div>${ch.length?`<div class="cgrid">${ch.join('')}</div>`:''}`;
  if(!st.released)return head+'<div class="panel empty">Your results have not been released yet.</div>';
  const d=await api(`sheet?term=${S.t}&session=${enc(S.session)}`);
  return head+`<div class="panel"><div class="tools">${termSel(true)}<label>Session<select onchange="S.session=this.value;render()">${S.sessions.map(x=>`<option ${x===S.session?'selected':''}>${esc(x)}</option>`).join('')}</select></label><button class="btn gold" onclick="printHTML('<div class=page>'+window._mine+'</div>')">Print or save as PDF</button></div><div class="prevwrap" id="pw">${(window._mine=sheetHTML(d))}</div></div>`;
}

/* ======================= users (admin) ======================= */
const ROLES={admin:'Administrator',staff:'Teacher',accountant:'Accountant',student:'Pupil'};
async function pUsers(){
  const f=F.us=F.us||{role:'',status:'',q:''};
  const d=await api(`users?role=${f.role}&status=${f.status}&q=${enc(f.q)}`);D.users=d.rows;
  const susp=d.rows.filter(u=>u.status==='suspended').length;
  const kp=[kpi('users',(d.counts.admin||0)+(d.counts.staff||0)+(d.counts.accountant||0),'Staff accounts','#16213e'),kpi('book',d.counts.staff||0,'Teachers','#5b7db1'),kpi('dollar',d.counts.accountant||0,'Accountants','#2f7d6d'),kpi('school',d.counts.student||0,'Pupil accounts','#8e6bbf'),kpi('ban',susp,'Suspended in this list','#c4161c')];
  return `<div class="kpis">${kp.join('')}</div><div class="panel"><div class="tools"><label>Role<select onchange="F.us.role=this.value;render()"><option value="">All roles</option>${Object.entries(ROLES).map(([k,v])=>`<option value="${k}" ${f.role===k?'selected':''}>${v}</option>`).join('')}</select></label>
  <label>Status<select onchange="F.us.status=this.value;render()"><option value="">All</option><option value="active" ${f.status==='active'?'selected':''}>Active</option><option value="suspended" ${f.status==='suspended'?'selected':''}>Suspended</option></select></label>
  <label>Search<input type="text" value="${esc(f.q)}" placeholder="Name or username" onchange="F.us.q=this.value;render()"></label><button class="btn gold" onclick="userForm()">Add user</button></div>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>Name</th><th>Username</th><th>Role</th><th>Class</th><th>Status</th><th>Last sign-in</th><th>Actions</th></tr>${d.rows.map(u=>`<tr><td>${esc(u.name)}</td><td>${esc(u.username)}</td><td>${ROLES[u.role]}</td><td>${esc(u.cname)}</td><td><span class="pill ${u.status==='active'?'ok':'bad'}">${u.status==='active'?'Active':'Suspended'}</span></td><td>${esc(u.last_login||'never')}</td>
  <td style="white-space:nowrap"><button class="btn alt sm" onclick="${u.role==='student'?`S.cid=${u.class_id};go('students')`:`userForm(${u.id})`}">Edit</button> <button class="btn alt sm" onclick="resetForm(${u.id})">Reset password</button> ${u.id===d.me?'':`<button class="btn alt sm" onclick="setStatus(${u.id},'${u.status==='active'?'suspended':'active'}')">${u.status==='active'?'Suspend':'Activate'}</button> <button class="btn danger sm" onclick="delUser(${u.id})">Delete</button>`}</td></tr>`).join('')}</table></div>`:'<div class="empty">No users match.</div>'}
  <p class="note">Pupils are added from the Pupils page. The key icon resets a password, the circle icon suspends or re-activates a user, and the bin deletes. Pupils with fee records cannot be deleted, so suspend them instead.</p></div>`;
}
function userForm(id){
  const u=id?D.users.find(x=>x.id===id):{name:'',username:'',role:'staff'};
  openModal(`<h2>${id?'Edit user':'Add user'}</h2><div class="fgrid"><div class="fld"><label>Full name<input type="text" id="un" value="${esc(u.name)}"></label></div><div class="fld"><label>Username<input type="text" id="uu" value="${esc(u.username)}" autocomplete="off"></label></div>
  <div class="fld"><label>Role<select id="ur"><option value="staff" ${u.role==='staff'?'selected':''}>Teacher (results and pupils)</option><option value="accountant" ${u.role==='accountant'?'selected':''}>Accountant (fees and accounts)</option><option value="admin" ${u.role==='admin'?'selected':''}>Administrator (everything)</option></select></label></div>
  <div class="fld"><label>${id?'New password (leave empty to keep)':'Password'}<input type="text" id="up" autocomplete="off" placeholder="${id?'':'At least 4 characters'}"></label></div></div>
  <div class="mact"><button class="btn alt" onclick="document.getElementById('up').value=tempPw()">Generate password</button><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="saveUser(${id||0})">Save</button></div>`);
}
const tempPw=()=>{const a='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';let s='';const r=new Uint32Array(8);(window.crypto||{getRandomValues:x=>x.forEach((_,i)=>x[i]=Math.random()*4e9)}).getRandomValues(r);r.forEach(x=>s+=a[x%a.length]);return s};
async function saveUser(id){const b={name:$('#un').value,username:$('#uu').value,role:$('#ur').value,password:$('#up').value};if(id)b.id=id;await api('staff',b);closeModal();toast(id?'User updated':'User created',true);render()}
function resetForm(id){
  const u=D.users.find(x=>x.id===id),pupil=u.role==='student';
  openModal(`<h2>Reset password</h2><p><b>${esc(u.name)}</b> (${esc(u.username)})</p><div class="fld"><label>${pupil?'New password (leave empty to reset to the Reg No)':'New password (leave empty to generate a temporary one)'}<input type="text" id="rp1" autocomplete="off"></label></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="doReset(${id})">Reset password</button></div>`);
}
async function doReset(id){const r=await api('users/reset'+'pw',{id,password:$('#rp1').value});openModal(`<h2>Password reset</h2><p>Give <b>${esc(r.name)}</b> this password. They can change it after signing in.</p><div class="pwshow">${esc(r.password)}</div><p class="note">Username: <b>${esc(r.username)}</b>. This password is shown only now.</p><div class="mact"><button class="btn alt" onclick="copyText('${esc(r.password)}')">Copy</button><button class="btn" onclick="closeModal();render()">Done</button></div>`)}
function copyText(t){if(navigator.clipboard)navigator.clipboard.writeText(t).then(()=>toast('Copied',true));else toast(t,true)}
function setStatus(id,st){ask(st==='suspended'?'Suspend this user? They are signed out and cannot sign in until you activate them again.':'Activate this user so they can sign in again?',async()=>{await api('users/status',{id,status:st});toast(st==='suspended'?'User suspended':'User activated',true);render()})}
function delUser(id){ask('Delete this user permanently? This cannot be undone.',async()=>{await api('users/delete',{id});toast('User deleted',true);render()})}

/* ======================= messages (all users) ======================= */
async function pMsgs(){
  const f=F.ms=F.ms||{box:'inbox',q:'',page:1};
  const d=await api(`messages?box=${f.box}&q=${enc(f.q)}&page=${f.page}`);S.unread=d.unread;
  return `<div class="panel"><div class="tools"><button class="btn gold" onclick="composeForm()">New message</button><button class="btn ${f.box==='inbox'?'':'alt'}" onclick="F.ms.box='inbox';F.ms.page=1;render()">Inbox${d.unread?`<span class="badge">${d.unread}</span>`:''}</button><button class="btn ${f.box==='sent'?'':'alt'}" onclick="F.ms.box='sent';F.ms.page=1;render()">Sent</button>
  <label>Search<input type="text" value="${esc(f.q)}" placeholder="Subject or text" onchange="F.ms.q=this.value;F.ms.page=1;render()"></label>${f.box==='inbox'&&d.unread?'<button class="btn alt" onclick="readAll()">Mark all read</button>':''}</div>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>${f.box==='sent'?'To':'From'}</th><th>Subject</th><th>Date</th><th>Actions</th></tr>${d.rows.map(m=>`<tr class="msgrow ${m.read?'':'unread'}" onclick="openMsg(${m.id})"><td>${esc(f.box==='sent'?m.to:m.from)}${f.box==='sent'?'':` <span class="pill">${ROLES[m.role]||''}</span>`}</td><td>${esc(m.subject)}<div class="note" style="margin:0">${esc(m.preview)}</div></td><td style="white-space:nowrap">${esc(m.created.slice(0,16))}</td>
  <td style="white-space:nowrap" onclick="event.stopPropagation()"><button class="btn alt sm" onclick="openMsg(${m.id})">View</button>${f.box==='inbox'?` <button class="btn alt sm" onclick="replyMsg(${m.id})">Reply</button>`:''} <button class="btn danger sm" onclick="delMsg(${m.id})">Delete</button></td></tr>`).join('')}</table></div>
  <div class="tools" style="margin-top:10px"><button class="btn alt" ${f.page<=1?'disabled':''} onclick="F.ms.page--;render()">Newer</button><button class="btn alt" ${d.rows.length<30?'disabled':''} onclick="F.ms.page++;render()">Older</button></div>`:`<div class="empty">${f.box==='inbox'?'Your inbox is empty.':'You have not sent any messages.'}</div>`}</div>`;
}
async function openMsg(id){
  const m=await api('messages/get?id='+id);const cur=S.unread;
  openModal(`<h2>${esc(m.subject)}</h2><p class="note" style="margin:0">From <b>${esc(m.from)}</b> (${ROLES[m.role]||''}) to <b>${esc(m.to)}</b> · ${esc(m.created.slice(0,16))}</p><div class="msgbody">${esc(m.body)}</div>
  <div class="mact">${m.mine?'':`<button class="btn" onclick="replyMsg(${m.id})">Reply</button>`}<button class="btn danger" onclick="closeModal();delMsg(${m.id})">Delete</button>${S.user.role==='admin'?`<button class="btn alt" onclick="delMsgAll(${m.id})">Delete for everyone</button>`:''}<button class="btn alt" onclick="closeModal()">Close</button></div>`);
  pollMsgs();if(S.page==='msgs')setTimeout(()=>{if(S.page==='msgs'&&!$('#modal').classList.contains('on'))render()},0);
}
function delMsg(id){ask('Delete this message from your list?',async()=>{await api('messages/delete',{id});render()})}
function delMsgAll(id){ask('Delete this message for everyone?',async()=>{await api('messages/delete',{id,everyone:true});closeModal();render()})}
async function readAll(){await api('messages/readall',{});pollMsgs();render()}
async function replyMsg(id){const m=await api('messages/get?id='+id);await composeForm('user:'+m.sender_id,'Re: '+m.subject.replace(/^Re: /,''))}
async function composeForm(to,subject){
  const d=await api('messages/directory'),stf=S.user.role!=='student';
  const grp=(r,l)=>{const u=d.users.filter(x=>x.role===r);return u.length?`<optgroup label="${l}">${u.map(x=>`<option value="user:${x.id}" ${to==='user:'+x.id?'selected':''}>${esc(x.name)}${x.cname?' ('+esc(x.cname)+')':''}</option>`).join('')}</optgroup>`:''};
  openModal(`<h2>New message</h2><div class="fld"><label>To<input type="text" id="mfilter" placeholder="Type to find a person" oninput="msgFilter()"></label></div>
  <div class="fld" style="margin-top:8px"><select id="mto" size="1" style="width:100%"><option value="all">Everyone</option>${stf?`<optgroup label="Groups">${Object.entries({'role:staff':'All teachers','role:accountant':'Accountants','role:admin':'Administrators','role:student':'All pupils'}).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</optgroup>${d.classes.length?`<optgroup label="Whole class">${d.classes.map(c=>`<option value="class:${c.id}">Class ${esc(c.name)}</option>`).join('')}</optgroup>`:''}`:''}
  ${grp('admin','Administrators')}${grp('staff','Teachers')}${grp('accountant','Accountants')}${grp('student','Pupils')}</select></div>
  <div class="fld" style="margin-top:8px"><label>Subject<input type="text" id="msub" value="${esc(subject||'')}"></label></div><div class="fld" style="margin-top:8px"><label>Message<textarea id="mbody" rows="6"></textarea></label></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn gold" onclick="sendMsg()">Send</button></div>`,false);
  if(to)$('#mto').value=to;
}
function msgFilter(){const q=$('#mfilter').value.toLowerCase();[...$('#mto').options].forEach(o=>{o.hidden=!!q&&!o.text.toLowerCase().includes(q)});const f=[...$('#mto').options].find(o=>!o.hidden&&o.value!=='all'||(!q&&o.value==='all'));if(f&&q)$('#mto').value=f.value}
async function sendMsg(){await api('messages',{to:$('#mto').value,subject:$('#msub').value,body:$('#mbody').value});closeModal();toast('Message sent',true);if(S.page==='msgs')render()}
let lastUnread=null;
async function pollMsgs(){if(!S.user)return;try{const r=await api('messages/unread');if(lastUnread!==null&&r.unread>lastUnread)toast('You have a new message',true);lastUnread=r.unread;if(r.unread!==S.unread){S.unread=r.unread;badges()}}catch(e){}}
function badges(){document.querySelectorAll('.gnav button,.tnav button,#side button').forEach(b=>{const k=b.textContent.replace(/\d+$/,'').trim();if(k==='Messages'){const o=b.querySelector('.badge');if(o)o.remove();if(S.unread)b.insertAdjacentHTML('beforeend',`<span class="badge">${S.unread}</span>`)}})}

/* ======================= forgot password and recovery key ======================= */
async function forgotModal(){
  let i={iid:'',email:'technologyokv@gmail.com',whatsapp:'+2348104141138'};try{i=await api('recover/info')}catch(e){}
  openModal(`<h2>Forgot your password?</h2>
  <h3 style="font-size:16px;margin:8px 0 4px">Pupils, teachers and accountants</h3><p>Ask your school <b>administrator</b> to reset it. They open <b>Admin, Users</b>, press the key icon beside your name and give you a new password. A pupil reset sets the password back to the Reg No.</p>
  <h3 style="font-size:16px;margin:14px 0 4px">Administrators</h3><p>Use <b>one</b> of these two ways:</p>
  <ol style="line-height:1.6"><li><b>Recovery key.</b> The system showed you a key starting <code>RK-</code> the first time you signed in. Enter it below.</li><li><b>Reset code from OKV Technology Consults.</b> Send your <b>Installation ID</b> (below) to <a href="mailto:${esc(i.email)}">${esc(i.email)}</a> or WhatsApp ${esc(i.whatsapp)}, with proof that you are the school administrator. We reply with a code that works only on this computer for 24 hours and only once.</li></ol>
  <div class="note" style="margin:6px 0 10px">Installation ID: <b>${esc(i.iid)}</b></div>
  <div class="fgrid"><div class="fld"><label>Administrator username<input type="text" id="fu" value="admin"></label></div><div class="fld"><label>New password (6 or more characters)<input type="password" id="fp"></label></div></div>
  <div class="fld" style="margin-top:8px"><label>Recovery key or reset code<textarea id="fk" rows="3" placeholder="RK-XXXX-XXXX-XXXX-XXXX  or  OKVR-..."></textarea></label></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn gold" onclick="doRecover()">Reset administrator password</button></div>`);
}
async function doRecover(){const k=$('#fk').value.trim();await api('recover',{method:/^OKVR-/i.test(k)?'okv':'key',username:$('#fu').value,secret:k,password:$('#fp').value});closeModal();toast('Password reset. Sign in with the new password.',true)}
async function recoveryModal(){
  let r;try{r=await api('recovery/pending')}catch(e){return}if(!r.key)return;
  openModal(`<h2>Save your recovery key</h2><p>If you ever forget the administrator password, this key lets you set a new one. <b>Write it down or print it and keep it somewhere safe.</b> It is shown only once.</p><div class="pwshow">${esc(r.key)}</div>
  <div class="mact"><button class="btn alt" onclick="copyText('${esc(r.key)}')">Copy</button><button class="btn alt" onclick="printHTML('<div class=free><h2>Recovery key</h2><p>School Result and Accounting Management System</p><p style=&quot;font:700 26px monospace&quot;>${esc(r.key)}</p><p>Keep this paper safe.</p></div>')">Print</button><button class="btn" onclick="ackRecovery()">I have saved it</button></div>`);
}
async function ackRecovery(){await api('recovery/ack',{});closeModal();toast('Recovery key saved. It will not be shown again.',true)}
async function regenKey(){openModal(`<h2>New recovery key</h2><p>The old key stops working. Enter your password to continue.</p><div class="fld"><label>Your password<input type="password" id="rkp"></label></div><div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="doRegen()">Create new key</button></div>`)}
async function doRegen(){await api('recovery/regenerate',{password:$('#rkp').value});closeModal();await recoveryModal()}
const cookieOk=()=>{try{return localStorage.getItem('ck_ok')==='1'}catch(e){return false}};
function cookieBar(){if(cookieOk()||$('.cookiebar'))return;const d=document.createElement('div');d.className='cookiebar';d.innerHTML='<span>This system uses one strictly necessary cookie to keep you signed in. No tracking or advertising. <a href="/legal/cookies" target="_blank">Cookie policy</a></span><button onclick="try{localStorage.setItem(\'ck_ok\',\'1\')}catch(e){};this.parentNode.remove()">OK</button>';document.body.appendChild(d)}

/* ======================= downloads: CSV and print for any table ======================= */
function mainTable(){return [...document.querySelectorAll('#view table.t')].sort((a,b)=>b.rows.length-a.rows.length)[0]}
function keepCols(t){const heads=[...t.rows[0].cells];return heads.map((h,i)=>{const txt=h.innerText.trim();if(txt==='Actions'||txt==='')return false;const cell=t.rows[1]&&t.rows[1].cells[i];return !(cell&&cell.querySelector('input[type=checkbox],input[type=number],select,button.ib,.thumb'))||txt!==''&&!(cell.querySelector('input[type=checkbox]')||cell.querySelector('.thumb'))})}
function tableData(t){const keep=keepCols(t);return [...t.rows].filter(r=>r.cells.length>1||r.cells[0].colSpan<2).map(r=>[...r.cells].filter((c,i)=>keep[i]!==false||r.cells.length!==t.rows[0].cells.length).map(c=>{const inp=c.querySelector('input:not([type=checkbox])');return(inp?inp.value:c.innerText).replace(/\s+/g,' ').trim()}))}
function printTable(){
  const t=mainTable();if(!t){toast('Nothing to print here');return}
  const rows=tableData(t);const title=(TABS_LABEL[S.page]||S.page);
  printHTML(`<div class="free"><h2 style="font-family:Georgia">${esc((S.info&&S.info.name)||document.getElementById('schoolLine').textContent)}</h2><p>${esc(title)} &middot; ${esc(S.session)} &middot; ${fdate(today())}</p><table style="border-collapse:collapse;width:100%;font-size:10px" border="1" cellpadding="3">${rows.map((r,i)=>'<tr>'+r.map(c=>i?`<td>${esc(c)}</td>`:`<th style="background:#eee">${esc(c)}</th>`).join('')+'</tr>').join('')}</table></div>`);
}
const TABS_LABEL={dash:'Dashboard',students:'Pupils',classes:'Classes and subjects',scores:'Scores',reports:'Report sheets',board:'Broadsheet',fees:'Fee schedule',invoices:'Invoices',receipts:'Receipts',expenses:'Expenses',debtors:'Debtors',cash:'Cash book',freports:'Financial report',users:'Users',msgs:'Messages',clearance:'Clearances'};
/* ======================= fee types (common and custom) ======================= */
async function loadFeeTypes(){S.feeTypes=await api('fee-types');return S.feeTypes}
const feeList=()=>`<datalist id="ftl">${(S.feeTypes||[]).filter(f=>f.active).map(f=>`<option value="${esc(f.name)}"></option>`).join('')}</datalist>`;
function feeAuto(prefix,i){const n=$('#'+prefix+'l'+i).value.trim().toUpperCase(),f=(S.feeTypes||[]).find(x=>x.name===n),a=$('#'+prefix+'a'+i);if(f&&f.amount&&!+a.value)a.value=f.amount}
async function feeTypesForm(){
  await loadFeeTypes();
  openModal(`<h2>Fee types</h2><p class="note">Common school payments are ready. Add your own, for example EXCURSION TO ABUJA, and pick them when you set class fees or raise an invoice. A default amount is filled in for you.</p>
  <div class="tw" style="max-height:46vh;overflow:auto"><table class="t"><tr><th>Fee</th><th>Default amount</th><th>Actions</th></tr>${S.feeTypes.map(f=>`<tr><td>${esc(f.name)}${f.custom?' <span class="pill gold">custom</span>':''}</td><td><input type="number" min="0" value="${f.amount||''}" style="width:110px" onchange="saveFeeType(${f.id},'${esc(f.name).replace(/'/g,'')}',this.value)"></td><td>${f.custom?`<button class="btn danger sm" onclick="delFeeType(${f.id})">Delete</button>`:''}</td></tr>`).join('')}</table></div>
  <div class="fgrid" style="margin-top:12px;grid-template-columns:2fr 1fr auto"><input type="text" id="nf" placeholder="New fee name"><input type="number" id="nfa" min="0" placeholder="Amount"><button class="btn gold" onclick="addFeeType()">Add</button></div><div class="mact"><button class="btn" onclick="closeModal();render()">Done</button></div>`,true);
}
async function saveFeeType(id,name,amount){await api('fee-types',{id,name,amount})}
async function addFeeType(){await api('fee-types',{name:$('#nf').value,amount:$('#nfa').value});await feeTypesForm()}
function delFeeType(id){api('fee-types/delete',{id}).then(feeTypesForm)}

/* ======================= clearance, voucher and reminder documents ======================= */
function clearanceHTML(d){
  const sc=d.school,ok=d.cleared||d.provisional;
  return `<div class="doc">${d.provisional?'<div class="stamp" style="border-color:#b58a2c;color:#8b6a1b">PROVISIONAL</div>':d.cleared?'<div class="stamp">CLEARED</div>':'<div class="stamp void">OWING</div>'}${docHead(sc)}<div class="dt">FEE CLEARANCE CERTIFICATE</div>
  <div class="meta"><div><b>Certificate No:</b> ${esc(d.no||'(preview)')}</div><div><b>Date:</b> ${fdate(d.issued||today())}</div><div><b>Pupil:</b> ${esc(d.student.name)}</div><div><b>Reg No:</b> ${esc(d.student.reg)}</div><div><b>Class:</b> ${esc(d.student.cname)}</div><div><b>Period:</b> ${esc(d.session)}${d.term?' - '+termLbl(d.term):' (whole session)'}</div></div>
  <p style="margin:12px 0">This is to certify that <b>${esc(d.student.name)}</b> of <b>${esc(d.student.cname)}</b> ${d.cleared?'has paid all school fees invoiced':d.provisional?'has been given <b>provisional</b> clearance although a balance of ₦'+NF(d.balance)+' remains':'still owes ₦'+NF(d.balance)}${d.cleared||d.provisional?' for the period shown above':''}.</p>
  <table><tr><th>Invoice</th><th>Term</th><th class="r">Total (₦)</th><th class="r">Paid (₦)</th><th class="r">Balance (₦)</th></tr>${d.invoices.map(i=>`<tr><td>${esc(i.no)}</td><td>${i.term?termLbl(i.term):'-'}</td><td class="r">${NF(i.total)}</td><td class="r">${NF(i.paid)}</td><td class="r">${NF(i.balance)}</td></tr>`).join('')||'<tr><td colspan="5">No invoices for this period.</td></tr>'}
  <tr><th colspan="2">Total</th><th class="r">${NF(d.billed)}</th><th class="r">${NF(d.paid)}</th><th class="r">${NF(d.balance)}</th></tr></table>
  ${d.note?`<p style="margin-top:10px"><b>Reason for provisional clearance:</b> ${esc(d.note)}</p>`:''}<p style="margin-top:10px;font-size:11px">Issued by: ${esc(d.issued_by||'')}</p>
  <div class="sig"><div>Bursar / Accountant</div><div>Head of School</div></div></div>`;
}
function voucherHTML(d){
  return `<div class="doc">${d.status==='void'?'<div class="stamp void">VOID</div>':''}${docHead(d.school)}<div class="dt">PAYMENT VOUCHER</div>
  <div class="meta"><div><b>Voucher No:</b> ${esc(d.no)}</div><div><b>Date:</b> ${fdate(d.edate)}</div><div><b>Paid to:</b> ${esc(d.payee)}</div><div><b>Method:</b> ${esc(d.method)}${d.ref?' ('+esc(d.ref)+')':''}</div><div><b>Category:</b> ${esc(d.category)}</div><div><b>Paid from:</b> ${esc(d.aname)}</div></div>
  <table><tr><th style="width:190px">Amount</th><td style="font:700 18px Arial">₦${NF(d.amount)}</td></tr><tr><th>The sum of</th><td>${esc(words(d.amount))}</td></tr><tr><th>Being payment for</th><td>${esc(d.description||d.category)}</td></tr></table>
  <p style="margin-top:8px;font-size:11px">Prepared by: ${esc(d.created_by)}</p><div class="sig"><div>Approved by</div><div>Received by (sign and date)</div></div></div>`;
}
function reminderHTML(d){
  return `<div class="doc rep">${docHead(d.school)}<div class="dt">SCHOOL FEES REMINDER</div><p>Date: ${fdate(today())}</p><p style="margin-top:10px">Dear Parent / Guardian of <b>${esc(d.student.name)}</b> (${esc(d.student.cname)}, Reg No ${esc(d.student.reg)}),</p>
  <p style="margin-top:8px">Our records show an outstanding school fees balance of <b>₦${NF(d.fin.balance)}</b>. Details of the account are below. Kindly settle the balance as soon as possible, and ignore this letter if you have paid in the last few days.</p>
  <table style="margin-top:10px"><tr><th>Invoice</th><th>Term</th><th class="r">Total (₦)</th><th class="r">Paid (₦)</th><th class="r">Balance (₦)</th></tr>${d.invoices.filter(i=>i.balance>0.004).map(i=>`<tr><td>${esc(i.no)}</td><td>${i.term?termLbl(i.term):'-'}</td><td class="r">${NF(i.total)}</td><td class="r">${NF(i.paid)}</td><td class="r">${NF(i.balance)}</td></tr>`).join('')}<tr><th colspan="4">Total outstanding</th><th class="r">${NF(d.fin.balance)}</th></tr></table>
  ${d.school.bank?`<p style="margin-top:10px"><b>Pay to:</b><br>${esc(d.school.bank).replace(/\n/g,'<br>')}</p>`:''}<p style="margin-top:10px">Thank you.</p><div class="sig"><div></div><div>Bursar / Accountant</div></div></div>`;
}
async function viewVoucher(id){showDoc(voucherHTML(await api('expense?id='+id)))}
async function reminder(id){showDoc(reminderHTML(await api('statement?student='+id)),true)}
async function pClearance(){
  const cl=await loadClasses();if(!cl)return noClass;
  const l=await api('students?class='+cl.id),rec=await api('clearances');
  if(!l.find(s=>s.id===S.sid))S.sid=l[0]&&l[0].id;
  const f=F.cl=F.cl||{term:0};let chk=null;if(S.sid)chk=await api(`clearance/check?student=${S.sid}&term=${f.term}&session=${enc(S.session)}`);
  return `<div class="panel"><div class="tools">${classSel()}<label>Pupil<select onchange="S.sid=+this.value;render()">${l.map(s=>`<option value="${s.id}" ${s.id===S.sid?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
  <label>Period<select onchange="F.cl.term=+this.value;render()"><option value="0">Whole session</option>${[1,2,3].map(x=>`<option value="${x}" ${f.term===x?'selected':''}>${TN[x]} term</option>`).join('')}</select></label></div>
  ${chk?`<div class="kpis">${kpi(chk.cleared?'check':'alert',chk.cleared?'Cleared':'Owing',chk.cleared?'All invoices paid':'Balance ₦'+NF(chk.balance),chk.cleared?'#2f7d6d':'#c4161c')}${kpi('dollar','₦'+NF(chk.billed),`Billed (${chk.n_invoices} invoices)`,'#16213e')}${kpi('wallet','₦'+NF(chk.paid),'Paid','#2f7d6d')}${kpi('alert','₦'+NF(chk.all_balance),'Total owed across all invoices','#c4161c')}</div>
  <div class="tools">${chk.cleared?`<button class="btn gold" onclick="issueClr(false)">Issue clearance certificate</button>`:`<button class="btn alt" onclick="provClr()">Issue provisional clearance</button><button class="btn" onclick="payForm(${S.sid})">Receive payment</button>`}<button class="btn alt" onclick="stmt(${S.sid})">Statement</button><button class="btn alt" onclick="reminder(${S.sid})">Reminder letter</button></div>`:'<div class="empty">Add pupils first.</div>'}</div>
  <div class="panel"><h3 style="margin-bottom:8px">Certificates issued</h3>${rec.length?`<div class="tw"><table class="t"><tr><th>No</th><th>Date</th><th>Pupil</th><th>Class</th><th>Period</th><th>Type</th><th>Actions</th></tr>${rec.map(r=>`<tr><td>${esc(r.no)}</td><td>${fdate(r.issued)}</td><td>${esc(r.sname)}</td><td>${esc(r.cname)}</td><td>${esc(r.session)} ${r.term?TN[r.term]:'(year)'}</td><td>${r.provisional?'<span class="pill gold">provisional</span>':'<span class="pill ok">full</span>'}</td><td><button class="btn alt sm" onclick="viewClr(${r.id})">View</button></td></tr>`).join('')}</table></div>`:'<div class="empty">No certificates issued yet.</div>'}</div>`;
}
async function issueClr(prov,note){const r=await api('clearance',{student_id:S.sid,session:S.session,term:F.cl.term,provisional:prov,note});closeModal();showDoc(clearanceHTML(r));render()}
function provClr(){openModal(`<h2>Provisional clearance</h2><p class="note">The pupil still owes money. Give the reason (for example, the parent promised to pay on Friday).</p><div class="fld"><label>Reason<textarea id="pn" rows="3"></textarea></label></div><div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="issueClr(true,$('#pn').value)">Issue</button></div>`)}
async function viewClr(id){showDoc(clearanceHTML(await api('clearance/doc?id='+id)))}

/* ======================= licence page: buy on the website, enter the code here ======================= */
async function pLicense(){
  const l=await api('license');S.lic=l;let info={};try{info=await api('license/info')}catch(e){}
  const price=info.price||l.price,buy=l.pricing_url;
  const st=l.state==='licensed'?kpi('check','Activated','Licensed to '+(l.licensee||'this school')+' on '+(l.issued||''),'#2f7d6d'):l.state==='trial'?kpi('clock',l.days_left+' days left','Free trial ends on '+l.expires,'#b58a2c'):kpi('alert','Trial ended',(l.reason==='clock'?'The computer date looks wrong. ':'')+'Activate to continue','#c4161c');
  const head=`<div class="kpis">${st}${kpi('key',`<span style="font-size:15px">${esc(l.installation_id||'')}</span>`,'Installation ID','#16213e')}${kpi('dollar','₦'+money(price),'One-time payment, no monthly fees','#2f7d6d')}</div>`;
  if(l.state==='licensed')return head+`<div class="panel"><h3>Thank you</h3><p>This installation is fully activated. Nothing more to do. Download a backup regularly from Settings.</p></div>`+svcCard(l);
  return head+`<div class="panel"><h3>1. Get your activation code</h3><p style="margin:6px 0 10px">Buying and requesting the code are done on our website, where you can pay by bank transfer or online, and upload your receipt.</p>
   ${buy?`<a class="btn gold" href="${esc(buy)}" target="_blank" rel="noopener" style="font-size:16px;padding:12px 22px">Buy full version / get activation code</a><p class="note">Opens the OKV Technology pricing page with your Installation ID filled in.</p>`:`<p class="note">The pricing page address is not set in this copy. Contact ${esc(l.support_email||'')} or WhatsApp ${esc(l.whatsapp||'')} to buy.</p>`}
   <ol style="line-height:1.8;margin-top:10px"><li>On the pricing page pay <b>₦${money(price)}</b> (bank transfer or Paystack).</li><li>If you paid by transfer, upload the payment receipt on that page. Paystack payments are confirmed automatically.</li><li>We email your <b>activation code</b> to the address you entered, within 24 hours and often much sooner.</li><li>Come back here, type the code below and press <b>Activate</b>.</li></ol></div>
  <div class="panel"><h3>2. Enter your activation code</h3><div class="tools" style="margin-top:8px"><label>Activation code<input type="text" id="lc" placeholder="OKV-XXXX-XXXX-XXXX" style="min-width:min(100%,300px);font:600 16px ui-monospace,Consolas,monospace;letter-spacing:1px;text-transform:uppercase"></label><button class="btn gold" onclick="doActivate()">Activate</button><button class="btn alt" onclick="copyText('${esc(l.installation_id||'')}')">Copy installation ID</button></div>
   <h4 style="margin:14px 0 6px;font-family:Georgia">Guidelines</h4><ul style="line-height:1.7;margin:0 0 0 18px"><li>Type or paste the code exactly as in the email. Capital letters and dashes are handled for you.</li><li>This computer must be <b>online</b> for this one step. After that the system works offline.</li><li>One code activates <b>one installation</b>. Do not share it.</li><li>"Code already used": it was activated on another computer. Contact us with your Installation ID.</li><li>"Not valid": check for a typo, such as the letter O and the number 0.</li><li>Reinstalling Windows or moving to a new computer changes the Installation ID. Contact us for a re-activation.</li><li>Your data is never deleted when the trial ends, and Backup still works.</li></ul></div>`+svcCard(l);
}
const svcCard=l=>`<div class="panel svc"><h3 style="font-size:16px">Installation and training service</h3><p style="margin:6px 0 0">Want us to set the system up for you? <b>OKV Technology Consults installs the software</b>, loads your classes, subjects and fees, trains your staff, and connects phones to your network, on site or remotely. Email ${esc(l.support_email||'')} or WhatsApp ${esc(l.whatsapp||'')} for a quote.</p></div>`;
async function doActivate(){await api('license/activate',{code:$('#lc').value});await refreshMe();toast('System activated. Thank you!',true);render()}
function upgrade(){go('license')}
function trialCTA(){
  if(!S.lic||S.lic.state!=='trial'||S.user.role!=='admin')return '';
  return `<div class="panel svc" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;justify-content:space-between"><div><h3 style="font-size:17px">Enjoying the free trial?</h3><p style="margin:4px 0 0">${S.lic.days_left} day${S.lic.days_left===1?'':'s'} left. Get the full version for one payment, with no monthly fees, and keep all the data you have entered.</p></div><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn gold" onclick="go('license')">Get the full version</button></div></div>`;
}
function licBanner(){
  const l=S.lic;if(!l||l.state==='licensed')return '';const n=l.days_left;
  return `<div class="trial ${n<=3?'warn':''}">Free trial: <b>${n} day${n===1?'':'s'}</b> left. ${S.user.role==='admin'?'<a href="#" onclick="go(\'license\');return false">Get the full version</a>':'Ask your administrator to upgrade.'}</div>`;
}
function trialModal(){
  if(!S.lic||S.lic.state!=='trial'||S.user.role!=='admin'||S.lic.days_left>3)return;try{if(sessionStorage.getItem('trial_nag'))return;sessionStorage.setItem('trial_nag','1')}catch(e){}
  openModal(`<h2>Your trial ends in ${S.lic.days_left} day${S.lic.days_left===1?'':'s'}</h2><p>Get the full version now so nothing is interrupted. Your data stays safe either way.</p><div class="mact"><button class="btn alt" onclick="closeModal()">Later</button><button class="btn gold" onclick="closeModal();go('license')">Get the full version</button></div>`);
}

/* ======================= themes, navigation icons, QR ======================= */
Object.assign(ICO,{grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 cog:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
 palette:'<circle cx="12" cy="12" r="10"/><circle cx="8" cy="9" r="1"/><circle cx="12" cy="7" r="1"/><circle cx="16" cy="9" r="1"/><path d="M12 22c-1.5 0-2-1-2-2 0-1.2 1-1.6 1-2.6 0-1-1-1.4-2-1.4H6"/>',
 qr:'<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v.01M14 20v.01M17 20h4v-3"/>',
 download:'<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
 upload:'<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
 userplus:'<path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/>',
 minus:'<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',phone:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
 logout:'<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>',lock:'<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>',help:'<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 015.8 1c0 2-3 3-3 3M12 17h.01"/>'});
const TAB_ICON={dash:'grid',students:'users',admissions:'userplus',classes:'school',scores:'edit',details:'cal',reports:'file',board:'list',data:'download',fdash:'trend',fees:'dollar',clearance:'award',invoices:'file',receipts:'wallet',expenses:'minus',debtors:'alert',cash:'book',freports:'pct',users:'users',customize:'palette',settings:'cog',license:'key',msgs:'inbox',results:'book'};
const GRP_ICON={Academics:'school',Accounting:'dollar',Admin:'cog',Messages:'inbox',Results:'book'};
const GROUPS=(()=>{
  const A=[['dash','Dashboard'],['students','Pupils'],['admissions','Admissions'],['classes','Classes & subjects'],['scores','Score entry'],['details','Attendance & remarks'],['reports','Report sheets'],['board','Broadsheet'],['data','Import & export']];
  const C=[['fdash','Overview'],['fees','Fee schedule'],['clearance','Clearance'],['invoices','Invoices'],['receipts','Receipts'],['expenses','Expenses'],['debtors','Debtors'],['cash','Cash book'],['freports','Reports'],['data','Import & export']];
  const M=['Messages',[['msgs','Messages']]];
  return {admin:[['Academics',A],['Accounting',C],['Admin',[['users','Users'],['customize','Customize'],['settings','Settings'],['license','License']]],M],staff:[['Academics',A],M],accountant:[['Accounting',C],M],student:[['Results',[['results','My results']]],M]};
})();
const THEMES={navy:{n:'Navy and gold',primary:'#16213e',accent:'#b58a2c',bg:'#eef0f4'},emerald:{n:'Emerald',primary:'#0b4f3a',accent:'#d4a017',bg:'#eef5f1'},royal:{n:'Royal blue',primary:'#1d3a8a',accent:'#f59e0b',bg:'#eef2fb'},
 crimson:{n:'Crimson',primary:'#7a1426',accent:'#d9a441',bg:'#f8eff0'},purple:{n:'Purple',primary:'#3f2a7a',accent:'#e0a82e',bg:'#f2eff9'},teal:{n:'Teal',primary:'#0f4c5c',accent:'#e36414',bg:'#eaf4f5'},
 slate:{n:'Slate',primary:'#2b3a4a',accent:'#e8a33d',bg:'#eef1f4'},rose:{n:'Rose',primary:'#8a1c4a',accent:'#f2b134',bg:'#faeff4'},forest:{n:'Forest',primary:'#1e4d2b',accent:'#c9a227',bg:'#eef4ee'},ocean:{n:'Ocean',primary:'#0b3d91',accent:'#00a6a6',bg:'#ecf3fb'}};
function personalTheme(){try{return JSON.parse(localStorage.getItem('ss_theme')||'null')}catch(e){return null}}
function applyTheme(){
  const t=personalTheme()||S.theme||{primary:'#16213e',accent:'#b58a2c',bg:'#eef0f4',dark:0},r=document.documentElement.style;
  r.setProperty('--navy',t.primary);r.setProperty('--gold',t.accent);r.setProperty('--bg',t.bg||'#eef0f4');document.body.classList.toggle('dark',!!t.dark);
  let m=document.querySelector('meta[name=theme-color]');if(!m){m=document.createElement('meta');m.name='theme-color';document.head.appendChild(m)}m.content=t.primary;
}
function setHH(){const t=document.querySelector('.top');if(t)document.documentElement.style.setProperty('--hh',t.offsetHeight+'px')}
window.addEventListener('resize',setHH);
function buildHeader(){
  const b=(i,l,on,id)=>`<button ${id?`id="${id}"`:''} onclick="${on}" title="${l}">${ic(i)}<span class="bt">${l}</span></button>`;
  $('#hdrBtns').innerHTML=b('qr','Phone (QR)','showQR()')+b('palette','Theme','themeModal()')+`<button id="upg" style="display:none;background:#b58a2c;border-color:#b58a2c" onclick="upgrade()">${ic('award')}<span class="bt">Upgrade</span></button><a class="mlink" href="/api/manual" title="User manual (PDF)">${ic('book')}<span class="bt">Manual</span></a>`+b('key','Password','pwForm()')+b('logout','Sign out','logout()');
}
async function showQR(path){
  let urls=[];try{urls=(await (await fetch('/api/lan')).json()).urls}catch(e){}
  if(!/^(localhost|127\.)/.test(location.hostname)&&!urls.some(u=>u.includes(location.host)))urls.unshift(location.origin);
  if(!urls.length)urls=[location.origin];
  const full=urls.map(u=>u+(path||''));
  openModal(`<h2>${path?'Online admission form':'Open on a phone or tablet'}</h2><p class="note">Connect the phone to the <b>same Wi-Fi or network</b> as the school computer, then scan the code with the camera. It opens ${path?'the admission form':'the system'} in the browser. ${path?'':'The code only opens the web address. You still sign in with your own username and password.'}</p>
  ${full.map(u=>`<div class="qrbox"><img alt="QR code for ${esc(u)}" src="/api/qr?text=${enc(u)}"><div><b style="word-break:break-all">${esc(u)}</b><p class="note">If there are several addresses, try the one that starts with 192.168 or 10.</p><button class="btn alt sm" onclick="copyText('${esc(u)}')">Copy address</button> <button class="btn alt sm" onclick="printHTML('<div class=free style=text-align:center><h2>${esc(path?'Apply online':'Open the school system')}</h2><img src=/api/qr?text=${enc(u)} width=320><p style=font-size:18px>${esc(u)}</p></div>')">Print</button></div></div>`).join('')}
  <div class="mact"><button class="btn" onclick="closeModal()">Close</button></div>`);
}
function themeModal(){
  const cur=personalTheme(),t=cur||S.theme||THEMES.navy;
  openModal(`<h2>Colour theme</h2><p class="note">Pick the colours you like. This changes only your own screen. ${S.user&&S.user.role==='admin'?'Set the school default under Admin, Customize.':''}</p><div class="themes">${Object.entries(THEMES).map(([k,v])=>`<div class="tile ${t.primary===v.primary&&t.accent===v.accent?'on':''}" onclick="setPersonal('${k}')"><i><b style="background:${v.primary}"></b><b style="background:${v.accent}"></b><b style="background:${v.bg}"></b></i><span>${v.n}</span></div>`).join('')}</div>
  <div class="fgrid" style="margin-top:12px"><div class="fld"><label>Main colour<input type="color" id="tp" value="${t.primary}" onchange="setPersonalCustom()"></label></div><div class="fld"><label>Accent colour<input type="color" id="ta" value="${t.accent}" onchange="setPersonalCustom()"></label></div><div class="fld"><label class="chk" style="margin-top:20px"><input type="checkbox" id="td" ${t.dark?'checked':''} onchange="setPersonalCustom()"> Dark mode</label></div></div>
  <div class="mact"><button class="btn alt" onclick="resetPersonal()">Use the school colours</button><button class="btn" onclick="closeModal()">Done</button></div>`);
}
function setPersonal(k){const v=THEMES[k];const dark=$('#td')?$('#td').checked:0;localStorage.setItem('ss_theme',JSON.stringify({name:k,primary:v.primary,accent:v.accent,bg:v.bg,dark:dark?1:0}));applyTheme();themeModal()}
function setPersonalCustom(){const p=$('#tp').value,a=$('#ta').value,d=$('#td').checked;localStorage.setItem('ss_theme',JSON.stringify({name:'custom',primary:p,accent:a,bg:d?'#0e1320':'#eef0f4',dark:d?1:0}));applyTheme()}
function resetPersonal(){localStorage.removeItem('ss_theme');applyTheme();themeModal()}
/* ---- navigation with icons ---- */
let rtok=0;
async function render(){
  const my=++rtok;
  if(typeof pend!=='undefined'&&Object.keys(pend).length)await flush();
  const gs=GROUPS[S.user.role];
  if(S.lic&&S.lic.state==='expired'){
    if(S.user.role==='admin')S.page='license';
    else{$('#nav').innerHTML='';$('#view').innerHTML='<div class="panel empty">The free trial has ended. Please ask the administrator to activate the system.</div>';return}
  }
  const cur=gs.find(g=>g[1].some(t=>t[0]===S.page))||gs[0];
  const tb=t=>`<button class="${S.page===t[0]?'on':''}" onclick="go('${t[0]}')" title="${esc(t[1])}" aria-label="${esc(t[1])}">${ic(TAB_ICON[t[0]]||'grid')}<span class="tl">${t[1]}</span></button>`;
  $('#nav').innerHTML=(gs.length>1?`<div class="gnav">${gs.map(g=>`<button class="${g===cur?'on':''}" onclick="go('${g[1][0][0]}')" aria-label="${g[0]}">${ic(GRP_ICON[g[0]]||'grid')}<span>${g[0]}</span>${g[1].some(t=>t[0]==='msgs')&&S.unread?'<span class="badge">'+S.unread+'</span>':''}</button>`).join('')}</div>`:'')+`<div class="tnav">${cur[1].map(tb).join('')}</div>`;
  $('#side').innerHTML=gs.map(g=>`<div class="sg"><div class="sh">${ic(GRP_ICON[g[0]]||'grid')}<span>${g[0]}</span></div>${g[1].map(t=>`<button class="${S.page===t[0]?'on':''}" onclick="go('${t[0]}')" title="${esc(t[1])}">${ic(TAB_ICON[t[0]]||'grid')}<span class="tl">${t[1]}</span></button>`).join('')}</div>`).join('');
  setHH();
  try{const h=await PAGES[S.page]();if(my!==rtok)return;$('#view').innerHTML=licBanner()+h;fitPreview();addExport();decorateActions(document.getElementById('view'));badges();window.scrollTo(0,0)}
  catch(e){if(my===rtok&&e.message)$('#view').innerHTML=`<div class="panel empty">${esc(e.message)}</div>`}
}
/* ======================= report sheet (configurable) ======================= */
const FONTS={calibri:'Calibri,Carlito,Arial,sans-serif',arial:'Arial,Helvetica,sans-serif',times:'"Times New Roman",Times,serif',georgia:'Georgia,serif',verdana:'Verdana,Geneva,sans-serif'};
const ORD=['1ST','2ND','3RD'];
const gradeOf=(bands,t)=>{for(const b of bands)if(t>=b[0])return b;return bands[bands.length-1]};
function sheetHTML(d){
  const Y=d.Y,sc=d.school,st=d.student,L=d.layout||{},nca=d.assess.ca.length,acc=L.accent||'#c4161c';
  const F=(l,v,fx)=>`<div class="f" style="flex:${fx||1}"><b>${l}</b><i>${esc(v)}</i></div>`;
  const cap=nca===3?'7%':'9%';
  const head=Y?`<tr><th style="width:30%">SUBJECT</th><th>1ST TERM<br>100%</th><th>2ND TERM<br>100%</th><th>3RD TERM<br>100%</th><th>TOTAL 300%</th><th>AVERAGE</th><th>REMARKS</th></tr>`
    :`<tr><th style="width:${nca===3?'26':'29'}%">SUBJECT</th>${d.assess.ca.map((m,i)=>`<th style="width:${cap}">${ORD[i]} C.A ${m}<br>%</th>`).join('')}<th style="width:10%">EXAM ${d.assess.exam}%</th><th style="width:9%">TOTAL<br>100%</th><th style="width:9%">GRADE</th><th>REMARKS</th></tr>`;
  const body=d.rows.map(x=>Y
    ?`<tr><td class="s">${esc(x.s)}</td><td class="c">${x.a[0]}</td><td class="c">${x.a[1]}</td><td class="c">${x.a[2]}</td><td class="c">${x.tot}</td><td class="c">${x.avg.toFixed(2)}</td><td class="c">${x.g}</td></tr>`
    :`<tr><td class="s">${esc(x.s)}</td>${[x.a,x.b,x.c].slice(0,nca).map(v=>`<td class="c">${nz(v)}</td>`).join('')}<td class="c">${nz(x.e)}</td><td class="c">${x.tot}</td><td class="c">${x.g}</td><td class="c">${esc(x.rem)}</td></tr>`).join('');
  const dom=d.domains.map(x=>`<tr><td class="s" style="font-size:10px">${esc(x[0])}</td><td class="c">${esc(x[1])}</td></tr>`).join('');
  const fees=d.fees.map(f=>`<tr><td class="bl">${esc(f.l)}</td><td class="bn">${f.a?`<span>₦</span><span>${money(f.a)}</span>`:''}</td></tr>`).join('');
  const blocks=[];
  if(L.show_domains!==0)blocks.push(`<table><tr><th>DOMAINS</th><th style="width:34%">RATING</th></tr>${dom}</table>`);
  if(L.show_keys!==0)blocks.push(`<div><div class="kb"><h6>KEYS TO GRADING</h6><div>${(d.scheme.keys||[]).map(esc).join('<br>')}</div></div>${L.show_domains!==0?`<div class="kb"><h6>KEYS TO RATING</h6><div>${(L.rating_key||[]).map(esc).join('<br>')}</div></div>`:''}</div>`);
  if(L.show_bill!==0)blocks.push(`<table><tr><th colspan="2">SCHOOL BILL</th></tr>${fees}<tr><td class="bl">OUTSTANDING BILL</td><td class="bn">${d.outstanding?`<span>₦</span><span>${money(d.outstanding)}</span>`:''}</td></tr><tr><td class="bl">TOTAL</td><td class="bn">${d.bill_total?`<span>₦</span><span>${money(d.bill_total)}</span>`:''}</td></tr></table>`);
  const sg=d.sig||{};
  return `<div class="sheet${d.rows.length>20?' d2':d.rows.length>15?' d1':''}" style="--acc:${esc(acc)};font-family:${FONTS[L.font]||FONTS.calibri}">
  <div class="sh-head">${sc.logo?`<img class="logo" src="${sc.logo}">`:CREST}
    <div class="mid"><div class="sh-name">${esc(sc.name)}</div><div class="sh-addr">${esc(sc.address)}</div><div class="sh-con">${esc(sc.contact)}</div><div class="sh-motto">MOTTO: ${esc(sc.motto)}</div></div>
    ${L.show_photo===0?'<div></div>':st.photo?`<img class="pphoto" src="${st.photo}">`:SIL}</div>
  <div class="sh-title">${Y?'YEARLY CUMULATIVE':TN[d.term]+' TERM '+esc(L.title_suffix||'REPORT SHEET')}</div>
  <div class="ibox">
    <div class="irow">${F('NAME',st.name,3.2)}${F('CLASS',d.cls.name,1.3)}${F('GENDER',st.gender,1.2)}${F('TERM',Y?'':TN[d.term],1.2)}</div>
    <div class="irow">${F('SESSION',d.session,1.2)}${F('NO IN CLASS',d.n_in_class,1)}${F('DATE OF BIRTH',fdate(st.dob),1.3)}</div>
    ${L.show_attendance===0?'':`<div class="irow">${F('NO OF TIMES SCHOOL OPENED',nz(d.opened))}${F('NO OF TIMES PRESENT',nz(d.present))}${F('NO OF TIMES ABSENT',nz(d.absent))}</div>`}
    <div class="irow">${F('CLOSING DATE',fdate(d.closing),1)}${F('RESUMPTION DATE',fdate(d.resumption),1)}</div>
    <div class="irow">${F('OVERALL TOTAL',d.total)}${F('AVERAGE',d.avg.toFixed(2))}${F('PERCENTAGE',d.pct+'%')}${L.show_position===0?'':F('POSITION',d.position)}</div>
  </div>
  <div class="ptitle">${esc(L.perf_title||"PUPIL'S ACADEMIC PERFORMANCE")} ( ${esc(d.cls.category)} CATEGORY)</div>
  <table class="ptab">${head}${body}</table>
  ${blocks.length?`<div class="bot" style="grid-template-columns:${blocks.map(()=> '1fr').join(' ')}">${blocks.join('')}</div>`:''}
  <div class="rm" style="margin-top:26px"><b>${esc(L.ct_label||"CLASS TEACHER'S REMARK")}</b><i>${esc(d.ct)}${sg.teacher_sig?`<img class="sigimg" src="${sg.teacher_sig}">`:''}${sg.teacher_name?` <small>(${esc(sg.teacher_name)})</small>`:''}</i></div>
  <div class="rm"><b>${esc(L.ht_label||"HEAD TEACHER'S REMARK")}</b><i>${esc(d.ht)}</i></div>
  <div class="rm"><b>DATE</b><i style="max-width:40%">${esc(fdate(d.date))}</i><b>SIGNATURE</b><i>${sg.head_sig?`<img class="sigimg" src="${sg.head_sig}">`:''}${sg.head_name?` <small>${esc(sg.head_name)}</small>`:''}</i></div>
  ${L.footer?`<div style="text-align:center;font-size:10px;margin-top:14px">${esc(L.footer)}</div>`:''}
  </div>`;
}
/* ======================= class form: C.A structure, grading, class teacher ======================= */
let tmpSig=null;
function classForm(id){
  const c=id?S.classes.find(x=>x.id===id):{name:'',category:'NURSERY',subjects:[],assess:{ca:[20,20],exam:60},grading:'',teacher_name:'',has_sig:false};tmpSig=null;const a=c.assess;
  openModal(`<h2>${id?'Edit class':'Add class'}</h2>${id?'':`<div class="fld" style="margin-bottom:12px"><label>Start from a ready subject list<select onchange="presetPick(this.value)"><option value="">Blank</option>${Object.entries(S.presets).map(([k,v])=>`<option value="${k}">${esc(v.label)}</option>`).join('')}</select></label></div>`}
  <div class="fgrid"><div class="fld"><label>Class name<input type="text" id="cn" value="${esc(c.name)}"></label></div><div class="fld"><label>Category shown on the sheet<input type="text" id="cc" list="ccl" value="${esc(c.category)}"></label><datalist id="ccl"><option>KG</option><option>NURSERY</option><option>PRIMARY</option><option>SECONDARY</option></datalist></div></div>
  <h3 style="margin:14px 0 4px;font-size:16px">Continuous assessment (C.A) and exam</h3><p class="note">Choose how many C.A tests this class has. The marks must add up to 100.</p>
  <div class="fgrid"><div class="fld"><label>Number of C.A<select id="nca" onchange="caCount(this.value)">${[1,2,3].map(n=>`<option value="${n}" ${a.ca.length===n?'selected':''}>${n} C.A</option>`).join('')}</select></label></div>
  <div class="fld"><label>1st C.A max<input type="number" id="ca0" min="1" value="${a.ca[0]||''}" oninput="caSum()"></label></div><div class="fld" id="w1"><label>2nd C.A max<input type="number" id="ca1" min="1" value="${a.ca[1]||''}" oninput="caSum()"></label></div><div class="fld" id="w2"><label>3rd C.A max<input type="number" id="ca2" min="1" value="${a.ca[2]||''}" oninput="caSum()"></label></div><div class="fld"><label>Exam max<input type="number" id="cex" min="1" value="${a.exam}" oninput="caSum()"></label></div></div>
  <p class="note" id="casum"></p>
  <div class="fgrid" style="margin-top:8px"><div class="fld"><label>Grading format for this class<select id="cg"><option value="" ${!c.grading?'selected':''}>Use the school default</option><option value="standard" ${c.grading==='standard'?'selected':''}>A to F (70, 60, 50, 45, 40)</option><option value="waec" ${c.grading==='waec'?'selected':''}>A1, B2, B3, C4 to F9</option><option value="custom" ${c.grading==='custom'?'selected':''}>My custom grading</option></select></label></div>
  <div class="fld"><label>Class teacher's name (for the sheet)<input type="text" id="ctn" value="${esc(c.teacher_name||'')}"></label></div><div class="fld"><label>Class teacher's signature image${c.has_sig?' (one is saved)':''}<input type="file" accept="image/*" onchange="imgToData(this.files[0],360,'image/png',d=>tmpSig=d)"></label>${c.has_sig?'<label class="chk"><input type="checkbox" id="rmsig"> Remove the saved signature</label>':''}</div></div>
  <div class="fld" style="margin-top:12px"><label>Subjects, one per line (this order prints on the sheet)<textarea id="cs" rows="10">${esc(c.subjects.map(s=>s.name).join('\n'))}</textarea></label></div>
  ${id?'<p class="note">Removing a subject deletes its scores. Changing the marks does not change scores already entered; check them if the maximum is now lower.</p>':''}
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="saveClass(${id||0})">Save class</button></div>`);
  caCount(a.ca.length,true);caSum();
}
function caCount(n,keep){n=+n;$('#w1').style.display=n>=2?'':'none';$('#w2').style.display=n>=3?'':'none';if(!keep){const p={1:[40,0,0,60],2:[20,20,0,60],3:[10,10,10,70]}[n];$('#ca0').value=p[0];$('#ca1').value=p[1]||'';$('#ca2').value=p[2]||'';$('#cex').value=p[3]}caSum()}
function caVals(){const n=+$('#nca').value;const ca=[0,1,2].slice(0,n).map(i=>+$('#ca'+i).value||0);return{ca,exam:+$('#cex').value||0}}
function caSum(){const v=caVals(),t=v.ca.reduce((a,b)=>a+b,0)+v.exam;const e=$('#casum');e.textContent='Total marks: '+t+(t===100?' (correct)':' (must be 100)');e.style.color=t===100?'#2f7d6d':'#c4161c'}
function presetPick(k){if(!k)return;const p=S.presets[k];$('#cc').value=p.category;$('#cs').value=p.subjects.join('\n')}
async function saveClass(id){
  const b={name:$('#cn').value,category:$('#cc').value,subjects:$('#cs').value.split('\n'),assess:caVals(),grading:$('#cg').value,teacher_name:$('#ctn').value};
  if(tmpSig)b.teacher_sig=tmpSig;else if($('#rmsig')&&$('#rmsig').checked)b.teacher_sig='';
  if(id)b.id=id;const r=await api('classes',b);S.cid=r.id;closeModal();render();
}
/* ======================= score entry with 1 to 3 C.A and any grading format ======================= */
async function pScores(){
  if(S.t==='Y')S.t=1;
  const cl=await loadClasses();if(!cl)return noClass;
  D=await api(`scores?class=${cl.id}&term=${S.t}&session=${enc(S.session)}`);
  if(!D.students.length)return `<div class="panel"><div class="tools">${classSel()}</div><div class="empty">Add pupils to this class to start entering scores.</div></div>`;
  if(!D.subjects.find(s=>s.id===S.si))S.si=D.subjects[0].id;
  if(!D.students.find(s=>s.id===S.sid))S.sid=D.students[0].id;
  const cols=D.assess.ca.map((m,i)=>({f:'abc'[i],i,max:m,label:ORD[i].charAt(0)+ORD[i].slice(1).toLowerCase()+' C.A'})).concat([{f:'e',i:3,max:D.assess.exam,label:'Exam'}]);
  const inp=(sid,sub,col,v)=>`<input type="number" min="0" max="${col.max}" value="${nz(v)}" oninput="setSc(${sid},${sub},'${col.f}',this)" aria-label="${col.label}">`;
  const val=(sid,sub)=>(D.scores[sid]&&D.scores[sid][sub])||[null,null,null,null];
  const tot=v=>(+v[0]||0)+(+v[1]||0)+(+v[2]||0)+(+v[3]||0);
  const gr=t=>gradeOf(D.scheme.bands,t)[1];
  const hdr=cols.map(c=>`<th>${c.label}<br><small>max ${c.max}</small></th>`).join('')+'<th>Total</th><th>Grade</th>';
  const row=(name,sid,sub)=>{const v=val(sid,sub),t=tot(v);return `<tr><td>${esc(name)}</td>${cols.map(c=>`<td>${inp(sid,sub,c,v[c.i])}</td>`).join('')}<td id="tt_${sid}_${sub}">${t}</td><td id="gg_${sid}_${sub}">${gr(t)}</td></tr>`};
  let body,pick;
  if(S.mode==='subj'){
    pick=`<label>Subject<select onchange="S.si=+this.value;render()">${D.subjects.map(s=>`<option value="${s.id}" ${s.id===S.si?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>`;
    body='<tr><th>Pupil</th>'+hdr+'</tr>'+D.students.map(s=>row(s.name,s.id,S.si)).join('');
  }else{
    pick=`<label>Pupil<select onchange="S.sid=+this.value;render()">${D.students.map(s=>`<option value="${s.id}" ${s.id===S.sid?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>`;
    body='<tr><th>Subject</th>'+hdr+'</tr>'+D.subjects.map(sb=>row(sb.name,S.sid,sb.id)).join('');
  }
  return `<div class="panel"><div class="tools">${classSel()}${termSel(false)}<label>Enter by<select onchange="S.mode=this.value;render()"><option value="subj" ${S.mode==='subj'?'selected':''}>Subject (whole class)</option><option value="stud" ${S.mode==='stud'?'selected':''}>Pupil (all subjects)</option></select></label>${pick}</div>
  <div class="tw"><table class="t">${body}</table></div><p class="note"><span id="sv">Scores save as you type.</span> This class has ${D.assess.ca.length} C.A (${D.assess.ca.join(' + ')}) and an exam of ${D.assess.exam}. Marks above the maximum are reduced to the maximum.</p></div>`;
}
function setSc(sid,sub,f,el){
  const max={a:D.assess.ca[0],b:D.assess.ca[1],c:D.assess.ca[2],e:D.assess.exam}[f];
  let v=el.value;if(v!==''){v=Math.max(0,Math.min(max,+v));if(+el.value!==v)el.value=v}
  const row=((D.scores[sid]=D.scores[sid]||{})[sub]=D.scores[sid][sub]||[null,null,null,null]);row['abce'.indexOf(f)]=v===''?null:v;
  const t=(+row[0]||0)+(+row[1]||0)+(+row[2]||0)+(+row[3]||0);
  $('#tt_'+sid+'_'+sub).textContent=t;$('#gg_'+sid+'_'+sub).textContent=gradeOf(D.scheme.bands,t)[1];
  pend[sid+'_'+sub+'_'+f]={student_id:sid,subject_id:sub,field:f,value:v===''?null:v,term:S.t,session:S.session};
  $('#sv').textContent='Saving...';clearTimeout(tmr);tmr=setTimeout(()=>flush().catch(e=>toast(e.message)),500);
}
async function flush(){
  const items=Object.values(pend);for(const k in pend)delete pend[k];if(!items.length)return;
  try{await api('scores',{items});const s=$('#sv');if(s)s.textContent='All changes saved'}
  catch(e){const s=$('#sv');if(s)s.textContent='Not saved';throw e}
}
/* ======================= export in several formats ======================= */
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},600)}
function exportTable(){
  if(!mainTable()){toast('Nothing to export here');return}
  openModal(`<h2>Export this list</h2><p class="note">Choose a format. The file contains the table you are looking at.</p><div class="grid" style="gap:8px">${[['xlsx','Excel (.xlsx)','Opens in Microsoft Excel, Google Sheets, LibreOffice'],['csv','CSV (.csv)','Plain text for any spreadsheet or program'],['json','JSON (.json)','For developers and other systems'],['tsv','Text (.txt)','Tab separated text']].map(f=>`<button class="btn alt" style="text-align:left" onclick="exportAs('${f[0]}')"><b>${f[1]}</b><br><small>${f[2]}</small></button>`).join('')}<button class="btn alt" style="text-align:left" onclick="closeModal();printTable()"><b>Print or save as PDF</b><br><small>Opens the print window</small></button></div><div class="mact"><button class="btn" onclick="closeModal()">Cancel</button></div>`);
}
async function exportAs(fmt){
  const t=mainTable(),rows=tableData(t);
  const r=await fetch('/api/export/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:(S.info&&S.info.name?S.info.name+' ':'')+(TABS_LABEL[S.page]||S.page),format:fmt,rows})});
  if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.error||'Export failed')}
  const cd=r.headers.get('Content-Disposition')||'',m=/filename="([^"]+)"/.exec(cd);download(await r.blob(),m?m[1]:'export.'+fmt);closeModal();toast('Downloaded',true);
}
function addExport(){
  const v=document.getElementById('view'),t=mainTable();if(!t||['scores','details','license','reports','results','msgs','data','customize','settings'].includes(S.page))return;
  const html='<button class="btn alt" onclick="exportTable()" title="Download this list as Excel, CSV, JSON or text, or print it">Export</button>';
  let bar=[...v.querySelectorAll('.tools')].find(x=>x.parentElement.classList.contains('panel')||x.parentElement===v);
  if(!bar){bar=document.createElement('div');bar.className='tools';v.insertBefore(bar,v.firstChild)}
  bar.insertAdjacentHTML('beforeend',html);
}
/* ======================= import and export centre ======================= */
function parseCSV(text){
  text=text.replace(/^\ufeff/,'');const first=text.split(/\r?\n/)[0]||'';const c1=first.split(',').length,c2=first.split(';').length,c3=first.split('\t').length;const d=c3>c1&&c3>=c2?'\t':c2>c1?';':',';
  const rows=[];let row=[],cur='',q=false;
  for(let i=0;i<text.length;i++){const ch=text[i];
    if(q){if(ch==='"'){if(text[i+1]==='"'){cur+='"';i++}else q=false}else cur+=ch}
    else if(ch==='"')q=true;else if(ch===d){row.push(cur);cur=''}
    else if(ch==='\n'||ch==='\r'){if(ch==='\r'&&text[i+1]==='\n')i++;row.push(cur);cur='';if(row.some(x=>x.trim()!==''))rows.push(row);row=[]}else cur+=ch}
  row.push(cur);if(row.some(x=>x.trim()!==''))rows.push(row);if(rows.length<2)return[];
  const heads=rows[0].map(h=>h.trim().toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,''));
  return rows.slice(1).map(r=>{const o={};heads.forEach((h,i)=>{if(h)o[h]=(r[i]||'').trim()});return o});
}
function templateCSV(def){const cols=def.cols,q=v=>/[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;return '\ufeff'+[cols.map(c=>c.name).join(','),cols.map(c=>q(c.example||'')).join(','),cols.map(()=>'').join(',')].join('\r\n')+'\r\n'}
let IMPORT_ROWS=[];
async function pData(){
  const defs=await api('import/defs'),ds=await api('export/datasets');D.defs=defs;S.imp=S.imp&&defs.find(d=>d.kind===S.imp)?S.imp:defs[0].kind;
  const def=defs.find(d=>d.kind===S.imp);IMPORT_ROWS=[];
  return `<div class="panel cust"><h3>${ic('upload')} Import from a CSV file</h3><p class="note">Fill a spreadsheet, save it as <b>CSV</b>, and import it. Download the template first, so the columns are right.</p>
  <div class="tools"><label>What are you importing?<select onchange="S.imp=this.value;render()">${defs.map(d=>`<option value="${d.kind}" ${d.kind===S.imp?'selected':''}>${esc(d.label)}</option>`).join('')}</select></label><button class="btn gold" onclick="getTemplate()">${ic('download')} Download CSV template</button></div>
  <div class="stepbox"><b>${esc(def.label)}</b>: ${esc(def.note)}<br><b>Columns</b> (first row of the file):</div>
  <div class="tw"><table class="t"><tr><th>Column</th><th>Required</th><th>What to enter</th><th>Example</th></tr>${def.cols.map(c=>`<tr><td><code>${c.name}</code></td><td>${c.required?'<span class="pill bad">required</span>':'optional'}</td><td>${esc(c.help)}</td><td>${esc(c.example)}</td></tr>`).join('')}</table></div>
  <ol style="line-height:1.7;margin:10px 0 0 18px"><li>Open the template in Excel or Google Sheets and replace the example row with your data. Keep the first row (the column names).</li><li>Save as <b>CSV (comma delimited)</b>.</li><li>Choose the file below, press <b>Check file</b> to see problems without changing anything, then press <b>Import now</b>.</li></ol>
  <div class="tools" style="margin-top:10px"><label>CSV file<input type="file" accept=".csv,.txt,text/csv" onchange="readCSV(this.files[0])"></label></div>
  <label class="fld" style="display:block"><span class="note">Or paste the CSV text here</span><textarea id="csvtext" rows="4" placeholder="name,class,reg_no,gender,dob..." onchange="IMPORT_ROWS=parseCSV(this.value);impPreview()"></textarea></label>
  <div id="imp"></div></div>
  <div class="panel cust"><h3>${ic('download')} Export your data</h3><p class="note">Download any list in Excel, CSV, JSON or text format. Every table in the system also has an Export button.</p>
  <div class="tw"><table class="t"><tr><th>Data</th><th>Excel</th><th>CSV</th><th>JSON</th><th>Text</th></tr>${ds.map(x=>`<tr><td>${esc(x.label)}</td>${['xlsx','csv','json','tsv'].map(f=>`<td><a class="btn alt sm" style="padding:5px 10px" href="/api/export?name=${x.name}&format=${f}&term=${S.et||1}&session=${enc(S.session)}">${f==='tsv'?'TXT':f.toUpperCase()}</a></td>`).join('')}</tr>`).join('')}</table></div>
  <div class="tools" style="margin-top:10px"><label>Term (for scores)<select onchange="S.et=+this.value">${[1,2,3].map(x=>`<option value="${x}" ${(S.et||1)===x?'selected':''}>${TN[x]} term</option>`).join('')}</select></label>${S.user.role==='admin'?`<a class="btn" href="/api/export/all">${ic('download')} Download everything (ZIP of CSV files)</a><a class="btn alt" href="/api/backup">Full backup (database)</a>`:''}</div></div>`;
}
function getTemplate(){const def=D.defs.find(d=>d.kind===S.imp);download(new Blob([templateCSV(def)],{type:'text/csv;charset=utf-8'}),'template_'+def.kind+'.csv')}
function readCSV(f){if(!f)return;const r=new FileReader();r.onload=()=>{IMPORT_ROWS=parseCSV(r.result);impPreview()};r.readAsText(f)}
function impPreview(){
  const def=D.defs.find(d=>d.kind===S.imp),box=$('#imp');if(!IMPORT_ROWS.length){box.innerHTML='<p class="note" style="color:#c4161c">No data rows found. The file needs a header row and at least one row of data.</p>';return}
  const names=Object.keys(IMPORT_ROWS[0]),missing=def.cols.filter(c=>c.required&&!names.includes(c.name)).map(c=>c.name);
  box.innerHTML=`<p><b>${IMPORT_ROWS.length}</b> rows found. Columns: ${names.map(n=>`<code>${esc(n)}</code>`).join(' ')}</p>${missing.length?`<p style="color:#c4161c"><b>Missing required column${missing.length>1?'s':''}:</b> ${missing.join(', ')}. Use the template.</p>`:`<div class="tw"><table class="t"><tr>${names.map(n=>`<th>${esc(n)}</th>`).join('')}</tr>${IMPORT_ROWS.slice(0,5).map(r=>`<tr>${names.map(n=>`<td>${esc(r[n])}</td>`).join('')}</tr>`).join('')}</table></div><p class="note">First 5 rows shown.</p><div class="tools"><button class="btn alt" onclick="runImport(true)">Check file (no changes)</button><button class="btn gold" onclick="runImport(false)">Import now</button></div><div id="impres"></div>`}`;
}
async function runImport(dry){
  const r=await api('import',{kind:S.imp,rows:IMPORT_ROWS,dry_run:dry,session:S.session});
  const gen=r.generated&&r.generated.length?`<div class="stepbox"><b>New staff passwords</b> (shown once, give each person theirs):<br>${r.generated.map(g=>`${esc(g.name)}: <b>${esc(g.username)}</b> / <b>${esc(g.password)}</b>`).join('<br>')}<br><button class="btn alt sm" onclick="downloadGen()">Download as CSV</button></div>`:'';
  window._gen=r.generated||[];
  $('#impres').innerHTML=`<div class="stepbox" style="border-color:${r.errors.length?'#c4161c':'#2f7d6d'}">${dry?'<b>Check only, nothing was saved.</b> ':'<b>Import finished.</b> '}Added ${r.added}, updated ${r.updated}, skipped ${r.skipped} (already there), problems ${r.errors.length}.</div>${gen}${r.errors.length?`<div class="tw"><table class="t"><tr><th>Row in file</th><th>Problem</th></tr>${r.errors.slice(0,200).map(e=>`<tr><td>${e.row}</td><td>${esc(e.error)}</td></tr>`).join('')}</table></div><p class="note">Fix these rows in your file and import again. Rows already imported are skipped, so it is safe to re-run.</p>`:''}`;
  if(!dry)toast('Import finished',true);
}
function downloadGen(){download(new Blob(['\ufeffname,username,password\r\n'+window._gen.map(g=>[g.name,g.username,g.password].join(',')).join('\r\n')],{type:'text/csv'}),'new_staff_logins.csv')}
function importForm(){S.imp='pupils';go('data')}

/* ======================= customize (administrator) ======================= */
const DEF_LAYOUT={accent:'#c4161c',font:'calibri',show_photo:1,show_domains:1,show_bill:1,show_position:1,show_attendance:1,show_keys:1,title_suffix:'REPORT SHEET',perf_title:"PUPIL'S ACADEMIC PERFORMANCE",ct_label:"CLASS TEACHER'S REMARK",ht_label:"HEAD TEACHER'S REMARK",domains:['PUNCTUALITY','ATTENDANCE','SELF-CONTROL','NEATNESS','RESPONSIBILITY','DILIGENCE','ATTENTIVENESS','LEGIBILITY','ACCURACY','SPORTS & GAMES'],rating_key:['5= EXCELLENT, 4= VERY GOOD','3= GOOD, 2= POOR','1= VERY POOR'],footer:''};
const jp=(t,d)=>{try{const v=JSON.parse(t);return v==null?d:v}catch(e){return d}};
const bankText=b=>(b||[]).map(x=>x.min+'|'+x.text).join('\n'),parseBank=t=>t.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>{const i=l.indexOf('|');return{min:+l.slice(0,i)||0,text:l.slice(i+1).trim()}});
async function pCustomize(){
  const s=await api('settings');S.cs=s;
  const th=Object.assign({name:'navy',primary:'#16213e',accent:'#b58a2c',bg:'#eef0f4',dark:0},jp(s.theme,{})),L=Object.assign({},DEF_LAYOUT,jp(s.layout,{}));S.cth=th;
  const chk=(id,v,l)=>`<label class="chk"><input type="checkbox" id="${id}" ${v!==0&&v!=='0'?'checked':''}> ${l}</label>`;
  return `<div class="panel cust"><h3>${ic('palette')} Colour theme (school default)</h3><p class="note">Everyone sees these colours unless they pick their own with the palette button at the top. Pick a ready theme or set your own colours.</p>
  <div class="themes">${Object.entries(THEMES).map(([k,v])=>`<div class="tile ${th.primary===v.primary&&th.accent===v.accent?'on':''}" onclick="pickSchoolTheme('${k}')"><i><b style="background:${v.primary}"></b><b style="background:${v.accent}"></b><b style="background:${v.bg}"></b></i><span>${v.n}</span></div>`).join('')}</div>
  <div class="fgrid"><div class="fld"><label>Main colour<input type="color" id="cp" value="${th.primary}" onchange="liveTheme()"></label></div><div class="fld"><label>Accent colour<input type="color" id="ca" value="${th.accent}" onchange="liveTheme()"></label></div><div class="fld"><label>Page background<input type="color" id="cb" value="${th.bg}" onchange="liveTheme()"></label></div><div class="fld">${chk('cd',th.dark?1:0,'Dark mode')}</div></div>
  <div class="tools" style="margin-top:10px"><button class="btn" onclick="saveTheme()">Save school colours</button></div></div>
  <div class="panel cust"><h3>${ic('file')} Report sheet design</h3><div class="fgrid">
  <div class="fld"><label>Accent colour (school name, headings)<input type="color" id="l_accent" value="${L.accent}"></label></div>
  <div class="fld"><label>Font<select id="l_font">${Object.keys(FONTS).map(f=>`<option value="${f}" ${L.font===f?'selected':''}>${f[0].toUpperCase()+f.slice(1)}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Title wording after the term<input type="text" id="l_title" value="${esc(L.title_suffix)}"></label></div>
  <div class="fld"><label>Performance heading<input type="text" id="l_perf" value="${esc(L.perf_title)}"></label></div>
  <div class="fld"><label>Class teacher's remark label<input type="text" id="l_ct" value="${esc(L.ct_label)}"></label></div>
  <div class="fld"><label>Head teacher's remark label<input type="text" id="l_ht" value="${esc(L.ht_label)}"></label></div></div>
  <div class="fgrid" style="margin-top:10px">${chk('l_photo',L.show_photo,'Show passport photo')}${chk('l_att',L.show_attendance,'Show attendance row')}${chk('l_pos',L.show_position,'Show position in class')}${chk('l_dom',L.show_domains,'Show domains and ratings')}${chk('l_keys',L.show_keys,'Show keys to grading')}${chk('l_bill',L.show_bill,'Show school bill')}</div>
  <div class="fgrid" style="margin-top:10px"><div class="fld"><label>Domains, one per line (up to 14)<textarea id="l_doms" rows="8">${esc(L.domains.join('\n'))}</textarea></label></div><div class="fld"><label>Keys to rating, one line each<textarea id="l_rk" rows="4">${esc(L.rating_key.join('\n'))}</textarea></label><label style="margin-top:10px">Footer note on every sheet<input type="text" id="l_foot" value="${esc(L.footer)}" placeholder="for example: Next term begins ..."></label></div></div>
  <div class="tools" style="margin-top:10px"><button class="btn" onclick="saveLayout()">Save sheet design</button><button class="btn alt" onclick="previewSheet()">Preview a sheet</button></div></div>
  <div class="panel cust"><h3>${ic('award')} Grading format</h3><p class="note">The default for all classes. Any class can use a different format in its own settings (Classes & subjects, edit).</p>
  <div class="fgrid"><div class="fld"><label>School default<select id="g_def"><option value="standard" ${s.grading_default==='standard'?'selected':''}>A to F (70, 60, 50, 45, 40) as on your sample sheet</option><option value="waec" ${s.grading_default==='waec'?'selected':''}>A1, B2, B3, C4, C5, C6, D7, E8, F9</option><option value="custom" ${s.grading_default==='custom'?'selected':''}>My own grading (below)</option></select></label></div></div>
  <div class="fld" style="margin-top:10px"><label>My own grading: one line per grade as <code>lowest mark|GRADE|REMARK</code>. The last line must start at 0.<textarea id="g_cust" rows="6" placeholder="75|A|EXCELLENT&#10;60|B|GOOD&#10;50|C|FAIR&#10;0|F|FAIL">${esc(jp(s.grading_custom,[]).map(b=>b.min+'|'+b.grade+'|'+b.remark).join('\n'))}</textarea></label></div>
  <div class="tools" style="margin-top:10px"><button class="btn" onclick="saveGrading()">Save grading</button></div></div>
  <div class="panel cust"><h3>${ic('edit')} Remarks, signatures and dates</h3>
  <div class="fgrid"><div class="fld"><label>Teachers' and head teacher's remarks<select id="r_mode"><option value="manual" ${s.remarks_mode==='manual'?'selected':''}>Manual: I type them for each pupil</option><option value="auto" ${s.remarks_mode==='auto'?'selected':''}>Automatic: fill from the lists below when blank (you can still type your own)</option></select></label></div>
  <div class="fld"><label>Date on the sheet<select id="r_date"><option value="manual" ${s.date_mode==='manual'?'selected':''}>Manual</option><option value="auto" ${s.date_mode==='auto'?'selected':''}>Automatic (closing date, else today)</option></select></label></div>
  <div class="fld"><label>Signatures<select id="r_sig"><option value="manual" ${s.sig_mode==='manual'?'selected':''}>Manual: leave the line blank to sign by hand</option><option value="auto" ${s.sig_mode==='auto'?'selected':''}>Automatic: print the uploaded signatures and names</option></select></label></div></div>
  <div class="fgrid" style="margin-top:10px"><div class="fld"><label>Class teacher remarks by average, one line each as <code>lowest average|remark</code><textarea id="r_ct" rows="7">${esc(bankText(jp(s.remarks_bank,[])))}</textarea></label></div><div class="fld"><label>Head teacher remarks by average<textarea id="r_ht" rows="7">${esc(bankText(jp(s.head_bank,[])))}</textarea></label></div></div>
  <div class="fgrid" style="margin-top:10px"><div class="fld"><label>Head teacher's name<input type="text" id="r_hn" value="${esc(s.head_name)}"></label></div><div class="fld"><label>Head teacher's signature image<input type="file" accept="image/*" onchange="imgToData(this.files[0],360,'image/png',d=>{api('settings',{head_sig:d}).then(()=>{toast('Signature saved',true);render()})})"></label>${s.head_sig?`<p><img src="${s.head_sig}" style="height:46px;background:#fff;border:1px solid var(--line);padding:2px"> <button class="btn alt sm" onclick="api('settings',{head_sig:''}).then(render)">Remove</button></p>`:''}</div></div>
  <p class="note">Each class teacher's name and signature are set in the class itself (Classes & subjects, edit).</p><div class="tools"><button class="btn" onclick="saveRemarks()">Save remarks and signatures</button></div></div>
  <div class="panel cust"><h3>${ic('userplus')} Registration numbers and admissions</h3><div class="fgrid"><div class="fld"><label>Reg No prefix (letters or numbers, up to 8)<input type="text" id="a_pre" value="${esc(s.reg_prefix)}"></label></div><div class="fld"><label>Online admission form<select id="a_open"><option value="0" ${s.admissions_open!=='1'?'selected':''}>Closed</option><option value="1" ${s.admissions_open==='1'?'selected':''}>Open (parents can apply from their phones)</option></select></label></div></div>
  <div class="fld" style="margin-top:10px"><label>Admission letter text. Use {name} {class} {reg} {school} {parent}<textarea id="a_letter" rows="6">${esc(s.admission_letter)}</textarea></label></div><div class="tools"><button class="btn" onclick="saveReg()">Save</button><button class="btn alt" onclick="showQR('/apply')">${ic('qr')} QR code for the admission form</button></div></div>`;
}
function pickSchoolTheme(k){const v=THEMES[k];$('#cp').value=v.primary;$('#ca').value=v.accent;$('#cb').value=v.bg;liveTheme(true)}
function liveTheme(save){S.theme={name:'custom',primary:$('#cp').value,accent:$('#ca').value,bg:$('#cb').value,dark:$('#cd').checked?1:0};if(personalTheme()){localStorage.removeItem('ss_theme')}applyTheme();if(save)saveTheme()}
async function saveTheme(){S.theme={name:'custom',primary:$('#cp').value,accent:$('#ca').value,bg:$('#cb').value,dark:$('#cd').checked?1:0};await api('settings',{theme:JSON.stringify(S.theme)});applyTheme();toast('School colours saved',true);render()}
async function saveLayout(){
  const L={accent:$('#l_accent').value,font:$('#l_font').value,title_suffix:$('#l_title').value,perf_title:$('#l_perf').value,ct_label:$('#l_ct').value,ht_label:$('#l_ht').value,footer:$('#l_foot').value,
    show_photo:+$('#l_photo').checked,show_attendance:+$('#l_att').checked,show_position:+$('#l_pos').checked,show_domains:+$('#l_dom').checked,show_keys:+$('#l_keys').checked,show_bill:+$('#l_bill').checked,
    domains:$('#l_doms').value.split('\n').map(x=>x.trim()).filter(Boolean),rating_key:$('#l_rk').value.split('\n').map(x=>x.trim()).filter(Boolean)};
  await api('settings',{layout:JSON.stringify(L)});const m=await api('me');S.domains=m.domains;toast('Sheet design saved',true)
}
async function saveGrading(){
  const rows=$('#g_cust').value.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>{const p=l.split('|');return{min:+p[0],grade:(p[1]||'').trim(),remark:(p[2]||'').trim()}});
  if($('#g_def').value==='custom'){if(!rows.length||rows.some(r=>isNaN(r.min)||!r.grade)||!rows.some(r=>r.min===0))throw new Error('Custom grading needs lines like 75|A|EXCELLENT, and the last line must start at 0')}
  await api('settings',{grading_default:$('#g_def').value,grading_custom:JSON.stringify(rows)});toast('Grading saved',true)
}
async function saveRemarks(){await api('settings',{remarks_mode:$('#r_mode').value,date_mode:$('#r_date').value,sig_mode:$('#r_sig').value,remarks_bank:JSON.stringify(parseBank($('#r_ct').value)),head_bank:JSON.stringify(parseBank($('#r_ht').value)),head_name:$('#r_hn').value});toast('Saved',true)}
async function saveReg(){await api('settings',{reg_prefix:$('#a_pre').value,admissions_open:$('#a_open').value,admission_letter:$('#a_letter').value});toast('Saved',true);render()}
async function previewSheet(){
  await loadClasses();for(const c of S.classes){const l=await api('students?class='+c.id);if(l.length){showDoc(sheetHTML(await api(`sheet?student=${l[0].id}&term=1&session=${enc(S.session)}`)));return}}
  throw new Error('Add a pupil first, then preview the sheet')
}
/* ======================= admissions and registration ======================= */
Object.assign(ACT,{'Admit':'userplus','Form':'file','Letter':'mail'});
const AST={Applied:'gold',Screening:'gold','Waiting list':'',Admitted:'ok',Rejected:'bad'};
async function pAdmissions(){
  await loadClasses();const f=F.ad=F.ad||{status:'',q:''};
  const d=await api(`applicants?status=${enc(f.status)}&q=${enc(f.q)}`);D.apps=d.rows;const n=k=>d.counts[k]||0;
  return `<div class="kpis">${kpi('userplus',n('Applied'),'New applications','#b58a2c')}${kpi('clock',n('Screening'),'Screening','#5b7db1')}${kpi('list',n('Waiting list'),'Waiting list','#8e6bbf')}${kpi('check',n('Admitted'),'Admitted','#2f7d6d')}${kpi('x',n('Rejected'),'Not admitted','#c4161c')}</div>
  <div class="panel"><div class="tools"><label>Status<select onchange="F.ad.status=this.value;render()"><option value="">All</option>${['Applied','Screening','Waiting list','Admitted','Rejected'].map(x=>`<option ${f.status===x?'selected':''}>${x}</option>`).join('')}</select></label><label>Search<input type="text" value="${esc(f.q)}" placeholder="Name, number or phone" onchange="F.ad.q=this.value;render()"></label>
  <button class="btn gold" onclick="appForm()">New application</button><button class="btn alt" onclick="showQR('/apply')">${ic('qr')} Online form QR</button><button class="btn alt" onclick="S.imp='applicants';go('data')">Import applicants</button></div>
  <p class="note" style="margin:0 0 10px">Online admission form: <b>${d.open?'open':'closed'}</b>. ${S.user.role==='admin'?'Change it under Admin, Customize.':''} Parents scan the QR code, fill the form on their phone, and the application appears here.</p>
  ${d.rows.length?`<div class="tw"><table class="t"><tr><th>No</th><th>Applicant</th><th>Class</th><th>Parent</th><th>Phone</th><th>Status</th><th>Applied</th><th>Actions</th></tr>${d.rows.map(a=>`<tr><td>${esc(a.no)}</td><td>${esc(a.name)}<div class="note" style="margin:0">${esc(a.gender)} ${esc(fdate(a.dob))}</div></td><td>${esc(a.cname||'')}</td><td>${esc(a.parent_name)}</td><td>${a.phone?`<a href="tel:${esc(a.phone)}">${esc(a.phone)}</a>`:''}</td>
  <td>${a.status==='Admitted'?`<span class="pill ok">Admitted</span><div class="note" style="margin:0">${esc(a.reg_no)}</div>`:`<select onchange="appStatus(${a.id},this.value)">${['Applied','Screening','Waiting list','Rejected'].map(x=>`<option ${a.status===x?'selected':''}>${x}</option>`).join('')}</select>`}</td><td>${esc((a.created||'').slice(0,10))}</td>
  <td style="white-space:nowrap"><button class="btn alt sm" onclick="appDoc(${a.id},'form')">Form</button> ${a.status==='Admitted'?`<button class="btn alt sm" onclick="appDoc(${a.id},'letter')">Letter</button>`:`<button class="btn alt sm" onclick="admitForm(${a.id})">Admit</button>`} <button class="btn alt sm" onclick="appForm(${a.id})">Edit</button> <button class="btn danger sm" onclick="delApp(${a.id})">Delete</button></td></tr>`).join('')}</table></div>`:'<div class="empty">No applications yet. Add one, import a list, or open the online form.</div>'}</div>`;
}
function appForm(id){
  const a=id?D.apps.find(x=>x.id===id):{name:'',gender:'',dob:'',class_id:S.cid,parent_name:'',phone:'',email:'',address:'',prev_school:'',notes:'',status:'Applied'};
  openModal(`<h2>${id?'Edit application':'New application'}</h2><div class="fgrid"><div class="fld"><label>Child's full name<input type="text" id="an" value="${esc(a.name)}"></label></div><div class="fld"><label>Gender<select id="ag"><option value=""></option><option ${a.gender==='MALE'?'selected':''}>MALE</option><option ${a.gender==='FEMALE'?'selected':''}>FEMALE</option></select></label></div>
  <div class="fld"><label>Date of birth<input type="date" id="ad" value="${esc(a.dob)}"></label></div><div class="fld"><label>Class applying for<select id="ac"><option value=""></option>${S.classes.map(c=>`<option value="${c.id}" ${c.id===a.class_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label></div>
  <div class="fld"><label>Parent / guardian<input type="text" id="ap" value="${esc(a.parent_name)}"></label></div><div class="fld"><label>Phone<input type="text" id="aph" value="${esc(a.phone)}"></label></div><div class="fld"><label>Email<input type="text" id="ae" value="${esc(a.email)}"></label></div><div class="fld"><label>Previous school<input type="text" id="as" value="${esc(a.prev_school)}"></label></div></div>
  <div class="fld" style="margin-top:10px"><label>Address<input type="text" id="aa" value="${esc(a.address)}"></label></div><div class="fld" style="margin-top:10px"><label>Notes<textarea id="anote" rows="2">${esc(a.notes)}</textarea></label></div>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn" onclick="saveApp(${id||0})">Save</button></div>`);
}
async function saveApp(id){const b={name:$('#an').value,gender:$('#ag').value,dob:$('#ad').value,class_id:$('#ac').value,parent_name:$('#ap').value,phone:$('#aph').value,email:$('#ae').value,prev_school:$('#as').value,address:$('#aa').value,notes:$('#anote').value};if(id){b.id=id;b.status=D.apps.find(x=>x.id===id).status}await api('applicants',b);closeModal();toast('Saved',true);render()}
async function appStatus(id,st){await api('applicants/status',{id,status:st});toast('Status updated',true)}
function delApp(id){ask('Delete this application?',async()=>{await api('applicants/delete',{id});render()})}
function admitForm(id){
  const a=D.apps.find(x=>x.id===id);
  openModal(`<h2>Admit ${esc(a.name)}</h2><p class="note">This creates the pupil with a Reg No. The pupil's first password is the Reg No.</p><div class="fgrid"><div class="fld"><label>Class to admit into<select id="mc">${S.classes.map(c=>`<option value="${c.id}" ${c.id===a.class_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label></div><div class="fld"><label>Reg No (leave empty to generate)<input type="text" id="mr"></label></div></div>
  <label class="chk" style="margin-top:12px"><input type="checkbox" id="mi" checked> Raise an invoice for the admission fees (fee types ADMISSION FORM, ADMISSION FEE and REGISTRATION FEE that have an amount)</label>
  <div class="mact"><button class="btn alt" onclick="closeModal()">Cancel</button><button class="btn gold" onclick="doAdmit(${id})">Admit pupil</button></div>`);
}
async function doAdmit(id){
  const r=await api('applicants/admit',{id,class_id:+$('#mc').value,reg_no:$('#mr').value,invoice:$('#mi').checked});
  openModal(`<h2>Admitted</h2><div class="pwshow">${esc(r.reg_no)}</div><p>The pupil can sign in with this Reg No as both username and first password.${r.invoice?` An invoice <b>${esc(r.invoice.no)}</b> was raised for the admission fees.`:''}</p><div class="mact"><button class="btn alt" onclick="appDoc(${id},'letter')">Print admission letter</button>${r.invoice?`<button class="btn alt" onclick="viewInv(${r.invoice.id})">View invoice</button>`:''}<button class="btn" onclick="closeModal();render()">Done</button></div>`);
}
async function appDoc(id,kind){const d=await api('applicants/doc?id='+id);showDoc(kind==='form'?appFormHTML(d):letterHTML(d))}
function appFormHTML(d){
  const row=(l,v)=>`<tr><th style="width:190px">${l}</th><td>${esc(v)||'&nbsp;'}</td></tr>`;
  return `<div class="doc">${docHead(d.school)}<div class="dt">ADMISSION APPLICATION FORM</div><div class="meta"><div><b>Application No:</b> ${esc(d.no)}</div><div><b>Date:</b> ${fdate((d.created||'').slice(0,10))}</div><div><b>Session:</b> ${esc(d.session)}</div><div><b>Status:</b> ${esc(d.status)}</div></div>
  <table>${row("Child's full name",d.name)}${row('Gender',d.gender)}${row('Date of birth',fdate(d.dob))}${row('Class applying for',d.cname)}${row('Previous school',d.prev_school)}${row('Parent / guardian',d.parent_name)}${row('Phone',d.phone)}${row('Email',d.email)}${row('Home address',d.address)}${row('Notes',d.notes)}</table>
  <p style="margin-top:12px;font-size:11px">I confirm that the information above is correct.</p><div class="sig"><div>Parent / Guardian signature and date</div><div>Admissions officer</div></div></div>`;
}
function letterHTML(d){
  const text=(d.letter||'').replace(/\{name\}/gi,d.name).replace(/\{class\}/gi,d.cname||'').replace(/\{reg\}/gi,d.reg_no||'').replace(/\{school\}/gi,d.school.name).replace(/\{parent\}/gi,d.parent_name||'Parent / Guardian');
  return `<div class="doc">${docHead(d.school)}<div class="dt">ADMISSION LETTER</div><p>Date: ${fdate(today())}</p><p style="margin-top:6px"><b>Application No:</b> ${esc(d.no)} &nbsp; <b>Reg No:</b> ${esc(d.reg_no)}</p><div style="margin-top:14px;white-space:pre-wrap;line-height:1.6;font-size:13px">${esc(text)}</div><div class="sig"><div></div><div>Head of School</div></div></div>`;
}

boot();
</script></body></html>
'''

if __name__ == '__main__':
    if '--version' in sys.argv:
        print(VERSION)
    else:
        main()
