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
            """(?i)(.+?)\s+te\s+envi[oó]\s+\$?\s*([\d.,]+)\b""",
        ),
        Pattern.compile(
            """(?i)(.+?)\s+te\s+envi[oó]\s+([\d.,]+)\s*[!,.]""",
        ),
    )
    private val NOISE_PREFIX = Regex("""(?i)^(env[ií]o|nequi)\s+""")

    fun parse(title: CharSequence?, text: CharSequence?, bigText: CharSequence?): ParsedNequi? {
        // Prefer body text alone so the title ("Envío") is not glued into the client name.
        for (part in listOf(bigText, text, title)) {
            val raw = part?.toString()?.trim().orEmpty()
            if (raw.isNotEmpty()) {
                parseFlat(raw)?.let { return it }
            }
        }
        val combined = listOfNotNull(title, text, bigText)
            .joinToString(" ") { it.toString().trim() }
            .replace(Regex("\\s+"), " ")
            .trim()
        return parseFlat(combined)
    }

    private fun parseFlat(flat: String): ParsedNequi? {
        if (flat.isEmpty()) return null
        for (p in PATTERNS) {
            val m = p.matcher(flat)
            if (m.find()) {
                val client = cleanClient(m.group(1).orEmpty())
                val value = normalizeMoney(m.group(2).orEmpty()) ?: continue
                if (client.isBlank()) continue
                return ParsedNequi(client = client, value = value, rawText = flat)
            }
        }
        return null
    }

    private fun cleanClient(raw: String): String {
        var s = raw.trim().replace(Regex("\\s+"), " ")
        while (NOISE_PREFIX.containsMatchIn(s)) {
            s = NOISE_PREFIX.replaceFirst(s, "").trim()
        }
        return s
    }

    private fun normalizeMoney(raw: String): String? {
        val cleaned = raw.replace(" ", "")
        val normalized = if (cleaned.contains(",") && cleaned.contains(".")) {
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
