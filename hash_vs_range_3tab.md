Report

Your input query:

SELECT *
FROM customers_tmp c
JOIN orders_tmp o ON c.id = o.customer_id
JOIN products_tmp p ON o.id = p.id
WHERE o.date > '2024-01-15'
  AND p.category = 'Shoes';

Problem Detected:

This query uses a range predicate on the 'date' field of the 'orders_tmp' table. The 'orders_tmp' table is hash-partitioned and the explain plan shows a sequential scan on this table, which suggests that there is no ordered 'ASC' index to support efficient access to the required range of data.

YugabyteDB Partitioning Model:

- YugabyteDB partitions tables into tablets.
- By default, tables are HASH partitioned on primary keys for even write distribution but inefficient range access.
- RANGE partitioning (PRIMARY KEY(field ASC)) keeps rows ordered but may create write hotspots for sequential inserts.

Common query problem:

- Queries using range predicates or ORDER BY on hash-partitioned tables often trigger sequential scans, even when only a small key range is needed,
- The lack of ordered storage leads to full table scans.


Proposed Solutions:

Solution 1 - Add Secondary ASC Index

To optimize the query, you can create an 'ASC' index on the 'date' field of the 'orders_tmp' table:

CREATE INDEX orders_tmp_date_idx ON orders_tmp (date ASC);

This allows efficient range scans on the 'date' field. However, the drawbacks include write overhead and potential hotspots on monotonically increasing keys.


Solution 2 - Repartition Table to Range Partitioning

Another solution is to recreate the 'orders_tmp' table with an 'ASC' primary key on the 'date' field so that data is directly stored in an ordered manner:

CREATE TABLE orders_tmp_v2 (
   id SERIAL PRIMARY KEY,
   customer_id INT REFERENCES customers_tmp(id),
   date DATE,
   PRIMARY KEY (date ASC)
) SPLIT INTO 4 TABLETS;

This will avoid full table scans for range queries, but may cause write hotspots, and recreating large tables can be operationally difficult.


Solution 3 - Use Secondary Index with Bucket ID

You can also add virtual bucketing to secondary index:

CREATE INDEX orders_tmp_bucket_idx ON orders_tmp (
  (yb_hash_code(date) % 3) ASC, 
  date ASC
);

Queries with range predicates like 'date > value' will still run efficiently without modification. However, viewing ordered data would require using 'UNION ALL' across buckets, which can be complex.


Solution 4 - Modify Table Primary Key to Include Bucket ID

Modifying the base table schema to include 'bucketid' directly in the primary key also reduces hotspots but requires a complete rebuild of the table:

CREATE TABLE orders_tmp_v3 (
   id SERIAL,
   customer_id INT REFERENCES customers_tmp(id),
   date DATE,
   bucketid smallint DEFAULT ((random()*10)::int % 3), 
   PRIMARY KEY (bucketid ASC, id ASC)
) SPLIT INTO 3 TABLETS;

For an Order by, you would need to UNION ALL across buckets.

Conclusion:

Each proposed solution has its own trade-offs: 
- Secondary indexes are simplest to implement but can introduce write overhead and potential hotspots. 
- Bucketed indexes reduce these hotspots but may complicate ORDER BY queries. 
- Repartitioning tables is ideal for pure range workloads but requires downtime or ETL reload. You should choose the solution most suited to your specific circumstances. 
