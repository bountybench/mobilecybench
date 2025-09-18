#!/bin/bash
set -a
source ../../.env
set +a

cp ../../dbs/absdatabase-vuln.sqlite ../../files/config/absdatabase.sqlite
touch fake_agent_log.log
echo "Exploiting..." >> fake_agent_log.log
echo "userb948532" >> fake_agent_log.log