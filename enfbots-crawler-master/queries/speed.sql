select (1.0 * (select count(*) from jobs
where ended_at BETWEEN NOW()::timestamp - '1 hours'::interval AND NOW() AND crawl_id = :crawl_id)/60.0)
