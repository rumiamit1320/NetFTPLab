from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main() -> None:
    s = MAIN.read_text(encoding="utf-8")
    s = s.replace('${BuildConfig.APPLICATION_ID}.fileprovider', '${packageName}.fileprovider')
    while '        transferRefreshJob?.cancel()\n        transferRefreshJob?.cancel()\n' in s:
        s = s.replace('        transferRefreshJob?.cancel()\n        transferRefreshJob?.cancel()\n', '        transferRefreshJob?.cancel()\n', 1)
    MAIN.write_text(s, encoding="utf-8")
    print("Cleaned FileProvider authority and duplicate refresh cancellation")


if __name__ == "__main__":
    main()
