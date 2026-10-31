from veyntora_api.knowledge.vocabulary import candidates, split, words

COUNTS = {
    "rückerstattung": 12,
    "richtlinie": 30,
    "reise": 8,
    "kosten": 20,
    "kostenstelle": 3,
    "stelle": 9,
    "lini": 1,
}


def freq(term: str) -> int:
    return COUNTS.get(term, 0)


def test_compounds_split_into_known_parts_with_linking_letters() -> None:
    assert split("rückerstattungsrichtlinie", freq) == ["rückerstattung", "richtlinie"]
    assert split("reisekostenrichtlinie", freq) == ["reise", "kosten", "richtlinie"]


def test_a_word_is_kept_when_splitting_does_not_score_higher() -> None:
    assert split("richtlinie", freq) == [], "no split beats a frequent whole word"
    assert split("donaudampfschiff", freq) == [], "unknown parts are never invented"


def test_candidates_cover_every_part_a_split_can_use() -> None:
    found = candidates("rückerstattungsrichtlinie")
    assert {"rückerstattung", "rückerstattungs", "richtlinie"} <= found
    assert all(len(c) >= 3 for c in found)


def test_words_are_lower_case_letters_only() -> None:
    assert words("Die Rückerstattung (§ 4.2) gilt ab 2026!") == {"rückerstattung", "gilt"}
