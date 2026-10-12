"""Tests for the deterministic safety classifier and default-list logic (T009)."""

import unittest

from src.skills.safety import (
    DEFAULT_LIST_LIMIT,
    classify,
    default_view,
    tag_candidate,
    tag_candidates,
)


class ClassifyTests(unittest.TestCase):
    def test_school_shooting_tags_violence_crime_and_minors(self) -> None:
        self.assertEqual(
            classify("School shooting leaves two injured"),
            ["violence", "crime_against_individual", "minors"],
        )

    def test_death(self) -> None:
        self.assertEqual(classify("Beloved teacher dies at 90"), ["death"])

    def test_disaster_casualties(self) -> None:
        self.assertEqual(
            classify("Earthquake collapses buildings, dozens rescued"),
            ["disaster_casualties"],
        )

    def test_minors_only(self) -> None:
        self.assertEqual(classify("Students launch recycling program"), ["minors"])

    def test_crime_and_violence(self) -> None:
        self.assertEqual(
            classify("Police arrest suspect in armed robbery"),
            ["violence", "crime_against_individual"],
        )

    def test_phrase_match(self) -> None:
        self.assertEqual(
            classify("Man charged with sexual assault"),
            ["violence", "crime_against_individual"],
        )

    def test_multi_tag_fire(self) -> None:
        self.assertEqual(
            classify("Three killed in apartment fire"),
            ["violence", "death", "disaster_casualties"],
        )

    def test_benign_story_is_untagged(self) -> None:
        self.assertEqual(classify("National team wins championship title"), [])

    def test_case_insensitive(self) -> None:
        self.assertEqual(classify("DEATH TOLL RISES"), ["death"])

    def test_word_boundary_avoids_substring_false_positive(self) -> None:
        # "gun" must not match "gundam"; "war" must not match "warning".
        self.assertEqual(classify("Gundam warning system upgraded"), [])


class TagTests(unittest.TestCase):
    def test_tag_candidate_fills_fields_and_preserves_keys(self) -> None:
        candidate = {
            "candidate_id": "c-1",
            "title": "Two killed in attack",
            "url": "https://x/1",
            "publisher": "BBC",
            "published_at": "2026-10-12T00:00:00+00:00",
            "description": "",
            "source": "rss",
            "cluster_id": "cl-0",
        }
        tagged = tag_candidate(candidate)
        self.assertEqual(tagged["safety_tags"], ["violence", "death"])
        self.assertIs(tagged["hidden_by_safety"], True)
        # Original keys survive untouched.
        self.assertEqual(tagged["candidate_id"], "c-1")
        self.assertEqual(tagged["cluster_id"], "cl-0")
        # The input candidate is not mutated; tagging returns a fresh copy.
        self.assertNotIn("safety_tags", candidate)

    def test_untagged_candidate_stays_visible(self) -> None:
        tagged = tag_candidate({"candidate_id": "c-2", "title": "Markets close higher", "url": "https://x/2"})
        self.assertEqual(tagged["safety_tags"], [])
        self.assertIs(tagged["hidden_by_safety"], False)

    def test_tag_candidates_preserves_order(self) -> None:
        candidates = [
            {"candidate_id": "c-1", "title": "Two killed in attack", "url": "https://x/1"},
            {"candidate_id": "c-2", "title": "Markets close higher", "url": "https://x/2"},
        ]
        tagged = tag_candidates(candidates)
        self.assertEqual([c["candidate_id"] for c in tagged], ["c-1", "c-2"])
        self.assertIs(tagged[0]["hidden_by_safety"], True)
        self.assertIs(tagged[1]["hidden_by_safety"], False)


def _candidate(candidate_id: str, title: str) -> dict:
    return {"candidate_id": candidate_id, "title": title, "url": f"https://x/{candidate_id}"}


class DefaultViewTests(unittest.TestCase):
    def test_top_15_untagged_and_hidden_count(self) -> None:
        candidates = tag_candidates(
            [_candidate(f"c-{i}", f"Local team wins match {i}") for i in range(17)]
            + [_candidate(f"c-h-{i}", f"Two killed in attack {i}") for i in range(3)]
        )
        view = default_view(candidates)
        self.assertEqual(len(view["visible"]), DEFAULT_LIST_LIMIT)
        self.assertEqual(view["visible"][0]["candidate_id"], "c-0")
        self.assertEqual(view["visible"][-1]["candidate_id"], "c-14")
        self.assertEqual(view["hidden_count"], 3)
        self.assertIs(view["fewer_than_8"], False)
        self.assertEqual(view["message"], "")

    def test_fewer_than_8_flag_and_message(self) -> None:
        candidates = tag_candidates(
            [_candidate(f"c-h-{i}", f"Two killed in attack {i}") for i in range(8)]
            + [_candidate("c-ok-0", "Local team wins match"), _candidate("c-ok-1", "Markets close higher")]
        )
        view = default_view(candidates)
        self.assertEqual(len(view["visible"]), 2)
        self.assertEqual(view["hidden_count"], 8)
        self.assertIs(view["fewer_than_8"], True)
        self.assertIn("Fewer than 8", view["message"])


if __name__ == "__main__":
    unittest.main()
