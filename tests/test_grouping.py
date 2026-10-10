from fits_fetcher.grouping import build_sets


def acs_and_ps1(product):
    return [
        product("F435W"), product("F555W"), product("F814W"), product("F814W", exptime=5000), product("F658N"),
        product("g", "GPC1", collection="PS1", scale=0.25), product("r", "GPC1", collection="PS1", scale=0.25),
    ]


def test_one_set_per_instrument_with_min_filters(product):
    sets = build_sets(acs_and_ps1(product), min_filters=3)
    assert [s.instruments for s in sets] == [["ACS/WFC"]]  # PS1 has only 2 filters
    acs = sets[0]
    assert [r.filter for r in acs.rows] == ["F435W", "F555W", "F658N", "F814W"]  # by wavelength
    assert acs.name == "ACS-WFC_F435W-F555W-F658N-F814W"


def test_same_filter_products_share_a_row_deepest_first(product):
    acs = build_sets(acs_and_ps1(product), min_filters=3)[0]
    f814 = next(r for r in acs.rows if r.filter == "F814W")
    assert [p.exptime_s for p in f814.products] == [5000, 1000]


def test_min_filters_two_keeps_ps1(product):
    sets = build_sets(acs_and_ps1(product), min_filters=2)
    assert {tuple(s.instruments) for s in sets} == {("ACS/WFC",), ("GPC1",)}


def test_mixing_makes_one_set_and_warns_on_pixel_scale(product):
    sets = build_sets(acs_and_ps1(product), min_filters=3, mix_instruments=True, pixel_scale_warn_ratio=4)
    assert len(sets) == 1
    assert len(sets[0].rows) == 6
    assert sets[0].warnings and "5×" in sets[0].warnings[0]


def test_band_type_and_line_filters(product):
    prods = acs_and_ps1(product) + [product("F656N"), product("F502N")]
    narrow = build_sets(prods, min_filters=2, band_type="narrow")
    assert [r.filter for r in narrow[0].rows] == ["F502N", "F656N", "F658N"]
    ha_oiii = build_sets(prods, min_filters=2, lines={"Hα", "[OIII]"})
    assert [r.filter for r in ha_oiii[0].rows] == ["F502N", "F656N"]


def test_readiness_summary(product):
    acs = build_sets(acs_and_ps1(product) + [product("F656N")], min_filters=3)[0]
    assert acs.readiness.startswith("3 broadband (F435W, F555W, F814W) + 2 narrowband (F656N Hα")
