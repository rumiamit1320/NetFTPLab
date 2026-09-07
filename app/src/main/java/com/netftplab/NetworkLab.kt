package com.netftplab

import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

data class LabPoint(val x: Float, val y: Float)

object NetworkLab {
    fun alohaThroughput(g: Double) = g * exp(-2.0 * g)
    fun slottedThroughput(g: Double) = g * exp(-g)
    fun csmaCaThroughput(g: Double) = min(0.98, 1.0 - exp(-2.2 * g))

    fun curve(mode: String, maxG: Float = 4f): List<LabPoint> = (0..80).map { i ->
        val g = maxG * i / 80.0
        val s = when (mode) {
            "SLOTTED" -> slottedThroughput(g)
            "CSMA/CA" -> csmaCaThroughput(g)
            else -> alohaThroughput(g)
        }
        LabPoint(g.toFloat(), s.toFloat())
    }

    fun cwndTrace(algorithm: String, points: Int = 48): List<LabPoint> {
        var cwnd = 1.0
        var ssthresh = 16.0
        return (1..points).map { x ->
            when (algorithm) {
                "RENO" -> {
                    if (x < 10) cwnd += 1 else cwnd += 1.0 / max(cwnd, 1.0)
                    if (x == 20) { ssthresh = cwnd / 2; cwnd = ssthresh }
                }
                "CUBIC" -> cwnd = 1.0 + 0.018 * (x - 1) * (x - 1)
                else -> cwnd = min(32.0, cwnd + if (x < 12) 1.5 else 0.35)
            }
            LabPoint(x.toFloat(), cwnd.toFloat())
        }
    }
}
