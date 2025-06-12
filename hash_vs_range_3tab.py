import os
from openai import OpenAI


# Initialize client correctly
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

schema = """
CREATE TABLE customers_tmp (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    age INT
);

CREATE TABLE orders_tmp (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers_tmp(id),
    date DATE
);

CREATE TABLE products_tmp (
    id SERIAL PRIMARY KEY,
    product_name VARCHAR(100),
    category VARCHAR(50)
);
"""

query = """
explain (analyze, dist) SELECT *
FROM customers_tmp c
JOIN orders_tmp o ON c.id = o.customer_id
JOIN products_tmp p ON o.id = p.id
WHERE o.date > '2024-01-15'
  AND p.category = 'Shoes';
"""

explain_plan = """
                                                                    QUERY PLAN                                                                     
---------------------------------------------------------------------------------------------------------------------------------------------------
 YB Batched Nested Loop Join  (cost=0.00..329.83 rows=1000 width=578) (actual time=2.570..2.572 rows=0 loops=1)
   Join Filter: (o.id = p.id)
   ->  YB Batched Nested Loop Join  (cost=0.00..200.83 rows=1000 width=238) (actual time=1.045..1.097 rows=73 loops=1)
         Join Filter: (c.id = o.customer_id)
         ->  Seq Scan on orders_tmp o  (cost=0.00..102.50 rows=1000 width=12) (actual time=0.539..0.547 rows=73 loops=1)
               Storage Filter: (date > '2024-01-15'::date)
               Storage Table Read Requests: 1
               Storage Table Read Execution Time: 0.452 ms
               Storage Table Rows Scanned: 103
         ->  Index Scan using customers_tmp_pkey on customers_tmp c  (cost=0.00..0.11 rows=1 width=226) (actual time=0.419..0.439 rows=73 loops=1)
               Index Cond: (id = ANY (ARRAY[o.customer_id, $1, $2, ..., $1023]))
               Storage Table Read Requests: 1
               Storage Table Read Execution Time: 0.277 ms
               Storage Table Rows Scanned: 73
   ->  Index Scan using products_tmp_pkey on products_tmp p  (cost=0.00..0.12 rows=1 width=340) (actual time=1.412..1.412 rows=0 loops=1)
         Index Cond: (id = ANY (ARRAY[o.id, $1025, $1026, ..., $2047]))
         Storage Filter: ((category)::text = 'Shoes'::text)
         Storage Table Read Requests: 1
         Storage Table Read Execution Time: 1.272 ms
         Storage Table Rows Scanned: 73
 Planning Time: 0.870 ms
 Execution Time: 3.009 ms
 Storage Read Requests: 3
 Storage Read Execution Time: 2.001 ms
 Storage Rows Scanned: 249
 Storage Write Requests: 0
 Catalog Read Requests: 0
 Catalog Write Requests: 0
 Storage Flush Requests: 0
 Storage Execution Time: 2.001 ms
 Peak Memory Usage: 1035 kB
"""

context = """
You are a PostgreSQL query tuning expert working on YugabyteDB distributed SQL.

Your job is to analyze queries that may have range predicates and ORDER BY clauses running inefficiently on hash-partitioned tables. You will be given:
- SQL statement
- Explain plan output
- Table schema

The main problem occurs when:
- The query contains WHERE predicates like: field > value, field < value, field BETWEEN value1 AND value2, or ORDER BY field.
- The table is hash-partitioned.
- The explain plan shows sequential scans.
- There is no ASC index to support the range predicate or ORDER BY.
- If there *is* an ASC index, but a sequential scan still occurs, indicate that this suggests a problem in query planner or index usability.

---

format all SQL code  with ```sql notation

Don't not modify "(yb_hash_code(field) % 3) ASC," in the report. Use this string exactly "(yb_hash_code(field) % 3) ASC,"
Don't not modify "LIMIT 3 ASC," in the report. Use this string exactly "(yb_hash_code(field) % 3) ASC,"

Emphasize that queries using range predicates like > or <  can be run without any changes. 
Only generate the "UNION ALL" examples for the table that is used in the  range scan or order by 

Always give all 4 solutions. All 4 solutions always apply for range predicate filters
Only give solutions for the table used in the range predicate filters or order by
Avoid giving solutions for tables uses in equality joins and equality predicate filters

---

You must always generate your output following this report format:

==============================
Report

Your input query:

{SQL_STATEMENT}

Problem Detected:

This query uses a range predicate and/or ORDER BY. The explain plan shows sequential scan on a hash-partitioned table without a supporting ASC index.

YugabyteDB Partitioning Model:

- YugabyteDB partitions tables into tablets.
- By default, tables are HASH partitioned on primary keys for even write distribution but inefficient range access.
- RANGE partitioning (PRIMARY KEY(field ASC)) keeps rows ordered but may create write hotspots for sequential inserts.

Common query problem:

- Queries using range predicates or ORDER BY on hash-partitioned tables often trigger sequential scans, even when only a small key range is needed.
- The lack of ordered storage leads to full table scans.

Proposed Solutions:

Solution 1 - Add Secondary ASC Index

Propose creating an ASC index to optimize the query:

CREATE INDEX table_field_idx ON table_name (field ASC);

This allows efficient range scans. Drawbacks include write overhead and potential hotspots on monotonically increasing keys.

---

Solution 2 - Repartition Table to Range Partitioning

Propose recreating the table with ASC primary key to directly store data ordered by key:

CREATE TABLE table_v2 (
   id bigint GENERATED BY DEFAULT AS IDENTITY,
   car varchar,
   speed int,
   ts timestamp,
   PRIMARY KEY (id ASC)
) SPLIT INTO N TABLETS;

This avoids full scans for range queries but may cause write hotspots. Mention that recreating large tables can be operationally difficult.

---

Solution 3 - Use Secondary Index with Bucket ID

Propose adding virtual bucketing to secondary index:

CREATE INDEX table_bucket_idx ON table_name (
  (yb_hash_code(field) % 3) ASC, 
  field ASC
);


Queries with range predicates like < and > can be run without modification.
Queries with Order by would need to UNION ALL across buckets in order to take advantages of efficiencies with bucketid.


SELECT * FROM (
 (SELECT * FROM table_name WHERE yb_hash_code(field) % 3 = 0 ORDER BY id ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM table_name WHERE yb_hash_code(field) % 3 = 1 ORDER BY id ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM table_name WHERE yb_hash_code(field) % 3 = 2 ORDER BY id ASC LIMIT 3)
) AS combined
ORDER BY field ASC LIMIT 3;

This reduces hotspots while retaining the original table structure, but requires modifying queries for ORDER BY.

---

Solution 4 - Modify Table Primary Key to Include Bucket ID

Propose modifying the base table schema to include bucket_id directly in the primary key:

CREATE TABLE table_v3 (
   id bigint GENERATED BY DEFAULT AS IDENTITY,
   car varchar,
   speed int,
   ts timestamp,
   bucketid smallint DEFAULT ((random()*10)::int % 3), 
   PRIMARY KEY (bucketid ASC, id ASC)
) SPLIT INTO 3 TABLETS;

Queries with range predicates like < and > can be run without modification.
Queries with Order by would need to UNION ALL across buckets in order to take advantages of efficiencies with bucketid.

 
SELECT * FROM (
 (SELECT * FROM table_v3 WHERE bucketid = 0  ORDER BY id ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM table_v3 WHERE bucketid = 1 ORDER BY id ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM table_v3 WHERE bucketid = 2 ORDER BY id ASC LIMIT 3)
) AS combined
ORDER BY id ASC LIMIT 3;

This reduces hotspots but requires full table rebuild and query rewrites.

---

Conclusion:

Summarize the trade-offs:
- Secondary indexes are simplest but may introduce write overhead and hotspots.
- Bucketed indexes reduce hotspots but complicate ORDER BY queries.
- Repartitioning tables is ideal for pure range workloads but requires downtime or ETL reload.
==============================

Always output the full SQL examples for each solution.
If any solution is not applicable based on explain plan and schema, write 'N/A' for that section.
"""



prompt = f"""

You are a postgres performance expert. Here you will be analyzing a postgres comaptibale database Yugabyte.

Please review and optimize the following PostgreSQL sql query based on the schema definition and explain plan.

Here is the query: {query}
Here is the schema of the table: {schema}
Here is the explain plan for the query were are running:  {explain_plan}


{context}

Output the example SQL from customer at the beginning of report
"""

response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a PostgreSQL query tuning expert."},
        {"role": "user", "content": prompt}
    ]
)

print(response.choices[0].message.content)

