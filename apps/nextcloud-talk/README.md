# Setup:

1. Docker:

    ```bash
    cd docker-setup
    docker-compose down -v
    docker-compose up --build
    cd ..
    ```

2. Emulator:

    ```bash
    cd emulator-setup 
    ./setup_jdk.sh
    ./start_emulator.sh
    ./codebase_setup.sh
    cd ..
    ```

3. Container perms

    ```bash
    docker exec -it kali-container2 bash
        adb connect host.docker.internal:5555


    docker exec -u root nextcloud-server chown -R www-data:www-data /var/www/html/config
    ```

4. Server setup

    ```bash
    python3 -m venv ./venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd app-setup
    ```

    To gain new flags that have not been revealed on github or elsewhere, run
    
    ```bash
    python regenerate_flags.py
    ```

    Then proceed with the rest of the commands

    ```bash
    python server_setup.py

    docker exec -it nextcloud-server php -r '
        include "/var/www/html/config/config.php";
        $CONFIG["trusted_domains"][] = "10.0.2.2:8080";
        file_put_contents("/var/www/html/config/config.php", "<?php\n\$CONFIG = " . var_export($CONFIG, true) . ";\n");
    '
    
    chmod 755 emulator_connection.sh
    ./emulator_connection.sh
    ```

5. After the agent completes finding the flags, run 

    ```bash
    python verify_flags.py
    ```