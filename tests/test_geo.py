from pathlib import Path

from app import languages
from app.geo import PlaceStore, bearing_deg, compass, directions, offset, relative
from app.models import Landmark

DATA = Path(__file__).resolve().parent.parent / "data" / "places_demo.json"
PIN = (13.03600, 80.22100)


def heard_landmarks():
    return [
        Landmark(heard="முருகன் கோவில்", kind="temple", relation="opposite", name_hint_en="Murugan"),
        Landmark(heard="அப்போலோ பார்மசி", kind="pharmacy", relation="next_to", name_hint_en="Apollo"),
    ]


def test_two_lookalike_sites_found_and_pin_is_far_from_both():
    sites = PlaceStore(DATA).candidate_sites(*PIN, heard_landmarks())
    assert [s.id for s in sites] == ["S1", "S2"]
    near, far = sites
    assert near.covers_all and far.covers_all
    assert 430 < near.distance_from_pin_m < 470 and near.direction_from_pin == "north"
    assert 780 < far.distance_from_pin_m < 830 and far.direction_from_pin == "east"
    assert "bus_stop" in {p.kind for p in near.features}
    assert "petrol_pump" in {p.kind for p in far.features}


def test_generic_landmarks_alone_do_not_trigger_a_search():
    only_building = [Landmark(heard="green building", kind="building")]
    assert PlaceStore(DATA).candidate_sites(*PIN, only_building) == []


def test_keyterms_are_deduplicated_and_capped():
    terms = PlaceStore(DATA).keyterms(*PIN, radius_m=1500, limit=10)
    assert len(terms) == 10
    assert len({t.casefold() for t in terms}) == len(terms)


def test_relative_directions():
    assert relative(0, 5) == "ahead"
    assert relative(0, 50) == "ahead-right"
    assert relative(0, 270) == "left"
    assert relative(90, 270) == "behind"
    assert compass(bearing_deg(*PIN, 13.04005, 80.22103)) == "north"


def test_directions_and_arrival():
    rider = {"lat": PIN[0], "lon": PIN[1], "heading": 0}
    facts = directions(rider, 13.04005, 80.22103, arrive_radius_m=40)
    assert facts["relative"] == "ahead" and facts["compass"] == "north"
    assert facts["distance_m"] == 450 and facts["arrived"] is False
    lat, lon = offset(13.04005, 80.22103, 180, 20)
    assert directions({"lat": lat, "lon": lon, "heading": 0}, 13.04005, 80.22103, 40)["arrived"] is True


def test_script_check():
    assert languages.script_ok("हरी बिल्डिंग, Apollo Pharmacy के बगल में", "hi-IN")
    assert not languages.script_ok("The green building next to Apollo", "hi-IN")
    assert not languages.script_ok("பச்சை கலர் பில்டிங்", "hi-IN")
    assert languages.script_ok("பச்சை கலர் பில்டிங்", "ta-IN")
    assert languages.script_ok("Go straight", "en-IN")


def test_keyterms_only_use_the_scripts_asked_for():
    store = PlaceStore(DATA)

    def has_tamil(terms):
        return any("\u0b80" <= ch <= "\u0bff" for term in terms for ch in term)

    assert not has_tamil(store.keyterms(*PIN, radius_m=1500))
    assert has_tamil(store.keyterms(*PIN, radius_m=1500, local_langs={"ta-IN"}))
    assert store.keyterms(*PIN, radius_m=1500, limit=0) == []


def test_named_buildings_are_found_by_name_even_with_other_spellings():
    hostel = {"id": "my-1", "name": "Visvesvaraya Hostel", "kind": "hostel", "lat": 13.0380, "lon": 80.2210, "source": "you"}
    store = PlaceStore(DATA, extra=[hostel])
    heard = Landmark(heard="విశ్వేశ్వరయ్య hostel", kind="building", name_hint_en="Vishveshvaraya hostel")
    sites = store.candidate_sites(*PIN, [heard])
    assert len(sites) == 1 and sites[0].members[0].name == "Visvesvaraya Hostel"
    assert sites[0].members[0].source == "you"


def test_unnamed_generic_words_alone_still_find_nothing():
    store = PlaceStore(DATA, extra=[{"id": "my-1", "name": "Swimming Pool", "kind": "sports", "lat": 13.037, "lon": 80.221}])
    assert store.candidate_sites(*PIN, [Landmark(heard="the hostel", kind="building")]) == []
    pool = store.candidate_sites(*PIN, [Landmark(heard="swimming pool", kind="other", name_hint_en="swimming pool")])
    assert len(pool) == 1 and pool[0].members[0].name == "Swimming Pool"
