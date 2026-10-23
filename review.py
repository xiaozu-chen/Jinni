from memory import MemoryStore, Proposal, Rejected


def review(store: MemoryStore, proposals: list[Proposal]) -> int:
    saved = 0
    total = len(proposals)
    print(f"  Jinni would like to remember {total} thing(s).")
    print("  y = save   n = skip    e = edit first  q = stop reviewing")
    for i, proposals in enumerate(proposals, 1):
        label = "fact" if proposals.kind == "fact" else "session note"
        text = proposals.text
        while True:
            answer = input(f"  [{i}/{total}] {label}: {text}\n  save? (y/n/e/q) > ").strip().lower()
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
            store.add(proposals.kind, text)
            saved += 1
        except Rejected as e:
            print(f"  (not saved: {e})")
    return saved