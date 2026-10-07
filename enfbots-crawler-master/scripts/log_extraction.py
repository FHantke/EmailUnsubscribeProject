import os
import re
from glob import glob
from tqdm import tqdm

dirs = glob("/output/*/")

domain_re = re.compile("/output/(.*?)_.*")
with open("/concat.log", "w") as outf:
    for i, dir in tqdm(enumerate(dirs)):
        matches = domain_re.match(dir)
        if matches:
            domain = matches.group(1).strip()
            filename = os.path.join(dir, "crawler.log")
            if os.path.exists(filename):
                with open(filename) as f:
                    for line in f:
                        if line.strip():
                            outf.write(f"[{domain}] {line}")


# \[%{DATA:domain}\] %{DATA:timestamp_in;date;y-M-d:HH:mm:ss,SSS} %{DATA:name} %{LOGLEVEL:level} %{SPACE}\[%{DATA:source_file}\] %{GREEDYDATA:text}


# filebeat.config:
#   modules:
#     path: ${path.config}/modules.d/*.yml
#     reload.enabled: false

# output.logstash:
#   hosts: ["graylog:5044"]

# filebeat.inputs:
# - type: log
#   paths:
#     - /usr/share/filebeat/logs_aa
#     - /usr/share/filebeat/logs_ab
#     - /usr/share/filebeat/logs_ac
#     - /usr/share/filebeat/logs_ad
#     - /usr/share/filebeat/logs_ae
#     - /usr/share/filebeat/logs_af
#     - /usr/share/filebeat/logs_ag
#     - /usr/share/filebeat/logs_ah
#     - /usr/share/filebeat/logs_ai
#     - /usr/share/filebeat/logs_aj
#   close_eof: true
#   multiline.type: pattern
#   multiline.pattern: '^\['
#   multiline.negate: true
#   multiline.match: after


#docker run --name=filebeat --user=root --volume="crawling_output:/output" --network="graylog_graylog" -it docker.elastic.co/beats/filebeat:7.16.2 bash