# NetFTP Lab 2.0

NetFTP Lab is an Android LAN FTP/network laboratory for learning FTP, TCP data/control channels, device discovery, file transfer and basic MAC/TCP models.

## Features

- Active IPv4 /24 device discovery
- FTP client with persistent control connection
- EPSV with PASV fallback
- LIST/NLST, RETR, STOR, SIZE, REST and DELE
- Upload/download progress and throughput
- SHA-256 verification with the NetFTP Lab server
- Embedded multi-client FTP server on TCP 2121
- Fixed passive data range 21210-21250
- Protocol console showing TCP/FTP/DATA events
- Connection QR code
- Pure ALOHA, Slotted ALOHA and CSMA/CA educational models
- Modeled TCP Reno/CUBIC/BBR congestion-window traces
- Material 3 interface

## Android project

- Minimum API: 26
- Target/compile SDK: 35
- Kotlin: 2.0.21
- Android Gradle Plugin: 8.6.1
- Compose Material 3

## Important limitation

The MAC and congestion-control plots are educational models. An ordinary Android application cannot directly expose every Wi-Fi MAC collision or the kernel TCP congestion window.

The embedded server is anonymous FTP intended for a trusted LAN laboratory and should not be exposed to the public Internet.

## Build

Open the repository in Android Studio, sync Gradle, and build the debug APK. GitHub Actions is configured to build `:app:assembleDebug` on pushes and pull requests to `main`.
