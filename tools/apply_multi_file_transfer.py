from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")

def main():
    s = MAIN.read_text(encoding="utf-8")
    s = s.replace("uploadQueue.removeFirstOrNull() ?: break", "if (uploadQueue.isEmpty()) break\n                uploadQueue.removeFirst()")
    s = s.replace("downloadQueue.removeFirstOrNull() ?: break", "if (downloadQueue.isEmpty()) break\n                downloadQueue.removeFirst()")
    # The existing download worker is a suspend function. Its complete-cache path
    # must exit the worker, not an inline lambda, so use return@downloadNow.
    s = s.replace("                    return@launch\n", "                    return@downloadNow\n")
    MAIN.write_text(s, encoding="utf-8")
    print("Fixed queue compatibility and suspend-worker return")

if __name__ == "__main__":
    main()
