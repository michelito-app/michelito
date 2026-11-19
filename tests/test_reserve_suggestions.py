"""Reserve suggestions (pure logic of `analysis.reserve_suggestions`): yearly recurring charges,
irregular categories and repeated peaks, over a made-up, noisy history."""

from datetime import date
from decimal import Decimal as D

from michelito.analysis import categories as cat
from michelito.analysis import reserve_suggestions as suggest
from michelito.analysis import reserves
from michelito.analysis.reserve_suggestions import Category, RecurringSource
from michelito.analysis.reserves import Reserve

FUN, TRAVEL, TAX = 1, 2, 3
CURRENT = "2026-02"


def _months(first: str, count: int) -> list[str]:
    start = reserves.month_index(first)
    return [reserves.month_at(start + i) for i in range(count)]


COMPLETE = _months("2023-01", 36)  # all of 2023, 2024 and 2025


def test_suggestion_from_an_active_yearly_recurring() -> None:
    source = RecurringSource(
        "recurring:MARBETE:DOP", "MARBETE", TAX, D("3412.50"), date(2026, 1, 20)
    )
    [found] = suggest.from_recurring([source], CURRENT)
    assert (found.name, found.amount, found.due_month, found.every_months, found.multiple) == (
        "MARBETE",
        D(3_500),  # rounded up to RD$ 100
        "2027-01",  # next January
        12,
        False,
    )


def _noisy_history() -> tuple[dict[int, dict[str, D]], list[Category]]:
    """Eight irregular categories that spend in months that change from one year to the next (as
    in a real database), travel (irregular but heavy), entertainment (every month, with a
    Christmas peak) and groceries (every month, no peaks)."""
    regular: dict[int, dict[str, D]] = {}
    categories = [
        Category(FUN, cat.ENTERTAINMENT, "ent"),
        Category(TRAVEL, cat.TRAVEL, "travel"),
    ]
    # Noise: each category spends in 3 to 5 different months a year, small or medium amounts.
    for index in range(8):
        cid = 10 + index
        categories.append(Category(cid, f"Irregular {index}", f"irr{index}"))
        by_month: dict[str, D] = {}
        for year in ("2023", "2024", "2025"):
            for slot in range(3 + index % 3):
                number = (index * 5 + slot * 3 + int(year)) % 12 + 1
                by_month[f"{year}-{number:02d}"] = D(1_500 + 700 * index + 300 * slot)
        regular[cid] = by_month
    regular[TRAVEL] = {"2023-07": D(70_000), "2024-08": D(55_000), "2025-07": D(85_000)}
    fun = {m: D(3_000) for m in COMPLETE}
    for year in ("2023", "2024", "2025"):
        fun[f"{year}-12"] = D(18_000)
    regular[FUN] = fun
    categories.append(Category(99, cat.GROCERIES, "super"))
    regular[99] = {m: D(12_000 + (i % 4) * 900) for i, m in enumerate(COMPLETE)}
    return regular, categories


def test_noisy_history_gives_few_suggestions_and_christmas_is_one() -> None:
    regular, categories = _noisy_history()
    found = suggest.from_history(regular, COMPLETE, categories, CURRENT)
    pending = suggest.pending_suggestions(found, [], set())
    names = [s.name for s in pending]
    # First the peak repeated all 3 years; then by amount.
    assert names == [f"Diciembre: {cat.ENTERTAINMENT}", cat.TRAVEL]  # spanish-ui
    christmas, travel = pending
    assert (travel.key, travel.amount, travel.due_month, travel.every_months) == (
        "irregular:travel",
        D(70_000),  # the average of 70, 55 and 85 thousand
        "2026-07",  # the month with the most spending in the window
        12,
    )
    assert "≈ RD$ 70,000/año" in travel.reason  # spanish-ui
    assert (christmas.key, christmas.amount, christmas.due_month, christmas.multiple) == (
        "peak:ent:12",
        D(15_000),  # the last year's excess over the median (18,000 - 3,000)
        "2026-12",
        True,
    )


def test_a_single_year_peak_suggests_nothing() -> None:
    complete = _months("2025-01", 12)
    fun = {m: D(3_000) for m in complete}
    fun["2025-12"] = D(30_000)
    found = suggest.from_history({FUN: fun}, complete, [Category(FUN, "Ent", "ent")], CURRENT)
    assert found == []


def test_peak_needs_10000_over_the_median_and_skips_one_offs() -> None:
    small = {m: D(3_000) for m in COMPLETE}
    for year in ("2023", "2024", "2025"):
        small[f"{year}-12"] = D(9_000)  # three times as much, but only RD$ 6,000 above
    found = suggest.from_history({FUN: small}, COMPLETE, [Category(FUN, "Ent", "ent")], CURRENT)
    assert found == []
    # What is passed as `regular` already excludes one-offs: a trip marked one-off does not count.


def test_an_irregular_category_with_little_money_is_not_suggested() -> None:
    light = {"2023-03": D(4_000), "2024-05": D(6_000), "2025-02": D(5_000)}
    cats = [Category(TRAVEL, cat.TRAVEL, "travel")]
    assert suggest.from_history({TRAVEL: light}, COMPLETE, cats, CURRENT) == []


def test_at_most_one_per_category_and_at_most_eight() -> None:
    def item(key: str, category: int, amount: int) -> suggest.Suggestion:
        return suggest.Suggestion(key, key, D(amount), category, "2026-12", 12, True, "")

    first, second = item("recurring:a", FUN, 5_000), item("peak:b:12", FUN, 9_000)
    assert suggest.pending_suggestions([first, second], [], set()) == [first]
    many = [item(f"peak:{i}:12", 100 + i, 1_000 * i) for i in range(1, 12)]
    found = suggest.pending_suggestions(many, [], set())
    assert len(found) == suggest.MAX_SUGGESTIONS
    assert [s.amount for s in found] == sorted((s.amount for s in found), reverse=True)


def test_pending_suggestions_skip_dismissed_and_created() -> None:
    found = suggest.Suggestion("peak:ent:12", "Navidad", D(15_000), FUN, "2026-12", 12, True, "")
    assert suggest.pending_suggestions([found], [], set()) == [found]
    assert suggest.pending_suggestions([found], [], {found.key}) == []
    created = Reserve(1, "Navidad", D(15_000), FUN, "2026-12", 12, source=found.key)
    assert suggest.pending_suggestions([found], [created], set()) == []
    # Any reserve of that category also covers it (one per category).
    other = Reserve(2, "Cine", D(5_000), FUN, "2026-06", None)
    assert suggest.pending_suggestions([found], [other], set()) == []


def test_christmas_every_year_comes_first_over_bigger_but_less_consistent_ones() -> None:
    def item(key: str, category: int, amount: int, repeats: int) -> suggest.Suggestion:
        return suggest.Suggestion(key, key, D(amount), category, "2026-12", 12, True, "", repeats)

    bigger = [item(f"peak:{i}:0{i % 9 + 1}", 100 + i, 50_000 + i, 2) for i in range(8)]
    christmas = item("peak:ent:12", FUN, 15_000, 3)
    found = suggest.pending_suggestions([*bigger, christmas], [], set())
    assert len(found) == suggest.MAX_SUGGESTIONS
    assert found[0] == christmas
    # And from the history: a peak of all 3 years comes with `repeats` = 3.
    regular, categories = _noisy_history()
    [peak] = [
        s
        for s in suggest.from_history(regular, COMPLETE, categories, CURRENT)
        if s.key.startswith("peak")
    ]
    assert peak.repeats == 3


def test_excluded_categories_by_ref_group_and_monthly_recurring_share() -> None:
    loans, cash, insurance, food = (
        Category(20, cat.LOANS, cat.LOANS),
        Category(21, cat.CASH, cat.CASH),
        Category(22, "Seguro del carro", "user:22"),  # spanish-data
        Category(23, cat.RESTAURANTS, cat.RESTAURANTS),
    )
    regular = {
        22: {m: D(4_000) for m in COMPLETE},  # mostly a monthly policy
        23: {m: D(5_000) for m in COMPLETE},
    }
    monthly = {
        22: {m: D(3_000) for m in COMPLETE},  # 75 % monthly recurring charges
        23: {m: D(1_000) for m in COMPLETE},  # 20 %: no
    }
    groups = {20: "loans", 21: "other", 22: "insurance", 23: "other"}
    found = suggest.excluded_categories(
        [loans, cash, insurance, food], regular, monthly, COMPLETE, groups
    )
    assert found == {20, 21, 22}
    # Excluded, they show neither as irregular nor as a peak (new loans, a December cash peak).
    history = {
        20: {f"2025-{n:02d}": D(12_000) for n in range(7, 13)},
        21: {
            **{m: D(2_000) for m in COMPLETE},
            **{f"{y}-12": D(30_000) for y in ("2023", "2024", "2025")},
        },
    }
    cats = [loans, cash]
    assert suggest.from_history(history, COMPLETE, cats, CURRENT, found) == []
    assert (
        suggest.from_history(history, COMPLETE, cats, CURRENT) != []
    )  # without excluding, they do


def test_an_irregular_category_needs_spending_in_two_of_the_last_three_years() -> None:
    new = {"2025-03": D(60_000), "2025-08": D(70_000)}  # only in 2025: a new category
    cats = [Category(TRAVEL, cat.TRAVEL, "travel")]
    assert suggest.from_history({TRAVEL: new}, COMPLETE, cats, CURRENT) == []
    twice = {**new, "2024-07": D(80_000)}
    [found] = suggest.from_history({TRAVEL: twice}, COMPLETE, cats, CURRENT)
    assert found.key == "irregular:travel"
