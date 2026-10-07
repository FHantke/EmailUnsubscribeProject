select (1.0 * (
	select count(*) from jobs
		where ended_at is not NULL and 
		crawl_id = :crawl_id and
	    num_starts < 3))/(
select count(*) from jobs
		where crawl_id = :crawl_id and (num_starts < 3 or num_starts is NULL)) as progress_percent

