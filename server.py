#!/usr/bin/env python3
"""Family Tree API server with SQLite database. Zero external dependencies."""

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
DB_PATH = ROOT / 'family.db'
PHOTOS_DIR = ROOT / 'photos'
PORT = 8000
SESSION_DAYS = 30
INVITE_DAYS = 7

PEOPLE_COLS = [
    'id', 'given_names', 'surname', 'surname_birth', 'nickname',
    'gender', 'birth_date', 'death_date', 'deceased', 'birth_place',
    'death_place', 'cause_of_death', 'burial_place',
    'profession', 'company', 'email', 'home_tel', 'mobile',
    'address', 'interests', 'activities', 'bio_notes',
    'photo', 'mother_id', 'father_id', 'generation',
]

SCHEMA = '''
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    given_names TEXT DEFAULT '',
    surname TEXT DEFAULT '',
    surname_birth TEXT DEFAULT '',
    nickname TEXT DEFAULT '',
    gender TEXT DEFAULT 'other' CHECK(gender IN ('male','female','other')),
    birth_date TEXT,
    death_date TEXT,
    deceased INTEGER DEFAULT 0,
    birth_place TEXT DEFAULT '',
    death_place TEXT DEFAULT '',
    cause_of_death TEXT DEFAULT '',
    burial_place TEXT DEFAULT '',
    profession TEXT DEFAULT '',
    company TEXT DEFAULT '',
    email TEXT DEFAULT '',
    home_tel TEXT DEFAULT '',
    mobile TEXT DEFAULT '',
    address TEXT DEFAULT '',
    interests TEXT DEFAULT '',
    activities TEXT DEFAULT '',
    bio_notes TEXT DEFAULT '',
    photo TEXT DEFAULT '',
    mother_id TEXT REFERENCES people(id) ON DELETE SET NULL,
    father_id TEXT REFERENCES people(id) ON DELETE SET NULL,
    generation INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS partnerships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person1_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    person2_id TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    type TEXT DEFAULT 'relationship',
    start_date TEXT,
    marriage_date TEXT,
    marriage_location TEXT,
    end_date TEXT,
    UNIQUE(person1_id, person2_id)
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    person_id TEXT REFERENCES people(id) ON DELETE SET NULL,
    role TEXT DEFAULT 'member' CHECK(role IN ('admin','member','viewer')),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    person_id TEXT REFERENCES people(id) ON DELETE CASCADE,
    email TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0
);
'''


def db_connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def db_init():
    with db_connect() as conn:
        conn.executescript(SCHEMA)


def is_cjk(s):
    return any('一' <= c <= '鿿' or '㐀' <= c <= '䶿' for c in (s or ''))


def make_display_name(given, surname, fallback_id):
    if given and surname:
        return (surname + given) if (is_cjk(surname) or is_cjk(given)) else (given + ' ' + surname)
    return given or surname or fallback_id


# ── Auth ──

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return salt + ':' + h.hex()


def verify_password(password, stored):
    salt, _ = stored.split(':', 1)
    return hash_password(password, salt) == stored


def create_user(email, password, display_name='', role=None):
    uid = uuid.uuid4().hex[:12]
    pw_hash = hash_password(password)
    if role is None:
        with db_connect() as conn:
            count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        role = 'admin' if count == 0 else 'member'
    with db_connect() as conn:
        conn.execute(
            'INSERT INTO users (id, email, display_name, password_hash, role) VALUES (?,?,?,?,?)',
            (uid, email.lower().strip(), display_name, pw_hash, role))
    return uid


def authenticate(email, password):
    with db_connect() as conn:
        row = conn.execute('SELECT * FROM users WHERE email = ?', (email.lower().strip(),)).fetchone()
    if not row:
        return None
    if verify_password(password, row['password_hash']):
        return dict(row)
    return None


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
    with db_connect() as conn:
        conn.execute('INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)',
                     (token, user_id, expires))
    return token


def get_session_user(token):
    if not token:
        return None
    with db_connect() as conn:
        row = conn.execute(
            '''SELECT u.* FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.token = ? AND s.expires_at > datetime('now')''',
            (token,)).fetchone()
    return dict(row) if row else None


def delete_session(token):
    with db_connect() as conn:
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))


def create_invite(person_id, email, created_by):
    token = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)).isoformat()
    with db_connect() as conn:
        conn.execute(
            'INSERT INTO invites (token, person_id, email, created_by, expires_at) VALUES (?,?,?,?,?)',
            (token, person_id, email or None, created_by, expires))
    return token


def get_invite(token):
    with db_connect() as conn:
        row = conn.execute(
            'SELECT * FROM invites WHERE token = ? AND used = 0 AND expires_at > datetime(\'now\')',
            (token,)).fetchone()
    return dict(row) if row else None


def accept_invite(token, user_id):
    invite = get_invite(token)
    if not invite:
        return None
    with db_connect() as conn:
        conn.execute('UPDATE invites SET used = 1 WHERE token = ?', (token,))
        if invite['person_id']:
            conn.execute('UPDATE users SET person_id = ? WHERE id = ?', (invite['person_id'], user_id))
    return invite


# ── CRUD ──

def list_people():
    with db_connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM people ORDER BY generation, surname, given_names')]


def get_person(pid):
    with db_connect() as conn:
        r = conn.execute('SELECT * FROM people WHERE id = ?', (pid,)).fetchone()
        return dict(r) if r else None


def create_person(data):
    pid = data.get('id') or uuid.uuid4().hex[:8].upper()
    data['id'] = pid
    cols = [c for c in PEOPLE_COLS if c in data]
    vals = [data[c] for c in cols]
    ph = ','.join(['?'] * len(cols))
    with db_connect() as conn:
        conn.execute(f'INSERT INTO people ({",".join(cols)}) VALUES ({ph})', vals)
    return pid


def update_person(pid, data):
    cols = [c for c in PEOPLE_COLS if c in data and c != 'id']
    if not cols:
        return False
    sets = ', '.join(f'{c} = ?' for c in cols)
    vals = [data[c] for c in cols] + [pid]
    with db_connect() as conn:
        return conn.execute(f'UPDATE people SET {sets} WHERE id = ?', vals).rowcount > 0


def delete_person(pid):
    with db_connect() as conn:
        conn.execute('UPDATE people SET mother_id = NULL WHERE mother_id = ?', (pid,))
        conn.execute('UPDATE people SET father_id = NULL WHERE father_id = ?', (pid,))
        conn.execute('DELETE FROM partnerships WHERE person1_id = ? OR person2_id = ?', (pid, pid))
        return conn.execute('DELETE FROM people WHERE id = ?', (pid,)).rowcount > 0


def list_partnerships():
    with db_connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM partnerships')]


def create_partnership(data):
    p1, p2 = sorted([data['person1_id'], data['person2_id']])
    with db_connect() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO partnerships (person1_id, person2_id, type, marriage_date, marriage_location) VALUES (?,?,?,?,?)',
            (p1, p2, data.get('type', 'relationship'), data.get('marriage_date'), data.get('marriage_location'))
        )
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]


def update_partnership(ppid, data):
    cols = [c for c in ['type', 'start_date', 'marriage_date', 'marriage_location', 'end_date'] if c in data]
    if not cols:
        return False
    sets = ', '.join(f'{c} = ?' for c in cols)
    vals = [data[c] for c in cols] + [ppid]
    with db_connect() as conn:
        return conn.execute(f'UPDATE partnerships SET {sets} WHERE id = ?', vals).rowcount > 0


def delete_partnership(ppid):
    with db_connect() as conn:
        return conn.execute('DELETE FROM partnerships WHERE id = ?', (ppid,)).rowcount > 0


# ── Tree builder ──

def build_tree():
    people = list_people()
    partnerships = list_partnerships()
    nodes, edges, seen = [], [], set()

    for p in people:
        nodes.append({
            'id': p['id'],
            'name': make_display_name(p['given_names'], p['surname'], p['id']),
            'given_names': p['given_names'] or '',
            'surname': p['surname'] or '',
            'surname_birth': p['surname_birth'] or '',
            'gender': p['gender'] or 'other',
            'deceased': bool(p['deceased']),
            'birth_date': p['birth_date'],
            'death_date': p['death_date'],
            'birth_place': p['birth_place'] or '',
            'profession': p['profession'] or '',
            'company': p['company'] or '',
            'email': p['email'] or '',
            'interests': p['interests'] or '',
            'activities': p['activities'] or '',
            'bio_notes': p['bio_notes'] or '',
            'address': p['address'] or '',
            'home_tel': p['home_tel'] or '',
            'mobile': p['mobile'] or '',
            'photo': p['photo'] or '',
            'generation': p['generation'] or 0,
        })
        for col in ['mother_id', 'father_id']:
            parent = p[col]
            if parent:
                ek = (parent, p['id'])
                if ek not in seen:
                    seen.add(ek)
                    edges.append({'source': parent, 'target': p['id'], 'type': 'parent-child'})

    for pp in partnerships:
        ek = tuple(sorted([pp['person1_id'], pp['person2_id']]))
        if ek not in seen:
            seen.add(ek)
            edges.append({'source': pp['person1_id'], 'target': pp['person2_id'],
                          'type': 'partner', 'partnership_type': pp['type'] or 'relationship'})

    start = 'START' if any(n['id'] == 'START' for n in nodes) else (nodes[0]['id'] if nodes else '')
    return {'nodes': nodes, 'edges': edges, 'startPerson': start}


# ── Import ──

def import_json(data):
    parent_map = {}
    partner_pairs = []
    node_map = {n['id']: n for n in data.get('nodes', [])}

    for e in data.get('edges', []):
        src = e['source'] if isinstance(e['source'], str) else e['source']['id']
        tgt = e['target'] if isinstance(e['target'], str) else e['target']['id']
        if e['type'] == 'parent-child':
            if tgt not in parent_map:
                parent_map[tgt] = {}
            pn = node_map.get(src)
            if pn and pn.get('gender') == 'female':
                parent_map[tgt]['mother_id'] = src
            else:
                parent_map[tgt]['father_id'] = src
        elif e['type'] == 'partner':
            partner_pairs.append((src, tgt, e.get('partnership_type', 'relationship')))

    with db_connect() as conn:
        for n in data.get('nodes', []):
            conn.execute(
                '''INSERT OR REPLACE INTO people
                   (id, given_names, surname, surname_birth, gender,
                    birth_date, death_date, deceased, birth_place,
                    profession, company, email, home_tel, mobile,
                    address, interests, activities, bio_notes,
                    generation)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (n['id'], n.get('given_names', ''), n.get('surname', ''),
                 n.get('surname_birth', ''), n.get('gender', 'other'),
                 n.get('birth_date'), n.get('death_date'),
                 1 if n.get('deceased') else 0, n.get('birth_place', ''),
                 n.get('profession', ''), n.get('company', ''),
                 n.get('email', ''), n.get('home_tel', ''), n.get('mobile', ''),
                 n.get('address', ''), n.get('interests', ''),
                 n.get('activities', ''), n.get('bio_notes', ''),
                 n.get('generation', 0)))

        for child_id, parents in parent_map.items():
            if parents.get('mother_id'):
                conn.execute('UPDATE people SET mother_id = ? WHERE id = ?', (parents['mother_id'], child_id))
            if parents.get('father_id'):
                conn.execute('UPDATE people SET father_id = ? WHERE id = ?', (parents['father_id'], child_id))

        for p1, p2, ptype in partner_pairs:
            s1, s2 = sorted([p1, p2])
            conn.execute('INSERT OR REPLACE INTO partnerships (person1_id, person2_id, type) VALUES (?,?,?)',
                         (s1, s2, ptype))

    return len(data.get('nodes', []))


def save_photo(person_id, data_url):
    match = re.match(r'data:image/(\w+);base64,(.+)', data_url)
    if not match:
        return None
    ext = match.group(1).replace('jpeg', 'jpg')
    try:
        img_data = base64.b64decode(match.group(2))
    except Exception:
        return None
    PHOTOS_DIR.mkdir(exist_ok=True)
    filename = f'{person_id}.{ext}'
    (PHOTOS_DIR / filename).write_bytes(img_data)
    return filename


# ── HTTP Handler ──

class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, msg):
        self._json({'error': msg}, status)

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError) as e:
            self._error(400, f'Invalid JSON: {e}')
            return None

    def _get_user(self):
        cookie_header = self.headers.get('Cookie', '')
        c = SimpleCookie()
        try:
            c.load(cookie_header)
        except Exception:
            return None
        token = c.get('session')
        if not token:
            return None
        return get_session_user(token.value)

    def _require_auth(self):
        user = self._get_user()
        if not user:
            self._error(401, 'Sign in required')
            return None
        return user

    def _require_admin(self):
        user = self._require_auth()
        if user and user['role'] != 'admin':
            self._error(403, 'Admin access required')
            return None
        return user

    def do_GET(self):
        p = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        if p == '/api/tree':
            self._json(build_tree())
        elif p == '/api/people':
            self._json(list_people())
        elif p.startswith('/api/people/') and p.count('/') == 3:
            person = get_person(p.split('/')[-1])
            self._json(person) if person else self._error(404, 'Not found')
        elif p == '/api/partnerships':
            self._json(list_partnerships())
        elif p == '/api/auth/status':
            with db_connect() as conn:
                user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            self._json({'has_users': user_count > 0, 'needs_setup': user_count == 0})
        elif p == '/api/auth/me':
            user = self._get_user()
            if user:
                safe = {k: user[k] for k in ('id', 'email', 'display_name', 'person_id', 'role')}
                self._json(safe)
            else:
                self._json(None)
        elif p.startswith('/api/invites/') and p.count('/') == 3:
            token = p.split('/')[-1]
            invite = get_invite(token)
            if invite:
                person = get_person(invite['person_id']) if invite['person_id'] else None
                name = make_display_name(person['given_names'], person['surname'], person['id']) if person else None
                self._json({'token': invite['token'], 'person_id': invite['person_id'],
                            'person_name': name, 'email': invite['email'],
                            'expires_at': invite['expires_at']})
            else:
                self._error(404, 'Invite not found or expired')
        elif p.startswith('/api/photos/'):
            fname = Path(p.split('/')[-1]).name
            fpath = PHOTOS_DIR / fname
            if fpath.exists() and fpath.is_file():
                ct = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                      '.gif': 'image/gif', '.webp': 'image/webp'}.get(fpath.suffix.lower(), 'application/octet-stream')
                data = fpath.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('Content-Length', len(data))
                self.send_header('Cache-Control', 'max-age=3600')
                self.end_headers()
                self.wfile.write(data)
            else:
                self._error(404, 'Photo not found')
        elif p == '/api/search':
            q = (qs.get('q', [''])[0] or '').strip().lower()
            if not q:
                self._json([])
                return
            people = list_people()
            results = []
            for pp in people:
                name = make_display_name(pp['given_names'], pp['surname'], pp['id']).lower()
                fields = [name, (pp['given_names'] or '').lower(), (pp['surname'] or '').lower(),
                          (pp['surname_birth'] or '').lower(), (pp['profession'] or '').lower(),
                          (pp['birth_place'] or '').lower(), (pp['company'] or '').lower(),
                          (pp['bio_notes'] or '').lower(), (pp['interests'] or '').lower()]
                if any(q in f for f in fields):
                    results.append({'id': pp['id'], 'name': name,
                                    'given_names': pp['given_names'], 'surname': pp['surname'],
                                    'profession': pp['profession'], 'birth_place': pp['birth_place']})
            self._json(results)
        else:
            super().do_GET()

    def do_POST(self):
        p = urlparse(self.path).path
        body = self._body()
        if body is None:
            return

        if p == '/api/auth/register':
            email = (body.get('email') or '').strip().lower()
            password = body.get('password') or ''
            display_name = body.get('display_name') or ''
            invite_token = body.get('invite_token')
            if not email or not password:
                self._error(400, 'Email and password required')
                return
            if len(password) < 6:
                self._error(400, 'Password must be at least 6 characters')
                return
            with db_connect() as conn:
                user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            if user_count > 0 and not invite_token:
                self._error(403, 'Invite token required to register')
                return
            if invite_token and not get_invite(invite_token):
                self._error(403, 'Invalid or expired invite token')
                return
            try:
                uid = create_user(email, password, display_name)
            except sqlite3.IntegrityError:
                self._error(409, 'Email already registered')
                return
            if invite_token:
                accept_invite(invite_token, uid)
            token = create_session(uid)
            cookie = f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_DAYS * 86400}'
            user = get_session_user(token)
            safe = {k: user[k] for k in ('id', 'email', 'display_name', 'person_id', 'role')}
            self._json(safe, 201, cookie=cookie)

        elif p == '/api/auth/login':
            email = (body.get('email') or '').strip()
            password = body.get('password') or ''
            user = authenticate(email, password)
            if not user:
                self._error(401, 'Invalid email or password')
                return
            token = create_session(user['id'])
            cookie = f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_DAYS * 86400}'
            safe = {k: user[k] for k in ('id', 'email', 'display_name', 'person_id', 'role')}
            self._json(safe, cookie=cookie)

        elif p == '/api/auth/logout':
            cookie_header = self.headers.get('Cookie', '')
            c = SimpleCookie()
            try:
                c.load(cookie_header)
            except Exception:
                pass
            token = c.get('session')
            if token:
                delete_session(token.value)
            cookie = 'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
            self._json({'ok': True}, cookie=cookie)

        elif p == '/api/people':
            user = self._require_auth()
            if not user:
                return
            pid = create_person(body)
            self._json({'id': pid}, 201)

        elif p.endswith('/photo') and '/api/people/' in p:
            user = self._require_auth()
            if not user:
                return
            pid = p.split('/')[3]
            photo = body.get('photo')
            if not photo:
                self._error(400, 'Missing photo data')
                return
            fname = save_photo(pid, photo)
            if fname:
                update_person(pid, {'photo': fname})
                self._json({'photo': fname})
            else:
                self._error(400, 'Invalid photo data')

        elif p == '/api/partnerships':
            user = self._require_auth()
            if not user:
                return
            ppid = create_partnership(body)
            self._json({'id': ppid}, 201)

        elif p == '/api/import':
            user = self._require_admin()
            if not user:
                return
            count = import_json(body)
            self._json({'imported': count})

        elif p == '/api/invites':
            user = self._require_auth()
            if not user:
                return
            person_id = body.get('person_id')
            email = body.get('email')
            if not person_id:
                self._error(400, 'person_id required')
                return
            token = create_invite(person_id, email, user['id'])
            self._json({'token': token, 'url': f'/invite/{token}'})

        elif p.startswith('/api/invites/') and p.endswith('/accept'):
            user = self._require_auth()
            if not user:
                return
            token = p.split('/')[3]
            result = accept_invite(token, user['id'])
            if result:
                self._json({'ok': True, 'person_id': result['person_id']})
            else:
                self._error(404, 'Invite not found or expired')

        else:
            self._error(404, 'Not found')

    def do_PUT(self):
        p = urlparse(self.path).path
        body = self._body()
        if body is None:
            return

        if p.startswith('/api/people/') and p.count('/') == 3:
            user = self._require_auth()
            if not user:
                return
            ok = update_person(p.split('/')[-1], body)
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        elif p.startswith('/api/partnerships/'):
            user = self._require_auth()
            if not user:
                return
            ok = update_partnership(int(p.split('/')[-1]), body)
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        elif p == '/api/auth/link':
            user = self._require_auth()
            if not user:
                return
            person_id = body.get('person_id')
            if not person_id:
                self._error(400, 'person_id required')
                return
            with db_connect() as conn:
                existing = conn.execute('SELECT id FROM users WHERE person_id = ? AND id != ?',
                                        (person_id, user['id'])).fetchone()
                if existing:
                    self._error(409, 'This person is already claimed by another user')
                    return
                conn.execute('UPDATE users SET person_id = ? WHERE id = ?', (person_id, user['id']))
            self._json({'ok': True, 'person_id': person_id})
        else:
            self._error(404, 'Not found')

    def do_DELETE(self):
        p = urlparse(self.path).path

        if p.startswith('/api/people/') and p.count('/') == 3:
            user = self._require_admin()
            if not user:
                return
            ok = delete_person(p.split('/')[-1])
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        elif p.startswith('/api/partnerships/'):
            user = self._require_auth()
            if not user:
                return
            ok = delete_partnership(int(p.split('/')[-1]))
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        else:
            self._error(404, 'Not found')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, fmt, *args):
        try:
            req = str(args[0]) if args else ''
            if '/api/' in req:
                super().log_message(fmt, *args)
        except Exception:
            pass


def main():
    PHOTOS_DIR.mkdir(exist_ok=True)
    db_init()

    with db_connect() as conn:
        count = conn.execute('SELECT COUNT(*) FROM people').fetchone()[0]

    if count == 0:
        json_path = ROOT / 'data.json'
        if json_path.exists():
            data = json.loads(json_path.read_text())
            n = import_json(data)
            print(f'Imported {n} people from data.json')
        else:
            print('Empty database. Load a FamilyScript file or use the API.')
    else:
        print(f'Database has {count} people')

    with db_connect() as conn:
        user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    print(f'  Users: {user_count} (first registration becomes admin)')

    server = http.server.ThreadingHTTPServer(('', PORT), Handler)
    print(f'\nFamily Tree at http://localhost:{PORT}  (Ctrl+C to stop)')
    print(f'  Database: {DB_PATH}')
    print(f'  Photos:   {PHOTOS_DIR}/')
    print(f'  API docs: GET /api/tree, /api/people, /api/partnerships')
    print(f'  Auth:     POST /api/auth/register, /api/auth/login, GET /api/auth/me\n')
    threading.Timer(0.5, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
