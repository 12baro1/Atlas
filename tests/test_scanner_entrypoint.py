def test_legacy_scanner_entrypoint_is_the_same_side_effect_free_cli():
    import atlas_app
    import scanner

    assert scanner.main is atlas_app.main
