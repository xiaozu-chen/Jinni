# ATTENTION CODEX: Update the 'commit_message' variable below with a brief,
# accurate summary of the changes you just made before running this script.

import subprocess


def auto_commit(commit_message="Automated update from Codex"):
  try:
    # Stage all changes
    subprocess.run(["git", "add", "-A"], check=True)

    # Commit with the updated message
    subprocess.run(["git", "commit", "-m", commit_message], check=True)
    print(f"Successfully committed: '{commit_message}'")
  except subprocess.CalledProcessError as e:
    print(f"Git operation failed: {e}")


if __name__ == "__main__":
  # Codex can edit the message here dynamically
  auto_commit("Update files with recent changes")