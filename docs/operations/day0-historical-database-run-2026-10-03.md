# Day 0 full-history database run

Run date: 2026-10-03 to 2026-10-04 (Asia/Kolkata)

## Target

Populate the active SQLite database from 2015-01-01 through the latest completed market session. The requested end date is 2026-10-01: Oct 2 is an NSE trading holiday and Oct 3 is Saturday ([NSE market holidays](https://www.nseindia.com/resources/exchange-communication-holidays?article_id=432919950.0)). The active database path is `instance/stock_screener.db`. The user asked that all actions, failures, diagnoses, and fixes be recorded here for handoff and test review. Never record Kite tokens or authentication query strings.

## Action log

| # | Action | Result |
|---|---|---|
| 1 | Inspected the application startup, database path, job pipeline limits, provider setup, and Kite authentication flow. | Pipeline date spans are limited to 365 days. The active database configuration now points to `instance/stock_screener.db`. |
| 2 | Initialized the active database for the current application and started the local app with its job worker disabled. | `http://127.0.0.1:5000/health/ready` returned 200. |
| 3 | Opened the Kite integration page and completed market-data authentication. | The callback first returned 404 because the app did not have the callback path used by Kite. Added that route. Token exchange succeeded, then a stale redirect caused HTTP 500. Updated the redirect target and confirmed the Kite profile successfully. Authentication query data was not recorded. |
| 4 | Submitted 12 inclusive history ranges from 2015-01-01 through 2026-10-01, with data orchestration enabled. | Pipeline IDs and ranges are in [day0-pipeline-segments-2026-10-03.json](day0-pipeline-segments-2026-10-03.json). |
| 5 | Started the worker to execute pipeline preparation. | NSE constituent retrieval timed out. No historical market-bar fetch started. Stopped the worker after repeated dependent failures. |
| 6 | Inspected the repository's dated constituent CSV and validated its 501 rows. | Imported it into the active database with its actual snapshot date, 2026-09-27, and recorded its source hash. The database API confirms the snapshot is available. |
| 7 | Added preparation logic to reuse a constituent snapshot no more than seven days old. | This uses the recorded Sep 27 snapshot without claiming it was collected on Oct 3. |
| 8 | Retried the failed stages after restarting the app. | Preparation passed snapshot reuse and resolved 505 records; `HFCL` was absent from the primary listing. The test job then failed at corporate-action discovery. |
| 9 | Queried Kite's current instrument data for the alternate listing of `HFCL`. | Kite returned an active instrument record. Preparation now uses the returned exchange identity for history retrieval. |
| 10 | Updated preparation to retain and report unresolved source rows while continuing with successfully resolved instruments. | `DUMMYHEG` remains explicitly unresolved in durable progress and final reconciliation; it is not silently substituted. The retry resolved 506 records and reported one unresolved row. |
| 11 | Stopped and checked the worker after the one-range retry. | Worker is stopped, with no active or queued jobs. All 12 preparation stages and 12 coordinators remain failed; no history bars were requested. |
| 12 | Diagnosed the corporate-action error by repeating the official read-only request with a longer timeout. | The configured NSE URL returned HTTP 404, rather than timing out. The current official path returned HTTP 200 and JSON data for the same date window. |
| 13 | Updated the NSE client to use the current official corporate-action path. | Source change is in `src/domains/reference_data/nse_provider.py`; the first annual range must be retried to verify detection completes before any market-history requests. |
| 14 | Restarted the app with the worker disabled after route cleanup. | `/health/ready` returned 200. `/api/operations/worker/status` and `/api/universe/snapshots` returned the expected worker and dated snapshot state. |
| 15 | Repeated the official 2015 corporate-action query through the updated URL. | Read-only request returned HTTP 200 with 1,919 records for the requested window. |
| 16 | Retried only the 2015 preparation stage through `/api/pipelines/.../stages/market:prepare/retry`. | Snapshot reuse succeeded. Instrument sync resolved 506 records and recorded `DUMMYHEG` as the sole unresolved source row. Corporate-action detection found 1,128 records and skipped 778 unsupported/non-action rows. |
| 17 | Monitored the active corporate-action processing stage. | Durable job remains `RUNNING`; event attempt counters are increasing. No market-bar download has started and the other 11 annual ranges have not been requeued. |
| 18 | Checked the official NSE 2026 equity holiday calendar. | Oct 2, 2026 is a trading holiday; corrected the latest completed session from Oct 2 to Oct 1. The submitted 2026 range must be replaced with one ending Oct 1. |
| 19 | Created the corrected 2026 range, 2026-01-01 through 2026-10-01. | New pipeline ID is in the manifest. The earlier 2026-10-02 submission is marked superseded and its failed stages will not be retried. |
| 20 | Retried the remaining annual preparation/coordinator stages behind the active 2015 preparation. | 23 stages are queued across 2015-2025 and the corrected 2026 range; worker concurrency is one. Two failed stages belong only to the superseded holiday-ending range. |
| 21 | Observed the first historical market batch. | 2015 preparation is at 74/506 instrument requests. The active database currently contains 49,291 bars and 332 coverage rows, spanning 2012-07-16 through 2013-07-12 for the required warm-up before 2015. |
| 22 | Diagnosed the terminal result of the first history batch using durable status and a read-only coverage audit. | The fetcher completed 503 of 506 records, writing 75,239 bars with 503 coverage records for 2012-07-15 through 2013-07-14. `CGCL`, `DEEPAKNTR`, and `MINDACORP` have no coverage for that window. The preparation only returns a generic failure and did not persist each provider error, so these three need targeted diagnosis/retry before declaring that range complete. |
| 23 | Stopped the worker after detecting the failed range and sent a cooperative cancel request to the already-started 2016 preparation. | Worker stop has been requested; job 3 is still running its action-processing stage with `cancel_requested=true`. No additional ranges should start. Remaining queued stages are preserved. |
| 24 | Improved pipeline failure diagnostics for subsequent history chunks. | `pipeline_preparation.py` now writes failed symbols and sanitized per-item reasons into durable progress before failing the stage. The running process has not loaded this source change yet; load it after job 3 exits. |
| 25 | Added corporate-action processing progress checkpoints every 25 records. | Future runs can report this long stage and honor cancellation between records. The active app process still has the earlier code in memory. |
| 26 | Checked the cancellation-pending job status and process health. | At 23:52 Asia/Kolkata it remained in action detection with cancellation requested; the worker process was responsive. The durable event timeline showed progress entered at 23:42 and no history-fetch stage began. |

| 27 | Confirmed job 3 remains active with its stop request. | At 23:56 Asia/Kolkata the latest durable event was still the 23:43 cancellation request; the worker reports one active job and 21 queued. No market-history stage has started. |
| 28 | Checked action-processing progress with read-only database aggregates. | At 23:57:43 Asia/Kolkata, 26 actionable records had no prior attempt, down from 41 in the previous check. The newest recorded attempt was at 23:57:43; processing is advancing. |

| 29 | Confirmed the canceled 2016 preparation reached a terminal state and restarted the app. | Job 3 is `CANCELLED`; worker is stopped. Restarted the app with worker disabled; `/health/ready` returned 200 and the new checkpoints are loaded. |
| 30 | Submitted targeted history diagnostic job 27 for three missing instruments. | A one-shot worker call selected older queued job 4 first; it failed because its preparation stage had been canceled. No market-history request was made by that coordinator. Job 27 remains queued. |
| 31 | Inspected queue order before the diagnostic retry. | Jobs 5 onward were older queued pipeline stages. The diagnostic job was briefly moved to the front, executed, then its original queue timestamp was restored. |

| 32 | Executed the targeted history diagnostic for the three missing instruments. | Job 27 completed but reported all three as errors: `historical provider OHLCV record is invalid`; it wrote zero bars. |
| 33 | Traced the generic error to the provider bar converter. | `NormalizedBar` validation exceptions were caught as generic `ValueError`, hiding the invalid date and invariant. |
| 34 | Improved provider validation diagnostics. | `providers.py` now preserves the invalid candle date and specific normalized-bar validation reason. This change still needs loading and a targeted retry. |

| 35 | Captured exact inconsistent candle details. | Job 29 found CGCL on Apr 9, DEEPAKNTR on Apr 10, and MINDACORP on Apr 8, 2013. Each source low/high failed to contain its own open or close. No bars were written. |
| 36 | Added auditable envelope expansion for inconsistent provider OHLC. | Bulk history preserves raw source rows when needed, expands only high/low to include source open/close, marks the artifact partial, and records a warning with source and stored values. Open and close are unchanged. |
| 37 | Ran the three-symbol verification. | All 741 daily bars were fetched. Audit found 26 range expansions, including 21 MINDACORP sessions with source open/high/low 28.05 and close 29.50. This repeated 5.17% difference is unresolved. |

| 38 | Rejected the candidate OHLC changes after the audit. | Removed the 741 diagnostic bars and three exact-window coverage rows. Retained 26 error-quality events and three source/candidate artifacts as investigation evidence. |
| 39 | Replaced broad range expansion with source verification. | Inconsistent traded bars must now match an official daily row; unmatched zero-volume records are omitted with a quality event. Unsupported price changes are rejected. |

| 40 | Verified flagged dates against official NSE daily files. | All 26 daily files downloaded. Four nonzero-volume rows matched the instrument identity and were independently confirmed; 22 zero-volume rows had no official equity row. |
| 41 | Added evidence-based handling for inconsistent daily bars. | For active trades, require official OHLC scaling to agree within 1% and adjusted volume within 2%; otherwise the symbol fails. Omit a zero-volume row only when the official file has no matching equity row. Save source rows, URL/hash and quality events. |
| 42 | Checked source reachability and Python syntax. | Python `requests` downloaded the official file successfully (HTTP 200); modified modules compiled. |
| 43 | Prepared the next targeted history job. | Restart and exact-window fetch are pending. Existing queued annual stages remain untouched. |

| 44 | Verified the official-source reconciliation in the database. | Job 31 stored 719 bars; all three window-coverage rows are present. Four active trades match official rows after common price scaling, 22 unmatched zero-volume records were omitted, and all 26 prior errors are resolved as warnings. |

| 45 | Fixed stale job progress summaries. | The job detail route was selecting the first 500 events. It now reads the most recent event window; syntax check passed. Restart after the active job ends to load it. |
| 46 | Checked the latest preparation progress. | At 00:37 Asia/Kolkata, job 1 was processing 749 of 2,310 detected corporate actions. The event log is advancing. |

| 47 | Reconciled live pipeline job states. | Job 1 is RUNNING in action processing at 524/2,310; job 2 is FAILED pending preparation. Job 3 is CANCELLED and job 4 is FAILED after its preparation was cancelled. Jobs 5 onward remain queued. |

| 48 | Checked the most recent durable progress event. | At 00:37 Asia/Kolkata, job 1 reached 749/2,310 action records; its lease is current and there is no error. |

| 49 | Checked the current app source and dashboard copy for explicit version labels, then read the durable database job state. | No exact version label is present in src, 	emplates, static, or the app entry/config files checked. Job 1 is still running corporate-action processing at 1,249/2,310 (2026-10-04 00:40 Asia/Kolkata); bars/coverage remain 75,958/506. Jobs 2 and 4 remain failed pending their data stages; job 3 remains cancelled. |
| 50 | Rechecked the active preparation worker and database. | At 00:41 Asia/Kolkata, job 1 advanced to 1,399/2,310 action records; its lease is current and it has no error. Bars/coverage remain 75,958/506 while this stage is processing. |
| 51 | Monitored the active preparation stage. | At 00:42 Asia/Kolkata, job 1 reached 1,524/2,310 action records with a renewed lease and no error. |
| 52 | Enabled the pipeline retry route to requeue a cancelled stage after explicit operator request. | `research_pipeline.py` now dispatches cancelled stages to the dedicated retry method; syntax check passed. This supports resuming the cancelled 2016 preparation after the active 2015 job and app restart. |

| 53 | Checked preparation progress after the retry-route change. | At 00:44 Asia/Kolkata, job 1 reached 1,799/2,310 action records. Its lease is current; no error is recorded. |

| 54 | Monitored the active action-processing stage. | At 00:45 Asia/Kolkata, job 1 reached 1,899/2,310. The job remains active with no error. |

| 55 | Read the latest preparation progress event. | At 00:46 Asia/Kolkata, job 1 reached 2,024/2,310 action records; no error is recorded. |

| 56 | Checked the preparation transition after corporate-action processing. | At 00:47 Asia/Kolkata, job 1 completed action processing and entered the historical bulk fetch, 363/506 requests processed. This stage has not yet reported committed bars. |

| 57 | Recorded the one-shot worker failure and inspected durable state. | The request returned HTTP 500 after job 1 stopped reporting events at 85/506; 12,054 additional bars and 70 coverage records had been committed. The job row remained RUNNING with its one-hour lease expired and no recorded error. |
| 58 | Reclaimed the expired job lease through a controlled one-shot worker call. | Job 1 was reclaimed (attempt 2) and resumed from pipeline preparation; its previously committed history writes remain in the database and are safely upserted. The new lease is current. |

| 59 | Verified the recovered retry is progressing. | At 05:53 Asia/Kolkata, job 1 is processing corporate actions again at 674/2,310; attempt 2 has a current lease and no recorded error. |

| 60 | Checked the recovered job after action processing resumed. | At 05:54 Asia/Kolkata, job 1 reached 1,899/2,310 with a current lease and no error. |

| 61 | Confirmed the retry returned to the historical fetch. | At 05:55 Asia/Kolkata, attempt 2 entered bulk fetch at 11/506 requests; no errors are recorded. |

| 62 | Checked the retried fetch after prior partial writes were replayed. | At 05:56 Asia/Kolkata, job 1 reached 223/506; the 12,054 bars from the prior attempt remain present, while this replay has not reported additional inserts yet. |

| 63 | Monitored the replayed history batch. | At 05:57 Asia/Kolkata, job 1 reached 370/506. Earlier committed bars are preserved; the replay continues with a current lease and no error. |

| 64 | Completed all 506 preparation history requests and checked the durable item outcomes. | The stage failed with `TokenException` for 422 instruments; previously committed bars remain. Opened `http://127.0.0.1:5000/integrations/kite` for a fresh Kite sign-in. Waiting for authentication before retrying. |

| 65 | Reconciled the pipeline manifest and handoff after the Kite rejection. | The 2015 preparation is marked failed pending reauthentication; partial database writes are retained. The recovery sequence now starts with Kite sign-in, then an app restart and stage retry. |

| 66 | Updated the shared page title and sidebar brand to identify the Development environment. | The template source is changed. The running app still serves cached template markup, so a restart after Kite authentication is required before verifying the new label. |

| 67 | Validated the refreshed Kite session with a read-only profile request. | The configured API credentials and saved token returned a profile successfully; no credential values were logged. |
| 68 | Restarted the local app with its background worker disabled. | `/health/ready` returned `ready`; worker status is false. The served page title and sidebar now show Development, and the rendered dashboard contains no version suffix. |
| 69 | Retried the 2015 preparation and started one controlled worker call. | Job 1 was requeued successfully and entered the one-shot worker. The retried stage is in progress; later ranges remain queued. |

| 70 | Read durable progress from the active 2015 preparation. | At 06:10 Asia/Kolkata, job 1 reached 124/2,310 action records; its lease is current and there is no error. |

| 71 | Checked the next action-processing checkpoint. | At 06:11 Asia/Kolkata, job 1 reached 224/2,310; the lease remains current and no error is recorded. |

| 72 | Monitored the active action-processing retry. | At 06:12 Asia/Kolkata, job 1 reached 1,249/2,310 records. Kite is authenticated, the lease is current, and no error is recorded. |

| 73 | Observed the 2015 preparation enter bulk history requests. | At 06:13 Asia/Kolkata, job 1 reached 201/506 requests, with its lease current and no provider errors reported so far. The earlier partial writes remain intact. |

| 74 | Rechecked the durable bulk-fetch progress. | At 06:14 Asia/Kolkata, the active history batch reached 317/506 requests. The worker lease is current and the stage has no reported error. |

| 75 | Checked the final part of the current bulk-fetch batch. | At 06:15 Asia/Kolkata, job 1 reached 469/506 requests with no error; persisted bar/coverage counts remain 88,012/590 pending the stage result. |

| 76 | Investigated why the Universe tab had no current-date row. | The tab lists immutable saved snapshots; only the Sep 27 snapshot (501 members) existed. A refresh labeled Oct 1 was rejected because the download was collected Oct 4; no snapshot was written by that attempt. |
| 77 | Submitted a constituent refresh with the actual collection date, Oct 4. | Job 33 is running via a one-shot worker. Its temporary queue priority is in place so older historical ranges are not started; restore the original queue time when the refresh reaches a terminal state. |

| 78 | Recorded the current-date universe refresh result and restored its queue ordering. | Job 33 failed with `NSE constituent download failed`; no Oct 4 snapshot was written. Its original queue timestamp is restored, and the existing Sep 27 snapshot remains the only one. |

| 79 | Compared the failed app download with the official source request. | The official CSV returns HTTP 200 with a browser-like user agent and CSV accept header; the constituent client omitted request headers. |
| 80 | Updated the constituent client request headers. | `nse_provider.py` now sends the headers used by the successful official-source check. The current app needs a restart before retrying job 33. |

| 81 | Retried the Oct 4 refresh after fixing the source request headers. | Job 33 succeeded; snapshot `96888519-dc8d-5277-81b9-9ae9f526a47d` is saved for 2026-10-04 with 501 members and source hash `2959bf206239284e145f7aecc65095b18d11556d2642323a70f2d26efe0f5cb3`. The Universe API lists it first and returns its members. |
| 82 | Changed preparation to collect a snapshot dated today instead of reusing any snapshot within seven days. | This prevents a Sep 27 snapshot from silently replacing the requested current universe. Preparation now passes the exact collected snapshot ID into instrument sync. |
| 83 | Changed universe refresh/default member lookup to use the NSE local date; corrected the Universe source column mapping. | The page uses Asia/Kolkata date boundaries and displays the `source_url` field returned by the API. |

| 84 | Pointed the history preparation at the exact current snapshot and constrained snapshot reuse to the current NSE date. | This ensures the 2015 run resolves the Oct 4 501-member universe and avoids silently selecting an older snapshot. Source syntax check passed. |
| 85 | Opened the Universe page after the Oct 4 snapshot was saved. | The page route is live; reload the tab to show the Oct 4 row and its 501 members. |
| 86 | Rechecked Kite after the retry completed. | The saved token now returns `TokenException` on a profile check; the 2015 job had already failed with the same provider response on 422 instruments. A fresh authorization must be verified immediately with both profile and one historical request before retrying. |

| 87 | Reauthenticated Kite and verified market-data access immediately. | The configured profile request succeeded, and a read-only TCS daily-history request for Oct 1 returned one candle. |
| 88 | Requeued the 2015 preparation and started one controlled worker call. | Job 1 is running again from the saved Oct 4 snapshot; corporate-action processing began at 0/2,310. |

| 89 | Checked the authenticated 2015 retry checkpoint. | At 06:34 Asia/Kolkata, job 1 is processing 99/2,310 corporate actions; its lease is current and no error is recorded. |

| 90 | Read the next corporate-action progress checkpoint. | At 06:35 Asia/Kolkata, job 1 reached 199/2,310; the lease is current with no error. |

| 91 | Read the latest corporate-action checkpoint. | At 06:35 Asia/Kolkata, job 1 reached 299/2,310 with a current lease and no error. |

| 92 | Monitored action processing. | At 06:36 Asia/Kolkata, job 1 reached 424/2,310; its lease is current and no error is recorded. |

| 93 | Confirmed the scheduled NIFTY 500 snapshot timing with the user. | The Oct 4 collection was correct: refresh on the first trading session of April and October, after the end-of-month membership rejig; reuse the saved snapshot between those windows. |
| 94 | Updated pipeline preparation to match the confirmed schedule. | It reuses the latest snapshot except in April or October when no snapshot from that month exists, so it can refresh at most once in that window. |
| 95 | Reviewed the active 2015 preparation checkpoint. | Job 1 was RUNNING at 1,149/2,310 corporate actions (49.74%) with a current lease and no recorded error. Its earlier worker session handle is no longer available; continue monitoring the database checkpoint. |
| 96 | Fixed preparation result reporting after the expensive work completes. | Replaced a reference to an undefined `snapshot` variable with a fallback calculation based on the selected snapshot date and requested start date. |

| 97 | Added an in-code guard so historical batches skip corporate-action discovery and action-history processing. | A batch ending more than seven calendar days before the current Asia/Kolkata date records `corporate_actions_skipped`; a recent batch still checks and processes actions. |
| 98 | Requested cooperative cancellation of the first 2015 preparation attempt while it was processing 1,449/2,310 corporate actions. | Job 1 reached CANCELLED before history fetching. |
| 99 | Retried 2015 preparation under the corporate-action guard. | Database event 17315 records `corporate_actions_skipped` for end date 2015-12-31; the job proceeded to history fetching. |
| 100 | Observed the first history attempt fail on INDIA VIX provider dates after 505 of 506 requests completed. | The batch reported `historical provider dates are invalid or duplicated`; 74,821 bars from completed requests were written before failure. |
| 101 | Removed INDIA VIX from the shared `NSE_INDEX_SYMBOLS` set. | Preparation instrument selection and benchmark coverage no longer request or require INDIA VIX, including after a database is recreated. |
| 102 | Retried 2015 preparation with existing coverage and the updated index set. | Job 1 is RUNNING with a current lease; first range 2015-01-01 to 2015-12-31 was at 69/505 requests with no recorded error. A temporary queue priority remains applied until this job reaches a terminal state. |

| 103 | Read the latest 2015 history checkpoint. | At 06:58 Asia/Kolkata, job 1 reached 123/505 requests, with 8,389 bars written in its active batch and no recorded error. |

| 104 | Monitored job 1 history ingestion. | At 07:00 Asia/Kolkata, the 2015 range reached 350/505 requests, with 24,682 bars written in the current batch and no recorded error. |

| 105 | Read the terminal checkpoint for the retry after it reached all 505 requests in the 2015-07-15 through 2015-12-31 history window. | Four equities failed only because Kite returned identical duplicate rows for 2015-12-31; no invalid dates or conflicting values were present. |
| 106 | Inspected raw Kite history for COALINDIA, NMDC, ONGC, and PETRONET. | Each returned 116 records with 115 unique dates; the duplicated Dec 31 OHLCV row was byte-for-value identical for each symbol. |
| 107 | Updated Kite historical normalization to ignore identical duplicate daily rows and retain a warning with the raw duplicate record; conflicting duplicate values still fail validation. | A direct COALINDIA request normalized to 115 unique bars, one Dec 31 bar, and one duplicate warning. Source syntax check passed. |
| 108 | Restored job 1's original queue timestamp after its attempt failed. | Original created time `2026-10-03T17:32:41.613873+00:00` is restored before another retry. |

| 109 | Retried the 2015 preparation using exact-duplicate normalization and existing coverage. | The four-equity 2015-07-15 through 2015-12-31 history batch passed; completed-session quality ran and indicator rebuilding began. |
| 110 | Read the current 2015 indicator checkpoint. | At 07:08 Asia/Kolkata, momentum indicator rebuilding reached 275/326 instruments with no job error. |

| 111 | Confirmed the 2015 preparation job reached SUCCEEDED after duplicate-date normalization. | Job result records corporate-action detection and processing as `skipped_historical_batch`; market history, quality, and momentum indicators completed. |
| 112 | Audited the 2015 quality result and database totals. | Quality is PARTIAL: 248 observed sessions, 494 instrument/session gaps, and two unresolved identities (DUMMYHEG, HFCL) under the available historical snapshots. Active database has 264,717 bars and 2,057 coverage rows. These checks are recorded as partial, not full-history completion. |

## Current state

- Active database: `instance/stock_screener.db`.
- Kite authentication: latest direct historical request and the 2015 retry succeeded; continue monitoring during later ranges.
- Constituents: Oct 4 snapshot is saved with 501 members and source hash recorded. Refresh on the first trading session of April and October; reuse the saved snapshot between windows.
- Corporate actions: batches ending more than seven calendar days before the current Asia/Kolkata date skip detection and processing in code. The 2015 job result confirms the skip. A current-date batch still checks actions.
- Index set: INDIA VIX has been removed from `NSE_INDEX_SYMBOLS`; preparation requested 505 instruments.
- Kite duplicate handling: identical same-day OHLCV repeats collapse to one bar and are recorded as a warning; conflicting duplicates and out-of-range dates remain errors. Direct verification returned 115 unique COALINDIA bars from 116 source rows.
- Pipelines: 12 ranges cover 2015-01-01 through 2026-10-01. The 2015 preparation is SUCCEEDED. Its quality status is PARTIAL: 248 observed sessions, 494 missing instrument/session combinations and two unresolved identities (DUMMYHEG and HFCL) based on available membership history. Job 2, the 2015 advance stage, remains FAILED and is next to retry. The 2016 preparation remains cancelled.
- Database totals: 264,717 market bars and 2,057 fetch-coverage rows at the last audit. The full requested date range is not complete.
- Worker: background loop remains disabled. One-shot processing is used. Job 1's original queue timestamp was restored to `2026-10-03T17:32:41.613873+00:00`.
- Known issue: one source row remains unresolved in instrument sync. Three historical OHLC issues in the first warm-up window were reconciled using official exchange rows and explicit zero-volume omissions.

## Resume procedure

1. Check job 1 status and its latest checkpoint; do not retry it while it is RUNNING.
2. If it failed, verify Kite profile and one historical-data request, then retry 2015 preparation against the saved Oct 4 snapshot. The workflow skips corporate actions for this historical range, excludes INDIA VIX, and deduplicates exact repeated daily bars.
3. Retry the 2015 `advance` stage after preparation succeeds; record whether research jobs complete with the partial coverage report.
4. Resume the cancelled 2016 preparation using the updated retry route, then continue the remaining queued ranges one at a time.
5. Keep this log and manifest updated after material actions; verify date coverage, per-instrument status, pipeline stages, and research output before completion.



| 113 | Investigated why BSE code and backup handling remained after the NSE-only instruction; completed cleanup in application code and fixtures. | Removed the Kite BSE-dump cache/fallback, restricted instrument synchronization, storage queries, history fetches, and reference data to NSE, and updated fixtures to exercise NSE behavior. HFCL lookup now tries the `-BE` NSE trading symbol when the constituent series is BE. Exact-token scan of `src`, `tests`, and `pyproject.toml` found no BSE references; broad substring matches were ordinary words such as “observed.” No BSE storage was accessed during this cleanup. |
| 114 | Replaced the yearly data orchestration with one full-history run. | The requested interval is now 2015-01-01 through 2026-10-01. Each NSE instrument is requested only for uncovered intervals, in Kite windows of at most 2,000 calendar days. The lower bound is fixed at 2015-01-01; no earlier history is fetched. |
| 115 | Retired the obsolete yearly queued jobs and submitted the replacement full-history pipeline. | Cancelled 20 queued annual preparation, coordinator, and leftover signal jobs without deleting stored bars or coverage. Full-history pipeline `9f148cdd-71eb-507c-8932-e11d5af6d527` was created with preparation job 37 and coordinator job 38. Its ordered research stage is indicator cache, percentiles, daily scores, then weekly rankings. |
| 116 | Corrected current-batch corporate-action handling before the full-history retry. | The workflow now queries only the final seven calendar days ending on the requested completed session and processes only action IDs detected in that query. It does not process historic action records during a history rebuild. The first full-history attempt was cancelled before history fetching and no bars were removed. |
| 117 | Made the latest-batch corporate-action source non-blocking for the full history run. | The NSE corporate-action request did not return within its configured timeout sequence. The preparation now records this as `unavailable_latest_batch` and continues with history ingestion; it never expands into historic action processing. |
| 118 | Completed the full historical preparation. | Job 37 reused already stored 2015-01-01 through 2017-12-31 coverage, then fetched the two uncovered Kite windows 2018-01-01 through 2023-06-23 and 2023-06-24 through 2026-10-01. The combined stored range is 2015-01-01 through 2026-10-01. A clean database has no prior coverage and therefore uses three windows of at most 2,000 calendar days. The job ran quality and rebuilt momentum indicators. Four constituent records could not be resolved to Kite NSE instruments: BAGMANE, BIRET, DUMMYHEG, and EMBASSY. |
| 119 | Completed the staged full-range research calculation. | Pipeline `9f148cdd-71eb-507c-8932-e11d5af6d527` succeeded for 2015-01-01 through 2026-10-01. Job 39 produced 1,061,716 daily momentum scores for 2,911 sessions and 224,228 weekly ranking rows across 614 weeks. The scoring path now reads the immutable active strategy definition once per job instead of once per factor value. |
| 120 | Enforced the requested database floor in the completed database. | Removed 187,598 pre-2015 market bars and clipped coverage records to begin at 2015-01-01. Final market history is 1,146,602 bars across 502 instruments, from 2015-01-01 through 2026-10-01. |
