import sys
import os

# Reconfigure stdout/stderr to support emojis on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Add project root to system path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.storage.database import init_db, db_session
from app.storage.models import Ad, UserFeedback, CategoryStats, MarketSnapshot

def clear_database():
    print("=== CLEARING ALL MOCK DATA FROM RESELL RADAR DATABASE ===")
    init_db()
    with db_session() as session:
        session.query(UserFeedback).delete()
        session.query(Ad).delete()
        session.query(CategoryStats).delete()
        session.query(MarketSnapshot).delete()
        session.commit()
    print("✅ Database cleared successfully! Ready for real live monitoring.")

if __name__ == "__main__":
    clear_database()
