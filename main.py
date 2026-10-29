"""Backward-compatible entrypoint for Atlas.

Use the same CLI/TUI runtime as the installed `atlas` command. Importing this
module must not start a scanner or make network requests.
"""

from atlas_app import main


if __name__ == "__main__":
    raise SystemExit(main())
