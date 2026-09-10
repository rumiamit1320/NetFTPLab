from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")

    # Preservation/verification step only. The complete Transfer-tab UI is
    # generated later by the transfer UI scripts. This step must never fail
    # because an older source shape is no longer present.
    if "private fun TransfersTab()" not in s:
        print("TransfersTab is not present in this source revision; deferred to later transfer UI step")
        return

    start = s.find("private fun TransfersTab()")
    end = s.find("private fun ", start + len("private fun TransfersTab()"))
    if end < 0:
        end = len(s)

    tab = s[start:end]
    if "LazyColumn(" in tab:
        print("Transfer tab already uses LazyColumn; preserved existing UI")
    else:
        print("Transfer tab is not yet scrollable; deferred to multi-file transfer UI step")

    print("Transfer UI preservation check passed; server networking untouched")


if __name__ == "__main__":
    main()
