package com.drogueriasortega.nequicapture

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class PendingNequi(
    val notificationKey: String,
    val client: String,
    val value: String,
    val notifiedAtMillis: Long,
    val rawText: String,
)

class PendingStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun upsert(item: PendingNequi) {
        val map = loadMap()
        map[item.notificationKey] = item
        saveMap(map)
    }

    fun all(): List<PendingNequi> = loadMap().values.sortedBy { it.notifiedAtMillis }

    fun removeKeys(keys: Collection<String>) {
        if (keys.isEmpty()) return
        val map = loadMap()
        keys.forEach { map.remove(it) }
        saveMap(map)
    }

    fun pendingCount(): Int = loadMap().size

    private fun loadMap(): LinkedHashMap<String, PendingNequi> {
        val raw = prefs.getString(KEY, "[]") ?: "[]"
        val arr = JSONArray(raw)
        val out = LinkedHashMap<String, PendingNequi>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            val item = PendingNequi(
                notificationKey = o.getString("notification_key"),
                client = o.getString("client"),
                value = o.getString("value"),
                notifiedAtMillis = o.getLong("notified_at"),
                rawText = o.optString("raw_text", ""),
            )
            out[item.notificationKey] = item
        }
        return out
    }

    private fun saveMap(map: Map<String, PendingNequi>) {
        val arr = JSONArray()
        map.values.forEach { item ->
            arr.put(
                JSONObject()
                    .put("notification_key", item.notificationKey)
                    .put("client", item.client)
                    .put("value", item.value)
                    .put("notified_at", item.notifiedAtMillis)
                    .put("raw_text", item.rawText),
            )
        }
        prefs.edit().putString(KEY, arr.toString()).apply()
    }

    companion object {
        private const val PREFS = "nequi_pending"
        private const val KEY = "items"
    }
}
