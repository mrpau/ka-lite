#!/usr/bin/env bash

set -euo pipefail

PARENT_PATH=$(pwd)
KALITE_DOCKER_PATH="$PARENT_PATH/windows_installer_docker_build"
KALITE_WINDOWS_PATH="$KALITE_DOCKER_PATH/ka-lite-installers/windows"
STEP=1
STEPS=5


# Download artifacts to dist/
echo "$STEP of $STEPS"
mkdir -p dist
buildkite-agent artifact download 'dist/*.whl' dist/
make dockerwriteversion
cat "$PARENT_PATH/kalite/VERSION"
((STEP++))
echo "$STEP of $STEPS"
# Clone KA-Lite windows installer and download content pack
cd $KALITE_DOCKER_PATH
git clone https://github.com/learningequality/ka-lite-installers.git && cd ka-lite-installers && git checkout 0.17.x
cd $KALITE_WINDOWS_PATH && wget http://pantry.learningequality.org/downloads/ka-lite/0.17/content/contentpacks/en.zip
((STEP++))

echo "$STEP of $STEPS"
# Copy kalite whl files to kalite windows installer path
COPY_CMD="cp $PARENT_PATH/dist/*.whl $KALITE_WINDOWS_PATH"
$COPY_CMD

if [ $? -ne 0 ]; then
    echo "... Abort! Error running $COPY_CMD"
    exit 1
fi
((STEP++))

echo "$STEP of $STEPS"
KALITE_BUILD_VERSION=$(cat $PARENT_PATH/kalite/VERSION)

# Build KA-Lite windows installer docker image
cd $KALITE_DOCKER_PATH
echo "Docker Path: $KALITE_DOCKER_PATH"
ls -l $KALITE_DOCKER_PATH
if [ ! -f "$PARENT_PATH/windows_installer_docker_build/Dockerfile" ]; then
    echo "Dockerifle does not exist!"
    exit 1
fi

DOCKER_BUILD_CMD="docker image build -t $KALITE_BUILD_VERSION-build ."
$DOCKER_BUILD_CMD

if [ $? -ne 0 ]; then
    echo "... Abort! Error running $DOCKER_BUILD_CMD."
    exit 1
fi

INSTALLER_PATH="$KALITE_DOCKER_PATH/installer"
mkdir -p $INSTALLER_PATH

# Run KA-Lite windows installer docker image.
DOCKER_RUN_CMD="docker run -v $INSTALLER_PATH:/installer/ $KALITE_BUILD_VERSION-build"
$DOCKER_RUN_CMD

if [ $? -ne 0 ]; then
    echo "... Abort! Error running $DOCKER_RUN_CMD."
    exit 1
fi
cd $KALITE_DOCKER_PATH
buildkite-agent artifact upload './installer/*.exe'