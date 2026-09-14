package com.drogueriasortega.nequicapture

import java.util.Locale
import java.util.regex.Pattern

data class ParsedNequi(
    val client: String,
    val value: String,
    val rawText: String,
)

object NequiParser {
    private val PATTERNS = listOf(
        Pattern.compile(
            """(?i)^\s*(.+?)\s+te\s+envi[oó]\s+\$?\s*([\d.,]+)\b""",
        ),
        Pattern.compile(
            """(?i)^\s*(.+?)\s+te\s+envi[oó]\s+([\d.,]+)\s*[!,.]""",
        ),
    )

    fun parse(title: CharSequence?, text: CharSequence?, bigText: CharSequence?): ParsedNequi? {
        val combined = listOfNotNull(title, text, bigText)
            .joinToString("\n") { it.toString().trim() }
            .trim()
        if (combined.isEmpty()) return null
        val flat = combined.replace('\n', ' ').replace(Regex("\\s+"), " ").trim()
        for (p in PATTERNS) {
            val m = p.matcher(flat)
            if (m.find()) {
                val client = m.group(1)?.trim().orEmpty()
                val rawVal = m.group(2)?.trim().orEmpty()
                val value = normalizeMoney(rawVal) ?: continue
                if (client.isBlank()) continue
                return ParsedNequi(client = client, value = value, rawText = flat)
            }
        }
        return null
    }

    private fun normalizeMoney(raw: String): String? {
        val cleaned = raw.replace(" ", "")
        val normalized = if (cleaned.contains(",") && cleaned.contains(".")) {
            // 1.234,56 -> 1234.56
            cleaned.replace(".", "").replace(",", ".")
        } else {
            cleaned.replace(",", "")
        }
        return try {
            val d = normalized.toBigDecimal()
            if (d < java.math.BigDecimal.ZERO) null
            else String.format(Locale.US, "%.2f", d)
        } catch (_: Exception) {
            null
        }
    }
}
