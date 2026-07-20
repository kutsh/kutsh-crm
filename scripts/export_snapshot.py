#!/usr/bin/env python3
"""Façade CLI historique — la logique vit désormais dans `crm_export` (module packagé).

Conservée pour ne pas casser les appels existants (cron serveur, documentation,
habitudes). Strictement équivalente à `python -m crm_export`.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crm_export import main  # noqa: E402  # type: ignore[import-not-found]

if __name__ == "__main__":
    main()
