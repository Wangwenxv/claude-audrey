export type TurnStartTime = number

/**
 * Default number of files uploaded in parallel during BYOC session file
 * persistence. Mirrors the Files API default concurrency.
 */
export const DEFAULT_UPLOAD_CONCURRENCY = 5

/**
 * Maximum number of modified files that will be persisted in a single turn.
 * Beyond this limit persistence is skipped to avoid unbounded uploads.
 */
export const FILE_COUNT_LIMIT = 1000

/**
 * Subdirectory (under the session directory) that holds output files eligible
 * for persistence.
 */
export const OUTPUTS_SUBDIR = 'outputs'

/** A file that was successfully persisted. */
export type PersistedFile = {
  filename: string
  file_id: string
}

/** A file that failed to persist, with the associated error message. */
export type FailedPersistence = {
  filename: string
  error: string
}

/** Result payload describing which files were persisted and which failed. */
export type FilesPersistedEventData = {
  files: PersistedFile[]
  failed: FailedPersistence[]
}
