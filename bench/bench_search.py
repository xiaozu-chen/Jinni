import time

from ddgs import DDGS

QUERY = "mediterranean diet benefits"

for backend in ["auto", "duckduckgo", "bing", "brave", "google", "mojeek"]:
    start = time.perf_counter()
    try:
        results = DDGS(timeout=10).text(QUERY, max_results=5, backend=backend)
        outcome = f"{len(results)} results"
    except Exception as e:
        outcome = f"FAILED ({type(e).__name__})"
    print(f"{backend:12} {time.perf_counter() - start:5.1f}s {outcome}")