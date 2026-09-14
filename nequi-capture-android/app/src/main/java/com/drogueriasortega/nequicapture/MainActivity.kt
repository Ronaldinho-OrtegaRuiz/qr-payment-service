package com.drogueriasortega.nequicapture

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.text.TextUtils
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import java.text.DateFormat
import java.util.Date

class MainActivity : AppCompatActivity() {
    private lateinit var statusText: TextView
    private lateinit var pendingText: TextView
    private lateinit var syncText: TextView

    private val notifPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        KeepAliveService.start(this)
        refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        setContentView(R.layout.activity_main)

        val root = findViewById<android.view.View>(R.id.root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.updatePadding(top = bars.top, bottom = bars.bottom)
            insets
        }

        statusText = findViewById(R.id.statusText)
        pendingText = findViewById(R.id.pendingText)
        syncText = findViewById(R.id.syncText)

        findViewById<Button>(R.id.btnPermission).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        findViewById<Button>(R.id.btnAppNotifs).setOnClickListener {
            ensurePostNotifications()
            openAppNotificationSettings()
        }
        findViewById<Button>(R.id.btnSync).setOnClickListener {
            ensurePostNotifications()
            rebindListener()
            KeepAliveService.start(this)
            SyncWorker.enqueueNow(this)
            refresh()
        }

        ensurePostNotifications()
        KeepAliveService.start(this)
        SyncWorker.enqueuePeriodic(this)
    }

    override fun onResume() {
        super.onResume()
        ensurePostNotifications()
        rebindListener()
        KeepAliveService.start(this)
        SyncWorker.enqueueNow(this)
        refresh()
    }

    private fun ensurePostNotifications() {
        if (Build.VERSION.SDK_INT < 33) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun openAppNotificationSettings() {
        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
            putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
        }
        startActivity(intent)
    }

    private fun rebindListener() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
        try {
            NotificationListenerService.requestRebind(
                ComponentName(this, NequiNotificationListener::class.java),
            )
        } catch (_: Exception) {
            // Ignore OEM failures; permission toggle remains the fallback.
        }
    }

    private fun refresh() {
        val enabled = isNotificationServiceEnabled()
        statusText.text =
            if (enabled) getString(R.string.status_ok) else getString(R.string.listener_needed)
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
