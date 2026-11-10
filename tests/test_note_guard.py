"""Doorstep notes keep only room numbers, floors and cautions that the address or the call support."""
from app import prompts
from app.note_guard import address_unit, guard_note

CALL = ("Bhaiya, main swimming pool ke back gate pe hoon. Dada, location ta wrong. SN Bose hostel er main gate "
        "e chole ashun. The location is wrong. Come to the main gate of SN Bose Hostel.")
# The note a 4-bit Evon wrote after copying the old prompt's example.
REPORTED = {"building_description": "SN Bose Hostel", "entrance": "front gate", "floor": "ground",
            "landmarks": ["SN Bose Hostel"], "cautions": ["The gate may be closed, check with hostel staff"],
            "summary_en": "Front gate of SN Bose Hostel, room 105, ground floor."}


def test_the_reported_note_takes_the_room_from_the_address_and_drops_guesses():
    note, changes = guard_note(REPORTED, "Room 214, IIT (BHU) campus", CALL)
    assert note["summary_en"] == "Front gate of SN Bose Hostel, Room 214."
    assert note["floor"] is None and note["cautions"] == []
    assert len(changes) == 3


def test_an_invented_room_is_removed_when_the_address_has_none():
    note, _ = guard_note(REPORTED, "IIT (BHU) campus, Varanasi", CALL)
    assert "105" not in note["summary_en"] and note["summary_en"] == "Front gate of SN Bose Hostel."


def test_facts_really_said_in_the_call_are_kept():
    said = {**REPORTED, "floor": "second", "cautions": ["A dog at the gate"],
            "summary_en": "Main gate of SN Bose Hostel, room 214, second floor."}
    note, changes = guard_note(said, "IIT (BHU) campus", CALL + " Room 214, second floor. Careful, a dog at the gate.")
    assert note == said and changes == []


def test_an_old_note_is_corrected_from_the_address_when_read_out():
    note, _ = guard_note(REPORTED, "Room 214, IIT (BHU) campus", heard=None)
    assert "Room 214" in note["summary_en"] and "105" not in note["summary_en"]


def test_address_units_are_read_as_written():
    assert address_unit("Flat 3C, near Murugan temple, Chennai") == "Flat 3C"
    assert address_unit("H.No 12/4, Lanka, Varanasi") == "H.No 12/4"
    assert address_unit("IIT (BHU) campus") is None


def test_prompts_hold_no_example_a_model_could_copy_as_fact():
    assert "105" not in prompts.NOTE and "SN Bose" not in prompts.NOTE
    assert "rider_name" in prompts.BRIEFING and "customer_name" in prompts.BRIEFING
