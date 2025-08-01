
## TODOs!

1. Finish review for android_probes.py
2. Check databases and learn what they store
3. Find new files (particularly) xml file and log file in database for POC
4. Find newly written files as another POC.
5. check the server side



# tested vulnerabile version: oc-android-2.21.1


Main Vulnerability:

* a path traversal vulnerability in the ownCloud Android application
* allowing for bypasses that could lead to information disclosure and arbitrary file writes
* The flaw allows an attacker to manipulate file paths when the application receives files from an external source, thereby reading from or writing to unintended locations within the application's internal storage.
* **Application's internal storage** might store settings, logs, and other metadata that should be only visible for the app itself and of course root.

* User Interaction: Required (UI:R) in Vector


* **Information Disclosure** (C:L - Confidentiality: Low): An attacker can craft a path traversal payload to trick the ownCloud app into reading its own internal files (e.g., configuration files, session tokens, or even the local SQLite databases) and uploading them to the attacker-controlled ownCloud server.

* Arbitrary File Write (I:L - Integrity: Low): An attacker can use a path traversal payload to write a file to an arbitrary location within the app's data directory. While the advisory notes this is limited to plain text files with a .txt extension, this could still be used to overwrite critical files, potentially leading to a denial of service, configuration manipulation, or chaining with other vulnerabilities.

* Information Disclosure: An attacker can craft a malicious filename that points to a sensitive file within the ownCloud app's private data directory. For example, a filename like ../../databases/owncloud_database could be used. When the user shares content to the ownCloud app, the app would inadvertently read this internal database file instead of the shared content and then proceed to upload it to the user's (and thus, the attacker's) ownCloud server. This exfiltrates the contents of the database.


* Arbitrary File Write: Similarly, an attacker can specify a destination path that traverses out of the intended directory. When the app writes the shared content to a file, it will be placed in the attacker-specified location within the app's writable data directory. The CVE description notes this is limited to writing plain text files with a .txt extension. Despite this limitation, this could be used to overwrite configuration files, inject content into logs, or potentially create files in locations that could trigger further adverse behavior in the application.

* Path Traversal (CVE-2023-24804):

Normal Operation: You use another app (like a photo gallery) to "Share" a picture with ownCloud to upload it. The gallery app sends a message (an "Intent") to ownCloud with the location of the picture.

The Exploit: A malicious app sends a similar "Share" Intent to ownCloud. However, instead of a valid filename, it provides a malicious path like ../../databases/owncloud.db. Because the vulnerable ownCloud app fails to properly validate this filename, it follows the path and reads its own internal database file, thinking it's the file you wanted to share. It then proceeds to upload this sensitive database to the server, which the attacker controls.   

The Scope Change: The malicious app (which has no permission to read ownCloud's database) has successfully commanded the ownCloud app to use its own permissions to read and exfiltrate its own data.
