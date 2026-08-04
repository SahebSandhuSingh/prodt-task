import sys
from pathlib import Path

# Add project root directory to sys.path so pytest can discover adapters, mocks, and schemas
project_root = str(Path(__file__).parent.parent.resolve())
if project_root not in sys.path:
    sys.path.insert(0, project_root)
