from veyntora_api.rag import grounding
from veyntora_api.rag.pipeline import language_of

SOURCES = [
    "Digital products can't be refunded once they have been downloaded by the customer.",
    "Physical products can be returned within 30 days if the customer has the receipt.",
]


def test_cited_and_supported_answer_is_grounded() -> None:
    g = grounding.check(
        "Digital products cannot be refunded after the customer downloaded them [1]. "
        "Physical products can be returned within 30 days with a receipt [2].",
        SOURCES,
    )
    assert g.score == 1.0 and g.cited == (1, 2) and g.invalid == ()


def test_citing_the_wrong_source_is_not_support() -> None:
    g = grounding.check(
        "Physical products can be returned within 30 days with receipt [1].", SOURCES
    )
    assert g.score == 0.0 and g.cited == (1,)


def test_uncited_and_invented_citations() -> None:
    assert grounding.check("Refunds are always possible within one year.", SOURCES).score == 0.0
    g = grounding.check("Digital products can't be refunded once downloaded [3].", SOURCES)
    assert g.invalid == (3,) and g.cited == ()


def test_inflection_is_tolerated_in_german() -> None:
    g = grounding.check(
        "Rückerstattungen für digitale Produkte sind nach dem Download ausgeschlossen [1].",
        ["Eine Rückerstattung digitaler Produkte ist nach dem Download ausgeschlossen."],
    )
    assert g.score == 1.0


def test_short_lines_do_not_count() -> None:
    g = grounding.check("Sure!\nDigital products can't be refunded once downloaded [1].", SOURCES)
    assert g.sentences == 1 and g.supported == 1


def test_no_answer_sentinel_and_language() -> None:
    assert grounding.is_no_answer("NO_ANSWER")
    assert grounding.is_no_answer(" no_answer. ")
    assert not grounding.is_no_answer("The answer is no.")
    assert language_of("Wie kann ich das Passwort ändern?") == "de"
    assert language_of("How do I reset my password?") == "en"


def test_abbreviations_and_numbers_do_not_end_a_sentence() -> None:
    text = (
        "Die Anmeldung geht über BundID bzw. das Unternehmenskonto online [1]. "
        "Seit dem 15.07. 2017 gilt z. B. die Online-Ausweisfunktion [2].\n"
        "Termin am 1. Januar [1]."
    )
    assert grounding.split_sentences(text) == [
        "Die Anmeldung geht über BundID bzw. das Unternehmenskonto online [1].",
        "Seit dem 15.07. 2017 gilt z. B. die Online-Ausweisfunktion [2].",
        "Termin am 1. Januar [1].",
    ]
    source = "Die Anmeldung geht über BundID bzw. das Unternehmenskonto auch online."
    # Split at "bzw.", the second half had no citation and counted as unsupported.
    first = "Die Anmeldung geht über BundID bzw. das Unternehmenskonto online [1]."
    assert grounding.check(first, [source]).score == 1.0
