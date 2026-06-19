# Family Galaxy

Interactive family tree visualizer with a space-themed UI. Click nodes to explore relationships, edit profiles, upload photos, and export data.

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
- **Edit profiles**: click Edit in the sidebar to modify names, dates, profession, contact info
- **Photo upload**: attach profile photos (stored locally in `photos/`)
- **Add/delete people**: full CRUD from the UI
- **Search**: `/` to search by name, `F` to fit all, `C` to center on start person
- **Drag-and-drop import**: load FamilyScript files directly
- **Export**: download full tree as JSON
- **Minimap**: bottom-right corner shows viewport position

## API

All data is stored in a SQLite database (`family.db`). The server exposes a REST API:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tree` | Full tree (nodes + edges) for the frontend |
| `GET` | `/api/people` | List all people |
| `GET` | `/api/people/:id` | Get one person |
| `POST` | `/api/people` | Create a person |
| `PUT` | `/api/people/:id` | Update a person |
| `DELETE` | `/api/people/:id` | Delete a person (cascades) |
| `POST` | `/api/people/:id/photo` | Upload photo (base64 JSON) |
| `GET` | `/api/photos/:file` | Serve a photo |
| `GET` | `/api/partnerships` | List partnerships |
| `POST` | `/api/partnerships` | Create a partnership |
| `PUT` | `/api/partnerships/:id` | Update a partnership |
| `DELETE` | `/api/partnerships/:id` | Delete a partnership |
| `POST` | `/api/import` | Import tree data (JSON) |

### Example: create a person

```bash
curl -X POST http://localhost:8000/api/people \
  -H 'Content-Type: application/json' \
  -d '{"given_names": "Jane", "surname": "Doe", "gender": "female", "birth_date": "1990 Mar 15"}'
```

### Example: upload a photo

```bash
# Base64 encode and send
BASE64=$(base64 -w0 photo.jpg)
curl -X POST http://localhost:8000/api/people/START/photo \
  -H 'Content-Type: application/json' \
  -d "{\"photo\": \"data:image/jpeg;base64,$BASE64\"}"
```

## Files

| File | Purpose |
|------|---------|
| `server.py` | API server + SQLite database (zero dependencies) |
| `index.html` | Frontend visualization (D3.js) |
| `parse.py` | FamilyScript parser (converts `.txt` to `data.json`) |
| `family.db` | SQLite database (auto-created, gitignored) |
| `photos/` | Uploaded photos (gitignored) |

## Data Format

The app uses **SQLite** as its primary database. FamilyScript (Family Echo's `.txt` format) is supported for import only.

Why not FamilyScript as the database?
- Stores photo URLs, not actual images
- Tab-separated with fragile escaping
- No schema versioning or extensibility
- Only used by Family Echo

The SQLite schema has two tables: `people` (26 columns including photo path, parent foreign keys) and `partnerships` (type, dates, location).

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` or `Ctrl+K` | Focus search |
| `F` | Fit all nodes in view |
| `C` | Center on start person |
| `Escape` | Deselect / clear search |

## License

MIT
