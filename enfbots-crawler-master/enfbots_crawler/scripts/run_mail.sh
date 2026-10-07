#!/bin/bash

while [ 1 ]; 
do
    python /crawler/enfbots_crawler/scripts/mail_confirm.py -d 2>&1 | tee -a /crawler/enfbots_mail.log
    sleep 30
done