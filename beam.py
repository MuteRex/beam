#!/usr/bin/env python3
"""Launch Beam without installing it (python ~/beam/beam.py)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from beam.main import main
raise SystemExit(main())
