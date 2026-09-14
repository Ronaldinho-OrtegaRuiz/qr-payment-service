package com.drogueriasortega.nequicapture

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

class SyncWorker(appContext: Context, params: WorkerParameters) :
    CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val store = PendingStore(applicationContext)
        val pending = store.all()
        if (pending.isEmpty()) return Result.success()
        val sync = ApiClient.sync(applicationContext, pending)
        return if (sync.isSuccess) {
            // Remember keys forever (capped) so shade re-scans do not re-queue them.
            store.markSynced(sync.getOrThrow())
            prefs(applicationContext).edit()
                .putLong(KEY_LAST_SYNC, System.currentTimeMillis())
                .apply()
            Result.success()
        } else {
            Result.retry()
        }
    }

    companion object {
        private const val UNIQUE = "nequi_sync"
        private const val UNIQUE_NOW = "nequi_sync_now"
        private const val PREFS = "nequi_meta"
        const val KEY_LAST_SYNC = "last_sync"

        fun prefs(context: Context) =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        fun enqueuePeriodic(context: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                UNIQUE,
                ExistingPeriodicWorkPolicy.UPDATE,
                req,
            )
        }

        fun enqueueNow(context: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>().build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_NOW,
                ExistingWorkPolicy.REPLACE,
                req,
            )
        }
    }
}
