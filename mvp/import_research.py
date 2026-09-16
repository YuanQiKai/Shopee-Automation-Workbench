"""Import captured MCP responses, with a recoverable SQLite backup first."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import research
import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--transport', choices=['manual_import', 'agent-mcp'], default='manual_import')
    args = parser.parse_args()
    bundle = json.loads(args.file.read_text(encoding='utf-8-sig'))
    server.init_db()
    target = server.DB_PATH.parent / ('before-research-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
    with sqlite3.connect(server.DB_PATH) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
    with server.connect() as db:
        result = research.import_bundle(db, bundle, args.transport)
        if not db.execute("SELECT 1 FROM records WHERE kind='research_policy' AND id='main'").fetchone():
            research.save(db, 'research_policy', research.DEFAULT_POLICY)
        profile = research.source_profile(research.observations_with_conflicts(db))
    print(json.dumps({'backup': str(target), 'batchId': result['id'], 'profile': profile}, ensure_ascii=True))


if __name__ == '__main__':
    main()
