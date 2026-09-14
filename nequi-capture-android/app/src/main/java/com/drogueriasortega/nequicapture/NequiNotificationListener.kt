package com.drogueriasortega.nequicapture

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class NequiNotificationListener : NotificationListenerService() {
    override fun onListenerConnected() {
        super.onListenerConnected()
        // Catch already-visible Nequi alerts after enabling permission.
        activeNotifications?.forEach { handle(it) }
        SyncWorker.enqueuePeriodic(this)
        SyncWorker.enqueueNow(this)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        handle(sbn)
    }

    private fun handle(sbn: StatusBarNotification) {
        if (sbn.packageName != NEQUI_PKG) return
        val n = sbn.notification ?: return
        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)
        val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
        val parsed = NequiParser.parse(title, text, big) ?: return
        val key = sbn.key?.takeIf { it.isNotBlank() }
            ?: "nequi-${sbn.postTime}-${parsed.client}-${parsed.value}"
        PendingStore(this).upsert(
            PendingNequi(
                notificationKey = key,
                client = parsed.client,
                value = parsed.value,
                notifiedAtMillis = sbn.postTime,
                rawText = parsed.rawText,
            ),
        )
        SyncWorker.enqueueNow(this)
    }

    companion object {
        const val NEQUI_PKG = "com.nequi.MobileApp"
    }
}
