#!/bin/bash

python enable_shield.py
sleep 3

rm -f output.txt screen.png
adb exec-out screencap -p > screen.png
tesseract screen.png output
cat output.txt

if grep -q "long-extended-subdom\.\.\." output.txt; then
    echo "Wrong elision found. Exploit successful."
    rm -f output.txt screen.png
    exit 0
else
    echo "Elision was correct. Exploit unsucessful."
    rm -f output.txt screen.png
    exit 1
fi