SELECT count(*) FROM jobs
	WHERE crawl_id = :crawl_id AND (num_starts < 3 OR num_starts IS NULL) AND ended_at IS NULL