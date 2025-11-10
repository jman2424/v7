"""
CLI for AI Sales Assistant ops.

Commands:
  seed                 Generate example tenant data.
  snapshot --tenant K  Create snapshot tar.gz for tenant K.
  restore  --tenant K  Restore from snapshot path (dry-run by default).
  validate --tenant K  Validate tenant JSON (schema + duplicate SKUs).
  synonyms --tenant K  Rebuild synonym suggestions from logs.
  export-analytics     Export analytics to CSV.

Connections:
- scripts/* modules provide the heavy lifting.
- retrieval/storage.py used by validate/restore paths.

Usage:
  python -m cli seed --tenant EXAMPLE
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Lazy imports so CLI loads fast and scripts remain optional at build time
def _m_import(mod: str):
    return __import__(mod, fromlist=["*"])


def cmd_seed(args: argparse.Namespace) -> int:
    scripts = _m_import("scripts.seed_example_data")
    return int(bool(scripts.main(tenant=args.tenant)))


def cmd_snapshot(args: argparse.Namespace) -> int:
    scripts = _m_import("scripts.snapshot_backup")
    out = scripts.main(tenant=args.tenant, out_dir=args.output)
    print(out)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    scripts = _m_import("scripts.restore_snapshot")
    res = scripts.main(tenant=args.tenant, snapshot=args.snapshot, apply=args.apply)
    print(res)
    return 0 if res.get("ok") else 1


def cmd_validate(args: argparse.Namespace) -> int:
    scripts = _m_import("scripts.validate_catalog")
    ok = scripts.main(tenant=args.tenant, business_dir=args.business_dir)
    print("VALID" if ok else "INVALID")
    return 0 if ok else 2


def cmd_synonyms(args: argparse.Namespace) -> int:
    scripts = _m_import("scripts.rebuild_synonyms")
    res = scripts.main(tenant=args.tenant, preview=not args.apply)
    print(res)
    return 0


def cmd_export_analytics(args: argparse.Namespace) -> int:
    scripts = _m_import("scripts.export_analytics_csv")
    path = scripts.main(out_path=args.output, tenant=args.tenant)
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-sales-cli",
        description="Operational CLI for AI Sales Assistant"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("seed", help="Generate example tenant data")
    sp.add_argument("--tenant", default="EXAMPLE")
    sp.set_defaults(func=cmd_seed)

    sp = sub.add_parser("snapshot", help="Create snapshot tar.gz for a tenant")
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--output", default=str(Path("backups")))
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("restore", help="Restore from a snapshot")
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--snapshot", required=True, help="Path to .tar.gz")
    sp.add_argument("--apply", action="store_true", help="Actually apply changes (otherwise dry-run)")
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("validate", help="Validate tenant JSON against schemas")
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--business-dir", default=str(Path("business")))
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("synonyms", help="Rebuild synonym suggestions from logs")
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--apply", action="store_true", help="Write suggestions into synonyms.json")
    sp.set_defaults(func=cmd_synonyms)

    sp = sub.add_parser("export-analytics", help="Export analytics CSV")
    sp.add_argument("--tenant", required=False, help="Filter by tenant")
    sp.add_argument("--output", default=str(Path("analytics_export.csv")))
    sp.set_defaults(func=cmd_export_analytics)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
