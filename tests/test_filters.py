import pytest

from fits_fetcher import filters


@pytest.mark.parametrize("name, instrument, wavelength, band", [
    ("F435W", "ACS/WFC", 0.435, "broad"),
    ("F658N", "ACS/WFC", 0.658, "narrow"),
    ("F218W", "WFPC2/PC", 0.218, "broad"),       # WFPC2 UV: nm
    ("F160W", "WFC3/IR", 1.60, "broad"),         # HST IR: 10 nm units
    ("F222M", "NICMOS/NIC3", 2.22, "broad"),
    ("F200W", "NIRCAM/IMAGE", 2.00, "broad"),    # JWST
    ("F405N", "NIRCAM/IMAGE", 4.05, "narrow"),
    ("F1000W", "MIRI/IMAGE", 10.0, "broad"),
    ("r", "GPC1", 0.62, "broad"),
    ("W3", "", 12.0, "broad"),
])
def test_parse(name, instrument, wavelength, band):
    wl, kind = filters.parse(name, instrument)
    assert wl == pytest.approx(wavelength)
    assert kind == band


def test_parse_unknown():
    assert filters.parse("MIRVIS", "STIS/CCD") == (None, "broad")


@pytest.mark.parametrize("raw, expected", [
    ("F814W", "F814W"),
    ("CLEAR1L;F435W", "F435W"),       # clear wheel position dropped
    ("F444W;F405N", "F405N"),         # JWST pupil narrowband inside a wide filter
    ("F150W2;F164N", "F164N"),
    ("detection", None),              # HLA/HAP white-light images
    ("F814W;F555W;F435W", None),
    ("F435W;F814W", None),            # two broadband filters: not one passband
    ("", None),
    ("F150W2;F162M", "F162M"),
    ("F606W-POL0V", None),            # polarizers (HAP joins parts with '-')
    ("F547M-POLQ", None),
    ("FR656N", None),                 # ramp filter: passband varies across the image
])
def test_effective_filter(raw, expected):
    assert filters.effective_filter(raw) == expected


def test_line_for():
    assert filters.line_for(0.656) == "Hα"
    assert filters.line_for(0.502) == "[OIII]"
    assert filters.line_for(0.80) is None
    assert filters.line_for(None) is None
    # OmegaCAM's NB_659 is centred nearer [NII] but is the Hα filter; HST's F658N stays [NII].
    assert filters.line_for(0.659, filter_name="NB659") == "Hα"
    assert filters.line_for(0.6584, filter_name="F658N") == "[NII]"


def test_quad_filters_are_narrowband():
    assert filters.parse("FQ727N", "WFC3/UVIS") == (0.727, "narrow")


@pytest.mark.parametrize("wl, name", [(0.3, "UV"), (0.40, "violet"), (0.432, "indigo"), (0.501, "green"),
                                      (0.6563, "red"), (0.727, "deep red"), (0.814, "far red"), (1.5, "near-IR"),
                                      (3.23, "thermal IR"), (7.7, "mid-IR"), (None, "?")])
def test_colour_names(wl, name):
    assert filters.colour(wl)[0] == name
