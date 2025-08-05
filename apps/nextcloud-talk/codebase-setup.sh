if [ ! -d "codebase" ]; then
    mkdir codebase
fi 

cd codebase
# git submodule update --init --recursive

if [ ! -d "talk-android" ]; then
    git submodule add https://github.com/nextcloud/talk-android talk-android
fi

git submodule update --init talk-android
sleep 10

cd talk-android
git fetch origin
git checkout f59e2d5478125862101c3470e4cb1c7271e3498f #commit of relevant version
./gradlew installGenericDebug || { echo "Gradle build failed"; exit 1; }

echo "Added Talk app!"