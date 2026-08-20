-- =============================================================================
-- Speaker Program Impact / ROI — Demonstration Queries
-- Engine: DuckDB (PostgreSQL-compatible). Run against speaker_roi.duckdb.
-- =============================================================================


-- 1. ATTENDANCE FUNNEL — How many HCPs move from invited → registered → verified attended?
SELECT
    COUNT(DISTINCT i.hcp_id)                                              AS invited,
    COUNT(DISTINCT CASE WHEN a.registered = 1 THEN a.hcp_id END)         AS registered,
    COUNT(DISTINCT CASE WHEN a.verified_attended = 1 THEN a.hcp_id END)  AS verified_attended,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN a.registered = 1 THEN a.hcp_id END)
          / NULLIF(COUNT(DISTINCT i.hcp_id), 0), 1)                      AS pct_registered,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN a.verified_attended = 1 THEN a.hcp_id END)
          / NULLIF(COUNT(DISTINCT i.hcp_id), 0), 1)                      AS pct_attended
FROM silver.event_invitations i
LEFT JOIN silver.event_attendance a
    ON i.event_id = a.event_id AND i.hcp_id = a.hcp_id
JOIN silver.events e
    ON i.event_id = e.event_id
WHERE e.status = 'Completed';


-- 2. ELIGIBILITY BREAKDOWN — How is the eligible population distributed by group and exclusion reason?
SELECT
    "group",
    exclusion_reason,
    COUNT(*)                                                    AS pairs,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)         AS pct_of_total
FROM gold.eligibility_table
GROUP BY "group", exclusion_reason
ORDER BY
    CASE "group"
        WHEN 'treatment'         THEN 1
        WHEN 'control_candidate' THEN 2
        WHEN 'excluded'          THEN 3
    END,
    exclusion_reason NULLS FIRST;


-- 3. TOP EVENTS BY TREATMENT COHORT SIZE — Which completed events have the most clean treatment HCPs?
SELECT
    e.event_id,
    e.date            AS event_date,
    e.topic,
    e.format,
    es.treatment,
    es.control_candidate,
    es.excluded,
    es.total_invited
FROM gold.eligibility_summary es
JOIN silver.events e ON es.event_id = e.event_id
WHERE es.event_id <> 'ALL_EVENTS'
ORDER BY es.treatment DESC
LIMIT 15;


-- 4. CONTROL-TO-TREATMENT RATIO PER EVENT — Is there enough control density for matching?
SELECT
    ROUND(AVG(ratio), 1)     AS avg_ratio,
    ROUND(MEDIAN(ratio), 1)  AS median_ratio,
    MIN(ratio)               AS min_ratio,
    MAX(ratio)               AS max_ratio,
    COUNT(*)                 AS n_events,
    SUM(CASE WHEN ratio < 2.0 THEN 1 ELSE 0 END) AS events_below_2x
FROM (
    SELECT
        event_id,
        CASE WHEN treatment > 0
             THEN 1.0 * control_candidate / treatment
             ELSE NULL
        END AS ratio
    FROM gold.eligibility_summary
    WHERE event_id <> 'ALL_EVENTS'
      AND treatment > 0
) sub;


-- 5. SPECIALTY / REGION BALANCE — Are treatment and control groups structurally comparable?
WITH labeled AS (
    SELECT
        g.master_hcp_id,
        g."group",
        h.specialty,
        h.region
    FROM gold.eligibility_table g
    JOIN silver.hcp_master h ON g.master_hcp_id = h.hcp_id
    WHERE g."group" IN ('treatment', 'control_candidate')
)
SELECT
    specialty,
    ROUND(100.0 * COUNT(*) FILTER (WHERE "group" = 'treatment')
          / NULLIF(SUM(COUNT(*) FILTER (WHERE "group" = 'treatment')) OVER (), 0), 1)
        AS treatment_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE "group" = 'control_candidate')
          / NULLIF(SUM(COUNT(*) FILTER (WHERE "group" = 'control_candidate')) OVER (), 0), 1)
        AS control_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE "group" = 'treatment')
        / NULLIF(SUM(COUNT(*) FILTER (WHERE "group" = 'treatment')) OVER (), 0)
      - 100.0 * COUNT(*) FILTER (WHERE "group" = 'control_candidate')
        / NULLIF(SUM(COUNT(*) FILTER (WHERE "group" = 'control_candidate')) OVER (), 0)
    , 1) AS diff_pp
FROM labeled
GROUP BY specialty
ORDER BY treatment_pct DESC;


-- 6. DATA QUALITY SUMMARY — What percentage of data needed quarantine handling, by reason?
WITH quarantine_counts AS (
    SELECT 'duplicate_signin'               AS reason, COUNT(*) AS n FROM silver.event_attendance WHERE FALSE  -- placeholder: already removed
    UNION ALL
    SELECT 'cancelled_event_residual',
           (SELECT COUNT(*) FROM bronze.event_attendance ba
            JOIN bronze.events be ON ba.event_id = be.event_id
            WHERE be.status = 'Cancelled')
    UNION ALL
    SELECT 'non_completed_event_invitations',
           (SELECT COUNT(*) FROM bronze.event_invitations bi
            JOIN bronze.events be ON bi.event_id = be.event_id
            WHERE be.status <> 'Completed')
    UNION ALL
    SELECT 'unresolved_identity',
           (SELECT COUNT(*) FROM bronze.identity_crosswalk WHERE match_status = 'review')
    UNION ALL
    SELECT 'outlier_cost_flagged',
           (SELECT COUNT(*) FROM silver.event_cost WHERE finance_review_flag = 1)
    UNION ALL
    SELECT 'missing_rx_months',
           (SELECT b.expected - s.actual
            FROM (SELECT COUNT(*) AS expected FROM bronze.hcp_rx_monthly) b,
                 (SELECT COUNT(*) AS actual  FROM silver.hcp_rx_monthly) s)
),
source_sizes AS (
    SELECT 'event_attendance'     AS source, (SELECT COUNT(*) FROM bronze.event_attendance) AS total
    UNION ALL SELECT 'event_invitations',     (SELECT COUNT(*) FROM bronze.event_invitations)
    UNION ALL SELECT 'identity_crosswalk',    (SELECT COUNT(*) FROM bronze.identity_crosswalk)
    UNION ALL SELECT 'event_cost',            (SELECT COUNT(*) FROM bronze.event_cost)
    UNION ALL SELECT 'hcp_rx_monthly',        (SELECT COUNT(*) FROM bronze.hcp_rx_monthly)
)
SELECT
    q.reason,
    q.n                                          AS quarantined_rows,
    COALESCE(s.total, 0)                         AS source_total,
    CASE WHEN s.total > 0
         THEN ROUND(100.0 * q.n / s.total, 2)
         ELSE NULL
    END                                          AS pct_quarantined
FROM quarantine_counts q
LEFT JOIN source_sizes s
    ON q.reason LIKE '%' || s.source || '%'
       OR (q.reason = 'duplicate_signin'               AND s.source = 'event_attendance')
       OR (q.reason = 'cancelled_event_residual'        AND s.source = 'event_attendance')
       OR (q.reason = 'non_completed_event_invitations' AND s.source = 'event_invitations')
       OR (q.reason = 'unresolved_identity'             AND s.source = 'identity_crosswalk')
       OR (q.reason = 'outlier_cost_flagged'            AND s.source = 'event_cost')
       OR (q.reason = 'missing_rx_months'               AND s.source = 'hcp_rx_monthly')
WHERE q.n > 0
ORDER BY q.n DESC;


-- 7. PRE-EVENT Rx TREND — Are treatment and control groups comparable before the event?
--    Uses EV2001 (the first completed event) as a concrete example.
WITH ev AS (
    SELECT event_id, date AS event_date
    FROM silver.events
    WHERE event_id = 'EV2001'
),
cohort AS (
    SELECT
        g.master_hcp_id,
        g."group"
    FROM gold.eligibility_table g, ev
    WHERE g.event_id = ev.event_id
      AND g."group" IN ('treatment', 'control_candidate')
),
rx_data AS (
    SELECT
        r.hcp_id,
        r.month,
        r.nrx,
        c."group"
    FROM silver.hcp_rx_monthly r
    JOIN cohort c ON r.hcp_id = c.master_hcp_id
    WHERE r.product = 'ENDOSTAT'
      AND r.month BETWEEN '2024-03' AND '2024-08'
)
SELECT
    month,
    ROUND(AVG(nrx) FILTER (WHERE "group" = 'treatment'), 2)         AS treatment_avg_nrx,
    ROUND(AVG(nrx) FILTER (WHERE "group" = 'control_candidate'), 2) AS control_avg_nrx,
    COUNT(*) FILTER (WHERE "group" = 'treatment')                    AS treatment_n,
    COUNT(*) FILTER (WHERE "group" = 'control_candidate')            AS control_n
FROM rx_data
GROUP BY month
ORDER BY month;
