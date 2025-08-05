FROM cybench/kali-linux-base:latest

# Install common tools, Python 3.10, Docker, and pytest
RUN apt-get update && \
    apt-get install -y \
    docker.io \
    curl \
    unzip \
    wget \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libgdbm-dev \
    libdb5.3-dev \
    libbz2-dev \
    libexpat1-dev \
    liblzma-dev \
    tk-dev \
    libffi-dev \
    git \
    android-tools-adb \
    android-tools-fastboot && \
    wget https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz && \
    tar xzf Python-3.10.14.tgz && \
    cd Python-3.10.14 && \
    ./configure --enable-optimizations && \
    make altinstall && \
    cd .. && \
    rm -rf Python-3.10.14 Python-3.10.14.tgz && \
    python3.10 -m pip install --upgrade pip && \
    python3.10 -m pip install pytest && \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -SL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN if [ -L /usr/bin/python3 ]; then rm /usr/bin/python3; fi && \
    ln -s /usr/local/bin/python3.10 /usr/bin/python3 && \
    if [ -L /usr/bin/python ]; then rm /usr/bin/python; fi && \
    ln -s /usr/local/bin/python3.10 /usr/bin/python

# Add custom entrypoint script
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Install requirements
COPY ./requirements.txt /requirements.txt
RUN pip install wheel && pip install -r /requirements.txt