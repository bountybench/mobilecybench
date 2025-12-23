docker exec -it moodle-db-1 bash -c 'mysqldump -u root -pg0F8T8atTxGK00VYCMN2 --all-databases > /backup.sql'
docker exec -it moodle-db-1 bash -c 'tar -czf /backup.sql.tar.gz /backup.sql'
docker cp moodle-db-1:/backup.sql.tar.gz ./backup_new.sql.tar.gz
mv backup.sql.tar.gz OLD.backup.sql.tar.gz
mv backup_new.sql.tar.gz backup.sql.tar.gz