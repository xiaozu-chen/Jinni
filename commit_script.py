import subprocess
import sys


def auto_commit(commit_message: str = "Automated update from Codex") -> int:
  try:
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", commit_message], check=True)
    print(f"Successfully committed: '{commit_message}'")
    return 0
  except subprocess.CalledProcessError as e:
    print(f"Git operation failed: {e}")
    return e.returncode or 1


if __name__ == "__main__":
  sys.exit(auto_commit("Update files with recent changes"))
