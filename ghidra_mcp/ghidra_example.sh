#!/bin/bash
echo "Ghidra test"

# Set default Ghidra installation directory
export GHIDRA_INSTALL_DIR=${GHIDRA_INSTALL_DIR:-/opt/ghidra}

cat > /tmp/hello.c << 'EOF'
#include <stdio.h>

int main() {
    printf("Hello World!\n");
    return 0;
}
EOF

echo "Compiling test program..."
gcc -o /tmp/hello /tmp/hello.c
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to compile test program"
    exit 1
fi

echo "Test binary created: /tmp/hello"
ls -l /tmp/hello

# Make Ghidra project directory
PROJECT_DIR="/tmp/ghidra_test_project"
mkdir -p $PROJECT_DIR

echo "Run Ghidra headless analysis..."
$GHIDRA_INSTALL_DIR/support/analyzeHeadless \
    $PROJECT_DIR TestProject \
    -import /tmp/hello \
    -scriptPath $GHIDRA_INSTALL_DIR/Ghidra/Features/Decompiler/ghidra_scripts \
    -overwrite \
    -noanalysis

echo "Ghidra test analysis complete"
