FROM --platform=linux/amd64 ubuntu:20.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Java 11 and build tools with better repository handling
RUN apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    openjdk-11-jdk \
    wget \
    unzip \
    make \
    build-essential \
    ca-certificates \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Set environment variables
ENV ANDROID_HOME=/opt/android-sdk
ENV PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

# Download and install Android SDK
RUN mkdir -p $ANDROID_HOME/cmdline-tools && \
    cd $ANDROID_HOME/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-8512546_latest.zip && \
    unzip commandlinetools-linux-8512546_latest.zip && \
    mv cmdline-tools latest && \
    rm commandlinetools-linux-8512546_latest.zip

# Accept licenses and install required SDK components
RUN yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses && \
    $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
    "platform-tools" \
    "platforms;android-30" \
    "build-tools;30.0.3"

# Download and install specific NDK version (21.4.7075529 = NDK r21e)
# Gradle expects: $ANDROID_HOME/ndk/21.4.7075529/
RUN cd $ANDROID_HOME && \
    wget -q https://dl.google.com/android/repository/android-ndk-r21e-linux-x86_64.zip && \
    unzip android-ndk-r21e-linux-x86_64.zip && \
    mkdir -p ndk && \
    mv android-ndk-r21e ndk/21.4.7075529 && \
    rm android-ndk-r21e-linux-x86_64.zip

# Set NDK environment variables (only the essential ones)
ENV ANDROID_NDK_HOME=$ANDROID_HOME/ndk/21.4.7075529
ENV JITPACK_NDK_VERSION=21.4.7075529

# Override build configuration to target single architecture (arm64-v8a only)
ENV GRADLE_OPTS="-Dandroid.injected.abi=arm64-v8a"

# Set working directory
WORKDIR /app

# Pre-download Gradle to avoid SSL issues during build
RUN mkdir -p ~/.gradle/wrapper/dists/gradle-7.1-all && \
    cd ~/.gradle/wrapper/dists/gradle-7.1-all && \
    wget -q --retry-connrefused --tries=3 https://services.gradle.org/distributions/gradle-7.1-all.zip || \
    echo "Gradle download failed, will try during build"

# Copy the build script
COPY build_termux.sh /app/
RUN chmod +x /app/build_termux.sh

# Keep container running for manual execution
CMD ["tail", "-f", "/dev/null"]

