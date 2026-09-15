from __future__ import annotations

from itertools import pairwise

import pytest

from watcher.services.pagination import normalize_page, page_sequence

LARGE_TOTALS = (8, 9, 11, 20, 50, 100)


class TestPageSequence:
    def test_zero_pages_returns_empty_sequence(self) -> None:
        assert page_sequence(1, 0) == []

    def test_single_page(self) -> None:
        assert page_sequence(1, 1) == [1]

    @pytest.mark.parametrize("total", range(1, 8))
    def test_up_to_seven_pages_shows_all_of_them(self, total: int) -> None:
        for current in range(1, total + 1):
            assert page_sequence(current, total) == list(range(1, total + 1))

    def test_more_than_seven_pages_uses_ellipsis(self) -> None:
        assert "…" in page_sequence(1, 8)

    # Worked example for an 11 page listing:
    # page 1-4: 1 2 3 4 5 6 … 11
    # page 5: 1 … 3 4 5 6 7 … 11
    # page 6: 1 … 4 5 6 7 8 … 11
    # page 7: 1 … 5 6 7 8 9 … 11
    # page 8-11: 1 … 6 7 8 9 10 11

    def test_beginning(self) -> None:
        assert page_sequence(1, 11) == [1, 2, 3, 4, 5, 6, "…", 11]

    def test_page_two(self) -> None:
        assert page_sequence(2, 11) == [1, 2, 3, 4, 5, 6, "…", 11]

    def test_page_three(self) -> None:
        assert page_sequence(3, 11) == [1, 2, 3, 4, 5, 6, "…", 11]

    def test_transition_into_the_middle(self) -> None:
        assert page_sequence(4, 11) == [1, 2, 3, 4, 5, 6, "…", 11]
        assert page_sequence(5, 11) == [1, "…", 3, 4, 5, 6, 7, "…", 11]

    def test_center(self) -> None:
        assert page_sequence(6, 11) == [1, "…", 4, 5, 6, 7, 8, "…", 11]

    def test_transition_into_the_end(self) -> None:
        assert page_sequence(7, 11) == [1, "…", 5, 6, 7, 8, 9, "…", 11]
        assert page_sequence(8, 11) == [1, "…", 6, 7, 8, 9, 10, 11]

    def test_penultimate(self) -> None:
        assert page_sequence(10, 11) == [1, "…", 6, 7, 8, 9, 10, 11]

    def test_last(self) -> None:
        assert page_sequence(11, 11) == [1, "…", 6, 7, 8, 9, 10, 11]

    def test_large_total_twenty_pages(self) -> None:
        assert page_sequence(1, 20) == [1, 2, 3, 4, 5, 6, "…", 20]
        assert page_sequence(10, 20) == [1, "…", 8, 9, 10, 11, 12, "…", 20]
        assert page_sequence(19, 20) == [1, "…", 15, 16, 17, 18, 19, 20]
        assert page_sequence(20, 20) == [1, "…", 15, 16, 17, 18, 19, 20]

    def test_large_total_fifty_pages(self) -> None:
        assert page_sequence(1, 50) == [1, 2, 3, 4, 5, 6, "…", 50]
        assert page_sequence(25, 50) == [1, "…", 23, 24, 25, 26, 27, "…", 50]
        assert page_sequence(49, 50) == [1, "…", 45, 46, 47, 48, 49, 50]
        assert page_sequence(50, 50) == [1, "…", 45, 46, 47, 48, 49, 50]

    def test_large_total_one_hundred_pages(self) -> None:
        assert page_sequence(1, 100) == [1, 2, 3, 4, 5, 6, "…", 100]
        assert page_sequence(50, 100) == [1, "…", 48, 49, 50, 51, 52, "…", 100]
        assert page_sequence(99, 100) == [1, "…", 95, 96, 97, 98, 99, 100]
        assert page_sequence(100, 100) == [1, "…", 95, 96, 97, 98, 99, 100]

    def test_current_page_beyond_total_is_clamped(self) -> None:
        assert page_sequence(999, 20) == page_sequence(20, 20)

    def test_current_page_below_one_is_clamped(self) -> None:
        assert page_sequence(0, 20) == page_sequence(1, 20)

    def test_no_ellipsis_between_truly_adjacent_numbers(self) -> None:
        for total in LARGE_TOTALS:
            for current in range(1, total + 1):
                sequence = page_sequence(current, total)
                for previous, entry in pairwise(sequence):
                    if isinstance(previous, int) and isinstance(entry, int):
                        assert entry - previous == 1, (total, current)

    def test_ellipsis_always_represents_at_least_one_hidden_page(self) -> None:
        for total in LARGE_TOTALS:
            for current in range(1, total + 1):
                sequence = page_sequence(current, total)
                for index, entry in enumerate(sequence):
                    if entry == "…":
                        before = sequence[index - 1]
                        after = sequence[index + 1]
                        assert isinstance(before, int)
                        assert isinstance(after, int)
                        assert after - before > 1, (total, current)

    def test_current_page_is_always_present(self) -> None:
        for total in (8, 11, 20, 50, 100):
            for current in range(1, total + 1):
                assert current in page_sequence(current, total)

    def test_first_and_last_page_always_present(self) -> None:
        for total in (8, 11, 20, 50, 100):
            for current in range(1, total + 1):
                sequence = page_sequence(current, total)
                assert 1 in sequence
                assert total in sequence


class TestNormalizePage:
    def test_missing_page_defaults_to_one(self) -> None:
        assert normalize_page(None, 5) == 1

    def test_non_numeric_page_defaults_to_one(self) -> None:
        assert normalize_page("abc", 5) == 1

    def test_zero_page_defaults_to_one(self) -> None:
        assert normalize_page("0", 5) == 1

    def test_negative_page_defaults_to_one(self) -> None:
        assert normalize_page("-3", 5) == 1

    def test_page_beyond_total_clamps_to_last_page(self) -> None:
        assert normalize_page("999", 5) == 5

    def test_valid_page_passes_through(self) -> None:
        assert normalize_page("3", 5) == 3

    def test_zero_total_pages_always_normalizes_to_one(self) -> None:
        assert normalize_page("1", 0) == 1
        assert normalize_page("5", 0) == 1
        assert normalize_page(None, 0) == 1
