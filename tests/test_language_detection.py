"""Each person's language comes from their own speech, checked before Pata acts on it."""
from app.language_tracking import LangState, update

KANNADA = "ನಾನು ಮುರುಗನ್ ದೇವಸ್ಥಾನದ ಎದುರು ಇದ್ದೇನೆ"
TAMIL = "முருகன் கோவில் எதிரே, அப்போலோ பார்மசி பக்கத்துல"
TANGLISH = "Murugan temple எதிரே, Apollo pharmacy பக்கத்துல, green colour building"


def test_first_real_sentence_replaces_the_starting_guess():
    state = LangState("ta-IN", "profile")
    verdict = update(state, prisma_lang="kn-IN", evon_lang="kn-IN", transcript=KANNADA, typed=False)
    assert verdict.switched and state.code == "kn-IN" and state.confirmed and state.source == "detected"


def test_short_replies_never_switch():
    state = LangState("ta-IN", "profile")
    verdict = update(state, prisma_lang="kn-IN", evon_lang="kn-IN", transcript="ಹೌದು", typed=False)
    assert not verdict.switched and state.code == "ta-IN" and not state.confirmed


def test_a_confirmed_language_needs_two_turns_in_a_row_to_switch():
    state = LangState("ta-IN", "profile")
    update(state, prisma_lang="ta-IN", evon_lang="ta-IN", transcript=TAMIL, typed=False)
    assert state.confirmed
    once = update(state, prisma_lang="kn-IN", evon_lang="kn-IN", transcript=KANNADA, typed=False)
    assert not once.switched and state.code == "ta-IN" and state.candidate == "kn-IN"
    update(state, prisma_lang="ta-IN", evon_lang="ta-IN", transcript=TAMIL, typed=False)
    assert state.candidate is None  # back to Tamil: the count starts again
    update(state, prisma_lang="kn-IN", evon_lang="kn-IN", transcript=KANNADA, typed=False)
    twice = update(state, prisma_lang="kn-IN", evon_lang="kn-IN", transcript=KANNADA, typed=False)
    assert twice.switched and state.code == "kn-IN"


def test_disagreement_or_the_wrong_script_is_ignored():
    state = LangState("hi-IN", "profile")
    assert not update(state, prisma_lang="kn-IN", evon_lang="te-IN", transcript=KANNADA, typed=False).switched
    assert not update(state, prisma_lang="ta-IN", evon_lang=None, transcript="मैं पिन पर खड़ा हूँ भैया", typed=False).switched
    assert state.code == "hi-IN"


def test_code_mixed_speech_counts_as_its_indian_language():
    state = LangState("hi-IN", "profile")
    verdict = update(state, prisma_lang="ta-IN", evon_lang="ta-IN", transcript=TANGLISH, typed=False)
    assert verdict.switched and state.code == "ta-IN"


def test_typed_text_relies_on_evons_reading():
    state = LangState("kn-IN", "picked")
    verdict = update(state, prisma_lang=None, evon_lang="ta-IN", transcript=TAMIL, typed=True)
    assert verdict.switched and state.code == "ta-IN"


def test_a_language_set_in_the_control_room_never_switches():
    state = LangState("ta-IN", "picked", auto=False)
    verdict = update(state, prisma_lang="kn-IN", evon_lang="kn-IN", transcript=KANNADA, typed=False)
    assert not verdict.switched and state.code == "ta-IN"
