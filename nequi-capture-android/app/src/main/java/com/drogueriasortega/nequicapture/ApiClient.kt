package com.drogueriasortega.nequicapture

import android.content.Context
import android.os.Build
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

object ApiClient {
    fun sync(context: Context, items: List<PendingNequi>): Result<Set<String>> {
        if (items.isEmpty()) return Result.success(emptySet())
        return try {
            val deviceId = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ANDROID_ID,
            ) ?: Build.MODEL
            val arr = JSONArray()
            items.forEach { item ->
                arr.put(
                    JSONObject()
                        .put("client", item.client)
                        .put("value", item.value)
                        .put("notified_at", item.notifiedAtMillis)
                        .put("notification_key", item.notificationKey)
                        .put("raw_text", item.rawText)
                        .put("device_id", deviceId),
                )
            }
            val body = JSONObject().put("items", arr).toString()
            val url = URL(BuildConfig.API_BASE_URL.trimEnd('/') + "/nequi-payments/ingest")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 20000
                readTimeout = 30000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("X-Nequi-Device-Key", BuildConfig.NEQUI_DEVICE_KEY)
            }
            OutputStreamWriter(conn.outputStream, StandardCharsets.UTF_8).use { it.write(body) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.let { BufferedReader(InputStreamReader(it, StandardCharsets.UTF_8)).readText() }.orEmpty()
            if (code !in 200..299) {
                return Result.failure(IllegalStateException("HTTP $code: $text"))
            }
            // Idempotent: treat all sent keys as done (created or duplicate).
            Result.success(items.map { it.notificationKey }.toSet())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
