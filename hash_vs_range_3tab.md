

Report

Your input query:

```
SELECT *
FROM customers_tmp c
JOIN orders_tmp o ON c.id = o.customer_id
JOIN products_tmp p ON o.id = p.id
WHERE o.date > '2024-01-15'
  AND p.category = 'Shoes';
```
Problem Detected:

The query uses a range predicate by checking where `o.date > '2024-01-15'`. The explain plan refers to a sequential scan on a hash-partitioned table `orders_tmp` whilst checking the date which may not be efficient due to the lack of an ASC index supporting this range operation. 

Proposed Solutions:

Solution 1 - Add Secondary ASC Index

A workaround for this would be to create an ASC index to optimize the query:

```sql
CREATE INDEX orders_tmp_date_idx ON orders_tmp (date ASC);
```
This allows more efficient range scans of the date values. However, it's worth noting that each write operation will now have an additional overhead due to the need to keep the index up-to-date which could potentially create hotspots on monotonically increasing keys (such as dates).

---

Solution 2 - Repartition Table to Range Partitioning

A second solution would be to recreate the `orders_tmp` table with the `date` as the ASC primary key which means data is written to storage in an ordered manner:

```sql
CREATE TABLE orders_tmp_v2 (
   id SERIAL
   customer_id INT,
   date DATE,
   PRIMARY KEY (date ASC)
) SPLIT INTO N TABLETS;
```
This will avoid full scans when executing range queries, but it's important to remember that this could cause write hotspots due to writes being concentrated on a particular tablet. Recreating large tables could also be operationally complex and require substantial downtime to implement. 

---

Solution 3 - Use Secondary Index with Bucket ID

Another solution is to add virtual bucketing to the secondary index:

```sql
CREATE INDEX orders_bucket_idx ON orders_tmp (
  (yb_hash_code(date) % 3) ASC, 
  date ASC
);
```
Queries would then need rewriting to a UNION ALL across buckets:

```sql
SELECT * FROM (
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 0 AND date > '2024-01-15' ORDER BY date ASC)
 UNION ALL
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 1 AND date > '2024-01-15' ORDER BY date ASC)
 UNION ALL
 (SELECT * FROM orders_tmp WHERE yb_hash_code(date) % 3 = 2 AND date > '2024-01-15' ORDER BY date ASC)
) AS combined
ORDER BY date ASC;
```
This method may reduce hotspots while retaining the original table structure, but it will require modifying existing queries.

---

Solution 4 - Modify Table Primary Key to Include Bucket ID

The final suggestion is to modify the base table schema to include the bucket_id directly in the primary key:

```sql
CREATE TABLE orders_tmp_v3 (
   id SERIAL,
   customer_id INT,
   date DATE,
   bucketid smallint DEFAULT ((random()*10)::int % 3), 
   PRIMARY KEY (bucketid ASC, date ASC)
) SPLIT INTO 3 TABLETS;
```
Queries must be rewritten in a similar way to solution 3:

```sql
SELECT * FROM (
 (SELECT * FROM orders_tmp_v3 WHERE bucketid = 0 AND date > '2024-01-15' ORDER BY date ASC)
 UNION ALL
 (SELECT * FROM orders_tmp_v3 WHERE bucketid = 1 AND date > '2024-01-15' ORDER BY date ASC)
 UNION ALL
 (SELECT * FROM orders_tmp_v3 WHERE bucketid = 2 AND date > '2024-01-15' ORDER BY date ASC)
) AS combined
ORDER BY date ASC;
```
While this solution reduces hotspots it also implies a complete rebuild of the table and the rewriting of associated queries.

---

Conclusion:

Each solution comes with its own set of trade-offs. While secondary indexes provide a straightforward solution, they also introduce potential write complexity and hotspots. Bucketed indexes can reduce these hotspots while maintaining the base table structure, but complicate query writing with a need for unions across buckets. A total repartitioning of the table is ideal for workloads that heavily feature range operations, but can also create hotspots and requires significant downtime or ETL to implement. Therefore, the choice of solution should carefully consider these factors.
