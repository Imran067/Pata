"""Rules from field testing on a campus: whose words count, unknown names, genders."""
from pathlib import Path

from app.evon_tasks import language_rule
from app.geo import PlaceStore
from app.models import Landmark
from app.pipeline import Pata

DATA = Path(__file__).resolve().parent.parent / "data" / "places_demo.json"
EARLIER = [{"speaker": "rider", "text": "मैं सतीश धवन हॉस्टल के पास swimming pool पर हूँ, gate नहीं मिल रहा",
            "gloss_en": "I'm at Satish Dhawan Hostel near the swimming pool and can't find the gate.",
            "relayed": "నేను సతీష్ ధావన్ హాస్టల్ దగ్గర ఉన్నాను"}]
NOW = "SN Bose hostel gate ముందుకు రండి"


def test_landmarks_taken_from_the_riders_earlier_words_are_ignored():
    assert Pata._from_earlier_turns(Landmark(heard="Satish Dhawan Hostel", kind="hostel", name_hint_en="Satish Dhawan Hostel"), NOW, EARLIER)
    assert Pata._from_earlier_turns(Landmark(heard="swimming pool", kind="sports", name_hint_en="swimming pool"), NOW, EARLIER)
    assert not Pata._from_earlier_turns(Landmark(heard="SN Bose hostel", kind="hostel", name_hint_en="SN Bose Hostel"), NOW, EARLIER)


def test_a_named_place_missing_from_the_map_is_reported_not_swapped_for_another():
    store = PlaceStore(DATA, extra=[{"id": "my-1", "name": "Satish Dhawan Hostel", "kind": "hostel", "lat": 13.0365, "lon": 80.2210}])
    unknown: list[str] = []
    sites = store.candidate_sites(13.036, 80.221, [Landmark(heard="SN Bose hostel", kind="hostel", name_hint_en="SN Bose Hostel")],
                                  unknown=unknown)
    assert sites == [] and unknown == ["SN Bose Hostel"]


def test_every_evon_request_says_not_to_assume_gender():
    for code in ("hi-IN", "ta-IN", "en-IN"):
        assert "gender" in language_rule("say", code)
