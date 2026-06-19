# Family Galaxy

Interactive family tree visualizer with a space-themed UI. Click nodes to explore relationships, edit profiles, upload photos, and invite family members to collaborate.

## Quick Start

```bash
# Generate sample data
python3 parse.py sample.familyscript

# Start the server (zero dependencies, just Python 3)
python3 server.py
```

Opens at `http://localhost:8000`. The SQLite database (`family.db`) is created automatically on first run.

You can also drag-and-drop any FamilyScript `.txt` export (from [Family Echo](https://familyecho.com)) directly onto the page.

## Features

- **Clustered layout**: families automatically group by surname with colored backgrounds
- **Focused view**: click any person to animate their immediate family into a compact view
- **Search**: search by name, profession, birthplace, company, or notes with `/`
- **User accounts**: register and sign in to edit; first user becomes admin
- **Invite system**: generate invite links for family members to claim their profiles
- **Edit profiles**: click Edit in the sidebar to modify names, dates, profession, contact info
- **Photo upload**: attach profile photos when creating or editing people
- **Import/Export**: import JSON files or export the full tree as JSON
- **Drag-and-drop**: load FamilyScript files directly onto the page
- **Minimap**: bottom-right corner shows viewport position

## Multi-User Setup

1. Start the server and register the first account (becomes admin)
2. Click any person node, then click **Invite** to generate a shareable link
3. Share the link with family members; they register and claim their profile
4. Members can edit profiles and add people; admins can also delete and import data

Invite links are valid for 7 days. Users who claim a profile see their node highlighted in green.

## API

All data is stored in a SQLite database (`family.db`). The server exposes a REST API:

### Tree & People

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/tree` | Full tree (nodes + edges) | No |
| `GET` | `/api/people` | List all people | No |
| `GET` | `/api/people/:id` | Get one person | No |
| `POST` | `/api/people` | Create a person | Yes |
| `PUT` | `/api/people/:id` | Update a person | Yes |
| `DELETE` | `/api/people/:id` | Delete a person | Admin |
| `POST` | `/api/people/:id/photo` | Upload photo (base64 JSON) | Yes |
| `GET` | `/api/photos/:file` | Serve a photo | No |
| `GET` | `/api/search?q=term` | Search people by multiple fields | No |

### Partnerships

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/partnerships` | List partnerships | No |
| `POST` | `/api/partnerships` | Create a partnership | Yes |
| `PUT` | `/api/partnerships/:id` | Update a partnership | Yes |
| `DELETE` | `/api/partnerships/:id` | Delete a partnership | Yes |

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register` | Create account (email, password, display_name) |
| `POST` | `/api/auth/login` | Sign in (email, password) |
| `POST` | `/api/auth/logout` | Sign out |
| `GET` | `/api/auth/me` | Current user info |
| `PUT` | `/api/auth/link` | Link user to a person_id ("This is me") |

### Invites

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/invites` | Create invite (person_id, email) | Yes |
| `GET` | `/api/invites/:token` | Validate invite | No |
| `POST` | `/api/invites/:token/accept` | Accept invite, link to profile | Yes |

### Import

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/import` | Import tree data (JSON) | Admin |

### Example: create a person

```bash
curl -X POST http://localhost:8000/api/people \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  -d '{"given_names": "Jane", "surname": "Doe", "gender": "female", "birth_date": "1990 Mar 15"}'
```

### Example: upload a photo

```bash
BASE64=$(base64 -w0 photo.jpg)
curl -X POST http://localhost:8000/api/people/START/photo \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  -d "{\"photo\": \"data:image/jpeg;base64,$BASE64\"}"
```

## Files

| File | Purpose |
|------|---------|
| `server.py` | API server + SQLite + auth (zero dependencies) |
| `index.html` | Frontend visualization (D3.js) |
| `parse.py` | FamilyScript parser (converts `.txt` to `data.json`) |
| `family.db` | SQLite database (auto-created, gitignored) |
| `photos/` | Uploaded photos (gitignored) |

## Data Format

The app uses **SQLite** as its primary database. FamilyScript (Family Echo's `.txt` format) is supported for import only.

The SQLite schema has five tables: `people` (26 columns), `partnerships` (type, dates, location), `users` (email, password hash, linked person), `sessions`, and `invites`.

Passwords are hashed with PBKDF2-HMAC-SHA256 (100k iterations). Sessions use HttpOnly SameSite cookies.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` or `Ctrl+K` | Focus search |
| `F` | Fit all nodes in view |
| `C` | Center on start person |
| `Escape` | Deselect / clear search |

## License

MIT
