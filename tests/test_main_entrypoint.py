import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_main_entrypoint_reuses_supported_cli_without_scanning_on_import():
    import main
    import atlas_app

    assert main.main is atlas_app.main
