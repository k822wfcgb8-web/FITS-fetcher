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


def test_planet_sets_hold_one_visit_each_newest_first(product):
    """REQ-80: the planet moves and rotates between visits, so visits never mix."""
    old = [product(f, "WFC3/UVIS", visit="idg235", date="2018-06-06") for f in ("F395N", "F502N", "F631N")]
    new = [product(f, "WFC3/UVIS", visit="iemr40", date="2023-09-22") for f in ("F395N", "F502N", "F631N")]
    one = [product("F275W", "WFC3/UVIS", visit="ict902", date="2015-01-01")]
    sets = build_sets(old + new + one, min_filters=3)
    assert [(s.visit, s.date) for s in sets] == [("iemr40", "2023-09-22"), ("idg235", "2018-06-06")]
    assert sets[0].name == "WFC3-UVIS_F395N-F502N-F631N_iemr40"
    assert build_sets(old + new, min_filters=3, mix_instruments=True)[0].visit == "iemr40"


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


def test_grid_groups_mark_images_sharing_a_grid_in_two_or_more_filters(product):
    # M1 WFC3/UVIS narrowband (verification step 12): visits 06 and 04 each cover three filters, 08 only one.
    v6, v4, v8 = "HST visit 17500_06 WFC3/UVIS", "HST visit 17500_04 WFC3/UVIS", "HST visit 17500_08 WFC3/UVIS"
    uvis = lambda f, grid, exp: product(f, "WFC3/UVIS", obs_id=f"{grid}-{f}", exptime=exp, grid=grid)
    sets = build_sets([uvis("F487N", v8, 7808),
                       uvis("F502N", v6, 2460), uvis("F631N", v6, 3888), uvis("F673N", v6, 3888),
                       uvis("F502N", v4, 2460), uvis("F631N", v4, 3888), uvis("F673N", v4, 4000),
                       uvis("F656N", "", 9999)], min_filters=3)
    grids = sets[0].grids
    assert [(g.label, g.grid) for g in grids] == [("A", v4), ("B", v6)]  # same filter count, deeper first
    assert [p.filter for p in grids[0].products] == ["F502N", "F631N", "F673N"]
    assert all(v8 not in g.grid for g in grids)  # one filter only: no group
    assert sets[0].to_dict()["grids"][1]["product_keys"] == [p.key for p in grids[1].products]


# ---------- colour hint (REQ-82) ----------
def _hint(product, names, instrument="ACS/WFC"):
    sets = build_sets([product(f, instrument) for f in names], min_filters=2)
    return sets[0].to_dict()["colours"]


def test_colour_names_and_swatches(product):
    c = _hint(product, ["F435W", "F555W", "F658N", "F814W"])
    assert [(f["filter"], f["colour"]) for f in c["filters"]] == [
        ("F435W", "indigo"), ("F555W", "green"), ("F658N", "red"), ("F814W", "far red")]
    assert c["filters"][0]["swatch"] and c["filters"][3]["swatch"] is None  # far red is invisible: dashed swatch


def test_natural_colour_first_lists_unused_filters(product):
    c = _hint(product, ["F225W", "F275W", "F343N", "F395N", "F467M", "F502N", "F631N", "FQ727N", "F763M", "FQ889N"],
              "WFC3/UVIS")
    assert c["rgb"] == {"B": ["F395N", "F467M"], "G": ["F502N"], "R": ["F631N", "FQ727N"]}
    assert c["kind"] == "natural colour"
    assert c["unused"] == ["F225W", "F275W", "F343N", "F763M", "FQ889N"]


def test_infrared_split_in_thirds_keeps_close_filters_together(product):
    c = _hint(product, ["F150W2", "F212N", "F322W2", "F323N"], "NIRCAM/IMAGE")
    assert [f["colour"] for f in c["filters"]] == ["near-IR", "near-IR", "thermal IR", "thermal IR"]
    assert c["rgb"] == {"B": ["F150W2"], "G": ["F212N"], "R": ["F322W2", "F323N"]}
    assert c["kind"] == "false colour (all infrared)"


def test_two_filters_and_missing_colour(product):
    c = _hint(product, ["g", "r"], "GPC1")
    assert c["rgb"] == {"B": ["g"], "G": [], "R": ["r"]} and c["kind"] == "approximate colour (no green filter)"
    c = _hint(product, ["F435W", "F658N", "F814W"])
    assert c["rgb"] == {"B": ["F435W"], "G": ["F658N"], "R": ["F814W"]}
    assert c["kind"] == "partly natural (includes infrared)"


def test_many_filters_split_evenly(product):
    """M51's NIRCam set: splitting at the largest jumps gave 1, 9 and 6 filters."""
    names = ["F115W", "F140M", "F150W", "F164N", "F182M", "F187N", "F200W", "F210M", "F212N", "F250M", "F300M",
             "F335M", "F360M", "F405N", "F430M", "F444W"]
    c = _hint(product, names, "NIRCAM/IMAGE")
    assert [len(c["rgb"][ch]) for ch in "BGR"] == [4, 7, 5]
    miri = _hint(product, ["F560W", "F770W", "F1000W", "F1130W", "F1280W", "F1500W", "F1800W", "F2100W"], "MIRI/IMAGE")
    assert miri["rgb"]["G"] == ["F1130W", "F1280W"]


def test_omegacam_halpha_filter_counts_as_halpha():
    """NB659 (653-665 nm) is centred nearer [NII] but is OmegaCAM's Hα filter (verification step 20)."""
    from fits_fetcher.archives.base import Product
    vst = [Product(archive="ESO", collection="VST", telescope="VST", instrument="OmegaCAM", filter=f, obs_id=f,
                   url="https://example/x", wavelength_um=wl, band_type=band)
           for f, wl, band in (("g", 0.48, "broad"), ("r", 0.62, "broad"), ("NB659", 0.659, "narrow"))]
    (s,) = build_sets(vst, min_filters=3)
    assert "NB659 Hα" in s.readiness
    assert next(r for r in s.to_dict()["rows"] if r["filter"] == "NB659")["line"] == "Hα"
    (ha,) = build_sets(vst, min_filters=1, lines={"Hα"})
    assert [r.filter for r in ha.rows] == ["NB659"]
