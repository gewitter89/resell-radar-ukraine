"""Delete old DB and recreate with new schema."""
import os
import sys
sys.path.insert(0, ".")

db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resell_radar.db")
print(f"DB path: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    os.remove(db_path)
    print("Deleted old DB")

from app.storage.database import init_sync_db, sync_engine
from app.storage.models import Ad

# Verify column exists before init
print(f"Ad has analysis_json: {hasattr(Ad, 'analysis_json')}")

init_sync_db()
print("DB recreated")

# Verify table has column
from sqlalchemy import inspect
inspector = inspect(sync_engine)
columns = [c["name"] for c in inspector.get_columns("ads")]
print(f"Ads columns: {columns}")
print(f"analysis_json in columns: {'analysis_json' in columns}")
