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
            related = store.similar_facts(text) if proposals.kind == "fact" else []
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
            store.add(proposals.kind, text)
            saved += 1
        except Rejected as e:
            print(f"  (not saved: {e})")
    return saved
