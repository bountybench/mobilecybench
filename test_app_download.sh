# #! /bin/bash
#Demo here: https://youtu.be/UgP33ajMcl8

echo "Enter github file path"
read github_file_path

echo "Enter app name (your best guess, we'll try to find the application id!)"
read app_name

echo $github_file_path

#startup of emulator 
chmod +x *.sh

./setup.sh
source ~/.bashrc
./start_emulator.sh

devices=$(adb devices)

if [ -z "$devices" ]; then
    echo "PROBLEM: No devices found"
    exit 1
fi

mkdir -p testing_app
cd testing_app
git clone --recurse-submodules $github_file_path

#The following file paths should be filled in with the specific directory to your app!
cd haven

./gradlew clean
./gradlew installDebug
./gradlew assembleDebug

# cd app-thunderbird

package_name=$(adb shell pm list packages -3 | grep $app_name | sed 's/package://')
package_path=$(adb shell cmd package resolve-activity --brief $package_name | tail -n 1)

echo "package path"
echo $package_path

adb shell am start -n $package_path