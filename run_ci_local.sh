#!/bin/bash

# Define color codes
GREEN="\033[1;32m"
RED="\033[1;31m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RESET="\033[0m"

# Define message prefixes
INFO="${CYAN}[INFO]${RESET}"
SUCCESS="${GREEN}[SUCCESS]${RESET}"
ERROR="${RED}[ERROR]${RESET}"
WARNING="${YELLOW}[WARNING]${RESET}"

print_header() {
    local color="$1"
    local message="$2"
    echo -e "${color}========== ${message} ==========${RESET}"
}

execute_if_exists() {
  local script_path="$1"
  if [ -f "$script_path" ]; then
    echo "Executing $script_path"
    bash "$script_path"
    return $?
  else
    echo "$script_path not found, skipping."
    return 0
  fi
}

RUN_PATCH=false

# Check if argument was provided
if [ -z "$1" ]; then
    echo "Usage: $0 <dir> [--patch]"
    echo "Example: $0 basecamp"
    exit 1
fi

DIR="$1"
shift

# Loop through arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --patch) RUN_PATCH=true ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

# setup according to the sdk value from metadata.json
metadata="$DIR/metadata.json"
if [ ! -f $metadata ]; then
    echo "${ERROR} $metadata not found"
    exit 1
fi

sdk=$(jq -r '.sdk' $metadata)
if [ "$?" -ne 0 ] || [ "$sdk" = "null" ] || [ -z "$sdk" ]; then
    echo "${ERROR} Could not extract SDK value from $metadata. Use default."
    ./setup.sh
else 
    echo "SDK value: $sdk"
    ./setup.sh --sdk "$sdk"
fi

vuln_version=$(jq -r '.app_vulnerable_version' "$metadata")
if [ $? -ne 0 ] || [ "$vuln_version" = "null" ] || [ -z "$vuln_version" ]; then
    echo "${ERROR} Could not extract vulnerable version of app from $metadata."
    exit 1
fi

patched_version=$(jq -r '.app_patched_version' "$metadata")
if [ $? -ne 0 ] || [ "$patched_version" = "null" ] || [ -z "$patched_version" ]; then
    echo "${ERROR} Could not extract patched version of app from $metadata."
    exit 1
fi

# checking to see if exploit and verify exist
cd $DIR
exploit_script="exploit.sh" 
verify_script="verify.sh"
setup_app_script="setup_app.sh"

if [[ -z "$exploit_script" ]]; then
    print_header "$RED" "ERROR"
    echo -e "${ERROR} Could not find exploit.sh"
    exit 1
fi

if [[ -z "$verify_script" ]]; then
    print_header "$RED" "ERROR"
    echo -e "${ERROR} Could not find verify.sh"
    exit 1
fi

if [[ -z "$setup_app_script" ]]; then
    print_header "$RED" "ERROR"
    echo -e "${ERROR} Could not find setup_app.sh"
    exit 1
fi

print_header "$CYAN" "CHECKING IF NECESSARY SCRIPTS EXIST"
echo -e "${SUCCESS} Found exploit script at: ${exploit_script}"
echo -e "${SUCCESS} Found verify script at: ${verify_script}"
echo -e "${SUCCESS} Found setup app script at: ${setup_app_script}"


# starting emulator
print_header "$CYAN" "STARTING EMULATOR"
cd ..
./start_emulator.sh > /dev/null 2>&1 
sleep 30
cd $DIR

# running setup app with vulnerable version
print_header "$CYAN" "SETTING UP THE APP"
./setup_app.sh "$vuln_version"

# executing exploit flow
print_header "$CYAN" "RUNNING VERIFY SCRIPT BEFORE EXPLOIT"
initial_log=$(./$verify_script)
initial_status=$?

if [[ ${initial_status} -eq 0 ]]; then
    print_header "$RED" "ERROR"
    echo -e "${ERROR} Running verify script before exploit should fail (return 1)"
    echo -e "${ERROR} ${initial_log}"
    exit 1
fi

echo -e "${SUCCESS} Initial verification failed as expected. Running exploit.sh..."
print_header "$CYAN" "EXPLOIT"
./$exploit_script
sleep 5

print_header "$CYAN" "RUNNING VERIFY SCRIPT AFTER EXPLOIT"
final_log=$(./$verify_script)
final_status=$?

if [[ ${final_status} -ne 0 ]]; then
    print_header "$RED" "ERROR"
    echo -e "${ERROR} Verify script after exploit should succeed (return zero) after exploit but it returned ${final_status}"
    print_header "$CYAN" "VERIFY SCRIPT LOG"
    echo -e "${INFO} ${final_log}\n"
    exit 1
fi

print_header "$GREEN" "EXPLOIT MODE SUCCEEDED"
echo -e "${SUCCESS} Verify script after exploit completed successfully."


# stop the emulator
print_header "$CYAN" "STOPPING EMULATOR"
cd ..
./stop_emulator.sh
cd $DIR


if [[ "$RUN_PATCH" == true ]]; then
    print_header "$CYAN" "APPLYING PATCH"

    # starting emulator
    print_header "$CYAN" "STARTING EMULATOR"
    cd ..
    ./start_emulator.sh > /dev/null 2>&1 
    sleep 30
    cd $DIR

    # running setup app with patched version
    print_header "$CYAN" "SETTING UP THE APP"
    ./setup_app.sh "$patched_version"

    # executing exploit flow
    print_header "$CYAN" "RUNNING VERIFY SCRIPT BEFORE EXPLOIT"
    initial_log=$(./$verify_script)
    initial_status=$?

    if [[ ${initial_status} -eq 0 ]]; then
        print_header "$RED" "ERROR"
        echo -e "${ERROR} Running verify script before exploit should fail (return 1)"
        echo -e "${ERROR} ${initial_log}"
        exit 1
    fi

    echo -e "${SUCCESS} Initial verification failed as expected. Running exploit.sh..."
    print_header "$CYAN" "EXPLOIT"
    ./$exploit_script
    sleep 5

    print_header "$CYAN" "RUNNING VERIFY SCRIPT AFTER EXPLOIT"
    final_log=$(./$verify_script)
    final_status=$?

    if [[ ${final_status} -eq 0 ]]; then
        print_header "$RED" "ERROR"
        echo -e "${ERROR} Verify script should fail (return 1) after patch, but it returned ${final_status}"
        echo -e "${ERROR} ========= Error log ========= \n\n ${final_log}"
        exit 1
    fi

    print_header "$GREEN" "PATCH MODE SUCCEEDED"
    echo -e "${SUCCESS} Patch completed successfully."

    # stop the emulator
    print_header "$CYAN" "STOPPING EMULATOR"
    cd ..
    ./stop_emulator.sh
    cd $DIR
fi