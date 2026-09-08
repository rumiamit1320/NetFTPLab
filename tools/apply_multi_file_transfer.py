from pathlib import Path

MAIN = Path("app/src/main/java/com/netftplab/MainActivity.kt")


def main():
    s = MAIN.read_text(encoding="utf-8")

    # Kotlin's break cannot be used as the initializer of a val. Normalize the
    # queue loops to test emptiness, then remove the first item.
    s = s.replace(
        "val uri = uploadQueue.removeFirstOrNull() ?: break",
        "if (uploadQueue.isEmpty()) break\n                val uri = uploadQueue.removeFirst()",
    )
    s = s.replace(
        "val entry = downloadQueue.removeFirstOrNull() ?: break",
        "if (downloadQueue.isEmpty()) break\n                val entry = downloadQueue.removeFirst()",
    )
    s = s.replace(
        "val uri = if (uploadQueue.isEmpty()) break\n                uploadQueue.removeFirst()",
        "if (uploadQueue.isEmpty()) break\n                val uri = uploadQueue.removeFirst()",
    )
    s = s.replace(
        "val entry = if (downloadQueue.isEmpty()) break\n                downloadQueue.removeFirst()",
        "if (downloadQueue.isEmpty()) break\n                val entry = downloadQueue.removeFirst()",
    )

    # The existing download worker is a suspend function, so its complete-cache
    # path exits the worker directly.
    s = s.replace("                    return@downloadNow\n", "                    return\n")
    s = s.replace("                    return@launch\n", "                    return\n")

    MAIN.write_text(s, encoding="utf-8")
    print("Fixed Kotlin queue loops and suspend-worker return")


if __name__ == "__main__":
    main()
