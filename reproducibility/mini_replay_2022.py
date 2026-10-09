"""Compatibility entry point; no independent mini production chain remains.

Use REPRODUIRE_TOUT.ps1 -ControleCourt. Old command-line calls are redirected to
the complete production orchestrator, with only the explicit scope changed.
The old 2022 mini artifacts are evidence of an earlier test, not a current run.
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    arguments = list(sys.argv[1:])
    if "--profile" in arguments:
        index = arguments.index("--profile")
        if index + 1 >= len(arguments) or arguments[index + 1] not in {"court2022", "dix2022"}:
            raise SystemExit("Ancien profil inconnu; utiliser REPRODUIRE_TOUT.ps1 -ControleCourt")
        del arguments[index:index + 2]
    if "--scope" in arguments:
        raise SystemExit("Ce point d'entree ancien impose le perimetre court")
    os.environ["LONGITUDINAL_REPLICATION_SCOPE"] = "court"
    sys.argv = ["reproducibility.replication_complete", *arguments, "--scope", "court"]
    from reproducibility.replication_complete import main as production_main
    production_main()


if __name__ == "__main__":
    main()
