package com.drogueriasortega.nequicapture

import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.text.TextUtils
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.text.DateFormat
import java.util.Date

class MainActivity : AppCompatActivity() {
    private lateinit var statusText: TextView
    private lateinit var pendingText: TextView
    private lateinit var syncText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        statusText = findViewById(R.id.statusText)
        pendingText = findViewById(R.id.pendingText)
        syncText = findViewById(R.id.syncText)

        findViewById<Button>(R.id.btnPermission).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        findViewById<Button>(R.id.btnSync).setOnClickListener {
            SyncWorker.enqueueNow(this)
            refresh()
        }
        SyncWorker.enqueuePeriodic(this)
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val enabled = isNotificationServiceEnabled()
        statusText.text = if (enabled) getString(R.string.status_ok) else getString(R.string.listener_needed)
        pendingText.text = getString(R.string.pending_fmt, PendingStore(this).pendingCount())
        val last = SyncWorker.prefs(this).getLong(SyncWorker.KEY_LAST_SYNC, 0L)
        syncText.text = if (last > 0L) {
            getString(R.string.synced_fmt, DateFormat.getDateTimeInstance().format(Date(last)))
        } else {
            getString(R.string.synced_fmt, "nunca")
        }
    }

    private fun isNotificationServiceEnabled(): Boolean {
        val cn = ComponentName(this, NequiNotificationListener::class.java)
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners")
        if (flat.isNullOrEmpty()) return false
        val splitter = TextUtils.SimpleStringSplitter(':')
        splitter.setString(flat)
        while (splitter.hasNext()) {
            val component = ComponentName.unflattenFromString(splitter.next())
            if (component != null && component == cn) return true
        }
        return false
    }
}
