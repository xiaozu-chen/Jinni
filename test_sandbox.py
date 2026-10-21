from tools import safe_path

tests = [
    "notes/poem.txt",
    "notes/../mm.txt",
    "../jinni.py",
    "notes/../../jinni.py",
    "..\\jinni.py",
    "C:/Windows/win.ini",
]

for t in tests:
    try:
        print("OK     ", t, "->", safe_path(t))
    except ValueError as e:
        print("BLOCKED", t, "->", e)