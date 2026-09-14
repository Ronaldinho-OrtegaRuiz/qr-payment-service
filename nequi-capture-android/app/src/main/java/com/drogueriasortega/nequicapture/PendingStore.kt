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

/**
 * Pending queue + permanent-ish set of already-synced notification keys.
 * Prevents re-uploading the same shade notifications every time the listener reconnects.
 */
class PendingStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun upsert(item: PendingNequi): Boolean {
        if (wasSynced(item.notificationKey)) return false
        val map = loadPending()
        if (map.containsKey(item.notificationKey)) return false
        map[item.notificationKey] = item
        savePending(map)
        return true
    }

    fun all(): List<PendingNequi> = loadPending().values.sortedBy { it.notifiedAtMillis }

    fun markSynced(keys: Collection<String>) {
        if (keys.isEmpty()) return
        val pending = loadPending()
        keys.forEach { pending.remove(it) }
        savePending(pending)

        val synced = loadSynced().toMutableList()
        val seen = synced.toHashSet()
        for (k in keys) {
            if (seen.add(k)) synced.add(k)
        }
        while (synced.size > MAX_SYNCED) {
            synced.removeAt(0)
        }
        prefs.edit().putString(KEY_SYNCED, JSONArray(synced).toString()).apply()
    }

    fun wasSynced(key: String): Boolean = loadSynced().contains(key)

    fun pendingCount(): Int = loadPending().size

    private fun loadPending(): LinkedHashMap<String, PendingNequi> {
        val raw = prefs.getString(KEY_PENDING, "[]") ?: "[]"
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

    private fun savePending(map: Map<String, PendingNequi>) {
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
        prefs.edit().putString(KEY_PENDING, arr.toString()).apply()
    }

    private fun loadSynced(): List<String> {
        val raw = prefs.getString(KEY_SYNCED, "[]") ?: "[]"
        val arr = JSONArray(raw)
        return buildList {
            for (i in 0 until arr.length()) add(arr.getString(i))
        }
    }

    companion object {
        private const val PREFS = "nequi_pending"
        private const val KEY_PENDING = "items"
        private const val KEY_SYNCED = "synced_keys"
        private const val MAX_SYNCED = 500
    }
}
