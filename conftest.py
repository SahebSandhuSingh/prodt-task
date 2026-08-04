import sys
import os

# Add root directory to sys.path before any test modules are collected
root_dir = os.path.abspath(os.path.dirname(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
