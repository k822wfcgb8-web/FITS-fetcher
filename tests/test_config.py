from fits_fetcher.config import Settings


def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    Settings(min_filters=4, hst_show_mosaics=True).save(path)
    loaded = Settings.load(path)
    assert loaded.min_filters == 4 and loaded.hst_show_mosaics is True


def test_missing_file_gives_defaults(tmp_path):
    assert Settings.load(tmp_path / "nope.json") == Settings()


def test_unknown_keys_ignored_and_corrupt_file_tolerated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"min_filters": 5, "from_a_future_version": 1}')
    assert Settings.load(path).min_filters == 5
    path.write_text("{not json")
    assert Settings.load(path) == Settings()
