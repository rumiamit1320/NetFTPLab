from pathlib import Path

P = Path("tools/apply_transfer_reliability.py")


def main() -> None:
    s = P.read_text(encoding="utf-8")
    marker = "    s = replace_function(s, '    private fun publishToDownloads(', '    private fun verifyRemote(', publish_body)"
    replacement = "    s = s.replace('    private fun verifyRemote(', publish_body + '    private fun verifyRemote(', 1)"
    if marker in s:
        s = s.replace(marker, replacement, 1)
        P.write_text(s, encoding="utf-8")
        print("Prepared transfer reliability patch for builds where the publisher is absent")
    elif "publish_body + '    private fun verifyRemote('" in s:
        print("Transfer reliability publisher preparation already applied")
    else:
        raise SystemExit("Reliability publisher patch marker not found")


if __name__ == "__main__":
    main()
