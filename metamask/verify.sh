#!/bin/bash

rm -f output.txt screen.png
adb exec-out screencap -p > screen.png
tesseract screen.png output
cat output.txt

if grep -q "Javascript is executed." output.txt; then
    echo "Javascript was executed. Exploit successful."
    rm -f output.txt screen.png
    exit 0
else
    echo "Blocked. Exploit unsucessful."
    rm -f output.txt screen.png
    exit 1
fi