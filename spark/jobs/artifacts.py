"""Small artifact writers shared by notebooks 03, 04 and 05."""

import csv
import json
from pathlib import Path


def write_rows_csv(path, columns, rows) -> None:
    """Write collected rows (dicts) as CSV with an explicit column order."""
    path = Path(path)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[column] for column in columns])
    print(f'wrote {path} ({len(rows)} rows)')


def write_json(path, payload) -> None:
    """Write a JSON artifact (numpy/other values stringified)."""
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    print('wrote', path)


def update_registry(path, sections: dict) -> dict:
    """Merge ``sections`` into ``model_selection.json`` instead of overwriting it."""
    path = Path(path)
    registry = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    registry.update(sections)
    path.write_text(json.dumps(registry, indent=2, default=str), encoding='utf-8')
    print('registry sections:', sorted(registry))
    return registry
