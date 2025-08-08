echo "Setting up NewPipe environment"
# install Python dependencies for availability tests
pip3 install --break-system-packages -q -r requirements.txt

# First set up the environment (this will reboot emulator with writable system)
./setup_env.sh
# Then install NewPipe (after emulator is properly configured)
./setup_app.sh

echo "NewPipe environment setup complete."