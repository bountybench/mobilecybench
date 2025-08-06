cd ../codebase
git fetch origin
git checkout f59e2d5478125862101c3470e4cb1c7271e3498f

./gradlew installGenericDebug || { echo "Gradle build failed"; exit 1; }

echo "Added Talk app!"

cd ../app-setup
chmod +x emulator_connection.sh
./emulator_connection.sh