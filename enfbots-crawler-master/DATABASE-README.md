# Database Structure

Database is managed by SQLAlchemy. 

For a good overview over all tables and relationships there is `./doc/database/ERM.pdf`.

Below, we explain each table in the database and its purpose:
* [cookie:] All cookies found during crawling on a specific website will be stored in this table for further analysis. 
* [form:] Represents a single form that we tried to submit to 
* [input:] Represents a single input of a form
* [jobs:] Contains a list of domain scheduled to crawl
* [website:] Each crawled website is stored in this relation together with the detected captchas and other details like a successful registration validation


# Stats

## Amount of PP/TC links per consideration_basis
```SQL
SELECT pps.consideration_basis, number_of_privacy_policies, number_of_terms_and_conditions FROM (SELECT coalesce(consideration_basis, 'NONE') AS consideration_basis, count(*) AS number_of_privacy_policies FROM best_pp_urls_kw
WHERE crawl_id = 'regular-2024-02'
GROUP BY consideration_basis) pps
LEFT JOIN (SELECT coalesce(consideration_basis, 'NONE') AS consideration_basis, count(*) AS number_of_terms_and_conditions FROM best_tc_urls_kw
WHERE crawl_id = 'regular-2024-02'
GROUP BY consideration_basis) sub ON sub.consideration_basis = pps.consideration_basis
```

## Amount of jobs
```SQL
SELECT count(*) FROM jobs j
WHERE j.crawl_id = 'regular-2024-04' AND NOT J.index_redirect
```

## Amount of website_crawls
```SQL
SELECT count(*) FROM Website_crawls wc
JOIN jobs j ON J.Id = wc.job_id
WHERE j.crawl_id = 'regular-2024-04' AND NOT J.index_redirect
```

## Amount of each index_status for one crawl_id
``` SQL
-- count amount of status' of website_crawls; count all error types
SELECT index_status, count(*) FROM website_crawls wc
	JOIN jobs j ON j.id = wc.job_id
	WHERE j.crawl_id = 'regular-2024-04'
	GROUP BY index_status
	ORDER BY index_status
```