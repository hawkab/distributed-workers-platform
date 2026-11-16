# Put only nonsecret vendor JDK21 and Android build-tools36.0.0 in toolchain/.
# Never copy a home directory, runner registration, or signing material.
FROM docker.gitea.com/runner-images@sha256:139605d4a6ab61e48dfd7687b11184881c2d7fcf06bf739e9cadb34f73deb51d
USER root
COPY toolchain/jdk21 /opt/java21
COPY toolchain/build-tools/36.0.0 /opt/android-sdk/build-tools/36.0.0
ENV JAVA_HOME=/opt/java21 ANDROID_HOME=/opt/android-sdk ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=/opt/java21/bin:/opt/android-sdk/build-tools/36.0.0:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
