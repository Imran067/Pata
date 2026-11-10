"""Fixed lines Pata speaks without Evon must exist in all ten languages, in the right script."""
from app import languages, phrases
from app.pipeline import MORE_LANDMARK


def test_fixed_lines_exist_in_every_language_in_the_right_script():
    for code in languages.LANGUAGES:
        assert languages.script_ok(phrases.disclosure(code), code), code
        assert languages.script_ok(MORE_LANDMARK[code], code), code


def test_pin_fix_question_exists_in_every_language():
    for code in languages.LANGUAGES:
        assert languages.script_ok(phrases.pin_fix(code), code), code
