#!/usr/bin/env python3
"""Family Tree API server with SQLite database. Zero external dependencies."""

import base64
import http.server
import json
import os
import re
import sqlite3
import threading
import uuid
import webbrowser
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DB_PATH = ROOT / 'family.db'
PHOTOS_DIR = ROOT / 'photos'
PORT = 8000

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
        # Pass 1: insert all people without parent refs
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

        # Pass 2: set parent references
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

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
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

    def do_GET(self):
        p = urlparse(self.path).path

        if p == '/api/tree':
            self._json(build_tree())
        elif p == '/api/people':
            self._json(list_people())
        elif p.startswith('/api/people/') and p.count('/') == 3:
            person = get_person(p.split('/')[-1])
            self._json(person) if person else self._error(404, 'Not found')
        elif p == '/api/partnerships':
            self._json(list_partnerships())
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
        else:
            super().do_GET()

    def do_POST(self):
        p = urlparse(self.path).path
        body = self._body()
        if body is None:
            return

        if p == '/api/people':
            pid = create_person(body)
            self._json({'id': pid}, 201)
        elif p.endswith('/photo') and '/api/people/' in p:
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
            ppid = create_partnership(body)
            self._json({'id': ppid}, 201)
        elif p == '/api/import':
            count = import_json(body)
            self._json({'imported': count})
        else:
            self._error(404, 'Not found')

    def do_PUT(self):
        p = urlparse(self.path).path
        body = self._body()
        if body is None:
            return

        if p.startswith('/api/people/') and p.count('/') == 3:
            ok = update_person(p.split('/')[-1], body)
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        elif p.startswith('/api/partnerships/'):
            ok = update_partnership(int(p.split('/')[-1]), body)
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        else:
            self._error(404, 'Not found')

    def do_DELETE(self):
        p = urlparse(self.path).path

        if p.startswith('/api/people/') and p.count('/') == 3:
            ok = delete_person(p.split('/')[-1])
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        elif p.startswith('/api/partnerships/'):
            ok = delete_partnership(int(p.split('/')[-1]))
            self._json({'ok': True}) if ok else self._error(404, 'Not found')
        else:
            self._error(404, 'Not found')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
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

    server = http.server.ThreadingHTTPServer(('', PORT), Handler)
    print(f'\nFamily Tree at http://localhost:{PORT}  (Ctrl+C to stop)')
    print(f'  Database: {DB_PATH}')
    print(f'  Photos:   {PHOTOS_DIR}/')
    print(f'  API docs: GET /api/tree, /api/people, /api/partnerships\n')
    threading.Timer(0.5, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
