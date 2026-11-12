"""Delete all stored voice transcripts (run after judging - Responsible AI baseline)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import build_ledger  # noqa: E402
print("deleted", build_ledger().purge_transcripts(), "transcript rows")
