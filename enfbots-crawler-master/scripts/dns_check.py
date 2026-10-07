import re
from pathlib import Path
from hyperlink import URL
from enfbots_crawler.main import ns_lookup
from pqdm.processes import pqdm

list = Path("/home/lukal/enfbots_2022_06_public_websites.csv")


def check_domain(url):
    url = URL.from_text(url.strip())
    res = ns_lookup(url.host, "@8.8.8.8")
    if res and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", res[-1]):
        print(url, res[-1])
        return 1
    return 0


domains = []
for line in list.open():
    domains.append(line.strip())

for d in domains:
    check_domain(d)
# parallelize checkdomain on domains
#result = sum(pqdm(domains, check_domain, n_jobs=16))
#print(result, len(domains), result / len(domains))