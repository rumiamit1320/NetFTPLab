package com.netftplab

import java.io.*
import java.net.*
import java.nio.charset.StandardCharsets

class FtpClient(
    private val host: String,
    private val port: Int,
    private val logger: (String, String) -> Unit
) : Closeable {
    private lateinit var control: Socket
    private lateinit var reader: BufferedReader
    private lateinit var writer: BufferedWriter
    private var passivePort = -1
    private var restOffset = 0L

    fun connect() {
        control = Socket()
        val t = System.currentTimeMillis()
        logger("TCP", "SYN → $host:$port")
        control.connect(InetSocketAddress(host, port), 5000)
        control.soTimeout = 30000
        logger("TCP", "Connection established; RTT ≈ ${System.currentTimeMillis() - t} ms")
        reader = control.getInputStream().bufferedReader(StandardCharsets.US_ASCII)
        writer = control.getOutputStream().bufferedWriter(StandardCharsets.US_ASCII)
        logger("FTP", "RX ${readResponse()}")
    }

    fun login(user: String, pass: String) { command("USER $user"); command("PASS $pass") }

    fun enterPassive(): Int {
        val epsv = command("EPSV")
        val ep = Regex("\\(\\|\\|\\|(\\d+)\\|\\)").find(epsv)?.groupValues?.get(1)?.toIntOrNull()
        if (ep != null) { passivePort = ep; logger("FTP", "EPSV selected data port = $passivePort"); return ep }
        val r = command("PASV")
        val nums = Regex("(\\d+),(\\d+),(\\d+),(\\d+),(\\d+),(\\d+)").find(r)?.groupValues
        if (nums != null) {
            passivePort = nums[5].toInt() * 256 + nums[6].toInt()
            logger("FTP", "PASV selected data port = $passivePort")
        } else throw IOException("Server did not return PASV/EPSV")
        return passivePort
    }

    fun list(): String {
        val data = openDataSocket()
        val response = command("LIST")
        if (!response.startsWith("150") && !response.startsWith("125")) { data.close(); throw IOException(response) }
        val bytes = data.getInputStream().readBytes(); data.close(); val final = readResponse(); passivePort = -1
        logger("DATA", "LIST received ${bytes.size} bytes; $final")
        return bytes.toString(StandardCharsets.UTF_8)
    }

    fun remoteSize(path: String): Long { val r = command("SIZE $path"); return r.substringAfter(' ').trim().toLongOrNull() ?: -1L }
    fun remoteSha256(path: String): String { val r = command("XSHA256 $path"); return if (r.startsWith("213 ")) r.substringAfter("213 ").trim() else "" }

    fun download(path: String, output: OutputStream, resumeFrom: Long = 0L, progress: (Long, Long) -> Unit = { _, _ -> }): Long {
        if (resumeFrom > 0) { restOffset = resumeFrom; command("REST $resumeFrom") }
        val total = remoteSize(path)
        val data = openDataSocket(); val r = command("RETR $path")
        if (!r.startsWith("150") && !r.startsWith("125")) { data.close(); throw IOException(r) }
        var done = resumeFrom
        data.getInputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) { val n = input.read(buf); if (n < 0) break; output.write(buf, 0, n); done += n; progress(done, total) }
        }
        data.close(); val end = readResponse(); passivePort = -1; logger("DATA", "RETR complete $done/$total bytes; $end"); restOffset = 0
        return done
    }

    fun upload(path: String, input: InputStream, size: Long, resumeFrom: Long = 0L, progress: (Long, Long) -> Unit = { _, _ -> }): Long {
        if (resumeFrom > 0) { restOffset = resumeFrom; command("REST $resumeFrom") }
        val data = openDataSocket(); val r = command("STOR $path")
        if (!r.startsWith("150") && !r.startsWith("125")) { data.close(); throw IOException(r) }
        var done = resumeFrom
        data.getOutputStream().use { out ->
            val buf = ByteArray(64 * 1024)
            while (true) { val n = input.read(buf); if (n < 0) break; out.write(buf, 0, n); done += n; progress(done, size) }
            out.flush()
        }
        data.close(); val end = readResponse(); passivePort = -1; logger("DATA", "STOR complete $done/$size bytes; $end"); restOffset = 0
        return done
    }

    fun delete(path: String) { command("DELE $path") }
    fun quit() { if (::control.isInitialized && !control.isClosed) { try { command("QUIT") } catch (_: Exception) {}; close() } }
    override fun close() { try { control.close() } catch (_: Exception) {} }

    private fun openDataSocket(): Socket {
        if (passivePort < 0) enterPassive()
        logger("DATA", "Opening passive data socket $host:$passivePort")
        return Socket().also { it.connect(InetSocketAddress(host, passivePort), 5000) }
    }

    private fun command(c: String): String {
        logger("FTP", "TX $c")
        writer.write(c); writer.write("\r\n"); writer.flush()
        val r = readResponse(); logger("FTP", "RX $r"); return r
    }

    private fun readResponse(): String {
        val first = reader.readLine() ?: throw IOException("FTP server closed connection")
        if (first.length >= 4 && first[3] == '-') {
            val code = first.substring(0, 3); var line = reader.readLine() ?: return first
            while (!line.startsWith("$code ")) line = reader.readLine() ?: break
            return line
        }
        return first
    }
}
