# Sample outputs

## 1. Total sales in India for March
**Confidence:** 0.92

```sql
SELECT ROUND(SUM(quantity * unit_price * (1 - discount)), 2) AS revenue
FROM sales
WHERE country = 'India' AND month = '2024-03'
```
| revenue |
|---|
| 108.0 |

**Explanation:** UNDERSTOOD: Aggregate revenue filtered to country in ['India']; period month 2024-03. TERM MAPPING: 'sales' -> metric:revenue; 'time' -> month:2024-03; 'india' -> value:country=India. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 2. Top 2 cities by profit
**Confidence:** 0.92

```sql
SELECT city, ROUND(SUM(profit), 2) AS profit
FROM sales
GROUP BY city
ORDER BY profit DESC, city
LIMIT 2
```
| city | profit |
|---|---|
| New York | 200.0 |
| San Francisco | 180.0 |

**Explanation:** UNDERSTOOD: Rank city by profit (highest first), keep the top 2. TERM MAPPING: 'profit' -> metric:profit; 'cities' -> dimension:city. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 3. Average order value by region
**Confidence:** 0.92

```sql
SELECT region, ROUND(1.0 * (SUM(quantity * unit_price * (1 - discount))) / NULLIF((COUNT(order_id)), 0), 2) AS avg_order_value
FROM sales
GROUP BY region
ORDER BY avg_order_value DESC
```
| region | avg_order_value |
|---|---|
| NA | 1087.47 |
| EMEA | 799.33 |
| APAC | 118.5 |

**Explanation:** UNDERSTOOD: Aggregate avg_order_value grouped by region. TERM MAPPING: 'average order value' -> metric:avg_order_value; 'region' -> dimension:region. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 4. Which region missed its target in Feb?
**Confidence:** 0.92

```sql
WITH tgt AS (
  SELECT region, month, target_revenue FROM targets WHERE month IN ('2024-02')
),
act AS (
  SELECT region, month, SUM(revenue) AS actual FROM sales WHERE month = '2024-02'
  GROUP BY region, month
)
SELECT tgt.region,
       ROUND(COALESCE(SUM(act.actual), 0), 2) AS actual_revenue,
       ROUND(SUM(tgt.target_revenue), 2) AS target_revenue,
       ROUND(COALESCE(SUM(act.actual), 0) - SUM(tgt.target_revenue), 2) AS variance,
       ROUND(100.0 * COALESCE(SUM(act.actual), 0) / NULLIF(SUM(tgt.target_revenue), 0), 2) AS attainment_pct,
       CASE WHEN COALESCE(SUM(act.actual), 0) >= SUM(tgt.target_revenue) THEN 'met' ELSE 'missed' END AS status
FROM tgt LEFT JOIN act ON act.region = tgt.region AND act.month = tgt.month
GROUP BY tgt.region
HAVING COALESCE(SUM(act.actual), 0) < SUM(tgt.target_revenue)
ORDER BY tgt.region
```
| region | actual_revenue | target_revenue | variance | attainment_pct | status |
|---|---|---|---|---|---|
| APAC | 75.0 | 6000.0 | -5925.0 | 1.25 | missed |
| EMEA | 255.0 | 7500.0 | -7245.0 | 3.4 | missed |
| NA | 1116.0 | 9500.0 | -8384.0 | 11.75 | missed |

**Explanation:** UNDERSTOOD: Actual revenue vs target per region (which fell short of target); period month 2024-02. TERM MAPPING: 'region' -> dimension:region; 'time' -> month:2024-02. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 5. Sales contribution % by category
**Confidence:** 0.92

```sql
SELECT product_category, ROUND(SUM(quantity * unit_price * (1 - discount)), 2) AS revenue,
       ROUND(100.0 * SUM(quantity * unit_price * (1 - discount)) / SUM(SUM(quantity * unit_price * (1 - discount))) OVER (), 2) AS contribution_pct
FROM sales
GROUP BY product_category
ORDER BY contribution_pct DESC
```
| product_category | revenue | contribution_pct |
|---|---|---|
| Technology | 5402.0 | 88.06 |
| Furniture | 579.0 | 9.44 |
| Office Supplies | 153.4 | 2.5 |

**Explanation:** UNDERSTOOD: Share (%) of total revenue contributed by each product_category. TERM MAPPING: 'sales' -> metric:revenue; 'category' -> dimension:product_category. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 6. Top product in each region
**Confidence:** 0.84

```sql
WITH g AS (
  SELECT region, product_name, SUM(quantity * unit_price * (1 - discount)) AS value
  FROM sales
  GROUP BY region, product_name
),
r AS (
  SELECT *, RANK() OVER (PARTITION BY region ORDER BY value DESC) AS rnk FROM g
)
SELECT region, product_name, ROUND(value, 2) AS revenue, rnk AS rank
FROM r
WHERE rnk <= 1
ORDER BY region, rnk, product_name
```
| region | product_name | revenue | rank |
|---|---|---|---|
| APAC | Ergo Chair | 324.0 | 1 |
| EMEA | Samsung Galaxy | 1288.0 | 1 |
| NA | Dell XPS | 2068.0 | 1 |

**Explanation:** UNDERSTOOD: Rank product_name by revenue (highest first), keep the top 1 within each region. TERM MAPPING: 'product' -> dimension:product_name; 'region' -> dimension:region. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. ASSUMPTIONS: no metric named; ranked by revenue (sales). Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 7. YoY growth in revenue
**Confidence:** 0.64

```sql
WITH p AS (
  SELECT year AS period, SUM(quantity * unit_price * (1 - discount)) AS value
  FROM sales
  
  GROUP BY year
)
SELECT cur.period,
       ROUND(cur.value, 2) AS revenue, ROUND(prev.value, 2) AS previous_year_revenue,
       ROUND(100.0 * (cur.value - prev.value) / NULLIF(prev.value, 0), 2) AS yoy_growth_pct
FROM p cur LEFT JOIN p prev ON prev.period = CAST(cur.period AS INTEGER) - 1
WHERE 1=1
ORDER BY cur.period
```
| period | revenue | previous_year_revenue | yoy_growth_pct |
|---|---|---|---|
| 2024 | 6134.4 |  |  |

**Explanation:** UNDERSTOOD: Year-over-year growth of revenue by year. TERM MAPPING: 'revenue' -> metric:revenue. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. WARNINGS: column 'previous_year_revenue' is NULL for every row (e.g. no earlier period to compare against); column 'yoy_growth_pct' is NULL for every row (e.g. no earlier period to compare against). CONFIDENCE FACTORS: some output columns are entirely NULL (insufficient data for the calculation). Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).

## 8. Revenue of top 3 customers per region
**Confidence:** 0.92

```sql
WITH g AS (
  SELECT region, customer_id, SUM(quantity * unit_price * (1 - discount)) AS value
  FROM sales
  GROUP BY region, customer_id
),
r AS (
  SELECT *, RANK() OVER (PARTITION BY region ORDER BY value DESC) AS rnk FROM g
)
SELECT region, customer_id, ROUND(value, 2) AS revenue, rnk AS rank,
       ROUND(SUM(value) OVER (PARTITION BY region), 2) AS top_3_total_revenue
FROM r
WHERE rnk <= 3
ORDER BY region, rnk, customer_id
```
| region | customer_id | revenue | rank | top_3_total_revenue |
|---|---|---|---|---|
| APAC | C001 | 324.0 | 1 | 474.0 |
| APAC | C003 | 75.0 | 2 | 474.0 |
| APAC | C006 | 75.0 | 2 | 474.0 |
| EMEA | C008 | 1288.0 | 1 | 2398.0 |
| EMEA | C002 | 855.0 | 2 | 2398.0 |
| EMEA | C005 | 255.0 | 3 | 2398.0 |
| NA | C009 | 2068.0 | 1 | 3262.4 |
| NA | C004 | 1116.0 | 2 | 3262.4 |
| NA | C007 | 78.4 | 3 | 3262.4 |

**Explanation:** UNDERSTOOD: Rank customer_id by revenue (highest first), keep the top 3 within each region. TERM MAPPING: 'revenue' -> metric:revenue; 'customers' -> dimension:customer_id; 'region' -> dimension:region. HOW: A deterministic grammar over the semantic layer translated the question into SQL; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database. Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning).
