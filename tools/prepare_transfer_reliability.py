from pathlib import Path
import re

P = Path("tools/apply_transfer_reliability.py")


def main() -> None:
    s = P.read_text(encoding="utf-8")
    old = "    s = replace_function(s, '    private fun publishToDownloads(', '    private fun verifyRemote(', publish_body)"
    new = '''    if "private fun publishToDownloads(" in s:
        s = replace_function(s, '    private fun publishToDownloads(', '    private fun verifyRemote(', publish_body)
    else:
        s = s.replace(
            "    s = replace_function(s, '    private fun publishToDownloads(', '    private fun verifyRemote(', publish_body)",
            "    s = s.replace('    private fun verifyRemote(', publish_body + '    private fun verifyRemote(', 1)",
            1,
        )
    if old not in s and new not in s:
        raise SystemExit("Reliability publisher patch marker not found")
    P.write_text(s, encoding="utf-8")
    print("Prepared transfer reliability patch for builds where the publisher is absent")


if __name__ == "__main__":
    main()
