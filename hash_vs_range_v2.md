

Report

Your input query:

```sql
select * from hash_vs_range where id > 1 and id < 4;
```

Problem Detected:

This query uses a range predicate on the id field. According to the explain plan, a sequential scan was performed on the hash-partitioned table `hash_vs_range`. As there is no ASC index on the id field, these range queries can lead to inefficient full table scans.

Proposed Solutions:

Solution 1 - Add Secondary ASC Index

We can create an ASC index to optimize the query:

```sql
CREATE INDEX hash_vs_range_id_idx ON hash_vs_range(id ASC);
```

This index allows the database to efficiently scan only the necessary range of the id field, avoiding full table scans. However, it introduces the overhead of maintaining the index during writes and may create write hotspots if the id values increase monotonically.

---

Solution 2 - Repartition Table to Range Partitioning

Another option is to create a new version of the table with an ASC primary key:

```sql
CREATE TABLE hash_vs_range_v2 (
   id bigint GENERATED BY DEFAULT AS IDENTITY,
   car varchar,
   speed int,
   ts timestamp,
   PRIMARY KEY (id ASC)
) SPLIT INTO 3 TABLETS;
```

This will make the id field stored in order, which will improve the performance of these kinds of range queries. It reduces the likelihood of full table scans but may result in uneven data distribution causing write hotspots. However, migrating data to a new table can be operationally challenging for large tables.

---

Solution 3 - Use Secondary Index with Bucket ID

Creating a secondary index with virtual bucketing may alleviate the hotspot problem while retaining query efficiency:

```sql
CREATE INDEX hash_vs_range_bucket_idx ON hash_vs_range (
  (yb_hash_code(id) % 3) ASC, 
  id
);
```

However, this approach requires modifying the original query:

```sql
SELECT * FROM (
  (SELECT * FROM hash_vs_range WHERE yb_hash_code(id) % 3 = 0 AND id > 1 AND id < 4 ORDER BY id ASC)
  UNION ALL
  (SELECT * FROM hash_vs_range WHERE yb_hash_code(id) % 3 = 1 AND id > 1 AND id < 4 ORDER BY id ASC)
  UNION ALL
  (SELECT * FROM hash_vs_range WHERE yb_hash_code(id) % 3 = 2 AND id > 1 AND id < 4 ORDER BY id ASC)
) AS combined
ORDER BY id ASC;
```
---

Solution 4 - Modify Table Primary Key to Include Bucket ID

Modifying the base table schema to include `bucket_id` directly in the primary key:

```sql
CREATE TABLE hash_vs_range_v3 (
   id bigint GENERATED BY DEFAULT AS IDENTITY,
   car varchar,
   speed int,
   ts timestamp,
   bucketid smallint DEFAULT ((random()*10)::int % 3), 
   PRIMARY KEY (bucketid ASC, id ASC)
) SPLIT INTO 3 TABLETS;
```

Queries would be rewritten as:

```sql
 (SELECT * FROM hash_vs_range_v3 WHERE bucketid = 0 AND id > 1 AND id < 4 ORDER BY id ASC)
 UNION ALL
 (SELECT * FROM hash_vs_range_v3 WHERE bucketid = 1 AND id > 1 AND id < 4 ORDER BY id ASC)
 UNION ALL
 (SELECT * FROM hash_vs_range_v3 WHERE bucketid = 2 AND id > 1 AND id < 4 ORDER BY id ASC)
) AS combined
ORDER BY id ASC;
```

This approach requires a full table rebuild and rewriting the original query.

---

Conclusion:

The best solution depends on the specific use case:
- Adding a secondary index is the simplest solution but may introduce write overhead.
- Repartitioning the table into range partitions is efficient for range queries but may cause write hotspots and requires significant operational effort.
- Using a bucketed index or modifying the table to include a bucket id in the primary key can help balance the load, but complicates queries and may require rewriting the application's SQL queries.


