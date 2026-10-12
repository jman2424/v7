"""Unicode customer messages must not be mistaken for symbol-only input."""
import pytest

from service.message_handler import MessageHandler, _looks_like_noise


@pytest.mark.parametrize("message", [
    "ما هي ساعات العمل؟", "مرحبا", "نعم", "sí", "ça", "¿Cuál es el precio?",
    "Quel est le prix ?", "你好", "はい",
])
def test_multilingual_letters_reach_the_business_handler(message):
    assert MessageHandler._guard_input(None, message, sess={}) is None
    assert not _looks_like_noise(message)


@pytest.mark.parametrize("message", ["!!!", "???", "🙂", "— • …"])
def test_symbols_still_need_clarification(message):
    assert MessageHandler._guard_input(None, message, sess={})["facts"]["reason"] == "symbols_only"


@pytest.mark.parametrize("message", ["x", "zq"])
def test_existing_ascii_noise_guard_remains(message):
    assert MessageHandler._guard_input(None, message, sess={})["facts"]["reason"] == "nonsense_input"


def test_valid_postcodes_and_empty_input_keep_existing_paths():
    assert MessageHandler._guard_input(None, "SW1A 1AA", sess={}) is None
    assert MessageHandler._guard_input(None, "", sess={})["intent"] == "system_empty"
