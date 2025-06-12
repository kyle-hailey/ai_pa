Report

Your input query:

```sql
SELECT *
FROM customers_tmp c
JOIN orders_tmp o ON c.id = o.customer_id
JOIN products_tmp p ON o.id = p.id
WHERE o.date > '2024-01-15'
  AND p.category = 'Shoes';
```
Problem Detected:

Explain that this query uses a range predicate and/or ORDER BY. The explain plan shows sequential scan on a hash-partitioned table without a supporting ASC index.

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

```sql 
CREATE INDEX orders_tmp_date_idx ON orders_tmp (date ASC);
```

Explain that this allows efficient range scans. Drawbacks include write overhead and potential hotspots on monotonically increasing keys.

---

Solution 2 - Repartition Table to Range Partitioning

Propose recreating the table with ASC primary key to directly store data ordered by key:

```sql 
CREATE TABLE orders_tmp_v2 (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers_tmp(id),
    date DATE,
    PRIMARY KEY (date ASC)
) SPLIT INTO 10 TABLETS;
```

Explain that this avoids full scans for range queries but may cause write hotspots. Mention that recreating large tables can be operationally difficult.

---

Solution 3 - Use Secondary Index with Bucket ID

Propose adding virtual bucketing to secondary index:

```sql
CREATE INDEX orders_bucket_idx ON orders_tmp (
  (yb_hash_code(date) % 3) ASC, 
  date ASC
);
```

Queries with range predicates like < and > can be run without modification.
Queries with Order by would need to UNION ALL across buckets in order to take advantages of efficiencies with bucketid.

```sql
SELECT * FROM (
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 0 ORDER BY date ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 1 ORDER BY date ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 2 ORDER BY date ASC LIMIT 3)
) AS combined
ORDER BY date ASC LIMIT 3;
```

Explain that this reduces hotspots while retaining the original table structure, but requires modifying queries for ORDER BY.

---

Solution 4 - Modify Table Primary Key to Include Bucket ID

Propose modifying the base table schema to include bucket_id directly in the main storage primary key:

```sql
CREATE TABLE orders_tmp_v3 (
   id SERIAL,
   customer_id INT REFERENCES customers_tmp(id),
   date DATE,
   bucketid smallint DEFAULT ((random()*10)::int % 3), 
   PRIMARY KEY (bucketid ASC, date ASC)
) SPLIT INTO 3 TABLETS;
```

Queries with range predicates like < and > can be run without modification.
Queries with Order by would need to UNION ALL across buckets in order to take advantages of efficiencies with bucketid.

```sql
SELECT * FROM (
   (SELECT * FROM orders_tmp_v3 WHERE bucketid = 0  ORDER BY date ASC LIMIT 3)
   UNION ALL
   (SELECT * FROM orders_tmp_v3 WHERE bucketid = 1 ORDER BY date ASC LIMIT 3)
   UNION ALL
   (SELECT * FROM orders_tmp_v3 WHERE bucketid = 2 ORDER BY date ASC LIMIT 3)
) AS combined
ORDER BY date ASC LIMIT 3;
```

Explain that this reduces hotspots but requires full table rebuild and query rewrites.

---

Conclusion:

Summarize the trade-offs:
- Secondary indexes are simplest but may introduce write overhead and hotspots.
- Bucketed indexes reduce hotspots but complicate ORDER BY queries.
- Repartitioning tables is ideal for pure range workloads but requires downtime or ETL reload.
