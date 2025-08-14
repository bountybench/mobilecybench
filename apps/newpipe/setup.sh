echo "Setting up NewPipe environment"
# install Python dependencies for availability tests
pip3 install --break-system-packages -q -r requirements.txt

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

# First set up the environment (this will reboot emulator with writable system)
"$SCRIPT_DIR/setup_env.sh"
# Then install NewPipe (after emulator is properly configured)
"$SCRIPT_DIR/setup_app.sh"

echo "NewPipe environment setup complete."