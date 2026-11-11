package ru.mangapoisk.reborn.download

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import ru.mangapoisk.reborn.MangaApp
import ru.mangapoisk.reborn.data.local.entity.DownloadEntity
import ru.mangapoisk.reborn.data.local.entity.StoredPage
import ru.mangapoisk.reborn.data.model.DownloadStatus
import ru.mangapoisk.reborn.data.remote.MediaUrlResolver
import java.io.File
import java.io.IOException

/**
 * Downloads every page of one chapter to app-private storage and records the
 * relative paths in Room so the reader can work fully offline afterwards.
 *
 * Partial files are kept on failure, making a retry cheap.  WorkManager retries
 * interrupted work; the UI can also explicitly retry a failed download.
 */
class DownloadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val chapterId = inputData.getString(KEY_CHAPTER_ID) ?: return@withContext Result.failure()
        val app = applicationContext as? MangaApp ?: return@withContext Result.failure()
        val container = app.container
        val dao = container.database.downloadDao()
        val entity = dao.find(chapterId) ?: return@withContext Result.failure()

        if (entity.status == DownloadStatus.DONE.name) return@withContext Result.success()

        val directory = container.downloadRepository.chapterDirectory(chapterId)
        directory.mkdirs()
        val stored = mutableListOf<StoredPage>()

        try {
            val chapter = container.api.chapter(chapterId)
            val pages = chapter.pages
            if (pages.isEmpty()) {
                markFailed(dao, entity, "Chapter has no pages")
                return@withContext Result.failure()
            }

            markProgress(dao, entity, DownloadStatus.RUNNING, 0, pages.size, emptyList())
            setProgress(workDataOf(KEY_PROGRESS to 0, KEY_TOTAL to pages.size))

            pages.forEachIndexed { index, page ->
                ensureActive()
                val number = if (page.number > 0) page.number else index + 1
                val relativePath = container.downloadRepository.relativePath(chapterId, number)
                val file = File(applicationContext.filesDir, relativePath)

                if (!file.exists() || file.length() == 0L) {
                    downloadPage(container, page.url, file)
                }
                stored.add(
                    StoredPage(
                        number = number,
                        path = relativePath,
                        width = page.width,
                        height = page.height,
                    ),
                )

                markProgress(
                    dao = dao,
                    entity = entity,
                    status = DownloadStatus.RUNNING,
                    downloaded = stored.size,
                    total = pages.size,
                    stored = stored,
                )
                setProgress(
                    workDataOf(
                        KEY_PROGRESS to stored.size,
                        KEY_TOTAL to pages.size,
                    ),
                )
            }

            val now = System.currentTimeMillis()
            container.database.downloadDao().upsert(
                entity.copy(
                    status = DownloadStatus.DONE.name,
                    downloadedPages = stored.size,
                    totalPages = pages.size,
                    pagesJson = container.json.encodeToString(
                        ListSerializer(StoredPage.serializer()),
                        stored,
                    ),
                    error = null,
                    updatedAt = now,
                ),
            )
            Result.success()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            markFailed(dao, entity, error.message ?: error.javaClass.simpleName)
            Result.failure()
        }
    }

    private fun downloadPage(
        container: ru.mangapoisk.reborn.di.AppContainer,
        rawUrl: String,
        target: File,
    ) {
        val url = MediaUrlResolver.resolve(rawUrl, container.settingsStore.currentBaseUrl)
            ?: throw IOException("Invalid image URL")
        val request = okhttp3.Request.Builder()
            .url(url)
            .header("Accept", "image/*")
            .build()
        container.downloadClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("Image request failed: HTTP ${response.code}")
            }
            val body = response.body ?: throw IOException("Empty image response")
            val temp = File(target.parentFile, "${target.name}.tmp")
            body.byteStream().use { input ->
                temp.outputStream().use { output -> input.copyTo(output) }
            }
            if (!temp.renameTo(target)) {
                temp.copyTo(target, overwrite = true)
                temp.delete()
            }
        }
    }

    private suspend fun markProgress(
        dao: ru.mangapoisk.reborn.data.local.dao.DownloadDao,
        entity: DownloadEntity,
        status: DownloadStatus,
        downloaded: Int,
        total: Int,
        stored: List<StoredPage>,
    ) {
        val app = applicationContext as MangaApp
        dao.upsert(
            entity.copy(
                status = status.name,
                downloadedPages = downloaded,
                totalPages = total,
                pagesJson = app.container.json.encodeToString(
                    ListSerializer(StoredPage.serializer()),
                    stored,
                ),
                error = null,
                updatedAt = System.currentTimeMillis(),
            ),
        )
    }

    private suspend fun markFailed(
        dao: ru.mangapoisk.reborn.data.local.dao.DownloadDao,
        entity: DownloadEntity,
        message: String,
    ) {
        dao.upsert(
            entity.copy(
                status = DownloadStatus.FAILED.name,
                error = message.take(500),
                updatedAt = System.currentTimeMillis(),
            ),
        )
    }

    companion object {
        const val KEY_CHAPTER_ID = "chapter_id"
        const val KEY_PROGRESS = "progress"
        const val KEY_TOTAL = "total"
    }
}
