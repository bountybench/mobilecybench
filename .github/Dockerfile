FROM cybench/kali-linux-base:latest

# Install common tools, Python 3.9, Docker, and pytest
RUN apt-get update && \
    apt-get install -y \
    docker.io \
    curl \
    docker-compose \
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
    git && \
    wget https://www.python.org/ftp/python/3.9.7/Python-3.9.7.tgz && \
    tar xzf Python-3.9.7.tgz && \
    cd Python-3.9.7 && \
    ./configure --enable-optimizations && \
    make altinstall && \
    cd .. && \
    rm -rf Python-3.9.7 Python-3.9.7.tgz && \
    python3.9 -m pip install --upgrade pip && \
    python3.9 -m pip install pytest docker-compose && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN if [ -L /usr/bin/python3 ]; then rm /usr/bin/python3; fi && \
    ln -s /usr/local/bin/python3.9 /usr/bin/python3 && \
    if [ -L /usr/bin/python ]; then rm /usr/bin/python; fi && \
    ln -s /usr/local/bin/python3.9 /usr/bin/python

RUN apt-get update && \
    apt-get install -y android-tools-adb android-tools-fastboot

# Add this before the COPY command to debug
COPY . /build_context
RUN echo "Listing files in /build_context:" && ls -la /build_context

# Add custom entrypoint script
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Install requirements
COPY ./requirements.txt /requirements.txt
RUN /venv/bin/pip install --upgrade pip
RUN /venv/bin/pip install wheel && /venv/bin/pip install -r /requirements.txt