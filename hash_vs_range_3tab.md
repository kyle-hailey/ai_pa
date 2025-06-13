==============================
Report

Your input query:

```sql
explain (analyze, dist) SELECT *
FROM customers_tmp c
JOIN orders_tmp o ON c.id = o.customer_id
JOIN products_tmp p ON o.id = p.id
WHERE o.date > '2024-01-15'
 AND p.category = 'Shoes';
Problem Detected:
This query uses a range predicate (o.date > '2024-01-15') and the explain plan shows sequential scan on the orders_tmp table without a supporting ASC index. The date field is not the primary key, so this requires investigation of secondary indexing rather than tablet partitioning.
YugabyteDB Partitioning Model:

YugabyteDB partitions tables into tablets.
By default, tables are HASH partitioned on primary keys for even write distribution but inefficient range access.
RANGE partitioning (PRIMARY KEY(field ASC)) keeps rows ordered but may create write hotspots for sequential inserts.

Common query problem:

Queries using range predicates or ORDER BY on hash-partitioned tables often trigger sequential scans, even when only a small key range is needed.
The lack of ordered storage leads to full table scans.

Proposed Solutions:
Solution 1 - Add Secondary ASC Index
Creating an ASC index to optimize the query:
sqlCREATE INDEX orders_tmp_date_idx ON orders_tmp (date ASC);
This allows efficient range scans. Drawbacks include write overhead and potential hotspots on monotonically increasing keys.

Solution 2 - Repartition Table to Range Partitioning
N/A - The date field is not the primary key, so repartitioning the table is not recommended. Secondary indexing is the appropriate solution for non-primary key range predicates.

Solution 3 - Use Secondary Index with Bucket ID
Propose adding virtual bucketing to secondary index:
sqlCREATE INDEX orders_tmp_bucket_idx ON orders_tmp (
  (yb_hash_code(date) % 3) ASC, 
  date ASC
);
Queries with range predicates like < and > can be run without modification.
Queries with Order by would need to UNION ALL across buckets in order to take advantages of efficiencies with bucketid.
sqlSELECT * FROM (
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 0 ORDER BY date ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 1 ORDER BY date ASC LIMIT 3)
 UNION ALL
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 2 ORDER BY date ASC LIMIT 3)
) AS combined
ORDER BY date ASC LIMIT 3;
This reduces hotspots while retaining the original table structure, but requires modifying queries for ORDER BY.

Solution 4 - Modify Table Primary Key to Include Bucket ID
N/A - The date field is not the primary key, so modifying the primary key structure is not recommended for this specific range predicate issue. Secondary indexing solutions are more appropriate.

Additional Notes:

The query also has a potential data modeling issue: the join condition o.id = p.id suggests that order IDs are being matched to product IDs, which may not represent the intended business relationship. Consider if there should be a product_id field in the orders table instead.
The products table also shows a storage filter on category = 'Shoes', which could benefit from an index on the category column if this type of filtering is common.


Conclusion:
For the range predicate on the date field (which is not a primary key):

Secondary indexes are the most appropriate solution and simplest to implement.
Bucketed indexes can reduce hotspots but complicate ORDER BY queries.
Since the date field is not the primary key, table repartitioning and primary key modifications are not applicable for this specific optimization.

The recommended approach is to start with Solution 1 (simple secondary ASC index) and monitor performance, moving to Solution 3 (bucketed index) only if write hotspots become an issue with sequential date inserts.
==============================
