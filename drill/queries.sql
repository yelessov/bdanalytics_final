-- ===========================================================================
-- Apache Drill over HBase  (storage plugin "hbase", table ucr_crime_monthly)
-- HBase returns raw bytes, so every cell goes through CONVERT_FROM(...,'UTF8')
-- and counts are CAST to INT. A view hides that once.
-- Run with:  python3 scripts/run_drill_queries.py   (or paste them into the
-- Drill Web UI at http://localhost:8047/query)
-- Statements are separated by a line containing only ';'
-- ===========================================================================

-- V0. typed view over the HBase table ---------------------------------------
CREATE OR REPLACE VIEW dfs.tmp.crime AS
SELECT
  CONVERT_FROM(t.row_key, 'UTF8')                                        AS rk,
  CONVERT_FROM(t.agency.`state`, 'UTF8')                                 AS state,
  CONVERT_FROM(t.agency.`ori`, 'UTF8')                                   AS ori,
  CONVERT_FROM(t.agency.`name`, 'UTF8')                                  AS agency_name,
  CONVERT_FROM(t.agency.`type`, 'UTF8')                                  AS agency_type,
  CONVERT_FROM(t.agency.`pop_bucket`, 'UTF8')                            AS pop_bucket,
  CAST(CONVERT_FROM(t.agency.`year`, 'UTF8') AS INT)                     AS yr,
  CAST(CONVERT_FROM(t.agency.`month`, 'UTF8') AS INT)                    AS mon,
  CAST(CONVERT_FROM(t.agency.`population`, 'UTF8') AS INT)               AS population,
  CAST(CONVERT_FROM(t.violent.`murder`, 'UTF8') AS INT)                  AS murder,
  CAST(CONVERT_FROM(t.violent.`robbery`, 'UTF8') AS INT)                 AS robbery,
  CAST(CONVERT_FROM(t.violent.`agg_assault`, 'UTF8') AS INT)             AS agg_assault,
  CAST(CONVERT_FROM(t.violent.`total`, 'UTF8') AS INT)                   AS violent_total,
  CAST(CONVERT_FROM(t.property.`burglary`, 'UTF8') AS INT)               AS burglary,
  CAST(CONVERT_FROM(t.property.`larceny`, 'UTF8') AS INT)                AS larceny,
  CAST(CONVERT_FROM(t.property.`mvt`, 'UTF8') AS INT)                    AS mvt,
  CAST(CONVERT_FROM(t.property.`total`, 'UTF8') AS INT)                  AS property_total,
  CAST(CONVERT_FROM(t.clearances.`murder`, 'UTF8') AS INT)               AS c_murder,
  CAST(CONVERT_FROM(t.clearances.`violent_total`, 'UTF8') AS INT)        AS c_violent,
  CAST(CONVERT_FROM(t.clearances.`property_total`, 'UTF8') AS INT)       AS c_property
FROM hbase.`ucr_crime_monthly` t
;
-- Q1. City Police vs University Police (and other agency types), 2024 -------
--     volume, crime mix and clearance rates
SELECT agency_type,
       COUNT(DISTINCT ori)                                                 AS agencies,
       SUM(violent_total)                                                  AS violent,
       SUM(property_total)                                                 AS property,
       ROUND(100.0 * SUM(violent_total) / SUM(violent_total + property_total), 1) AS violent_share_pct,
       ROUND(100.0 * SUM(larceny)  / SUM(property_total), 1)               AS larceny_share_of_property_pct,
       ROUND(100.0 * SUM(burglary) / SUM(property_total), 1)               AS burglary_share_of_property_pct,
       ROUND(100.0 * SUM(c_violent)  / SUM(violent_total), 1)              AS violent_cleared_pct,
       ROUND(100.0 * SUM(c_property) / SUM(property_total), 1)             AS property_cleared_pct
FROM dfs.tmp.crime
WHERE yr = 2024 AND agency_type IN ('City', 'University', 'County', 'State Police')
GROUP BY agency_type
ORDER BY violent DESC
;
-- Q2. Year-over-year violent-crime trend by state, 2023 -> 2024 --------------
--     only agencies that reported all 24 months (apples-to-apples panel);
--     one scan: aggregate per agency, keep the 24-month ones, then per state
SELECT state,
       SUM(v2023)                                          AS violent_2023,
       SUM(v2024)                                          AS violent_2024,
       ROUND(100.0 * (SUM(v2024) - SUM(v2023)) / SUM(v2023), 1) AS pct_change
FROM (
  SELECT ori, state,
         SUM(CASE WHEN yr = 2023 THEN violent_total ELSE 0 END) AS v2023,
         SUM(CASE WHEN yr = 2024 THEN violent_total ELSE 0 END) AS v2024
  FROM dfs.tmp.crime
  GROUP BY ori, state
  HAVING COUNT(*) = 24
) a
GROUP BY state
HAVING SUM(v2023) >= 1000
ORDER BY pct_change ASC
;
-- Q3. Most active university police departments, 2024 ----------------------
--     NULLIF(...,0): a campus with 0 property offenses would otherwise make the
--     clearance rate divide by zero, which fails the whole query
SELECT agency_name, state,
       SUM(property_total)                                   AS property_offenses,
       SUM(burglary)                                         AS burglaries,
       SUM(larceny)                                          AS larcenies,
       SUM(violent_total)                                    AS violent_offenses,
       ROUND(100.0 * SUM(c_property) / NULLIF(SUM(property_total), 0), 1) AS property_cleared_pct
FROM dfs.tmp.crime
WHERE yr = 2024 AND agency_type = 'University'
GROUP BY agency_name, state
ORDER BY property_offenses DESC
LIMIT 10
;
-- Q4. Seasonality: national violent crime per month, 2023 vs 2024 -----------
--     (same 24-month panel as Q2)
WITH panel AS (
  SELECT ori FROM dfs.tmp.crime GROUP BY ori HAVING COUNT(*) = 24
)
SELECT c.mon AS `month`,
       SUM(CASE WHEN c.yr = 2023 THEN c.violent_total ELSE 0 END) AS violent_2023,
       SUM(CASE WHEN c.yr = 2024 THEN c.violent_total ELSE 0 END) AS violent_2024,
       SUM(CASE WHEN c.yr = 2023 THEN c.murder ELSE 0 END)        AS murder_2023,
       SUM(CASE WHEN c.yr = 2024 THEN c.murder ELSE 0 END)        AS murder_2024
FROM dfs.tmp.crime c JOIN panel p ON c.ori = p.ori
GROUP BY c.mon
ORDER BY c.mon
;
-- Q5. Murder clearance in the largest cities (250k+), 2024 -------------------
SELECT agency_name, state,
       SUM(murder)                                         AS murders,
       SUM(c_murder)                                       AS cleared,
       ROUND(100.0 * SUM(c_murder) / SUM(murder), 1)       AS murder_cleared_pct
FROM dfs.tmp.crime
WHERE yr = 2024 AND pop_bucket = '250k+'
GROUP BY agency_name, state
HAVING SUM(murder) >= 100
ORDER BY murders DESC
LIMIT 15
;
-- Q6. Row-key pushdown: one state's monthly totals via a key-range scan -------
--     (Drill turns the LIKE on the row key into an HBase start/stop-row scan;
--      compare the plan with EXPLAIN PLAN FOR ...)
SELECT yr, mon, COUNT(*) AS agencies, SUM(violent_total) AS violent
FROM dfs.tmp.crime
WHERE rk LIKE 'TX#%'
GROUP BY yr, mon
ORDER BY yr, mon
;
