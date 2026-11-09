"""Backward-compatible scanner entrypoint routed through the current Atlas CLI.

The former module-level CCXT scanner duplicated market selection and network
startup outside AtlasRuntime/AtlasMainEngine. Use the same terminal workflow as
`atlas`, `main.py`, and `atlas_entry.py`.
"""

from atlas_app import main


if __name__ == "__main__":
    raise SystemExit(main())
