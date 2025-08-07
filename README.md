# mobilecybench

## MCP Interaction

First, obtain an ngrok token by going to https://ngrok.com, signing up, and then copying the ngrok token to mcp/ngrok.yml next to the authtoken: field. Your file should look like: 

version: 2
authtoken: {YOUR_AUTHTOKEN_HERE}
tunnels:
  web:
    proto: http
    addr: 8000


Then, run the following commands to start the emulator, mcp, and kali containers: 

    ```bash
    ./setup.sh
    ./start_emulator.sh
    docker-compose up --build
   ```

In addition, set up a python runtime either by creating a virtual environment, installing everything in requirements.txt, and setting the environment variable OPENAI_API_KEY to your OpenAI api key. 

Finally, you can start interacting with the agent via running 

    ```bash
   python test_ai_interaction.py 
   ```
The agent will be able to access the kali container as well as your android emulator with its corresponding set of possible tools. 

## Local Development Setup

### Quick Start

1. **Run the setup script:**

   ```bash
   bash setup.sh
   ```

2. **Start the emulator:**

   ```bash
   ./start_emulator.sh
   ```

3. **Verify setup:**
   ```bash
   ./check_device.sh
   ```

That's it! The emulator is ready for testing.

### What the Setup Script Does

- Downloads and installs Android SDK Command Line Tools
- Creates an Android 9.0 (API 28) emulator
- Sets up environment variables automatically
- Creates helper scripts for common tasks

### Helper Scripts

| Script              | Description                          |
| ------------------- | ------------------------------------ |
| `start_emulator.sh` | Start the Android emulator           |
| `stop_emulator.sh`  | Stop the Android emulator            |
| `check_device.sh`   | Check if device is ready for testing |

### Requirements

- **Linux/macOS/Windows** (script auto-detects)
- **8GB+ RAM** (4GB for emulator + 4GB for host)
- **10GB+ free disk space**
- **Hardware virtualization enabled** (Intel VT-x/AMD-V)

### Troubleshooting

#### Emulator won't start

- Ensure hardware virtualization is enabled in BIOS
- Check available RAM: `free -h` (Linux) or Activity Monitor (macOS)

#### ADB not found

- Restart terminal after setup
- Manually source profile: `source ~/.bashrc`

#### Permission denied

- Make scripts executable: `chmod +x *.sh`

### Directory Structure

```
├── setup.sh              # Main setup script
├── start_emulator.sh      # Start emulator
├── stop_emulator.sh       # Stop emulator
├── check_device.sh        # Device status check
└── setup.log             # Setup log file
```

### Advanced Configuration

The emulator is configured with:

- **Device:** Pixel 2 profile
- **Android:** 9.0 (API 28) with Google APIs
- **RAM:** 2GB
- **Architecture:** x86_64
- **GPU:** Hardware acceleration enabled

To modify settings, edit the AVD configuration in:
`~/.android/avd/MobileBenchmark_API28.avd/config.ini`

### Support

If you encounter issues:

1. Check `setup.log` for error details
2. Ensure system requirements are met
3. Try running setup script again

## Adding Target App Repo

We maintain isolated copies of target repositories in the **cy-suite** organization.

NOTE: If you do not have access to the **cy-suite** repo, please reach out to a senior member on the core team with the link to the repo you want to add. They will execute the following steps for you. Once the repo has been added, skip to the next section.

1. Navigate to [cy-suite](https://github.com/cy-suite) and select the green **New** button.
2. Select **Import a repository**.
3. Enter the URL for the app repo (the same URL you use with the `git clone` command).
4. Select **owner** to **cy-suite**.
5. Make sure **Private** is selected.
