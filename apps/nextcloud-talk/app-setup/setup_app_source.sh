cd ../codebase

./gradlew installGenericDebug || { echo "Gradle build failed"; exit 1; }

echo "Added Talk app!"

cd ../app-setup
chmod +x emulator_connection.sh
./emulator_connection.sh