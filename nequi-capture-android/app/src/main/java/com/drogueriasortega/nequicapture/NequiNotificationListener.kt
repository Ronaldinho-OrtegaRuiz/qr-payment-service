package com.drogueriasortega.nequicapture

import android.app.Notification
import android.os.Handler
import android.os.Looper
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class NequiNotificationListener : NotificationListenerService() {
    private val handler = Handler(Looper.getMainLooper())
    private val rescanRunnable = object : Runnable {
        override fun run() {
            scanActive()
            handler.postDelayed(this, RESCAN_MS)
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        KeepAliveService.start(this)
        SyncWorker.enqueuePeriodic(this)
        scanActive()
        handler.removeCallbacks(rescanRunnable)
        handler.postDelayed(rescanRunnable, RESCAN_MS)
    }

    override fun onListenerDisconnected() {
        handler.removeCallbacks(rescanRunnable)
        super.onListenerDisconnected()
    }

    override fun onDestroy() {
        handler.removeCallbacks(rescanRunnable)
        super.onDestroy()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        handle(sbn)
    }

    private fun scanActive() {
        try {
            activeNotifications?.forEach { handle(it) }
        } catch (_: Exception) {
            // Listener may be mid-disconnect on OEM builds.
        }
        SyncWorker.enqueueNow(this)
    }

    private fun handle(sbn: StatusBarNotification) {
        if (sbn.packageName != NEQUI_PKG) return
        val n = sbn.notification ?: return
        // Android groups Nequi alerts; the summary has no payment payload.
        if ((n.flags and Notification.FLAG_GROUP_SUMMARY) != 0) return

        val store = PendingStore(this)
        val key = sbn.key?.takeIf { it.isNotBlank() }
            ?: "nequi-${sbn.postTime}"
        if (store.wasSynced(key)) return

        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)
        val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
        val parsed = NequiParser.parse(title, text, big) ?: return

        val added = store.upsert(
            PendingNequi(
                notificationKey = key,
                client = parsed.client,
                value = parsed.value,
                notifiedAtMillis = sbn.postTime,
                rawText = parsed.rawText,
            ),
        )
        if (added) {
            SyncWorker.enqueueNow(this)
        }
    }

    companion object {
        const val NEQUI_PKG = "com.nequi.MobileApp"
        private const val RESCAN_MS = 60_000L
    }
}
