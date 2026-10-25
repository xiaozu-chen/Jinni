from datetime import date, timedelta

from memory import MemoryStore, Proposal, Rejected

STALE_FACT_DAYS = 365


def review(store: MemoryStore, proposals: list[Proposal]) -> int:
    saved = 0
    total = len(proposals)
    print(f"  Jinni would like to remember {total} thing(s).")
    print("  y = save   n = skip    e = edit first  q = stop reviewing")
    for i, proposal in enumerate(proposals, 1):
        label = "fact" if proposal.kind == "fact" else "session note"
        text = proposal.text
        while True:
            related = store.similar_facts(text) if proposal.kind == "fact" else []
            if related:
                print("  This fact may overlap with saved fact(s):")
                for item in related:
                    print(f"    #{item.id}: {item.text}")
                prompt = "  save both? (y/n/e/q) > "
            else:
                prompt = "  save? (y/n/e/q) > "
            answer = input(f"  [{i}/{total}] {label}: {text}\n{prompt}").strip().lower()
            if answer == "e":
                edited = input("  new text > ").strip()
                if edited:
                    text = edited
                continue
            break
        if answer == "q":
            break
        if answer != "y":
            continue
        try:
            store.add(proposal.kind, text)
            saved += 1
        except Rejected as e:
            print(f"  (not saved: {e})")
    return saved


def review_stale_facts(store: MemoryStore, days: int = STALE_FACT_DAYS) -> int:
    cutoff = date.today() - timedelta(days=max(1, days))
    stale = store.facts_before(cutoff)
    if not stale:
        return 0
    print(f"  {len(stale)} saved fact(s) have not been revisited for {days} days.")
    print("  d = delete   k = keep   q = stop reviewing")
    deleted = 0
    for item in stale:
        answer = input(
            f"  #{item.id} [{item.created}] {item.text}\n  delete this fact? (d/k/q) > "
        ).strip().lower()
        if answer == "q":
            break
        if answer == "d" and store.delete(item.id):
            deleted += 1
    return deleted
