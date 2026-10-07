COPY (
SELECT
        BPP.WEBSITE_CRAWL_ID AS "website_crawls.id",
        WC.JOB_ID AS "website_crawls.job_id",
        WC.INDEX_STATUS AS "website_crawls.index_status",
        WC.LANG AS "website_crawls.lang",
        WEBSITES.URL AS "websites.url",

        -- now follows jobs
        JOBS.DOMAIN_STATUS AS "jobs.domain_status",
        JOBS.STARTED_AT AS "jobs.started_at",
        JOBS.ENDED_AT AS "jobs.ended_at",
        JOBS.ADDITIONAL_CRUX_RANKS AS "jobs.crux_popularity",
        JOBS.INDEX_REDIRECT AS "jobs.index_redirect",
        JOBS.NUM_STARTS AS "jobs.num_starts",
        JOBS.FROM_STATIC AS "jobs.from_static",
        JOBS.FROM_DYNAMIC AS "jobs.from_dynamic",
        BPP.CRAWL_ID AS "jobs.crawl_id",
        -- PP
        -- TODO: ID is missing in the view
        BPP.PP_URL_ID AS "crawl_to_privacy.pp_url_id",
        BPP.PP_KW_SCORE AS "crawl_to_privacy.pp_kw_score",
        CPP.PP_PROBABILITY AS "crawl_to_privacy.pp_probability",
        CPP.CONSIDERATION_BASIS AS "crawl_to_privacy.consideration_basis",
        -- URLs
        URLS.URL AS "urls.url",
        URLS.CONTENT_HASH AS "urls.content_hash",
        -- contents
        UC.CONTENT AS "contents.content"
FROM
        BEST_PP_URLS_KW BPP
        LEFT JOIN URLS ON URLS.ID = BPP.PP_URL_ID
        LEFT JOIN URLCONTENTS UC ON UC.HASH = URLS.CONTENT_HASH
        LEFT JOIN WEBSITE_CRAWLS WC ON WC.ID = BPP.WEBSITE_CRAWL_ID
        LEFT JOIN JOBS ON JOBS.ID = WC.JOB_ID
        LEFT JOIN WEBSITES ON WC.WEBSITE_ID = WEBSITES.ID
        LEFT JOIN CRAWL_TO_PRIVACY_POLICY CPP ON CPP.PP_URL_ID = URLS.ID
        AND CPP.WEBSITE_CRAWL_ID = WC.ID
WHERE
        BPP.CRAWL_ID = 'REPLACE_THIS_CRAWL_ID'
ORDER BY
        BPP.WEBSITE_CRAWL_ID
) TO stdout DELIMITER ',' CSV HEADER

