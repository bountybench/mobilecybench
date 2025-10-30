#!/bin/bash
# Simple check of what Flexisip actually sees

echo "=== What Flexisip Configuration Sees ==="
echo ""
echo "SQL Query line:"
docker exec flexisip cat /etc/flexisip/flexisip.conf | grep "^soci-password-request"
echo ""
echo "DB Connection line:"
docker exec flexisip cat /etc/flexisip/flexisip.conf | grep "^soci-connection-string"
echo ""
echo "Authentication enabled:"
docker exec flexisip cat /etc/flexisip/flexisip.conf | grep -A 3 "^\[module::Authentication\]" | grep "^enabled"
echo ""
echo "=== Last 50 lines of log ==="
docker logs flexisip --tail 200