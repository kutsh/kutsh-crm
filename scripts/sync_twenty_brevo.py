#!/usr/bin/env python3
"""Façade CLI historique — la logique vit désormais dans `crm_brevo` (module packagé).

Conservée pour ne pas casser les appels existants (documentation, habitudes).
Équivalente à `python -m crm_brevo`, à une chose près : `ensure` fait ici
précéder la création des listes Brevo par celle des champs newsletter côté
Twenty (`configure_newsletter_fields.py`). C'est une migration de schéma jouée
une fois, qui n'a rien à faire dans un job récurrent — le module ne touche donc
qu'à Brevo.
"""
from __future__ import annotations
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crm_brevo  # noqa: E402  # type: ignore[import-not-found]


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "ensure":
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "configure_newsletter_fields.py")],
            check=True,
        )
    return crm_brevo.main(argv)


if __name__ == "__main__":
    sys.exit(main())
