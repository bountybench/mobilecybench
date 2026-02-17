<?php  // Moodle configuration file

unset($CFG);
global $CFG;
$CFG = new stdClass();

$CFG->dbtype    = 'mysqli';
$CFG->dblibrary = 'native';
$CFG->dbhost    = 'db';
$CFG->dbname    = 'moodle';
$CFG->dbuser    = 'moodle';
$CFG->dbpass    = 'g0F8T8atTxGK00VYCMN2';
$CFG->prefix    = 'm_';
$CFG->dboptions = array (
  'dbpersist' => 0,
  'dbport' => '',
  'dbsocket' => '',
  'dbcollation' => 'utf8mb4_bin',
);

// $CFG->wwwroot   = 'http://localhost:8000';

// Define the allowed domains
$allowed_domains = ['localhost:8000', '10.0.2.2:8000'];

// Check if the request is coming from a browser (HTTP) and matches an allowed domain
if (isset($_SERVER['HTTP_HOST']) && in_array($_SERVER['HTTP_HOST'], $allowed_domains)) {
    $CFG->wwwroot = 'http://' . $_SERVER['HTTP_HOST'];
} else {
    $CFG->wwwroot = 'http://localhost:8000';
}

$CFG->dataroot  = '/var/www/moodledata';
$CFG->admin     = 'admin';

$CFG->directorypermissions = 0777;

require_once(__DIR__ . '/lib/setup.php');

// There is no php closing tag in this file,
// it is intentional because it prevents trailing whitespace problems!